from __future__ import annotations

import asyncio
import logging
import platform as _platform
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from thomas.agent.chat_dispatcher import dispatch_async
from thomas.agent.dispatch import should_dispatch
from thomas.core import task_bot_runtime
from thomas.core.file_access import PROJECT, clamp_file_access_level, file_access_spec
from thomas.core.task_titling import derive_task_title
from thomas.marketplace.orchestrator.bot_roster import pick_bot_for_specialist
from thomas.server import chat_delegation_live_repo as _live_repo_module
from thomas.server import chat_delegation_runner as _runner_module
from thomas.server.chat_delegation_canvas import canvas_start, is_canvas_task, run_canvas_worker

# Re-export every deliverable helper that external callers may import from this module.
# (Tests and routes do `from thomas.server.chat_delegation import _build_result_summary`
# etc., so these must stay at module scope as visible attributes.)
from thomas.server.chat_delegation_deliverable import (  # noqa: F401
    _FAILURE_LANGUAGE_RE,
    _artifacts_from_created,
    _build_result_summary,
    _claimed_filenames,
    _claims_action_success,
    _claims_file_creation,
    _files_changed_since,
    _handoff_block,
    _resolve_created,
    _snapshot_workspace_files,
    _worker_summary_line,
    _WorkerFatal,
    _WorkerRetry,
    _workspace_mtimes,
    executability_warning,
    prompt_needs_handoff,
    quality_tier_clause,
    render_report_pdfs,
    runtime_executability_warning,
)
from thomas.server.chat_delegation_emitter import _DelegationEmitter
from thomas.server.chat_delegation_live_repo import (  # noqa: F401
    _live_repo_files_changed_since,
    _live_repo_workspace_mtimes,
    _prompt_targets_live_thomas_repo,
    _with_live_repo_change_requirement,
)
from thomas.server.chat_delegation_runner import (  # noqa: F401
    _next_worker_event,
)
from thomas.server.chat_delegation_session import (  # noqa: F401
    _TERMINAL_TASK_STATES,
    _heartbeat_age_s,
    _normalize_record,
    _resolve_repo_root,
    _worker_has_started_progress,
    session_active_delegations,
)
from thomas.server.chat_delegation_worker_config import (  # noqa: F401
    _WORKER_FIRST_EVENT_TIMEOUT_S,
    _WORKER_IDLE_EVENT_TIMEOUT_S,
    PROVIDER_NATIVE_BACKEND,
    TASK_MANAGER_BACKEND,
    _agent_worker_runtime_profile,
    _helper_prompt,
    _infer_specialist,
    _replan_prompt,
    _requested_delegate_count,
    _self_recovery_attempts,
)
from thomas.server.worker_runtime import run_agent_worker_events

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]


def _sync_runner_legacy_globals() -> None:
    """Keep old chat_delegation monkeypatch surfaces effective after the module split."""
    _runner_module.run_agent_worker_events = run_agent_worker_events
    _runner_module._WORKER_FIRST_EVENT_TIMEOUT_S = _WORKER_FIRST_EVENT_TIMEOUT_S
    _runner_module._WORKER_IDLE_EVENT_TIMEOUT_S = _WORKER_IDLE_EVENT_TIMEOUT_S
    _runner_module._replan_prompt = _replan_prompt
    _runner_module._self_recovery_attempts = _self_recovery_attempts
    _runner_module._workspace_mtimes = _workspace_mtimes
    _live_repo_module._workspace_mtimes = _workspace_mtimes
    _runner_module._live_repo_workspace_mtimes = _live_repo_module._live_repo_workspace_mtimes


async def _run_agent_worker(*args: Any, **kwargs: Any) -> None:
    _sync_runner_legacy_globals()
    return await _runner_module._run_agent_worker(*args, **kwargs)


async def _run_agent_worker_supervised(*args: Any, **kwargs: Any) -> None:
    _sync_runner_legacy_globals()
    return await _runner_module._run_agent_worker_supervised(*args, **kwargs)


async def _run_exhaustive_worker(*args: Any, **kwargs: Any) -> None:
    _sync_runner_legacy_globals()
    return await _runner_module._run_exhaustive_worker(*args, **kwargs)


