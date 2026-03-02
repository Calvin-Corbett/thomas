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
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from thomas.agent.loop import AgentLoop
from thomas.cli.repl_approval import _FILE_WRITE_TOOLS, render_post_edit_summary
from thomas.cli.repl_hooks import HookType, format_hook_result_line, tool_summary_line
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

        agent = AgentLoop(
            config=self.config,
            llm=llm,
            tools=self.tools,
            conversation=self._conversation,
            memory=self._memory,
            thread_id="repl",
            autonomy_level=self._autonomy_level,
            guarded_tool_runner=guarded_runner,
            session_id="repl",
            run_id="repl",
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

        def _activity(message: str, *, level: str = "normal") -> None:
            if hasattr(self, "_record_activity"):
                self._record_activity(message, level=level)

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
                    route = event.data.get("route", {}) if isinstance(event.data.get("route"), dict) else {}
                    mode = route.get("mode") or event.data.get("mode") or "auto"
                    policy = event.data.get("tools_policy", "auto")
                    level = int(event.data.get("autonomy_level", self._autonomy_level) or self._autonomy_level)
                    name = str(event.data.get("autonomy_name") or autonomy_level_name(level))
                    _activity("planning...", level="minimal")
                    self._print_auto(f"route={mode}, tools={policy}, autonomy=L{level} {name}")

                elif event.type == EventType.STATUS:
                    message = str(event.data.get("message") or "").strip()
                    if message:
                        _activity(message, level="debug")

                elif event.type == EventType.MEMORY_QUERY:
                    _activity("retrieving memory...", level="minimal")

                elif event.type == EventType.MEMORY_RESULT:
                    _activity("memory result received", level="debug")

                elif event.type == EventType.AGENT_ITERATION:
                    ctx_tokens = event.data.get("token_estimate", 0)
                    ctx_window = event.data.get("context_window", 0)
                    iteration = event.data.get("iteration", 0)
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
                        is_streaming = True
                        self._console.file.write(token)
                        self._console.file.flush()

                elif event.type == EventType.TOOL_CALL_START:
                    _stop_spinner()
                    _finish_stream_line()
                    tc_id = str(event.data.get("tool_id", ""))
                    tname = event.data["tool_name"]
                    _activity(f"calling tool {tname}...", level="normal")
                    if tc_id:
                        _tool_names[tc_id] = tname
                        _tool_args_buf[tc_id] = ""

                elif event.type == EventType.TOOL_CALL_ARGS_DELTA:
                    tc_id = str(event.data.get("tool_id", ""))
                    delta = str(event.data.get("delta", ""))
                    if tc_id and tc_id in _tool_args_buf:
                        _tool_args_buf[tc_id] += delta

                elif event.type == EventType.TOOL_CALL_END:
                    tc_id = str(event.data.get("tool_id", ""))
                    tname = _tool_names.get(tc_id, "tool")
                    args_raw = _tool_args_buf.get(tc_id, "")
                    # Parse args for display and hooks
                    parsed_args: dict[str, Any] = {}
                    if args_raw:
                        try:
                            parsed_args = json.loads(args_raw)
                        except json.JSONDecodeError:
                            pass
                    # Run PreToolUse hooks
                    if self._hook_runner.has_hooks:
                        pre_results = await self._hook_runner.run_hooks(
                            HookType.PRE_TOOL_USE, tname, tool_args=parsed_args,
                        )
                        for hr in pre_results:
                            status_color = "green" if hr.success else "red"
                            label = format_hook_result_line(hr)
                            self._console.print(
                                f"  [dim]\u2514[/dim] [{status_color}]{label}[/{status_color}]"
                            )

                elif event.type == EventType.TOOL_START:
                    _stop_spinner()
                    tc_id = str(event.data.get("tool_id", ""))
                    tname = event.data.get("tool_name") or _tool_names.get(tc_id, "tool")
                    args_raw = _tool_args_buf.get(tc_id, "")
                    parsed_args = {}
                    if args_raw:
                        try:
                            parsed_args = json.loads(args_raw)
                        except json.JSONDecodeError:
                            pass
                    from thomas.cli.repl_hooks import tool_display_name
                    display = tool_display_name(tname)
                    _start_spinner(f" {display}...")

                elif event.type == EventType.TOOL_RESULT:
                    _stop_spinner()
                    ok = event.data["ok"]
                    tname = event.data["tool_name"]
                    ms = event.data["duration_ms"]
                    tc_id = str(event.data.get("tool_id", ""))
                    args_raw = _tool_args_buf.get(tc_id, "")
                    parsed_args: dict[str, Any] = {}
                    if args_raw:
                        try:
                            parsed_args = json.loads(args_raw)
                        except json.JSONDecodeError:
                            pass

                    if ok:
                        _activity(f"tool result received ({tname})", level="normal")
                        _activity(f"{tname} completed in {ms:.0f}ms", level="debug")
                        # Claude Code-style: â— summary line
                        summary = tool_summary_line(tname, parsed_args, ms)
                        self._console.print(
                            f"  [bold green]\u25cf[/bold green] [dim]{summary}[/dim]"
                        )
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
                    else:
                        _activity(f"tool failed ({tname})", level="normal")
                        err = str(event.data.get("result", "failed"))[:100]
                        self._console.print(
                            f"  [bold red]\u25cf[/bold red] [dim]{tname}[/dim] "
                            f"[red]-> {err}[/red]"
                        )

                    # Run PostToolUse hooks
                    if self._hook_runner.has_hooks:
                        tool_result_data = event.data.get("result", "")
                        post_results = await self._hook_runner.run_hooks(
                            HookType.POST_TOOL_USE, tname,
                            tool_args=parsed_args,
                            tool_result=tool_result_data,
                        )
                        for hr in post_results:
                            status_color = "green" if hr.success else "red"
                            label = format_hook_result_line(hr)
                            self._console.print(
                                f"  [dim]\u2514[/dim] [{status_color}]{label}[/{status_color}]"
                            )

                    _tool_args_buf.pop(tc_id, None)
                    _tool_names.pop(tc_id, None)
                    _start_spinner(" thinking...")

                elif event.type == EventType.AGENT_ERROR:
                    _stop_spinner()
                    _finish_stream_line()
                    _activity("response failed", level="minimal")
                    self._console.print(f"[bold red]Error:[/bold red] {event.data['error']}")

                elif event.type == EventType.AGENT_DONE:
                    _stop_spinner()
                    _finish_stream_line()
                    _activity("response complete", level="minimal")
                    final_text = str(event.data.get("text") or "").strip()
                    if not final_text:
                        final_text = streamed_text.strip()
                    final_text = re.sub(r"</?thinking>", "", final_text, flags=re.IGNORECASE).strip()

                    # Only render the panel if we didn't already stream
                    # the text live to the terminal. If streamed_text has
                    # content, the user already saw it token-by-token.
                    if final_text and not streamed_text.strip():
                        self._console.print(
                            Panel(
                                Markdown(final_text),
                                title=ASSISTANT_PANEL_TITLE,
                                border_style=getattr(self, "_mascot_style", "cyan"),
                                expand=True,
                            )
                        )
                    elif streamed_text.strip():
                        # Streamed text was already displayed â€” just add
                        # a subtle separator so the token stats line below
                        # doesn't merge with the response.
                        self._console.print()
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
            self._console.print("[yellow](interrupted \u2013 press Ctrl+C again to abort)[/yellow]")

        except asyncio.CancelledError:
            _stop_spinner()
            _finish_stream_line()
            self._console.print("[yellow](cancelled)[/yellow]")
        finally:
            self._approval_handler.stop()

