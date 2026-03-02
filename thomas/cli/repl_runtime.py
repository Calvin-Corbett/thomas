"""Runtime command handlers extracted from `ThomasREPL`."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from prompt_toolkit.formatted_text import HTML
from rich.panel import Panel
from rich.text import Text

from thomas.cli.repl_project import instruction_file_path
from thomas.cli.repl_skills import expand_skill, list_all_skills
from thomas.cli.repl_slash import (
    extract_slash_token,
    is_known_slash_command,
    normalize_slash_command,
    suggest_slash_commands,
)
from thomas.cli.repl_state import ReplUiState
from thomas.core.autonomy import autonomy_level_name, clamp_autonomy_level, parse_autonomy_level

USER_PANEL_TITLE = "USER"


class ThomasREPLRuntimeMixin:
    async def _persist_repl_model_selection(self, *, profile: str, model_id: str | None) -> None:
        resolved_profile = str(profile or "").strip()
        if not resolved_profile:
            return
        try:
            from thomas.preferences.store import AdvancedModelPatch, PreferencesPatch, PreferencesStore
            from thomas.preferences.store import get_db_path

            PreferencesStore(get_db_path()).patch(
                PreferencesPatch(
                    advanced=AdvancedModelPatch(active_profile=resolved_profile, model_id=(str(model_id or "").strip() or None))
                ),
                user_id="default",
            )
        except Exception:
            return

    async def _handle_slash(self, cmd: str) -> tuple[bool, bool]:
        """Handle a slash command.

        Returns `(should_exit, handled)`.
        """
        parts = str(cmd or "").strip().split(None, 1)
        raw_command = parts[0].lower() if parts else ""
        command = normalize_slash_command(raw_command)
        arg = parts[1] if len(parts) > 1 else ""

        if command == "/":
            self._transition_ui_state(ReplUiState.SLASH_POPUP)
            try:
                selected = await self._pick_slash_command(default=f"/{arg}".strip() if arg else "/")
            except (KeyboardInterrupt, EOFError):
                self._transition_ui_state(ReplUiState.IDLE)
                return False, True
            if not selected:
                self._transition_ui_state(ReplUiState.IDLE)
                return False, True
            should_exit, handled = await self._handle_slash(selected)
            if not should_exit and self._ui_state != ReplUiState.IDLE:
                self._transition_ui_state(ReplUiState.IDLE)
            return should_exit, handled

        if not command or not is_known_slash_command(cmd):
            token = extract_slash_token(cmd)
            tips = suggest_slash_commands(token)
            tip_text = f" Did you mean: {', '.join(tips)}?" if tips else ""
            self._print_system_event(
                f"Unknown slash command: {token or cmd}.{tip_text} Use / for picker or // to send literal slash text.",
                important=True,
            )
            return False, True

        if command == "/model" and not arg:
            from thomas.models.discovery import discover_models_async

            discovered: list[Any] = []
            try:
                cfg = self.config.get_model(self._current_model)
                discovered = await discover_models_async(cfg, timeout_s=1.5)
            except (ValueError, TypeError):
                discovered = []
            ids = [d.id for d in discovered]
            seen: set[str] = set()
            ids = [x for x in ids if not (x in seen or seen.add(x))]
            self._last_model_choices = ids

        arg = await self._pick_slash_argument(command, arg)
        if arg is getattr(self, "_overlay_back_sentinel", None):
            self._transition_ui_state(ReplUiState.SLASH_POPUP)
            should_exit, handled = await self._handle_slash("/")
            if not should_exit and self._ui_state != ReplUiState.IDLE:
                self._transition_ui_state(ReplUiState.IDLE)
            return should_exit, handled
        if self._ui_state != ReplUiState.IDLE:
            self._transition_ui_state(ReplUiState.IDLE)
        if command == "/exit":
            return True, True

        elif command == "/help":
            lines = []
            for spec in self._slash_specs:
                aliases = f"  [dim]{' '.join(spec.aliases)}[/dim]" if spec.aliases else ""
                usage = spec.usage or spec.command
                lines.append(f"[bold]{usage}[/bold]  {spec.summary}{aliases}")
            lines.append("")
            lines.append("[dim]/ opens picker. Use // to send literal slash text. Ctrl+J for multiline input.[/dim]")
            self._console.print(Panel("\n".join(lines), title="Commands", border_style="dim"))

        elif command == "/clear":
            self._conversation.clear()
            if self._llm:
                await self._llm.close()
                self._llm = None
            self._persist_conversation_state()
            self._console.print("[dim]Conversation cleared.[/dim]")

        elif command == "/save":
            filename = arg or "thomas_conversation.json"
            try:
                path = Path(filename)
                path.write_text(
                    json.dumps(self._conversation, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                self._console.print(f"[dim]Saved {len(self._conversation)} messages to {path}[/dim]")
            except OSError as e:
                self._console.print(f"[red]Save failed: {e}[/red]")

        elif command == "/load":
            filename = arg or "thomas_conversation.json"
            try:
                path = Path(filename)
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    self._conversation = data
                    self._persist_conversation_state()
                    self._console.print(f"[dim]Loaded {len(data)} messages from {path}[/dim]")
                else:
                    self._console.print("[red]Invalid conversation format[/red]")
            except (OSError, json.JSONDecodeError) as e:
                self._console.print(f"[red]Load failed: {e}[/red]")

        elif command == "/model":
            if not arg:
                self._console.print("[dim]No model selected.[/dim]")
                return False, True

            # Switch profile: /model <profile>
            if arg in self.config.models:
                self._current_model = arg
                self._reset_context_window_cache()
                if self._llm:
                    await self._llm.close()
                    self._llm = None
                current_model_id = self.config.models[self._current_model].model
                self._print_system_event(f"model set to {current_model_id}", important=True)
                await self._persist_repl_model_selection(profile=arg, model_id=None)
                if await self._maybe_pick_reasoning_level(current_model_id):
                    self._transition_ui_state(ReplUiState.SLASH_POPUP)
                    should_exit, handled = await self._handle_slash("/model")
                    return should_exit, handled
                return False, True

            # Switch model id explicitly: /model id:foo
            if arg.lower().startswith("id:"):
                chosen = arg[3:].strip()
                if not chosen:
                    self._console.print("[yellow]Usage: /model id:<model_id>[/yellow]")
                    return False, True
                self.config.models[self._current_model].model = chosen
                self._reset_context_window_cache()
                if self._llm:
                    await self._llm.close()
                    self._llm = None
                self._print_system_event(f"model set to {chosen}", important=True)
                await self._persist_repl_model_selection(profile=self._current_model, model_id=chosen)
                if await self._maybe_pick_reasoning_level(chosen):
                    self._transition_ui_state(ReplUiState.SLASH_POPUP)
                    should_exit, handled = await self._handle_slash("/model")
                    return should_exit, handled
                return False, True

            # Direct model id: /model gpt-5...
            if arg:
                self.config.models[self._current_model].model = arg
                self._reset_context_window_cache()
                if self._llm:
                    await self._llm.close()
                    self._llm = None
                self._print_system_event(f"model set to {arg}", important=True)
                await self._persist_repl_model_selection(profile=self._current_model, model_id=arg)
                if await self._maybe_pick_reasoning_level(arg):
                    self._transition_ui_state(ReplUiState.SLASH_POPUP)
                    should_exit, handled = await self._handle_slash("/model")
                    return should_exit, handled
                return False, True

            self._console.print(
                f"[red]Unknown model/profile '{arg}'. " "Use /model and select from popup results.[/red]"
            )

        elif command == "/autonomy":
            if not arg:
                level = int(self._autonomy_level)
                self._print_system_event(f"Autonomy: L{level} ({autonomy_level_name(level)})", important=True)
                return False, True

            if str(arg).strip().lower() in {"auto", "default", "l0"}:
                if str(arg).strip().lower() == "l0":
                    self._console.print("[dim]L0 is mapped to L1 in this runtime.[/dim]")
                level = clamp_autonomy_level(3, default=self._autonomy_level)
                self._autonomy_level = int(level)
                self._print_system_event(
                    f"autonomy set to L{self._autonomy_level} ({autonomy_level_name(self._autonomy_level)})",
                    important=True,
                )
                return False, True

            level = parse_autonomy_level(arg, default=self._autonomy_level)
            self._autonomy_level = int(level)
            self._print_system_event(f"autonomy set to L{level} ({autonomy_level_name(level)})", important=True)

        elif command == "/status":
            route = str(self._last_route)
            user_turns = sum(1 for m in self._conversation if m.get("role") == "user")
            asst_turns = sum(1 for m in self._conversation if m.get("role") == "assistant")
            tool_count = 0
            for cat in self.tools.list_categories():
                tool_count += len(self.tools.list_tools(cat))
            self._console.print(f"[dim]Model: {self._current_model}[/dim]")
            self._console.print(
                f"[dim]Autonomy: L{self._autonomy_level} " f"({autonomy_level_name(self._autonomy_level)})[/dim]"
            )
            self._console.print(f"[dim]Tools policy: {self._tools_policy}[/dim]")
            self._console.print(f"[dim]Route: {route}[/dim]")
            self._console.print(
                f"[dim]Conversation: {user_turns} user, {asst_turns} assistant, "
                f"{len(self._conversation)} total messages[/dim]"
            )
            self._console.print(f"[dim]Tools: {tool_count} registered[/dim]")
            self._console.print(
                f"[dim]Access: server={self.config.server.access_mode}, "
                f"shell={'enabled' if self.config.tools.allow_shell else 'disabled'}[/dim]"
            )

        elif command == "/permissions":
            self._console.print(f"[dim]server.access_mode = {self.config.server.access_mode}[/dim]")
            self._console.print(
                f"[dim]server.api_token configured = " f"{bool(str(self.config.server.api_token or '').strip())}[/dim]"
            )
            self._console.print(f"[dim]tools.allow_shell = {bool(self.config.tools.allow_shell)}[/dim]")
            self._console.print(f"[dim]tools.sandbox_root = {self.config.tools.sandbox_path}[/dim]")
            self._console.print(f"[dim]tools.max_file_size = {self.config.tools.max_file_size} bytes[/dim]")

        elif command == "/cost":
            if self._llm:
                usage = self._llm.session_usage
                self._console.print(
                    f"[dim]LLM session tokens: prompt={usage.prompt_tokens}, "
                    f"completion={usage.completion_tokens}, total={usage.total_tokens}[/dim]"
                )
            else:
                self._console.print("[dim]LLM session tokens: no active model session yet[/dim]")
            try:
                from thomas.core.cost_tracker import get_cost_tracker

                tracker = get_cost_tracker()
                session_tokens = tracker.session_tokens()
                self._console.print(
                    f"[dim]Cost tracker tokens: prompt={session_tokens.get('prompt_tokens', 0)}, "
                    f"completion={session_tokens.get('completion_tokens', 0)}, "
                    f"total={session_tokens.get('total_tokens', 0)}[/dim]"
                )
                self._console.print(
                    f"[dim]Cost tracker: calls={tracker.session_call_count()}, "
                    f"usd={tracker.session_usd():.6f}[/dim]"
                )
            except Exception as e:
                self._console.print(f"[yellow]Cost tracker unavailable: {type(e).__name__}[/yellow]")

        elif command == "/review":
            if not self._conversation:
                self._console.print("[dim]No conversation to review yet.[/dim]")
                return False, True
            user_turns = sum(1 for m in self._conversation if m.get("role") == "user")
            asst_turns = sum(1 for m in self._conversation if m.get("role") == "assistant")
            self._console.print(
                f"[dim]Review: {user_turns} user turns, {asst_turns} assistant turns, "
                f"{len(self._conversation)} messages total[/dim]"
            )
            self._console.print("[dim]Recent turns:[/dim]")
            for row in self._conversation[-6:]:
                role = str(row.get("role") or "unknown")
                text = str(row.get("content") or "").replace("\n", " ").strip()
                if len(text) > 140:
                    text = text[:137] + "..."
                self._console.print(f"  [cyan]{role}[/cyan]: {text}")
            self._console.print("[dim]Tip: pin priorities with /pin todo.<key>=<task>[/dim]")

        elif command == "/reads":
            self._print_read_file_trace("Session")

        elif command == "/todo":
            todos: list[tuple[str, str]] = []
            seen: set[str] = set()
            if self._memory and self._memory.started:
                try:
                    pins = self._memory.list_pins()
                except (ValueError, TypeError):
                    pins = []
                for key, text, _score in pins:
                    key_s = str(key or "").strip()
                    text_s = str(text or "").strip()
                    if not key_s or not text_s:
                        continue
                    if not key_s.lower().startswith("todo"):
                        continue
                    marker = f"pin:{key_s.lower()}"
                    if marker in seen:
                        continue
                    seen.add(marker)
                    todos.append((f"pin:{key_s}", text_s))

            for candidate in (
                Path(self.config.memory.root_path) / "thomas_state.json",
            ):
                if not candidate.exists():
                    continue
                try:
                    payload = json.loads(candidate.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
                goals = payload.get("goals") if isinstance(payload, dict) else None
                if not isinstance(goals, list):
                    continue
                for idx, row in enumerate(goals, start=1):
                    if not isinstance(row, dict):
                        continue
                    status = str(row.get("status") or "open").strip().lower()
                    if status in {"done", "completed", "closed"}:
                        continue
                    text = str(row.get("text") or row.get("goal") or row.get("title") or "").strip()
                    if not text:
                        continue
                    marker = f"goal:{status}:{text.lower()}"
                    if marker in seen:
                        continue
                    seen.add(marker)
                    todos.append((f"goal:{idx}", text))

            if not todos:
                self._console.print("[dim]No open todos found. Add one with /pin todo.<key>=<task>[/dim]")
            else:
                self._console.print(f"[dim]Open todos: {len(todos)}[/dim]")
                for origin, text in todos[:20]:
                    self._console.print(f"  - {origin}: {text}")

        elif command == "/tools":
            if not arg:
                for cat in self.tools.list_categories():
                    self._console.print(f"\n[bold]{cat}[/bold]")
                    for tool in self.tools.list_tools(cat):
                        self._console.print(f"  [cyan]{tool.name}[/cyan] - {tool.description[:70]}")
                self._console.print(f"\n[dim]Current tools mode: {self._tools_policy}[/dim]")
                return False, True

            policy = str(arg).strip().lower()
            if policy == "on":
                self._tools_policy = "always"
            elif policy == "off":
                self._tools_policy = "never"
            elif policy == "auto":
                self._tools_policy = "auto"
            else:
                self._console.print("[yellow]Usage: /tools [auto|on|off][/yellow]")
                return False, True

            self._print_system_event(f"tools policy set to {self._tools_policy}", important=True)

        elif command == "/verbose":
            mode = str(arg or "").strip().lower()
            if not mode:
                current = "on" if self._show_system_logs else "off"
                activity = str(getattr(self, "_activity_verbosity", "normal") or "normal").strip().lower()
                self._console.print(f"[dim]Verbose system logs: {current}[/dim]")
                self._console.print(f"[dim]Activity verbosity: {activity}[/dim]")
                return False, True
            if mode in {"on", "true", "1", "yes"}:
                self._show_system_logs = True
                self._console.print("[dim]Verbose system logs: on[/dim]")
                return False, True
            if mode in {"off", "false", "0", "no"}:
                self._show_system_logs = False
                self._console.print("[dim]Verbose system logs: off[/dim]")
                return False, True
            if mode in {"minimal", "normal", "debug"}:
                self._activity_verbosity = mode
                self._console.print(f"[dim]Activity verbosity: {mode}[/dim]")
                return False, True
            self._console.print("[yellow]Usage: /verbose [on|off|minimal|normal|debug][/yellow]")

        elif command == "/memory":
            user_turns = sum(1 for m in self._conversation if m.get("role") == "user")
            asst_turns = sum(1 for m in self._conversation if m.get("role") == "assistant")
            self._console.print(
                f"[dim]Conversation: {user_turns} user, {asst_turns} assistant, "
                f"{len(self._conversation)} total messages[/dim]"
            )
            if self._llm:
                usage = self._llm.session_usage
                self._console.print(
                    f"[dim]Tokens: {usage.prompt_tokens} prompt + "
                    f"{usage.completion_tokens} completion = {usage.total_tokens} total[/dim]"
                )
            if self._memory and self._memory.started:
                stats = self._memory.stats()
                self._console.print(
                    f"[dim]Memory: {stats['event_count']} events, "
                    f"dense={'yes (dim=' + str(stats['dense_dim']) + ')' if stats['has_dense'] else 'no (hash fallback)'}[/dim]"
                )
                pins = self._memory.list_pins()
                if pins:
                    self._console.print(f"[dim]Pins: {len(pins)} active[/dim]")
                    for key, text, _ in pins:
                        self._console.print(f"  [cyan]{key}[/cyan]: {text[:60]}")
            else:
                self._console.print("[dim]Memory engine: not active[/dim]")

        elif command == "/compact":
            await self._handle_compact_command()

        elif command == "/pin":
            if not arg:
                self._console.print("[yellow]Usage: /pin key=value[/yellow]")
            elif "=" not in arg:
                self._console.print(
                    "[yellow]Usage: /pin key=value (e.g. /pin style=concise code with comments)[/yellow]"
                )
            elif self._memory and self._memory.started:
                key, _, value = arg.partition("=")
                self._memory.pin(key.strip(), value.strip())
                self._console.print(f"[dim]Pinned: [cyan]{key.strip()}[/cyan][/dim]")
            else:
                self._console.print("[yellow]Memory engine not active[/yellow]")

        elif command == "/unpin":
            if not arg:
                self._console.print("[yellow]Usage: /unpin key[/yellow]")
            elif self._memory and self._memory.started:
                self._memory.unpin(arg.strip())
                self._console.print(f"[dim]Unpinned: [cyan]{arg.strip()}[/cyan][/dim]")
            else:
                self._console.print("[yellow]Memory engine not active[/yellow]")

        elif command == "/project":
            if arg.strip().lower() == "reload":
                self._project_instructions_path = instruction_file_path(self.config.tools.sandbox_path)
                if self._project_instructions_path:
                    try:
                        self._project_instructions = (
                            self._project_instructions_path.read_text(encoding="utf-8", errors="replace").strip()
                            or None
                        )
                    except OSError:
                        self._project_instructions = None
                    self._console.print(f"[dim]Reloaded: {self._project_instructions_path}[/dim]")
                else:
                    self._project_instructions = None
                    self._console.print("[dim]No THOMAS.md found.[/dim]")
            elif self._project_instructions:
                from rich.markdown import Markdown as _Md

                self._console.print(
                    Panel(
                        _Md(self._project_instructions),
                        title=f"Project Instructions ({self._project_instructions_path})",
                        border_style="dim",
                    )
                )
            else:
                self._console.print(
                    "[dim]No THOMAS.md found. Create .thomas.md or THOMAS.md in your project root.[/dim]"
                )

        elif command == "/plugins":
            plugin_tools = [t for t in self.tools.list_tools() if t.category == "plugin"]
            if not plugin_tools:
                self._console.print("[dim]No plugin tools registered.[/dim]")
            else:
                self._console.print(f"[dim]Plugin tools: {len(plugin_tools)}[/dim]")
                for t in plugin_tools:
                    self._console.print(f"  [cyan]{t.name}[/cyan] - {t.description[:70]}")

        elif command == "/mcp":
            mcp_tools = [t for t in self.tools.list_tools() if t.category == "mcp"]
            servers = self._mcp_bridge.list_servers() if self._mcp_bridge else []
            self._console.print(f"[dim]MCP servers connected: {len(servers)}[/dim]")
            for s in servers:
                self._console.print(f"  [cyan]{s}[/cyan]")
            if mcp_tools:
                self._console.print(f"[dim]MCP tools: {len(mcp_tools)}[/dim]")
                for t in mcp_tools:
                    self._console.print(f"  [cyan]{t.name}[/cyan] - {t.description[:70]}")
            elif not servers:
                self._console.print("[dim]No MCP servers configured. Use `thomas mcp add` to register one.[/dim]")

        elif command == "/skill":
            skills = list_all_skills()
            if not arg:
                if not skills:
                    self._console.print("[dim]No skills available. Add .md files to ~/.thomas/skills/[/dim]")
                else:
                    self._console.print(f"[dim]Available skills ({len(skills)}):[/dim]")
                    for name, skill in sorted(skills.items()):
                        self._console.print(f"  [cyan]{name}[/cyan] - {skill.description}")
                    self._console.print("[dim]Usage: /skill <name> [args][/dim]")
            else:
                parts = arg.split(None, 1)
                skill_name = parts[0].strip()
                skill_args = parts[1].strip() if len(parts) > 1 else ""
                skill = skills.get(skill_name)
                if skill is None:
                    self._console.print(f"[red]Unknown skill: {skill_name}. Use /skill to list.[/red]")
                else:
                    expanded = expand_skill(skill, skill_args)
                    self._console.print(f"[dim]Running skill: {skill_name}[/dim]")
                    self._console.print(
                        Panel(Text(expanded[:500]), title=USER_PANEL_TITLE, border_style="bright_blue", expand=True)
                    )
                    await self._run_agent_turn(expanded)
                    self._persist_conversation_state()

        elif command == "/worktree":
            sub = arg.strip().lower().split(None, 1) if arg else []
            sub_cmd = sub[0] if sub else "list"
            sub_arg = sub[1].strip() if len(sub) > 1 else ""

            if sub_cmd == "create":
                try:
                    from thomas.tools.git_worktree import create_worktree, get_repo_root

                    repo = await get_repo_root(self.config.tools.sandbox_path)
                    if not repo:
                        self._console.print("[red]Not in a git repository.[/red]")
                        return False, True
                    wt_name = sub_arg or None
                    info = await create_worktree(repo, wt_name)
                    self._worktree = info
                    self._original_sandbox = self.config.tools.sandbox_path
                    self.config.tools.sandbox_root = str(info.path)
                    self._console.print(
                        f"[dim]Worktree created: {info.name} at {info.path} (branch: {info.branch})[/dim]"
                    )
                except Exception as e:
                    self._console.print(f"[red]Worktree creation failed: {e}[/red]")

            elif sub_cmd == "list":
                try:
                    from thomas.tools.git_worktree import get_repo_root, list_worktrees

                    repo = await get_repo_root(self.config.tools.sandbox_path)
                    if not repo:
                        self._console.print("[red]Not in a git repository.[/red]")
                        return False, True
                    wts = await list_worktrees(repo)
                    if not wts:
                        self._console.print("[dim]No Thomas-managed worktrees found.[/dim]")
                    else:
                        for wt in wts:
                            marker = (
                                " [bold green]â† active[/bold green]"
                                if (self._worktree and self._worktree.name == wt.name)
                                else ""
                            )
                            self._console.print(f"  [cyan]{wt.name}[/cyan] ({wt.branch}) at {wt.path}{marker}")
                except Exception as e:
                    self._console.print(f"[red]Failed to list worktrees: {e}[/red]")

            elif sub_cmd == "remove":
                if not self._worktree:
                    self._console.print("[dim]No active worktree to remove.[/dim]")
                else:
                    try:
                        from thomas.tools.git_worktree import remove_worktree

                        await remove_worktree(self._worktree)
                        self._console.print(f"[dim]Removed worktree: {self._worktree.name}[/dim]")
                        if self._original_sandbox:
                            self.config.tools.sandbox_root = str(self._original_sandbox)
                        self._worktree = None
                        self._original_sandbox = None
                    except Exception as e:
                        self._console.print(f"[red]Worktree removal failed: {e}[/red]")
            else:
                self._console.print("[yellow]Usage: /worktree [create|list|remove] [name][/yellow]")

        elif command == "/bg":
            if not arg:
                self._console.print("[yellow]Usage: /bg <prompt>[/yellow]")
            else:
                task_id = await self._bg_manager.submit(arg)
                self._console.print(f"[dim]Background task started: {task_id}[/dim]")

        elif command == "/tasks":
            if arg:
                task = self._bg_manager.get_task(arg.strip())
                if task is None:
                    self._console.print(f"[red]Task not found: {arg.strip()}[/red]")
                else:
                    self._console.print(f"[bold]{task.task_id}[/bold] [{task.status}]")
                    self._console.print(f"  Prompt: {task.prompt[:100]}")
                    if task.result_text:
                        from rich.markdown import Markdown as _Md

                        self._console.print(
                            Panel(
                                _Md(task.result_text[:2000]),
                                title=f"Result: {task.task_id}",
                                border_style="cyan",
                            )
                        )
                    if task.error:
                        self._console.print(f"  [red]Error: {task.error}[/red]")
                    # Surface the result summary into the main conversation
                    # so the agent knows what the background task produced.
                    summary = self._bg_manager.surface_result(arg.strip())
                    if summary:
                        self._conversation.append(
                            {
                                "role": "user",
                                "content": summary,
                            }
                        )
                        self._persist_conversation_state()
                        self._console.print("[dim]Background task result added to conversation context.[/dim]")
            else:
                tasks = self._bg_manager.list_tasks()
                if not tasks:
                    self._console.print("[dim]No background tasks.[/dim]")
                else:
                    for t in tasks[:20]:
                        elapsed = ""
                        if t.finished_at:
                            elapsed = f" ({t.finished_at - t.started_at:.1f}s)"
                        self._console.print(f"  [{t.status}] [cyan]{t.task_id}[/cyan]{elapsed} - {t.prompt[:60]}")

        elif command == "/plan":
            if not arg:
                # Show active plan or list saved plans
                if self._plan_handler.active_plan:
                    from rich.markdown import Markdown as _Md

                    from thomas.agent.plan_mode import plan_to_markdown as _ptm

                    self._console.print(
                        Panel(
                            _Md(_ptm(self._plan_handler.active_plan)),
                            title="Active Plan",
                            border_style="yellow",
                        )
                    )
                else:
                    plans = self._plan_handler.list_plans()
                    if not plans:
                        self._console.print("[dim]No plans. Usage: /plan <task description>[/dim]")
                    else:
                        self._console.print(f"[dim]Saved plans: {len(plans)}[/dim]")
                        for p in plans[:10]:
                            self._console.print(f"  [{p.status}] [cyan]{p.plan_id}[/cyan] - {p.task_description[:60]}")
            else:
                self._console.print("[dim]Creating plan...[/dim]")
                try:
                    plan = await self._plan_handler.create_plan(arg)
                    decision = await self._plan_handler.present_plan(plan)
                    # Edit loop: let the user modify steps, then re-decide
                    while decision == "edit":
                        decision = await self._plan_handler.edit_plan(plan)
                    if decision == "approve":
                        await self._plan_handler.execute_plan(plan)
                    else:
                        plan.status = "rejected"
                        self._plan_handler._store.update_status(plan.plan_id, "rejected")
                        self._console.print("[dim]Plan rejected.[/dim]")
                except Exception as e:
                    self._console.print(f"[red]Plan creation failed: {e}[/red]")

        else:
            self._console.print(f"[yellow]Unknown command: {command}. Type /help for help.[/yellow]")

        return False, True

    def _reset_context_window_cache(self) -> None:
        self._runtime_context_window = None
        self._last_context_source = None
        self._runtime_context_window_profile = None

    def _active_context_limit(self) -> int:
        """Return a best-effort context window size for the current model."""
        def _coerce_context_window(value: object) -> int:
            try:
                window = int(value)
            except (TypeError, ValueError):
                return 0
            return window if window > 0 else 0

        runtime_window = _coerce_context_window(getattr(self, "_runtime_context_window", 0))
        runtime_profile = str(getattr(self, "_runtime_context_window_profile", "") or "").strip().lower()
        current_profile = str(getattr(self, "_current_model", "") or "").strip().lower()
        if runtime_window > 0 and runtime_profile and runtime_profile != current_profile:
            stale_profile = runtime_profile
            stale_window = runtime_window
            self._runtime_context_window = None
            self._runtime_context_window_profile = None
            runtime_window = 0
            self._last_context_source = None
            log.debug(
                "Ignoring stale runtime context window %s for profile %s; current profile is %s",
                stale_window,
                stale_profile,
                current_profile,
            )
        if runtime_window > 0:
            return runtime_window

        profile = str(self._current_model or "").strip()
        model_cfg = None
        if profile:
            model_cfg = self.config.models.get(profile)
        if model_cfg is None and profile:
            profile_l = profile.lower()
            model_name = next(
                (name for name in self.config.models.keys() if str(name).lower() == profile_l),
                "",
            )
            model_cfg = self.config.models.get(model_name)
        if model_cfg is None and self._llm is not None:
            llm_profile = str(getattr(self._llm.config, "name", "") or "").strip()
            if llm_profile:
                if llm_profile in self.config.models:
                    model_cfg = self.config.models[llm_profile]
                else:
                    llm_profile_l = llm_profile.lower()
                    llm_profile_name = next(
                        (name for name in self.config.models.keys() if str(name).lower() == llm_profile_l),
                        "",
                    )
                    model_cfg = self.config.models.get(llm_profile_name)

        if model_cfg is None:
            return 8192

        try:
            limit = int(getattr(model_cfg, "context_window", 0) or 0)
            if limit > 0:
                return limit
        except Exception:
            pass
        try:
            if self._llm is not None:
                limit = _coerce_context_window(getattr(self._llm.config, "context_window", 0))
                if limit > 0:
                    return limit
        except Exception:
            pass
        return 8192

    def _get_token_usage_display(self) -> str:
        """Return a compact token usage string for the toolbar."""
        try:
            from thomas.agent.context_compaction import estimate_conversation_tokens

            conv_tokens = estimate_conversation_tokens(self._conversation)
            hard_cap = self._active_context_limit()
            if conv_tokens >= 1000:
                display = f"{conv_tokens / 1000:.1f}k"
            else:
                display = str(conv_tokens)
            cap_display = f"{hard_cap / 1000:.0f}k"
            pct = int((conv_tokens / hard_cap) * 100)
            if pct > 85:
                return f"ctx: {display}/{cap_display} (!)"
            return f"ctx: {display}/{cap_display}"
        except Exception:
            return ""

    async def _handle_compact_command(self) -> None:
        """Handle the /compact slash command."""
        from thomas.agent.context_compaction import (
            ContextCompactor,
            estimate_conversation_tokens,
        )

        conv_tokens = estimate_conversation_tokens(self._conversation)
        hard_cap = self._active_context_limit()
        pct = int((conv_tokens / max(1, hard_cap)) * 100)
        msg_count = len(self._conversation)

        # Show current token usage
        self._console.print("[bold]Context Budget[/bold]")
        self._console.print(
            f"  Tokens: [cyan]{conv_tokens:,}[/cyan] / {hard_cap:,} "
            f"([{'red' if pct > 85 else 'yellow' if pct > 60 else 'green'}]{pct}%[/])"
        )
        self._console.print(f"  Messages: {msg_count}")

        # Show message breakdown
        user_turns = sum(1 for m in self._conversation if m.get("role") == "user")
        asst_turns = sum(1 for m in self._conversation if m.get("role") == "assistant")
        tool_msgs = sum(1 for m in self._conversation if m.get("role") == "tool")
        system_msgs = sum(1 for m in self._conversation if m.get("role") == "system")
        self._console.print(
            f"  Breakdown: {user_turns} user, {asst_turns} assistant, " f"{tool_msgs} tool, {system_msgs} system"
        )

        if conv_tokens < int(hard_cap * 0.50):
            self._console.print("\n[dim]Context usage is low. No compaction needed yet.[/dim]")
            return

        # Ask user if they want to compact
        self._console.print("\n[dim]Compaction will summarize older turns to free token budget.[/dim]")
        try:
            confirm = await self._session.prompt_async(
                HTML("<prompt>Compact now?</prompt> <ansigray>(y/n)</ansigray> > "),
            )
        except (KeyboardInterrupt, EOFError):
            return

        if str(confirm or "").strip().lower() not in ("y", "yes"):
            self._console.print("[dim]Compaction cancelled.[/dim]")
            return

        # Perform compaction
        llm = self._get_llm()
        compactor = ContextCompactor(
            llm=llm,
            max_summary_tokens=400,
            segment_size=8,
        )

        from rich.live import Live as _Lv
        from rich.spinner import Spinner as _Sp

        spinner = _Lv(
            _Sp("dots", text=Text(" compacting context...", style="dim")),
            console=self._console,
            transient=True,
        )
        spinner.start()

        try:
            result = await compactor.compact(
                self._conversation,
                target_budget=int(hard_cap * 0.55),
                preserve_recent=6,
                use_llm=True,
            )
        except Exception as e:
            spinner.stop()
            self._console.print(f"[red]Compaction failed: {e}[/red]")
            return

        spinner.stop()

        # Show results
        self._console.print("\n[bold]Compaction Complete[/bold]")
        self._console.print(
            f"  Tokens: {result.original_tokens:,} -> "
            f"[green]{result.compacted_tokens:,}[/green] "
            f"(saved {result.tokens_saved:,})"
        )
        self._console.print(f"  Messages: {result.original_message_count} -> " f"{result.compacted_message_count}")
        if result.segments_summarized > 0:
            self._console.print(f"  Segments summarized: {result.segments_summarized}")
        self._console.print(f"  Time: {result.elapsed_ms:.0f}ms")

        if result.summary_text:
            summary_preview = result.summary_text
            if len(summary_preview) > 500:
                summary_preview = summary_preview[:500] + "..."
            self._console.print(
                Panel(
                    summary_preview,
                    title="Summary of compacted context",
                    border_style="dim",
                    expand=True,
                )
            )