def build_active_task_digest(
    session_id: str,
    *,
    repo_root: str | Path | None = None,
    limit: int = 3,
) -> str:
    rows = session_active_delegations(session_id, repo_root=repo_root)
    if not rows:
        return ""
    lines = ["Background work in this chat: to change or stop a RUNNING one, call update_task with its [task <ref>]:"]
    for row in rows[: max(1, int(limit or 1))]:
        bot = str(row.get("bot_id") or "worker").strip() or "worker"
        state = str(row.get("state") or "requested").replace("_", " ")
        backend = str(row.get("backend_type") or TASK_MANAGER_BACKEND).replace("_", " ")
        ref = str(row.get("execution_id") or "").strip()
        # Lead with WHAT the task is (its subject) so the model can match the user's
        # reference ("cancel the jazz report") to the right task. The subject lives in
        # `summary` (the task request); `last_progress` is only a status line and must
        # NOT replace it — burying the subject left the model unable to tell which task
        # the user meant. (chat sweep, 2026-06-27)
        subject = str(row.get("summary") or row.get("title") or "").strip()
        progress = str(row.get("last_progress") or "").strip()
        if subject and progress and progress.lower() not in subject.lower():
            detail = f"{subject} (status: {progress})"
        else:
            detail = subject or progress or "starting up"
        lines.append(f"- [task {ref}] {bot} [{state} via {backend}]: {detail}")
    return "\n".join(lines)


def resolve_active_task_ref(
    session_id: str,
    task_ref: str,
    *,
    repo_root: str | Path | None = None,
) -> str | None:
    ref = str(task_ref or "").strip().lower().replace("[", "").replace("]", "")
    for token in ("task", "ref", "#", ":"):
        ref = ref.replace(token, "")
    ref = ref.strip()
    if not ref:
        return None
    rows = session_active_delegations(session_id, repo_root=repo_root)
    matches: list[tuple[str, bool]] = []
    for row in rows:
        eid = str(row.get("execution_id") or "").lower()
        if not eid:
            continue
        terminal = str(row.get("state") or "").lower() in _TERMINAL_TASK_STATES
        if eid == ref or eid.endswith(ref) or ref.endswith(eid) or (len(ref) >= 4 and ref in eid):
            matches.append((str(row.get("execution_id") or ""), terminal))
    for eid, terminal in matches:
        if not terminal:
            return eid
    if matches:
        return matches[0][0]
    # The model often references a task by a loose ref the opaque exec-id doesn't
    # contain. These are PLAUSIBLE interpretations of what it copied from the digest,
    # not blind guesses (an unrelated ref still resolves to None):
    #   (a) a pure ordinal ('[task 1]' -> '1') maps to the Nth task in digest order;
    #   (b) otherwise the ref's words are matched against each task's subject
    #       ('cancel the jazz report' -> the task whose summary mentions jazz).
    # (chat sweep, 2026-06-27)
    digits = "".join(ch for ch in ref if ch.isdigit())
    if digits and digits == ref and 1 <= int(digits) <= len(rows):
        return str(rows[int(digits) - 1].get("execution_id") or "") or None
    ref_words = [w for w in ref.replace("-", " ").replace("_", " ").split() if len(w) >= 3]
    if ref_words:
        for r in rows:
            subject = str(r.get("summary") or r.get("title") or "").lower()
            if subject and any(w in subject for w in ref_words):
                return str(r.get("execution_id") or "") or None
    return None


def apply_task_update(
    session_id: str,
    task_ref: str,
    update: str = "",
    *,
    cancel: bool = False,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    eid = resolve_active_task_ref(session_id, task_ref, repo_root=repo_root)
    if not eid:
        return {"ok": False, "error": f"No running task matches reference '{task_ref}'."}
    root = _resolve_repo_root(repo_root)
    try:
        if cancel:
            task_bot_runtime.request_cancel(eid, actor="user", repo_root=root)
            return {"ok": True, "execution_id": eid, "action": "cancel"}
        text = str(update or "").strip()
        if not text:
            return {"ok": False, "error": "No update instruction was provided."}
        task_bot_runtime.steer_execution(eid, text, actor="user", repo_root=root)
        return {"ok": True, "execution_id": eid, "action": "steer"}
    except ValueError as exc:
        return {"ok": False, "execution_id": eid, "error": str(exc)}
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc)}


