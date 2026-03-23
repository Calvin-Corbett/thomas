from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from thomas.cli.commands.channel_ops.p082_channel_logs_command import _run_from_args
from thomas.marketplace.channels.p082_channel_logs_command import (
    ChannelLogsRequest,
    InvalidInputError,
    MissingConfigError,
    get_channel_logs,
)


def _write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_get_channel_logs_all_filters_to_channel_subsystem(tmp_path: Path) -> None:
    log = tmp_path / "thomas-2026-02-20.log"

    lines = [
        json.dumps(
            {
                "ts": "2026-02-20T00:00:00Z",
                "level": "info",
                "subsystem": "channels/telegram/inbound",
                "msg": "Received hello",
                "provider": "telegram",
            }
        ),
        json.dumps(
            {
                "ts": "2026-02-20T00:00:01Z",
                "level": "info",
                "subsystem": "channels/discord/inbound",
                "msg": "Received hi",
                "provider": "discord",
            }
        ),
        json.dumps(
            {
                "ts": "2026-02-20T00:00:02Z",
                "level": "error",
                "subsystem": "gateway",
                "msg": "Gateway crash",
            }
        ),
        "[channels/telegram] outbound message",
        "random noise",
    ]

    _write_lines(log, lines)

    result = get_channel_logs(ChannelLogsRequest(channel="all", lines=50, log_file=log))

    assert result.channel == "all"
    assert Path(result.log_file) == log
    # Only channel-related records should survive.
    assert result.lines_returned == 3
    assert result.entries[0].parsed is not None
    assert result.entries[1].parsed is not None
    assert result.entries[2].parsed is None


def test_get_channel_logs_filters_by_provider(tmp_path: Path) -> None:
    log = tmp_path / "thomas-2026-02-20.log"

    lines = [
        json.dumps(
            {
                "ts": "2026-02-20T00:00:00Z",
                "level": "info",
                "subsystem": "channels/telegram/inbound",
                "msg": "Received hello",
                "provider": "telegram",
            }
        ),
        json.dumps(
            {
                "ts": "2026-02-20T00:00:01Z",
                "level": "info",
                "subsystem": "channels/discord/inbound",
                "msg": "Received hi",
                "provider": "discord",
            }
        ),
        "[channels/telegram] outbound message",
    ]

    _write_lines(log, lines)

    result = get_channel_logs(ChannelLogsRequest(channel="telegram", lines=50, log_file=log))

    assert result.channel == "telegram"
    assert result.lines_returned == 2
    assert "telegram" in result.entries[0].raw.lower()
    assert "telegram" in result.entries[1].raw.lower()


def test_get_channel_logs_limits_to_last_n_matching(tmp_path: Path) -> None:
    log = tmp_path / "thomas-2026-02-20.log"

    lines = [
        "[channels/telegram] older",
        "[channels/telegram] newer",
        "[channels/telegram] newest",
    ]

    _write_lines(log, lines)

    result = get_channel_logs(ChannelLogsRequest(channel="telegram", lines=1, log_file=log))

    assert result.lines_returned == 1
    assert result.entries[0].raw.endswith("newest")


def test_get_channel_logs_invalid_lines() -> None:
    with pytest.raises(InvalidInputError) as ei:
        get_channel_logs(ChannelLogsRequest(channel="all", lines=0, log_file=Path("/tmp/nope")))
    assert ei.value.code == "invalid_input"


def test_get_channel_logs_missing_log_file(tmp_path: Path) -> None:
    missing = tmp_path / "missing.log"
    with pytest.raises(MissingConfigError) as ei:
        get_channel_logs(ChannelLogsRequest(channel="all", lines=5, log_file=missing))
    assert ei.value.code == "missing_config"


def test_cli_json_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    log = tmp_path / "thomas-2026-02-20.log"
    _write_lines(
        log,
        [
            json.dumps(
                {
                    "ts": "2026-02-20T00:00:00Z",
                    "level": "info",
                    "subsystem": "channels/telegram/inbound",
                    "msg": "Received hello",
                    "provider": "telegram",
                }
            )
        ],
    )

    # Force resolution without needing Thomas config.
    monkeypatch.setenv("THOMAS_LOG_FILE", str(log))

    rc = _run_from_args(argparse.Namespace(channel="telegram", lines=10, json=True))
    assert rc == 0

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["channel"] == "telegram"
    assert payload["lines_returned"] == 1


def test_cli_json_error(capsys: pytest.CaptureFixture[str]) -> None:
    rc = _run_from_args(argparse.Namespace(channel="all", lines=0, json=True))
    assert rc == 1

    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_input"
