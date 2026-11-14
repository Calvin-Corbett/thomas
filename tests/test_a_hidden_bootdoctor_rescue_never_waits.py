"""A rescue that nobody can see never stops to ask a question, when it is started with --no-interactive.

When its automatic attempts ran out, `bootdoctor rescue` sat at an input() prompt, which in a window no one can see
waits for good. `--no-interactive` ends the run instead. Without it the rescue is unchanged and stays open for you:
that is how startup_recovery_watch.ps1 still starts it, in a visible window. Nothing in the launchers passes the flag
yet; run-ui.ps1 starts its own rescue hidden and is the caller it is for.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import thomas.bootdoctor.__main__ as bd_main
from tests._bootdoctor_fakes import isolate_offline_checks
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_offline_checks(tmp_path, monkeypatch)


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Records every prompt. Nobody types, so each one ends at once: a rescue that wrongly waits fails, not hangs."""
    prompts: list[str] = []

    def _no_one_types(*args):
        prompts.append(str(args))
        raise EOFError

    monkeypatch.setattr("builtins.input", _no_one_types)
    return prompts


def _config(tmp_path: Path, *, with_model: bool = False) -> AppConfig:
    models = {"rescue": ModelConfig(name="rescue", provider="local", model="stub")} if with_model else {}
    return AppConfig(memory=MemoryConfig(root=str(tmp_path / "mem")), models=models, default_model="rescue")


class _SilentAgent:
    """An agent whose repair pass does nothing, so every attempt ends with Thomas still down."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def run(self, prompt: str):
        self.prompts.append(prompt)
        return
        yield  # makes this an async generator


class _Llm:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _use_agent(monkeypatch: pytest.MonkeyPatch, agent: _SilentAgent, llm: _Llm) -> None:
    monkeypatch.setattr(bd_main, "_build_bootdoctor_agent", lambda args, *, config, root: (agent, llm, object()))


def _status(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "runtime" / "boot_doctor" / "rescue_status.json").read_text(encoding="utf-8"))


def _rescue(tmp_path: Path, *flags: str, with_model: bool = False) -> int:
    args = bd_main._build_parser().parse_args(
        ["rescue", "--no-ai", "--no-auto-repair", "--port", "22058", "--max-attempts", "1", *flags]
    )
    return asyncio.run(bd_main._run_rescue(args, config=_config(tmp_path, with_model=with_model), root=tmp_path))


def test_a_hidden_rescue_with_no_model_never_waits_for_typed_input(tmp_path: Path, asked: list[str]) -> None:
    assert _rescue(tmp_path, "--no-interactive", "--relaunch") == 1
    assert asked == []


def test_a_hidden_rescue_that_runs_out_of_attempts_ends_instead_of_waiting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asked: list[str]
) -> None:
    agent, llm = _SilentAgent(), _Llm()
    _use_agent(monkeypatch, agent, llm)

    assert _rescue(tmp_path, "--no-interactive", with_model=True) == 1

    assert asked == []
    assert len(agent.prompts) == 1  # the one allowed repair pass ran
    assert llm.closed
    status = _status(tmp_path)
    assert (status["status"], status["phase"]) == ("failed", "awaiting_user")


def test_a_visible_rescue_that_runs_out_of_attempts_stays_open_for_you(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent, llm = _SilentAgent(), _Llm()
    _use_agent(monkeypatch, agent, llm)
    prompts: list[str] = []

    def _no_one_types(*args):
        prompts.append("asked")
        raise EOFError

    monkeypatch.setattr("builtins.input", _no_one_types)

    assert _rescue(tmp_path, with_model=True) == 0  # the interactive loop ended when its input ran dry

    assert prompts == ["asked"]  # it opened the prompt and waited
    assert llm.closed


def test_a_visible_rescue_with_no_model_still_waits_at_the_end(tmp_path: Path, asked: list[str]) -> None:
    assert _rescue(tmp_path) == 1
    assert len(asked) == 1
