"""aiohttp route registration for goals / task-board endpoints."""

from __future__ import annotations

import asyncio
import importlib
import json
import re
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Literal
from collections.abc import Awaitable, Callable

from aiohttp import web

from thomas.core.persistence import get_persistence

RequireAccessFn = Callable[[web.Request], None]
ReadJsonFn = Callable[[web.Request], Awaitable[Any]]

Priority = Literal["low", "medium", "high"]
Status = Literal["open", "in_progress", "done"]

PRIORITY_ORDER: dict[str, int] = {"high": 0, "medium": 1, "low": 2}
STATUS_ALIASES: dict[str, Status] = {
    "open": "open",
    "todo": "open",
    "new": "open",
    "pending": "open",
    "backlog": "open",
    "in_progress": "in_progress",
    "inprogress": "in_progress",
    "doing": "in_progress",
    "active": "in_progress",
    "working": "in_progress",
    "wip": "in_progress",
    "done": "done",
    "closed": "done",
    "complete": "done",
    "completed": "done",
    "finished": "done",
}


# ── pure helpers (framework-agnostic) ──


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _coerce_priority(v: Any) -> Priority:
    s = str(v).strip().lower()
    if s not in ("low", "medium", "high"):
        raise web.HTTPUnprocessableEntity(text="priority must be low|medium|high")
    return s  # type: ignore[return-value]


def _coerce_status(v: Any) -> Status:
    s = str(v).strip().lower()
    if s in STATUS_ALIASES:
        return STATUS_ALIASES[s]
    raise web.HTTPUnprocessableEntity(
        text='status must be "open"|"in_progress"|"done" (aliases: todo/doing/closed/etc)',
    )


def _parse_ts_seconds(v: Any) -> float:
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        f = float(v)
        return (f / 1000.0) if f > 2_000_000_000 else f
    s = str(v).strip()
    if not s:
        return 0.0
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return 0.0


