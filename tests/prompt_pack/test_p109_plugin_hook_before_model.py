import json

import pytest
from typer.testing import CliRunner

from thomas.cli.commands.plugins.p109_plugin_hook_before_model import app as cli_app
from thomas.plugins.p109_plugin_hook_before_model import BeforeModelError, apply_before_model_hook, hook_json_schema


def test_before_model_hook_success_injects_system_message():
    out = apply_before_model_hook(
        {"messages": [{"role": "user", "content": "hi"}]},
        config={"inject_system": "You are a helpful assistant."},
    )

    payload = out.to_dict()
    assert payload["ok"] is True
    messages = payload["result"]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "You are a helpful assistant."
    assert messages[1]["role"] == "user"


def test_before_model_hook_invalid_input_is_deterministic_error():
    with pytest.raises(BeforeModelError) as ei:
        apply_before_model_hook(
            {"messages": [{"role": "user"}]},
            config={"inject_system": "SYS"},
        )

    assert ei.value.code == "INVALID_INPUT"


def test_before_model_hook_missing_config_is_deterministic_error():
    with pytest.raises(BeforeModelError) as ei:
        apply_before_model_hook({"messages": [{"role": "user", "content": "hi"}]}, config={})

    assert ei.value.code == "MISSING_CONFIG"


def test_before_model_hook_external_failure_is_deterministic_error():
    with pytest.raises(BeforeModelError) as ei:
        apply_before_model_hook(
            {"messages": [{"role": "user", "content": "hi"}]},
            config={"inject_system": "SYS", "simulate_external_failure": True},
        )

    assert ei.value.code == "EXTERNAL_FAILURE"


def test_cli_json_success():
    runner = CliRunner()
    result = runner.invoke(
        cli_app,
        [
            "run",
            "--request",
            json.dumps({"messages": [{"role": "user", "content": "hi"}]}),
            "--config",
            json.dumps({"inject_system": "SYS"}),
            "--json",
        ],
    )

    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert data["result"]["messages"][0]["role"] == "system"


def test_cli_json_failure_is_machine_readable_and_nonzero_exit():
    runner = CliRunner()
    result = runner.invoke(
        cli_app,
        [
            "run",
            "--request",
            json.dumps({"messages": [{"role": "user", "content": "hi"}]}),
            "--config",
            json.dumps({}),
            "--json",
        ],
    )

    assert result.exit_code != 0
    data = json.loads(result.stdout)
    assert data["ok"] is False
    assert data["error"]["code"] == "MISSING_CONFIG"


def test_schema_is_stable_and_machine_readable():
    sch = hook_json_schema()
    assert sch["type"] == "object"
    assert (
        "request" in sch.get("properties", {})
        and "config" in sch.get("properties", {})
        and "result" in sch.get("properties", {})
    )

    runner = CliRunner()
    result = runner.invoke(cli_app, ["schema", "--json"])
    assert result.exit_code == 0
    cli_sch = json.loads(result.stdout)
    assert cli_sch["type"] == "object"
