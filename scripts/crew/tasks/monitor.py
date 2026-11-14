"""The task manager's monitor cycle: the one caller the dead-claim sweep never had.

`manager.py --monitor` is documented to "sweep inactive", but `messages._monitor_loop`
was a stub that returned `{"cycle_count": n}` at once, so a claim whose agent died
stayed on the board until a person ran `--sweep-inactive` by hand.

Each cycle runs the sweep read-only. It reaps only when the caller asked for it
deliberately:

* no `apply`: report only, the board is not written;
* `apply` without `only`: nothing is reaped, the cycle names what it would take
  and says why it did not (an unattended `--apply` used to reap every stale claim
  on its first cycle, including ones nobody had looked at);
* `apply` with `only`: exactly the named claim ids (agent ids) that are stale,
  one by one. A claim with no timing evidence is held back alone; it does not
  stop the others.

A claim that is live by `claimed_at` or by presence heartbeat is never stale (see
`claim_liveness`). Blame is the slow part (about 0.9 s per call on the real
board), so it is cached per board content and bounded by a per-cycle time budget;
what the budget skipped is logged and reported.
"""

from __future__ import annotations

import hashlib
import logging
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.crew.tasks import sweep as workboard_task_manager_sweep  # noqa: E402

LOG = logging.getLogger(__name__)
NO_EVIDENCE_ISSUE = "missing_blame_timestamp_and_activity"
MAX_CONSECUTIVE_FAILURES = 5
DEFAULT_BLAME_BUDGET_SECONDS = 20.0
_BLAME_CACHE: dict[tuple[str, int], int | None] = {}
_BLAME_CACHE_LIMIT = 512


def _norm(value: object) -> str:
    return str(value or "").strip().casefold()


def parse_only(raw: str | None) -> frozenset[str] | None:
    """`--only a,b` -> {"a","b"}; None when the flag was not given."""

    if raw is None:
        return None
    return frozenset(_norm(part) for part in str(raw).split(",") if _norm(part))


class BlameBudget:
    """Blame wrapper: memoised by board content, stops calling git when time runs out."""

    def __init__(self, inner: Callable[[Path, int], int | None], seconds: float) -> None:
        self._inner = inner
        self._deadline = time.monotonic() + max(0.0, float(seconds))
        self.skipped: list[int] = []

    def __call__(self, workboard_path: Path, line_no: int) -> int | None:
        try:
            digest = hashlib.sha1(Path(workboard_path).read_bytes()).hexdigest()
        except OSError:
            return self._inner(workboard_path, line_no)
        key = (digest, int(line_no))
        if key in _BLAME_CACHE:
            return _BLAME_CACHE[key]
        if time.monotonic() >= self._deadline:
            self.skipped.append(int(line_no))
            return None
        value = self._inner(workboard_path, line_no)
        if len(_BLAME_CACHE) >= _BLAME_CACHE_LIMIT:
            _BLAME_CACHE.clear()
        _BLAME_CACHE[key] = value
        return value


def sweep_once(
    *,
    workboard_path: Path,
    max_idle_minutes: float,
    task_manager_agent: str,
    now: datetime,
    require_claims_to_have_active_task: bool,
    apply: bool,
    only: frozenset[str] | None = None,
    presence_dir: Path | None = None,
    blame_budget_seconds: float = DEFAULT_BLAME_BUDGET_SECONDS,
) -> tuple[bool, dict[str, object]]:
    """One sweep. Writes only for claims named in `only`, one claim at a time."""

    sweep = workboard_task_manager_sweep._sweep_inactive
    common = {
        "workboard_path": workboard_path,
        "max_idle_minutes": max_idle_minutes,
        "task_manager_agent": task_manager_agent,
        "now": now,
        "require_claims_to_have_active_task": require_claims_to_have_active_task,
        "presence_dir": presence_dir,
    }
    original = workboard_task_manager_sweep._line_commit_unix
    budget = BlameBudget(original, blame_budget_seconds)
    workboard_task_manager_sweep._line_commit_unix = budget
    try:
        ok, details = sweep(**common, apply=False)
        details = dict(details)
        stale = [row for row in list(details.get("stale_claims") or []) if isinstance(row, dict)]
        if budget.skipped:
            details["blame_skipped_lines"] = list(budget.skipped)
            LOG.warning("blame budget spent: %d claim line(s) not blamed this cycle", len(budget.skipped))
        if not apply or not ok or not stale:
            return ok, details
        agents = [str(row.get("agent", "")) for row in stale]
        if not only:
            details["apply_refused"] = "--apply reaps only claims named with --only; nothing was reaped"
            details["would_reap"] = agents
            return ok, details
        targets = [row for row in stale if _norm(row.get("agent")) in only]
        details["only_not_stale"] = sorted(only - {_norm(a) for a in agents})
        unproven = [str(row.get("agent", "")) for row in targets if row.get("issue") == NO_EVIDENCE_ISSUE]
        details["held_back_no_evidence"] = unproven
        reapable = frozenset(_norm(row.get("agent")) for row in targets if row.get("issue") != NO_EVIDENCE_ISSUE)
        if not reapable:
            return ok, details
        ok_apply, applied = sweep(**common, apply=True, only=reapable)
        applied = dict(applied)
        applied["held_back_no_evidence"] = unproven
        applied["only_not_stale"] = details["only_not_stale"]
        if budget.skipped:
            applied["blame_skipped_lines"] = list(budget.skipped)
        return ok_apply, applied
    finally:
        workboard_task_manager_sweep._line_commit_unix = original


