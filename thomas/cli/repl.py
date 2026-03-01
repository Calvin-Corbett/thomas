"""Interactive REPL for Thomas using prompt_toolkit and rich."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import inspect
import re
import sys
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
    raise ImportError("prompt_toolkit is required for the REPL. Install with: pip install prompt_toolkit>=3.0")

try:
    from rich.console import Console
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.spinner import Spinner
    from rich.text import Text
except ImportError:
    raise ImportError("rich is required for the REPL. Install with: pip install rich>=13.0")

from thomas.agent.loop import AgentLoop
from thomas.core.autonomy import autonomy_level_name, clamp_autonomy_level
from thomas.core.config import AppConfig
from thomas.core.events import EventType
from thomas.core.llm import LLMClient
from thomas.core.token_economy import normalize_token_economy_level
from thomas.cli.repl_picker import PickerCompleter, PickerOption, picker_toolbar_hint, resolve_picker_selection
from thomas.cli.repl_slash import (
    SlashCommandCompleter,
    extract_slash_token,
    is_known_slash_command,
    list_slash_specs,
    normalize_slash_command,
    resolve_slash_selection,
    suggest_slash_commands,
)
from thomas.cli.repl_background import BackgroundTaskManager
from thomas.cli.repl_keybindings import apply_keybindings, load_keybindings
from thomas.cli.repl_plan import PlanModeHandler
from thomas.cli.repl_project import discover_project_instructions, instruction_file_path
from thomas.cli.repl_skills import expand_skill, list_all_skills
from thomas.cli.repl_state import ReplUiState, is_valid_ui_transition
from thomas.cli.repl_approval import ReplApprovalHandler, create_repl_approval_handler
from thomas.cli.repl_hooks import HookRunner
from thomas.cli.repl_runtime import ThomasREPLRuntimeMixin
from thomas.cli.repl_agent_runtime import ThomasREPLAgentMixin
from thomas.tools.registry import ToolRegistry

log = logging.getLogger(__name__)
try:
    from thomas.memory.autonomy import AutonomyMemoryEngine

    _HAS_MEMORY = True
except ImportError:
    _HAS_MEMORY = False


# Backward-compat exports used by tests and older imports.
_SlashCommandCompleter = SlashCommandCompleter

USER_PROMPT_LABEL = "you"
USER_PANEL_TITLE = "USER"
ASSISTANT_PANEL_TITLE = "THOMAS"
AUTO_LABEL = "THOMAS"


def _is_known_slash_command(text: str) -> bool:
    return is_known_slash_command(text)


class ThomasREPL(ThomasREPLRuntimeMixin, ThomasREPLAgentMixin):
    """Interactive REPL with rich terminal UI."""

    def __init__(self, config: AppConfig, tools: ToolRegistry):
        self.config = config
        self.tools = tools
        self._conversation: list[dict[str, Any]] = []
        self._current_model: str = config.default_model
        self._autonomy_level: int = 3
        self._last_model_choices: list[str] = []
        self._ui_state: ReplUiState = ReplUiState.IDLE
        self._slash_specs = list(list_slash_specs())
        self._llm: LLMClient | None = None
        self._memory: Any | None = None
        self._console = Console(highlight=False)
        self._history_path = Path(config.memory.root) / "repl_history.txt"
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        self._conversation_state_path = Path(config.memory.root_path) / "repl_conversation.json"
        self._conversation_state_path.parent.mkdir(parents=True, exist_ok=True)
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
        self._slash_completer = SlashCommandCompleter(arg_provider=self._slash_arg_values)
        self._session = self._build_session()

        # Project instructions (THOMAS.md)
        self._project_instructions_path = instruction_file_path(config.tools.sandbox_path)
        self._project_instructions: str | None = None
        if self._project_instructions_path:
            try:
                self._project_instructions = self._project_instructions_path.read_text(
                    encoding="utf-8", errors="replace"
                ).strip() or None
            except OSError:
                self._project_instructions = None

        # MCP tool bridge (initialized at run() startup)
        self._mcp_bridge: Any = None

        # Git worktree state
        self._worktree: Any = None         # WorktreeInfo if active
        self._original_sandbox: Path | None = None

        # Background task manager
        self._bg_manager = BackgroundTaskManager(self)

        # Plan mode handler
        self._plan_handler = PlanModeHandler(self)

        # Tool approval handler (guardrails)
        self._approval_handler: ReplApprovalHandler = create_repl_approval_handler(
            self._console, config,
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

        @bindings.add("backspace")
        def _close_slash_popup_on_backspace(event: Any) -> None:
            if self._ui_state != ReplUiState.SLASH_POPUP:
                event.current_buffer.delete_before_cursor(count=1)
                return
            text = str(event.current_buffer.text or "")
            if text == "/":
                event.app.exit(result="")
                return
            event.current_buffer.delete_before_cursor(count=1)

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
            buffer = event.current_buffer
            if buffer.complete_state and buffer.complete_state.current_completion:
                buffer.apply_completion(buffer.complete_state.current_completion)
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
        if command == "/model":
            values = [*self._known_model_profile_names()]
            values.extend([f"id:{model_id}" for model_id in self._last_model_choices[:50]])
            return values
        if command == "/autonomy":
            return ["1", "2", "3", "4", "L1", "L2", "L3", "L4"]
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

    def _composer_toolbar_hint(self) -> str:
        token_info = self._get_token_usage_display()
        base = "Enter send  Ctrl+J newline  / commands  // literal slash"
        if token_info:
            return f"{base}  [{token_info}]"
        return base

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
    ) -> str:
        """Render a non-destructive overlay prompt and return user selection."""
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
        try:
            if "prompt" in prompt_async_params:
                typed = await self._session.prompt_async(prompt=prompt_html, **overlay_kwargs)
            elif "message" in prompt_async_params:
                typed = await self._session.prompt_async(message=prompt_html, **overlay_kwargs)
            else:
                typed = await self._session.prompt_async(prompt_html, **overlay_kwargs)
            return str(typed or "").strip()
        finally:
            self._exit_overlay_screen()

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
        self._transition_ui_state(ReplUiState.PICKER)
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
            self._transition_ui_state(ReplUiState.IDLE)
            return ""
        default_value = self._current_model if self._current_model in profiles else ""
        menu_rows = 10
        try:
            selected = await self._prompt_overlay(
                HTML("<prompt>model</prompt> > "),
                default=default_value,
                completer=PickerCompleter(options, match_middle=True),
                menu_rows=menu_rows,
                toolbar_text=picker_toolbar_hint(len(options), menu_rows),
            )
        except (KeyboardInterrupt, EOFError):
            self._transition_ui_state(ReplUiState.IDLE)
            return ""
        self._transition_ui_state(ReplUiState.IDLE)
        picked = resolve_picker_selection(selected, options)
        lowered = picked.lower()
        if lowered in profile_set:
            return profile_set[lowered]
        if lowered in model_id_set:
            return model_id_set[lowered]
        return ""

    async def _maybe_pick_reasoning_level(self, selected_model_id: str) -> None:
        model_id = str(selected_model_id or "").strip().lower()
        if not model_id.startswith("gpt-5"):
            return
        levels = ["minimal", "low", "medium", "high"]
        current = str(self.config.get_model(self._current_model).reasoning_effort or "").strip().lower()
        default_value = current if current in levels else "medium"
        options = [
            PickerOption(value=level, label=level, is_current=(level == default_value))
            for level in levels
        ]
        try:
            picked = await self._prompt_overlay(
                HTML("<prompt>reasoning</prompt> > "),
                default=default_value,
                completer=PickerCompleter(options, match_middle=False),
                menu_rows=6,
                toolbar_text=picker_toolbar_hint(len(options), 6),
            )
        except (KeyboardInterrupt, EOFError):
            return
        picked = resolve_picker_selection(str(picked or "").strip(), options)
        if picked not in levels:
            return
        self.config.models[self._current_model].reasoning_effort = picked
        self._console.print(f"[dim]Reasoning level set to {picked}[/dim]")

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
            try:
                live.stop()
            except OSError:
                pass

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
        return HTML(
            f"<prompt>{USER_PROMPT_LABEL}</prompt> "
            f"<ansigray>[{self._current_model} | L{self._autonomy_level}]</ansigray> > "
        )

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
            self._console.print(f"Current: [cyan]{self._current_model}[/cyan]  " f"Available: {', '.join(available)}")
            return True

        # e.g. "switch to model local", "use model local", "set model local", "switch to local"
        import re

        m = re.match(r"^(switch|use|set|change)\\s+(to\\s+)?(model\\s+)?(?P<name>[\\w\\-\\.:]+)\\s*$", t_lower)
        if not m:
            return False

        name = m.group("name")
        # Map back to exact model key if case differs
        for key in self.config.models.keys():
            if key.lower() == name:
                name = key
                break

        if name in self.config.models:
            self._current_model = name
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

        self._console.print(f"[red]Unknown model '{name}'. " f"Available: {', '.join(self.config.models.keys())}[/red]")
        return True

    async def run(self) -> None:
        """Main REPL loop."""
        version = _get_version()
        banner_lines = [
            f"[bold green]Thomas[/bold green] v{version} - "
            f"model: [cyan]{self._current_model}[/cyan]",
            f"Type [dim]/help[/dim] for commands, [dim]Ctrl+J[/dim] for multiline, "
            f"[dim]Ctrl+C[/dim] or [dim]/exit[/dim] to quit. "
            f"Use [dim]//[/dim] to send a literal slash message.",
        ]
        if self._project_instructions_path:
            banner_lines.append(
                f"[dim]Project instructions: {self._project_instructions_path}[/dim]"
            )
        if self._conversation:
            banner_lines.append(
                f"[dim]Recovered {len(self._conversation)} messages from last REPL session.[/dim]"
            )
        self._console.print(Panel("\n".join(banner_lines), border_style="dim"))

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
                turns = len(self._conversation) // 2
                user_input = await self._session.prompt_async(
                    self._get_prompt(),
                    rprompt=HTML(f"<ansigray>{turns} turns</ansigray>") if turns > 0 else None,
                    bottom_toolbar=(lambda: self._composer_toolbar_hint()),
                )
            except KeyboardInterrupt:
                self._console.print("\n[dim](interrupted - type /exit to quit)[/dim]")
                continue
            except EOFError:
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            # Natural-language model switching / listing
            if self._handle_nl_model(user_input):
                continue

            # Escape hatch for literal slash-prefixed chat text.
            if user_input.startswith("//"):
                user_input = user_input[1:]

            # Slash commands
            if user_input.startswith("/"):
                should_exit, handled = await self._handle_slash(user_input)
                if should_exit:
                    break
                if handled:
                    continue

            # Run agent
            self._console.print(
                Panel(Text(user_input), title=USER_PANEL_TITLE, border_style="bright_blue", expand=True)
            )
            await self._run_agent(user_input)
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
            self._console.print(
                f"[yellow]Active worktree: {self._worktree.name} at {self._worktree.path}[/yellow]"
            )
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

