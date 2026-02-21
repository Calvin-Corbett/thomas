from __future__ import annotations

import importlib
import json
import re
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, field_validator

from thomas.core.persistence import get_persistence

router = APIRouter()

Priority = Literal["low", "medium", "high"]
Status = Literal["open", "in_progress", "done"]

PRIORITY_ORDER: Dict[str, int] = {"high": 0, "medium": 1, "low": 2}
STATUS_ALIASES: Dict[str, Status] = {
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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _coerce_priority(v: Any) -> Priority:
    s = str(v).strip().lower()
    if s not in ("low", "medium", "high"):
        raise HTTPException(status_code=422, detail="priority must be low|medium|high")
    return s  # type: ignore[return-value]


def _coerce_status(v: Any) -> Status:
    s = str(v).strip().lower()
    if s in STATUS_ALIASES:
        return STATUS_ALIASES[s]
    raise HTTPException(
        status_code=422,
        detail='status must be "open"|"in_progress"|"done" (aliases allowed: todo/doing/closed/etc)',
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


def _parse_iso(v: Any) -> Optional[datetime]:
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


def _parse_rank(v: Any) -> Optional[float]:
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


def _coerce_tags(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, list):
        out = []
        for x in v:
            s = str(x).strip()
            if s:
                out.append(s[:64])
        # de-dupe, preserve order
        seen = set()
        dedup = []
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
    # comma/space separated
    parts = re.split(r"[,\n]+", s)
    out = []
    for p in parts:
        pp = p.strip()
        if pp:
            out.append(pp[:64])
    seen = set()
    dedup = []
    for t in out:
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        dedup.append(t)
    return dedup[:16]


def _normalize_goal(g: Dict[str, Any]) -> Dict[str, Any]:
    gg = dict(g)

    gid = gg.get("id")
    if gid is None:
        gid = f"goal_{abs(hash((gg.get('text',''), gg.get('created',''))))}"
    gg["id"] = str(gid)

    if not gg.get("created"):
        gg["created"] = _utc_now_iso()

    raw_status = gg.get("status", "open")
    try:
        gg["status"] = _coerce_status(raw_status)
    except HTTPException:
        gg["status"] = "open"

    raw_pri = gg.get("priority", "medium")
    try:
        gg["priority"] = _coerce_priority(raw_pri)
    except HTTPException:
        gg["priority"] = "medium"

    r = _parse_rank(gg.get("rank"))
    if r is not None:
        gg["rank"] = r
    elif "rank" in gg:
        gg.pop("rank", None)

    gg["tags"] = _coerce_tags(gg.get("tags"))

    # due_at should be ISO string or epoch; normalize to ISO string for UI
    due_dt = _parse_iso(gg.get("due_at"))
    if due_dt:
        gg["due_at"] = due_dt.isoformat()
    elif "due_at" in gg and gg.get("due_at") is None:
        gg.pop("due_at", None)

    # done_at is useful for lead-time metrics
    done_dt = _parse_iso(gg.get("done_at"))
    if done_dt:
        gg["done_at"] = done_dt.isoformat()
    elif "done_at" in gg and gg.get("done_at") is None:
        gg.pop("done_at", None)

    # optional fields used by UI
    for k in ("notes", "estimate_minutes", "archived", "updated"):
        if k in gg and gg[k] is None:
            gg.pop(k, None)

    # Ensure notes is a string if present
    if "notes" in gg and not isinstance(gg["notes"], str):
        gg["notes"] = str(gg["notes"])

    # Ensure archived is bool
    if "archived" in gg:
        gg["archived"] = bool(gg["archived"])

    return gg


def _find_goal(pe: Any, goal_id: str) -> Optional[Dict[str, Any]]:
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


def _top_rank_for_status(goals: List[Dict[str, Any]], status: str) -> float:
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


def _group_and_sort(goals: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {"open": [], "in_progress": [], "done": []}
    for g in goals:
        ng = _normalize_goal(g)
        grouped[ng["status"]].append(ng)

    def sort_key(g: Dict[str, Any]) -> Tuple[int, float, int, int, float]:
        # rank (manual ordering) dominates
        r = _parse_rank(g.get("rank"))
        has_rank = 0 if r is not None else 1
        rank_val = r if r is not None else 0.0

        pri = PRIORITY_ORDER.get(g.get("priority", "medium"), 1)

        # due soon comes earlier (only when no rank)
        due = _parse_ts_seconds(g.get("due_at"))
        due_bucket = 0 if due > 0 else 1
        due_val = due if due > 0 else 0.0

        created_ts = _parse_ts_seconds(g.get("created"))

        return (has_rank, rank_val, pri, due_bucket, due_val - created_ts * 0.0)  # stable

    for k in grouped:
        grouped[k].sort(key=sort_key)

    return grouped


def _etag_for_payload(payload: Any) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return sha256(blob).hexdigest()


def _resolve_initiative_enqueue() -> Tuple[Any, str]:
    module_candidates = (
        "thomas.core.initiative",
        "thomas.core.initiative_engine",
        "thomas.initiative",
        "thomas.initiative_engine",
    )
    getter_candidates = ("get_initiative_engine", "get_engine", "get_initiative", "engine")
    enqueue_candidates = ("queue_goal", "enqueue_goal", "submit_goal", "run_goal", "queue")

    errors: List[str] = []

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

    raise HTTPException(
        status_code=501,
        detail={
            "error": "initiative engine not found",
            "probe_errors": errors[-6:],
        },
    )


def _call_enqueue(enqueue_fn: Any, goal: Dict[str, Any]) -> None:
    try:
        try:
            enqueue_fn(goal)
        except TypeError:
            enqueue_fn(str(goal.get("id")))
    except Exception:
        return


class GoalCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=10_000)
    priority: Priority = "medium"
    due_at: Optional[str] = None  # ISO8601 or epoch-ish string; stored as-is and normalized
    tags: Optional[List[str]] = None
    notes: Optional[str] = None


class GoalPatch(BaseModel):
    status: Optional[str] = None
    text: Optional[str] = Field(None, min_length=1, max_length=10_000)
    priority: Optional[str] = None
    rank: Optional[float] = None
    due_at: Optional[str] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None
    estimate_minutes: Optional[int] = None
    archived: Optional[bool] = None

    @field_validator("rank")
    @classmethod
    def _rank_is_finite(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError("rank must be a finite number")
        return float(v)

    @field_validator("estimate_minutes")
    @classmethod
    def _estimate_range(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return None
        if v < 0 or v > 10_000:
            raise ValueError("estimate_minutes out of range")
        return int(v)


@router.get("/goals")
def goals_page() -> FileResponse:
    web_dir = Path(__file__).resolve().parents[1] / "web"
    page = web_dir / "goals.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="goals.html not found")
    return FileResponse(str(page))


@router.get("/goals.js")
def goals_js() -> FileResponse:
    web_dir = Path(__file__).resolve().parents[1] / "web"
    js = web_dir / "goals.js"
    if not js.exists():
        raise HTTPException(status_code=404, detail="goals.js not found")
    return FileResponse(str(js), media_type="application/javascript")


@router.get("/api/goals")
def get_goals(request: Request) -> Response:
    pe = get_persistence()
    goals = getattr(pe, "goals", []) or []
    payload = _group_and_sort(list(goals))

    etag = _etag_for_payload(payload)
    inm = (request.headers.get("if-none-match") or "").strip().lower()

    headers = {"ETag": etag, "Cache-Control": "no-store"}
    if inm and inm == etag.lower():
        return Response(status_code=304, headers=headers)
    return JSONResponse(payload, headers=headers)


@router.get("/api/goals/stats")
def goals_stats(request: Request) -> Response:
    """
    Small â€œconsumer loveâ€ endpoint: dashboard stats.
    Safe to ignore if you don't need it.
    """
    pe = get_persistence()
    goals = [_normalize_goal(g) for g in (getattr(pe, "goals", []) or [])]
    now = _utc_now()

    open_n = sum(1 for g in goals if g.get("status") == "open" and not g.get("archived"))
    ip_n = sum(1 for g in goals if g.get("status") == "in_progress" and not g.get("archived"))
    done_n = sum(1 for g in goals if g.get("status") == "done" and not g.get("archived"))

    # done today
    done_today = 0
    lead_hours = []
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
        "open": open_n,
        "in_progress": ip_n,
        "done": done_n,
        "done_today": done_today,
        "avg_lead_hours": avg_lead_h,
        "generated_at": now.isoformat(),
    }

    etag = _etag_for_payload(payload)
    inm = (request.headers.get("if-none-match") or "").strip().lower()
    headers = {"ETag": etag, "Cache-Control": "no-store"}
    if inm and inm == etag.lower():
        return Response(status_code=304, headers=headers)
    return JSONResponse(payload, headers=headers)


@router.post("/api/goals")
def create_goal(payload: GoalCreate) -> Dict[str, Any]:
    pe = get_persistence()
    priority = _coerce_priority(payload.priority)
    text = payload.text.strip()

    add_goal = getattr(pe, "add_goal", None)
    if not callable(add_goal):
        raise HTTPException(status_code=500, detail="Persistence engine missing add_goal()")

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
                if payload.due_at:
                    g["due_at"] = payload.due_at
                if payload.tags:
                    g["tags"] = payload.tags
                if payload.notes:
                    g["notes"] = payload.notes
    except Exception:
        pass

    _commit(pe)

    if isinstance(result, dict):
        return {"ok": True, "goal": _normalize_goal(result)}
    if result is not None:
        found = _find_goal(pe, str(result))
        if found:
            return {"ok": True, "goal": _normalize_goal(found)}

    # fallback: newest match by text
    goals = getattr(pe, "goals", []) or []
    matches = [g for g in goals if str(g.get("text", "")).strip() == text]
    if matches:
        matches.sort(key=lambda g: -_parse_ts_seconds(g.get("created")))
        return {"ok": True, "goal": _normalize_goal(matches[0])}

    return {"ok": True, "goal": {"id": str(result) if result is not None else "unknown", "text": text, "priority": priority, "status": "open", "created": _utc_now_iso()}}


@router.patch("/api/goals/{goal_id}")
def update_goal(goal_id: str, payload: GoalPatch) -> Dict[str, Any]:
    pe = get_persistence()
    g = _find_goal(pe, goal_id)
    if not g:
        raise HTTPException(status_code=404, detail="Goal not found")

    # text
    if payload.text is not None:
        g["text"] = payload.text.strip()

    # priority
    if payload.priority is not None:
        g["priority"] = _coerce_priority(payload.priority)

    # notes/tags/due/estimate/archive
    if payload.notes is not None:
        g["notes"] = payload.notes
    if payload.tags is not None:
        g["tags"] = payload.tags
    if payload.due_at is not None:
        if payload.due_at.strip() == "":
            g.pop("due_at", None)
        else:
            g["due_at"] = payload.due_at
    if payload.estimate_minutes is not None:
        g["estimate_minutes"] = int(payload.estimate_minutes)
    if payload.archived is not None:
        g["archived"] = bool(payload.archived)

    status_changed = False
    if payload.status is not None:
        new_status = _coerce_status(payload.status)
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
            # reopening clears done_at
            if prev == "done":
                g.pop("done_at", None)
        status_changed = True

    # rank ordering within column (optional)
    if payload.rank is not None:
        g["rank"] = float(payload.rank)
    elif status_changed:
        try:
            goals = getattr(pe, "goals", []) or []
            g["rank"] = _top_rank_for_status(goals, str(g.get("status", "open")))
        except Exception:
            pass

    g["updated"] = _utc_now_iso()
    _commit(pe)

    g2 = _find_goal(pe, goal_id) or g
    return {"ok": True, "goal": _normalize_goal(g2)}


@router.delete("/api/goals/{goal_id}")
def delete_goal(goal_id: str) -> Dict[str, Any]:
    pe = get_persistence()

    delete_fn = getattr(pe, "delete_goal", None)
    if callable(delete_fn):
        delete_fn(goal_id)
        _commit(pe)
        return {"ok": True}

    goals = getattr(pe, "goals", []) or []
    before = len(goals)
    goals[:] = [g for g in goals if str(g.get("id")) != str(goal_id)]
    after = len(goals)

    if before == after:
        raise HTTPException(status_code=404, detail="Goal not found")

    _commit(pe)
    return {"ok": True}


@router.post("/api/goals/{goal_id}/run")
def run_goal(goal_id: str, background: BackgroundTasks) -> JSONResponse:
    pe = get_persistence()
    g = _find_goal(pe, goal_id)
    if not g:
        raise HTTPException(status_code=404, detail="Goal not found")

    goal = _normalize_goal(g)
    enqueue_fn, how = _resolve_initiative_enqueue()

    background.add_task(_call_enqueue, enqueue_fn, goal)
    return JSONResponse({"ok": True, "queued": True, "how": how})

