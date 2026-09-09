#!/usr/bin/env python3
"""A branch is a claim that expires -- not a fork that lives forever for free.

WHY THIS EXISTS: this repo's own cleanup found 63 local branches and 150+
remote branches with no owner, no purpose, and no end date attached to any of
them -- forking was free, and nothing ever asked a branch to justify still
existing. This registry is the other half of that fix (the trunk-health line
in ``scripts/crew/brief/trunk_health.py`` makes the SYMPTOM visible; this
module makes the CLAIM mechanism exist): every branch that wants to reach a
remote must be recorded here first, with an owner, a purpose, and a date it
stops being valid. ``scripts/forge/gates/branch_claim_gate.py`` reads this
registry to refuse an unclaimed push; ``scripts/forge/branch_sweep.py`` reads
it to decide which local branches have outlived their claim.

FIELD SHAPE: ``branch``/``owner``/``purpose``/``created_on``/``expires_on``/
``refs`` -- the schema fixed by the plan
the internal design record, Task 2). No
``id`` field: a claim is looked up by branch name directly (see NEWEST WINS
below), the same way the graveyard's ``dead_ref_names()`` is keyed by branch
name rather than record id.

THE 60-DAY CAP (the one place this diverges from ``accepted_risks.py``'s
otherwise-identical pattern): an accepted risk can run open-ended because a
human explicitly reviewed it; a branch claim is a WORKING claim on a fork
that is supposed to land or die, not a standing exception. ``record_claim``
rejects any ``expires_on`` more than 60 days past the day it is recorded, in
addition to rejecting a date that is already in the past --
``_validate_expires_on`` enforces both bounds before the lock is ever taken.

NEWEST WINS: records are append-only, exactly like ``accepted_risks.py`` and
``graveyard.py``. A branch can be re-claimed (a new record with the same
``branch`` name) after its first claim expires or is superseded; ``get()``
and ``is_expired()`` both resolve the NEWEST record for that branch name, not
the first -- so a branch that was claimed, expired, and re-claimed reads as
live again, and a branch that was claimed and then re-claimed with a new
purpose reads under the new one.

THE HONESTY CONTRACT (identical shape to ``accepted_risks.py`` and
``graveyard.py`` -- this repo's documented disease is absence-reads-as-clean):
  * a MISSING ``docs/ops/branch_claims.json`` is legitimately "nothing has
    been claimed yet" -- ``load()`` returns an empty ``Claims`` and prints a
    NOTE so the absence is visible, never silent.
  * a file that EXISTS but fails to parse, is the wrong shape, or contains a
    record missing a required key is a completely different situation -- the
    record is broken, not empty. ``load()`` raises ``SystemExit`` naming the
    file. It never falls back to an empty registry.

CALLERS HANDLE MISSING DIFFERENTLY FROM EACH OTHER ON PURPOSE: this module's
``load()`` treats "missing file" as "legitimately empty" exactly like its
siblings -- that symmetry is deliberate and lives here, not in the callers.
What differs is what each CALLER does with an empty-because-absent registry:
``branch_claim_gate.py`` checks ``path(repo_root).exists()`` itself BEFORE
calling ``load()`` and passes with a loud note when the file is entirely
absent (infrastructure absence must not block every push before the registry
is even provisioned) -- but treats a genuinely present, genuinely empty
registry as real enforcement (every unclaimed push still fails).
``branch_sweep.py`` makes the opposite call for the same "file absent" state:
it refuses to delete anything, because destruction needs positive proof a
claim is truly absent, not merely "the tooling was never set up on this
machine". See those modules' docstrings for the full reasoning; this module
only provides ``path()`` so both can make that distinction without
duplicating the absence check.

EXPIRY BOUNDARY SEMANTICS match ``accepted_risks.py``'s (itself matching
``monolith_guard.py``'s waiver-expiry check): a claim is expired only once
its ``expires_on`` date is STRICTLY before "today" -- the expiry day itself
is still live.

APPEND-ONLY, LOCKED, ATOMIC: copied byte-for-byte from ``accepted_risks.py``
-- see that module's docstring for the full reasoning on the lockfile and
atomic-write pattern; it is reproduced here unchanged rather than imported,
so this registry has no import-time dependency on a sibling registry module.

CLI: ``python scripts/forge/branch_claims.py record|list [...]``.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]

_CLAIMS_RELATIVE = Path("docs") / "ops" / "branch_claims.json"

_REQUIRED_RECORD_KEYS = ("branch", "owner", "purpose", "created_on", "expires_on", "refs")

_MAX_EXPIRY_DAYS = 60

# Lock knobs -- read from the module namespace at call time (not bound as
# default arguments) so a test can `monkeypatch.setattr(branch_claims,
# "_LOCK_...", ...)` to shrink the retry window. Values match
# accepted_risks.py's / graveyard.py's.
_LOCK_MAX_RETRIES = 20
_LOCK_RETRY_INTERVAL = 0.25  # seconds
_LOCK_STALE_SECONDS = 30.0


@dataclass(frozen=True)
class Claims:
    """An immutable, in-memory view of every branch claim on record.

    ``records`` is every record in the file, in append order (oldest
    first).
    """

    records: tuple[dict[str, Any], ...]

    def get(self, branch: str) -> dict[str, Any] | None:
        """The NEWEST record for ``branch``, or ``None`` if it was never
        claimed. Never raises -- an unclaimed branch is a normal, expected
        outcome for a gate checking an arbitrary push."""
        newest: dict[str, Any] | None = None
        for record in self.records:
            if record["branch"] == branch:
                newest = record
        return newest

    def is_expired(self, branch: str, today: dt.date | str | None = None) -> bool | None:
        """Whether ``branch``'s newest claim has lapsed as of ``today``
        (default: the real current date).

        Returns ``None`` -- never ``False`` -- when ``branch`` was never
        claimed at all. A caller that conflated "never claimed" with
        "claimed and still live" would let an anonymous fork through as if
        it had an owner; ``None`` forces the caller to handle "no claim
        exists" as its own case, distinct from "not expired yet". This is
        the house law (see ``accepted_risks.py:Risks.is_expired``, the same
        rule, same reasoning).

        Boundary semantics: expired iff ``expires_on`` is STRICTLY before
        ``today`` -- the expiry day itself still counts as live.
        """
        record = self.get(branch)
        if record is None:
            return None
        as_of = _coerce_date(today) if today is not None else dt.date.today()
        expires_date = dt.date.fromisoformat(record["expires_on"])
        return expires_date < as_of


def _coerce_date(value: dt.date | str) -> dt.date:
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def path(repo_root: Path) -> Path:
    """The registry file's path under ``repo_root``. Public (unlike the
    sibling registries' private ``_risks_path``/``_graveyard_path``) because
    both ``branch_claim_gate.py`` and ``branch_sweep.py`` need to check
    ``.exists()`` themselves BEFORE calling ``load()`` -- see the module
    docstring's "CALLERS HANDLE MISSING DIFFERENTLY" section."""
    return Path(repo_root) / _CLAIMS_RELATIVE


