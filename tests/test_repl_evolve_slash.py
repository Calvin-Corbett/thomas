from __future__ import annotations

import json
from pathlib import Path

import pytest

import thomas.cli.repl_runtime as repl_runtime_module
from thomas.cli.repl_runtime import ThomasREPLRuntimeMixin
from thomas.cli.repl_slash import list_slash_specs, slash_arg_options
from thomas.cli.repl_state import ReplUiState


class _DummyRuntime(ThomasREPLRuntimeMixin):
    def __init__(self) -> None:
        self._slash_specs = list_slash_specs()
        self._ui_state = ReplUiState.IDLE
        self._conversation: list[dict[str, str]] = []
        self._autonomy_level = 3
        self._current_model = "default"
        self._overlay_back_sentinel = object()
        self._show_system_logs = False
        self._activity_verbosity = "normal"
        self._console_output: list[str] = []
        self._console = type(
            "Console", (), {"print": lambda _self, message: self._console_output.append(str(message))}
        )()
        self.config = type(
            "Config",
            (),
            {
                "tools": type("Tools", (), {"sandbox_path": Path.cwd()})(),
                "models": {"default": type("Model", (), {"model": "gpt-default"})()},
            },
        )()

    async def _pick_slash_argument(self, command: str, arg: str):
        return arg

    def _transition_ui_state(self, target: ReplUiState) -> None:
        self._ui_state = target

    def _print_system_event(self, text: str, *, important: bool = False) -> None:
        self._console_output.append(str(text))


def test_evolve_slash_registry_and_args() -> None:
    specs = {spec.command: spec for spec in list_slash_specs()}
    assert "/evolve" in specs
    values = [opt.value for opt in slash_arg_options("/evolve")]
    assert values == ["status", "run ", "promote"]


@pytest.mark.asyncio
async def test_evolve_status_dispatch(monkeypatch) -> None:
    runtime = _DummyRuntime()
    payload = {
        "ok": True,
        "initialized": True,
        "charter": {"objective": "Improve Thomas continuously"},
        "latest_session": {
            "session_id": "evolve-123",
            "status": "ready",
            "changed_files": ["thomas/__init__.py"],
            "promotable": True,
        },
    }

    def fake_run(*args, **kwargs):
        return type("Completed", (), {"returncode": 0, "stdout": json.dumps(payload), "stderr": ""})()

    monkeypatch.setattr(repl_runtime_module.subprocess, "run", fake_run)
    should_exit, handled = await runtime._handle_slash("/evolve status")
    assert should_exit is False
    assert handled is True
    assert any("evolve-123" in line or "Improve Thomas continuously" in line for line in runtime._console_output)
