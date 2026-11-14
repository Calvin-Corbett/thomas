"""Tool execution helpers extracted from thomas.agent.loop."""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import math
import os
import re
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from thomas.agent.hook_events import HookEvent, bridge_guardrails_event, emit_hook
from thomas.agent.loop_tool_batches import build_tool_result, execute_build_tool_batch
from thomas.agent.loop_tool_paths import (
    _WRITE_TOOL_PATH_KEYS,
    _declares_a_path_parameter,
    _optional_empty_path_keys,
    _sanitize_write_tool_path,
    fenced_patch_target,
    loop_sandbox_root,
)
from thomas.agent.tool_failure_guard import ToolFailureGuard
from thomas.core import step_log
from thomas.core.benchmark_lane import audit_benchmark_event, get_benchmark_context
from thomas.core.events import AgentEvent, EventType
from thomas.core.file_access import is_file_access_refusal
from thomas.core.session_scope import bind_session

try:
    from thomas.agent.verification import format_verification_feedback, verify_after_tool

    _HAS_VERIFICATION = True
except ImportError:
    _HAS_VERIFICATION = False

log = logging.getLogger(__name__)


_WRITE_TOOL_KEYWORDS = (
    "write",
    "edit",
    "create",
    "delete",
    "remove",
    "replace",
    "patch",
    "append",
    "rename",
    "move",
    "mkdir",
    "touch",
    "fs.write",
    "fs.delete",
    "fs.rename",
)
_SELF_DEVELOPMENT_WRITE_TOOLS = {"diff.create", "fs.write_file", "fs.write_protected_file"}
_SELF_DEVELOPMENT_INSPECTION_TOOL_PREFIXES = (
    "fs.read",
    "fs.list",
    "fs.search",
    "code.search",
    "code.view",
    "git.status",
    "shell.exec",
)
# Exempt from the inspection-loop counter: one committed read, matched by parsing alone.
# Round 1's regex allowed `<>` backtick `$()*?` and never required `<path>` to name a file,
# so a directory listing (unlimited) and `a>file` / `--output=<file>` (writes) all matched.
# Ruling AA (N1): three whole-string forms, a metacharacter-free `<path>`, and a dot in its
# last segment. A dotted folder (changelog.d, .github) passes too; its read is at most a
# one-level listing of that folder, accepted as a read (fix round 3).
_GIT_REV_CHARS = r"[A-Za-z0-9_./~^@{}-]+"
_GIT_COMMITTED_READ_FORMS = tuple(
    re.compile(rf"^git {verb} ({_GIT_REV_CHARS}):(\S+)$", re.IGNORECASE)
    for verb in ("show", "cat-file -p", "cat-file blob")
)
_GIT_PATH_FORBIDDEN_CHARS = frozenset("|&;<>`$()*?")


def _is_git_committed_read(command: str) -> bool:
    """True only for a bare `git show`/`cat-file` read of a dotted last segment (Ruling AA)."""
    text = str(command or "").strip()
    for pattern in _GIT_COMMITTED_READ_FORMS:
        match = pattern.match(text)
        if match is None:
            continue
        rev, path = match.group(1), match.group(2)
        if rev.startswith("-") or "^{tree}" in rev:
            return False
        if any(ch in _GIT_PATH_FORBIDDEN_CHARS for ch in path) or path.endswith("/"):
            return False
        last_segment = path.rsplit("/", 1)[-1]
        return "." in last_segment
    return False


# Tools that wait for the person (ask_user) are exempt from the per-tool
# timeout: a 20-minute question must not be cut off by a 120-second budget
# meant for shell commands.
_WAITS_ON_THE_PERSON = frozenset({"ask_user", "settings.request_change"})


def _waits_on_the_person(name: str) -> bool:
    return str(name or "").strip().lower() in _WAITS_ON_THE_PERSON


def _host_deadline(loop: Any, name: str) -> Any:
    """The host-owned deadline for this tool: a loop time, or a callable giving it now (one a pause can move)."""
    deadlines = getattr(loop, "_tool_deadlines", None)
    if not isinstance(deadlines, dict) or not deadlines or _waits_on_the_person(name):
        return None
    return deadlines.get(getattr(loop.tools.get(name), "name", ""))