def _parse_iso(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        sec = _parse_ts_seconds(v)
        if sec <= 0:
            return None
        return datetime.fromtimestamp(sec, tz=timezone.utc)
    s = str(v).strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _parse_rank(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return f
    s = str(v).strip()
    if not s:
        return None
    try:
        f = float(s)
        if f != f or f in (float("inf"), float("-inf")):
            return None
        return f
    except Exception:
        return None


def _coerce_tags(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        out = []
        for x in v:
            s = str(x).strip()
            if s:
                out.append(s[:64])
        seen: set[str] = set()
        dedup: list[str] = []
        for t in out:
            k = t.lower()
            if k in seen:
                continue
            seen.add(k)
            dedup.append(t)
        return dedup[:16]
    s = str(v).strip()
    if not s:
        return []
    parts = re.split(r"[,\n]+", s)
    out = []
    for p in parts:
        pp = p.strip()
        if pp:
            out.append(pp[:64])
    seen2: set[str] = set()
    dedup2: list[str] = []
    for t in out:
        k = t.lower()
        if k in seen2:
            continue
        seen2.add(k)
        dedup2.append(t)
    return dedup2[:16]


def _normalize_goal(g: dict[str, Any]) -> dict[str, Any]:
    gg = dict(g)

    gid = gg.get("id")
    if gid is None:
        gid = f"goal_{abs(hash((gg.get('text', ''), gg.get('created', ''))))}"
    gg["id"] = str(gid)

    if not gg.get("created"):
        gg["created"] = _utc_now_iso()

    raw_status = gg.get("status", "open")
    try:
        gg["status"] = _coerce_status(raw_status)
    except web.HTTPUnprocessableEntity:
        gg["status"] = "open"

    raw_pri = gg.get("priority", "medium")
    try:
        gg["priority"] = _coerce_priority(raw_pri)
    except web.HTTPUnprocessableEntity:
        gg["priority"] = "medium"

    r = _parse_rank(gg.get("rank"))
    if r is not None:
        gg["rank"] = r
    elif "rank" in gg:
        gg.pop("rank", None)

    gg["tags"] = _coerce_tags(gg.get("tags"))

    due_dt = _parse_iso(gg.get("due_at"))
    if due_dt:
        gg["due_at"] = due_dt.isoformat()
    elif "due_at" in gg and gg.get("due_at") is None:
        gg.pop("due_at", None)

    done_dt = _parse_iso(gg.get("done_at"))
    if done_dt:
        gg["done_at"] = done_dt.isoformat()
    elif "done_at" in gg and gg.get("done_at") is None:
        gg.pop("done_at", None)

    for k in ("notes", "estimate_minutes", "archived", "updated"):
        if k in gg and gg[k] is None:
            gg.pop(k, None)

    if "notes" in gg and not isinstance(gg["notes"], str):
        gg["notes"] = str(gg["notes"])

    if "archived" in gg:
        gg["archived"] = bool(gg["archived"])

    return gg


def _find_goal(pe: Any, goal_id: str) -> dict[str, Any] | None:
    goals = getattr(pe, "goals", []) or []
    for g in goals:
        if str(g.get("id")) == str(goal_id):
            return g
    return None


def _commit(pe: Any) -> None:
    for name in ("save", "flush", "commit", "sync", "persist", "write"):
        fn = getattr(pe, name, None)
        if callable(fn):
            try:
                fn()
            except TypeError:
                pass
            except Exception:
                pass
            return


def _top_rank_for_status(goals: list[dict[str, Any]], status: str) -> float:
    ranks = []
    for g in goals:
        if str(g.get("status")) != status:
            continue
        r = _parse_rank(g.get("rank"))
        if r is not None:
            ranks.append(r)
    if not ranks:
        return 0.0
    return min(ranks) - 1.0


def _group_and_sort(goals: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {"open": [], "in_progress": [], "done": []}
    for g in goals:
        ng = _normalize_goal(g)
        grouped[ng["status"]].append(ng)

    def sort_key(g: dict[str, Any]) -> tuple[int, float, int, int, float]:
        r = _parse_rank(g.get("rank"))
        has_rank = 0 if r is not None else 1
        rank_val = r if r is not None else 0.0
        pri = PRIORITY_ORDER.get(g.get("priority", "medium"), 1)
        due = _parse_ts_seconds(g.get("due_at"))
        due_bucket = 0 if due > 0 else 1
        due_val = due if due > 0 else 0.0
        created_ts = _parse_ts_seconds(g.get("created"))
        return (has_rank, rank_val, pri, due_bucket, due_val - created_ts * 0.0)

    for k in grouped:
        grouped[k].sort(key=sort_key)

    return grouped


def _etag_for_payload(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return sha256(blob).hexdigest()


def _resolve_initiative_enqueue() -> tuple[Any, str]:
    module_candidates = (
        "thomas.core.initiative",
        "thomas.core.initiative_engine",
        "thomas.initiative",
        "thomas.initiative_engine",
    )
    getter_candidates = ("get_initiative_engine", "get_engine", "get_initiative", "engine")
    enqueue_candidates = ("queue_goal", "enqueue_goal", "submit_goal", "run_goal", "queue")

    errors: list[str] = []

    for mod_name in module_candidates:
        try:
            mod = importlib.import_module(mod_name)
        except Exception as e:
            errors.append(f"{mod_name}: {e}")
            continue

        engine: Any = None
        for getter_name in getter_candidates:
            getter = getattr(mod, getter_name, None)
            if callable(getter):
                try:
                    engine = getter()
                    break
                except Exception as e:
                    errors.append(f"{mod_name}.{getter_name}(): {e}")
            elif getter_name == "engine" and getter is not None:
                engine = getter
                break

        if engine is None:
            engine = mod

        for fn_name in enqueue_candidates:
            fn = getattr(engine, fn_name, None)
            if callable(fn):
                return fn, f"{mod_name}.{fn_name}"

        errors.append(f"{mod_name}: no enqueue method found")

    raise web.HTTPNotImplemented(
        text=json.dumps({
            "error": "initiative engine not found",
            "probe_errors": errors[-6:],
        }),
    )


def _call_enqueue(enqueue_fn: Any, goal: dict[str, Any]) -> None:
    try:
        try:
            enqueue_fn(goal)
        except TypeError:
            enqueue_fn(str(goal.get("id")))
    except Exception:
        return


# ── validation helpers (replace Pydantic models) ──


def _validate_goal_create(data: dict[str, Any]) -> dict[str, Any]:
    text = str(data.get("text") or "").strip()
    if not text:
        raise web.HTTPBadRequest(text="text is required")
    if len(text) > 10_000:
        raise web.HTTPBadRequest(text="text must be <= 10,000 characters")

    priority = _coerce_priority(data.get("priority", "medium"))
    due_at = data.get("due_at")
    tags = _coerce_tags(data.get("tags"))
    notes = data.get("notes")
    if notes is not None:
        notes = str(notes)

    return {
        "text": text,
        "priority": priority,
        "due_at": due_at,
        "tags": tags,
        "notes": notes,
    }


def _validate_goal_patch(data: dict[str, Any]) -> dict[str, Any]:
    patch: dict[str, Any] = {}

    if "status" in data and data["status"] is not None:
        patch["status"] = str(data["status"])

    if "text" in data and data["text"] is not None:
        text = str(data["text"]).strip()
        if not text:
            raise web.HTTPBadRequest(text="text must not be empty")
        if len(text) > 10_000:
            raise web.HTTPBadRequest(text="text must be <= 10,000 characters")
        patch["text"] = text

    if "priority" in data and data["priority"] is not None:
        patch["priority"] = str(data["priority"])

    if "rank" in data and data["rank"] is not None:
        r = _parse_rank(data["rank"])
        if r is None:
            raise web.HTTPBadRequest(text="rank must be a finite number")
        patch["rank"] = r

    if "due_at" in data:
        patch["due_at"] = data["due_at"]

    if "tags" in data:
        patch["tags"] = _coerce_tags(data["tags"])

    if "notes" in data and data["notes"] is not None:
        patch["notes"] = str(data["notes"])

    if "estimate_minutes" in data and data["estimate_minutes"] is not None:
        try:
            em = int(data["estimate_minutes"])
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(text="estimate_minutes must be an integer")
        if em < 0 or em > 10_000:
            raise web.HTTPBadRequest(text="estimate_minutes out of range (0-10000)")
        patch["estimate_minutes"] = em

    if "archived" in data and data["archived"] is not None:
        patch["archived"] = bool(data["archived"])

    return patch


# ── route registration ──


def register_goals_routes(
    app: web.Application,
    *,
    require_api_access: RequireAccessFn,
    read_json: ReadJsonFn,
) -> None:
    """Register /api/goals/* routes on *app*."""

    # ── GET /api/goals ──

    async def api_goals_list(request: web.Request) -> web.Response:
        require_api_access(request)
        pe = get_persistence()
        goals = getattr(pe, "goals", []) or []
        payload = _group_and_sort(list(goals))

        etag = _etag_for_payload(payload)
        inm = (request.headers.get("If-None-Match") or "").strip().lower()

        headers = {"ETag": etag, "Cache-Control": "no-store"}
        if inm and inm == etag.lower():
            return web.Response(status=304, headers=headers)
        return web.json_response(payload, headers=headers)

    # ── GET /api/goals/stats ──

    async def api_goals_stats(request: web.Request) -> web.Response:
        """Dashboard stats: open/ip/done counts, lead time."""
        require_api_access(request)
        pe = get_persistence()
        goals = [_normalize_goal(g) for g in (getattr(pe, "goals", []) or [])]
        now = _utc_now()

        open_n = sum(1 for g in goals if g.get("status") == "open" and not g.get("archived"))
        ip_n = sum(1 for g in goals if g.get("status") == "in_progress" and not g.get("archived"))
        done_n = sum(1 for g in goals if g.get("status") == "done" and not g.get("archived"))

        done_today = 0
        lead_hours: list[float] = []
        for g in goals:
            if g.get("status") != "done":
                continue
            done_dt = _parse_iso(g.get("done_at"))
            if done_dt and done_dt.date() == now.date():
                done_today += 1
            created_dt = _parse_iso(g.get("created"))
            if created_dt and done_dt:
                lead_hours.append((done_dt - created_dt).total_seconds() / 3600.0)

        avg_lead_h = round(sum(lead_hours) / len(lead_hours), 2) if lead_hours else None

        payload = {
            "open_n": open_n,
            "ip_n": ip_n,
            "done_n": done_n,
            "done_today": done_today,
            "avg_lead_hours": avg_lead_h,
            "generated_at": now.isoformat(),
        }

        etag = _etag_for_payload(payload)
        inm = (request.headers.get("If-None-Match") or "").strip().lower()
        headers = {"ETag": etag, "Cache-Control": "no-store"}
        if inm and inm == etag.lower():
            return web.Response(status=304, headers=headers)
        return web.json_response(payload, headers=headers)

    # ── POST /api/goals ──

    async def api_goals_create(request: web.Request) -> web.Response:
        require_api_access(request)
        data = await read_json(request)
        if not isinstance(data, dict):
            raise web.HTTPBadRequest(text="expected JSON object")
        validated = _validate_goal_create(data)

        pe = get_persistence()
        text = validated["text"]
        priority = validated["priority"]

        add_goal = getattr(pe, "add_goal", None)
        if not callable(add_goal):
            raise web.HTTPInternalServerError(text="Persistence engine missing add_goal()")

        result = add_goal(text, priority=priority)

        # best-effort: set rank so new goals appear at top of Open
        try:
            goals = getattr(pe, "goals", []) or []
            top_rank = _top_rank_for_status(goals, "open")

            gid = None
            if isinstance(result, dict):
                gid = str(result.get("id"))
            elif result is not None:
                gid = str(result)

            if gid:
                g = _find_goal(pe, gid)
                if g is None and isinstance(result, dict):
                    g = result
                if g is not None:
                    g.setdefault("status", "open")
                    g["rank"] = top_rank
                    if validated["due_at"]:
                        g["due_at"] = validated["due_at"]
                    if validated["tags"]:
                        g["tags"] = validated["tags"]
                    if validated["notes"]:
                        g["notes"] = validated["notes"]
        except Exception:
            pass

        _commit(pe)

        if isinstance(result, dict):
            return web.json_response({"ok": True, "goal": _normalize_goal(result)})
        if result is not None:
            found = _find_goal(pe, str(result))
            if found:
                return web.json_response({"ok": True, "goal": _normalize_goal(found)})

        # fallback: newest match by text
        goals = getattr(pe, "goals", []) or []
        matches = [g for g in goals if str(g.get("text", "")).strip() == text]
        if matches:
            matches.sort(key=lambda g: -_parse_ts_seconds(g.get("created")))
            return web.json_response({"ok": True, "goal": _normalize_goal(matches[0])})

        return web.json_response({
            "ok": True,
            "goal": {
                "id": str(result) if result is not None else "unknown",
                "text": text,
                "priority": priority,
                "status": "open",
                "created": _utc_now_iso(),
            },
        })

    # ── PATCH /api/goals/{goal_id} ──

    async def api_goals_update(request: web.Request) -> web.Response:
        require_api_access(request)
        goal_id = request.match_info["goal_id"]
        data = await read_json(request)
        if not isinstance(data, dict):
            raise web.HTTPBadRequest(text="expected JSON object")
        patch = _validate_goal_patch(data)

        pe = get_persistence()
        g = _find_goal(pe, goal_id)
        if not g:
            raise web.HTTPNotFound(text="Goal not found")

        if "text" in patch:
            g["text"] = patch["text"]

        if "priority" in patch:
            g["priority"] = _coerce_priority(patch["priority"])

        if "notes" in patch:
            g["notes"] = patch["notes"]
        if "tags" in patch:
            g["tags"] = patch["tags"]
        if "due_at" in patch:
            if patch["due_at"] is not None and str(patch["due_at"]).strip() == "":
                g.pop("due_at", None)
            else:
                g["due_at"] = patch["due_at"]
        if "estimate_minutes" in patch:
            g["estimate_minutes"] = patch["estimate_minutes"]
        if "archived" in patch:
            g["archived"] = patch["archived"]

        status_changed = False
        if "status" in patch:
            new_status = _coerce_status(patch["status"])
            prev = str(g.get("status", "open"))
            if new_status == "done":
                close_goal = getattr(pe, "close_goal", None)
                if callable(close_goal):
                    close_goal(goal_id)
                g["status"] = "done"
                if not g.get("done_at"):
                    g["done_at"] = _utc_now_iso()
            else:
                g["status"] = new_status
                if prev == "done":
                    g.pop("done_at", None)
            status_changed = True

        if "rank" in patch:
            g["rank"] = patch["rank"]
        elif status_changed:
            try:
                goals = getattr(pe, "goals", []) or []
                g["rank"] = _top_rank_for_status(goals, str(g.get("status", "open")))
            except Exception:
                pass

        g["updated"] = _utc_now_iso()
        _commit(pe)

        g2 = _find_goal(pe, goal_id) or g
        return web.json_response({"ok": True, "goal": _normalize_goal(g2)})

    # ── DELETE /api/goals/{goal_id} ──

    async def api_goals_delete(request: web.Request) -> web.Response:
        require_api_access(request)
        goal_id = request.match_info["goal_id"]

        pe = get_persistence()

        delete_fn = getattr(pe, "delete_goal", None)
        if callable(delete_fn):
            delete_fn(goal_id)
            _commit(pe)
            return web.json_response({"ok": True})

        goals = getattr(pe, "goals", []) or []
        before = len(goals)
        goals[:] = [g for g in goals if str(g.get("id")) != str(goal_id)]
        after = len(goals)

        if before == after:
            raise web.HTTPNotFound(text="Goal not found")

        _commit(pe)
        return web.json_response({"ok": True})

    # ── POST /api/goals/{goal_id}/run ──

    async def api_goals_run(request: web.Request) -> web.Response:
        require_api_access(request)
        goal_id = request.match_info["goal_id"]

        pe = get_persistence()
        g = _find_goal(pe, goal_id)
        if not g:
            raise web.HTTPNotFound(text="Goal not found")

        goal = _normalize_goal(g)
        enqueue_fn, how = _resolve_initiative_enqueue()

        loop = asyncio.get_event_loop()
        loop.call_soon(lambda: _call_enqueue(enqueue_fn, goal))

        return web.json_response({"ok": True, "queued": True, "how": how})

    # ── register ──

    app.router.add_get("/api/goals", api_goals_list)
    app.router.add_get("/api/goals/stats", api_goals_stats)
    app.router.add_post("/api/goals", api_goals_create)
    app.router.add_patch("/api/goals/{goal_id}", api_goals_update)
    app.router.add_delete("/api/goals/{goal_id}", api_goals_delete)
    app.router.add_post("/api/goals/{goal_id}/run", api_goals_run)