def _lock_path(repo_root: Path) -> Path:
    p = path(repo_root)
    return p.with_name(p.name + ".lock")


def _today() -> str:
    return dt.date.today().isoformat()


def _require(value: str, field_name: str) -> str:
    value = str(value or "").strip()
    if not value:
        raise ValueError(f"branch_claims: `{field_name}` must not be empty")
    return value


def _validate_branch(branch: str) -> str:
    """Validate ``branch`` is non-empty, is not a trunk name, and is a name
    ``git`` itself will actually accept as a branch (fix round 1, MIN-1: a
    claim recorded for a git-invalid name, e.g. one containing a space, can
    never match a real push -- it is a garbage record that silently never
    protects anything). Uses ``git check-ref-format --branch`` -- the same
    check git applies when creating a branch, run standalone (no repository
    required; verified empirically) so this registry never depends on being
    invoked from inside a repo to validate a name."""
    branch = _require(branch, "branch")
    if branch in ("dev", "main"):
        raise ValueError(f"branch_claims: refusing to claim trunk branch {branch!r} -- trunk needs no claim")
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell, no repo required
        ["git", "check-ref-format", "--branch", branch],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or "git check-ref-format rejected it"
        raise ValueError(
            f"branch_claims: {branch!r} is not a valid git branch name ({detail}) -- refusing to record a "
            "claim that could never match a real push"
        )
    return branch


def _validate_expires_on(expires_on: str, *, today: dt.date | None = None) -> str:
    """Validate ``expires_on`` is a real ``YYYY-MM-DD`` date that is today or
    later, and no more than ``_MAX_EXPIRY_DAYS`` days out. Loud on garbage or
    on an over-long claim -- both raise ``ValueError`` before the lock is
    ever taken, mirroring ``accepted_risks.py``'s ``_validate_expires_on``
    with one extra bound."""
    text = str(expires_on or "").strip()
    if not text:
        raise ValueError("branch_claims: `expires_on` must not be empty")
    try:
        expires_date = dt.date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"branch_claims: `expires_on` {text!r} is not a valid YYYY-MM-DD date") from exc
    as_of = today if today is not None else dt.date.today()
    if expires_date < as_of:
        raise ValueError(
            f"branch_claims: `expires_on` {text!r} is already in the past -- a branch claim must "
            "expire today or later, never a shrug that was already stale when it was written down"
        )
    latest_allowed = as_of + dt.timedelta(days=_MAX_EXPIRY_DAYS)
    if expires_date > latest_allowed:
        raise ValueError(
            f"branch_claims: `expires_on` {text!r} is more than {_MAX_EXPIRY_DAYS} days out from {as_of.isoformat()} "
            f"(latest allowed: {latest_allowed.isoformat()}) -- a branch claim is a working claim, not a "
            "standing exception; re-claim it if the work is still live when it lapses"
        )
    return expires_date.isoformat()