def _tool_execution_timeout(loop: Any, name: str) -> float | None:
    """Honor a host-owned tool deadline without changing other tools' budgets."""
    deadline = _host_deadline(loop, name)
    deadline = deadline() if callable(deadline) else deadline
    if isinstance(deadline, (int, float)) and math.isfinite(deadline):
        return max(0.0, deadline - asyncio.get_running_loop().time())
    return None if _waits_on_the_person(name) else loop._tool_timeout_s


def _bounded(loop: Any, name: str, awaitable: Any, timeout_s: float | None) -> Any:
    """Await a tool under its bound. A host deadline that moves (a Build run's pause gives its time back) bounds
    the wait itself through its ``bound``, re-read as the wait goes; any other bound is a fixed timeout."""
    deadline = _host_deadline(loop, name)
    if callable(getattr(deadline, "bound", None)):
        return deadline.bound(awaitable)
    return asyncio.wait_for(awaitable, timeout=float(timeout_s)) if timeout_s is not None else awaitable


def _failure_guard(loop: Any) -> ToolFailureGuard:
    """One guard per loop, created on first use so every caller shares the counts."""
    guard = getattr(loop, "_tool_failure_guard", None)
    if not isinstance(guard, ToolFailureGuard):
        guard = ToolFailureGuard()
        try:
            loop._tool_failure_guard = guard
        except AttributeError:
            pass
    return guard


def _is_write_tool(name: str, file_audit_module: Any) -> bool:
    name_lower = str(name or "").lower()
    if file_audit_module is not None:
        checker = getattr(file_audit_module, "is_write_tool", None)
        if callable(checker):
            try:
                return bool(checker(name_lower))
            except Exception:
                log.debug(
                    "file_audit.is_write_tool checker failed for tool %r; using fallback", name_lower, exc_info=True
                )
    return any(kw in name_lower for kw in _WRITE_TOOL_KEYWORDS)


def _self_development_write_guard_event(
    loop: Any,
    *,
    name: str,
    args: dict[str, Any] | None = None,
    tc_id: str,
    iteration: int,
) -> AgentEvent | None:
    """Block runaway inspection loops in Thomas self-development runs.

    A self-development background task has a hard completion contract: no
    changed source/test/doc file means failure. After a small inspection
    budget, return a tool error so the model uses the write tool instead of
    burning the run on search/list/status calls. This job_type only ever
    fires for a run in a green, so the refusal says "this self-fix run",
    never "live repo" (item-12(b)).
    """
    if str(getattr(loop, "_current_job_type", "") or "").strip().lower() != "self_development":
        return None
    guard = getattr(loop, "_self_development_write_guard", None)
    if not isinstance(guard, dict) or bool(guard.get("write_seen")):
        return None
    name_lower = str(name or "").strip().lower()
    if name_lower in _SELF_DEVELOPMENT_WRITE_TOOLS:
        guard["write_seen"] = True
        return None
    # Never a file read: refusing one made a worker write a 107-line module blind,
    # as its 5-line docstring (exec-8ef69b69fb68, 2026-09-22). Reading the file is
    # how an edit starts; the guard is for search and listing loops. A one-file
    # `git show`/`cat-file` read is the same act through the shell (item-12(a); narrowed
    # by Ruling AA to exclude any write, and any listing but one level of a dotted folder).
    if name_lower == "fs.read_file":
        return None
    if name_lower == "shell.exec" and _is_git_committed_read((args or {}).get("command")):
        return None
    if not any(name_lower.startswith(prefix) for prefix in _SELF_DEVELOPMENT_INSPECTION_TOOL_PREFIXES):
        return None
    count = int(guard.get("inspection_count", 0) or 0) + 1
    guard["inspection_count"] = count
    limit = max(0, int(guard.get("limit", 6) or 0))
    if count <= limit:
        return None
    msg = (
        "Self-development write-first guard: this self-fix run already used "
        f"{count} inspection tools without a write. Stop inspecting. The next "
        "substantive tool call must be diff.create (to patch an existing file), "
        "fs.write_file (only to create a new one), or fs.write_protected_file "
        "on a scoped source/test/doc file, or explicitly report the blocker."
    )
    return AgentEvent(
        type=EventType.TOOL_RESULT,
        data={
            "tool_id": tc_id,
            "tool_name": name,
            "result": msg,
            "result_text": msg,
            "ok": False,
            "duration_ms": 0,
        },
        iteration=iteration,
    )