def _summary(report: dict[str, object]) -> str:
    return (
        f"monitor: {report['cycle_count']} cycle(s), {report['stale_claim_count']} stale, "
        f"reaped={report['reaped_agents']}, presence overrides={len(report['presence_overrides'])}, "  # type: ignore[arg-type]
        f"held back={report['held_back_no_evidence']}, spared live={report['spared_live_claims']}, "
        f"failed cycles={report['failed_cycles']}"
    )


def run_monitor_cycles(
    *,
    cycles: int,
    interval_seconds: float,
    workboard_path: Path,
    max_idle_minutes: float,
    task_manager_agent: str,
    now_seed: datetime | None,
    require_claims_to_have_active_task: bool,
    apply: bool,
    only: frozenset[str] | None = None,
    presence_dir: Path | None = None,
    blame_budget_seconds: float = DEFAULT_BLAME_BUDGET_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[bool, dict[str, object]]:
    """Run `cycles` sweeps (0 = until stopped). A bad cycle is logged and counted; the fifth in a row is raised."""

    ran = failed = consecutive = stale_total = 0
    keys = ("released", "reaped", "moved", "held", "spared", "would", "skipped")
    names: dict[str, set[str]] = {k: set() for k in keys}
    overrides: list[dict[str, object]] = []
    refused = ""
    errors: list[str] = []
    while cycles == 0 or ran < cycles:
        now = now_seed or datetime.now(timezone.utc)
        try:
            ok, details = sweep_once(
                workboard_path=workboard_path,
                max_idle_minutes=max_idle_minutes,
                task_manager_agent=task_manager_agent,
                now=now,
                require_claims_to_have_active_task=require_claims_to_have_active_task,
                apply=apply,
                only=only,
                presence_dir=presence_dir,
                blame_budget_seconds=blame_budget_seconds,
            )
            consecutive = 0
        except Exception as exc:
            failed += 1
            consecutive += 1
            LOG.exception("monitor sweep cycle failed (%d in a row)", consecutive)
            errors.append(f"sweep cycle failed: {type(exc).__name__}: {exc}")
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                raise
            ok, details = False, {}
        ran += 1
        stale_total += int(details.get("stale_claim_count") or 0)
        for name, key in (
            ("released", "released_agents"),
            ("reaped", "reaped_agents"),
            ("moved", "moved_task_ids"),
            ("held", "held_back_no_evidence"),
            ("would", "would_reap"),
            ("skipped", "skipped_repeat_notices"),
        ):
            names[name].update(str(item) for item in list(details.get(key) or []))
        names["spared"].update(str(r.get("agent")) for r in list(details.get("spared_live_claims") or []))
        overrides.extend(dict(o) for o in list(details.get("presence_overrides") or []))
        refused = str(details.get("apply_refused") or refused)
        if not ok and details:
            errors.extend(str(e) for e in list(details.get("errors") or [details.get("error") or "sweep failed"]))
        if cycles == 0 or ran < cycles:
            sleep(max(0.0, float(interval_seconds)))
    report: dict[str, object] = {
        "cycle_count": ran,
        "failed_cycles": failed,
        "stale_claim_count": stale_total,
        "released_agents": sorted(names["released"], key=str.lower),
        "reaped_agents": sorted(names["reaped"], key=str.lower),
        "moved_task_ids": sorted(names["moved"], key=str.lower),
        "held_back_no_evidence": sorted(names["held"], key=str.lower),
        "spared_live_claims": sorted(names["spared"], key=str.lower),
        "would_reap": sorted(names["would"], key=str.lower),
        "skipped_repeat_notices": sorted(names["skipped"], key=str.lower),
        "presence_overrides": overrides,
        "applied": bool(names["reaped"]),
        "apply_refused": refused,
    }
    report["summary"] = _summary(report)
    LOG.info("%s", report["summary"])
    if errors:
        report["errors"] = errors
    return not errors, report
