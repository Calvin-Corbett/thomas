"""The REPL's turn-taking half: running a turn, models, sessions, pickers, the mascot.

``ThomasREPL`` was one 1,101-line class. The seam finder read it by its methods
and found two groups with five cross-calls and three shared helpers; this
mixin is the second group plus the shared helpers, and the labels and the
version helper those methods use. Every cross-call resolves through ``self``,
so ``ThomasREPL`` behaves exactly as before with one more base.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import os
import random
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.shortcuts import CompleteStyle
    from prompt_toolkit.styles import Style
except ImportError:
    raise ImportError(
        "prompt_toolkit is required for the REPL. Install with: pip install prompt_toolkit>=3.0"
    ) from None
try:
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text
except ImportError:
    raise ImportError("rich is required for the REPL. Install with: pip install rich>=13.0") from None
from thomas.cli.repl_picker import PickerOption, resolve_picker_selection
from thomas.cli.repl_skills import list_all_skills
from thomas.cli.repl_slash import (
    SlashArgOption,
    slash_arg_options,
)
from thomas.cli.repl_state import ReplUiState, is_valid_ui_transition
from thomas.core.llm import LLMClient
from thomas.core.llm_slot import models
from thomas.core.model_resolution import build_model_label

try:
    from thomas.memory.autonomy import AutonomyMemoryEngine

    _HAS_MEMORY = True
except ImportError:
    _HAS_MEMORY = False

log = logging.getLogger(__name__)

USER_PROMPT_LABEL = ">"
USER_PANEL_TITLE = "USER"
ASSISTANT_PANEL_TITLE = "THOMAS"
AUTO_LABEL = "THOMAS"
_OVERLAY_EXIT_ACCEPT = "accept"
_OVERLAY_EXIT_BACK = "back"
_OVERLAY_EXIT_CLOSE = "close"
_MASCOT_LINES = [
    " ┌──────┐ ",
    " │ ▪  ▪ │ ",
    " └─┬──┬─┘ ",
    "   │ ██ │ ",
    "   │_▁▁_│ ",
    "    ░  ░  ",
]
_USER_PANEL_STYLE = "bright_blue"

_ACCENT_PALETTE: list[tuple[str, str]] = [
    ("bright_cyan", "#00bcd4"),
    ("bright_magenta", "#d946ef"),
    ("bright_yellow", "#f59e0b"),
    ("bright_green", "#22c55e"),
    ("bright_white", "#e5e7eb"),
    ("cyan", "#06b6d4"),
    ("magenta", "#c026d3"),
    ("bright_red", "#ef4444"),
    ("green", "#16a34a"),
    ("yellow", "#eab308"),
    ("red", "#dc2626"),
    ("deep_pink2", "#ff0066"),
    ("dark_orange", "#ff8c00"),
    ("medium_purple1", "#af87ff"),
    ("spring_green2", "#00d75f"),
    ("turquoise2", "#00d7ff"),
]


def _get_version() -> str:
    try:
        from thomas import __version__

        return __version__
    except (ImportError, AttributeError):
        return "?"


class ThomasREPLTurnsMixin:
    """Turn running, models, sessions and pickers; mixed into ``ThomasREPL``."""

    def _watch_escape_interrupt(self, stop: threading.Event, triggered: threading.Event) -> None:
        if stop.is_set():
            return
        if os.name != "nt":
            # Non-blocking key polling is intentionally platform-agnostic
            # only where required by this environment. Windows receives the
            # primary support path for ESC interrupts.
            return

        try:
            import msvcrt
        except ImportError:
            return

        while not stop.is_set():
            try:
                if not msvcrt.kbhit():
                    time.sleep(0.06)
                    continue
                key = msvcrt.getwch()
                if key in {"\x1b", "\x03"}:
                    triggered.set()
                    return
                if key == "\x00":
                    if msvcrt.kbhit():
                        _ = msvcrt.getwch()
            except OSError:
                return

    async def _run_agent_turn(self, prompt: str) -> None:
        self._runtime_context_window = None
        self._last_context_source = None
        stop = threading.Event()
        triggered = threading.Event()
        watcher = threading.Thread(
            target=self._watch_escape_interrupt,
            args=(stop, triggered),
            name="thomas-repl-escape-watcher",
            daemon=True,
        )
        watcher.start()
        run_task = asyncio.create_task(self._run_agent(prompt))

        try:
            while True:
                done, _pending = await asyncio.wait(
                    {run_task},
                    timeout=0.08,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if run_task in done:
                    await run_task
                    return
                if triggered.is_set():
                    if not run_task.done():
                        run_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await run_task
                    self._console.print("[yellow](cancelled)[/yellow]")
                    return
        finally:
            stop.set()
            watcher.join(timeout=0.2)

    def _known_model_profile_names(self) -> list[str]:
        names = list(self.config.models.keys())
        names.sort(key=lambda x: x.lower())
        return names

    def _pinned_keys(self) -> list[str]:
        if not (self._memory and self._memory.started):
            return []
        try:
            pins = self._memory.list_pins()
        except (OSError, ValueError, TypeError):
            return []
        values: list[str] = []
        for key, _text, _score in pins:
            key_s = str(key or "").strip()
            if key_s:
                values.append(key_s)
        return sorted(set(values), key=lambda x: x.lower())

    def _slash_arg_values(self, command: str) -> list[str]:
        if command == "/unpin":
            return self._pinned_keys()
        if command in ("/load", "/save"):
            json_files = [p.name for p in Path.cwd().glob("*.json") if p.is_file()]
            return sorted(json_files, key=lambda x: x.lower())
        if command == "/skill":
            try:
                return sorted(list_all_skills().keys())
            except (OSError, RuntimeError, TypeError, ValueError):
                return []
        if command == "/worktree":
            return ["create", "list", "remove"]
        return []

    def _slash_arg_options(self, command: str) -> list[SlashArgOption]:
        return slash_arg_options(command, self)

    def _should_show_mascot(self) -> bool:
        hide = str(os.environ.get("THOMAS_NO_MASCOT", "")).strip().lower()
        return hide not in {"1", "true", "on", "yes", "enabled", "enable"}

    def _resolved_model_label(self) -> str:
        current_profile = str(self._current_model or "").strip()
        if not current_profile:
            return ""
        try:
            current_model = str(self.config.models.get(current_profile).model or "").strip()
        except (AttributeError, KeyError, TypeError):
            current_model = ""
        return build_model_label(current_profile, current_model)

    def _resolve_picker_selection(self, typed: str, options: list[PickerOption], *, default: str = "") -> str:
        normalized = resolve_picker_selection(str(typed or "").strip(), options).strip()
        if not normalized:
            if default:
                default_normalized = str(default or "").strip().lower()
                for option in options:
                    if str(option.value).strip().lower() == default_normalized:
                        return str(option.value)
                return str(default).strip()
            return ""
        if any(str(option.value).strip().lower() == normalized.lower() for option in options):
            return normalized
        return ""

    async def _run_interactive_flow(
        self,
        *,
        prompt: str,
        options: list[PickerOption],
        default: str = "",
        menu_rows: int = 8,
        match_middle: bool = True,
        parent_command: str | None = None,
    ) -> str | object:
        if not options:
            return ""
        selected = await self._interactive_flow.choose(
            prompt=prompt,
            options=options,
            default=default,
            menu_rows=menu_rows,
            match_middle=match_middle,
            parent_command=parent_command,
        )
        if self._overlay_exit_action == _OVERLAY_EXIT_BACK:
            return self._overlay_back_sentinel
        return str(selected or "").strip()

    def _composer_toolbar_hint(self) -> str:
        token_info = self._get_token_usage_display()
        bg_info = self._background_toolbar_badge()
        panel_state: list[str] = []
        if self._help_panel_open:
            panel_state.append("Help")
        if self._activity_panel_open:
            panel_state.append(f"Activity:{self._activity_verbosity}")
        if self._logs_panel_open:
            panel_state.append("Logs")
        panels = f" [{'/'.join(panel_state)}]" if panel_state else ""
        line = f"{self._status_badges()}{panels}  F1 Help  F2 Activity  F3 Logs  Ctrl+Space Commands  Tab Focus"
        if bg_info:
            line = f"{line}  {bg_info}"
        if token_info:
            line = f"{line}  {token_info}"
        return self._truncate_to_terminal(line)

    def _background_toolbar_badge(self) -> str:
        tasks = self._bg_manager.list_tasks()
        running = [task for task in tasks if task.status == "running"]
        if not running:
            return ""
        now = time.time()
        oldest_started = min(float(task.started_at or now) for task in running)
        elapsed_seconds = max(0.0, now - oldest_started)
        total = len(running)
        return f"[bg:running {total} | {self._format_elapsed_short(elapsed_seconds)}]"

    @staticmethod
    def _format_elapsed_short(seconds: float) -> str:
        total = max(0, int(seconds))
        minutes, secs = divmod(total, 60)
        hours, minutes = divmod(minutes, 60)
        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"

    def _status_badges(self) -> str:
        return (
            f"[model:{self._current_model}] "
            f"[autonomy:L{self._autonomy_level}] "
            f"[tools:{self._tools_policy}] "
            f"[route:{self._last_route}]"
        )

    def _new_session_theme(self) -> tuple[str, str]:
        style, hex_color = random.choice(_ACCENT_PALETTE)
        return style, hex_color

    @staticmethod
    def _new_repl_session_id() -> str:
        return f"repl-{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _new_chat_thread_id(session_id: str) -> str:
        base = str(session_id or "").strip() or f"repl-{uuid.uuid4().hex[:12]}"
        return f"{base}-chat"

    def _rotate_chat_thread(self) -> None:
        self._repl_session_id = self._new_repl_session_id()
        self._chat_thread_id = self._new_chat_thread_id(self._repl_session_id)
        self._chat_run_counter = 0

    def _next_chat_run_id(self) -> str:
        self._chat_run_counter += 1
        return f"{self._repl_session_id}-turn-{self._chat_run_counter}"

    def _truncate_to_terminal(self, text: str) -> str:
        try:
            width = int(self._console.size.width or 120)
        except (AttributeError, TypeError, ValueError):
            width = 120
        width = max(20, width - 1)
        if len(text) <= width:
            return text
        return text[: max(1, width - 1)] + "..."

    def _startup_header_lines(self, version: str) -> list[str]:
        model_label = str(self._current_model or "").strip()
        info_pairs = [
            ("model", model_label),
            ("autonomy", f"L{self._autonomy_level}"),
            ("tools", str(self._tools_policy)),
        ]
        label_w = max(len(k) for k, _ in info_pairs)
        raw_details: list[str] = [f"THOMAS v{version}"]
        for key, val in info_pairs:
            raw_details.append(f"{key:>{label_w}}: {val}")
        # Offset details so title aligns with the eyes row (line 1)
        details: list[str] = [""] + raw_details
        mascot = list(_MASCOT_LINES)
        pad = max(len(line) for line in mascot) + 2 if mascot else 2
        merged: list[str] = []
        style = str(getattr(self, "_mascot_style", "") or "bright_cyan")
        for idx in range(max(len(mascot), len(details))):
            left = mascot[idx] if idx < len(mascot) else ""
            right = details[idx] if idx < len(details) else ""
            if right:
                merged.append(f"[{style}]{left.ljust(pad)}[/{style}] {right}")
            else:
                merged.append(f"[{style}]{left}[/{style}]")
        return merged

    def _erase_prompt_line(self) -> None:
        if not bool(getattr(sys.stdout, "isatty", lambda: False)()):
            return
        try:
            # Cursor is on the next line after Enter; clear both lines so input is ephemeral.
            sys.stdout.write("\r\033[2K\033[1A\033[2K\r")
            sys.stdout.flush()
        except OSError:
            return

    def _print_turn(self, role: str, text: str) -> None:
        content = (text or "").strip()
        if not content:
            return
        role_key = (role or "").strip().lower()
        if role_key == "user":
            self._console.print(
                Panel(Text(content), title=USER_PANEL_TITLE, border_style=_USER_PANEL_STYLE, expand=True)
            )
        elif role_key == "assistant":
            self._console.print(
                Panel(Text(content), title=ASSISTANT_PANEL_TITLE, border_style=self._mascot_style, expand=True)
            )
        elif role_key == "system":
            self._console.print(f"[dim]SYSTEM: {content}[/dim]")
        else:
            self._console.print(f"[dim]{role}:[/dim] {content}")

    def _append_transcript_turn(self, role: str, text: str) -> None:
        content = (text or "").strip()
        if not content:
            return
        self._print_turn(role, content)

    def _print_system_event(self, text: str, *, important: bool = False) -> None:
        if not text:
            return
        if not important and not self._show_system_logs:
            return
        self._print_turn("system", text)

    def _transition_ui_state(self, target: ReplUiState) -> None:
        source = self._ui_state
        if not is_valid_ui_transition(source, target):
            log.debug("Invalid REPL UI state transition: %s -> %s", source.value, target.value)
            self._ui_state = ReplUiState.IDLE
            return
        self._ui_state = target

    async def _prompt_overlay(
        self,
        prompt_html: HTML,
        *,
        default: str = "",
        completer: Any | None = None,
        menu_rows: int = 10,
        toolbar_text: str = "",
        start_completion: bool = False,
    ) -> str:
        """Render a non-destructive overlay prompt and return user selection."""
        self._overlay_exit_action = _OVERLAY_EXIT_ACCEPT
        self._enter_overlay_screen()
        # Keep overlay menus scrollable and sized relative to terminal height.
        try:
            terminal_height = int(self._console.size.height or 24)
        except (TypeError, ValueError, OSError):
            terminal_height = 24
        adaptive_rows = max(4, min(int(menu_rows), terminal_height - 8))
        prompt_async_params = inspect.signature(self._session.prompt_async).parameters
        overlay_kwargs = {
            "default": default,
            "completer": completer,
            "complete_while_typing": True,
            "reserve_space_for_menu": adaptive_rows,
        }
        if "bottom_toolbar" in prompt_async_params:
            overlay_kwargs["bottom_toolbar"] = (lambda: toolbar_text) if toolbar_text else None
        if "erase_when_done" in prompt_async_params:
            overlay_kwargs["erase_when_done"] = True
        if start_completion:

            def _start_completion_immediately() -> None:
                try:
                    from prompt_toolkit.application.current import get_app

                    app = get_app()
                    if app.current_buffer:
                        app.current_buffer.start_completion(select_first=True)
                except (AttributeError, RuntimeError):
                    return

            overlay_kwargs["pre_run"] = _start_completion_immediately
        try:
            if "prompt" in prompt_async_params:
                typed = await self._session.prompt_async(prompt=prompt_html, **overlay_kwargs)
            elif "message" in prompt_async_params:
                typed = await self._session.prompt_async(message=prompt_html, **overlay_kwargs)
            else:
                typed = await self._session.prompt_async(prompt_html, **overlay_kwargs)
            return str(typed or "").strip()
        finally:
            self._erase_prompt_line()
            self._exit_overlay_screen()

    async def _pick_slash_command(self, *, default: str = "/") -> str:
        options = [
            PickerOption(
                value=spec.command,
                label=spec.command,
                description=spec.summary,
            )
            for spec in self._slash_specs
        ]
        if not options:
            return ""
        try:
            picked = await self._run_interactive_flow(
                prompt="slash",
                options=options,
                default=default,
                menu_rows=10,
                match_middle=True,
            )
        except (KeyboardInterrupt, EOFError):
            return ""
        if picked is self._overlay_back_sentinel:
            return ""
        return self._resolve_picker_selection(str(picked or ""), options, default=default)

    async def _pick_slash_argument(self, command: str, arg: str) -> str | object:
        arg_text = str(arg or "").strip()

        choices = self._slash_arg_options(command)
        if not choices:
            return arg_text

        sorted_choices = sorted(
            choices,
            key=lambda opt: (str(opt.value).lower(), str(opt.label).lower()),
        )
        rows = min(8, max(4, len(sorted_choices)))

        options = [
            PickerOption(
                value=choice.value,
                label=choice.label,
                description=choice.description,
            )
            for choice in sorted_choices
        ]
        try:
            picked = await self._run_interactive_flow(
                prompt=command,
                options=options,
                default=arg_text,
                menu_rows=rows,
                match_middle=True,
                parent_command=command,
            )
        except (KeyboardInterrupt, EOFError):
            return arg_text

        if picked is self._overlay_back_sentinel:
            return self._overlay_back_sentinel
        return self._resolve_picker_selection(str(picked or ""), options, default=arg_text)

    def _enter_overlay_screen(self) -> None:
        self._overlay_depth += 1
        if not self._use_alt_screen:
            return
        if not bool(getattr(sys.stdout, "isatty", lambda: False)()):
            return
        if self._alt_screen_active:
            return
        # Alternate screen enter (DECSET 1049).
        sys.stdout.write("\x1b[?1049h")
        sys.stdout.flush()
        self._alt_screen_active = True

    def _exit_overlay_screen(self) -> None:
        self._overlay_depth = max(0, self._overlay_depth - 1)
        if not self._use_alt_screen:
            return
        if not bool(getattr(sys.stdout, "isatty", lambda: False)()):
            return
        if not self._alt_screen_active:
            return
        if self._overlay_depth > 0:
            return
        # Alternate screen leave (DECRST 1049).
        sys.stdout.write("\x1b[?1049l")
        sys.stdout.flush()
        self._alt_screen_active = False

    async def _pick_model_choice(self, profiles: list[str], model_ids: list[str]) -> str:
        profile_set = {name.lower(): name for name in profiles}
        model_id_set = {mid.lower(): mid for mid in model_ids}
        current_profile = str(self._current_model or "").strip()
        current_model_id = str(self.config.models.get(self._current_model).model or "").strip()
        options: list[PickerOption] = [
            PickerOption(
                value=name,
                label=name,
                description="profile",
                is_current=name == current_profile,
            )
            for name in profiles
        ]
        options.extend(
            PickerOption(
                value=mid,
                label=mid,
                description="model id",
                is_current=mid == current_model_id,
            )
            for mid in model_ids
        )
        if not options:
            return ""
        default_value = self._current_model if self._current_model in profiles else ""
        menu_rows = 10
        try:
            selected = await self._run_interactive_flow(
                prompt="model",
                options=options,
                default=default_value,
                menu_rows=menu_rows,
                match_middle=True,
                parent_command="/model",
            )
        except (KeyboardInterrupt, EOFError):
            return ""
        if selected is self._overlay_back_sentinel:
            return ""
        picked = self._resolve_picker_selection(str(selected or ""), options, default=default_value)
        lowered = picked.lower()
        if lowered in profile_set:
            return profile_set[lowered]
        if lowered in model_id_set:
            return model_id_set[lowered]
        return ""

    async def _maybe_pick_reasoning_level(self, selected_model_id: str) -> bool:
        model_id = str(selected_model_id or "").strip().lower()
        model_profile = str(self._current_model or "").strip()
        try:
            current_cfg = self.config.get_model(model_profile)
        except (KeyError, RuntimeError, TypeError, ValueError):
            current_cfg = None
        if current_cfg is None:
            return False
        provider = str(getattr(current_cfg, "provider", "") or "").strip().lower()
        configured_model_id = str(getattr(current_cfg, "model", "") or "").strip().lower()
        if not model_id:
            model_id = configured_model_id
        if provider != "codex" and not model_id.startswith("gpt-5"):
            return False
        levels = ["minimal", "low", "medium", "high", "xhigh"]
        default_value = ""
        options = [PickerOption(value=level, label=level, is_current=(level == default_value)) for level in levels]
        try:
            picked = await self._run_interactive_flow(
                prompt="reasoning",
                options=options,
                default=default_value,
                menu_rows=6,
                match_middle=False,
                parent_command="/model",
            )
        except (KeyboardInterrupt, EOFError):
            return False
        if picked is self._overlay_back_sentinel:
            return True
        picked = self._resolve_picker_selection(str(picked or ""), options, default=default_value)
        if picked not in levels:
            return False
        self.config.models[self._current_model].reasoning_effort = picked
        self._console.print(f"[dim]Reasoning level set to {picked}[/dim]")
        return False

    async def _flash_status(self, text: str, seconds: float = 0.9) -> None:
        message = str(text or "").strip()
        if not message:
            return
        live = Live(Text(message, style="dim"), console=self._console, transient=True, refresh_per_second=30)
        try:
            live.start()
            await asyncio.sleep(max(0.1, float(seconds)))
        except (ValueError, OSError):
            self._console.print(f"[dim]{message}[/dim]")
            return
        finally:
            with contextlib.suppress(OSError):
                live.stop()

    def _get_llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = models().profile(self.config, self._current_model, default=LLMClient)
        return self._llm

    def _get_prompt(self) -> HTML:
        return HTML(f"<prompt>{USER_PROMPT_LABEL}</prompt> ")

    def _print_auto(self, text: str) -> None:
        label = f"[bold magenta]{AUTO_LABEL}[/bold magenta]"
        self._console.print(f"{label} [dim]{text}[/dim]")

    async def run(self) -> None:
        """Main REPL loop."""
        version = _get_version()
        if self._should_show_mascot():
            self._console.print("\n".join(self._startup_header_lines(version)))
            self._console.print(f"[{self._mascot_style}]{'─' * 40}[/{self._mascot_style}]")
        else:
            self._console.print(f"[bold green]THOMAS[/bold green] v{version}")
            self._console.print(f"[dim]model: {self._resolved_model_label() or self._current_model}[/dim]")
            self._console.print(f"[dim]autonomy: L{self._autonomy_level}[/dim]")
            self._console.print(f"[dim]tools: {self._tools_policy}[/dim]")
            self._console.print(f"[dim]route: {self._last_route}[/dim]")
        if self._trace_file_reads:
            self._print_read_file_trace("Startup")
        if self._restored_conversation_count > 0:
            self._console.print(
                "[dim]Resumed "
                f"{self._restored_conversation_count} messages from previous REPL session. "
                "Use /clear for a fresh start.[/dim]"
            )

        # Connect to MCP servers at startup (best-effort)
        try:
            from thomas.tools.mcp_bridge import register_mcp_tools

            self._mcp_bridge = await register_mcp_tools(self.tools, self.config)
            connected = self._mcp_bridge.list_servers()
            if connected:
                self._console.print(f"[dim]MCP servers: {', '.join(connected)}[/dim]")
        except (ConnectionError, OSError, RuntimeError, TypeError, ValueError) as e:
            log.debug("MCP startup failed: %s", e)

        while True:
            try:
                prompt_kwargs = {}
                if "erase_when_done" in inspect.signature(self._session.prompt_async).parameters:
                    prompt_kwargs["erase_when_done"] = True
                user_input = await self._session.prompt_async(
                    self._get_prompt(),
                    rprompt=HTML(f"<ansigray>{self._session_turns} turns</ansigray>")
                    if self._session_turns > 0
                    else None,
                    bottom_toolbar=(lambda: self._composer_toolbar_hint()),
                    **prompt_kwargs,
                )
            except KeyboardInterrupt:
                self._console.print("\n[dim](interrupted - type /exit to quit)[/dim]")
                continue
            except EOFError:
                break
            self._erase_prompt_line()

            user_input = user_input.strip()
            if not user_input:
                continue

            # Escape hatch for literal slash-prefixed chat text.
            if user_input.startswith("//"):
                user_input = user_input[1:]
                self._append_transcript_turn("user", user_input)
            elif user_input.startswith("/"):
                should_exit, handled = await self._handle_slash(user_input)
                if should_exit:
                    break
                if handled:
                    continue
                # Unknown slash-like input can be treated as plain text.
            # For plain text chat, render user input once in the transcript.
            self._append_transcript_turn("user", user_input)

            # Run agent
            self._session_turns += 1
            self._print_read_file_trace("Turn")
            try:
                await self._run_agent_turn(user_input)
            except KeyboardInterrupt:
                self._print_system_event("(cancelled)", important=True)
            self._persist_conversation_state()

        self._console.print("[dim]Goodbye.[/dim]")

        # Cancel background tasks
        await self._bg_manager.cancel_all()

        # Disconnect MCP servers
        if self._mcp_bridge:
            try:
                await self._mcp_bridge.disconnect_all()
            except (ConnectionError, OSError, RuntimeError, TypeError, ValueError) as e:
                log.debug("MCP cleanup failed: %s", e)

        # Prompt about worktree cleanup
        if self._worktree:
            self._console.print(f"[yellow]Active worktree: {self._worktree.name} at {self._worktree.path}[/yellow]")
            self._console.print("[dim]Use 'git worktree remove' to clean up manually.[/dim]")

        while self._alt_screen_active:
            self._exit_overlay_screen()
        if self._llm:
            await self._llm.close()
        if self._memory:
            self._memory.close()
        self._persist_runtime_settings()
        self._persist_conversation_state()
