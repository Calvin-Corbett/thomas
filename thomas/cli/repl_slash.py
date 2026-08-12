"""Slash-command parsing, normalization, and completion for the Thomas REPL."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

from thomas.cli.repo_commands import RepoCommand, discover_repo_commands, find_repo_command


def _score_match(query: str, candidate: str) -> float:
    """Return a fuzzy score for matching / ranking candidates."""
    if not query:
        return 0.0
    if candidate == query:
        return 1.0
    if candidate.startswith(query):
        return 0.95
    if candidate.startswith(query.lstrip("/")):
        return 0.90
    if query in candidate:
        return 0.78
    return SequenceMatcher(None, query, candidate).ratio()


@dataclass(frozen=True)
class SlashArgOption:
    """A selectable slash-command argument value."""

    value: str
    label: str
    description: str = ""
    is_current: bool = False


@dataclass(frozen=True)
class SlashSpec:
    """Metadata for a single slash command."""

    command: str
    summary: str
    usage: str = ""
    aliases: list[str] = field(default_factory=list)
    has_args: bool = False
    arg_options: list[SlashArgOption] = field(default_factory=list)
    arg_values_provider: Callable[[Any], list[SlashArgOption]] | None = None


def _unique_by_key(values: Iterable[SlashArgOption], *, key: str = "value") -> list[SlashArgOption]:
    out: list[SlashArgOption] = []
    seen: set[str] = set()
    for value in values:
        raw = str(getattr(value, key, "")).strip()
        if not raw:
            continue
        lowered = raw.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(value)
    return out


def _build_model_options(context: Any) -> list[SlashArgOption]:
    options: list[SlashArgOption] = []
    profile_provider = getattr(context, "_known_model_profile_names", None)
    current_profile = str(getattr(context, "_current_model", "")).strip()
    current_model_id = ""
    if callable(profile_provider):
        current_profile_cfg = getattr(context, "config", None)
        if current_profile_cfg is not None:
            current_cfg = getattr(current_profile_cfg, "models", {}).get(current_profile)
            if current_cfg is not None:
                current_model_id = str(getattr(current_cfg, "model", "")).strip()
        for profile in profile_provider():
            profile_name = str(profile).strip()
            if profile_name:
                options.append(
                    SlashArgOption(
                        value=profile_name,
                        label=profile_name,
                        description="model profile",
                        is_current=profile_name == current_profile,
                    )
                )

    recent_models: list[str] = []
    raw_recent = getattr(context, "_last_model_choices", [])
    if isinstance(raw_recent, list):
        recent_models = [str(m).strip() for m in raw_recent if str(m).strip()]

    explicit_models = []
    config = getattr(context, "config", None)
    if config is not None:
        model_registry = getattr(config, "models", None)
        if isinstance(model_registry, dict):
            for model_cfg in model_registry.values():
                model_id = str(getattr(model_cfg, "model", "")).strip()
                if model_id:
                    explicit_models.append(model_id)

    for model_id in explicit_models:
        options.append(
            SlashArgOption(
                value=model_id,
                label=model_id,
                description="model id",
                is_current=model_id == current_model_id,
            )
        )

    seen: set[str] = set()
    deduped: list[str] = []
    for model_id in recent_models:
        normalized_model_id = model_id[3:].strip() if model_id.lower().startswith("id:") else model_id
        if not normalized_model_id:
            continue
        key = normalized_model_id.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized_model_id)
    for model_id in deduped:
        options.append(
            SlashArgOption(
                value=f"id:{model_id}",
                label=model_id,
                description="recent model id",
                is_current=model_id == current_model_id,
            )
        )
    return _unique_by_key(options, key="value")


def _build_autonomy_options(context: Any) -> list[SlashArgOption]:
    current_level = 3
    try:
        current_level = int(getattr(context, "_autonomy_level", 3))
    except (TypeError, ValueError):
        current_level = 3
    current = f"L{current_level}".upper()
    return [
        SlashArgOption("Auto", "Auto", "use default policy", is_current=current == "Auto"),
        SlashArgOption("L0", "L0", "lowest autonomy", is_current=current == "L0"),
        SlashArgOption("L1", "L1", "chat", is_current=current == "L1"),
        SlashArgOption("L2", "L2", "assist", is_current=current == "L2"),
        SlashArgOption("L3", "L3", "agent", is_current=current == "L3"),
        SlashArgOption("L4", "L4", "full autonomy", is_current=current == "L4"),
    ]


def _build_tools_options(context: Any) -> list[SlashArgOption]:
    policy = str(getattr(context, "_tools_policy", "auto") or "auto").strip().lower()
    selected = {"always": "on", "never": "off"}.get(policy, "auto")
    return [
        SlashArgOption("auto", "auto", "route-aware", is_current=selected == "auto"),
        SlashArgOption("on", "on", "always allow tools", is_current=selected == "on"),
        SlashArgOption("off", "off", "disable tools", is_current=selected == "off"),
    ]


def _build_verbose_options(context: Any) -> list[SlashArgOption]:
    show = bool(getattr(context, "_show_system_logs", False))
    activity_mode = str(getattr(context, "_activity_verbosity", "normal") or "normal").strip().lower()
    return [
        SlashArgOption("on", "on", "show system logs", is_current=show),
        SlashArgOption("off", "off", "hide system logs", is_current=not show),
        SlashArgOption("minimal", "minimal", "major activity phases", is_current=activity_mode == "minimal"),
        SlashArgOption("normal", "normal", "major phases + tool calls", is_current=activity_mode == "normal"),
        SlashArgOption("debug", "debug", "include timings and diagnostics", is_current=activity_mode == "debug"),
    ]


def _build_memory_options(context: Any) -> list[SlashArgOption]:
    _ = context
    return [
        SlashArgOption("stats", "stats", "show memory stats"),
        SlashArgOption("thread", "thread", "show active session + thread scope"),
        SlashArgOption("new", "new", "rotate to a fresh memory thread"),
        SlashArgOption("query ", "query", "preview memory retrieval for a query"),
    ]


def _build_session_options(context: Any) -> list[SlashArgOption]:
    _ = context
    return [
        SlashArgOption("info", "info", "show active session details"),
        SlashArgOption("new", "new", "start fresh session + memory scope"),
        SlashArgOption("list", "list", "list saved named sessions"),
        SlashArgOption("save ", "save", "save current session snapshot"),
        SlashArgOption("load ", "load", "load a saved session snapshot"),
    ]


def _build_evolve_options(context: Any) -> list[SlashArgOption]:
    _ = context
    return [
        SlashArgOption("status", "status", "show latest evolve session"),
        SlashArgOption("run ", "run", "start a green-side evolve session"),
        SlashArgOption("promote", "promote", "promote the latest ready evolve session"),
    ]


def slash_arg_options(command: str, context: Any | None = None) -> list[SlashArgOption]:
    """Return all argument options for a command."""
    target = str(command or "").strip().lower()
    spec = get_slash_spec(target)
    if spec is None:
        return []
    if spec.arg_values_provider is not None:
        try:
            return _unique_by_key(spec.arg_values_provider(context), key="value")
        except TypeError:
            return _unique_by_key(spec.arg_values_provider(), key="value")
    return [
        SlashArgOption(
            option.value,
            option.label,
            option.description,
            is_current=getattr(option, "is_current", False),
        )
        for option in spec.arg_options
    ]


def _match_option(query: str, option: SlashArgOption) -> bool:
    if not query:
        return True
    lowered = query.lower()
    value = option.value.lower()
    label = option.label.lower()
    if value.startswith(lowered) or label.startswith(lowered):
        return True
    if lowered in value or lowered in label:
        return True
    return _score_match(lowered, value) > 0.52 or _score_match(lowered, label) > 0.52


_SLASH_SPECS: list[SlashSpec] = [
    SlashSpec("/help", "Show available commands", usage="/help"),
    SlashSpec("/exit", "Exit the REPL", usage="/exit", aliases=["/quit", "/q"]),
    SlashSpec("/clear", "Clear conversation history", usage="/clear"),
    SlashSpec("/save", "Save conversation to file", usage="/save [file]", has_args=True),
    SlashSpec("/load", "Load conversation from file", usage="/load [file]", has_args=True),
    SlashSpec(
        "/model",
        "Switch or list model profiles",
        usage="/model [name|id:...]",
        has_args=True,
        arg_values_provider=_build_model_options,
    ),
    SlashSpec(
        "/autonomy",
        "Set autonomy level",
        usage="/autonomy [Auto|L0|L1|L2|L3|L4]",
        has_args=True,
        arg_values_provider=_build_autonomy_options,
    ),
    SlashSpec("/status", "Show session status", usage="/status"),
    SlashSpec(
        "/evolve",
        "Run green-side self-improvement",
        usage="/evolve [status|run <goal>|promote]",
        has_args=True,
        arg_values_provider=_build_evolve_options,
    ),
    SlashSpec(
        "/session",
        "Manage REPL sessions",
        usage="/session [info|new|list|save <name>|load <name>]",
        has_args=True,
        arg_values_provider=_build_session_options,
    ),
    SlashSpec("/permissions", "Show guardrail permissions", usage="/permissions"),
    SlashSpec(
        "/verbose",
        "Toggle verbose system logs",
        usage="/verbose [on|off]",
        has_args=True,
        arg_values_provider=_build_verbose_options,
    ),
    SlashSpec("/cost", "Show token cost estimate", usage="/cost"),
    SlashSpec("/review", "Review recent conversation", usage="/review [n]", has_args=True),
    SlashSpec("/reads", "Show files the REPL has read this session", usage="/reads"),
    SlashSpec("/todo", "Manage todo items", usage="/todo [add|list|done|clear] [text]", has_args=True),
    SlashSpec(
        "/tools",
        "Show tools or set tool policy",
        usage="/tools [auto|on|off]",
        has_args=True,
        arg_values_provider=_build_tools_options,
    ),
    SlashSpec(
        "/memory",
        "Inspect or manage memory",
        usage="/memory [stats|thread|new|query <text>]",
        has_args=True,
        arg_values_provider=_build_memory_options,
    ),
    SlashSpec("/compact", "Compact conversation context", usage="/compact"),
    SlashSpec("/pin", "Pin a memory key", usage="/pin <key> <text>", has_args=True),
    SlashSpec("/unpin", "Remove a pinned memory", usage="/unpin <key>", has_args=True),
    SlashSpec("/project", "Show project instructions", usage="/project"),
    SlashSpec("/plugins", "List loaded plugins", usage="/plugins"),
    SlashSpec("/mcp", "Show MCP server status", usage="/mcp"),
    SlashSpec("/skill", "Run a skill", usage="/skill [name] [args]", has_args=True),
    SlashSpec("/worktree", "Git worktree management", usage="/worktree [create|list|remove]", has_args=True),
    SlashSpec("/bg", "Run a prompt as a background task", usage="/bg <prompt>", has_args=True),
    SlashSpec("/tasks", "List tasks or inspect one by id", usage="/tasks [task-id]", has_args=True),
    SlashSpec("/plan", "Enter plan mode", usage="/plan [prompt]", has_args=True),
]


_CANONICAL_COMMANDS: tuple[str, ...] = tuple(
    spec.command for spec in sorted(_SLASH_SPECS, key=lambda spec: spec.command)
)
_COMMAND_SET: set[str] = {spec.command for spec in _SLASH_SPECS}
_ALIAS_MAP: dict[str, str] = {}
for _spec in _SLASH_SPECS:
    for _alias in _spec.aliases:
        _ALIAS_MAP[_alias] = _spec.command
        _COMMAND_SET.add(_alias)


def list_slash_specs() -> list[SlashSpec]:
    """Return all registered slash command specs."""
    return list(_SLASH_SPECS)


def list_repo_slash_specs(root: Any | None = None) -> tuple[list[SlashSpec], list[str]]:
    """Return specs for repository-defined commands plus scan warnings.

    Re-scans ``.thomas/commands`` and ``.claude/commands`` on every call
    (cheap mtime cache underneath), so newly added definition files are
    discoverable without a REPL restart. Repo commands whose names collide
    with a built-in command or alias are excluded — built-ins always win.
    """
    scan = discover_repo_commands(root)
    specs: list[SlashSpec] = []
    for repo_command in scan.commands:
        if repo_command.command in _COMMAND_SET:
            continue
        specs.append(
            SlashSpec(
                command=repo_command.command,
                summary=repo_command.description or f"Repo command ({repo_command.origin})",
                usage=repo_command.usage,
                has_args=bool(repo_command.argument_hint),
            )
        )
    return specs, list(scan.warnings)


def resolve_slash_invocation(raw: str, root: Any | None = None) -> tuple[str, RepoCommand | None]:
    """Resolve a raw slash token to ``(builtin_command, repo_command)``.

    Precedence: exact built-in command or alias first (built-ins always win
    name collisions), then an exact repository-defined command, then the
    usual built-in prefix/fuzzy normalization. Exactly one element of the
    returned tuple is truthy for a recognized token; both are falsy when the
    token is unknown.
    """
    token = str(raw or "").strip().lower()
    if not token.startswith("/"):
        return "", None
    if token in _ALIAS_MAP:
        return _ALIAS_MAP[token], None
    if token in _COMMAND_SET:
        return token, None
    repo_command = find_repo_command(token, root=root)
    if repo_command is not None and repo_command.command not in _COMMAND_SET:
        return "", repo_command
    return normalize_slash_command(raw), None


def get_slash_spec(command: str) -> SlashSpec | None:
    """Return the canonical spec for *command* if registered."""
    token = str(command or "").strip().lower()
    if not token:
        return None
    if token in _ALIAS_MAP:
        token = _ALIAS_MAP[token]
    for spec in _SLASH_SPECS:
        if spec.command == token:
            return spec
    return None


def normalize_slash_command(raw: str) -> str:
    """Normalize a raw slash token to its canonical command name."""
    t = raw.strip().lower()
    if not t.startswith("/"):
        return ""
    if t in _ALIAS_MAP:
        return _ALIAS_MAP[t]
    if t in _COMMAND_SET:
        return t
    if len(t) >= 2:
        prefix_matches = [cmd for cmd in _CANONICAL_COMMANDS if cmd.startswith(t)]
        if len(prefix_matches) == 1:
            return prefix_matches[0]
    # Fuzzy fallback for obvious typos (only when confidence is strong).
    if len(t) >= 4:
        scored: list[tuple[float, str]] = sorted(
            ((_score_match(t, cmd), cmd) for cmd in _CANONICAL_COMMANDS),
            key=lambda item: item[0],
            reverse=True,
        )
        if scored:
            best_score, best_command = scored[0]
            second_score = scored[1][0] if len(scored) > 1 else 0.0
            if best_score >= 0.74 and (best_score - second_score) >= 0.08 and abs(len(t) - len(best_command)) <= 1:
                return best_command
    return ""


def is_known_slash_command(text: str) -> bool:
    """Return True if *text* starts with a recognized slash command."""
    token = extract_slash_token(text)
    if not token:
        return False
    return bool(normalize_slash_command(token))


def extract_slash_token(text: str) -> str:
    """Extract the leading slash token from *text*."""
    parts = str(text or "").strip().split(None, 1)
    if not parts:
        return ""
    token = parts[0]
    if token.startswith("/"):
        return token
    return ""


def resolve_slash_selection(typed: str, specs: Sequence[SlashSpec]) -> str:
    """Resolve picker/overlay *typed* text to a slash command string."""
    if not typed:
        return ""
    typed_stripped = typed.strip()
    if not typed_stripped.startswith("/"):
        return ""
    parts = typed_stripped.split(None, 1)
    token = parts[0].lower()
    normalized = normalize_slash_command(token)
    if not normalized:
        return ""
    arg = parts[1] if len(parts) > 1 else ""
    return f"{normalized} {arg}".strip()


def suggest_slash_commands(token: str, n: int = 3) -> list[str]:
    """Return up to *n* close matches for *token* from known commands."""
    if not token:
        return []
    all_commands = sorted({s.command for s in _SLASH_SPECS})
    lowered = token.strip().lower()
    if lowered in {"", "/"}:
        return list(all_commands)[:n]
    scored: list[tuple[float, str]] = []
    for command in all_commands:
        score = _score_match(lowered, command)
        if score >= 0.45:
            scored.append((score, command))
    if not scored:
        return []
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_command = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    if best_score >= 0.74 and (best_score - second_score) >= 0.08 and abs(len(lowered) - len(best_command)) <= 1:
        return [best_command]
    return [command for _, command in scored[:n]]


class SlashCommandCompleter(Completer):
    """Prompt-toolkit completer for slash commands with optional arg completion."""

    def __init__(self, *, arg_provider: Callable[[str], list[SlashArgOption]] | None = None) -> None:
        self._arg_provider = arg_provider
        self._context: Any | None = None

    def attach_context(self, context: Any) -> None:
        """Attach runtime context used by dynamic argument providers."""
        self._context = context

    def get_completions(self, document: Document, complete_event: Any) -> Any:
        text = document.text_before_cursor or ""
        if text and not text.startswith("/"):
            return

        parts = text.split(None, 1)
        if text.endswith(" ") and len(parts) == 1 and str(parts[0]).startswith("/"):
            parts = [parts[0], ""]
        token = parts[0].lower() if parts else ""
        token_query = token.strip()

        if len(parts) <= 1:
            all_specs = list(_SLASH_SPECS)
            repo_specs, _repo_warnings = list_repo_slash_specs()
            all_specs.extend(repo_specs)
            ranked: list[tuple[float, SlashSpec]] = []
            if token_query in {"", "/"}:
                ranked = [(1.0, spec) for spec in all_specs]
            else:
                prefix_matches = [spec for spec in all_specs if spec.command.startswith(token_query)]
                if prefix_matches:
                    ranked = [(1.0 if spec.command == token_query else 0.95, spec) for spec in prefix_matches]
                else:
                    for spec in all_specs:
                        score = _score_match(token_query, spec.command)
                        if score >= 0.68:
                            ranked.append((score, spec))
            ranked.sort(key=lambda item: (-item[0], item[1].command))

            for _, spec in ranked:
                yield Completion(
                    spec.command,
                    start_position=-len(token),
                    display=spec.command,
                    display_meta=spec.summary,
                )
            return

        cmd = normalize_slash_command(token_query)
        if not cmd:
            return
        if not self._arg_provider:
            return
        try:
            if self._context is not None:
                raw_choices = slash_arg_options(cmd, self._context)
            else:
                raw_choices = self._arg_provider(cmd)
        except Exception:
            return
        if not raw_choices:
            return
        arg_text = parts[1] if len(parts) > 1 else ""
        for choice in raw_choices:
            if not isinstance(choice, SlashArgOption):
                continue
            if not _match_option(arg_text, choice):
                continue
            yield Completion(
                choice.value,
                start_position=-len(arg_text),
                display=choice.label,
                display_meta=choice.description,
            )
