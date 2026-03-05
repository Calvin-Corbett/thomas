from __future__ import annotations

import pytest
from prompt_toolkit.document import Document

from thomas.cli.repl import _should_open_slash_popup
from thomas.cli.repl_slash import (
    SlashArgOption,
    SlashCommandCompleter,
    slash_arg_options,
    is_known_slash_command,
    list_slash_specs,
    normalize_slash_command,
    resolve_slash_selection,
    suggest_slash_commands,
)

from thomas.cli.repl_runtime import ThomasREPLRuntimeMixin
from thomas.cli.repl_state import ReplUiState


class _DummySlashRuntime(ThomasREPLRuntimeMixin):
    def __init__(self, *, command_plan: list[str], arg_plan: list[str | object]) -> None:
        self._slash_specs = list_slash_specs()
        self._ui_state = ReplUiState.IDLE
        self._current_model = "default"
        self._conversation: list[dict[str, str]] = []
        self._autonomy_level = 3
        self._overlay_parent_command: str | None = None
        self._overlay_exit_action = "accept"
        self._overlay_back_sentinel = object()
        self._overlay_depth = 0
        self._alt_screen_active = False
        self._command_plan = list(command_plan)
        self._arg_plan = list(arg_plan)
        self._show_system_logs = False
        self.printed_turns: list[tuple[str, str]] = []
        self.printed_system_events: list[str] = []
        self.printed_console: list[str] = []
        self._pick_calls: list[str] = []
        self._console = type(
            "Console",
            (),
            {"print": lambda _self, message: self.printed_console.append(str(message or ""))},
        )()
        self.config = type("Config", (), {"models": {"default": type("Model", (), {"model": "gpt-default"})()}})()

    def _print_turn(self, role: str, text: str) -> None:
        self.printed_turns.append((role, text))

    def _print_system_event(self, text: str, *, important: bool = False) -> None:
        self.printed_system_events.append(str(text or ""))

    def _transition_ui_state(self, target: ReplUiState) -> None:
        self._ui_state = target

    async def _pick_slash_command(self, *, default: str = "/") -> str:
        self._pick_calls.append(f"command:{default}")
        if not self._command_plan:
            return ""
        return str(self._command_plan.pop(0))

    async def _pick_slash_argument(self, command: str, arg: str) -> str | object:
        self._pick_calls.append(f"arg:{command}:{arg}")
        if not self._arg_plan:
            return arg
        return self._arg_plan.pop(0)

    def _reset_context_window_cache(self) -> None:
        return None

    async def _maybe_pick_reasoning_level(self, *_: object) -> None:
        return None


@pytest.mark.asyncio
async def test_handle_slash_command_menu_can_return_to_root_on_argument_escape() -> None:
    runtime = _DummySlashRuntime(
        command_plan=["/autonomy", "/exit"],
        arg_plan=[object(), ""],
    )
    runtime._arg_plan[0] = runtime._overlay_back_sentinel
    should_exit, handled = await runtime._handle_slash("/")
    assert should_exit is True
    assert handled is True
    assert runtime._pick_calls == [
        "command:/",
        "arg:/autonomy:",
        "command:/",
        "arg:/exit:",
    ]
    assert runtime.printed_turns == []


@pytest.mark.asyncio
async def test_handle_slash_command_from_picker_uses_recursive_dispatch() -> None:
    runtime = _DummySlashRuntime(command_plan=["/exit"], arg_plan=[""])
    should_exit, handled = await runtime._handle_slash("/")
    assert should_exit is True
    assert handled is True
    assert runtime.printed_turns == []
    assert runtime._pick_calls == ["command:/", "arg:/exit:"]


@pytest.mark.asyncio
async def test_handle_slash_model_command_updates_state_not_user_transcript() -> None:
    runtime = _DummySlashRuntime(
        command_plan=[],
        arg_plan=[],
    )
    runtime.config = type(
        "Config",
        (),
        {
            "models": {
                "default": type("Model", (), {"model": "gpt-base"})(),
                "codex": type("Model", (), {"model": "gpt-codex"})(),
            }
        },
    )()

    should_exit, handled = await runtime._handle_slash("/model codex")

    assert should_exit is False
    assert handled is True
    assert runtime._current_model == "codex"
    assert runtime.printed_turns == []
    assert runtime.printed_system_events
    assert any("model set to" in event for event in runtime.printed_system_events)


def test_normalize_canonical_alias_and_typo_handling() -> None:
    assert normalize_slash_command("/memory") == "/memory"
    assert normalize_slash_command("/q") == "/exit"
    assert normalize_slash_command("/mmeorty") == "/memory"


def test_normalize_does_not_execute_longer_non_command_variants() -> None:
    assert normalize_slash_command("/clearing") == ""


def test_normalize_ambiguous_prefix_remains_unknown() -> None:
    assert normalize_slash_command("/m") == ""
    assert is_known_slash_command("/m") is False


def test_normalize_unique_prefix_expands_once() -> None:
    assert normalize_slash_command("/mem") == "/memory"
    assert normalize_slash_command("/task") == "/tasks"


def test_suggest_and_resolve_aware_of_typo() -> None:
    specs = list_slash_specs()
    assert suggest_slash_commands("/mmeorty") == ["/memory"]
    assert resolve_slash_selection("/mmeorty", specs) == "/memory"


