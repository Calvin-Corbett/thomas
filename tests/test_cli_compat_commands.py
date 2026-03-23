from __future__ import annotations

import json

import click
from click.testing import CliRunner

from thomas.cli.compat_core_help import agent_cmd
from thomas.cli.compat_mcp import install_cmd, mcp_serve, register_compat_commands
from thomas.cli.compat_skills import plugin_cmd, qr_cmd
from thomas.cli.compat_tools import acp_client, clawbot_chat, daemon_install


def test_agent_help_does_not_advertise_unsupported_token_economy() -> None:
    result = CliRunner().invoke(agent_cmd, ["--help"])
    assert result.exit_code == 0
    assert "--token-economy" not in result.output


def test_register_compat_commands_syncs_help_topics_for_root_commands() -> None:
    @click.group()
    def root() -> None:
        pass

    @root.command("release")
    def release_cmd() -> None:
        pass

    register_compat_commands(root)

    help_group = root.commands["help"]
    assert isinstance(help_group, click.Group)
    assert "release" in help_group.commands


def test_install_compat_json_describes_guided_setup_flow() -> None:
    result = CliRunner().invoke(install_cmd, ["--compat-json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "guided setup flow" in str(payload.get("note") or "").lower()


def test_acp_client_preserves_chat_options(monkeypatch) -> None:
    calls: list[tuple[list[str], tuple[object, ...]]] = []

    def _fake_forward(ctx, base_args, extra_args):
        calls.append((list(base_args), tuple(extra_args)))

    monkeypatch.setattr("thomas.cli.compat_tools._forward_passthrough", _fake_forward)
    result = CliRunner().invoke(acp_client, ["--model", "local", "prompt"])
    assert result.exit_code == 0
    assert calls == [(["chat"], ("--model", "local", "prompt"))]


def test_clawbot_chat_joins_plain_prompt_tokens(monkeypatch) -> None:
    calls: list[tuple[list[str], tuple[object, ...]]] = []

    def _fake_forward(ctx, base_args, extra_args):
        calls.append((list(base_args), tuple(extra_args)))

    monkeypatch.setattr("thomas.cli.compat_tools._forward_passthrough", _fake_forward)
    result = CliRunner().invoke(clawbot_chat, ["hello", "world"])
    assert result.exit_code == 0
    assert calls == [(["chat", "hello world"], ())]


def test_daemon_install_help_forwards_to_gateway_install(monkeypatch) -> None:
    calls: list[tuple[list[str], tuple[object, ...]]] = []

    def _fake_forward(ctx, base_args, extra_args):
        calls.append((list(base_args), tuple(extra_args)))

    monkeypatch.setattr("thomas.cli.compat_tools._forward_passthrough", _fake_forward)
    result = CliRunner().invoke(daemon_install, ["--help"])
    assert result.exit_code == 0
    assert calls == [(["gateway", "install"], ("--help",))]


def test_plugin_help_forwards_to_plugins_help(monkeypatch) -> None:
    calls: list[tuple[list[str], tuple[object, ...]]] = []

    def _fake_forward(ctx, base_args, extra_args):
        calls.append((list(base_args), tuple(extra_args)))

    monkeypatch.setattr("thomas.cli.compat_skills._forward_passthrough", _fake_forward)
    result = CliRunner().invoke(plugin_cmd, ["--help"])
    assert result.exit_code == 0
    assert calls == [(["plugins"], ("--help",))]


def test_qr_help_does_not_inject_generated_name(monkeypatch) -> None:
    calls: list[tuple[list[str], tuple[object, ...]]] = []

    def _fake_forward(ctx, base_args, extra_args):
        calls.append((list(base_args), tuple(extra_args)))

    monkeypatch.setattr("thomas.cli.compat_skills._forward_passthrough", _fake_forward)
    result = CliRunner().invoke(qr_cmd, ["--help"])
    assert result.exit_code == 0
    assert calls == [(["devices", "pair"], ("--help",))]


def test_mcp_serve_help_forwards_to_gateway_run(monkeypatch) -> None:
    calls: list[tuple[list[str], tuple[object, ...]]] = []

    def _fake_forward(ctx, base_args, extra_args):
        calls.append((list(base_args), tuple(extra_args)))

    monkeypatch.setattr("thomas.cli.compat_mcp._forward_passthrough", _fake_forward)
    result = CliRunner().invoke(mcp_serve, ["--help"])
    assert result.exit_code == 0
    assert calls == [(["gateway", "run"], ("--help",))]
