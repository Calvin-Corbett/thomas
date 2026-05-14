from __future__ import annotations

from typing import Any, Dict, List, Optional

from thomas.core.scheduler import get_scheduler

# ============================================================
# Table formatting (monospace-friendly)
# ============================================================

def _truncate(s: str, max_len: int) -> str:
    s = s or ""
    if len(s) <= max_len:
        return s
    return s[: max(0, max_len - 1)] + "…"

def _format_table(rows: list[dict[str, str]], columns: list[str]) -> str:
    if not rows:
        header = " | ".join(columns)
        sep = "-+-".join("-" * len(c) for c in columns)
        return header + "\n" + sep + "\n(no scheduled tasks)"

    widths = {c: len(c) for c in columns}
    for r in rows:
        for c in columns:
            widths[c] = max(widths[c], len(str(r.get(c, ""))))

    def fmt_row(r: dict[str, str]) -> str:
        return " | ".join(str(r.get(c, "")).ljust(widths[c]) for c in columns)

    header = " | ".join(c.ljust(widths[c]) for c in columns)
    sep = "-+-".join("-" * widths[c] for c in columns)
    body = "\n".join(fmt_row(r) for r in rows)
    return header + "\n" + sep + "\n" + body


def _tasks_table() -> str:
    sched = get_scheduler()
    tasks = sched.list_tasks()

    rows: list[dict[str, str]] = []
    for t in tasks:
        rows.append(
            {
                "id": str(t.get("id", "")),
                "cron": str(t.get("cron", "")),
                "next_run": str(t.get("next_run", "") or "-"),
                "task": _truncate(str(t.get("task", "")), 80),
                "status": str(t.get("status", "")),
            }
        )

    return _format_table(rows, ["id", "cron", "next_run", "task", "status"])


# ============================================================
# REQUIRED tools
# ============================================================

def schedule_add(params: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    params = params or {}
    task_id = str(params.get("id", "")).strip()
    cron = str(params.get("cron", "")).strip()
    task = str(params.get("task", "")).strip()

    channel = str(params.get("channel", "default")).strip() or "default"

    sched = get_scheduler()
    sched.add_task(task_id, cron, task, channel=channel)
    return {"ok": True, "message": f"Scheduled task '{task_id}' added/updated.", "table": _tasks_table()}


def schedule_list(params: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    sched = get_scheduler()
    return {"ok": True, "health": sched.health(), "table": _tasks_table()}


def schedule_remove(params: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    params = params or {}
    task_id = str(params.get("id", "")).strip()

    sched = get_scheduler()
    sched.remove_task(task_id)
    return {"ok": True, "message": f"Scheduled task '{task_id}' removed (if it existed).", "table": _tasks_table()}


def schedule_run_now(params: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    params = params or {}
    task_id = str(params.get("id", "")).strip()

    sched = get_scheduler()
    sched.run_now(task_id, ignore_paused=True)
    return {"ok": True, "message": f"Scheduled task '{task_id}' fired now.", "table": _tasks_table()}


# ============================================================
# OPTIONAL "consumer delight" tools (won't break required set)
# ============================================================

def schedule_pause(params: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    params = params or {}
    task_id = str(params.get("id", "")).strip()
    sched = get_scheduler()
    sched.pause_task(task_id)
    return {"ok": True, "message": f"Paused '{task_id}'.", "table": _tasks_table()}

def schedule_resume(params: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    params = params or {}
    task_id = str(params.get("id", "")).strip()
    sched = get_scheduler()
    sched.resume_task(task_id)
    return {"ok": True, "message": f"Resumed '{task_id}'.", "table": _tasks_table()}

def schedule_preview(params: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    params = params or {}
    task_id = str(params.get("id", "")).strip()
    count = int(params.get("count", 5) or 5)
    sched = get_scheduler()
    return {"ok": True, "id": task_id, "next": sched.preview_next(task_id, count=count)}

def schedule_update(params: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
    params = params or {}
    task_id = str(params.get("id", "")).strip()
    sched = get_scheduler()
    sched.update_task(
        task_id,
        cron=params.get("cron"),
        task=params.get("task"),
        channel=params.get("channel"),
        misfire_policy=params.get("misfire_policy"),
        misfire_grace_s=params.get("misfire_grace_s"),
        jitter_s=params.get("jitter_s"),
    )
    return {"ok": True, "message": f"Updated '{task_id}'.", "table": _tasks_table()}


# ============================================================
# Tool registry patterns
# ============================================================

TOOLS: dict[str, dict[str, Any]] = {
    # required
    "schedule.add": {"handler": schedule_add, "schema": {"id": "str", "cron": "str", "task": "str"}},
    "schedule.list": {"handler": schedule_list, "schema": {}},
    "schedule.remove": {"handler": schedule_remove, "schema": {"id": "str"}},
    "schedule.run_now": {"handler": schedule_run_now, "schema": {"id": "str"}},
    # optional
    "schedule.pause": {"handler": schedule_pause, "schema": {"id": "str"}},
    "schedule.resume": {"handler": schedule_resume, "schema": {"id": "str"}},
    "schedule.preview": {"handler": schedule_preview, "schema": {"id": "str", "count": "int"}},
    "schedule.update": {
        "handler": schedule_update,
        "schema": {
            "id": "str",
            "cron": "str?",
            "task": "str?",
            "channel": "str?",
            "misfire_policy": "'catch_up'|'skip'?",
            "misfire_grace_s": "int?",
            "jitter_s": "int?",
        },
    },
}


def get_tools() -> dict[str, dict[str, Any]]:
    return TOOLS


def register(registry: Any) -> None:
    """
    Best-effort integration with tool registries:
      - registry.register(name, handler, schema)
      - registry.add_tool(...)
    """
    for name, spec in TOOLS.items():
        handler = spec["handler"]
        schema = {"name": name, "params": spec.get("schema", {})}

        if hasattr(registry, "register"):
            try:
                registry.register(name, handler, schema)
                continue
            except Exception:
                pass
        if hasattr(registry, "add_tool"):
            try:
                registry.add_tool(name=name, handler=handler, schema=schema)
                continue
            except Exception:
                pass
