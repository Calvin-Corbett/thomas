from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from thomas.cli.main import cli


def _write_min_config(path: Path) -> Path:
    cfg = path / "thomas.toml"
    runtime_root = (path / "runtime").as_posix()
    cfg.write_text(
        f"""
default_model = "local"

[memory]
root = "{runtime_root}"

[models.local]
provider = "ollama"
base_url = "http://127.0.0.1:11434/v1"
model = "qwen2.5-coder:7b"
""".strip(),
        encoding="utf-8",
    )
    return cfg


def test_cli_release_contracts_check_json(tmp_path: Path) -> None:
    cfg = _write_min_config(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["-c", str(cfg), "release-contracts", "check", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert int(payload["summary"]["contract_count"]) >= 1


def test_cli_security_audit_json(tmp_path: Path) -> None:
    cfg = _write_min_config(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["-c", str(cfg), "security", "audit", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["command"] == "security"
    assert payload["action"] == "audit"
    assert "summary" in payload
    assert int(payload["summary"]["check_count"]) >= 4


def test_cli_plugins_certify_and_update_json(tmp_path: Path) -> None:
    cfg = _write_min_config(tmp_path)
    runtime_root = tmp_path / "runtime" / ".thomas" / "cli"
    runtime_root.mkdir(parents=True, exist_ok=True)
    (runtime_root / "plugins.json").write_text(
        json.dumps(
            {
                "plugins": [
                    {
                        "name": "pack-alerts-slack-detect",
                        "path": "",
                        "enabled": True,
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    runner = CliRunner()

    certify = runner.invoke(cli, ["-c", str(cfg), "plugins", "certify", "--json"])
    assert certify.exit_code == 0, certify.output
    certify_payload = json.loads(certify.output)
    assert int(certify_payload["summary"]["total"]) >= 1
    assert "required_capabilities" in certify_payload

    update = runner.invoke(cli, ["-c", str(cfg), "plugins", "update", "--json"])
    assert update.exit_code == 0, update.output
    update_payload = json.loads(update.output)
    assert update_payload["ok"] is True
    assert int(update_payload["summary"]["total"]) == 1
