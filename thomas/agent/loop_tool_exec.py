"""Tool execution helpers extracted from thomas.agent.loop."""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import os
import re
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from thomas.core.events import AgentEvent, EventType

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

_WRITE_TOOL_PATH_KEYS = (
    "path",
    "file",
    "filename",
    "filepath",
    "file_path",
    "source_path",
    "destination_path",
    "payload_path",
    "auth_path",
    "auth_payload_path",
)


def _is_write_tool(name: str, file_audit_module: Any) -> bool:
    name_lower = str(name or "").lower()
    if file_audit_module is not None:
        checker = getattr(file_audit_module, "is_write_tool", None)
        if callable(checker):
            try:
                return bool(checker(name_lower))
            except Exception:
                pass
    return any(kw in name_lower for kw in _WRITE_TOOL_KEYWORDS)


def _validate_filesystem_path(path_value: Any) -> tuple[str | None, str | None]:
    if path_value is None:
        return None, "missing path value"

    try:
        path_text = os.fspath(path_value)
    except TypeError:
        return None, "path must be a string or path-like value"

    if not isinstance(path_text, str):
        return None, "path must be a string or path-like value"

    path_text = str(path_text).strip()

    if path_text == "":
        return None, "path cannot be empty"

    if "\x00" in path_text:
        return None, "path cannot contain null bytes"

    if any(ord(ch) < 32 or ord(ch) == 127 for ch in path_text):
        return None, "path cannot contain control characters"

    if os.path.isabs(path_text) or path_text.startswith(("/", "\\")):
        return None, "absolute paths are not allowed"

    if re.match(r"^[A-Za-z]:", path_text) or re.match(r"^[/\\]{2,}", path_text):
        return None, "disallowed root/path prefix in file path"

    if "://" in path_text:
        return None, "path cannot contain URI-like prefixes"

    parts = re.split(r"[\\/]", path_text)
    if ".." in parts:
        return None, "path traversal via '..' segment is not allowed"

    if any(part == "" for part in parts):
        return None, "path segments cannot be empty"

    # Reject any attempts to normalise into an ancestor path
    if ".." in Path(path_text).parts:
        return None, "path traversal via parent directory reference is not allowed"

    return path_text, None


def _sanitize_write_tool_path(
    args: dict[str, Any],
    *,
    require_path: bool = True,
) -> tuple[str | None, str | None]:
    if not isinstance(args, dict):
        return None, "tool arguments must be an object"

    validated_path: str | None = None
    saw_path_key = False

    for key in _WRITE_TOOL_PATH_KEYS:
        if key not in args:
            continue
        saw_path_key = True
        path_value = args.get(key)
        if not isinstance(path_value, (str, os.PathLike)):
            return None, f"{key} must be a string or path-like value"
        checked_path, error = _validate_filesystem_path(path_value)
        if error is not None:
            return None, f"invalid {key}: {error}"
        args[key] = checked_path
        if validated_path is None:
            validated_path = checked_path

    if not saw_path_key and require_path:
        return None, "missing path argument (expected path, file, or filename)"

    return validated_path, None


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

        validated_path: str | None = None
        is_write_tool_call = _is_write_tool(name, file_audit_module)
        should_sanitize_paths = is_write_tool_call or any(key in args for key in _WRITE_TOOL_PATH_KEYS)
        if should_sanitize_paths:
            validated_path, path_error = _sanitize_write_tool_path(
                args,
                require_path=is_write_tool_call,
            )
            if path_error is not None:
                msg = f"Invalid file path argument for write tool {name}: {path_error}"
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

        start = time.monotonic()
        await loop._audit_action(
            kind="tool_action_start",
            tool_call_id=tc_id,
            tool_name=name,
            decision="STARTED",
            payload={"arguments": args},
        )
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
                    no_human_mode="allow" if int(loop._autonomy_level or 0) >= 4 else None,
                )

            try:
                guarded: Any
                if loop._tool_timeout_s is not None:
                    guarded = await asyncio.wait_for(
                        _execute_guarded_tool(),
                        timeout=float(loop._tool_timeout_s),
                    )
                else:
                    guarded = await _execute_guarded_tool()
            except asyncio.TimeoutError:
                duration = (time.monotonic() - start) * 1000
                await loop._audit_action(
                    kind="tool_action_timeout",
                    tool_call_id=tc_id,
                    tool_name=name,
                    decision="TIMEOUT",
                    reason=f"timeout_s={loop._tool_timeout_s}",
                    payload={"duration_ms": duration},
                )
                return AgentEvent(
                    type=EventType.TOOL_RESULT,
                    data={
                        "tool_id": tc_id,
                        "tool_name": name,
                        "result": f"Tool timed out after {loop._tool_timeout_s}s",
                        "result_text": f"Tool timed out after {loop._tool_timeout_s}s",
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
                if loop._tool_timeout_s is not None:
                    result = await asyncio.wait_for(
                        loop.tools.execute(name, args),
                        timeout=float(loop._tool_timeout_s),
                    )
                else:
                    result = await loop.tools.execute(name, args)
            except asyncio.TimeoutError:
                duration = (time.monotonic() - start) * 1000
                await loop._audit_action(
                    kind="tool_action_timeout",
                    tool_call_id=tc_id,
                    tool_name=name,
                    decision="TIMEOUT",
                    reason=f"timeout_s={loop._tool_timeout_s}",
                    payload={"duration_ms": duration},
                )
                return AgentEvent(
                    type=EventType.TOOL_RESULT,
                    data={
                        "tool_id": tc_id,
                        "tool_name": name,
                        "result": f"Tool timed out after {loop._tool_timeout_s}s",
                        "result_text": f"Tool timed out after {loop._tool_timeout_s}s",
                        "ok": False,
                        "duration_ms": duration,
                    },
                    iteration=iteration,
                )
            except Exception as e:
                duration = (time.monotonic() - start) * 1000
                err_text = f"{type(e).__name__}: {e}"
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

        return AgentEvent(
            type=EventType.TOOL_RESULT,
            data=event_data,
            iteration=iteration,
        )

    if not tool_calls:
        return

    max_parallel = loop._max_parallel_tools
    if max_parallel is None:
        max_parallel = max(1, len(tool_calls))
    sem = asyncio.Semaphore(max(1, int(max_parallel)))

    async def _run_one_limited(tc: dict[str, Any]) -> AgentEvent:
        async with sem:
            return await _run_one(tc)

    tool_tasks = {asyncio.create_task(_run_one_limited(tc)): tc for tc in tool_calls}
    try:
        for done in asyncio.as_completed(tool_tasks):
            try:
                result_event = await done
            except Exception as e:
                tc = tool_tasks.get(done, {})
                tc_id = str(tc.get("id", ""))
                tool_name = str(tc.get("name") or "tool")
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
            done_fallback = await asyncio.gather(*tool_tasks, return_exceptions=True)
            _ = done_fallback


__all__ = [
    "execute_tools",
    "parse_tool_args",
]
