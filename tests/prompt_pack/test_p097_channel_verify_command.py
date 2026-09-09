from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

from thomas.cli.commands.channels import app as channels_app


def _fake_config(root: Path) -> SimpleNamespace:
    return SimpleNamespace(memory=SimpleNamespace(root_path=root))


def test_channels_verify_command_json_success(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(
        channels_app,
        ["verify", "--provider", "telegram", "--json"],
        obj={"config": _fake_config(tmp_path)},
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["summary"]["providers_total"] == 1
    assert payload["providers"][0]["provider"] == "telegram"
    assert payload["providers"][0]["overall_ok"] is True
