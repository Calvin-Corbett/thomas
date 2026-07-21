"""Tests for repository-defined slash commands (CAP-022).

Acceptance line: repository-defined, parameterized slash commands that are
discoverable at runtime.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from thomas.cli.repl_slash import (
    SlashCommandCompleter,
    list_repo_slash_specs,
    resolve_slash_invocation,
)
from thomas.cli.repo_commands import (
    RepoCommand,
    discover_repo_commands,
    dispatch_repo_command,
    find_repo_command,
    render_repo_command,
)


def _write_command(root: Path, source: str, name: str, body: str) -> Path:
    directory = root / source / "commands"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.md"
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_discovers_thomas_command_with_frontmatter(tmp_path: Path) -> None:
    _write_command(
        tmp_path,
        ".thomas",
        "deploy",
        "---\ndescription: Deploy the app\nargument-hint: <env>\n---\nDeploy to $1 now.\n",
    )
    scan = discover_repo_commands(tmp_path)
    assert scan.warnings == ()
    assert [c.name for c in scan.commands] == ["deploy"]
    command = scan.commands[0]
    assert command.command == "/deploy"
    assert command.description == "Deploy the app"
    assert command.argument_hint == "<env>"
    assert command.usage == "/deploy <env>"
    assert command.template == "Deploy to $1 now."
    assert command.origin == ".thomas"


def test_discovers_claude_commands_as_fallback_source(tmp_path: Path) -> None:
    _write_command(tmp_path, ".claude", "review-pr", "Review PR $1 carefully.")
    scan = discover_repo_commands(tmp_path)
    assert scan.warnings == ()
    assert [c.name for c in scan.commands] == ["review-pr"]
    assert scan.commands[0].origin == ".claude"


def test_frontmatter_is_optional(tmp_path: Path) -> None:
    _write_command(tmp_path, ".thomas", "plain", "Just a prompt.")
    command = find_repo_command("/plain", root=tmp_path)
    assert command is not None
    assert command.template == "Just a prompt."
    assert command.description == ""


def test_thomas_wins_name_collision_with_claude(tmp_path: Path) -> None:
    _write_command(tmp_path, ".thomas", "deploy", "thomas template")
    _write_command(tmp_path, ".claude", "deploy", "claude template")
    scan = discover_repo_commands(tmp_path)
    assert [c.name for c in scan.commands] == ["deploy"]
    assert scan.commands[0].origin == ".thomas"
    assert scan.commands[0].template == "thomas template"


def test_new_file_discoverable_without_restart(tmp_path: Path) -> None:
    _write_command(tmp_path, ".thomas", "first", "first template")
    assert [c.name for c in discover_repo_commands(tmp_path).commands] == ["first"]
    # Add a new definition after the first scan: must show up on re-scan.
    _write_command(tmp_path, ".thomas", "second", "second template")
    assert [c.name for c in discover_repo_commands(tmp_path).commands] == ["first", "second"]


def test_scan_of_repo_without_command_dirs_is_empty(tmp_path: Path) -> None:
    scan = discover_repo_commands(tmp_path)
    assert scan.commands == ()
    assert scan.warnings == ()


# ---------------------------------------------------------------------------
# Malformed definitions degrade to warnings, never a crash
# ---------------------------------------------------------------------------


def test_unterminated_frontmatter_warns_and_skips(tmp_path: Path) -> None:
    _write_command(tmp_path, ".thomas", "broken", "---\ndescription: no closing fence\nBody text\n")
    _write_command(tmp_path, ".thomas", "good", "Working template")
    scan = discover_repo_commands(tmp_path)
    assert [c.name for c in scan.commands] == ["good"]
    assert len(scan.warnings) == 1
    assert "broken.md" in scan.warnings[0]
    assert "unterminated frontmatter" in scan.warnings[0]


def test_empty_template_warns_and_skips(tmp_path: Path) -> None:
    _write_command(tmp_path, ".thomas", "empty", "---\ndescription: nothing\n---\n\n")
    scan = discover_repo_commands(tmp_path)
    assert scan.commands == ()
    assert len(scan.warnings) == 1
    assert "empty prompt template" in scan.warnings[0]


def test_invalid_command_name_warns_and_skips(tmp_path: Path) -> None:
    _write_command(tmp_path, ".thomas", "bad name!", "template")
    scan = discover_repo_commands(tmp_path)
    assert scan.commands == ()
    assert len(scan.warnings) == 1
    assert "invalid command name" in scan.warnings[0]


def test_invalid_frontmatter_line_warns_and_skips(tmp_path: Path) -> None:
    _write_command(tmp_path, ".thomas", "oddmeta", "---\njust some words\n---\nBody\n")
    scan = discover_repo_commands(tmp_path)
    assert scan.commands == ()
    assert len(scan.warnings) == 1
    assert "invalid frontmatter line" in scan.warnings[0]


# ---------------------------------------------------------------------------
# Parameter substitution
# ---------------------------------------------------------------------------


def test_arguments_placeholder_receives_full_string(tmp_path: Path) -> None:
    _write_command(tmp_path, ".thomas", "ask", "Answer this: $ARGUMENTS")
    command = find_repo_command("ask", root=tmp_path)
    assert command is not None
    assert render_repo_command(command, "why is the sky blue") == "Answer this: why is the sky blue"


def test_positional_placeholders_substitute_in_order() -> None:
    command = RepoCommand(name="mv", template="Move $1 to $2 (was: $ARGUMENTS)")
    assert render_repo_command(command, "a.txt b.txt") == "Move a.txt to b.txt (was: a.txt b.txt)"


def test_missing_positional_renders_empty() -> None:
    command = RepoCommand(name="pair", template="First=$1 Second=$2 Ninth=$9")
    assert render_repo_command(command, "only") == "First=only Second= Ninth="


def test_quoted_arguments_stay_grouped() -> None:
    command = RepoCommand(name="say", template="A=$1 B=$2")
    assert render_repo_command(command, '"hello world" next') == "A=hello world B=next"


def test_args_appended_when_template_has_no_placeholder() -> None:
    command = RepoCommand(name="fix", template="Fix the failing tests.")
    assert render_repo_command(command, "focus on auth") == "Fix the failing tests.\n\nfocus on auth"


def test_no_args_substitutes_placeholders_with_empty() -> None:
    command = RepoCommand(name="fix", template="Fix $1 and $ARGUMENTS.")
    assert render_repo_command(command, "") == "Fix  and ."


# ---------------------------------------------------------------------------
# Resolution: built-ins always win; exact repo match beats fuzzy built-in
# ---------------------------------------------------------------------------


def test_builtin_wins_name_collision_with_repo_command(tmp_path: Path) -> None:
    _write_command(tmp_path, ".thomas", "help", "Shadow the built-in help")
    command, repo_command = resolve_slash_invocation("/help", root=tmp_path)
    assert command == "/help"
    assert repo_command is None


def test_builtin_alias_wins_over_repo_command(tmp_path: Path) -> None:
    _write_command(tmp_path, ".thomas", "quit", "Shadow the /exit alias")
    command, repo_command = resolve_slash_invocation("/quit", root=tmp_path)
    assert command == "/exit"
    assert repo_command is None


def test_repo_command_resolves_when_not_builtin(tmp_path: Path) -> None:
    _write_command(tmp_path, ".thomas", "deploy", "Deploy to $1")
    command, repo_command = resolve_slash_invocation("/deploy", root=tmp_path)
    assert command == ""
    assert repo_command is not None
    assert repo_command.name == "deploy"


def test_exact_repo_command_beats_fuzzy_builtin_match(tmp_path: Path) -> None:
    # "/planx" would otherwise fuzzy-normalize to the built-in "/plan".
    _write_command(tmp_path, ".thomas", "planx", "Custom planning: $ARGUMENTS")
    command, repo_command = resolve_slash_invocation("/planx", root=tmp_path)
    assert command == ""
    assert repo_command is not None
    assert repo_command.name == "planx"


def test_unknown_token_resolves_to_nothing(tmp_path: Path) -> None:
    command, repo_command = resolve_slash_invocation("/definitely-not-a-command", root=tmp_path)
    assert command == ""
    assert repo_command is None


# ---------------------------------------------------------------------------
# Runtime discoverability (/help listing + completer)
# ---------------------------------------------------------------------------


def test_repo_specs_listed_with_descriptions(tmp_path: Path) -> None:
    _write_command(
        tmp_path,
        ".thomas",
        "deploy",
        "---\ndescription: Deploy the app\nargument-hint: <env>\n---\nDeploy to $1\n",
    )
    specs, warnings = list_repo_slash_specs(tmp_path)
    assert warnings == []
    assert [s.command for s in specs] == ["/deploy"]
    assert specs[0].summary == "Deploy the app"
    assert specs[0].usage == "/deploy <env>"
    assert specs[0].has_args is True


def test_repo_specs_exclude_builtin_shadows_and_carry_warnings(tmp_path: Path) -> None:
    _write_command(tmp_path, ".thomas", "help", "shadowed by built-in")
    _write_command(tmp_path, ".thomas", "broken", "---\nno closing fence\n")
    _write_command(tmp_path, ".thomas", "mine", "visible template")
    specs, warnings = list_repo_slash_specs(tmp_path)
    assert [s.command for s in specs] == ["/mine"]
    assert len(warnings) == 1
    assert "broken.md" in warnings[0]


def test_repo_spec_listing_rescans_for_new_files(tmp_path: Path) -> None:
    specs, _warnings = list_repo_slash_specs(tmp_path)
    assert specs == []
    _write_command(tmp_path, ".thomas", "fresh", "new template")
    specs, _warnings = list_repo_slash_specs(tmp_path)
    assert [s.command for s in specs] == ["/fresh"]


def test_completer_offers_repo_commands(tmp_path: Path, monkeypatch) -> None:
    from prompt_toolkit.document import Document

    _write_command(tmp_path, ".thomas", "deploy", "Deploy to $1")
    monkeypatch.chdir(tmp_path)
    completer = SlashCommandCompleter()
    completions = list(completer.get_completions(Document("/dep"), None))
    assert any(c.text == "/deploy" for c in completions)


# ---------------------------------------------------------------------------
# Dispatch: rendered prompt goes through the typed-message agent path
# ---------------------------------------------------------------------------


class _FakeConsole:
    def __init__(self) -> None:
        self.printed: list[object] = []

    def print(self, *args: object, **kwargs: object) -> None:
        self.printed.extend(args)


class _FakeRepl:
    def __init__(self) -> None:
        self._console = _FakeConsole()
        self.agent_turns: list[str] = []

    async def _run_agent_turn(self, prompt: str) -> None:
        self.agent_turns.append(prompt)


def test_dispatch_sends_rendered_prompt_to_agent_turn() -> None:
    repl = _FakeRepl()
    command = RepoCommand(name="deploy", template="Deploy to $1 with $ARGUMENTS", origin=".thomas")
    asyncio.run(dispatch_repo_command(repl, command, "staging --fast"))
    assert repl.agent_turns == ["Deploy to staging with staging --fast"]
    assert any("/deploy" in str(item) for item in repl._console.printed)


def test_handle_slash_dispatches_repo_command_end_to_end(tmp_path: Path, monkeypatch) -> None:
    """/name arg flows through _handle_slash into the agent-turn path."""
    from thomas.cli.repl_runtime import ThomasREPLRuntimeMixin

    _write_command(tmp_path, ".thomas", "greet", "Say hello to $1")
    monkeypatch.chdir(tmp_path)

    class _Repl(ThomasREPLRuntimeMixin):
        def __init__(self) -> None:
            self._console = _FakeConsole()
            self.agent_turns: list[str] = []

        async def _run_agent_turn(self, prompt: str) -> None:
            self.agent_turns.append(prompt)

    repl = _Repl()
    should_exit, handled = asyncio.run(repl._handle_slash("/greet Calvin"))
    assert (should_exit, handled) == (False, True)
    assert repl.agent_turns == ["Say hello to Calvin"]
