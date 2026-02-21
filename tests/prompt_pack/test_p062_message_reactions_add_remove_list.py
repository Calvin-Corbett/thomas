import json
import os

import pytest


def test_reactions_add_list_remove_roundtrip_memory_backend():
    from thomas.messages.p062_message_reactions_add_remove_list import (
        InMemoryReactionBackend,
        MessageReactionAddInput,
        MessageReactionListInput,
        MessageReactionRemoveInput,
        add_reaction,
        list_reactions,
        remove_reaction,
    )

    store = {}
    backend = InMemoryReactionBackend(store=store)

    add_result = add_reaction(
        MessageReactionAddInput(message_id="m1", channel_id="c1", emoji=":+1:", user_id="u1"),
        backend=backend,
    )
    assert add_result.ok is True
    assert add_result.action == "add"
    assert add_result.applied is True

    # Duplicate add should be a deterministic no-op.
    add_result2 = add_reaction(
        MessageReactionAddInput(message_id="m1", channel_id="c1", emoji=":+1:", user_id="u1"),
        backend=backend,
    )
    assert add_result2.ok is True
    assert add_result2.applied is False

    list_result = list_reactions(MessageReactionListInput(message_id="m1", channel_id="c1"), backend=backend)
    assert list_result.ok is True
    assert list_result.action == "list"
    assert len(list_result.reactions) == 1
    assert list_result.reactions[0].emoji == ":+1:"
    assert list_result.reactions[0].count == 1
    assert list_result.reactions[0].user_ids == ("u1",)

    # Removing a missing user is a no-op.
    remove_result_noop = remove_reaction(
        MessageReactionRemoveInput(message_id="m1", channel_id="c1", emoji=":+1:", user_id="u2"),
        backend=backend,
    )
    assert remove_result_noop.ok is True
    assert remove_result_noop.applied is False

    remove_result = remove_reaction(
        MessageReactionRemoveInput(message_id="m1", channel_id="c1", emoji=":+1:", user_id="u1"),
        backend=backend,
    )
    assert remove_result.ok is True
    assert remove_result.action == "remove"
    assert remove_result.applied is True

    list_result2 = list_reactions(MessageReactionListInput(message_id="m1", channel_id="c1"), backend=backend)
    assert list_result2.ok is True
    assert list_result2.reactions == ()


def test_invalid_input_is_deterministic():
    from thomas.messages.p062_message_reactions_add_remove_list import MessageReactionsError, run

    with pytest.raises(MessageReactionsError) as exc:
        run({"operation": "add", "message_id": "m1", "emoji": ""}, backend=None, config=None)

    assert exc.value.code == "invalid_input"
    data = exc.value.to_dict()
    assert data["ok"] is False
    assert data["error"]["code"] == "invalid_input"


def test_missing_config_is_deterministic(monkeypatch):
    from thomas.messages.p062_message_reactions_add_remove_list import MessageReactionsError, run

    monkeypatch.delenv("THOMAS_MESSAGE_REACTIONS_BACKEND", raising=False)
    monkeypatch.delenv("THOMAS_API_BASE_URL", raising=False)
    monkeypatch.delenv("THOMAS_API_TOKEN", raising=False)
    monkeypatch.delenv("THOMAS_API_TIMEOUT_SECONDS", raising=False)

    with pytest.raises(MessageReactionsError) as exc:
        run({"operation": "list", "message_id": "m1"}, backend=None, config=None)

    assert exc.value.code == "missing_config"


def test_cli_json_output_memory_backend(monkeypatch):
    from typer.testing import CliRunner

    from thomas.cli.commands.messages.p062_message_reactions_add_remove_list import app
    from thomas.messages.p062_message_reactions_add_remove_list import InMemoryReactionBackend

    InMemoryReactionBackend.reset_global_store()

    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "add",
            "--message-id",
            "m1",
            "--channel-id",
            "c1",
            "--emoji",
            ":rocket:",
            "--user-id",
            "u1",
            "--backend",
            "memory",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["action"] == "add"
    assert payload["applied"] is True

    # Ensure list returns the expected reaction.
    result2 = runner.invoke(
        app,
        [
            "list",
            "--message-id",
            "m1",
            "--channel-id",
            "c1",
            "--backend",
            "memory",
            "--json",
        ],
    )
    assert result2.exit_code == 0, result2.output
    payload2 = json.loads(result2.output)
    assert payload2["ok"] is True
    assert payload2["action"] == "list"
    assert payload2["reactions"][0]["emoji"] == ":rocket:"
    assert payload2["reactions"][0]["count"] == 1


def test_cli_missing_config_emits_json_error(monkeypatch):
    from typer.testing import CliRunner

    from thomas.cli.commands.messages.p062_message_reactions_add_remove_list import app

    monkeypatch.delenv("THOMAS_MESSAGE_REACTIONS_BACKEND", raising=False)
    monkeypatch.delenv("THOMAS_API_BASE_URL", raising=False)
    monkeypatch.delenv("THOMAS_API_TOKEN", raising=False)
    monkeypatch.delenv("THOMAS_API_TIMEOUT_SECONDS", raising=False)

    runner = CliRunner()
    result = runner.invoke(app, ["list", "--message-id", "m1", "--json"])
    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_config"
