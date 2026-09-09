#!/usr/bin/env python3
"""The graveyard: deletion becomes recorded intent, in a form a gate can read.

WHY THIS EXISTS: a three-way merge cannot tell a deliberate deletion from an
absence -- the missing file looks identical whether it was removed on purpose
or just never existed on this branch. A dead branch name looks identical to
one nobody has used yet. Without a record, both come back on the next merge
or push with no error at all. This module is that record: every deliberate
death of a branch or a file is appended here, and downstream gates
(``merge_resurrection_gate.py``, ``dead_ref_gate.py``) refuse to let the dead
thing quietly reappear unless a resurrection was explicitly approved.

THE HONESTY CONTRACT (this repo's documented disease is absence-reads-as-
clean, per this program's own repeated audits):
  * a MISSING ``docs/ops/graveyard.json`` is legitimately "nothing has been
    recorded yet" -- ``load()`` returns an empty Graveyard and prints a NOTE
    so the absence is visible, never silent.
  * a graveyard.json that EXISTS but fails to parse, is the wrong shape, or
    contains a record missing a required key is a completely different
    situation -- it means the record is broken, not empty. ``load()`` raises
    SystemExit naming the file. It never falls back to an empty graveyard,
    because an empty graveyard reads as "nothing is dead" and a gate acting
    on that lie would let every dead thing back in.

APPEND-ONLY, AND SAFE UNDER CONCURRENT WRITERS: ``record_death`` and
``record_resurrection_approval`` only ever add a new record to the end of
the list. Nothing already on disk is ever edited or removed by this module.
A resurrection is a NEW record (``kind="resurrection-approved"``) whose
``refs`` field names the death record's id -- it does not replace or touch
that record. Because of this, a path can die, be approved for resurrection,
and then die AGAIN: the newest ``kind="file"`` (or ``"branch"``) record is
what ``dead_file_paths`` / ``dead_ref_names`` see, and the older approval
does not apply to the new death.

This is a multi-agent repo -- the custodian and the janitor can both be
writing graveyard records around the same time. The read-modify-write cycle
in ``record_death``/``record_resurrection_approval`` is therefore wrapped in
an exclusive file lock (``docs/ops/graveyard.json.lock``, created via
``os.O_CREAT | os.O_EXCL`` -- this repo's established lockfile pattern, see
``scripts/crew/workboard/claim_utils.py:_file_lock``), and every write goes
to a temp file in the same directory followed by ``os.replace`` (atomic on
the same volume) so a reader never observes a half-written file and a crash
mid-write never corrupts the original. A lock that cannot be acquired within
the bounded retry window is a loud SystemExit naming the lock file -- never
a silent skip of the record.

CLI: ``python scripts/forge/graveyard.py record-branch|record-file|
approve-resurrection|list [...]`` -- see ``main()`` for arguments; ``list
--json`` is the machine-readable surface for other tooling.
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

_GRAVEYARD_RELATIVE = Path("docs") / "ops" / "graveyard.json"

_DEATH_KINDS = ("branch", "file")
_RESURRECTION_KIND = "resurrection-approved"
_REQUIRED_RECORD_KEYS = ("id", "kind", "name", "dead_sha", "deleted_on", "reason", "by", "refs")

# Lock knobs. Read from the module namespace at call time (not bound as
# default arguments) so a test can `monkeypatch.setattr(graveyard, "_LOCK_...", ...)`
# to shrink the retry window without waiting out the real timeout.
_LOCK_MAX_RETRIES = 20
_LOCK_RETRY_INTERVAL = 0.25  # seconds
_LOCK_STALE_SECONDS = 30.0


@dataclass(frozen=True)
class Graveyard:
    """An immutable, in-memory view of everything recorded as dead.

    ``records`` is every record in the file, in append order (oldest
    first). Consumers who need more than the three query methods below can
    read ``records`` directly -- for example a pre-push gate that needs the
    full death record (id, deleted_on, reason) for a branch name, not just
    the fact that the name is dead.
    """

    records: tuple[dict[str, Any], ...]

    def dead_ref_names(self) -> set[str]:
        """Every branch name that has a death record, dead or resurrected.

        Callers that need to honor an approved resurrection look up the
        matching record in ``records`` and check ``is_resurrection_approved``
        on ITS id -- this method only answers "has this name ever died".
        """
        return {r["name"] for r in self.records if r["kind"] == "branch"}

    def dead_file_paths(self) -> dict[str, dict[str, Any]]:
        """path -> the newest ``kind="file"`` death record for that path.

        "Newest" is append order, not ``deleted_on`` (two deaths can share a
        date). A resurrection-approval record never appears as a value here
        -- it is a different ``kind``, so it can never shadow the death
        record it references. That is what makes contract 4 work: a path
        that was approved and then deleted again reports as dead again,
        because the newest ``kind="file"`` record for that path is the new
        death, not the old approval.
        """
        newest: dict[str, dict[str, Any]] = {}
        for record in self.records:
            if record["kind"] == "file":
                newest[record["name"]] = record
        return newest

    def is_resurrection_approved(self, record_id: str) -> bool:
        """True iff some ``resurrection-approved`` record's ``refs`` names
        exactly this death record id -- never any other id, however similar
        the branch/path name."""
        return any(record["kind"] == _RESURRECTION_KIND and record.get("refs") == record_id for record in self.records)


def _graveyard_path(repo_root: Path) -> Path:
    return Path(repo_root) / _GRAVEYARD_RELATIVE


def _lock_path(repo_root: Path) -> Path:
    path = _graveyard_path(repo_root)
    return path.with_name(path.name + ".lock")


def _today() -> str:
    return dt.date.today().isoformat()


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return slug or "record"


def _require(value: str, field_name: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"graveyard: `{field_name}` must not be empty")
    return value


def load(repo_root: Path) -> Graveyard:
    """Read the graveyard, or raise SystemExit if it exists but is broken.

    See the module docstring's "honesty contract": missing is empty (with a
    printed NOTE); malformed -- bad JSON, wrong top-level shape, or any
    record missing a required key -- is a loud, hard failure naming the
    file.
    """
    path = _graveyard_path(repo_root)
    if not path.exists():
        # I5 (graveyard-with-teeth fix-wave, 2026-08-25): this NOTE must never
        # land on stdout. `graveyard.py list --json` is a machine-readable
        # surface other tooling parses with json.loads() (the janitor's
        # graveyard_dead_branch_ids(), janitor.py:323) -- a NOTE line ahead of
        # the JSON payload breaks that parse and misreports an empty
        # graveyard as an unparseable/corrupt one. stderr keeps the honesty
        # contract (absence is stated, not silent) without contaminating the
        # one output stream a JSON consumer actually reads.
        print(
            f"NOTE: {path} does not exist -- starting from an empty graveyard (nothing recorded yet).",
            file=sys.stderr,
        )
        return Graveyard(records=())

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"graveyard: cannot read {path}: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"graveyard: {path} is malformed JSON ({exc}) -- refusing to treat this as an empty graveyard"
        ) from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise SystemExit(
            f"graveyard: {path} does not have the expected shape "
            '(top-level object with a "records" list) -- refusing to treat this as an empty graveyard'
        )

    records = payload["records"]
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise SystemExit(f"graveyard: {path} record #{index} is not a JSON object -- malformed")
        missing = [key for key in _REQUIRED_RECORD_KEYS if key not in record]
        if missing:
            raise SystemExit(
                f"graveyard: {path} record #{index} (id={record.get('id')!r}) is missing required "
                f"key(s) {missing} -- malformed, refusing to treat this as an empty graveyard"
            )

    return Graveyard(records=tuple(records))


@contextmanager
def _locked(repo_root: Path):
    """Exclusive lock around a graveyard read-modify-write cycle.

    Mirrors ``scripts/crew/workboard/claim_utils.py:_file_lock``: an
    ``O_CREAT | O_EXCL`` lockfile, bounded retry, and a stale-lock break so a
    crashed holder cannot wedge the graveyard shut forever. Unlike that
    helper, a timeout here is a loud SystemExit naming the lock file -- this
    registry's whole purpose is to never lose a death record, so a caller
    that cannot get the lock must not silently skip writing.
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
                    f"graveyard: timed out waiting for lock {lock_path} "
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
    itself fails (disk full, permissions, a crash mid-call), the temp file is
    removed and the exception propagates -- the original file is untouched
    because it was never opened for writing in the first place.
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


