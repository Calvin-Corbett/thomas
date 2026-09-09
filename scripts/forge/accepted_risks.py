#!/usr/bin/env python3
"""The accepted-risks registry: an accepted risk has an owner, a date, and an
expiry -- not a shrug.

WHY THIS EXISTS: the closure gate (``scripts/forge/gates/problem_closure_gate.py``,
phase 1.5 Task 2) refuses to let an incident resolve unless its record points
at something that actually resolves -- a landed gate, a graveyard tombstone,
or an owner-accepted risk. Without a place to put that acceptance, "we know
about this and we're not fixing it" has nowhere honest to live, and it either
gets fabricated as a fake fix or drops silently. This module is that place:
every accepted risk has an owner, the day it was reviewed, and the day it
stops being acceptable -- never an unowned, undated, un-expiring shrug.

FIELD SHAPE: ``owner``/``reason``/``reviewed_on``/``expires_on`` mirrors the
precedent already enforced elsewhere in this repo,
``docs/security/mutating_route_policy_exceptions.json`` (the mutating-route
authz/csrf exception list) -- an accepted risk, wherever it is recorded here,
carries the same four facts: who signed off, why, when they looked at it,
and when that sign-off runs out.

THE HONESTY CONTRACT (identical shape to ``scripts/forge/graveyard.py``'s,
this repo's documented disease is absence-reads-as-clean, per this program's
own repeated audits):
  * a MISSING ``docs/ops/accepted_risks.json`` is legitimately "nothing has
    been accepted yet" -- ``load()`` returns an empty ``Risks`` and prints a
    NOTE so the absence is visible, never silent.
  * a file that EXISTS but fails to parse, is the wrong shape, or contains a
    record missing a required key is a completely different situation -- the
    record is broken, not empty. ``load()`` raises ``SystemExit`` naming the
    file. It never falls back to an empty registry, because an empty
    registry reads as "nothing is accepted" and a gate acting on that lie
    would refuse every closure that legitimately rests on an accepted risk.

EXPIRY BOUNDARY SEMANTICS match ``scripts/forge/gates/monolith_guard.py``'s
waiver-expiry check exactly (~monolith_guard.py:429,
``elif expires_date < date.today():``): a risk is expired only once its
``expires_on`` date is STRICTLY before "today" -- the expiry day itself is
still an accepted risk, valid through its own last day, not already lapsed
at its first moment. ``Risks.is_expired`` takes the same comparison operator
so a risk recorded here and a waiver checked by ``monolith_guard`` never
disagree about what "expired" means on the boundary date.

APPEND-ONLY, AND SAFE UNDER CONCURRENT WRITERS: copied byte-for-byte from
the graveyard's pattern. ``record_risk`` only ever adds a new record to the
end of the list; nothing already on disk is ever edited or removed. The
read-modify-write cycle is wrapped in an exclusive file lock
(``docs/ops/accepted_risks.json.lock``, ``os.O_CREAT | os.O_EXCL`` --
this repo's established lockfile pattern, see
``scripts/crew/workboard/claim_utils.py:_file_lock`` and
``scripts/forge/graveyard.py:_locked``), and every write goes to a temp file
in the same directory followed by ``os.replace`` (atomic on the same
volume, including Windows) so a reader never observes a half-written file
and a crash mid-write never corrupts the original. A lock that cannot be
acquired within the bounded retry window is a loud ``SystemExit`` naming the
lock file -- never a silent skip of the record.

CLI: ``python scripts/forge/accepted_risks.py record|list [...]`` -- see
``main()`` for arguments; ``list --json`` is the machine-readable surface
for other tooling (the closure gate reads through ``load()`` directly, but
the CLI mirrors the graveyard's surface for humans and scripts).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]

_RISKS_RELATIVE = Path("docs") / "ops" / "accepted_risks.json"

_REQUIRED_RECORD_KEYS = ("id", "owner", "reason", "reviewed_on", "expires_on", "refs")

# Lock knobs. Read from the module namespace at call time (not bound as
# default arguments) so a test can `monkeypatch.setattr(accepted_risks,
# "_LOCK_...", ...)` to shrink the retry window without waiting out the real
# timeout. Values match graveyard.py's.
_LOCK_MAX_RETRIES = 20
_LOCK_RETRY_INTERVAL = 0.25  # seconds
_LOCK_STALE_SECONDS = 30.0


@dataclass(frozen=True)
class Risks:
    """An immutable, in-memory view of every accepted risk on record.

    ``records`` is every record in the file, in append order (oldest
    first). Consumers who need more than ``get``/``is_expired`` can read
    ``records`` directly.
    """

    records: tuple[dict[str, Any], ...]

    def get(self, risk_id: str) -> dict[str, Any] | None:
        """The record with this id, or ``None`` if no such risk was ever
        recorded. Never raises -- a missing id is a normal, expected
        outcome for a caller checking an arbitrary closure reference."""
        return next((r for r in self.records if r["id"] == risk_id), None)

    def is_expired(self, risk_id: str, today: dt.date | str | None = None) -> bool | None:
        """Whether the risk has lapsed as of ``today`` (default: the real
        current date).

        Returns ``None`` -- never ``False`` -- when ``risk_id`` does not
        resolve to any record. A caller that conflated "never accepted"
        with "accepted and still valid" would let an unresolvable closure
        reference through; ``None`` forces the caller to handle "this risk
        does not exist" as its own case, distinct from "not expired yet".

        Boundary semantics match ``monolith_guard.py``'s waiver-expiry
        check (~monolith_guard.py:429): expired iff ``expires_on`` is
        STRICTLY before ``today`` -- the expiry day itself still counts as
        accepted.
        """
        record = self.get(risk_id)
        if record is None:
            return None
        as_of = _coerce_date(today) if today is not None else dt.date.today()
        expires_date = dt.date.fromisoformat(record["expires_on"])
        return expires_date < as_of


def _coerce_date(value: dt.date | str) -> dt.date:
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def _risks_path(repo_root: Path) -> Path:
    return Path(repo_root) / _RISKS_RELATIVE


def _lock_path(repo_root: Path) -> Path:
    path = _risks_path(repo_root)
    return path.with_name(path.name + ".lock")


def _today() -> str:
    return dt.date.today().isoformat()


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "record"


def _require(value: str, field_name: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"accepted_risks: `{field_name}` must not be empty")
    return value


def _validate_expires_on(expires_on: str) -> str:
    """Validate ``expires_on`` is a real ``YYYY-MM-DD`` date that is today or
    in the future, and return it normalized. Loud on garbage: an unparseable
    string or an already-past date both raise ``ValueError`` -- an accepted
    risk with a meaningless or already-lapsed expiry is worse than no
    acceptance at all, because it reads as covered when it is not."""
    text = str(expires_on or "").strip()
    if not text:
        raise ValueError("accepted_risks: `expires_on` must not be empty")
    try:
        expires_date = dt.date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"accepted_risks: `expires_on` {text!r} is not a valid YYYY-MM-DD date") from exc
    if expires_date < dt.date.today():
        raise ValueError(
            f"accepted_risks: `expires_on` {text!r} is already in the past -- an accepted risk must "
            "expire today or later, never a shrug that was already stale when it was written down"
        )
    return expires_date.isoformat()


def load(repo_root: Path) -> Risks:
    """Read the accepted-risks registry, or raise ``SystemExit`` if it
    exists but is broken.

    See the module docstring's "honesty contract": missing is empty (with a
    printed NOTE); malformed -- bad JSON, wrong top-level shape, or any
    record missing a required key -- is a loud, hard failure naming the
    file.
    """
    path = _risks_path(repo_root)
    if not path.exists():
        # Mirrors graveyard.py's I5 fix: this NOTE must never land on stdout
        # -- `accepted_risks.py list --json` is a machine-readable surface,
        # and a NOTE line ahead of the JSON payload would break a
        # json.loads() caller. stderr keeps the honesty contract (absence
        # is stated, not silent) without contaminating the one output
        # stream a JSON consumer actually reads.
        print(
            f"NOTE: {path} does not exist -- starting from an empty accepted-risks registry "
            "(nothing recorded yet).",
            file=sys.stderr,
        )
        return Risks(records=())

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"accepted_risks: cannot read {path}: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"accepted_risks: {path} is malformed JSON ({exc}) -- refusing to treat this as an empty registry"
        ) from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise SystemExit(
            f"accepted_risks: {path} does not have the expected shape "
            '(top-level object with a "records" list) -- refusing to treat this as an empty registry'
        )

    records = payload["records"]
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise SystemExit(f"accepted_risks: {path} record #{index} is not a JSON object -- malformed")
        missing = [key for key in _REQUIRED_RECORD_KEYS if key not in record]
        if missing:
            raise SystemExit(
                f"accepted_risks: {path} record #{index} (id={record.get('id')!r}) is missing required "
                f"key(s) {missing} -- malformed, refusing to treat this as an empty registry"
            )

    return Risks(records=tuple(records))


@contextmanager
def _locked(repo_root: Path):
    """Exclusive lock around an accepted-risks read-modify-write cycle.

    Identical in shape to ``graveyard.py:_locked`` (itself mirroring
    ``scripts/crew/workboard/claim_utils.py:_file_lock``): an
    ``O_CREAT | O_EXCL`` lockfile, bounded retry, and a stale-lock break so
    a crashed holder cannot wedge the registry shut forever. A timeout here
    is a loud ``SystemExit`` naming the lock file -- this registry's whole
    purpose is to never lose an acceptance record, so a caller that cannot
    get the lock must not silently skip writing.
    """
    lock_path = _lock_path(repo_root)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    max_retries = _LOCK_MAX_RETRIES
    retry_interval = _LOCK_RETRY_INTERVAL
    stale_after = _LOCK_STALE_SECONDS

    fd: int | None = None
    attempts = 0
    while fd is None:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except FileNotFoundError:
                age = 0.0
            if age > stale_after:
                with suppress(FileNotFoundError):
                    lock_path.unlink()
                continue
            attempts += 1
            if attempts > max_retries:
                raise SystemExit(
                    f"accepted_risks: timed out waiting for lock {lock_path} "
                    f"(held by another process for at least {age:.1f}s) -- refusing to write unlocked"
                )
            time.sleep(retry_interval)

    try:
        yield
    finally:
        os.close(fd)
        with suppress(FileNotFoundError):
            lock_path.unlink()


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` to ``path`` via temp-file-then-replace.

    ``os.replace`` is atomic on the same volume (true on Windows too, unlike
    plain rename-over-existing-file on some platforms): a reader either sees
    the old file or the new one, never a partial write. If the replace step
    itself fails (disk full, permissions, a crash mid-call), the temp file
    is removed and the exception propagates -- the original file is
    untouched because it was never opened for writing in the first place.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.replace(str(tmp), str(path))
    except OSError:
        with suppress(FileNotFoundError):
            tmp.unlink()
        raise


def _next_id(records: list[dict[str, Any]], reason: str, *, today: str | None = None) -> str:
    date_str = today or _today()
    slug = _slugify(reason)
    prefix = f"{date_str}-{slug}-"
    existing_ids = {r["id"] for r in records}
    n = 1
    while f"{prefix}{n}" in existing_ids:
        n += 1
    return f"{prefix}{n}"


def record_risk(repo_root: Path, owner: str, reason: str, expires_on: str, refs: str | None = None) -> str:
    """Append a new accepted-risk record and return its id.

    ``owner`` and ``reason`` must be non-empty; ``expires_on`` must be a
    real, future-or-today ``YYYY-MM-DD`` date (see ``_validate_expires_on``)
    -- all three checks run BEFORE the lock is taken, so a bad call never
    even contends for the write lock. ``reviewed_on`` is always set to
    today, at record time -- an accepted risk is reviewed the moment it is
    accepted, not backdated or left blank. The read-modify-write is
    lock-protected: two callers racing to record a risk each see a
    consistent prior-state read and neither write clobbers the other's
    record.
    """
    owner = _require(owner, "owner")
    reason = _require(reason, "reason")
    expires_on = _validate_expires_on(expires_on)

    path = _risks_path(repo_root)
    with _locked(repo_root):
        records = list(load(repo_root).records)
        record_id = _next_id(records, reason)
        records.append(
            {
                "id": record_id,
                "owner": owner,
                "reason": reason,
                "reviewed_on": _today(),
                "expires_on": expires_on,
                "refs": refs,
            }
        )
        _atomic_write(path, {"version": 1, "records": records})
    return record_id


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli_record(args: argparse.Namespace) -> int:
    record_id = record_risk(Path(args.repo_root), args.owner, args.reason, args.expires_on, args.refs)
    print(record_id)
    return 0


def _cli_list(args: argparse.Namespace) -> int:
    risks = load(Path(args.repo_root))
    if args.json:
        print(json.dumps({"version": 1, "records": list(risks.records)}, ensure_ascii=False, indent=2))
        return 0
    if not risks.records:
        print("accepted_risks: no records.")
        return 0
    for record in risks.records:
        print(f"{record['id']}  owner={record['owner']:20s} expires_on={record['expires_on']}  {record['reason']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(_REPO_ROOT), help="Repository root path.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_record = sub.add_parser("record", help="Record an accepted risk.")
    p_record.add_argument("--owner", required=True)
    p_record.add_argument("--reason", required=True)
    p_record.add_argument("--expires-on", required=True, help="YYYY-MM-DD, today or later.")
    p_record.add_argument("--refs", default=None)
    p_record.set_defaults(func=_cli_record)

    p_list = sub.add_parser("list", help="List every record.")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=_cli_list)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
