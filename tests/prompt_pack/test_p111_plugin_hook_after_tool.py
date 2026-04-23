import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from thomas.cli.commands.plugins.p111_plugin_hook_after_tool import COMMAND
from thomas.plugins.p111_plugin_hook_after_tool import (
    AfterToolHookRequest,
    ConfigError,
    ExternalFailureError,
    run_after_tool_hook,
)


def test_runner_success_records_event_and_writes_log(tmp_path: Path) -> None:
    def tool(inp):
        return {"seen": inp}

    log_path = tmp_path / "audit.jsonl"
    resp = run_after_tool_hook(
        AfterToolHookRequest(
            tool_name="unit_test_tool",
            tool_input={"a": 1},
            tool_callable=tool,
            config={"log_path": str(log_path)},
        )
    )

    assert resp.ok is True
    assert resp.success is True
    assert resp.tool_output == {"seen": {"a": 1}}
    assert len(resp.events) == 1

    event = resp.events[0]
    assert event.tool.name == "unit_test_tool"
    assert event.tool.input == {"a": 1}
    assert event.outcome.ok is True
    assert event.outcome.output == {"seen": {"a": 1}}
    assert event.outcome.error is None

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["tool"]["name"] == "unit_test_tool"
    assert rec["outcome"]["ok"] is True


def test_runner_failure_tool_error_is_returned() -> None:
    def tool(_inp):
        raise RuntimeError("boom")

    resp = run_after_tool_hook(AfterToolHookRequest(tool_name="unit_test_fail", tool_input={"x": 1}, tool_callable=tool))

    assert resp.ok is False
    assert resp.success is False
    assert resp.tool_output is None
    assert resp.error is not None
    assert resp.error.code == "tool_failed"
    assert "RuntimeError" in resp.error.message
    assert len(resp.events) == 1
    assert resp.events[0].outcome.ok is False


def test_runner_missing_config_file_raises_deterministic_error(tmp_path: Path) -> None:
    missing = tmp_path / "nope.json"
    assert not missing.exists()

    with pytest.raises(ConfigError) as ei:
        run_after_tool_hook(
            AfterToolHookRequest(
                tool_name="echo",
                tool_input={"x": 1},
                config_path=str(missing),
                tool_callable=lambda x: x,
            )
        )

    assert ei.value.info.code == "config_not_found"


def test_runner_log_write_failure_is_deterministic(tmp_path: Path) -> None:
    # Point log_path at a directory to force a deterministic failure.
    log_dir = tmp_path / "audit_dir"
    log_dir.mkdir()

    with pytest.raises(ExternalFailureError) as ei:
        run_after_tool_hook(
            AfterToolHookRequest(
                tool_name="unit_test_tool",
                tool_input={"x": 1},
                tool_callable=lambda x: x,
                config={"log_path": str(log_dir)},
            )
        )

    assert ei.value.info.code == "external_failure"


def test_cli_json_success() -> None:
    runner = CliRunner()
    result = runner.invoke(COMMAND, ["--tool", "echo", "--input", '{"x": 1}', "--json"])
    assert result.exit_code == 0

    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["success"] is True
    assert isinstance(payload["events"], list)
    assert payload["events"]


def test_cli_json_invalid_input() -> None:
    runner = CliRunner()
    result = runner.invoke(COMMAND, ["--tool", "echo", "--input", "{not-json", "--json"])
    assert result.exit_code != 0

    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["success"] is False
    assert payload["error"]["code"] == "invalid_json"


def test_cli_json_schema() -> None:
    runner = CliRunner()
    result = runner.invoke(COMMAND, ["--json-schema"])
    assert result.exit_code == 0
    schema = json.loads(result.output)
    assert schema["title"] == "AfterToolHookResponse"
