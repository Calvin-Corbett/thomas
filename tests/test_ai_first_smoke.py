from __future__ import annotations

import json
import sys
import types

import pytest

from thomas.chat_logger import BehaviorObservation
from thomas.cli.repl_runtime import ThomasREPLRuntimeMixin
from thomas.cli.repl_slash import list_slash_specs
from thomas.cli.repl_state import ReplUiState
from thomas.plugins.p110_plugin_hook_before_tool import HookInputError, ToolCall
from thomas.tools.base import ToolResult


class _CaptureConsole:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *args: object, **kwargs: object) -> None:
        # Rich panels become objects; keep a stable fallback for assertions.
        self.lines.extend(str(part) for part in args)


class _SmokeSlashRuntime(ThomasREPLRuntimeMixin):
    def __init__(self) -> None:
        self._slash_specs = list_slash_specs()
        self._ui_state = ReplUiState.IDLE
        self._current_model = "default"
        self._autonomy_level = 3
        self._tools_policy = "auto"
        self._show_system_logs = False
        self._activity_verbosity = "normal"
        self._overlay_parent_command = None
        self._overlay_exit_action = "accept"
        self._overlay_back_sentinel = object()
        self._overlay_depth = 0
        self._alt_screen_active = False
        self._settings_persist_calls = 0
        self._console = _CaptureConsole()

    def _print_turn(self, role: str, text: str) -> None:
        # Kept for compatibility with legacy mixin contracts.
        return None

    def _print_system_event(self, text: str, important: bool = False) -> None:
        self._console.print(text)

    def _transition_ui_state(self, target: ReplUiState) -> None:
        self._ui_state = target

    def _persist_runtime_settings(self) -> None:
        self._settings_persist_calls += 1

    async def _pick_slash_argument(self, command: str, arg: str) -> str:
        return arg


class _SlashPickerRuntime(_SmokeSlashRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.pick_calls: list[str] = []

    async def _pick_slash_command(self, *, default: str = "/") -> str:
        self.pick_calls.append(default)
        return "/help"


@pytest.mark.asyncio
async def test_repl_help_command_is_handled() -> None:
    runtime = _SmokeSlashRuntime()
    should_exit, handled = await runtime._handle_slash("/help")

    assert should_exit is False
    assert handled is True
    assert len(runtime._console.lines) > 0
    assert any("Panel" in line for line in runtime._console.lines)


@pytest.mark.asyncio
async def test_root_slash_opens_picker_and_dispatches_command() -> None:
    runtime = _SlashPickerRuntime()
    should_exit, handled = await runtime._handle_slash("/")

    assert should_exit is False
    assert handled is True
    assert runtime.pick_calls == ["/"]
    assert any("Panel" in line for line in runtime._console.lines)


@pytest.mark.asyncio
async def test_repl_model_persist_failure_logs_warning(monkeypatch, caplog) -> None:
    runtime = _SmokeSlashRuntime()

    fake_module = types.ModuleType("thomas.server.model_preferences")

    def _boom(**_kwargs):
        raise RuntimeError("db write failed")

    fake_module.persist_user_model_preferences = _boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "thomas.server.model_preferences", fake_module)

    with caplog.at_level("WARNING", logger="thomas.cli.repl_runtime"):
        await runtime._persist_repl_model_selection(profile="codex", model_id="gpt-5")

    assert any(
        "Failed to persist REPL model selection profile=codex model_id=gpt-5" in rec.message for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_autonomy_command_persists_runtime_settings() -> None:
    runtime = _SmokeSlashRuntime()
    should_exit, handled = await runtime._handle_slash("/autonomy L4")

    assert should_exit is False
    assert handled is True
    assert runtime._autonomy_level == 4
    assert runtime._settings_persist_calls == 1


@pytest.mark.asyncio
async def test_tools_command_persists_runtime_settings() -> None:
    runtime = _SmokeSlashRuntime()
    should_exit, handled = await runtime._handle_slash("/tools on")

    assert should_exit is False
    assert handled is True
    assert runtime._tools_policy == "always"
    assert runtime._settings_persist_calls == 1


@pytest.mark.asyncio
async def test_verbose_command_persists_runtime_settings() -> None:
    runtime = _SmokeSlashRuntime()
    should_exit, handled = await runtime._handle_slash("/verbose debug")

    assert should_exit is False
    assert handled is True
    assert runtime._activity_verbosity == "debug"
    assert runtime._settings_persist_calls == 1


def test_toolcall_schema_validation_rejects_invalid_inputs() -> None:
    with pytest.raises(HookInputError):
        ToolCall(name="", args={})

    with pytest.raises(HookInputError):
        ToolCall(name="demo.echo", args=[])

    valid_call = ToolCall(name="demo.echo", args={"text": "hi"})
    assert valid_call.name == "demo.echo"
    assert valid_call.args == {"text": "hi"}


def test_toolresult_to_content_and_error_shape() -> None:
    ok_result = ToolResult(ok=True, data={"status": "ok"})
    assert ok_result.ok is True
    assert ok_result.error is None
    ok_payload = json.loads(ok_result.to_content())
    assert ok_payload["status"] == "ok"

    error_result = ToolResult(ok=False, error="tool failed")
    assert error_result.ok is False
    err_payload = json.loads(error_result.to_content())
    assert err_payload["ok"] is False
    assert err_payload["error"] == "tool failed"


def test_behavior_observation_contract_is_stable() -> None:
    obs = BehaviorObservation(
        quality="needs_improvement",
        flagged=True,
        reasons=["ambiguous request"],
        suggestions=["clarify"],
    )
    payload = obs.to_dict()

    assert payload["quality"] == "needs_improvement"
    assert payload["flagged"] is True
    assert payload["reasons"] == ["ambiguous request"]
    assert payload["suggestions"] == ["clarify"]
    assert "metrics" in payload
    assert isinstance(payload["timestamp"], float)


def test_app_boots_with_isolated_data_root(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "thomas-run"))

    from thomas.server.app import create_app

    app = create_app()
    assert app is not None
    assert app.router is not None
