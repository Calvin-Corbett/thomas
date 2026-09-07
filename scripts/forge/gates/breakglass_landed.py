"""Did a breakglass attempt actually land? (split out of precommit_skip_policy for size)

The skip-policy audit row is written when the policy passes, BEFORE the commit
runs, so a later gate failure leaves a row with nothing behind it. Those rows used
to burn the quota: 18 rows in one day for 6 ceremonies locked the shared principal
out. A row counts when a commit on top of its recorded ``head`` touched one of its
staged files, or while it is younger than ``pending_minutes`` (the commit may still
be in flight). Rows without ``head``/``staged_files`` (older format) always count.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta

_LANDED_CACHE: dict[str, set[str]] = {}


def clear_cache() -> None:
    _LANDED_CACHE.clear()


def breakglass_row_landed(
    payload: dict[str, object],
    *,
    now: datetime,
    pending_minutes: int,
    run_git: Callable[[list[str]], str | None],
    parse_iso_utc: Callable[[str], datetime | None],
) -> bool:
    head = str(payload.get("head") or "").strip()
    staged = [str(p).replace(chr(92), "/") for p in (payload.get("staged_files") or []) if str(p).strip()]
    if not head or not staged:
        return True
    stamp = parse_iso_utc(str(payload.get("timestamp_utc", "")))
    if stamp is not None and now - stamp <= timedelta(minutes=max(0, pending_minutes)):
        return True
    if head not in _LANDED_CACHE:
        touched: set[str] = set()
        log = run_git(["log", "--all", "--format=%H %P", "-n", "5000"]) or ""
        for line in log.splitlines():
            parts = line.split()
            if len(parts) >= 2 and head in parts[1:]:
                names = run_git(["diff-tree", "--no-commit-id", "--name-only", "-r", parts[0]]) or ""
                touched.update(n.strip().replace(chr(92), "/") for n in names.splitlines() if n.strip())
        _LANDED_CACHE[head] = touched
    return any(path in _LANDED_CACHE[head] for path in staged)