def _next_id(records: list[dict[str, Any]], name_or_path: str, *, today: str | None = None) -> str:
    date = today or _today()
    slug = _slugify(name_or_path)
    prefix = f"{date}-{slug}-"
    existing_ids = {r["id"] for r in records}
    n = 1
    while f"{prefix}{n}" in existing_ids:
        n += 1
    return f"{prefix}{n}"


def record_death(repo_root: Path, kind: str, name_or_path: str, dead_sha: str, reason: str, by: str) -> str:
    """Append a new death record (branch or file) and return its id.

    The read-modify-write is lock-protected: two callers racing to record a
    death each see a consistent prior-state read and neither write clobbers
    the other's record.
    """
    if kind not in _DEATH_KINDS:
        raise ValueError(f"graveyard: record_death kind must be one of {_DEATH_KINDS}, got {kind!r}")
    name_or_path = _require(name_or_path, "name_or_path")
    dead_sha = _require(dead_sha, "dead_sha")
    reason = _require(reason, "reason")
    by = _require(by, "by")

    path = _graveyard_path(repo_root)
    with _locked(repo_root):
        records = list(load(repo_root).records)
        record_id = _next_id(records, name_or_path)
        records.append(
            {
                "id": record_id,
                "kind": kind,
                "name": name_or_path,
                "dead_sha": dead_sha,
                "deleted_on": _today(),
                "reason": reason,
                "by": by,
                "refs": None,
            }
        )
        _atomic_write(path, {"version": 1, "records": records})
    return record_id