def parse_tool_args(raw_args: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Parse tool arguments with repair heuristics for weak model outputs."""
    if raw_args is None:
        return {}, None
    if isinstance(raw_args, dict):
        return raw_args, None

    text = str(raw_args).strip()
    if not text:
        return {}, None

    fenced = re.match(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", text, re.I | re.S)
    if fenced:
        text = fenced.group(1).strip()

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed, None
        return None, f"Tool arguments must be a JSON object, got {type(parsed).__name__}"
    except json.JSONDecodeError:
        pass

    repaired = text.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    brace_delta = repaired.count("{") - repaired.count("}")
    if brace_delta > 0:
        repaired = repaired + ("}" * brace_delta)

    try:
        parsed = json.loads(repaired)
        if isinstance(parsed, dict):
            return parsed, None
        return None, f"Tool arguments must be a JSON object, got {type(parsed).__name__}"
    except json.JSONDecodeError:
        pass

    try:
        parsed = ast.literal_eval(repaired)
        if isinstance(parsed, dict):
            return parsed, None
        return None, f"Tool arguments must be an object, got {type(parsed).__name__}"
    except Exception as e:
        return None, f"Could not parse tool arguments: {type(e).__name__}: {e}"


async def execute_tools(
    loop: Any,
    tool_calls: list[dict[str, Any]],
    iteration: int,
    *,
    file_audit_module: Any,
) -> AsyncIterator[AgentEvent]:
    """Execute tool calls and stream result events as each call completes."""

    async def _run_one(tc: dict[str, Any]) -> AgentEvent:
        name = tc["name"]
        tc_id = tc["id"]
        raw_args = tc["arguments"]
        sandbox_root = loop_sandbox_root(loop)
        benchmark_context, benchmark_error = get_benchmark_context(sandbox_root)
        benchmark_root = Path(str(benchmark_context.get("root") or "")).resolve() if benchmark_context else None

        args, parse_error = parse_tool_args(raw_args)
        if parse_error is not None or args is None:
            await loop._audit_action(
                kind="tool_action_invalid_args",
                tool_call_id=tc_id,
                tool_name=name,
                decision="FAILED",
                reason=str(parse_error or "invalid arguments"),
                payload={"raw_arguments": str(raw_args)[:1000]},
            )
            return AgentEvent(
                type=EventType.TOOL_RESULT,
                data={
                    "tool_id": tc_id,
                    "tool_name": name,
                    "result": f"Invalid tool arguments: {str(raw_args)[:200]}",
                    "result_text": (
                        "Error: Could not parse tool arguments.\n"
                        f"Raw arguments: {str(raw_args)[:500]}\n"
                        f"Reason: {parse_error or 'unknown parse error'}\n"
                        "Hint: return a JSON object for tool arguments."
                    ),
                    "ok": False,
                    "duration_ms": 0,
                },
                iteration=iteration,
            )

        # A call that already failed identically ``limit`` times is refused here,
        # before it runs, with the reason; the run continues (see tool_failure_guard).
        guard = _failure_guard(loop)
        disabled_refusal = guard.check_before_call(name, args)
        if disabled_refusal is not None:
            await loop._audit_action(
                kind="tool_action_rejected",
                tool_call_id=tc_id,
                tool_name=name,
                decision="FAILED",
                reason="repeated_identical_failure_disabled",
                payload={"arguments": args},
            )
            return AgentEvent(
                type=EventType.TOOL_RESULT,
                data={
                    "tool_id": tc_id,
                    "tool_name": name,
                    "result": disabled_refusal,
                    "result_text": disabled_refusal,
                    "ok": False,
                    "duration_ms": 0,
                    "disabled_call": True,
                },
                iteration=iteration,
            )

        validated_path: str | None = None
        is_write_tool_call = _is_write_tool(name, file_audit_module)
        guard_event = _self_development_write_guard_event(loop, name=name, args=args, tc_id=tc_id, iteration=iteration)
        if guard_event is not None:
            await loop._audit_action(
                kind="tool_action_rejected",
                tool_call_id=tc_id,
                tool_name=name,
                decision="FAILED",
                reason="self_development_write_first_guard",
                payload={},
            )
            return guard_event
        should_sanitize_paths = is_write_tool_call or any(key in args for key in _WRITE_TOOL_PATH_KEYS)
        if should_sanitize_paths:
            if is_write_tool_call and benchmark_error:
                msg = f"Benchmark write lane is invalid for write tool {name}: {benchmark_error}"
                await loop._audit_action(
                    kind="tool_action_invalid_args",
                    tool_call_id=tc_id,
                    tool_name=name,
                    decision="FAILED",
                    reason=msg,
                    payload={"arguments": args},
                )
                return AgentEvent(
                    type=EventType.TOOL_RESULT,
                    data={
                        "tool_id": tc_id,
                        "tool_name": name,
                        "result": msg,
                        "result_text": msg,
                        "ok": False,
                        "duration_ms": 0,
                    },
                    iteration=iteration,
                )
            validated_path, path_error = _sanitize_write_tool_path(
                args,
                require_path=is_write_tool_call and _declares_a_path_parameter(getattr(loop, "tools", None), name),
                optional_empty_path_keys=_optional_empty_path_keys(getattr(loop, "tools", None), name),
                sandbox_root=sandbox_root,
                benchmark_root=benchmark_root if is_write_tool_call else None,
                # Absolute WRITE targets are judged by the file-access ladder
                # (the authority fs.write_file itself consults), so a refused
                # Desktop write carries the ladder's remedy sentence instead of
                # a bare "absolute paths are not allowed" (measured live,
                # exec-c3adbfcfa341 2026-08-07). Benchmark lane and non-write
                # tools keep the old blanket rejection.
                file_access=(
                    getattr(getattr(loop.config, "tools", None), "file_access", None)
                    if is_write_tool_call and benchmark_root is None
                    else None
                ),
                # The run's file fence (paths another agent or the brief holds)
                # is enforced on write tools here, never left to the prose.
                protected_paths=(getattr(loop, "protected_paths", None) or None) if is_write_tool_call else None,
            )
            if path_error is None and is_write_tool_call:
                # A patch names its files inside its text; the path sanitizer never
                # sees them. Read the patch's own headers against the same fence.
                fence = fenced_patch_target(args, sandbox_root, getattr(loop, "protected_paths", None))
                if fence is not None:
                    path_error = (
                        f"BLOCKED: {fence} is fenced off for this run (another agent or the run's brief holds it); "
                        "write elsewhere or report the change as not yours to make."
                    )
            if path_error is not None:
                # A read tool refused here used to be reported as a "write tool"
                # (TB-4.0 run 3: fs.read_file, fs.list_dir, eng.lint all labelled
                # write tools). Name what it is.
                tool_kind = "write tool" if is_write_tool_call else "tool"
                msg = (
                    path_error
                    if is_file_access_refusal(path_error)
                    else f"Invalid file path argument for {tool_kind} {name}: {path_error}"
                )
                if is_write_tool_call:
                    audit_benchmark_event(
                        benchmark_context,
                        event="write_path_check",
                        decision="BLOCKED",
                        payload={
                            "tool_call_id": tc_id,
                            "tool_name": name,
                            "attempted_path": str((args or {}).get("path") or ""),
                            "blocked_path": str((args or {}).get("path") or ""),
                            "error": path_error,
                        },
                    )
                await loop._audit_action(
                    kind="tool_action_invalid_args",
                    tool_call_id=tc_id,
                    tool_name=name,
                    decision="FAILED",
                    reason=msg,
                    payload={"arguments": args},
                )
                return AgentEvent(
                    type=EventType.TOOL_RESULT,
                    data={
                        "tool_id": tc_id,
                        "tool_name": name,
                        "result": msg,
                        "result_text": msg,
                        "ok": False,
                        "duration_ms": 0,
                    },
                    iteration=iteration,
                )
            if is_write_tool_call:
                audit_benchmark_event(
                    benchmark_context,
                    event="write_path_check",
                    decision="APPROVED",
                    payload={
                        "tool_call_id": tc_id,
                        "tool_name": name,
                        "attempted_path": str(validated_path or ""),
                        "approved_path": str(validated_path or ""),
                    },
                )

        # Hook surface (tool category): fires after arg parsing / path
        # sanitization and before tool execution. Read-only this release.
        await emit_hook(loop, HookEvent.TOOL_PRE, {"name": name, "args": args})

        start = time.monotonic()
        await loop._audit_action(
            kind="tool_action_start",
            tool_call_id=tc_id,
            tool_name=name,
            decision="STARTED",
            payload={"arguments": args},
        )
        timeout_s = _tool_execution_timeout(loop, name)
        if loop._guarded_tool_runner is not None:

            async def _execute_guarded_tool() -> dict[str, Any]:
                async def _guarded_executor(call: dict[str, Any]) -> dict[str, Any]:
                    tr = await loop.tools.execute(str(call.get("name") or ""), call.get("args") or {})
                    return {
                        "ok": bool(tr.ok),
                        "error": tr.error,
                        "data": tr.data,
                        "result_text": tr.to_content(),
                    }

                async def _emit_guardrails_event(evt_type: str, payload: dict[str, Any]) -> None:
                    # Hook surface (approval category): bridge the guardrails
                    # TOOL_APPROVAL_REQUIRED event onto the approval_requested hook.
                    await bridge_guardrails_event(loop, evt_type, payload)
                    cb = loop._guardrails_event_cb
                    if cb is None:
                        return
                    try:
                        await cb(evt_type, payload)
                    except Exception as e:
                        log.debug("Guardrails callback failed: %s", e)

                summary_lines: list[str] = []
                for m in loop._conversation[-8:]:
                    if not isinstance(m, dict):
                        continue
                    role = str(m.get("role") or "?")
                    content = m.get("content")
                    if isinstance(content, str) and content.strip():
                        summary_lines.append(f"{role}: {content[:220]}")
                conversation_summary = "\n".join(summary_lines)

                return await loop._guarded_tool_runner.run(
                    executor=_guarded_executor,
                    tool_call={"id": tc_id, "name": name, "args": args},
                    run_id=loop._run_id,
                    session_id=loop._session_id,
                    iteration=iteration,
                    cwd=os.getcwd(),
                    sandbox_root=str(loop.config.tools.sandbox_path),
                    runtime_root=str(loop.config.memory.root_path),
                    conversation_summary=conversation_summary,
                    emit_event=_emit_guardrails_event,
                    # The caller (e.g. the guardrails "gatekeeper" mode) may pin the
                    # approval posture via this attribute; otherwise derive from autonomy.
                    no_human_mode=(
                        loop._no_human_mode_override
                        if hasattr(loop, "_no_human_mode_override")
                        else ("allow" if int(loop._autonomy_level or 0) >= 4 else None)
                    ),
                )

            try:
                guarded: Any = await _bounded(loop, name, _execute_guarded_tool(), timeout_s)
            except asyncio.TimeoutError:
                duration = (time.monotonic() - start) * 1000
                await loop._audit_action(
                    kind="tool_action_timeout",
                    tool_call_id=tc_id,
                    tool_name=name,
                    decision="TIMEOUT",
                    reason=f"timeout_s={timeout_s}",
                    payload={"duration_ms": duration},
                )
                return AgentEvent(
                    type=EventType.TOOL_RESULT,
                    data={
                        "tool_id": tc_id,
                        "tool_name": name,
                        "result": f"Tool timed out after {timeout_s}s",
                        "result_text": f"Tool timed out after {timeout_s}s",
                        "ok": False,
                        "duration_ms": duration,
                    },
                    iteration=iteration,
                )

            duration = (time.monotonic() - start) * 1000
            ok = bool(guarded.get("ok", False)) if isinstance(guarded, dict) else True
            if isinstance(guarded, dict):
                if isinstance(guarded.get("result_text"), str):
                    result_text = guarded.get("result_text", "")
                elif isinstance(guarded.get("result"), str):
                    result_text = guarded.get("result", "")
                elif guarded.get("data") is not None:
                    try:
                        result_text = json.dumps(guarded.get("data"), ensure_ascii=False, default=str)
                    except Exception:
                        log.debug("guarded tool result data serialization failed; using string fallback", exc_info=True)
                        result_text = str(guarded.get("data"))
                elif guarded.get("error"):
                    result_text = json.dumps(
                        {"ok": False, "error": str(guarded.get("error"))},
                        ensure_ascii=False,
                    )
                else:
                    result_text = json.dumps(guarded, ensure_ascii=False, default=str)
            else:
                result_text = str(guarded)
        else:
            try:
                result = await _bounded(loop, name, loop.tools.execute(name, args), timeout_s)
            except asyncio.TimeoutError:
                duration = (time.monotonic() - start) * 1000
                await loop._audit_action(
                    kind="tool_action_timeout",
                    tool_call_id=tc_id,
                    tool_name=name,
                    decision="TIMEOUT",
                    reason=f"timeout_s={timeout_s}",
                    payload={"duration_ms": duration},
                )
                return AgentEvent(
                    type=EventType.TOOL_RESULT,
                    data={
                        "tool_id": tc_id,
                        "tool_name": name,
                        "result": f"Tool timed out after {timeout_s}s",
                        "result_text": f"Tool timed out after {timeout_s}s",
                        "ok": False,
                        "duration_ms": duration,
                    },
                    iteration=iteration,
                )
            except Exception as e:
                duration = (time.monotonic() - start) * 1000
                err_text = f"{type(e).__name__}: {e}"
                # Broad catch: tool implementations may raise any exception; capture for audit and agent feedback.
                log.debug("Tool %r raised an exception during execution: %s", name, err_text, exc_info=True)
                await loop._audit_action(
                    kind="tool_action_exception",
                    tool_call_id=tc_id,
                    tool_name=name,
                    decision="FAILED",
                    reason=err_text,
                    payload={"duration_ms": duration},
                )
                return AgentEvent(
                    type=EventType.TOOL_RESULT,
                    data={
                        "tool_id": tc_id,
                        "tool_name": name,
                        "result": f"Tool execution failed: {err_text}",
                        "result_text": f"Tool execution failed: {err_text}",
                        "ok": False,
                        "duration_ms": duration,
                    },
                    iteration=iteration,
                )
            duration = (time.monotonic() - start) * 1000
            ok = bool(result.ok)
            result_text = result.to_content()

        try:
            if file_audit_module is not None and file_audit_module.is_write_tool(name):
                file_path = validated_path or ""
                action = "delete" if "delet" in name.lower() or "remov" in name.lower() else "write"
                try:
                    args_snippet = (
                        json.dumps(
                            {k: v for k, v in (args or {}).items() if k != "content"},
                            ensure_ascii=False,
                            default=str,
                        )[:300]
                        if isinstance(args, dict)
                        else ""
                    )
                except (TypeError, ValueError):
                    args_snippet = str(args)[:200]
                model_name = getattr(getattr(loop, "llm", None), "model_name", None) or getattr(
                    getattr(loop.llm, "config", None), "model", "unknown"
                )
                file_audit_module.record_file_write(
                    run_id=loop._run_id,
                    model=str(model_name),
                    tool_name=name,
                    path=file_path,
                    action=action,
                    args_snippet=args_snippet,
                )
        except Exception as _ae:
            log.debug("file_audit record failed: %s", _ae)

        await loop._audit_action(
            kind="tool_action_result",
            tool_call_id=tc_id,
            tool_name=name,
            decision="EXECUTED" if ok else "FAILED",
            payload={
                "ok": bool(ok),
                "duration_ms": duration,
                "result_preview": str(result_text)[:1000],
            },
        )
        if is_write_tool_call:
            audit_benchmark_event(
                benchmark_context,
                event="write_tool_result",
                decision="EXECUTED" if ok else "FAILED",
                payload={
                    "tool_call_id": tc_id,
                    "tool_name": name,
                    "approved_path": str(validated_path or ""),
                    "final_outcome": "success" if ok else "failure",
                },
            )

        # --- Post-action verification hooks ---
        verification_feedback = None
        if _HAS_VERIFICATION and ok and isinstance(args, dict):
            try:
                sandbox = str(loop.config.tools.sandbox_path) if hasattr(loop.config, "tools") else None
                issues = await verify_after_tool(
                    tool_name=name,
                    args=args,
                    result_ok=ok,
                    sandbox_root=sandbox,
                )
                verification_feedback = format_verification_feedback(issues)
                if verification_feedback:
                    log.info("Verification for %s: %s", name, verification_feedback[:200])
            except Exception as _ve:
                log.debug("Verification hook failed for %s: %s", name, _ve)

        event_data = {
            "tool_id": tc_id,
            "tool_name": name,
            "result": result_text[:4000],
            "result_text": result_text,
            "ok": ok,
            "duration_ms": duration,
        }
        if verification_feedback:
            event_data["verification"] = verification_feedback
            # Append verification feedback to result so the LLM sees it
            event_data["result_text"] = result_text + "\n\n" + verification_feedback
        if not ok:
            disable_note = guard.record_failure(name, args, result_text)
            if disable_note:
                event_data["result_text"] = str(event_data["result_text"]) + "\n\n" + disable_note
                event_data["result"] = str(event_data["result_text"])[:4000]
                event_data["disabled_call"] = True

        # Hook surface (tool category): fires after the tool completes, once
        # duration/ok/result_text are known. Read-only this release.
        await emit_hook(
            loop,
            HookEvent.TOOL_POST,
            {"name": name, "args": args, "ok": ok, "result_text": result_text},
        )

        return AgentEvent(
            type=EventType.TOOL_RESULT,
            data=event_data,
            iteration=iteration,
        )

    if not tool_calls:
        return

    sem = asyncio.Semaphore(max(1, int(loop._max_parallel_tools or max(1, len(tool_calls)))))

    async def _run_one_limited(tc: dict[str, Any]) -> AgentEvent:
        # Bind each tool to its chat so ask_user cards reach the right page.
        async with sem:  # every finished call is timed into the step log (2026-10-25)
            with bind_session(getattr(loop, "_session_id", ""), run_id=loop._run_id, run_owner=loop):
                return step_log.tool_finished(await _run_one(tc), run=str(getattr(loop, "_run_id", "") or ""))

    if getattr(loop, "_build_read_parallel_only", False):

        async def _run_one_build(tc: dict[str, Any]) -> AgentEvent:
            return await build_tool_result(_run_one_limited, tc, loop, iteration)

        async for event in execute_build_tool_batch(tool_calls, _run_one_build):
            yield event
        return
    tool_tasks = {asyncio.create_task(_run_one_limited(tc)): tc for tc in tool_calls}
    try:
        for done in asyncio.as_completed(tool_tasks):
            try:
                result_event = await done
            except Exception as e:
                tc = tool_tasks.get(done, {})
                tc_id = str(tc.get("id", ""))
                tool_name = str(tc.get("name") or "tool")
                # Broad catch: asyncio task wrapper can surface any exception from the tool coroutine.
                log.debug("Tool task for %r completed with unhandled exception: %s", tool_name, e, exc_info=True)
                await loop._audit_action(
                    kind="tool_action_exception",
                    tool_call_id=tc_id,
                    tool_name=tool_name,
                    decision="FAILED",
                    reason=f"{type(e).__name__}: {e}",
                    payload={},
                )
                yield AgentEvent(
                    type=EventType.TOOL_RESULT,
                    data={
                        "tool_id": tc_id,
                        "tool_name": tool_name,
                        "result": f"Tool execution failed before completion: {e}",
                        "result_text": f"Tool execution failed before completion: {e}",
                        "ok": False,
                        "duration_ms": 0,
                    },
                    iteration=iteration,
                )
                continue
            yield result_event
    finally:
        for t in tool_tasks:
            if not t.done():
                t.cancel()
        if tool_tasks:
            await asyncio.gather(*tool_tasks, return_exceptions=True)


__all__ = ["execute_tools", "parse_tool_args"]
