"""HTTP API for the self-recursive evolve loop -- the dashboard's backend.

Architecture note: the server layer must not import ``thomas.forge`` directly
(see ``thomas/_architecture.py``). So, exactly like the autonomy engine drives
evolve sessions, this module talks to the loop through the CLI boundary --
cheap reads come straight from the persisted state file, and the heavy actions
(plan / start / approve / reject) shell out to ``python -m thomas evolve ...``.
That keeps the web server decoupled from the self-improvement engine while still
driving it.

Polling-based: the loop persists its state + an event stream to disk, and the
dashboard reads ``/status`` on an interval. The repo root is resolved through an
injectable ``root_resolver`` so the routes are unit testable against a temp dir.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

log = logging.getLogger(__name__)

APP_EVOLVE_TASK = "evolve_loop_task"
_REPO_MARKERS = ("pyproject.toml", "thomas", ".git")
_JSON_BODY_ERRORS = (json.JSONDecodeError, UnicodeDecodeError)


def _default_repo_root() -> Path:
    here = Path.cwd()
    for base in (here, *here.parents):
        if any((base / marker).exists() for marker in _REPO_MARKERS):
            return base
    return here


def _loop_dir(root: Path) -> Path:
    return Path(root) / ".thomas" / "evolve" / "loop"


def _idle_state() -> dict[str, Any]:
    return {
        "status": "idle",
        "posture": "auto_safe",
        "iteration": 0,
        "counters": {"promoted": 0, "held": 0, "rejected": 0, "failed": 0, "planned": 0},
        "backlog": [],
        "history": [],
        "pending_approvals": [],
        "pending_count": 0,
        "signals": {},
    }


def _read_state(root: Path) -> dict[str, Any]:
    path = _loop_dir(root) / "state.json"
    if not path.exists():
        return _idle_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else _idle_state()
    except (json.JSONDecodeError, OSError):
        return {"status": "unknown", **_idle_state()}


def _write_control(root: Path, **flags: Any) -> None:
    directory = _loop_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "control.json").write_text(json.dumps(flags, ensure_ascii=False), encoding="utf-8")


def _task_running(task: Any) -> bool:
    if task is None:
        return False
    # asyncio subprocess Process: done when returncode is set.
    returncode = getattr(task, "returncode", "missing")
    if returncode != "missing":
        return returncode is None
    done = getattr(task, "done", None)
    if callable(done):
        return not done()
    return False


async def _json_body(request: web.Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except _JSON_BODY_ERRORS:
        return {}
    return body if isinstance(body, dict) else {}


async def _run_evolve_cli(root: Path, args: list[str]) -> dict[str, Any] | None:
    """Run `python -m thomas evolve <args> --json` and parse stdout."""
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "thomas",
            "evolve",
            *args,
            cwd=str(root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await proc.communicate()
    except (OSError, ValueError) as exc:
        log.warning("evolve CLI invocation failed: %s", exc)
        return None
    text = stdout.decode("utf-8", errors="replace").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


async def _spawn_evolve_cli(root: Path, args: list[str]) -> Any:
    """Spawn a detached `python -m thomas evolve <args>` (output discarded)."""
    return await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "thomas",
        "evolve",
        *args,
        cwd=str(root),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )


def build_evolve_loop_handlers(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
    root_resolver: Callable[[], Path] = _default_repo_root,
) -> dict[str, Any]:
    """Build the evolve-loop handlers as a name->handler map."""

    def _root() -> Path:
        return Path(root_resolver())

    async def status(request: web.Request) -> web.Response:
        require_api_access(request)
        state = _read_state(_root())
        running_task = _task_running(app.get(APP_EVOLVE_TASK))
        state["running_task"] = running_task
        # Reconcile a stale "running" status. The loop runs as a child of this
        # server (APP_EVOLVE_TASK); a crash or restart orphans/kills that child,
        # but the persisted state file is left saying "running". Without this, the
        # dashboard sees status=="running" forever and greys out "Start evolving",
        # locking the user out. If no live subprocess exists, the run is dead ->
        # report idle so the UI re-enables Start.
        if not running_task and state.get("status") == "running":
            state["status"] = "idle"
            state["stale_run"] = True
        return web.json_response({"ok": True, "state": state})

    async def plan(request: web.Request) -> web.Response:
        require_api_access(request)
        focus = str(request.query.get("focus", ""))
        limit = str(request.query.get("limit", "10"))
        data = await _run_evolve_cli(_root(), ["plan", "--json", "--focus", focus, "--limit", limit])
        backlog = data if isinstance(data, dict) else {"goals": [], "signals": {}, "count": 0}
        return web.json_response({"ok": True, "backlog": backlog})

    async def orchestration_status(request: web.Request) -> web.Response:
        require_api_access(request)
        data = await _run_evolve_cli(_root(), ["orchestration", "status", "--json"])
        payload = data if isinstance(data, dict) else {"ok": False, "recipes": [], "active_workers": [], "runs": []}
        return web.json_response({"ok": bool(payload.get("ok")), "orchestration": payload})

    async def orchestration_plan(request: web.Request) -> web.Response:
        require_api_access(request)
        recipe = str(request.query.get("recipe", "")).strip()
        args = ["orchestration", "plan", "--json"]
        if recipe:
            args += ["--recipe", recipe]
        data = await _run_evolve_cli(_root(), args)
        payload = data if isinstance(data, dict) else {"ok": False, "recipe": None, "run": None}
        return web.json_response({"ok": bool(payload.get("ok")), "orchestration": payload})

    async def start(request: web.Request) -> web.Response:
        require_api_access(request)
        if _task_running(app.get(APP_EVOLVE_TASK)):
            return web.json_response({"ok": False, "error": "evolve loop already running"}, status=409)
        body = await _json_body(request)
        posture = str(body.get("posture") or "auto_safe")
        focus = str(body.get("focus") or "")
        # Per-goal engine: "classic" single-pass, or "funnel" (multi-agent convergence).
        mode = str(body.get("mode") or "classic").strip().lower()
        if mode not in ("classic", "funnel"):
            mode = "classic"
        args = ["loop", "--json", "--posture", posture, "--mode", mode]
        if focus:
            args += ["--focus", focus]
        args += ["--max-iterations", str(int(body.get("max_iterations") or 6))]
        args += ["--max-promotions", str(int(body.get("max_promotions") or 4))]
        if body.get("max_wall_seconds"):
            args += ["--max-wall-seconds", str(int(body["max_wall_seconds"]))]
        if body.get("profile"):
            args += ["--profile", str(body["profile"])]
        app[APP_EVOLVE_TASK] = await _spawn_evolve_cli(_root(), args)
        return web.json_response({"ok": True, "started": True, "posture": posture, "focus": focus, "mode": mode})

    async def pause(request: web.Request) -> web.Response:
        require_api_access(request)
        _write_control(_root(), stop=True)
        return web.json_response({"ok": True, "state": _read_state(_root())})

    async def approve(request: web.Request) -> web.Response:
        require_api_access(request)
        approval_id = request.match_info["approval_id"]
        body = await _json_body(request)
        args = ["approve", approval_id, "--json"]
        if body.get("profile"):
            args += ["--profile", str(body["profile"])]
        # Re-derives + promotes -> heavy; run detached and let status polling reflect it.
        app[f"evolve_approve_{approval_id}"] = await _spawn_evolve_cli(_root(), args)
        return web.json_response({"ok": True, "queued": True, "approval_id": approval_id})

    async def reject(request: web.Request) -> web.Response:
        require_api_access(request)
        approval_id = request.match_info["approval_id"]
        body = await _json_body(request)
        reason = str(body.get("reason") or "dismissed from dashboard")
        await _spawn_evolve_cli(_root(), ["reject", approval_id, "--reason", reason, "--json"])
        return web.json_response({"ok": True, "queued": True, "approval_id": approval_id})

    return {
        "status": status,
        "plan": plan,
        "orchestration_status": orchestration_status,
        "orchestration_plan": orchestration_plan,
        "start": start,
        "pause": pause,
        "approve": approve,
        "reject": reject,
    }


def register_evolve_loop_routes(
    app: web.Application,
    *,
    require_api_access: Callable[[web.Request], None],
    root_resolver: Callable[[], Path] = _default_repo_root,
) -> None:
    """Register the evolve-loop dashboard API onto the aiohttp app."""
    handlers = build_evolve_loop_handlers(app, require_api_access=require_api_access, root_resolver=root_resolver)
    app.router.add_get("/api/evolve/loop/status", handlers["status"])
    app.router.add_get("/api/evolve/loop/plan", handlers["plan"])
    app.router.add_get("/api/evolve/orchestration/status", handlers["orchestration_status"])
    app.router.add_get("/api/evolve/orchestration/plan", handlers["orchestration_plan"])
    app.router.add_post("/api/evolve/loop/start", handlers["start"])
    app.router.add_post("/api/evolve/loop/pause", handlers["pause"])
    app.router.add_post("/api/evolve/loop/approve/{approval_id}", handlers["approve"])
    app.router.add_post("/api/evolve/loop/reject/{approval_id}", handlers["reject"])
