"""Thomas reviews his own recent sessions and writes the friction report.

The "automated Calvin": instead of the owner reading chats and telling us
what hurt, Thomas reads his OWN recent conversations, the issue ledger, and
task outcomes, then writes the prioritized report a product owner would —
where users repeated themselves, where tasks failed or stalled, what to fix
first. GET /api/self-review generates it on demand and saves a copy to
runtime/logs/self_review.md so improvement passes start from evidence.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.server.issue_ledger import summarize as summarize_issues

log = logging.getLogger(__name__)

_MAX_SESSIONS = 12
_MAX_MSGS_PER_SESSION = 14
_MAX_MSG_CHARS = 300
_REVIEW_SYSTEM = (
    "You are Thomas reviewing your OWN recent performance as an AI assistant, the way a "
    "sharp product owner would. You are given real conversation excerpts, an issue/friction "
    "ledger, and task outcomes. Write a terse, prioritized markdown report:\n"
    "1. TOP FRICTION — the 3-6 worst user experiences, each with a one-line quote or "
    "evidence reference and WHY it hurt (repeated asks, retries, cancels, silent failures, "
    "false claims of completion, confusing replies).\n"
    "2. FAILURES — tasks that failed or stalled, with the apparent root cause.\n"
    "3. FIX FIRST — the single highest-leverage fix, and the next two.\n"
    "Be specific and honest; never invent evidence; if the window is quiet, say so briefly."
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _recent_session_excerpts(store_dir: Path, cutoff: datetime) -> list[str]:
    """Bounded plain-text excerpts of recently-active sessions, newest first."""
    rows: list[tuple[float, Path]] = []
    try:
        for path in store_dir.glob("chat_*.json"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if datetime.fromtimestamp(mtime, tz=timezone.utc) >= cutoff:
                rows.append((mtime, path))
    except OSError:
        return []
    rows.sort(reverse=True)
    excerpts: list[str] = []
    for _mtime, path in rows[:_MAX_SESSIONS]:
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        msgs = data.get("conversation", {}).get("messages") or data.get("messages") or []
        lines: list[str] = []
        for msg in msgs[-_MAX_MSGS_PER_SESSION:]:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "")
            content = msg.get("content")
            if isinstance(content, list):
                content = " ".join(str(p.get("text", "")) for p in content if isinstance(p, dict))
            text = " ".join(str(content or "").split())[:_MAX_MSG_CHARS]
            if role in ("user", "assistant") and text:
                lines.append(f"{role}: {text}")
        if lines:
            excerpts.append(f"[session {str(data.get('session_id') or path.stem)[:18]}]\n" + "\n".join(lines))
    return excerpts


def _recent_task_outcomes(cutoff: datetime) -> list[str]:
    """One line per recently-updated delegated task: state + summary + blocker."""
    out: list[str] = []
    tasks_dir = _repo_root() / "runtime" / "coordination" / "task_bots"
    try:
        paths = sorted(tasks_dir.glob("exec-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return []
    for path in paths[:40]:
        try:
            if datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc) < cutoff:
                break
            row = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        state = str(row.get("state") or "")
        summary = " ".join(str(row.get("summary") or "").split())[:120]
        blocker = str(row.get("blocker") or "")
        line = f"{state}: {summary}" + (f" (blocker: {blocker})" if blocker else "")
        out.append(line)
    return out


async def generate_self_review(app: web.Application, *, hours: int = 24) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, hours))
    from thomas.server.routes.chat_v2_keys import APP_SESSION_STORE

    store = app.get(APP_SESSION_STORE)
    store_dir = getattr(store, "_store_dir", None)
    excerpts = _recent_session_excerpts(Path(store_dir), cutoff) if store_dir else []
    issues = summarize_issues(hours=hours)
    tasks = _recent_task_outcomes(cutoff)
    corpus = (
        f"WINDOW: last {hours}h\n\n"
        "== ISSUE / FRICTION LEDGER ==\n"
        + json.dumps({k: issues[k] for k in ("total", "by_kind", "by_surface")}, ensure_ascii=False)
        + "\n"
        + "\n".join(
            f"- {row.get('ts', '')} {row.get('surface', '')}/{row.get('kind', '')}: {row.get('message', '')}"
            for row in issues.get("recent", [])
        )
        + "\n\n== TASK OUTCOMES ==\n"
        + ("\n".join(f"- {line}" for line in tasks) or "(none)")
        + "\n\n== CONVERSATION EXCERPTS ==\n"
        + ("\n\n".join(excerpts) or "(no recent sessions)")
    )
    from thomas.server.routes.chat_v2_announcements import _announce_llm

    llm = _announce_llm(app, "self-review")
    if llm is None or not hasattr(llm, "chat"):
        return {"ok": False, "error": "no_llm"}
    try:
        response = await asyncio.wait_for(
            llm.chat(
                [
                    {"role": "system", "content": _REVIEW_SYSTEM},
                    {"role": "user", "content": corpus[:120_000]},
                ]
            ),
            timeout=120,
        )
        report = str((response or {}).get("text") or "").strip()
    except (asyncio.TimeoutError, AttributeError, RuntimeError, OSError, TypeError, ValueError) as exc:
        log.warning("self-review generation failed: %s", exc)
        return {"ok": False, "error": f"generation_failed: {type(exc).__name__}"}
    if not report:
        return {"ok": False, "error": "empty_report"}
    stamped = f"# Thomas self-review — {datetime.now(timezone.utc).isoformat()[:16]}Z (last {hours}h)\n\n{report}\n"
    try:
        out_path = _repo_root() / "runtime" / "logs" / "self_review.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(stamped, encoding="utf-8")
    except OSError:
        pass
    return {
        "ok": True,
        "report": stamped,
        "sessions_reviewed": len(excerpts),
        "issues_in_window": issues.get("total", 0),
    }


async def handle_self_review(request: web.Request) -> web.Response:
    try:
        hours = max(1, min(24 * 7, int(request.query.get("hours", "24"))))
    except (TypeError, ValueError):
        hours = 24
    result = await generate_self_review(request.app, hours=hours)
    return web.json_response(result, status=200 if result.get("ok") else 503)


__all__ = ["generate_self_review", "handle_self_review"]
