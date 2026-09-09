
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
    "Be specific and honest; never invent evidence; if the window is quiet, say so briefly.\n"
    "Message excerpts are LENGTH-CAPPED for this review and a cut one ends with a "
    "[+N more chars…] marker. That marker means the excerpt was shortened here, NOT that the "
    "reply was cut off in front of the user — never report a truncated excerpt as an "
    "incomplete or interrupted answer."
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
            # Mark the cut. Silently truncating the evidence makes the reviewer
            # manufacture exactly the class of bug that truncation resembles: a
            # complete 1,200-char answer about IRAs, chopped at 300, was
            # reported as "the response terminated mid-answer" and filed as a
            # product failure with the cut point quoted as proof. A self-review
            # that invents defects from its own excerpting sends whoever acts on
            # it chasing something that never happened.
            full = " ".join(str(content or "").split())
            text = full[:_MAX_MSG_CHARS]
            if len(full) > _MAX_MSG_CHARS:
                text += f" [+{len(full) - _MAX_MSG_CHARS} more chars…]"
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


def _recent_feedback(store: Path, cutoff: datetime) -> list[str]:
    """One line per thumbs up/down the person gave a reply inside the window.

    The chat page's Good/Bad reply buttons append ``{at, session_id, message_id,
    rating, note}`` rows to ``.thomas/feedback.jsonl`` (2026-09-05); a review
    that never saw them would be grading Thomas against his own opinion only.
    """
    try:
        lines = Path(store).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[str] = []
    for raw in lines[-400:]:
        raw = raw.strip()
        if not raw:
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        try:
            at = datetime.fromisoformat(str(row.get("at") or "").replace("Z", "+00:00"))
        except ValueError:
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if at < cutoff:
            continue
        note = " ".join(str(row.get("note") or "").split())[:200]
        line = f"{at.isoformat(timespec='minutes')} {row.get('rating', '?')} on {row.get('session_id') or 'chat'}#{row.get('message_id', '')}"
        out.append(line + (f": {note}" if note else ""))
    return out


async def generate_self_review(app: web.Application, *, hours: int = 24) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, hours))
    from thomas.server.routes.chat_v2_keys import APP_SESSION_STORE

    store = app.get(APP_SESSION_STORE)
    store_dir = getattr(store, "_store_dir", None)
    excerpts = _recent_session_excerpts(Path(store_dir), cutoff) if store_dir else []
    issues = summarize_issues(hours=hours)
    tasks = _recent_task_outcomes(cutoff)
    feedback = _recent_feedback(_repo_root() / "runtime" / ".thomas" / "feedback.jsonl", cutoff)
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
        + "\n\n== WHAT THE PERSON SAID ABOUT REPLIES (thumbs) ==\n"
        + ("\n".join(f"- {line}" for line in feedback) or "(no ratings in the window)")
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


# A 24h-window report doesn't meaningfully change minute to minute; this just
# needs to be short enough that a caller sees "generating" turn into a real,
# freshly-stamped report within a couple of requests, not so short that every
# GET pays for a fresh 15-30s LLM call.
_REFRESH_TTL_SECONDS = 300.0

APP_SELF_REVIEW_CACHE = web.AppKey("self_review_cache", dict)


def _self_review_cache(app: web.Application) -> dict[str, Any]:
    """App-scoped so tests (fresh web.Application per test) never share state.

    The live server registers this key eagerly in `app_core.create_app`,
    before the app is handed to `AppRunner` (aiohttp freezes the Application
    at that point, and writing a new key into a frozen app is deprecated).
    The lazy init below is a fallback for callers -- chiefly this module's
    own unit tests -- that build a bare `web.Application()` directly and
    never go through `create_app`/freeze at all.
    """
    cache = app.get(APP_SELF_REVIEW_CACHE)
    if not isinstance(cache, dict):
        cache = {"lock": asyncio.Lock(), "entries": {}}
        app[APP_SELF_REVIEW_CACHE] = cache
    return cache


