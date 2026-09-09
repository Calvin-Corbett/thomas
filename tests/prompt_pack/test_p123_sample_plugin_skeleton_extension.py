from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _ensure_repo_on_path():
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


def test_invoke_success_without_config():
    from thomas.plugins import p123_sample_plugin_skeleton_extension as plugin

    wrapper = plugin.invoke(
        {
            "message": "hello",
            "times": 2,
            "uppercase": True,
            "use_config": False,
        }
    )

    assert wrapper["ok"] is True
    assert wrapper["plugin_id"] == plugin.PLUGIN_ID
    result = wrapper["result"]
    assert result["prefix"] == "Thomas"
    assert result["used_config"] is False
    assert result["rendered"] == "Thomas: HELLO HELLO"


def test_invoke_missing_config_error(monkeypatch):
    from thomas.plugins import p123_sample_plugin_skeleton_extension as plugin

    monkeypatch.delenv(plugin.CONFIG_PATH_ENV, raising=False)

    wrapper = plugin.invoke(
        {
            "message": "hi",
            "times": 1,
            "uppercase": False,
            "use_config": True,
        },
        env={},
    )

    assert wrapper["ok"] is False
    assert wrapper["plugin_id"] == plugin.PLUGIN_ID
    assert wrapper["error"]["code"] == "missing_config"


def test_invoke_external_failure_invalid_json(tmp_path: Path):
    from thomas.plugins import p123_sample_plugin_skeleton_extension as plugin

    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text("{not-json}", encoding="utf-8")

    wrapper = plugin.invoke(
        {
            "message": "hi",
            "times": 1,
            "uppercase": False,
            "use_config": True,
        },
        config_path=str(cfg_path),
        env={},
    )

    assert wrapper["ok"] is False
    assert wrapper["error"]["code"] == "external_failure"


def test_invoke_success_with_config(tmp_path: Path):
    from thomas.plugins import p123_sample_plugin_skeleton_extension as plugin

    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps({"prefix": "Custom"}), encoding="utf-8")

    wrapper = plugin.invoke(
        {
            "message": "hi",
            "times": 3,
            "uppercase": False,
            "use_config": True,
        },
        config_path=str(cfg_path),
        env={},
    )

    assert wrapper["ok"] is True
    result = wrapper["result"]
    assert result["prefix"] == "Custom"
    assert result["used_config"] is True
    assert result["rendered"] == "Custom: hi hi hi"


def test_tool_handler_raises_on_failure(monkeypatch):
    from thomas.plugins import p123_sample_plugin_skeleton_extension as plugin

    monkeypatch.delenv(plugin.CONFIG_PATH_ENV, raising=False)

    with pytest.raises(plugin.SamplePluginError) as e:
        plugin.tool_handler({"message": "x", "times": 1, "uppercase": False, "use_config": True})

    assert e.value.code == "missing_config"


def test_cli_json_success():
    from typer.testing import CliRunner

    from thomas.cli.commands.plugins import p123_sample_plugin_skeleton_extension as cli

    runner = CliRunner()
    result = runner.invoke(cli.app, ["hello", "--times", "2", "--uppercase", "--json"])
    assert result.exit_code == 0, result.output

    payload = json.loads(result.output.strip())
    assert payload["ok"] is True
    assert payload["result"]["rendered"] == "Thomas: HELLO HELLO"


def test_cli_json_failure(monkeypatch):
    from typer.testing import CliRunner

    from thomas.cli.commands.plugins import p123_sample_plugin_skeleton_extension as cli
    from thomas.plugins import p123_sample_plugin_skeleton_extension as plugin

    monkeypatch.delenv(plugin.CONFIG_PATH_ENV, raising=False)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["hello", "--use-config", "--json"])
    assert result.exit_code == 1

    payload = json.loads(result.output.strip())
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_config"


def test_cli_schema():
    from typer.testing import CliRunner

    from thomas.cli.commands.plugins import p123_sample_plugin_skeleton_extension as cli

    runner = CliRunner()
    result = runner.invoke(cli.app, ["--schema"])
    assert result.exit_code == 0

    payload = json.loads(result.output.strip())
    assert payload["plugin_id"] == "p123_sample_plugin_skeleton_extension"
    assert payload["tool_name"] == "sample_plugin_skeleton_extension"
    assert "request_schema" in payload
    assert "response_schema" in payload
