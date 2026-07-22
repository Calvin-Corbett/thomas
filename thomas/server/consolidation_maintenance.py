"""Background consolidation maintenance -- the part that needs no human.

The branch custodian can detect sprawl and the hold can block on it, but both
only matter if something *runs* them. This is that something: a periodic loop
started with the server, alongside the runtime guard and the run-store janitor.

It runs :func:`thomas.forge.consolidation_hold.audit`, which places a hold when
branches cross the ceiling and lifts it once they drop back. So the repository
notices its own sprawl and says so, without anyone remembering to look -- which
is the entire point, because the person who most needs this is the one least
able to spot it.

Failure policy: maintenance must never take the server down. Every cycle is
wrapped, faults are logged, and the loop keeps its cadence.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger(__name__)

INTERVAL_ENV = "THOMAS_CONSOLIDATION_AUDIT_INTERVAL_S"
ENABLED_ENV = "THOMAS_CONSOLIDATION_AUDIT_ENABLED"

DEFAULT_INTERVAL_S = 6 * 60 * 60  # six hours
MIN_INTERVAL_S = 60.0
MAX_INTERVAL_S = 24 * 60 * 60.0
# Let the server finish booting before the first sweep.
DEFAULT_STARTUP_DELAY_S = 30.0

# Wide but concrete: a maintenance sweep must never escalate into an outage.
_SWEEP_FAULTS = (
    OSError,
    ValueError,
    TypeError,
    KeyError,
    LookupError,
    RuntimeError,
    ArithmeticError,
    UnicodeDecodeError,
)


def audit_interval_s() -> float:
    """Cadence between sweeps, clamped to something sane."""
    raw = str(os.environ.get(INTERVAL_ENV, "") or "").strip()
    try:
        value = float(raw) if raw else float(DEFAULT_INTERVAL_S)
    except (TypeError, ValueError):
        value = float(DEFAULT_INTERVAL_S)
    return max(MIN_INTERVAL_S, min(MAX_INTERVAL_S, value))


def maintenance_enabled() -> bool:
    """On unless explicitly disabled."""
    raw = str(os.environ.get(ENABLED_ENV, "") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def run_audit_once(repo_root: str = ".", *, trunk: str = "dev") -> dict[str, Any]:
    """One sweep. Returns a JSON-shaped result; never raises."""
    try:
        from thomas.forge.branch_custodian import subprocess_git_runner
        from thomas.forge.consolidation_hold import audit
    except (ImportError, ModuleNotFoundError) as exc:  # pragma: no cover - import guard
        log.debug("consolidation audit unavailable: %s", exc)
        return {"ok": False, "error": f"unavailable: {exc}"}

    try:
        result = audit(subprocess_git_runner(repo_root), repo_root, trunk=trunk, now=_utc_stamp)
    except _SWEEP_FAULTS as exc:
        log.warning("consolidation audit failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    payload = result.as_dict()
    payload["ok"] = True
    if result.hold_placed:
        log.warning("Branch sprawl: %s", result.hold.message() if result.hold else "consolidation hold placed")
    elif result.hold_released:
        log.info("Branch sprawl cleared; consolidation hold lifted.")
    else:
        log.debug("Consolidation audit: %s", result.report.summary())
    return payload


def _utc_stamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def consolidation_maintenance_loop(
    app: Any = None,
    *,
    repo_root: str = ".",
    trunk: str = "dev",
    startup_delay_s: float | None = None,
    interval_s: float | None = None,
    audit_fn: Callable[[], dict[str, Any]] | None = None,
    sleep_fn: Callable[[float], Awaitable[None]] | None = None,
    max_cycles: int | None = None,
) -> int:
    """Sweep for branch sprawl forever, on a cadence.

    ``audit_fn``/``sleep_fn``/``max_cycles`` exist so the loop is testable
    without a repository, a server, or real time. Returns the number of
    completed cycles (useful only to tests; in production it runs until
    cancelled).
    """
    if not maintenance_enabled():
        log.info("Consolidation maintenance disabled via %s", ENABLED_ENV)
        return 0

    sleep = sleep_fn or asyncio.sleep
    do_audit = audit_fn or (lambda: run_audit_once(repo_root, trunk=trunk))
    delay = DEFAULT_STARTUP_DELAY_S if startup_delay_s is None else startup_delay_s

    if delay > 0:
        await sleep(delay)

    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        try:
            do_audit()
        except _SWEEP_FAULTS as exc:  # belt and braces around an injected fn
            log.warning("consolidation maintenance cycle failed: %s", exc)
        except asyncio.CancelledError:
            raise
        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            break
        await sleep(interval_s if interval_s is not None else audit_interval_s())
    return cycles
