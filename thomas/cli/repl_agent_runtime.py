"""Execution runtime helpers for ThomasREPL agent loop streaming."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from rich.live import Live
from rich.markdown import Markdown
from rich.markup import escape as rich_escape
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from thomas.agent.loop import AgentLoop
from thomas.cli.repl_approval import _FILE_WRITE_TOOLS, render_post_edit_summary
from thomas.cli.repl_hooks import (
    HookType,
    format_hook_result_line,
    tool_display_name,
    tool_summary_line,
)
from thomas.core.autonomy import autonomy_level_name
from thomas.core.events import EventType
from thomas.core.token_economy import normalize_token_economy_level

ASSISTANT_PANEL_TITLE = "THOMAS"


class ThomasREPLAgentMixin:
    async def _run_agent(self, prompt: str) -> None:
        """Run the agent loop, streaming events to the terminal.

        Uses a thinking spinner while waiting for the LLM, and renders
        the final response as a readable assistant panel.

        Wires in the GuardedToolRunner with interactive approval prompts
        so that file-write and shell-exec tools require user confirmation.
        """
        llm = self._get_llm()

        # Wire up the approval system (guardrails)
        guarded_runner = self._approval_handler.create_guarded_runner(self.config)
        self._approval_handler.start()
        thread_id = str(getattr(self, "_chat_thread_id", "") or "repl")
        session_id = str(getattr(self, "_repl_session_id", "") or "repl")
        next_run_id = getattr(self, "_next_chat_run_id", None)
        if callable(next_run_id):
            run_id = str(next_run_id())
        else:
            run_id = str(session_id or "repl")

        agent = AgentLoop(
            config=self.config,
            llm=llm,
            tools=self.tools,
            conversation=self._conversation,
            memory=self._memory,
            thread_id=thread_id,
            autonomy_level=self._autonomy_level,
            guarded_tool_runner=guarded_runner,
            session_id=session_id,
            run_id=run_id,
        )

        # Streaming state
        thinking = True
        spinner_live: Live | None = None
        streamed_text = ""
        is_streaming = False
        render_phase_emitted = False
        final_text = ""
        usage_hint = ""
        token_info = ""
        # Track tool call args for post-edit diff summary + inline display
        _tool_args_buf: dict[str, str] = {}
        _tool_names: dict[str, str] = {}
        _tool_call_t0: dict[str, float] = {}
        _phase_t0: dict[str, float] = {}
        _planning_done = False
        _responding_started = False

        # Interrupt state
        cancel_ts: float = 0.0
        cancelled = False

        def _stop_spinner() -> None:
            nonlocal spinner_live, thinking
            if spinner_live is not None:
                spinner_live.stop()
                spinner_live = None
            thinking = False

        def _start_spinner(label: str = " thinking...") -> None:
            nonlocal spinner_live, thinking
            _stop_spinner()
            thinking = True
            msg = f"{label} ({usage_hint})" if usage_hint else label
            spinner_live = Live(
                Spinner("dots", text=Text(msg, style="dim")),
                console=self._console,
                transient=True,
            )
            spinner_live.start()

        def _finish_stream_line() -> None:
            nonlocal is_streaming
            if is_streaming:
                self._console.file.write("\n")
                self._console.file.flush()
                is_streaming = False

        def _activity(payload: dict[str, Any] | str, *, level: str = "normal") -> None:
            if hasattr(self, "_record_activity"):
                self._record_activity(payload, level=level)

        def _append_log(message: str) -> None:
            if not message:
                return
            if hasattr(self, "_append_log"):
                self._append_log(str(message))

        def _parse_tool_args(raw: str) -> dict[str, Any]:
            if not raw:
                return {}
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                return {}
            return {}

        def _tool_short_label(tool_name: str, args: dict[str, Any]) -> str:
            if not isinstance(args, dict):
                return ""
            if not args:
                return ""
            hints: list[str] = []
            if "command" in args and isinstance(args["command"], str):
                hints.append(args["command"].strip())
            elif "cmd" in args and isinstance(args["cmd"], str):
                hints.append(args["cmd"].strip())
            elif "query" in args and isinstance(args["query"], str):
                hints.append(args["query"].strip())
            elif "path" in args and isinstance(args["path"], str):
                hints.append(args["path"].strip())
            elif "file_path" in args and isinstance(args["file_path"], str):
                hints.append(args["file_path"].strip())
            if not hints:
                for key in ("input", "target", "instruction", "action"):
                    value = args.get(key)
                    if isinstance(value, str) and value.strip():
                        hints.append(f"{key}: {value.strip()}")
                        break
            return self._shorten(" ".join(hints), 80)

        def _tool_command(args: dict[str, Any]) -> str:
            if not isinstance(args, dict):
                return ""
            if "command" in args and isinstance(args["command"], str):
                return args["command"].strip()
            if "cmd" in args and isinstance(args["cmd"], str):
                return args["cmd"].strip()
            if "path" in args and isinstance(args["path"], str):
                return args["path"].strip()
            if "file_path" in args and isinstance(args["file_path"], str):
                return args["file_path"].strip()
            return ""

        def _result_components(result: Any) -> tuple[str, str, int | None]:
            result_text = ""
            result_stderr = ""
            bytes_out: int | None = None
            if isinstance(result, dict):
                if isinstance(result.get("stdout"), str):
                    result_text = result["stdout"]
                elif isinstance(result.get("output"), str):
                    result_text = result.get("output", "")
                if isinstance(result.get("stderr"), str):
                    result_stderr = result.get("stderr")
                if bytes_out is None:
                    for key in ("bytes_out", "size"):
                        value = result.get(key)
                        try:
                            if value is not None:
                                bytes_out = int(value)
                                break
                        except (TypeError, ValueError):
                            bytes_out = None
            elif isinstance(result, (bytes, bytearray)):
                result_text = result.decode("utf-8", errors="replace")
                bytes_out = len(result)
            elif result is not None:
                result_text = str(result)
            if bytes_out is None and result_text:
                bytes_out = len(result_text)
            return str(result_text), result_stderr, bytes_out

        def _sync_tool_args_from_event(tc_id: str, args_obj: Any) -> None:
            if not tc_id:
                return
            if args_obj is None:
                return
            if isinstance(args_obj, str):
                _tool_args_buf[tc_id] = args_obj
                return
            if not isinstance(args_obj, dict):
                return
            try:
                _tool_args_buf[tc_id] = json.dumps(args_obj, ensure_ascii=False)
            except (TypeError, ValueError):
                _tool_args_buf[tc_id] = str(args_obj)

        def _start_phase(name: str) -> None:
            _phase_t0[name] = time.perf_counter()
            _activity({"type": "phase_start", "phase": name}, level="minimal")

        def _end_phase(name: str, *, duration_ms: float | None = None) -> None:
            duration = duration_ms
            if duration is None:
                started = _phase_t0.pop(name, None)
                if started is None:
                    return
                duration = (time.perf_counter() - started) * 1000
            else:
                _phase_t0.pop(name, None)
            _activity({"type": "phase_end", "phase": name, "duration_ms": duration}, level="minimal")

        # Approval handler callbacks to pause/resume spinner
        def _pause_spinner() -> None:
            _stop_spinner()
            _finish_stream_line()

        def _resume_spinner() -> None:
            _start_spinner(" running...")

        self._approval_handler.set_ui_callbacks(
            pause_ui=_pause_spinner,
            resume_ui=_resume_spinner,
        )

        try:
            token_economy = normalize_token_economy_level(os.environ.get("THOMAS_TOKEN_ECONOMY", "optimal"))
            async for event in agent.run(prompt, token_economy=token_economy):
                if cancelled:
                    break

                if event.type == EventType.AGENT_START:
                    _start_phase("planning")
                    route = event.data.get("route", {}) if isinstance(event.data.get("route"), dict) else {}
                    mode = route.get("mode") or event.data.get("mode") or "auto"
                    policy = event.data.get("tools_policy", "auto")
                    level = int(event.data.get("autonomy_level", self._autonomy_level) or self._autonomy_level)
                    name = str(event.data.get("autonomy_name") or autonomy_level_name(level))
                    _activity(
                        {
                            "type": "status",
                            "message": f"planning ({mode}/{policy})",
                        },
                        level="minimal",
                    )
                    self._print_auto(f"route={mode}, tools={policy}, autonomy=L{level} {name}")

                elif event.type == EventType.STATUS:
                    message = str(event.data.get("message") or "").strip()
                    if message:
                        _activity(message, level="debug")

                elif event.type == EventType.MEMORY_QUERY:
                    if "retrieving_memory" not in _phase_t0:
                        _start_phase("retrieving_memory")
                    query = str(event.data.get("query") or event.data.get("question") or "").strip()
                    if query:
                        _activity(
                            {
                                "type": "memory_event",
                                "query": query,
                                "duration_ms": event.data.get("duration_ms"),
                            },
                            level="debug",
                        )

                elif event.type == EventType.MEMORY_RESULT:
                    if "retrieving_memory" in _phase_t0:
                        _end_phase("retrieving_memory")
                    _activity(
                        {
                            "type": "memory_event",
                            "query": str(event.data.get("query") or event.data.get("question") or "").strip(),
                            "hits": event.data.get("hits"),
                            "score": event.data.get("score"),
                            "duration_ms": event.data.get("duration_ms"),
                        },
                        level="debug",
                    )

                elif event.type == EventType.AGENT_ITERATION:
                    ctx_tokens = event.data.get("token_estimate", 0)
                    ctx_window = event.data.get("context_window", 0)
                    iteration = event.data.get("iteration", 0)
                    # Flush text from previous iteration so it doesn't
                    # merge with the next iteration's response.
                    if iteration > 0:
                        prev = streamed_text.strip()
                        prev = re.sub(r"</?thinking>", "", prev, flags=re.IGNORECASE).strip()
                        if prev:
                            self._console.print(
                                Panel(
                                    Markdown(prev),
                                    border_style="dim",
                                    expand=True,
                                )
                            )
                            streamed_text = ""
                            render_phase_emitted = False
                    if not _planning_done:
                        _end_phase("planning")
                        _planning_done = True
                        if not _responding_started:
                            _start_phase("responding")
                            _responding_started = True
                    _activity(f"iteration {int(iteration) + 1}", level="debug")
                    if iteration == 0:
                        usage_hint = f"~{ctx_tokens:,}/{ctx_window:,} tokens"
                    if thinking and spinner_live is None:
                        _start_spinner(" thinking...")

                elif event.type == EventType.TEXT_DELTA:
                    # Real-time token streaming to terminal
                    _stop_spinner()
                    token = str(event.data.get("text") or "")
                    if token:
                        if not render_phase_emitted:
                            render_phase_emitted = True
                            _activity("rendering response...", level="minimal")
                        streamed_text += token

                elif event.type == EventType.TOOL_CALL_START:
                    _stop_spinner()
                    _finish_stream_line()
                    # Flush any accumulated text as a thinking/intent panel
                    # before showing tool work — prevents the one-blob problem.
                    pending = streamed_text.strip()
                    pending = re.sub(r"</?thinking>", "", pending, flags=re.IGNORECASE).strip()
                    if pending:
                        self._console.print(
                            Panel(
                                Markdown(pending),
                                border_style="dim",
                                expand=True,
                            )
                        )
                        streamed_text = ""
                        render_phase_emitted = False
                    tc_id = str(event.data.get("tool_id", ""))
                    tname = str(event.data.get("tool_name", "tool"))
                    display = tool_display_name(tname)
                    _start_phase("calling_tool")
                    _activity(
                        {
                            "type": "tool_call",
                            "tool_id": tc_id,
                            "tool_name": display,
                        },
                        level="normal",
                    )
                    _append_log(f"tool call: {display} id={tc_id}")
                    if tc_id:
                        _tool_names[tc_id] = tname
                        _tool_args_buf[tc_id] = ""
                        _tool_call_t0[tc_id] = time.perf_counter()

                elif event.type == EventType.TOOL_CALL_ARGS_DELTA:
                    tc_id = str(event.data.get("tool_id", ""))
                    delta = str(event.data.get("delta", ""))
                    if tc_id and tc_id in _tool_args_buf:
                        _tool_args_buf[tc_id] += delta

                elif event.type == EventType.TOOL_CALL_END:
                    tc_id = str(event.data.get("tool_id", ""))
                    tname = _tool_names.get(tc_id, "tool")
                    display = tool_display_name(tname)
                    args_raw = _tool_args_buf.get(tc_id, "")
                    parsed_args = _parse_tool_args(args_raw)
                    short_label = _tool_short_label(display, parsed_args)
                    command = _tool_command(parsed_args)
                    if short_label or command:
                        _activity(
                            {
                                "type": "tool_call",
                                "tool_id": tc_id,
                                "tool_name": display,
                                "short_label": short_label,
                                "command": command,
                            },
                            level="normal",
                        )
                    if args_raw:
                        _append_log(f"tool args: {args_raw}")

                    # Run PreToolUse hooks
                    if self._hook_runner.has_hooks:
                        pre_results = await self._hook_runner.run_hooks(
                            HookType.PRE_TOOL_USE,
                            tname,
                            tool_args=parsed_args,
                        )
                        for hr in pre_results:
                            label = format_hook_result_line(hr)
                            _append_log(f"PreToolUse ({display}): {label}")
                            if not hr.success:
                                _activity({"type": "warning", "message": label}, level="debug")

                elif event.type == EventType.TOOL_START:
                    _stop_spinner()
                    tc_id = str(event.data.get("tool_id", ""))
                    _sync_tool_args_from_event(tc_id, event.data.get("args"))
                    tname = event.data.get("tool_name") or _tool_names.get(tc_id, "tool")
                    display = tool_display_name(tname)
                    args_raw = _tool_args_buf.get(tc_id, "")
                    parsed_args = _parse_tool_args(args_raw)
                    short_label = _tool_short_label(display, parsed_args)
                    command = _tool_command(parsed_args)
                    if short_label or command:
                        _activity(
                            {
                                "type": "tool_call",
                                "tool_id": tc_id,
                                "tool_name": display,
                                "short_label": short_label,
                                "command": command,
                            },
                            level="normal",
                        )
                    # No inline print here — the TOOL_RESULT handler
                    # prints the clean ● summary line with duration.
                    _start_spinner(f" {display}...")

                elif event.type == EventType.TOOL_RESULT:
                    _stop_spinner()
                    ok = bool(event.data.get("ok"))
                    tname = str(event.data.get("tool_name", "tool"))
                    display = tool_display_name(tname)
                    ms = event.data.get("duration_ms")
                    tc_id = str(event.data.get("tool_id", ""))
                    _sync_tool_args_from_event(tc_id, event.data.get("args"))
                    args_raw = _tool_args_buf.get(tc_id, "")
                    parsed_args = _parse_tool_args(args_raw)
                    short_label = _tool_short_label(display, parsed_args)
                    command = _tool_command(parsed_args)
                    result_preview, result_stderr, bytes_out = _result_components(event.data.get("result"))
                    summary = f"{display} {'ok' if ok else 'error'}"
                    if ms is not None:
                        try:
                            summary = f"{summary} ({float(ms):.0f}ms)"
                        except (TypeError, ValueError):
                            summary = f"{summary} ({ms})"

                    _activity(
                        {
                            "type": "tool_result",
                            "tool_id": tc_id,
                            "tool_name": display,
                            "short_label": short_label,
                            "command": command,
                            "ok": ok,
                            "duration_ms": ms,
                            "bytes_out": bytes_out,
                            "result_preview": result_preview,
                            "stderr": result_stderr,
                        },
                        level="normal",
                    )
                    # Print inline tool result so the user sees work happening
                    duration_f = float(ms) if ms is not None else 0.0
                    inline_summary = tool_summary_line(tname, parsed_args, duration_f)
                    status_style = "green" if ok else "red"
                    self._console.print(
                        f"  [{status_style}]●[/{status_style}] [dim]{rich_escape(inline_summary)}[/dim]"
                    )
                    if not ok:
                        _activity({"type": "error", "message": summary}, level="normal")
                        if result_stderr:
                            self._console.print(
                                f"    [red dim]{rich_escape(self._shorten(result_stderr.strip(), 120))}[/red dim]"
                            )
                    _append_log(f"tool result: {summary}")
                    if args_raw:
                        _append_log(f"tool args: {args_raw}")
                    if command:
                        _append_log(f"tool command: {command}")
                    if result_preview:
                        _append_log(f"tool output:\n{result_preview}")
                    if result_stderr:
                        _append_log(f"tool stderr:\n{result_stderr}")
                    if bytes_out is not None:
                        _append_log(f"tool bytes out: {bytes_out}")

                    # Post-edit diff summary for file-write tools
                    if tname in _FILE_WRITE_TOOLS and tc_id and args_raw:
                        try:
                            if isinstance(parsed_args, dict):
                                render_post_edit_summary(
                                    self._console,
                                    tname,
                                    parsed_args,
                                    ok,
                                    Path(self.config.tools.sandbox_path),
                                )
                        except Exception:
                            pass

                    # Run PostToolUse hooks
                    if self._hook_runner.has_hooks:
                        tool_result_data = event.data.get("result", "")
                        post_results = await self._hook_runner.run_hooks(
                            HookType.POST_TOOL_USE,
                            tname,
                            tool_args=parsed_args,
                            tool_result=tool_result_data,
                        )
                        for hr in post_results:
                            label = format_hook_result_line(hr)
                            _append_log(f"PostToolUse ({display}): {label}")
                            if not hr.success:
                                _activity({"type": "warning", "message": label}, level="debug")

                    _tool_args_buf.pop(tc_id, None)
                    _tool_names.pop(tc_id, None)
                    _tool_call_t0.pop(tc_id, None)
                    if "calling_tool" in _phase_t0:
                        _end_phase("calling_tool")
                    _start_spinner(" thinking...")

                elif event.type == EventType.TOOL_ERROR:
                    _stop_spinner()
                    tname = str(event.data.get("tool_name", "tool"))
                    tc_id = str(event.data.get("tool_id", ""))
                    error = str(event.data.get("message") or event.data.get("error") or "tool error")
                    _activity(
                        {
                            "type": "error",
                            "message": f"{tool_display_name(tname)}: {error}",
                        },
                        level="normal",
                    )
                    _append_log(f"tool error ({tc_id}): {error}")
                    if "calling_tool" in _phase_t0:
                        _end_phase("calling_tool")
                    _tool_args_buf.pop(tc_id, None)
                    _tool_names.pop(tc_id, None)
                    _tool_call_t0.pop(tc_id, None)

                elif event.type == EventType.SECURITY_FLAG:
                    message = str(event.data.get("message") or "Security warning")
                    _activity({"type": "warning", "message": message}, level="debug")
                    _append_log(f"SECURITY_FLAG: {message}")

                elif event.type == EventType.AGENT_ERROR:
                    _stop_spinner()
                    _finish_stream_line()
                    error = str(event.data.get("error", "unknown"))
                    _activity({"type": "error", "message": error}, level="normal")
                    _append_log(f"AGENT_ERROR: {error}")
                    self._console.print(f"[red]Thomas failed: {error}[/red] (see Activity / Logs)")

                elif event.type == EventType.AGENT_DONE:
                    _stop_spinner()
                    _finish_stream_line()
                    if "planning" in _phase_t0:
                        _end_phase("planning")
                    if _responding_started and "responding" in _phase_t0:
                        _end_phase("responding")
                    if "calling_tool" in _phase_t0:
                        _end_phase("calling_tool")
                    _activity("response complete", level="minimal")
                    # Use only the remaining streamed text (after prior
                    # segments were flushed as thinking panels).  Fall back
                    # to the full concatenated text only when nothing was
                    # streamed (e.g. fast / no-tool single-shot answers).
                    final_text = streamed_text.strip()
                    if not final_text:
                        final_text = str(event.data.get("text") or "").strip()
                    final_text = re.sub(r"</?thinking>", "", final_text, flags=re.IGNORECASE).strip()

                    if final_text:
                        self._console.print(
                            Panel(
                                Markdown(final_text),
                                title=ASSISTANT_PANEL_TITLE,
                                border_style=getattr(self, "_mascot_style", "cyan"),
                                expand=True,
                            )
                        )
                    token_report = event.data.get("token_report")
                    if isinstance(token_report, dict):
                        try:
                            prompt_tokens = int(token_report.get("prompt_tokens", 0) or 0)
                            completion_tokens = int(token_report.get("completion_tokens", 0) or 0)
                            total_tokens = int(token_report.get("total_tokens", 0) or 0)
                            if total_tokens > 0:
                                token_info = f"{prompt_tokens}+{completion_tokens}={total_tokens} tokens"
                        except (OSError, FileNotFoundError):
                            token_info = ""
                    iters = event.data["iterations"]
                    tc = event.data["tool_calls"]
                    parts = []
                    if iters > 1:
                        parts.append(f"{iters} iterations")
                    if tc > 0:
                        parts.append(f"{tc} tool call{'s' if tc != 1 else ''}")
                    if token_info:
                        parts.append(token_info)
                    if parts:
                        self._console.print(f"[dim]({', '.join(parts)})[/dim]")

                elif event.type == EventType.AGENT_END:
                    _stop_spinner()
                    _finish_stream_line()
                    message = str(event.data.get("message") or event.data.get("reason") or "agent ended")
                    _activity({"type": "warning", "message": message}, level="normal")
                    _append_log(f"AGENT_END: {message}")
                    return

        except KeyboardInterrupt:
            now = time.time()
            if cancel_ts > 0 and (now - cancel_ts) < 1.5:
                _stop_spinner()
                _finish_stream_line()
                self._console.print("\n[yellow](hard abort)[/yellow]")
                return
            cancel_ts = now
            cancelled = True
            _stop_spinner()
            _finish_stream_line()
            partial = streamed_text.strip()
            partial = re.sub(r"</?thinking>", "", partial, flags=re.IGNORECASE).strip()
            if partial:
                self._console.print(
                    Panel(
                        Markdown(partial),
                        title=f"{ASSISTANT_PANEL_TITLE} (partial)",
                        border_style="yellow",
                        expand=True,
                    )
                )
            self._console.print("[yellow](interrupted – press Ctrl+C again to abort)[/yellow]")

        except asyncio.CancelledError:
            _stop_spinner()
            _finish_stream_line()
            self._console.print("[yellow](cancelled)[/yellow]")
        finally:
            self._approval_handler.stop()
