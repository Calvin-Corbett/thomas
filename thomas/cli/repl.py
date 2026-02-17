"""Interactive REPL for Thomas using prompt_toolkit and rich.

Architecture:
- prompt_toolkit handles input (history, completion, multiline via Alt+Enter)
- rich handles output rendering (panels, styled text)
- Agent loop runs as a coroutine between prompt cycles (no event loop conflict)
- Slash commands are handled directly by the REPL, bypassing the agent
"""

from __future__ import annotations

import logging
import re
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.styles import Style
    from prompt_toolkit.completion import WordCompleter
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

from thomas.core.config import AppConfig
from thomas.core.autonomy import clamp_autonomy_level, autonomy_level_name
from thomas.core.events import EventType
from thomas.core.llm import LLMClient
from thomas.tools.registry import ToolRegistry
from thomas.agent.loop import AgentLoop

log = logging.getLogger(__name__)

# Optional memory import - graceful if not available
try:
    from thomas.memory.autonomy import AutonomyMemoryEngine
    _HAS_MEMORY = True
except ImportError:
    _HAS_MEMORY = False


_SLASH_COMMANDS = [
    "/help", "/clear", "/save", "/load",
    "/model", "/tools", "/memory", "/pin", "/unpin",
    "/autonomy",
    "/exit", "/quit",
]