def _ensure_task_workspace(execution_id: str) -> Path:
    """Create and return a clean per-task workspace OUTSIDE the source repo.

    User deliverables are built here (e.g. a pac-man HTML file). Keeping it outside
    the Thomas repo avoids the dev guardrails that block writes inside the repo.
    """
    safe_id = "".join(ch for ch in str(execution_id or "") if ch.isalnum() or ch in "-_") or "task"
    base = Path.home() / ".thomas" / "workspaces" / safe_id
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Fall back to a repo-local runtime dir if home isn't writable.
        base = (ROOT / "runtime" / "workspaces" / safe_id).resolve()
        base.mkdir(parents=True, exist_ok=True)
    return base


async def start_background_delegation(
    app: Any,
    *,
    session_id: str,
    prompt: str,
    mode: str,
    recent_messages: list[dict[str, Any]] | None,
    emit_event: Callable[[dict[str, Any]], Awaitable[None]],
    repo_root: str | Path | None = None,
    force: bool = False,
    autonomy_level: int = 4,
    file_access: int | None = None,
    profile: str | None = None,
    effort: str = "diligent",
    guardrails: str = "",
    guardrail_modes: dict[str, str] | None = None,
    session_llm: Any = None,
    surface: str | None = None,
) -> dict[str, Any] | None:
    normalized_mode = str(mode or "").strip().lower()
    forced = bool(force)
    if normalized_mode != "max" and not forced:
        return None

    current = session_active_delegations(session_id, repo_root=repo_root)
    decision = should_dispatch(
        prompt,
        recent_messages=recent_messages,
        active_tasks=current,
        mode=normalized_mode,
    )
    if decision.action != "dispatch" and not forced:
        return None

    specialist_id = _infer_specialist(prompt)
    emitter = _DelegationEmitter(emit_event)
    delegate_count = _requested_delegate_count(prompt) if forced else 1

    if delegate_count > 1:
        exclude: set[str] = set()
        records: list[dict[str, Any]] = []
        for index in range(delegate_count):
            bot = pick_bot_for_specialist(specialist_id, exclude=set(exclude))
            exclude.add(bot.id)
            helper_prompt = _helper_prompt(
                prompt,
                helper_index=index + 1,
                helper_count=delegate_count,
                bot_name=bot.name,
            )
            record = await _start_task_manager_delegation(
                session_id=session_id,
                prompt=helper_prompt,
                specialist_id=specialist_id,
                bot=bot,
                emitter=emitter,
                repo_root=repo_root,
            )
            if record:
                records.append(record)
        return records or None

    bot = pick_bot_for_specialist(specialist_id)

    # Engine choice is the MODEL's call, declared via send_task(surface=...) — organic
    # routing, NOT a keyword regex (Calvin's law). 'canvas' -> fast streaming watch-it-draw
    # worker; 'task' -> capable agent worker. Only when the model declared NOTHING (the
    # narration-backstop / forced-launch paths) do we fall back to the tightened is_canvas_task
    # hint. Falls back to the agent worker on any canvas-worker error.
    _declared = str(surface or "").strip().lower()
    if _declared == "canvas":
        _want_canvas = True
    elif _declared == "task":
        _want_canvas = False
    else:
        _want_canvas = is_canvas_task(prompt)
    if _want_canvas:
        try:
            return await _start_canvas_worker_delegation(
                session_id=session_id,
                prompt=prompt,
                specialist_id=specialist_id,
                bot=bot,
                emitter=emitter,
                repo_root=repo_root,
                profile=profile,
                session_llm=session_llm,
            )
        except (RuntimeError, OSError, ValueError, TypeError) as exc:
            log.warning("Canvas worker failed, falling back to agent worker: %s", exc, exc_info=True)

    try:
        return await _start_agent_worker_delegation(
            app,
            session_id=session_id,
            prompt=prompt,
            specialist_id=specialist_id,
            bot=bot,
            emitter=emitter,
            repo_root=repo_root,
            autonomy_level=autonomy_level,
            file_access=file_access,
            recent_messages=recent_messages,
            profile=profile,
            effort=effort,
            guardrails=guardrails,
            guardrail_modes=guardrail_modes,
        )
    except (RuntimeError, OSError, ValueError, TypeError) as exc:
        log.warning("Agent worker delegation failed, falling back to task manager: %s", exc, exc_info=True)

    return await _start_task_manager_delegation(
        session_id=session_id,
        prompt=prompt,
        specialist_id=specialist_id,
        bot=bot,
        emitter=emitter,
        repo_root=repo_root,
    )


