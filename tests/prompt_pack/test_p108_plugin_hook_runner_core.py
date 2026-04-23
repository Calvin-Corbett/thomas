from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from thomas.cli.commands.plugins.p108_plugin_hook_runner_core import app as cli_app
from thomas.plugins.p108_plugin_hook_runner_core import HookRunRequest, HookRunnerError, run_hook


class _OkPlugin:
    name = "ok"

    def on_demo(self, payload: dict[str, object]) -> dict[str, object]:
        return {"seen": payload.get("x"), "plugin": self.name}


class _AltOkPlugin:
    # Uses a different discovery pattern: method name equals hook.
    id = "alt"

    def demo(self, ctx: dict[str, object]) -> str:
        payload = ctx.get("payload") if isinstance(ctx, dict) else {}
        if isinstance(payload, dict):
            return f"alt:{payload.get('x')}"
        return "alt"


class _FailPlugin:
    name = "boom"

    def on_demo(self, payload: dict[str, object]) -> None:
        raise RuntimeError("kaboom")


def test_core_runs_hook_across_plugins_success() -> None:
    req = HookRunRequest(hook="demo", payload={"x": 123})
    resp = run_hook(req, plugins=[_OkPlugin(), _AltOkPlugin()])

    assert resp.ok is True
    assert resp.hook == "demo"
    assert [r.plugin for r in resp.results] == ["ok", "alt"]
    assert [r.status for r in resp.results] == ["ok", "ok"]
    assert resp.results[0].output == {"seen": 123, "plugin": "ok"}
    assert resp.results[1].output == "alt:123"


def test_core_reports_plugin_failure_deterministically() -> None:
    req = HookRunRequest(hook="demo", payload={"x": 1}, continue_on_error=True)
    resp = run_hook(req, plugins=[_OkPlugin(), _FailPlugin()])

    assert resp.ok is False
    assert resp.results[0].status == "ok"
    assert resp.results[1].status == "error"
    assert resp.results[1].error is not None
    assert resp.results[1].error.code == "hook_failed"
    assert resp.results[1].error.details["exception_type"] == "RuntimeError"


def test_core_missing_config_is_error() -> None:
    req = HookRunRequest(hook="demo")
    with pytest.raises(HookRunnerError) as exc:
        run_hook(req)
    assert exc.value.code == "missing_config"


def test_cli_json_success_with_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Create a temporary plugin module that can be imported.
    module_path = tmp_path / "tmp_p108_plugin.py"
    module_path.write_text(
        "\n".join(
            [
                "class ExamplePlugin:",
                "    name = 'example'",
                "    def on_demo(self, payload):",
                "        return {'ok': True, 'x': payload.get('x')} ",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    config_path = tmp_path / "thomas_plugins.json"
    config_path.write_text(
        json.dumps({"plugins": ["tmp_p108_plugin:ExamplePlugin"]}),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        cli_app,
        [
            "run-hook",
            "demo",
            "--payload",
            "{\"x\": 7}",
            "--config",
            str(config_path),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    doc = json.loads(result.output)
    assert doc["ok"] is True
    assert doc["hook"] == "demo"
    assert doc["results"][0]["plugin"] == "example"
    assert doc["results"][0]["output"] == {"ok": True, "x": 7}


def test_cli_json_error_for_missing_config(tmp_path: Path) -> None:
    runner = CliRunner()
    missing = tmp_path / "nope.json"
    result = runner.invoke(
        cli_app,
        [
            "run-hook",
            "demo",
            "--config",
            str(missing),
            "--json",
        ],
    )

    assert result.exit_code == 2
    doc = json.loads(result.output)
    assert doc["ok"] is False
    assert doc["error"]["code"] == "missing_config"
