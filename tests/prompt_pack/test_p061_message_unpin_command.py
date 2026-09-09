from __future__ import annotations

import json

import pytest


def test_message_unpin_success_direct_client() -> None:
    from thomas.messages import p061_message_unpin_command as mod

    calls: list[tuple[str, str]] = []

    class FakeClient:
        def unpin_message(self, *, channel_id: str, message_id: str) -> None:
            calls.append((channel_id, message_id))

    out = mod.execute(mod.MessageUnpinInput(channel_id="C123", message_id="1712345678.000100"), client=FakeClient())

    assert out.unpinned is True
    assert out.channel_id == "C123"
    assert out.message_id == "1712345678.000100"
    assert calls == [("C123", "1712345678.000100")]


def test_message_unpin_coerces_slack_digit_ts_when_channel_looks_slackish() -> None:
    from thomas.messages import p061_message_unpin_command as mod

    class FakeClient:
        def unpin_message(self, *, channel_id: str, message_id: str) -> None:
            assert channel_id == "C123"
            assert message_id == "1712345678.000100"

    out = mod.execute(mod.MessageUnpinInput(channel_id="C123", message_id="1712345678000100"), client=FakeClient())
    assert out.message_id == "1712345678.000100"


def test_message_unpin_parses_slack_permalink_url() -> None:
    from thomas.messages import p061_message_unpin_command as mod

    class FakeClient:
        def unpin_message(self, *, channel_id: str, message_id: str) -> None:
            assert channel_id == "C123"
            assert message_id == "1712345678.000100"

    url = "https://example.slack.com/archives/C123/p1712345678000100"
    out = mod.execute(mod.MessageUnpinInput(message_url=url), client=FakeClient())
    assert out.channel_id == "C123"
    assert out.message_id == "1712345678.000100"


def test_message_unpin_parses_discord_message_url() -> None:
    from thomas.messages import p061_message_unpin_command as mod

    class FakeClient:
        def unpin_message(self, *, channel_id: str, message_id: str) -> None:
            assert channel_id == "222222222222222222"
            assert message_id == "333333333333333333"

    url = "https://discord.com/channels/111111111111111111/222222222222222222/333333333333333333"
    out = mod.execute(mod.MessageUnpinInput(message_url=url), client=FakeClient())
    assert out.channel_id == "222222222222222222"
    assert out.message_id == "333333333333333333"


def test_message_unpin_invalid_input() -> None:
    from thomas.messages import p061_message_unpin_command as mod

    with pytest.raises(mod.MessageUnpinInputError) as excinfo:
        mod.execute(mod.MessageUnpinInput(channel_id=None, message_id=None, message_url=None), client=object())

    assert "channel_id and message_id" in str(excinfo.value)
    assert excinfo.value.code == "message_unpin.invalid_input"


def test_message_unpin_missing_config_when_client_unresolvable(monkeypatch: pytest.MonkeyPatch) -> None:
    from thomas.messages import p061_message_unpin_command as mod

    monkeypatch.setattr(
        mod,
        "_resolve_messages_client",
        lambda ctx: (_ for _ in ()).throw(mod.MessageUnpinConfigError("No messaging client")),
    )

    with pytest.raises(mod.MessageUnpinConfigError) as excinfo:
        mod.execute(mod.MessageUnpinInput(channel_id="C1", message_id="M1"))

    assert excinfo.value.code == "message_unpin.missing_config"


def test_message_unpin_external_failure() -> None:
    from thomas.messages import p061_message_unpin_command as mod

    class BoomClient:
        def unpin_message(self, *, channel_id: str, message_id: str) -> None:
            raise RuntimeError("boom")

    with pytest.raises(mod.MessageUnpinExternalError) as excinfo:
        mod.execute(mod.MessageUnpinInput(channel_id="C1", message_id="M1"), client=BoomClient())

    assert excinfo.value.code == "message_unpin.external_failure"
    assert "unpin_message" in str(excinfo.value)


def test_cli_json_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from click.testing import CliRunner

    from thomas.cli.commands.messages import p061_message_unpin_command as cli_mod

    class FakeClient:
        def unpin_message(self, *, channel_id: str, message_id: str) -> None:
            return None

    monkeypatch.setattr(cli_mod, "_resolve_client_for_cli", lambda: FakeClient())

    runner = CliRunner()
    result = runner.invoke(cli_mod.click_command, ["unpin", "--channel", "C123", "--message", "M1", "--json"])
    assert result.exit_code == 0, result.stdout

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["result"]["channel_id"] == "C123"
    assert payload["result"]["message_id"] == "M1"


def test_cli_json_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from click.testing import CliRunner

    from thomas.cli.commands.messages import p061_message_unpin_command as cli_mod

    class BoomClient:
        def unpin_message(self, *, channel_id: str, message_id: str) -> None:
            raise RuntimeError("boom")

    monkeypatch.setattr(cli_mod, "_resolve_client_for_cli", lambda: BoomClient())

    runner = CliRunner()
    result = runner.invoke(cli_mod.click_command, ["unpin", "--channel", "C123", "--message", "M1", "--json"])
    assert result.exit_code == 1

    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "message_unpin.external_failure"