async def _start_task_manager_delegation(
    *,
    session_id: str,
    prompt: str,
    specialist_id: str,
    bot: Any,
    emitter: _DelegationEmitter,
    repo_root: str | Path | None,
) -> dict[str, Any] | None:
    root = _resolve_repo_root(repo_root)
    result = await dispatch_async(
        prompt,
        session_id,
        scope=specialist_id,
        visibility="background",
        repo_root=root,
    )
    if not result.ok:
        failed = {
            "execution_id": result.execution_id,
            "task_id": result.task_id,
            "session_id": session_id,
            "backend_type": TASK_MANAGER_BACKEND,
            "state": "failed",
            "summary": derive_task_title(prompt),
            "last_progress": result.error or "Background dispatch failed.",
        }
        await emitter.failed(failed, specialist_id=specialist_id, bot=bot, text=failed["last_progress"])
        return failed

    task_bot_runtime.update_execution(
        result.execution_id,
        bot_id=bot.id,
        backend_type=TASK_MANAGER_BACKEND,
        progress_summary="Queued for background execution.",
        actor="thomas-max-delegation",
        repo_root=root,
        force=True,
    )
    payload = task_bot_runtime.get_execution(result.execution_id, root)
    record = _normalize_record(payload)
    await emitter.started(record, specialist_id=specialist_id, bot=bot)
    return record


async def _start_canvas_worker_delegation(
    *,
    session_id: str,
    prompt: str,
    specialist_id: str,
    bot: Any,
    emitter: _DelegationEmitter,
    repo_root: str | Path | None,
    profile: str | None = None,
    session_llm: Any = None,
) -> dict[str, Any]:
    """Fast streaming visual worker: streams a self-contained HTML document to the
    Canvas (the per-execution store), then writes it as a downloadable deliverable."""
    root = _resolve_repo_root(repo_root)
    execution = task_bot_runtime.create_execution(
        session_id=session_id,
        summary=derive_task_title(prompt),
        intent="chat_task",
        scope=[specialist_id],
        visibility="background",
        bot_id=bot.id,
        actor="thomas-canvas",
        backend_type=PROVIDER_NATIVE_BACKEND,
        runtime_profile={"backend_type": PROVIDER_NATIVE_BACKEND, "canvas": True},
        repo_root=root,
    )
    execution_id = str(execution.get("execution_id") or "")
    # Register the canvas store NOW (before the started event) so the very first
    # delegation_started already carries is_canvas=True and the Canvas opens instantly.
    canvas_start(execution_id, title=derive_task_title(prompt))
    task_bot_runtime.update_execution(
        execution_id,
        state="executing",
        claimed_owner=bot.name,
        progress_summary="Drawing it on the canvas…",
        actor=bot.name,
        repo_root=root,
        force=True,
    )
    record = _normalize_record(task_bot_runtime.get_execution(execution_id, root))
    await emitter.started(record, specialist_id=specialist_id, bot=bot)

    async def _progress(text: str) -> None:
        task_bot_runtime.update_execution(
            execution_id, progress_summary=text, actor=bot.name, repo_root=root, force=True
        )
        rec = _normalize_record(task_bot_runtime.get_execution(execution_id, root))
        await emitter.progress(rec, specialist_id=specialist_id, bot=bot, text=text)

    async def _run() -> None:
        # Generate in the BACKGROUND so the chat turn returns immediately and the
        # Canvas streams via the /delegations poll (no shared-LLM-lock deadlock and
        # no turn-blocking). The per-execution canvas store grows live for the poll.
        try:
            html = await run_canvas_worker(
                execution_id=execution_id,
                prompt=prompt,
                root=root,
                profile=profile,
                emit_progress=_progress,
                session_llm=session_llm,
            )
        except Exception as exc:  # noqa: BLE001 - surface as a failed card, don't crash anything
            task_bot_runtime.fail_execution(
                execution_id,
                actor=bot.name,
                summary=f"Canvas worker failed: {exc}",
                blocker="canvas_failed",
                repo_root=root,
            )
            rec = _normalize_record(task_bot_runtime.get_execution(execution_id, root))
            await emitter.failed(rec, specialist_id=specialist_id, bot=bot, text=str(exc))
            return
        # Persist the final HTML as a real downloadable deliverable.
        try:
            work_dir = _ensure_task_workspace(execution_id)
            (Path(work_dir) / "index.html").write_text(html or "", encoding="utf-8")
        except OSError:
            log.debug("canvas deliverable write failed for %s", execution_id, exc_info=True)
        task_bot_runtime.update_execution(
            execution_id,
            state="completed",
            proof_status="verified",
            progress_summary="Rendered on the canvas.",
            actor=bot.name,
            repo_root=root,
            force=True,
        )
        rec = _normalize_record(task_bot_runtime.get_execution(execution_id, root))
        await emitter.completed(rec, specialist_id=specialist_id, bot=bot, text="Rendered on the canvas.")

    asyncio.create_task(_run())
    return record