def _entry_for(cache: dict[str, Any], hours: int) -> dict[str, Any]:
    """Cached per `hours` window -- serving a 24h-window report for an `hours=1`
    request would be a fabrication the stamp alone couldn't disclose.

    Two clocks are tracked, deliberately kept separate:
    - `built_at`: when an ATTEMPT (success or failure) last finished. This is
      what throttles retries via the TTL -- it must be stamped even when the
      attempt crashed, or a broken generator relaunches on every request.
    - `result_built_at`: when the currently-held `result` was actually
      produced. This, not `built_at`, is what "stale" in the response means
      -- a failed refresh attempt must not make an old-but-still-correct
      report suddenly read as fresh.
    """
    entries: dict[int, dict[str, Any]] = cache["entries"]
    entry = entries.get(hours)
    if entry is None:
        # built_at/result_built_at stay None until they have something real
        # to record -- an explicit "never attempted"/"never built" rather
        # than a 0.0 that would rely on the event loop's monotonic clock
        # already being far from zero to force the first refresh.
        entry = {
            "result": None,
            "generated_at": None,
            "built_at": None,
            "result_built_at": None,
            "task": None,
            "error": None,
        }
        entries[hours] = entry
    return entry


async def _refresh_self_review_entry(app: web.Application, entry: dict[str, Any], hours: int) -> None:
    """Runs off the request path via asyncio.ensure_future.

    Every attempt -- success, a failure generate_self_review() itself caught
    and reported as {"ok": False}, or an exception that escaped it entirely
    (e.g. a KeyError/ImportError from the pre-LLM corpus assembly, outside
    generate_self_review's own internal try) -- must stamp `built_at`. A
    review of the first version of this fix found that an out-of-tuple
    exception left `built_at` untouched: the entry stayed "never attempted"
    forever, so the TTL never throttled (every request relaunched a broken
    generation) and `entry["error"]` never got set, so callers saw a
    permanently healthy-looking "generating" instead of ever reaching the
    error path -- the exact misreporting shape this task exists to fix,
    reintroduced one level down. `entry["task"]` holds a persistent
    reference to this Task, so asyncio's own GC-time "exception was never
    retrieved" logging does not fire while the server runs; the explicit
    log call below is what actually surfaces the failure. Catching broad and
    re-raising (rather than swallowing) both satisfies agent_safety.toml's
    broad-catch policy (logging + reraise) and keeps the exception
    retrievable by anything that does await this task, e.g. tests.
    """
    try:
        result = await generate_self_review(app, hours=hours)
    except Exception as exc:
        log.exception("self-review background refresh failed: %s", exc)
        entry["error"] = f"refresh_failed: {type(exc).__name__}"
        entry["built_at"] = asyncio.get_running_loop().time()
        raise
    entry["built_at"] = asyncio.get_running_loop().time()
    if result.get("ok"):
        entry["result"] = result
        entry["generated_at"] = datetime.now(timezone.utc).isoformat()
        entry["result_built_at"] = entry["built_at"]
        entry["error"] = None
    else:
        # Keep serving the last good report (if any) under its own honest,
        # aging stamp -- a transient LLM failure must not wipe a report that
        # was really generated, and must not touch result_built_at either
        # (the REPORT didn't get any older just because a refresh failed).
        # The failure itself is recorded and surfaced alongside that report;
        # the next request past the TTL gets to retry.
        entry["error"] = str(result.get("error") or "generation_failed")


async def handle_self_review(request: web.Request) -> web.Response:
    try:
        hours = max(1, min(24 * 7, int(request.query.get("hours", "24"))))
    except (TypeError, ValueError):
        hours = 24

    cache = _self_review_cache(request.app)
    async with cache["lock"]:
        entry = _entry_for(cache, hours)
        now = asyncio.get_running_loop().time()
        built_at = entry["built_at"]
        attempt_due = built_at is None or (now - built_at) >= _REFRESH_TTL_SECONDS
        task = entry.get("task")
        in_flight = task is not None and not task.done()
        if attempt_due and not in_flight:
            entry["task"] = asyncio.ensure_future(_refresh_self_review_entry(request.app, entry, hours))
            in_flight = True
        result = entry["result"]
        generated_at = entry["generated_at"]
        result_built_at = entry["result_built_at"]
        error = entry["error"]

    if result is not None:
        # Staleness reflects the RESULT's own age, never the attempt clock --
        # a failed refresh must not make an old report read as fresh just
        # because an attempt recently ran (and failed). Visible either way:
        # a fresh report, an old one still being served while a refresh
        # runs, or an old one whose latest refresh attempt failed.
        report_stale = result_built_at is None or (now - result_built_at) >= _REFRESH_TTL_SECONDS
        payload = {**result, "generated_at": generated_at, "stale": report_stale}
        if error:
            payload["refresh_error"] = error
        return web.json_response(payload, status=200)
    if in_flight:
        return web.json_response({"ok": True, "status": "generating"}, status=200)
    return web.json_response({"ok": False, "status": "error", "error": error or "generation_failed"}, status=503)


__all__ = ["generate_self_review", "handle_self_review"]
