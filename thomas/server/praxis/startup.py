"""Resume durable Praxis child continuations when the server starts again."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from thomas.core.project_root import user_praxis_root
from thomas.server.app_keys import APP_PRAXIS_RECOVERY_REPORT as APP_PRAXIS_RECOVERY_REPORT
from thomas.server.praxis.recovery import PraxisRunJournal, recover_channel

log = logging.getLogger(__name__)
_CONTEXT_KEYS = frozenset(
    {
        "project_root",
        "family",
        "model_id",
        "reviewer_model",
        "dispatch_model",
        "praxis_reviewer_profile",
        "praxis_reviewer_model",
    }
)


_OPTIONAL_KEYS = frozenset({"conversation_id", "agent"})


def _restore_settings(context: Any) -> tuple[Path, Any, str]:
    if not isinstance(context, dict) or not _CONTEXT_KEYS <= set(context) <= _CONTEXT_KEYS | _OPTIONAL_KEYS:
        raise ValueError("missing_launch_context")
    if any(not isinstance(value, str) for value in context.values()) or context["family"] not in {"gpt", "claude"}:
        raise ValueError("invalid_launch_context")
    project = Path(context["project_root"])
    if not project.is_absolute() or not project.is_dir():
        raise ValueError("project_unavailable")
    return (
        project.resolve(strict=True),
        # A launch recorded before the Agent choice has no agent: "" lets the runner pick as it did then.
        SimpleNamespace(
            **{key: context[key] for key in _CONTEXT_KEYS if key != "project_root"},
            agent=str(context.get("agent") or ""),
        ),
        str(context.get("conversation_id") or ""),
    )


def recover_interrupted_runs(app_ref: Any, registry: Any) -> dict[str, Any]:
    """Scan the journal once and take in each interrupted run; incomplete rows alone are eligible.

    Nothing here awaits, so a caller that must have the report before it goes on, such as the restart pass, can call
    this and read ``APP_PRAXIS_RECOVERY_REPORT`` straight after.
    """
    report: dict[str, Any] = {"resumed": [], "skipped": []}
    try:
        journal = PraxisRunJournal(user_praxis_root() / "praxis" / "runs.sqlite3")
        interrupted = journal.interrupted_runs()
    except (OSError, sqlite3.DatabaseError):
        log.exception("Praxis run journal is unavailable at server startup")
        report["skipped"].append({"run_id": "", "reason": "journal_unavailable"})
        app_ref[APP_PRAXIS_RECOVERY_REPORT] = report
        return report
    adopted: list[str] = []
    try:
        _take_in(app_ref, registry, journal, interrupted, report, adopted)
    except Exception:
        log.exception("Praxis recovery failed part way; stopping the runs already taken in")
        # A scan that fails part way hands back no helper: ones already taken in would run with nothing to stop them.
        for run_id in adopted:
            channel = registry._runs.pop(run_id, None)
            if channel is not None:
                channel.revoke()
            registry._release(run_id)
        raise
    app_ref[APP_PRAXIS_RECOVERY_REPORT] = report
    return report


def _take_in(
    app_ref: Any, registry: Any, journal: Any, interrupted: list[str], report: dict, adopted: list[str]
) -> None:
    from thomas.server.praxis.launch import build_dispatching_child_runner

    for run_id in interrupted:
        if run_id in registry._runs:
            continue
        try:
            saved = journal.load(run_id)
            if saved is None:
                raise ValueError("missing_run")
            project, settings, conversation_id = _restore_settings(saved["launch_context"])
            runner = build_dispatching_child_runner(app_ref, project, settings, run_id)
            channel = recover_channel(journal, run_id, runner)
            registry.adopt(run_id, channel)
            adopted.append(run_id)
        except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
            reason = (
                str(exc)
                if str(exc)
                in {"missing_launch_context", "invalid_launch_context", "project_unavailable", "missing_run"}
                else "recovery_failed"
            )
            if reason == "recovery_failed":
                log.exception("Praxis run %s could not resume", run_id)
            else:
                log.warning("Praxis run %s could not resume: %s", run_id, reason)
            report["skipped"].append({"run_id": run_id, "reason": reason})
            continue
        report["resumed"].append(
            {"run_id": run_id, "conversation_id": conversation_id, "agents": len(channel._children)}
        )


def install_praxis_recovery(app: Any, registry: Any) -> None:
    """Register one startup scan on an app that is not a row's view."""

    async def on_startup(app_ref: Any) -> None:
        recover_interrupted_runs(app_ref, registry)

    app.on_startup.append(on_startup)


__all__ = ["APP_PRAXIS_RECOVERY_REPORT", "install_praxis_recovery", "recover_interrupted_runs"]
