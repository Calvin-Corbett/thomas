from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import click
from click.testing import CliRunner

from thomas.cli.parity_compat import register_compat_commands


def _build_root_cli() -> click.Group:
    @click.group()
    @click.pass_context
    def root(ctx: click.Context) -> None:
        _ = ctx

    return root


def _fake_config(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        memory=SimpleNamespace(root_path=tmp_path),
        server=SimpleNamespace(access_mode="local", api_token=""),
        tools=SimpleNamespace(allow_shell=False, sandbox_path=tmp_path, max_file_size=5_000_000),
        models={"local": {"model": "dummy"}},
        default_model="local",
    )


def test_plugins_command_module_importable() -> None:
    from thomas.cli.commands.plugins import p113_plugin_tool_provider_injection as mod

    assert hasattr(mod, "COMMAND_NAME")
    assert mod.COMMAND_NAME == "p113-tool-provider-injection"


def test_claude_style_alias_commands_are_registered() -> None:
    root = _build_root_cli()
    register_compat_commands(root)
    for name in ("plugin", "mcp", "install", "setup-token"):
        assert name in root.commands


def test_install_compat_json_contract(tmp_path: Path) -> None:
    root = _build_root_cli()
    register_compat_commands(root)
    runner = CliRunner()
    cfg = _fake_config(tmp_path)

    res = runner.invoke(root, ["install", "--compat-json"], obj={"config": cfg})
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["command"] == "install"
    assert payload["compatibility"] == "mapped"
    assert "setup" in payload["equivalents"]


def test_mcp_registry_add_get_remove_roundtrip(tmp_path: Path) -> None:
    root = _build_root_cli()
    register_compat_commands(root)
    runner = CliRunner()
    cfg = _fake_config(tmp_path)

    res_add = runner.invoke(
        root,
        ["mcp", "add", "demo", "--command", "uvx", "--arg", "mcp-server-time", "--json"],
        obj={"config": cfg},
    )
    assert res_add.exit_code == 0, res_add.output
    add_payload = json.loads(res_add.output)
    assert add_payload["ok"] is True
    assert add_payload["server"]["name"] == "demo"
    assert add_payload["server"]["transport"] == "stdio"

    res_get = runner.invoke(root, ["mcp", "get", "demo", "--json"], obj={"config": cfg})
    assert res_get.exit_code == 0, res_get.output
    get_payload = json.loads(res_get.output)
    assert get_payload["name"] == "demo"
    assert get_payload["command"] == "uvx"

    res_remove = runner.invoke(root, ["mcp", "remove", "demo", "--json"], obj={"config": cfg})
    assert res_remove.exit_code == 0, res_remove.output
    remove_payload = json.loads(res_remove.output)
    assert remove_payload["ok"] is True


def test_setup_token_persists_masked_metadata_only(tmp_path: Path, monkeypatch) -> None:
    root = _build_root_cli()
    register_compat_commands(root)
    runner = CliRunner()
    cfg = _fake_config(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    token = "sk-ant-abcdef1234567890"
    res = runner.invoke(
        root,
        ["setup-token", "--provider", "anthropic", "--token", token, "--json"],
        obj={"config": cfg},
    )
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["ok"] is True
    assert payload["provider"] == "anthropic"
    assert payload["env_key"] == "ANTHROPIC_API_KEY"

    state_path = Path(str(payload["state_file"]))
    assert state_path.exists()
    raw = state_path.read_text(encoding="utf-8")
    assert token not in raw
    saved = json.loads(raw)
    row = saved["tokens"]["anthropic"]
    assert row["token_sha256"]
    assert "..." in row["token_masked"]