def load(repo_root: Path) -> Claims:
    """Read the branch-claims registry, or raise ``SystemExit`` if it exists
    but is broken.

    See the module docstring's honesty contract: missing is empty (with a
    printed NOTE); malformed -- bad JSON, wrong top-level shape, or any
    record missing a required key -- is a loud, hard failure naming the
    file.
    """
    p = path(repo_root)
    if not p.exists():
        print(
            f"NOTE: {p} does not exist -- starting from an empty branch-claims registry (nothing claimed yet).",
            file=sys.stderr,
        )
        return Claims(records=())

    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemExit(f"branch_claims: cannot read {p}: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit(
            f"branch_claims: {p} is malformed JSON ({exc}) -- refusing to treat this as an empty registry"
        ) from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise SystemExit(
            f"branch_claims: {p} does not have the expected shape "
            '(top-level object with a "records" list) -- refusing to treat this as an empty registry'
        )

    records = payload["records"]
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise SystemExit(f"branch_claims: {p} record #{index} is not a JSON object -- malformed")
        missing = [key for key in _REQUIRED_RECORD_KEYS if key not in record]
        if missing:
            raise SystemExit(
                f"branch_claims: {p} record #{index} (branch={record.get('branch')!r}) is missing required "
                f"key(s) {missing} -- malformed, refusing to treat this as an empty registry"
            )

    return Claims(records=tuple(records))


@contextmanager
def _locked(repo_root: Path):
    """Exclusive lock around a branch-claims read-modify-write cycle.
    Identical in shape to ``accepted_risks.py:_locked`` / ``graveyard.py:_locked``."""
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
                    f"branch_claims: timed out waiting for lock {lock_path} "
                    f"(held by another process for at least {age:.1f}s) -- refusing to write unlocked"
                )
            time.sleep(retry_interval)

    try:
        yield
    finally:
        os.close(fd)
        with suppress(FileNotFoundError):
            lock_path.unlink()


def _atomic_write(p: Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` to ``p`` via temp-file-then-replace. See
    ``accepted_risks.py:_atomic_write`` for the full reasoning; reproduced
    unchanged."""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.replace(str(tmp), str(p))
    except OSError:
        with suppress(FileNotFoundError):
            tmp.unlink()
        raise


def record_claim(
    repo_root: Path,
    branch: str,
    owner: str,
    purpose: str,
    expires_on: str,
    refs: str | None = None,
) -> None:
    """Append a new branch claim.

    ``branch``, ``owner``, and ``purpose`` must be non-empty; ``branch`` may
    not be ``dev`` or ``main`` (trunk needs no claim); ``expires_on`` must be
    a real date, today-or-later, and no more than 60 days out -- all checks
    run BEFORE the lock is taken, so a bad call never contends for the write
    lock. ``created_on`` is always set to today, at record time. The
    read-modify-write is lock-protected: two callers racing to claim a
    branch each see a consistent prior-state read and neither write clobbers
    the other's record -- the NEWEST record on disk after both writes is
    whichever one actually won the lock, and that is the one ``get()``/
    ``is_expired()`` will see (see the module docstring's "NEWEST WINS").
    """
    branch = _validate_branch(branch)
    owner = _require(owner, "owner")
    purpose = _require(purpose, "purpose")
    expires_on = _validate_expires_on(expires_on)

    p = path(repo_root)
    with _locked(repo_root):
        records = list(load(repo_root).records)
        records.append(
            {
                "branch": branch,
                "owner": owner,
                "purpose": purpose,
                "created_on": _today(),
                "expires_on": expires_on,
                "refs": refs,
            }
        )
        _atomic_write(p, {"version": 1, "records": records})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cli_record(args: argparse.Namespace) -> int:
    record_claim(Path(args.repo_root), args.branch, args.owner, args.purpose, args.expires_on, args.refs)
    print(f"claimed {args.branch!r} for {args.owner!r} until {args.expires_on}")
    return 0


def _cli_list(args: argparse.Namespace) -> int:
    claims = load(Path(args.repo_root))
    if args.json:
        print(json.dumps({"version": 1, "records": list(claims.records)}, ensure_ascii=False, indent=2))
        return 0
    if not claims.records:
        print("branch_claims: no records.")
        return 0
    for record in claims.records:
        print(
            f"{record['branch']:40s} owner={record['owner']:20s} "
            f"expires_on={record['expires_on']}  {record['purpose']}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(_REPO_ROOT), help="Repository root path.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_record = sub.add_parser("record", help="Record a branch claim.")
    p_record.add_argument("--branch", required=True)
    p_record.add_argument("--owner", required=True)
    p_record.add_argument("--purpose", required=True)
    p_record.add_argument("--expires-on", required=True, help="YYYY-MM-DD, today or later, at most 60 days out.")
    p_record.add_argument("--refs", default=None)
    p_record.set_defaults(func=_cli_record)

    p_list = sub.add_parser("list", help="List every claim.")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=_cli_list)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
