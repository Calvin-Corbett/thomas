import json

import pytest
from click.testing import CliRunner

from thomas.cli.commands.messages.p063_message_poll_create_command import COMMAND
from thomas.messages.p063_message_poll_create_command import (
    MessagePollCreateInput,
    MessagePollExternalFailureError,
    MessagePollInvalidInputError,
    MessagePollMissingConfigError,
    run,
)


def test_core_success_without_delivery() -> None:
    out = run(
        MessagePollCreateInput(
            question="Best spaceship?",
            options=("Serenity", "Rocinante"),
            send=False,
        )
    )
    assert out.poll_id
    assert out.question == "Best spaceship?"
    assert out.options == ("Serenity", "Rocinante")
    assert out.sent is False
    assert "Poll: Best spaceship?" in out.message_text


def test_core_idempotency_key_produces_deterministic_poll_id() -> None:
    inp = MessagePollCreateInput(
        question="Q",
        options=("A", "B"),
        send=False,
        idempotency_key="same-key",
    )
    out1 = run(inp)
    out2 = run(inp)
    assert out1.poll_id == out2.poll_id


def test_core_invalid_input_requires_two_options() -> None:
    with pytest.raises(MessagePollInvalidInputError):
        run(MessagePollCreateInput(question="Q", options=("Only one",), send=False))


def test_core_missing_config_when_send_enabled_without_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("THOMAS_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("THOMAS_MESSAGE_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("THOMAS_MESSAGING_WEBHOOK_URL", raising=False)

    with pytest.raises(MessagePollMissingConfigError):
        run(
            MessagePollCreateInput(
                question="Q",
                options=("A", "B"),
                send=True,
            )
        )


def test_core_external_failure_is_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THOMAS_WEBHOOK_URL", "https://example.invalid/webhook")

    def _boom(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("network kaboom")

    with pytest.raises(MessagePollExternalFailureError):
        run(
            MessagePollCreateInput(question="Q", options=("A", "B"), send=True),
            _post=_boom,
        )


def test_core_delivery_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THOMAS_WEBHOOK_URL", "https://example.invalid/webhook")

    class _Resp:
        status_code = 200
        text = "ok"

    def _post(*args, **kwargs):  # type: ignore[no-untyped-def]
        return _Resp()

    out = run(
        MessagePollCreateInput(question="Q", options=("A", "B"), send=True),
        _post=_post,
    )
    assert out.sent is True
    assert out.delivery == {"status_code": 200, "response": "ok"}


def test_cli_json_success() -> None:
    runner = CliRunner()
    result = runner.invoke(
        COMMAND,
        [
            "--json",
            "--question",
            "Pick one",
            "--option",
            "A",
            "--option",
            "B",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["poll"]["question"] == "Pick one"
    assert payload["poll"]["options"] == ["A", "B"]


def test_cli_json_failure_invalid_input() -> None:
    runner = CliRunner()
    result = runner.invoke(COMMAND, ["--json", "--question", "Q", "--option", "A"])
    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_input"