async def _start_agent_worker_delegation(
    app: Any,
    *,
    session_id: str,
    prompt: str,
    specialist_id: str,
    bot: Any,
    emitter: _DelegationEmitter,
    repo_root: str | Path | None,
    autonomy_level: int = 4,
    file_access: int | None = None,
    recent_messages: list[dict[str, Any]] | None = None,
    profile: str | None = None,
    effort: str = "diligent",
    guardrails: str = "",
    guardrail_modes: dict[str, str] | None = None,
) -> dict[str, Any]:
    root = _resolve_repo_root(repo_root)
    targets_live_repo = _prompt_targets_live_thomas_repo(prompt)
    effective_file_access = clamp_file_access_level(file_access if file_access is not None else 1)
    runtime_profile = _agent_worker_runtime_profile(
        autonomy_level=autonomy_level,
        file_access=file_access,
        effort=effort,
        guardrails=guardrails,
        requires_live_repo_change=targets_live_repo,
    )
    execution = task_bot_runtime.create_execution(
        session_id=session_id,
        # Display title for the task card — a real name for the work, not a raw prompt truncation.
        summary=derive_task_title(prompt),
        intent="chat_task",
        scope=[specialist_id],
        visibility="background",
        bot_id=bot.id,
        actor="thomas-worker",
        backend_type=PROVIDER_NATIVE_BACKEND,
        runtime_profile=runtime_profile,
        repo_root=root,
    )
    execution_id = str(execution.get("execution_id") or "")
    task_bot_runtime.update_execution(
        execution_id,
        state="classified",
        progress_summary="Prepared for provider-native background execution.",
        actor="thomas-worker",
        repo_root=root,
    )
    task_bot_runtime.update_execution(
        execution_id,
        state="queued",
        progress_summary="Queued on the provider-native worker.",
        actor="thomas-worker",
        repo_root=root,
    )
    task_bot_runtime.update_execution(
        execution_id,
        state="claimed",
        claimed_owner=bot.name,
        actor=bot.name,
        repo_root=root,
    )
    task_bot_runtime.update_execution(
        execution_id,
        state="executing",
        progress_summary="Provider-native worker is running.",
        actor=bot.name,
        repo_root=root,
    )
    record = _normalize_record(task_bot_runtime.get_execution(execution_id, root))
    await emitter.started(record, specialist_id=specialist_id, bot=bot)

    if targets_live_repo and effective_file_access < PROJECT:
        spec = file_access_spec(effective_file_access)
        summary = (
            "This task targets Thomas's live repo, but file access is "
            f"'{spec.ui_label}'. Raise the file-access dial to Project or higher, "
            "then retry so Thomas can work on the live checkout instead of a sandbox."
        )
        task_bot_runtime.fail_execution(
            execution_id,
            actor=bot.name,
            summary=summary,
            blocker="file_access_too_low_for_self_development",
            repo_root=root,
        )
        record = _normalize_record(task_bot_runtime.get_execution(execution_id, root))
        await emitter.failed(record, specialist_id=specialist_id, bot=bot, text=summary)
        return record

    # Normal deliverables run in a clean per-task workspace; self-development uses the
    # live checkout directly and is gated later on actual source-file changes.
    work_dir = root if targets_live_repo else _ensure_task_workspace(execution_id)

    _os_name = _platform.system() or "this"
    _shell_hint = (
        "Windows (shell commands run in cmd.exe / PowerShell — do NOT use Unix-only "
        "commands like printf, touch, or cat)"
        if _os_name.lower().startswith("win")
        else _os_name
    )
    instructions = (
        "You are a background worker building a deliverable for the user. "
        f"Your working directory is a fresh, empty workspace: {work_dir}. "
        "It is NOT a source repository — there are no repo rules, startup routers, "
        "or coordination checks to run here, so do not look for them. Just build "
        "what was asked directly: create whatever files are needed in this folder. "
        f"You are running on {_shell_hint}. "
        "HARD RULE — creating or editing files: you MUST use the `fs.write_file` "
        "tool (pass `path` and `content`); writing to a nested path creates the "
        "folders for you. Use `fs.list_dir` to inspect and `fs.read_file` to read. "
        "NEVER use shell commands such as printf, echo, touch, cat, tee, or heredocs "
        "to create or write files — they are unreliable and fail on this OS. Reserve "
        "the `shell.exec` tool ONLY for running programs/builds, and when you do, use "
        "commands valid for the OS above. Use relative paths inside the workspace. "
        "Do not address the user conversationally. "
        "When done, end with a one-line summary of what you built and the main file "
        "name(s) so it can be shown back in chat. " + quality_tier_clause(effort, autonomy_level)
    )
    if targets_live_repo:
        instructions = (
            "You are a background worker doing Thomas self-development in the live "
            f"Thomas repo: {work_dir}. This IS a source repository. Inspect the live "
            "code before changing it, keep edits tightly scoped, and do not claim "
            "success unless live repo files were actually changed and verified. "
            f"You are running on {_shell_hint}. "
            "HARD RULE - creating or editing files: use `fs.write_file` for ordinary "
            "project files. For protected Thomas runtime paths, use "
            "`fs.write_protected_file` with a clear reason; if native authorization is "
            "unavailable or denied, report that blocker honestly instead of writing a "
            "sandbox substitute. NEVER use shell commands such as printf, echo, touch, "
            "cat, tee, redirection, or heredocs to create or edit files. Reserve "
            "`shell.exec` ONLY for read-only inspection commands and tests/builds. "
            "If you cannot modify the live repo, create "
            f"`runtime/self_development/{execution_id}/SELF_DEVELOPMENT_REPORT.md` "
            "explaining the blocker, but do not say the requested fix is done. "
            "Do not address the user conversationally. End with a one-line summary of "
            "the live files changed and verification run, or the blocker encountered. "
            + quality_tier_clause(effort, autonomy_level)
        )

    # Forward a curated slice of chat only when the task leans on prior dialogue
    # ("make it blue"). Self-contained requests get no handoff — feeding earlier turns
    # made the worker build the wrong thing (a Pong request produced a starfield).
    handoff = _handoff_block(recent_messages) if prompt_needs_handoff(prompt) else ""
    if handoff:
        instructions = f"{instructions}\n\n{handoff}"

    from thomas.server.exhaustive_runtime import is_exhaustive

    runner = _run_exhaustive_worker if is_exhaustive(effort) else _run_agent_worker
    worker_kwargs: dict[str, Any] = {
        "execution_id": execution_id,
        "prompt": prompt,
        "specialist_id": specialist_id,
        "bot": bot,
        "instructions": instructions,
        "repo_root": root,
        "work_dir": work_dir,
        "requires_live_repo_change": targets_live_repo,
        "profile": profile,
        "effort": effort,
        "autonomy_level": autonomy_level,
        "file_access": file_access,
        "guardrails": guardrails,
        "guardrail_modes": guardrail_modes,
    }
    asyncio.create_task(
        _run_agent_worker_supervised(
            runner,
            app,
            execution_id=execution_id,
            specialist_id=specialist_id,
            bot=bot,
            emitter=emitter,
            repo_root=root,
            worker_kwargs=worker_kwargs,
        )
    )
    return record
