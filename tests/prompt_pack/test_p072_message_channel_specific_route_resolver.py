import json
from pathlib import Path

import pytest

from thomas.cli.commands.messages.p072_message_channel_specific_route_resolver import run as cli_run
from thomas.messages.p072_message_channel_specific_route_resolver import (
    InvalidRouteConfigError,
    InvalidRouteInputError,
    MessagePeer,
    MessageRouteContext,
    parse_routing_config,
    resolve_message_route,
)


def _config_dict() -> dict:
    return {
        "assistants": [
            {"id": "main", "default": True},
            {"id": "support"},
            {"id": "work"},
        ],
        "routing_rules": [
            # Most specific: peer binding
            {
                "assistant_id": "support",
                "match": {
                    "channel": "telegram",
                    "peer": {"kind": "group", "id": "-100123"},
                },
            },
            # Parent peer binding (thread inheritance)
            {
                "assistant_id": "work",
                "match": {
                    "channel": "discord",
                    "peer": {"kind": "channel", "id": "123"},
                },
            },
            # Discord: guild+roles
            {
                "assistant_id": "support",
                "match": {
                    "channel": "discord",
                    "guildId": "G1",
                    "roles": ["R1", "R2"],
                },
            },
            # Discord: guild only
            {
                "assistant_id": "work",
                "match": {
                    "channel": "discord",
                    "guild_id": "G2",
                },
            },
            # Slack: team
            {
                "assistant_id": "work",
                "match": {
                    "channel": "slack",
                    "teamId": "T123",
                },
            },
            # Account match
            {
                "assistant_id": "support",
                "match": {
                    "channel": "whatsapp",
                    "accountId": "biz",
                },
            },
            # Channel wildcard
            {
                "assistant_id": "work",
                "match": {
                    "channel": "whatsapp",
                    "accountId": "*",
                },
            },
            # Channel-only match (no account specified)
            {
                "assistant_id": "support",
                "match": {
                    "channel": "signal",
                },
            },
        ],
    }


def test_peer_match_wins() -> None:
    config = parse_routing_config(_config_dict())
    ctx = MessageRouteContext(
        channel="telegram",
        peer=MessagePeer(kind="group", id="-100123"),
    )
    res = resolve_message_route(ctx, config)
    assert res.assistant_id == "support"
    assert res.tier == "peer"
    assert res.rule_index == 0


def test_parent_peer_match_for_thread() -> None:
    config = parse_routing_config(_config_dict())
    ctx = MessageRouteContext(
        channel="discord",
        peer=MessagePeer(kind="channel", id="123:thread:999"),
        parent_peer=MessagePeer(kind="channel", id="123"),
    )
    res = resolve_message_route(ctx, config)
    assert res.assistant_id == "work"
    assert res.tier == "parent_peer"
    assert res.rule_index == 1


def test_guild_roles_match() -> None:
    config = parse_routing_config(_config_dict())
    ctx = MessageRouteContext(
        channel="discord",
        guild_id="G1",
        roles=("R1", "R2", "R9"),
    )
    res = resolve_message_route(ctx, config)
    assert res.assistant_id == "support"
    assert res.tier == "guild_roles"
    assert res.rule_index == 2


def test_guild_match_fallback() -> None:
    config = parse_routing_config(_config_dict())
    ctx = MessageRouteContext(
        channel="discord",
        guild_id="G2",
    )
    res = resolve_message_route(ctx, config)
    assert res.assistant_id == "work"
    assert res.tier == "guild"


def test_team_match() -> None:
    config = parse_routing_config(_config_dict())
    ctx = MessageRouteContext(channel="slack", team_id="T123")
    res = resolve_message_route(ctx, config)
    assert res.assistant_id == "work"
    assert res.tier == "team"


def test_account_match_and_wildcard() -> None:
    config = parse_routing_config(_config_dict())

    biz_ctx = MessageRouteContext(channel="whatsapp", account_id="biz")
    res_biz = resolve_message_route(biz_ctx, config)
    assert res_biz.assistant_id == "support"
    assert res_biz.tier == "account"

    personal_ctx = MessageRouteContext(channel="whatsapp", account_id="personal")
    res_personal = resolve_message_route(personal_ctx, config)
    assert res_personal.assistant_id == "work"
    assert res_personal.tier == "channel"


def test_default_fallback() -> None:
    config = parse_routing_config(_config_dict())
    ctx = MessageRouteContext(channel="unknown-channel")
    res = resolve_message_route(ctx, config)
    assert res.assistant_id == "main"
    assert res.tier == "default"


def test_parse_invalid_config_raises() -> None:
    with pytest.raises(InvalidRouteConfigError):
        parse_routing_config({"assistants": []})

    with pytest.raises(InvalidRouteConfigError):
        parse_routing_config(
            {
                "assistants": [{"id": "main"}],
                "routing_rules": [
                    {"assistant_id": "missing", "match": {"channel": "slack"}},
                ],
            }
        )


def test_invalid_context_raises() -> None:
    config = parse_routing_config(_config_dict())
    with pytest.raises(InvalidRouteInputError):
        resolve_message_route(  # type: ignore[arg-type]
            {"channel": "slack"},
            config,
        )


def test_cli_json_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = tmp_path / "routing.json"
    config_path.write_text(json.dumps(_config_dict()), encoding="utf-8")

    code = cli_run(
        [
            "--config",
            str(config_path),
            "--json",
            "--channel",
            "telegram",
            "--peer-kind",
            "group",
            "--peer-id",
            "-100123",
        ]
    )
    assert code == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["resolution"]["assistant_id"] == "support"


def test_cli_json_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config_path = tmp_path / "routing.json"
    config_path.write_text(json.dumps(_config_dict()), encoding="utf-8")

    code = cli_run(["--config", str(config_path), "--json"])  # missing channel
    assert code == 2
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_input"