def test_slash_registry_includes_help_and_tools() -> None:
    by_command = {spec.command: spec for spec in list_slash_specs()}
    assert "/help" in by_command
    assert "/tools" in by_command
    assert by_command["/help"].has_args is False
    assert by_command["/tools"].has_args is True


def test_autonomy_arg_options_include_levels() -> None:
    options = slash_arg_options("/autonomy")
    values = [opt.value for opt in options]
    assert "Auto" in values
    assert "L0" in values
    assert "L1" in values
    assert "L2" in values
    assert "L3" in values
    assert "L4" in values


def test_tools_arg_options_are_predefined() -> None:
    options = slash_arg_options("/tools")
    values = [opt.value for opt in options]
    assert values == ["auto", "on", "off"]


def test_verbose_arg_options_include_toggle_and_activity_values() -> None:
    options = slash_arg_options("/verbose")
    values = [opt.value for opt in options]
    assert values == ["on", "off", "minimal", "normal", "debug"]


def test_slash_registry_includes_verbose_command() -> None:
    by_command = {spec.command: spec for spec in list_slash_specs()}
    assert "/verbose" in by_command
    assert by_command["/verbose"].has_args is True


def test_model_arg_options_use_dynamic_and_static_sources() -> None:
    class _Ctx:
        def _known_model_profile_names(self) -> list[str]:
            return ["profile_a", "profile_b"]

    ctx = _Ctx()
    ctx._last_model_choices = ["id:gpt-5", "profile_b"]

    options = slash_arg_options("/model", ctx)
    values = [opt.value for opt in options]
    assert "profile_a" in values
    assert "profile_b" in values
    assert "id:gpt-5" in values


def test_suggest_slash_commands_fuzzy_match() -> None:
    got = suggest_slash_commands("/tool")
    assert "/tools" in got


def test_help_spec_exposes_description_and_usage() -> None:
    help_spec = {spec.command: spec for spec in list_slash_specs()}["/help"]
    assert "/help" in help_spec.usage
    assert help_spec.summary


def test_slash_completer_shows_commands_on_empty_input() -> None:
    completer = SlashCommandCompleter(arg_provider=slash_arg_options)
    completions = list(completer.get_completions(Document(""), None))
    completed = sorted({completion.text for completion in completions})
    assert "/help" in completed
    assert "/autonomy" in completed
    assert "/model" in completed
    assert len(completed) >= 10


def test_slash_completer_fuzzy_match_on_prefix() -> None:
    completer = SlashCommandCompleter(arg_provider=slash_arg_options)
    completions = list(completer.get_completions(Document("/aut"), None))
    values = sorted({completion.text for completion in completions})
    assert values == ["/autonomy"]


def test_slash_completer_uses_arg_completion_after_trailing_space() -> None:
    def _arg_provider(_: str) -> list[SlashArgOption]:
        return [SlashArgOption("profile_a", "profile_a"), SlashArgOption("profile_b", "profile_b")]

    completer = SlashCommandCompleter(arg_provider=_arg_provider)
    completions = list(completer.get_completions(Document("/model "), None))
    values = sorted({completion.text for completion in completions})
    assert values == ["profile_a", "profile_b"]


@pytest.mark.asyncio
async def test_handle_slash_model_profile_matching_is_case_insensitive() -> None:
    runtime = _DummySlashRuntime(command_plan=[], arg_plan=[])
    runtime.config = type(
        "Config",
        (),
        {"models": {"Codex": type("Model", (), {"model": "gpt-codex"})(), "Local": type("Model", (), {"model": "gpt-local"})()}},
    )()

    should_exit, handled = await runtime._handle_slash("/model local")

    assert should_exit is False
    assert handled is True
    assert runtime._current_model == "Local"
    assert runtime.config.models["Local"].model == "gpt-local"


@pytest.mark.asyncio
async def test_load_rejects_non_object_conversation_entries(tmp_path) -> None:
    runtime = _DummySlashRuntime(command_plan=[], arg_plan=[])
    bad_path = tmp_path / "bad_conversation.json"
    bad_path.write_text('["bad"]', encoding="utf-8")

    should_exit, handled = await runtime._handle_slash(f"/load {bad_path}")

    assert should_exit is False
    assert handled is True
    assert runtime._conversation == []
    assert any("Invalid conversation format" in message for message in runtime.printed_console)


@pytest.mark.asyncio
async def test_autonomy_l0_maps_to_l1_floor() -> None:
    runtime = _DummySlashRuntime(command_plan=[], arg_plan=[])
    runtime._autonomy_level = 3

    should_exit, handled = await runtime._handle_slash("/autonomy l0")

    assert should_exit is False
    assert handled is True
    assert int(runtime._autonomy_level) == 1


@pytest.mark.parametrize(
    ("text", "cursor_position", "expected"),
    [
        ("", 0, True),
        ("   ", 3, True),
        ("/", 1, True),
        ("/aut", 4, True),
        ("//", 2, False),
        ("hello", 5, False),
        ("/aut", 2, False),
    ],
)
def test_should_open_slash_popup_handles_reopen_edge_cases(text: str, cursor_position: int, expected: bool) -> None:
    assert _should_open_slash_popup(text, cursor_position) is expected
