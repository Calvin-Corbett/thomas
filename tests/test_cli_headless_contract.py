"""CAP-078 headless/CI contract: deterministic exit codes + machine-readable run log.

Contract under test (see thomas/cli/headless_run_log.py):
  exit 0 success, 1 agent/task error, 2 usage/config error, 3 timeout/interrupt;
  one JSON summary object appended per run to --run-log / THOMAS_RUN_LOG.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest
from click.testing import CliRunner

import thomas.cli.main as cli_main
from thomas.cli._commands_base import chat as chat_cmd
from thomas.cli.headless_run_log import (
    EXIT_AGENT_ERROR,
    EXIT_SUCCESS,
    EXIT_TIMEOUT,
    EXIT_USAGE_ERROR,
    append_run_record,
    exit_code_for_outcome,
    resolve_run_log_path,
)
from thomas.core.config import AppConfig, MemoryConfig, ModelConfig
from thomas.core.events import AgentEvent, EventType

REQUIRED_RECORD_KEYS = {
    "timestamp",
    "prompt",
    "model_profile",
    "model",
    "outcome",
    "exit_code",
    "duration_s",
    "error",
    "artifacts",
}


def _cfg(tmp_path: Path) -> AppConfig:
    return AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        memory=MemoryConfig(root=str(tmp_path)),
    )


class _DummyLLM:
    def __init__(self, model_config, **_kwargs):  # noqa: ANN001
        self.config = model_config
        self.session_usage = types.SimpleNamespace(prompt_tokens=0, completion_tokens=0, total_tokens=0)

    async def close(self) -> None:
        return None


class _SuccessAgentLoop:
    def __init__(self, _config, _llm, _tools, **_kwargs):  # noqa: ANN001
        pass

    async def run(self, _prompt, **_kwargs):  # noqa: ANN001
        yield AgentEvent(type=EventType.TEXT_DELTA, data={"text": "hi"})
        yield AgentEvent(
            type=EventType.AGENT_DONE,
            data={"iterations": 1, "tool_calls": 0, "artifacts": ["out/report.md"]},
        )


class _AgentErrorLoop:
    def __init__(self, _config, _llm, _tools, **_kwargs):  # noqa: ANN001
        pass

    async def run(self, _prompt, **_kwargs):  # noqa: ANN001
        yield AgentEvent(type=EventType.AGENT_ERROR, data={"error": "model exploded"})
        yield AgentEvent(type=EventType.AGENT_DONE, data={"iterations": 1, "tool_calls": 0})


class _InterruptAgentLoop:
    def __init__(self, _config, _llm, _tools, **_kwargs):  # noqa: ANN001
        pass

    async def run(self, _prompt, **_kwargs):  # noqa: ANN001
        raise KeyboardInterrupt
        yield  # pragma: no cover - makes this an async generator

    def __aiter__(self):  # pragma: no cover - unused helper
        return self


@pytest.fixture()
def _patched_cli(monkeypatch):  # noqa: ANN001
    monkeypatch.delenv("THOMAS_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("THOMAS_RUN_LOG", raising=False)
    monkeypatch.setattr(cli_main, "LLMClient", _DummyLLM)
    monkeypatch.setattr(cli_main, "_build_tools", lambda _config: object())
    monkeypatch.setattr(cli_main, "_build_memory", lambda _config: None)
    return monkeypatch


def _invoke_chat(tmp_path: Path, args: list[str]):  # noqa: ANN201
    return CliRunner().invoke(chat_cmd, args, obj={"config": _cfg(tmp_path)})


def _read_records(log_path: Path) -> list[dict]:
    lines = [line for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def test_success_exits_zero_and_writes_valid_run_log(tmp_path, _patched_cli) -> None:  # noqa: ANN001
    _patched_cli.setattr(cli_main, "AgentLoop", _SuccessAgentLoop)
    log_path = tmp_path / "logs" / "run.jsonl"

    result = _invoke_chat(tmp_path, ["hello", "--run-log", str(log_path)])

    assert result.exit_code == EXIT_SUCCESS
    records = _read_records(log_path)
    assert len(records) == 1
    record = records[0]
    assert set(record) >= REQUIRED_RECORD_KEYS
    assert record["outcome"] == "success"
    assert record["exit_code"] == 0
    assert record["prompt"] == "hello"
    assert record["model_profile"] == "local"
    assert record["model"] == "dummy"
    assert record["error"] is None
    assert record["artifacts"] == ["out/report.md"]
    assert isinstance(record["duration_s"], (int, float))
    assert record["duration_s"] >= 0
    assert "T" in record["timestamp"]  # ISO-8601


def test_agent_error_exits_one_with_error_detail(tmp_path, _patched_cli) -> None:  # noqa: ANN001
    _patched_cli.setattr(cli_main, "AgentLoop", _AgentErrorLoop)
    log_path = tmp_path / "run.jsonl"

    result = _invoke_chat(tmp_path, ["hello", "--run-log", str(log_path)])

    assert result.exit_code == EXIT_AGENT_ERROR
    (record,) = _read_records(log_path)
    assert record["outcome"] == "agent_error"
    assert record["exit_code"] == 1
    assert "model exploded" in record["error"]


def test_agent_exception_exits_one(tmp_path, _patched_cli) -> None:  # noqa: ANN001
    class _RaisingLoop:
        def __init__(self, _config, _llm, _tools, **_kwargs):  # noqa: ANN001
            pass

        async def run(self, _prompt, **_kwargs):  # noqa: ANN001
            raise RuntimeError("stream collapsed")
            yield  # pragma: no cover

    _patched_cli.setattr(cli_main, "AgentLoop", _RaisingLoop)
    log_path = tmp_path / "run.jsonl"

    result = _invoke_chat(tmp_path, ["hello", "--run-log", str(log_path)])

    assert result.exit_code == EXIT_AGENT_ERROR
    (record,) = _read_records(log_path)
    assert record["outcome"] == "agent_error"
    assert "stream collapsed" in record["error"]


def test_unknown_model_profile_exits_two(tmp_path, _patched_cli) -> None:  # noqa: ANN001
    _patched_cli.setattr(cli_main, "AgentLoop", _SuccessAgentLoop)
    log_path = tmp_path / "run.jsonl"

    result = _invoke_chat(tmp_path, ["hello", "-m", "no-such-profile", "--run-log", str(log_path)])

    assert result.exit_code == EXIT_USAGE_ERROR
    (record,) = _read_records(log_path)
    assert record["outcome"] == "usage_error"
    assert record["exit_code"] == 2
    assert "no-such-profile" in record["error"]


def test_interrupt_exits_three(tmp_path, _patched_cli) -> None:  # noqa: ANN001
    _patched_cli.setattr(cli_main, "AgentLoop", _InterruptAgentLoop)
    log_path = tmp_path / "run.jsonl"

    result = _invoke_chat(tmp_path, ["hello", "--run-log", str(log_path)])

    assert result.exit_code == EXIT_TIMEOUT
    (record,) = _read_records(log_path)
    assert record["outcome"] == "timeout"
    assert record["exit_code"] == 3


def test_env_var_controls_run_log_path(tmp_path, _patched_cli) -> None:  # noqa: ANN001
    _patched_cli.setattr(cli_main, "AgentLoop", _SuccessAgentLoop)
    log_path = tmp_path / "env-run.jsonl"
    _patched_cli.setenv("THOMAS_RUN_LOG", str(log_path))

    result = _invoke_chat(tmp_path, ["hello"])

    assert result.exit_code == EXIT_SUCCESS
    (record,) = _read_records(log_path)
    assert record["outcome"] == "success"


def test_run_log_write_failure_does_not_change_exit_code(tmp_path, _patched_cli) -> None:  # noqa: ANN001
    _patched_cli.setattr(cli_main, "AgentLoop", _SuccessAgentLoop)
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    bad_log = blocker / "nested" / "run.jsonl"

    result = _invoke_chat(tmp_path, ["hello", "--run-log", str(bad_log)])

    assert result.exit_code == EXIT_SUCCESS
    assert not bad_log.exists()


def test_run_log_write_failure_on_agent_error_keeps_exit_one(tmp_path, _patched_cli) -> None:  # noqa: ANN001
    _patched_cli.setattr(cli_main, "AgentLoop", _AgentErrorLoop)
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    bad_log = blocker / "nested" / "run.jsonl"

    result = _invoke_chat(tmp_path, ["hello", "--run-log", str(bad_log)])

    assert result.exit_code == EXIT_AGENT_ERROR


def test_append_run_record_failure_is_silent_with_stderr_note(tmp_path, capsys) -> None:  # noqa: ANN001
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    bad_path = blocker / "nested" / "run.jsonl"

    ok = append_run_record(bad_path, {"outcome": "success"})

    assert ok is False
    assert "run log" in capsys.readouterr().err


def test_append_run_record_appends_one_line_per_run(tmp_path) -> None:  # noqa: ANN001
    log_path = tmp_path / "run.jsonl"
    assert append_run_record(log_path, {"outcome": "success", "exit_code": 0}) is True
    assert append_run_record(log_path, {"outcome": "agent_error", "exit_code": 1}) is True

    records = _read_records(log_path)
    assert [r["exit_code"] for r in records] == [0, 1]


def test_exit_code_mapping_is_deterministic() -> None:
    assert exit_code_for_outcome("success") == 0
    assert exit_code_for_outcome("agent_error") == 1
    assert exit_code_for_outcome("usage_error") == 2
    assert exit_code_for_outcome("timeout") == 3
    # Unknown outcomes must never read as success.
    assert exit_code_for_outcome("weird") == 1
    assert exit_code_for_outcome("") == 1


def test_resolve_run_log_path_flag_wins_over_env(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    monkeypatch.setenv("THOMAS_RUN_LOG", str(tmp_path / "env.jsonl"))
    assert resolve_run_log_path(str(tmp_path / "flag.jsonl")) == tmp_path / "flag.jsonl"
    assert resolve_run_log_path(None) == tmp_path / "env.jsonl"
    monkeypatch.delenv("THOMAS_RUN_LOG")
    assert resolve_run_log_path(None) is None
