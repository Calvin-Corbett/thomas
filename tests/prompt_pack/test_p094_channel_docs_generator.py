from __future__ import annotations

import argparse
import json

import pytest

from thomas.cli.commands.channel_ops import p094_channel_docs_generator as cli_op
from thomas.marketplace.channels.p094_channel_docs_generator import (
    ChannelDocsGeneratorError,
    ChannelDocsRequest,
    generate_channel_docs,
    render_markdown,
    to_machine_readable,
)


def _required_env_keys() -> list[str]:
    result = generate_channel_docs()
    telegram = next(ch for ch in result.channels if ch.name == "telegram")
    keys = [f.key for f in telegram.config if f.kind == "env" and f.required]
    assert keys, "Expected at least one required env var for Telegram"
    return keys


def test_generate_docs_markdown_contains_telegram() -> None:
    result = generate_channel_docs()
    md = render_markdown(result)

    assert "# Thomas Channels" in md
    assert "## Telegram" in md

    for key in _required_env_keys():
        assert key in md


def test_machine_readable_output_is_stable_shape() -> None:
    result = generate_channel_docs()
    payload = to_machine_readable(result, include_markdown=False)

    assert payload["ok"] is True
    assert isinstance(payload["schema_version"], int)
    assert isinstance(payload["generated_at"], str)
    assert isinstance(payload["channels"], list)
    assert payload["channels"][0]["name"] == "telegram"

    cfg = payload["channels"][0]["config"]
    required_keys = set(_required_env_keys())
    assert required_keys.issubset({item["key"] for item in cfg})


def test_unknown_channel_error_is_deterministic() -> None:
    with pytest.raises(ChannelDocsGeneratorError) as excinfo:
        generate_channel_docs(ChannelDocsRequest(channel_names=("does-not-exist",)))

    err = excinfo.value
    assert err.code == "UNKNOWN_CHANNEL"
    assert "unknown" in err.details


def test_missing_config_error_is_deterministic() -> None:
    required_keys = _required_env_keys()

    with pytest.raises(ChannelDocsGeneratorError) as excinfo:
        generate_channel_docs(
            ChannelDocsRequest(
                channel_names=("telegram",),
                validate_required_config=True,
                env={},
            )
        )

    err = excinfo.value
    assert err.code == "CONFIG_MISSING"
    assert set(required_keys).issubset(set(err.details.get("missing", [])))


def test_cli_argparse_json_success(capsys) -> None:
    parser = argparse.ArgumentParser(prog="thomas channels")
    sub = parser.add_subparsers(dest="cmd", required=True)

    cli_op.register(sub)

    args = parser.parse_args(["docs", "--channel", "telegram", "--json"])
    exit_code = args.func(args)
    assert exit_code == 0

    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["ok"] is True
    assert any(ch["name"] == "telegram" for ch in data["channels"])


def test_cli_argparse_json_error(capsys) -> None:
    parser = argparse.ArgumentParser(prog="thomas channels")
    sub = parser.add_subparsers(dest="cmd", required=True)

    cli_op.register(sub)

    args = parser.parse_args(["docs", "--channel", "nope", "--json"])
    exit_code = args.func(args)
    assert exit_code == 1

    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["ok"] is False
    assert data["error"]["code"] == "UNKNOWN_CHANNEL"


def test_cli_argparse_writes_file(tmp_path) -> None:
    parser = argparse.ArgumentParser(prog="thomas channels")
    sub = parser.add_subparsers(dest="cmd", required=True)

    cli_op.register(sub)

    out_path = tmp_path / "channels.md"
    args = parser.parse_args(["docs", "--channel", "telegram", "--out", str(out_path)])
    exit_code = args.func(args)
    assert exit_code == 0
    assert out_path.exists()
    content = out_path.read_text(encoding="utf-8")
    assert "## Telegram" in content


def test_cli_invalid_out_path_is_caught_in_json_mode(capsys) -> None:
    exit_code = cli_op.run({"out": "   ", "json": True})
    assert exit_code == 1

    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["ok"] is False
    assert data["error"]["code"] == "INVALID_INPUT"