class ThomasREPL:
    """Interactive REPL with rich terminal UI."""

    def __init__(self, config: AppConfig, tools: ToolRegistry):
        self.config = config
        self.tools = tools
        self._conversation: List[Dict[str, Any]] = []
        self._current_model: str = config.default_model
        self._autonomy_level: int = 3
        self._last_model_choices: List[str] = []
        self._llm: Optional[LLMClient] = None
        self._memory: Optional[Any] = None
        self._console = Console(highlight=False)
        self._history_path = Path(config.memory.root) / "repl_history.txt"
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        self._session = self._build_session()

        # Initialize memory engine
        if _HAS_MEMORY:
            try:
                self._memory = AutonomyMemoryEngine(config)
                self._memory.start()
            except Exception as e:
                self._console.print(f"[yellow]Memory engine failed to start: {e}[/yellow]")
                self._memory = None

    def _build_session(self) -> PromptSession:
        history = FileHistory(str(self._history_path))

        bindings = KeyBindings()

        @bindings.add("escape", "enter")  # Alt+Enter = newline
        def _insert_newline(event: Any) -> None:
            event.current_buffer.insert_text("\n")

        # prompt_toolkit expects a compiled regex for `pattern` (not a string).
        completer = WordCompleter(_SLASH_COMMANDS, pattern=re.compile(r"^/\w*"))

        style = Style.from_dict({
            "prompt": "ansigreen bold",
        })

        return PromptSession(
            history=history,
            key_bindings=bindings,
            completer=completer,
            style=style,
            multiline=False,
            complete_while_typing=False,
        )

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
            f"<prompt>thomas</prompt> "
            f"<ansigray>[{self._current_model} | L{self._autonomy_level}]</ansigray> > "
        )

    def _handle_nl_model(self, text: str) -> bool:
        """Handle natural-language model switches or listing. Returns True if handled."""
        t = text.strip()
        if not t:
            return False

        t_lower = t.lower()
        if "model" in t_lower and any(k in t_lower for k in ("list", "show", "what models", "available")):
            available = list(self.config.models.keys())
            self._console.print(
                f"Current: [cyan]{self._current_model}[/cyan]  "
                f"Available: {', '.join(available)}"
            )
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

        self._console.print(
            f"[red]Unknown model '{name}'. "
            f"Available: {', '.join(self.config.models.keys())}[/red]"
        )
        return True

    async def run(self) -> None:
        """Main REPL loop."""
        version = _get_version()
        self._console.print(Panel(
            f"[bold green]Thomas[/bold green] v{version} - "
            f"model: [cyan]{self._current_model}[/cyan]\n"
            f"Type [dim]/help[/dim] for commands, [dim]Alt+Enter[/dim] for multiline, "
            f"[dim]Ctrl+C[/dim] or [dim]/exit[/dim] to quit.",
            border_style="dim",
        ))

        while True:
            try:
                turns = len(self._conversation) // 2
                user_input = await self._session.prompt_async(
                    self._get_prompt(),
                    rprompt=HTML(f"<ansigray>{turns} turns</ansigray>") if turns > 0 else None,
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

            # Slash commands
            if user_input.startswith("/"):
                should_exit = await self._handle_slash(user_input)
                if should_exit:
                    break
                continue

            # Run agent
            await self._run_agent(user_input)

        self._console.print("[dim]Goodbye.[/dim]")
        if self._llm:
            await self._llm.close()
        if self._memory:
            self._memory.close()

    async def _handle_slash(self, cmd: str) -> bool:
        """Handle a slash command. Returns True if REPL should exit."""
        parts = cmd.split(None, 1)
        command = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        if command in ("/exit", "/quit"):
            return True

        elif command == "/help":
            self._console.print(Panel(
                "\n".join([
                    "[bold]/clear[/bold]           Clear conversation history",
                    "[bold]/save [file][/bold]     Save conversation to JSON file",
                    "[bold]/load [file][/bold]     Load conversation from JSON file",
                    "[bold]/model [name][/bold]    Show or switch model profile",
                    "[bold]/autonomy [1-4][/bold]  Show or set autonomy level",
                    "[bold]/tools[/bold]           List available tools",
                    "[bold]/memory[/bold]          Show memory stats, pins, and token usage",
                    "[bold]/pin key=val[/bold]     Pin context (always included in memory)",
                    "[bold]/unpin key[/bold]       Remove a pinned context",
                    "[bold]/help[/bold]            Show this help",
                    "[bold]/exit[/bold]            Quit",
                    "",
                    "[dim]Alt+Enter for multiline input[/dim]",
                ]),
                title="Commands",
                border_style="dim",
            ))

        elif command == "/clear":
            self._conversation.clear()
            if self._llm:
                await self._llm.close()
                self._llm = None
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
                    self._console.print(f"[dim]Loaded {len(data)} messages from {path}[/dim]")
                else:
                    self._console.print("[red]Invalid conversation format[/red]")
            except (OSError, json.JSONDecodeError) as e:
                self._console.print(f"[red]Load failed: {e}[/red]")

        elif command == "/model":
            from thomas.models.discovery import (
                discover_models_async,
                model_family,
                parse_params_b,
            )

            # No args: show profiles + best-effort endpoint discovery for the current profile.
            if not arg:
                self._last_model_choices = []

                self._console.print("[bold]Model Profiles[/bold]")
                for name, m in self.config.models.items():
                    mark = "*" if name == self._current_model else " "
                    self._console.print(
                        f"  {mark} [cyan]{name}[/cyan]  "
                        f"[dim]{m.provider}[/dim]  {m.model}"
                    )

                # Best-effort discovery of model ids at the current endpoint.
                discovered = []
                try:
                    cfg = self.config.get_model(self._current_model)
                    discovered = await discover_models_async(cfg, timeout_s=1.5)
                except Exception:
                    cfg = None  # type: ignore[assignment]

                if not discovered or cfg is None:
                    self._console.print(
                        "\n[dim](No endpoint model list available. "
                        "If you're using Ollama, make sure it's running.)[/dim]"
                    )
                    return False

                ids = [d.id for d in discovered]
                # De-dupe while preserving order.
                seen: set[str] = set()
                ids = [x for x in ids if not (x in seen or seen.add(x))]
                self._last_model_choices = ids

                # Build above/below suggestions within each family (sorted by params_b when present).
                fam_map: Dict[str, List[tuple[str, Optional[float]]]] = {}
                for mid in ids:
                    fam_map.setdefault(model_family(mid), []).append((mid, parse_params_b(mid)))

                neighbor: Dict[str, tuple[Optional[str], Optional[str]]] = {}
                for fam, items in fam_map.items():
                    items_sorted = sorted(items, key=lambda x: (x[1] is None, x[1] or 0.0, x[0]))
                    mids = [m for m, _ in items_sorted]
                    for idx, mid in enumerate(mids):
                        above = mids[idx + 1] if idx + 1 < len(mids) else None
                        below = mids[idx - 1] if idx - 1 >= 0 else None
                        neighbor[mid] = (above, below)

                current_id = self.config.get_model(self._current_model).model
                self._console.print(f"\n[bold]Models At {cfg.base_url}[/bold]")
                for i, mid in enumerate(ids, start=1):
                    mark = "*" if mid == current_id else " "
                    above, below = neighbor.get(mid, (None, None))
                    hints: list[str] = []
                    if above:
                        hints.append(f"better: {above}")
                    if below:
                        hints.append(f"lighter: {below}")
                    hint_text = f"  [dim]{'  '.join(hints)}[/dim]" if hints else ""
                    self._console.print(f"  {mark} {i:>2}. {mid}{hint_text}")

                self._console.print("\n[dim]Switch profile: /model <profile>[/dim]")
                self._console.print(
                    "[dim]Switch model id: /model <number> (from list above) "
                    "or /model id:<model_id>[/dim]"
                )
                return False

            # Switch profile: /model <profile>
            if arg in self.config.models:
                self._current_model = arg
                if self._llm:
                    await self._llm.close()
                    self._llm = None
                self._console.print(f"[dim]Switched to [cyan]{arg}[/cyan][/dim]")
                return False

            # Switch model id by number from the last discovery list: /model 12
            if arg.isdigit():
                idx = int(arg)
                if 1 <= idx <= len(self._last_model_choices):
                    chosen = self._last_model_choices[idx - 1]
                    self.config.models[self._current_model].model = chosen
                    if self._llm:
                        await self._llm.close()
                        self._llm = None
                    self._console.print(
                        f"[dim]Set model id for [cyan]{self._current_model}[/cyan] -> {chosen}[/dim]"
                    )
                    return False

            # Switch model id explicitly: /model id:foo
            if arg.lower().startswith("id:"):
                chosen = arg[3:].strip()
                if not chosen:
                    self._console.print("[yellow]Usage: /model id:<model_id>[/yellow]")
                    return False
                self.config.models[self._current_model].model = chosen
                if self._llm:
                    await self._llm.close()
                    self._llm = None
                self._console.print(
                    f"[dim]Set model id for [cyan]{self._current_model}[/cyan] -> {chosen}[/dim]"
                )
                return False

            self._console.print(
                f"[red]Unknown model/profile '{arg}'. "
                f"Try /model (no args) to list profiles and endpoint models.[/red]"
            )

        elif command == "/autonomy":
            if not arg:
                level = int(self._autonomy_level)
                self._console.print(
                    f"[dim]Autonomy: L{level} ({autonomy_level_name(level)})[/dim]"
                )
                return False

            m = re.search(r"[1-4]", str(arg))
            if not m:
                self._console.print("[yellow]Usage: /autonomy <1|2|3|4>[/yellow]")
                return False

            level = clamp_autonomy_level(m.group(0), default=self._autonomy_level)
            self._autonomy_level = int(level)
            self._console.print(
                f"[dim]Autonomy set to L{level} ({autonomy_level_name(level)})[/dim]"
            )

        elif command == "/tools":
            for cat in self.tools.list_categories():
                self._console.print(f"\n[bold]{cat}[/bold]")
                for tool in self.tools.list_tools(cat):
                    self._console.print(f"  [cyan]{tool.name}[/cyan] - {tool.description[:70]}")

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

        elif command == "/pin":
            if not arg:
                self._console.print("[yellow]Usage: /pin key=value[/yellow]")
            elif "=" not in arg:
                self._console.print("[yellow]Usage: /pin key=value (e.g. /pin style=concise code with comments)[/yellow]")
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

        else:
            self._console.print(f"[yellow]Unknown command: {command}. Type /help for help.[/yellow]")

        return False

    async def _run_agent(self, prompt: str) -> None:
        """Run the agent loop, streaming events to the terminal.

        Uses a thinking spinner while waiting for the LLM, and renders
        the final text response as markdown for code blocks, bold, etc.
        """
        llm = self._get_llm()
        agent = AgentLoop(
            config=self.config,
            llm=llm,
            tools=self.tools,
            conversation=self._conversation,
            memory=self._memory,
            thread_id="repl",
            autonomy_level=self._autonomy_level,
        )

        # State for managing the spinner + streaming output
        thinking = True
        spinner_live: Optional[Live] = None
        text_buffer: list[str] = []
        usage_hint = ""
        token_info = ""

        try:
            async for event in agent.run(prompt):
                if event.type == EventType.AGENT_START:
                    route = event.data.get("route", {}) if isinstance(event.data.get("route"), dict) else {}
                    mode = route.get("mode") or event.data.get("mode") or "auto"
                    policy = event.data.get("tools_policy", "auto")
                    level = int(event.data.get("autonomy_level", self._autonomy_level) or self._autonomy_level)
                    name = str(event.data.get("autonomy_name") or autonomy_level_name(level))
                    self._console.print(f"[dim][route {mode}, tools={policy}, autonomy=L{level} {name}][/dim]")

                elif event.type == EventType.AGENT_ITERATION:
                    # Show thinking spinner
                    ctx_tokens = event.data.get("token_estimate", 0)
                    ctx_window = event.data.get("context_window", 0)
                    iteration = event.data.get("iteration", 0)
                    if iteration == 0:
                        usage_hint = f"~{ctx_tokens:,}/{ctx_window:,} tokens"
                    if thinking and spinner_live is None:
                        spinner_live = Live(
                            Spinner("dots", text=Text(f" thinking... ({usage_hint})", style="dim")),
                            console=self._console,
                            transient=True,
                        )
                        spinner_live.start()

                elif event.type == EventType.TEXT_DELTA:
                    # Stop spinner on first token
                    if spinner_live is not None:
                        spinner_live.stop()
                        spinner_live = None
                        thinking = False
                    text_buffer.append(event.data["text"])
                    # Stream raw text for responsiveness
                    sys.stdout.write(event.data["text"])
                    sys.stdout.flush()

                elif event.type == EventType.TOOL_CALL_START:
                    # Stop spinner, show tool info
                    if spinner_live is not None:
                        spinner_live.stop()
                        spinner_live = None
                        thinking = False
                    # Flush any text before tool call
                    if text_buffer:
                        sys.stdout.write("\n")
                        text_buffer.clear()
                    name = event.data["tool_name"]
                    self._console.print(f"  [dim][tool] {name}...[/dim]", end="")
                    # Show a spinner for tool execution too
                    thinking = True
                    spinner_live = Live(
                        Spinner("dots", text=Text(f" running...", style="dim")),
                        console=self._console,
                        transient=True,
                    )
                    spinner_live.start()

                elif event.type == EventType.TOOL_RESULT:
                    if spinner_live is not None:
                        spinner_live.stop()
                        spinner_live = None
                        thinking = False
                    ok = event.data["ok"]
                    name = event.data["tool_name"]
                    ms = event.data["duration_ms"]
                    if ok:
                        self._console.print(f" [green]ok[/green] [dim]{name} ({ms:.0f}ms)[/dim]")
                    else:
                        err = event.data.get("result", "failed")[:100]
                        self._console.print(f" [red]fail[/red] [dim]{name}:[/dim] [red]{err}[/red]")
                    # Restart thinking for next LLM iteration
                    thinking = True
                    spinner_live = Live(
                        Spinner("dots", text=Text(" thinking...", style="dim")),
                        console=self._console,
                        transient=True,
                    )
                    spinner_live.start()

                elif event.type == EventType.AGENT_ERROR:
                    if spinner_live is not None:
                        spinner_live.stop()
                        spinner_live = None
                    sys.stdout.write("\n")
                    self._console.print(f"[bold red]Error:[/bold red] {event.data['error']}")

                elif event.type == EventType.AGENT_DONE:
                    if spinner_live is not None:
                        spinner_live.stop()
                        spinner_live = None
                    sys.stdout.write("\n")
                    token_report = event.data.get("token_report")
                    if isinstance(token_report, dict):
                        try:
                            prompt_tokens = int(token_report.get("prompt_tokens", 0) or 0)
                            completion_tokens = int(token_report.get("completion_tokens", 0) or 0)
                            total_tokens = int(token_report.get("total_tokens", 0) or 0)
                            if total_tokens > 0:
                                token_info = f"{prompt_tokens}+{completion_tokens}={total_tokens} tokens"
                        except Exception:
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
            if spinner_live is not None:
                spinner_live.stop()
            sys.stdout.write("\n")
            self._console.print("[yellow](interrupted)[/yellow]")


def _get_version() -> str:
    try:
        from thomas import __version__
        return __version__
    except (ImportError, AttributeError):
        return "?"
