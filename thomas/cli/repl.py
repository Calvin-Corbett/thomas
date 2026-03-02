"""Interactive REPL for Thomas using prompt_toolkit and rich."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import os
import re
import sys
import threading
import time
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

from thomas.cli.repl_agent_runtime import ThomasREPLAgentMixin
from thomas.cli.repl_approval import ReplApprovalHandler, create_repl_approval_handler
from thomas.cli.repl_background import BackgroundTaskManager
from thomas.cli.repl_hooks import HookRunner
from thomas.cli.repl_keybindings import apply_keybindings, load_keybindings
from thomas.cli.repl_picker import PickerCompleter, PickerOption, picker_toolbar_hint, resolve_picker_selection
from thomas.cli.repl_plan import PlanModeHandler
from thomas.cli.repl_project import instruction_file_path
from thomas.cli.repl_runtime import ThomasREPLRuntimeMixin
from thomas.cli.repl_skills import list_all_skills
from thomas.cli.repl_slash import (
    SlashArgOption,
    SlashCommandCompleter,
    is_known_slash_command,
    list_slash_specs,
    slash_arg_options,
)
from thomas.cli.repl_state import ReplUiState, is_valid_ui_transition
from thomas.core.config import AppConfig
from thomas.core.model_resolution import build_model_label
from thomas.core.llm import LLMClient
from thomas.tools.registry import ToolRegistry

log = logging.getLogger(__name__)
try:
    from thomas.memory.autonomy import AutonomyMemoryEngine

    _HAS_MEMORY = True
except ImportError:
    _HAS_MEMORY = False


# Backward-compat exports used by tests and older imports.
_SlashCommandCompleter = SlashCommandCompleter

USER_PROMPT_LABEL = ">"
USER_PANEL_TITLE = "USER"
ASSISTANT_PANEL_TITLE = "THOMAS"
AUTO_LABEL = "THOMAS"
_OVERLAY_EXIT_ACCEPT = "accept"
_OVERLAY_EXIT_BACK = "back"
_OVERLAY_EXIT_CLOSE = "close"
_MASCOT_LINES = [
    "   /----\\",
    "  | ..  |",
    "  | --  |",
    " /|_||_|\\",
    "   |  |",
    "   |__|",
]


def _is_known_slash_command(text: str) -> bool:
    return is_known_slash_command(text)


class InteractiveFlow:
    """Reusable overlay picker workflow used for slash and follow-up menus."""

    def __init__(self, repl: "ThomasREPL") -> None:
        self._repl = repl

    def _normalize_options(
        self,
        options: list[PickerOption],
        default: str,
    ) -> list[PickerOption]:
        default_value = str(default or "").strip()
        normalized: list[PickerOption] = []
        if default_value:
            for option in options:
                normalized.append(
                    PickerOption(
                        value=str(option.value),
                        label=str(option.label),
                        description=str(option.description),
                        is_current=(
                            str(option.value) == default_value
                            or str(option.label) == default_value
                            or getattr(option, "is_current", False)
                        ),
                    )
                )
        else:
            for option in options:
                normalized.append(
                    PickerOption(
                        value=str(option.value),
                        label=str(option.label),
                        description=str(option.description),
                        is_current=bool(getattr(option, "is_current", False)),
                    )
                )

        defaults = [opt for opt in normalized if opt.is_current]
        if defaults:
            first = defaults[0]
            others = [opt for opt in normalized if opt is not first]
            return [first, *others]
        return normalized

    async def choose(
        self,
        *,
        prompt: str,
        options: list[PickerOption],
        default: str = "",
        menu_rows: int = 8,
        match_middle: bool = True,
        parent_command: str | None = None,
    ) -> str:
        prepared = self._normalize_options(options, default=default)
        if not prepared:
            return ""
        if parent_command:
            self._repl._overlay_parent_command = parent_command
            self._repl._transition_ui_state(ReplUiState.PICKER)
        else:
            self._repl._overlay_parent_command = None
            self._repl._transition_ui_state(ReplUiState.PICKER)

        try:
            selected = await self._repl._prompt_overlay(
                HTML(f"<prompt>{prompt}</prompt> > "),
                default=default,
                completer=PickerCompleter(prepared, match_middle=match_middle),
                menu_rows=min(1, int(menu_rows)) if menu_rows <= 0 else menu_rows,
                toolbar_text=picker_toolbar_hint(len(prepared), max(1, int(menu_rows))),
                start_completion=True,
            )
        finally:
            self._repl._transition_ui_state(ReplUiState.IDLE)
            self._repl._overlay_parent_command = None
        return selected


class ThomasREPL(ThomasREPLRuntimeMixin, ThomasREPLAgentMixin):
    """Interactive REPL with rich terminal UI."""

    def __init__(self, config: AppConfig, tools: ToolRegistry, *, trace_file_reads: bool = False):
        self.config = config
        self.tools = tools
        self._conversation: list[dict[str, Any]] = []
        resolved_profile = str(config.default_model)
        resolved_model_id = ""
        try:
            from thomas.core.model_resolution import resolve_effective_model
            from thomas.preferences.store import get_db_path

            resolved_profile, resolved_model_id = resolve_effective_model(
                config,
                env_profile=str(os.environ.get("THOMAS_DEFAULT_MODEL", "")).strip(),
                user_id="default",
                db_path=get_db_path(),
            )
            if resolved_profile in config.models:
                config.default_model = resolved_profile
                if resolved_model_id:
                    config.models[resolved_profile].model = resolved_model_id
        except Exception:
            resolved_profile = str(config.default_model)
        self._current_model: str = resolved_profile
        self._autonomy_level: int = 3
        self._tools_policy: str = "auto"
        self._last_route: str = "auto"
        self._last_model_choices: list[str] = []
        self._show_system_logs: bool = False
        self._ui_state: ReplUiState = ReplUiState.IDLE
        self._slash_specs = list(list_slash_specs())
        self._llm: LLMClient | None = None
        self._memory: Any | None = None
        self._console = Console(highlight=False)
        self._trace_file_reads = trace_file_reads
        self._history_path = Path(config.memory.root) / "repl_history.txt"
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        self._conversation_state_path = Path(config.memory.root_path) / "repl_conversation.json"
        self._conversation_state_path.parent.mkdir(parents=True, exist_ok=True)
        self._runtime_context_window: int | None = None
        self._runtime_context_window_profile: str | None = None
        self._last_context_source: str | None = None
        # Codex-style UX keeps slash/model interactions in-place by default.
        # Alternate-screen overlays remain available as an explicit opt-in.
        self._use_alt_screen = str(os.environ.get("THOMAS_REPL_ALT_SCREEN", "0")).strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )
        self._overlay_depth = 0
        self._alt_screen_active = False
        self._overlay_parent_command: str | None = None
        self._overlay_exit_action = _OVERLAY_EXIT_ACCEPT
        self._overlay_back_sentinel = object()
        self._interactive_flow = InteractiveFlow(self)
        self._slash_completer = SlashCommandCompleter(arg_provider=self._slash_arg_options)
        self._slash_completer.attach_context(self)
        self._session = self._build_session()

        # Project instructions (THOMAS.md)
        self._project_instructions_path = instruction_file_path(config.tools.sandbox_path)
        self._project_instructions: str | None = None
        if self._project_instructions_path:
            try:
                self._project_instructions = (
                    self._project_instructions_path.read_text(encoding="utf-8", errors="replace").strip() or None
                )
            except OSError:
                self._project_instructions = None

        # MCP tool bridge (initialized at run() startup)
        self._mcp_bridge: Any = None

        # Git worktree state
        self._worktree: Any = None  # WorktreeInfo if active
        self._original_sandbox: Path | None = None

        # Background task manager
        self._bg_manager = BackgroundTaskManager(self)

        # Plan mode handler
        self._plan_handler = PlanModeHandler(self)

        # Tool approval handler (guardrails)
        self._approval_handler: ReplApprovalHandler = create_repl_approval_handler(
            self._console,
            config,
        )

        # Claude Code-style hooks (PreToolUse / PostToolUse)
        self._hook_runner = HookRunner.from_project(
            Path(config.tools.sandbox_path) if hasattr(config.tools, "sandbox_path") else None
        )

        # Initialize memory engine
        if _HAS_MEMORY:
            try:
                self._memory = AutonomyMemoryEngine(config)
                self._memory.start()
            except Exception as e:
                self._console.print(f"[yellow]Memory engine failed to start: {e}[/yellow]")
                self._memory = None
        self._restore_conversation_state()

    def _collect_read_files(self) -> list[str]:
        files: list[str] = []
        seen: set[str] = set()

        def _add(raw: str | Path | None) -> None:
            if not raw:
                return
            try:
                path = Path(raw).expanduser().resolve()
            except OSError:
                return
            if not path.is_file():
                return
            resolved = str(path)
            if resolved in seen:
                return
            seen.add(resolved)
            files.append(resolved)

        sandbox_root = Path(self.config.tools.sandbox_path)
        hooks_dir = sandbox_root / ".thomas"

        _add(self.config.config_path)
        _add(self._conversation_state_path)
        _add(self._project_instructions_path)
        _add(hooks_dir / "hooks.json")
        _add(hooks_dir / "settings.json")
        return files

    def _print_read_file_trace(self, phase: str) -> None:
        if not self._trace_file_reads:
            return
        files = self._collect_read_files()
        if not files:
            return
        self._console.print(f"[dim]{phase} read files (order):[/dim]")
        for idx, path in enumerate(files, start=1):
            self._console.print(f"[dim]  {idx}. {path}[/dim]")

    def _restore_conversation_state(self) -> None:
        if not self._conversation_state_path.exists():
            return
        try:
            payload = json.loads(self._conversation_state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, list):
            return
        restored: list[dict[str, Any]] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            role = str(row.get("role") or "").strip()
            content = row.get("content")
            if role not in {"user", "assistant", "system"}:
                continue
            if not isinstance(content, str):
                continue
            restored.append({"role": role, "content": content})
        if restored:
            self._conversation = restored

    def _persist_conversation_state(self) -> None:
        try:
            safe_rows: list[dict[str, str]] = []
            for row in self._conversation:
                role = str(row.get("role") or "").strip()
                content = row.get("content")
                if role not in {"user", "assistant", "system"}:
                    continue
                if not isinstance(content, str):
                    continue
                safe_rows.append({"role": role, "content": content})
            self._conversation_state_path.write_text(
                json.dumps(safe_rows, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            return

    def _build_session(self) -> PromptSession:
        history = FileHistory(str(self._history_path))

        bindings = KeyBindings()

        # Apply configurable keybindings (newline, exit, clear_screen)
        kb_specs = load_keybindings(self.config)
        apply_keybindings(bindings, kb_specs, self)
        overlay_picker_states = {ReplUiState.SLASH_POPUP, ReplUiState.PICKER}
        overlay_back_state = {ReplUiState.PICKER}

        def _is_overlay_state() -> bool:
            return self._ui_state in overlay_picker_states

        @bindings.add("backspace")
        def _close_slash_popup_on_backspace(event: Any) -> None:
            if not _is_overlay_state():
                event.current_buffer.delete_before_cursor(count=1)
                return
            text = str(event.current_buffer.text or "")
            if text == "/":
                self._transition_ui_state(ReplUiState.IDLE)
            event.current_buffer.delete_before_cursor(count=1)

        @bindings.add("/")
        def _open_slash_picker(event: Any) -> None:
            buffer = event.current_buffer
            if buffer.document.cursor_position != len(buffer.text or ""):
                buffer.insert_text("/")
                return

            text = str(buffer.text or "")
            if text:
                buffer.insert_text("/")
                return

            self._transition_ui_state(ReplUiState.SLASH_POPUP)
            buffer.insert_text("/")
            buffer.start_completion(select_first=True)

        @bindings.add("c-space")
        def _open_slash_picker_alt(event: Any) -> None:
            if self._ui_state not in {ReplUiState.IDLE, ReplUiState.SLASH_POPUP}:
                return
            buffer = event.current_buffer
            if buffer.document.cursor_position != len(buffer.text or ""):
                return
            if buffer.text:
                return
            self._transition_ui_state(ReplUiState.SLASH_POPUP)
            buffer.insert_text("/")
            buffer.start_completion(select_first=True)

        @bindings.add("escape")
        def _close_overlay(event: Any) -> None:
            if not _is_overlay_state():
                return
            self._overlay_exit_action = _OVERLAY_EXIT_CLOSE
            if self._ui_state in overlay_back_state and self._overlay_parent_command:
                self._overlay_exit_action = _OVERLAY_EXIT_BACK
                self._transition_ui_state(ReplUiState.SLASH_POPUP)
            else:
                self._transition_ui_state(ReplUiState.IDLE)
            try:
                event.current_buffer.cancel_completion()
            except Exception:
                pass
            event.app.exit(result="")

        @bindings.add("tab")
        def _tab_autocomplete_slash_popup(event: Any) -> None:
            if self._ui_state not in overlay_picker_states:
                return
            buffer = event.current_buffer
            if buffer.complete_state and buffer.complete_state.current_completion:
                buffer.apply_completion(buffer.complete_state.current_completion)
                return
            buffer.start_completion(select_first=True)
            if buffer.complete_state and buffer.complete_state.current_completion:
                buffer.apply_completion(buffer.complete_state.current_completion)

        @bindings.add("down")
        def _overlay_picker_next(event: Any) -> None:
            if self._ui_state not in overlay_picker_states:
                event.current_buffer.auto_down(count=1)
                return
            buffer = event.current_buffer
            if buffer.complete_state:
                buffer.complete_next()
                return
            buffer.start_completion(select_first=True)

        @bindings.add("up")
        def _overlay_picker_previous(event: Any) -> None:
            if self._ui_state not in overlay_picker_states:
                event.current_buffer.auto_up(count=1)
                return
            buffer = event.current_buffer
            if buffer.complete_state:
                buffer.complete_previous()
                return
            buffer.start_completion(select_first=True)

        @bindings.add("enter")
        def _overlay_picker_enter(event: Any) -> None:
            if self._ui_state not in overlay_picker_states:
                event.current_buffer.validate_and_handle()
                return
            self._overlay_exit_action = _OVERLAY_EXIT_ACCEPT
            buffer = event.current_buffer
            if buffer.complete_state and buffer.complete_state.current_completion:
                buffer.apply_completion(buffer.complete_state.current_completion)
            self._transition_ui_state(ReplUiState.IDLE)
            event.app.exit(result=str(buffer.text or ""))

        style = Style.from_dict(
            {
                "prompt": "ansiblue bold",
                # Explicit overlay selection styling so active command/model is always visible.
                "completion-menu": "bg:#1f2430 #d9d9d9",
                "completion-menu.completion.current": "bg:#2e7d32 #ffffff bold",
                "completion-menu.meta.completion.current": "bg:#2e7d32 #d7ffd9",
            }
        )

        session_kwargs = {
            "history": history,
            "key_bindings": bindings,
            "completer": self._slash_completer,
            "style": style,
            "multiline": False,
            "complete_while_typing": True,
            "complete_style": CompleteStyle.COLUMN,
            "reserve_space_for_menu": 12,
        }
        if "full_screen" in inspect.signature(PromptSession).parameters:
            session_kwargs["full_screen"] = False
        return PromptSession(**session_kwargs)

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
        except Exception:
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
            except Exception:
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
            except Exception:
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
        except Exception:
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
        status = f"[dim]{self._status_badges()}[/dim]"
        base = (
            "Type / for commands · Ctrl+Space for palette · Enter send · Ctrl+J newline "
            "· Esc back · // literal slash"
        )
        if token_info:
            return f"{status}  [dim]{base}  [{token_info}][/dim]"
        return f"{status}  [dim]{base}[/dim]"

    def _status_badges(self) -> str:
        return (
            f"[model: {self._resolved_model_label()}] "
            f"[autonomy: L{self._autonomy_level}] "
            f"[tools: {self._tools_policy}] "
            f"[route: {self._last_route}]"
        )

    def _startup_header_lines(self, version: str) -> list[str]:
        model_label = self._resolved_model_label() or self._current_model
        details = [
            f"THOMAS v{version}",
            f"model: {model_label}",
            f"autonomy: L{self._autonomy_level}",
            f"tools: {self._tools_policy}",
        ]
        mascot = list(_MASCOT_LINES)
        pad = max(len(line) for line in mascot) + 2 if mascot else 2
        merged: list[str] = []
        for idx in range(max(len(mascot), len(details))):
            left = mascot[idx] if idx < len(mascot) else ""
            right = details[idx] if idx < len(details) else ""
            if right:
                merged.append(f"[bright_cyan]{left.ljust(pad)}[/bright_cyan] {right}")
            else:
                merged.append(f"[bright_cyan]{left}[/bright_cyan]")
        return merged

    def _erase_prompt_line(self) -> None:
        if not bool(getattr(sys.stdout, "isatty", lambda: False)()):
            return
        try:
            sys.stdout.write("\r\033[2K\r")
            sys.stdout.flush()
        except Exception:
            return

    def _print_turn(self, role: str, text: str) -> None:
        content = (text or "").strip()
        if not content:
            return
        role_key = (role or "").strip().lower()
        if role_key == "user":
            self._console.print(Panel(Text(content), title=USER_PANEL_TITLE, border_style="bright_magenta", expand=True))
        elif role_key == "assistant":
            self._console.print(Panel(Text(content), title=ASSISTANT_PANEL_TITLE, border_style="cyan", expand=True))
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
                except Exception:
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
        except Exception:
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
        current = str(self.config.get_model(self._current_model).reasoning_effort or "").strip().lower()
        default_value = current if current in levels else ""
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
            model_config = self.config.get_model(self._current_model)
            self._llm = LLMClient(
                model_config,
                fallback_configs=self.config.failover_chain(self._current_model),
                failover_enabled=self.config.failover.enabled,
                failover_cooldown_s=self.config.failover.cooldown_seconds,
                failover_on_auth_error=self.config.failover.fallback_on_auth_error,
            )
        return self._llm

    def _get_prompt(self) -> HTML:
        return HTML(f"<prompt>{USER_PROMPT_LABEL}</prompt> ")

    def _print_auto(self, text: str) -> None:
        label = f"[bold magenta]{AUTO_LABEL}[/bold magenta]"
        self._console.print(f"{label} [dim]{text}[/dim]")

    def _handle_nl_model(self, text: str) -> bool:
        """Handle natural-language model switches or listing. Returns True if handled."""
        t = text.strip()
        if not t:
            return False

        t_lower = t.lower()
        if "model" in t_lower and any(k in t_lower for k in ("list", "show", "what models", "available")):
            available = list(self.config.models.keys())
            self._console.print(f"Current: [cyan]{self._current_model}[/cyan]  Available: {', '.join(available)}")
            return True

        # e.g. "switch to model local", "use model local", "set model local", "switch to local"

        m = re.match(r"^(switch|use|set|change)\\s+(to\\s+)?(model\\s+)?(?P<name>[\\w\\-\\.:]+)\\s*$", t_lower)
        if not m:
            return False

        name = m.group("name")
        # Map back to exact model key if case differs
        for key in self.config.models:
            if key.lower() == name:
                name = key
                break
        if name in self.config.models:
            self._current_model = name
            self._runtime_context_window = None
            self._runtime_context_window_profile = None
            self._last_context_source = None
            if self._llm:
                # Reset client so it re-reads the new model config
                try:
                    import asyncio

                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(self._llm.close())
                    else:
                        loop.run_until_complete(self._llm.close())
                except Exception as e:
                    log.debug("Failed to close LLM while switching model: %s", e)
                self._llm = None
            self._console.print(f"[dim]Switched to [cyan]{name}[/cyan][/dim]")
            return True

        self._console.print(f"[red]Unknown model '{name}'. Available: {', '.join(self.config.models.keys())}[/red]")
        return True

    async def run(self) -> None:
        """Main REPL loop."""
        version = _get_version()
        if self._should_show_mascot():
            self._console.print("\n".join(self._startup_header_lines(version)))
            self._console.print("[dim]----------------------------------------[/dim]")
        else:
            self._console.print(f"[bold green]THOMAS[/bold green] v{version}")
            self._console.print(f"[dim]model: {self._resolved_model_label() or self._current_model}[/dim]")
            self._console.print(f"[dim]autonomy: L{self._autonomy_level}[/dim]")
            self._console.print(f"[dim]tools: {self._tools_policy}[/dim]")
            self._console.print(f"[dim]route: {self._last_route}[/dim]")
        banner_lines = [
            "Type [dim]/[/dim] or [dim]Ctrl+Space[/dim] for commands, [dim]Ctrl+J[/dim] for multiline, "
            "[dim]Ctrl+C[/dim] or [dim]/exit[/dim] to quit. "
            "Use [dim]//[/dim] to send a literal slash message.",
        ]
        if self._project_instructions_path:
            banner_lines.append(f"[dim]Project instructions: {self._project_instructions_path}[/dim]")
        if self._conversation:
            banner_lines.append(f"[dim]Recovered {len(self._conversation)} messages from last REPL session.[/dim]")
        self._console.print("\n".join(banner_lines))
        if self._trace_file_reads:
            self._print_read_file_trace("Startup")

        # Connect to MCP servers at startup (best-effort)
        try:
            from thomas.tools.mcp_bridge import register_mcp_tools

            self._mcp_bridge = await register_mcp_tools(self.tools, self.config)
            connected = self._mcp_bridge.list_servers()
            if connected:
                self._console.print(f"[dim]MCP servers: {', '.join(connected)}[/dim]")
        except Exception as e:
            log.debug("MCP startup failed: %s", e)

        while True:
            try:
                prompt_kwargs = {}
                if "erase_when_done" in inspect.signature(self._session.prompt_async).parameters:
                    prompt_kwargs["erase_when_done"] = True
                turns = len(self._conversation) // 2
                user_input = await self._session.prompt_async(
                    self._get_prompt(),
                    rprompt=HTML(f"<ansigray>{turns} turns</ansigray>") if turns > 0 else None,
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
            elif self._handle_nl_model(user_input):
                self._append_transcript_turn("user", user_input)
                continue

            # For plain text chat, render user input once in the transcript.
            self._append_transcript_turn("user", user_input)

            # Run agent
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
            except Exception as e:
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
        self._persist_conversation_state()


def _get_version() -> str:
    try:
        from thomas import __version__

        return __version__
    except (ImportError, AttributeError):
        return "?"
