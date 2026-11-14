"""Interactive REPL for Thomas using prompt_toolkit and rich."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
import logging
import os
import random
import sys
import threading
import time
import uuid
from collections import deque
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

from thomas.cli.repl_activity import ThomasREPLActivityMixin
from thomas.cli.repl_agent_runtime import ThomasREPLAgentMixin
from thomas.cli.repl_approval import ReplApprovalHandler, create_repl_approval_handler
from thomas.cli.repl_background import BackgroundTaskManager
from thomas.cli.repl_hooks import HookRunner
from thomas.cli.repl_keybindings import apply_keybindings, load_keybindings
from thomas.cli.repl_panels import ThomasREPLPanelsMixin
from thomas.cli.repl_picker import PickerCompleter, PickerOption, picker_toolbar_hint, resolve_picker_selection
from thomas.cli.repl_plan import PlanModeHandler
from thomas.cli.repl_project import instruction_file_path
from thomas.cli.repl_runtime import ThomasREPLRuntimeMixin
from thomas.cli.repl_settings import (
    ReplRuntimeSettings,
    load_repl_runtime_settings,
    save_repl_runtime_settings,
)
from thomas.cli.repl_skills import list_all_skills
from thomas.cli.repl_slash import (
    SlashArgOption,
    SlashCommandCompleter,
    is_known_slash_command,
    list_slash_specs,
    slash_arg_options,
)
from thomas.cli.repl_state import ReplUiState, is_valid_ui_transition
from thomas.cli.repl_turns import (  # noqa: F401 - labels and the version helper stay reachable here
    _ACCENT_PALETTE,
    _MASCOT_LINES,
    _OVERLAY_EXIT_ACCEPT,
    _OVERLAY_EXIT_BACK,
    _OVERLAY_EXIT_CLOSE,
    _USER_PANEL_STYLE,
    ASSISTANT_PANEL_TITLE,
    AUTO_LABEL,
    USER_PANEL_TITLE,
    USER_PROMPT_LABEL,
    ThomasREPLTurnsMixin,
    _get_version,
)
from thomas.core.config import AppConfig
from thomas.core.llm import LLMClient
from thomas.core.model_resolution import build_model_label
from thomas.tools.registry import ToolRegistry

log = logging.getLogger(__name__)
try:
    from thomas.memory.autonomy import AutonomyMemoryEngine

    _HAS_MEMORY = True
except ImportError:
    _HAS_MEMORY = False


# Backward-compat exports used by tests and older imports.
_SlashCommandCompleter = SlashCommandCompleter

# Fixed color for user panels — must NOT appear in _ACCENT_PALETTE.



def _is_known_slash_command(text: str) -> bool:
    return is_known_slash_command(text)


def _should_open_slash_popup(text: str, cursor_position: int) -> bool:
    """Return True when `/` should open the slash popup instead of inserting text."""
    current = str(text or "")
    if int(cursor_position) != len(current):
        return False

    stripped = current.strip()
    if not stripped:
        return True

    # If the buffer is already a slash token/filter, treat repeated `/` as
    # "reopen suggestions" instead of appending literal `//`.
    if stripped.startswith("/") and " " not in stripped and "\n" not in stripped and stripped != "//":
        return True
    return False


class InteractiveFlow:
    """Reusable overlay picker workflow used for slash and follow-up menus."""

    def __init__(self, repl: ThomasREPL) -> None:
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


class ThomasREPL(ThomasREPLTurnsMixin, ThomasREPLActivityMixin, ThomasREPLPanelsMixin, ThomasREPLRuntimeMixin, ThomasREPLAgentMixin):
    """Interactive REPL with rich terminal UI."""

    def __init__(self, config: AppConfig, tools: ToolRegistry, *, trace_file_reads: bool = False):
        self.config = config
        self.tools = tools
        self._conversation: list[dict[str, Any]] = []
        self._restored_conversation_count: int = 0
        self._session_turns: int = 0
        self._repl_session_id: str = self._new_repl_session_id()
        self._chat_thread_id: str = self._new_chat_thread_id(self._repl_session_id)
        self._chat_run_counter: int = 0
        resolved_profile = str(config.default_model)
        resolved_model_id = ""
        try:
            from thomas.preferences.model_resolution import resolve_effective_model

            resolved_profile, resolved_model_id = resolve_effective_model(
                config,
                env_profile=str(os.environ.get("THOMAS_DEFAULT_MODEL", "")).strip(),
                user_id="default",
            )
            if resolved_profile in config.models:
                config.default_model = resolved_profile
                if resolved_model_id:
                    config.models[resolved_profile].model = resolved_model_id
        except (KeyError, RuntimeError, TypeError, ValueError):
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
        self._runtime_state_path = Path(config.memory.root_path) / ".thomas" / "cli" / "repl_runtime_state.json"
        self._runtime_state_path.parent.mkdir(parents=True, exist_ok=True)
        self._runtime_context_window: int | None = None
        self._runtime_context_window_profile: str | None = None
        self._last_context_source: str | None = None
        self._mascot_style, self._accent_hex = self._new_session_theme()
        self._activity_verbosity = (
            str(os.environ.get("THOMAS_ACTIVITY_VERBOSITY", "normal") or "normal").strip().lower()
        )
        if self._activity_verbosity not in {"minimal", "normal", "debug"}:
            self._activity_verbosity = "normal"
        self._restore_runtime_settings()
        self._activity_feed: deque[dict[str, Any]] = deque(maxlen=220)
        self._activity_tool_index: dict[str, int] = {}
        self._activity_tool_selected_id: str | None = None
        self._expanded_tool_events: set[str] = set()
        self._phase_starts: dict[str, float] = {}
        self._logs: deque[str] = deque(maxlen=600)
        self._activity_panel_open = False
        self._logs_panel_open = False
        self._help_panel_open = False
        self._panel_focus = "input"
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
            except (OSError, RuntimeError, TypeError, ValueError) as e:
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
        self._restored_conversation_count = 0
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
            self._restored_conversation_count = len(restored)

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

    def _restore_runtime_settings(self) -> None:
        state = load_repl_runtime_settings(self._runtime_state_path)
        self._autonomy_level = int(state.autonomy_level)
        self._tools_policy = str(state.tools_policy)
        self._show_system_logs = bool(state.show_system_logs)
        if not str(os.environ.get("THOMAS_ACTIVITY_VERBOSITY", "")).strip():
            self._activity_verbosity = str(state.activity_verbosity)

    def _persist_runtime_settings(self) -> None:
        try:
            save_repl_runtime_settings(
                self._runtime_state_path,
                ReplRuntimeSettings(
                    autonomy_level=int(self._autonomy_level),
                    tools_policy=str(self._tools_policy),
                    show_system_logs=bool(self._show_system_logs),
                    activity_verbosity=str(self._activity_verbosity),
                ),
            )
        except OSError as exc:
            log.warning("Failed to persist REPL runtime settings: %s", exc)
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
            text = str(buffer.text or "")
            if not _should_open_slash_popup(text, int(buffer.document.cursor_position)):
                buffer.insert_text("/")
                return

            normalized = text.strip()
            if not normalized:
                buffer.text = ""
                buffer.insert_text("/")
            elif normalized != text:
                buffer.text = normalized
                buffer.cursor_position = len(normalized)

            self._transition_ui_state(ReplUiState.SLASH_POPUP)
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
            except (AttributeError, RuntimeError):
                pass
            event.app.exit(result="")

        @bindings.add("tab")
        def _tab_autocomplete_slash_popup(event: Any) -> None:
            if self._ui_state not in overlay_picker_states and (
                self._help_panel_open or self._activity_panel_open or self._logs_panel_open
            ):
                self._cycle_panel_focus()
                return
            if self._ui_state not in overlay_picker_states:
                return
            buffer = event.current_buffer
            if buffer.complete_state and buffer.complete_state.current_completion:
                buffer.apply_completion(buffer.complete_state.current_completion)
                return
            buffer.start_completion(select_first=True)
            if buffer.complete_state and buffer.complete_state.current_completion:
                buffer.apply_completion(buffer.complete_state.current_completion)

        @bindings.add("f1")
        def _toggle_help_panel(event: Any) -> None:
            self._help_panel_open = not self._help_panel_open
            if self._help_panel_open:
                self._panel_focus = "help"
            elif self._panel_focus == "help":
                self._panel_focus = "input"
            self._render_panels()
            event.app.invalidate()

        @bindings.add("f2")
        def _toggle_activity_panel(event: Any) -> None:
            self._activity_panel_open = not self._activity_panel_open
            if self._activity_panel_open:
                self._panel_focus = "activity"
            elif self._panel_focus == "activity":
                self._panel_focus = "input"
            self._render_panels()
            event.app.invalidate()

        @bindings.add("f3")
        def _toggle_logs_panel(event: Any) -> None:
            self._logs_panel_open = not self._logs_panel_open
            if self._logs_panel_open:
                self._panel_focus = "logs"
            elif self._panel_focus == "logs":
                self._panel_focus = "input"
            self._render_panels()
            event.app.invalidate()

        @bindings.add("down")
        def _overlay_picker_next(event: Any) -> None:
            if self._ui_state not in overlay_picker_states:
                if self._panel_focus == "activity" and self._activity_panel_open:
                    self._cycle_activity_tool_selection(1)
                    self._render_panels()
                    event.app.invalidate()
                    return
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
                if self._panel_focus == "activity" and self._activity_panel_open:
                    self._cycle_activity_tool_selection(-1)
                    self._render_panels()
                    event.app.invalidate()
                    return
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
                if self._panel_focus == "activity" and self._activity_panel_open:
                    self._toggle_activity_tool_expansion()
                    self._render_panels()
                    return
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
                "completion-menu.completion.current": f"bg:{self._accent_hex} #ffffff bold",
                "completion-menu.meta.completion.current": f"bg:{self._accent_hex} #f5f5f5",
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