def record_resurrection_approval(repo_root: Path, death_id: str, reason: str, by: str) -> str:
    """Append a ``resurrection-approved`` record referencing ``death_id`` and
    return its own new id. Never mutates the death record itself. Lock-
    protected the same way as ``record_death``."""
    death_id = _require(death_id, "death_id")
    reason = _require(reason, "reason")
    by = _require(by, "by")

    path = _graveyard_path(repo_root)
    with _locked(repo_root):
        records = list(load(repo_root).records)
        death = next((r for r in records if r["id"] == death_id and r["kind"] in _DEATH_KINDS), None)
        if death is None:
            raise SystemExit(f"graveyard: cannot approve resurrection -- no death record with id {death_id!r}")

        record_id = _next_id(records, death["name"])
        records.append(
            {
                "id": record_id,
                "kind": _RESURRECTION_KIND,
                "name": death["name"],
                "dead_sha": death["dead_sha"],
                "deleted_on": _today(),
                "reason": reason,
                "by": by,
                "refs": death_id,
            }
        )
        _atomic_write(path, {"version": 1, "records": records})
    return record_id


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli_record_branch(args: argparse.Namespace) -> int:
    record_id = record_death(Path(args.repo_root), "branch", args.name, args.dead_sha, args.reason, args.by)
    print(record_id)
    return 0


def _cli_record_file(args: argparse.Namespace) -> int:
    record_id = record_death(Path(args.repo_root), "file", args.path, args.dead_sha, args.reason, args.by)
    print(record_id)
    return 0


def _cli_approve_resurrection(args: argparse.Namespace) -> int:
    record_id = record_resurrection_approval(Path(args.repo_root), args.death_id, args.reason, args.by)
    print(record_id)
    return 0


def _cli_list(args: argparse.Namespace) -> int:
    gy = load(Path(args.repo_root))
    if args.json:
        print(json.dumps({"version": 1, "records": list(gy.records)}, ensure_ascii=False, indent=2))
        return 0
    if not gy.records:
        print("graveyard: no records.")
        return 0
    for record in gy.records:
        print(f"{record['id']}  {record['kind']:20s} {record['name']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(_REPO_ROOT), help="Repository root path.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_branch = sub.add_parser("record-branch", help="Record a branch death.")
    p_branch.add_argument("name")
    p_branch.add_argument("dead_sha")
    p_branch.add_argument("--reason", required=True)
    p_branch.add_argument("--by", required=True)
    p_branch.set_defaults(func=_cli_record_branch)

    p_file = sub.add_parser("record-file", help="Record a file death.")
    p_file.add_argument("path")
    p_file.add_argument("dead_sha")
    p_file.add_argument("--reason", required=True)
    p_file.add_argument("--by", required=True)
    p_file.set_defaults(func=_cli_record_file)

    p_approve = sub.add_parser("approve-resurrection", help="Approve resurrecting a dead branch/file.")
    p_approve.add_argument("death_id")
    p_approve.add_argument("--reason", required=True)
    p_approve.add_argument("--by", required=True)
    p_approve.set_defaults(func=_cli_approve_resurrection)

    p_list = sub.add_parser("list", help="List every record.")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=_cli_list)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
