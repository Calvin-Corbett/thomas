from __future__ import annotations

import json

import pytest


def test_vote_and_close_success() -> None:
    from thomas.messages.p064_message_poll_vote_and_close import (
        PollVoteAndCloseRequest,
        vote_and_close_poll,
    )

    class StubBackend:
        def poll_vote(self, *, poll_id: str, option: str, voter_id=None, reason=None):
            return {"poll_id": poll_id, "option": option, "voter_id": voter_id}

        def poll_close(self, *, poll_id: str, reason=None):
            return {"poll_id": poll_id, "closed": True}

    req = PollVoteAndCloseRequest(poll_id="poll-123", option="A", voter_id="u1")
    result = vote_and_close_poll(req, client=StubBackend())

    assert result.poll_id == "poll-123"
    assert result.option == "A"
    assert result.voted is True
    assert result.closed is True
    assert dict(result.vote_receipt or {})["voter_id"] == "u1"
    assert dict(result.close_receipt or {})["closed"] is True


def test_vote_and_close_invalid_input() -> None:
    from thomas.messages.p064_message_poll_vote_and_close import (
        MessagePollVoteAndCloseError,
        PollVoteAndCloseRequest,
        vote_and_close_poll,
    )

    class StubBackend:
        def poll_vote(self, *, poll_id: str, option: str, voter_id=None, reason=None):
            return {}

        def poll_close(self, *, poll_id: str, reason=None):
            return {}

    with pytest.raises(MessagePollVoteAndCloseError) as exc:
        vote_and_close_poll(PollVoteAndCloseRequest(poll_id="", option="A"), client=StubBackend())

    assert exc.value.code == "invalid_input"


def test_vote_and_close_external_failure_vote() -> None:
    from thomas.messages.p064_message_poll_vote_and_close import (
        MessagePollVoteAndCloseError,
        PollVoteAndCloseRequest,
        vote_and_close_poll,
    )

    class StubBackend:
        def poll_vote(self, *, poll_id: str, option: str, voter_id=None, reason=None):
            raise RuntimeError("boom")

        def poll_close(self, *, poll_id: str, reason=None):
            return {}

    with pytest.raises(MessagePollVoteAndCloseError) as exc:
        vote_and_close_poll(PollVoteAndCloseRequest(poll_id="poll-123", option="A"), client=StubBackend())

    assert exc.value.code == "external_failure"
    assert exc.value.details.get("stage") == "vote"


def test_vote_and_close_external_failure_close_includes_vote_receipt() -> None:
    from thomas.messages.p064_message_poll_vote_and_close import (
        MessagePollVoteAndCloseError,
        PollVoteAndCloseRequest,
        vote_and_close_poll,
    )

    class StubBackend:
        def poll_vote(self, *, poll_id: str, option: str, voter_id=None, reason=None):
            return {"poll_id": poll_id, "option": option, "voted": True}

        def poll_close(self, *, poll_id: str, reason=None):
            raise RuntimeError("close-boom")

    with pytest.raises(MessagePollVoteAndCloseError) as exc:
        vote_and_close_poll(PollVoteAndCloseRequest(poll_id="poll-123", option="A"), client=StubBackend())

    assert exc.value.code == "external_failure"
    assert exc.value.details.get("stage") == "close"
    assert "vote_receipt" in exc.value.details


def test_cli_json_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI wrapper should support deterministic JSON output."""

    import typer
    from typer.testing import CliRunner

    import thomas.messages.p064_message_poll_vote_and_close as msg_mod
    from thomas.cli.commands.messages import p064_message_poll_vote_and_close as cli_mod

    class StubBackend:
        def poll_vote(self, *, poll_id: str, option: str, voter_id=None, reason=None):
            return {"poll_id": poll_id, "option": option, "voted": True}

        def poll_close(self, *, poll_id: str, reason=None):
            return {"poll_id": poll_id, "closed": True}

    monkeypatch.setattr(msg_mod, "_get_messages_client", lambda config=None: StubBackend())

    app = typer.Typer(add_completion=False)

    @app.command("_noop")
    def _noop() -> None:  # pragma: no cover
        pass

    cli_mod.register(app)

    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "poll-vote-and-close",
            "--poll-id",
            "poll-123",
            "--option",
            "A",
            "--json",
        ],
    )

    assert res.exit_code == 0
    payload = json.loads(res.stdout.strip())
    assert payload["ok"] is True
    assert payload["poll_id"] == "poll-123"
    assert payload["closed"] is True

    # Deterministic key ordering isn't required by JSON, but we guarantee stable
    # formatting for automation; ensure parseable and stable ok-flag.
    assert "ok" in payload
