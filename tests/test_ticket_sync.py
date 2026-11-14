"""Tests for the ticket-system integration with bidirectional status sync (CAP-071).

All tests are hermetic: they use the in-memory ``FakeProvider`` and an injected
transport for the real ``LinearProvider``, so no network access is required.
"""

from __future__ import annotations

import json

import pytest

from thomas.integrations.tickets import (
    BidirectionalSyncEngine,
    CanonicalStatus,
    FakeProvider,
    LinearProvider,
)


def _assigned_ticket() -> dict:
    return {
        "id": "uuid-eng-42",
        "identifier": "ENG-42",
        "title": "Wire up ticket sync",
        "description": "Bidirectional status sync.",
        "assignee": {"name": "Calvin", "email": "calvin@example.com"},
        "state": {"id": "s-todo", "name": "Todo", "type": "unstarted"},
        "team": {"id": "team-1"},
    }


def test_assigned_ticket_becomes_work_item() -> None:
    engine = BidirectionalSyncEngine(FakeProvider())
    item = engine.intake_assignment(_assigned_ticket())

    assert item.key == "ENG-42"
    assert item.source == "linear"
    assert item.assignee == "Calvin"
    assert item.ticket_id == "uuid-eng-42"
    assert item.status == CanonicalStatus.TODO
    # tracked for subsequent sync
    assert engine.work_item("ENG-42").title == "Wire up ticket sync"


def test_unassigned_ticket_is_not_an_assignment() -> None:
    engine = BidirectionalSyncEngine(FakeProvider())
    ticket = _assigned_ticket()
    ticket["assignee"] = None
    with pytest.raises(ValueError, match="no assignee"):
        engine.intake_assignment(ticket)


def test_ticket_in_progress_propagates_to_pr_side() -> None:
    engine = BidirectionalSyncEngine(FakeProvider())
    engine.intake_assignment(_assigned_ticket())

    result = engine.sync_from_ticket("ENG-42", "In Progress")

    assert result.applied is True
    assert result.direction == "ticket->pr"
    assert result.canonical == CanonicalStatus.IN_PROGRESS
    assert result.pr_state == "in_progress"
    assert engine.record("ENG-42").pr_canonical == CanonicalStatus.IN_PROGRESS


def test_pr_merged_propagates_back_to_done() -> None:
    provider = FakeProvider({"uuid-eng-42": _assigned_ticket()})
    engine = BidirectionalSyncEngine(provider)
    engine.intake_assignment(_assigned_ticket())

    result = engine.sync_from_pr("ENG-42", "merged")

    assert result.applied is True
    assert result.direction == "pr->ticket"
    assert result.canonical == CanonicalStatus.DONE
    assert result.ticket_state == "Done"
    # the ticket provider actually received the write
    assert ("uuid-eng-42", "Done") in provider.state_writes
    assert provider.get_ticket("uuid-eng-42")["state"]["name"] == "Done"


def test_idempotent_no_duplicate_writes() -> None:
    provider = FakeProvider({"uuid-eng-42": _assigned_ticket()})
    engine = BidirectionalSyncEngine(provider)
    engine.intake_assignment(_assigned_ticket())

    first = engine.sync_from_pr("ENG-42", "merged")
    second = engine.sync_from_pr("ENG-42", "merged")

    assert first.applied is True
    assert second.applied is False
    # only one provider write despite two syncs
    assert provider.state_writes.count(("uuid-eng-42", "Done")) == 1


def test_simultaneous_divergent_change_records_conflict() -> None:
    provider = FakeProvider({"uuid-eng-42": _assigned_ticket()})
    engine = BidirectionalSyncEngine(provider)
    engine.intake_assignment(_assigned_ticket())

    # Ticket moved to Done; PR simultaneously closed (canceled). Divergent.
    result = engine.reconcile(
        "ENG-42",
        ticket_state="Done",
        pr_state="closed",
        ticket_updated_at=200.0,
        pr_updated_at=100.0,
    )

    assert result.direction == "conflict"
    assert result.conflict is not None
    assert result.conflict.winner == "ticket"  # newer timestamp wins
    assert result.conflict.resolved_canonical == CanonicalStatus.DONE
    assert result.conflict.ticket_canonical == CanonicalStatus.DONE
    assert result.conflict.pr_canonical == CanonicalStatus.CANCELED
    # conflict is recorded, not silently dropped
    assert len(engine.conflicts) == 1
    # both sides converge to the winner
    assert engine.record("ENG-42").ticket_canonical == CanonicalStatus.DONE
    assert engine.record("ENG-42").pr_canonical == CanonicalStatus.DONE


def test_conflict_pr_wins_writes_back_to_ticket() -> None:
    provider = FakeProvider({"uuid-eng-42": _assigned_ticket()})
    engine = BidirectionalSyncEngine(provider)
    engine.intake_assignment(_assigned_ticket())

    result = engine.reconcile(
        "ENG-42",
        ticket_state="In Progress",
        pr_state="merged",
        ticket_updated_at=100.0,
        pr_updated_at=250.0,
    )

    assert result.conflict is not None
    assert result.conflict.winner == "pr"
    assert result.conflict.resolved_canonical == CanonicalStatus.DONE
    # the losing (ticket) side is written back through the provider
    assert ("uuid-eng-42", "Done") in provider.state_writes


def test_reconcile_single_side_change_is_not_a_conflict() -> None:
    engine = BidirectionalSyncEngine(FakeProvider())
    engine.intake_assignment(_assigned_ticket())

    result = engine.reconcile(
        "ENG-42",
        ticket_state="In Progress",
        pr_state="open",  # open maps to in_progress == same canonical, no PR divergence
        ticket_updated_at=100.0,
        pr_updated_at=100.0,
    )

    assert result.conflict is None
    assert result.direction == "ticket->pr"
    assert result.canonical == CanonicalStatus.IN_PROGRESS
    assert engine.conflicts == []


def test_github_issue_assignment_reuses_normalizer() -> None:
    engine = BidirectionalSyncEngine(FakeProvider())
    issue = {
        "number": 7,
        "title": "Fix flaky test",
        "body": "It fails sometimes.",
        "state": "open",
        "labels": [{"name": "bug"}],
        "assignees": [{"login": "octocat"}],
        "html_url": "https://github.com/acme/repo/issues/7",
        "repository": {"full_name": "acme/repo"},
    }
    item = engine.intake_assignment(issue)

    assert item.source == "github_issue"
    assert item.assignee == "octocat"
    assert item.source_id == "acme/repo#7"
    assert item.status == CanonicalStatus.TODO


# --- LinearProvider: real adapter, credential redaction (hermetic) ----------


def test_linear_token_never_logged_in_repr() -> None:
    secret = "lin_api_SUPERSECRET_should_never_appear"
    provider = LinearProvider(token_provider=lambda: secret)

    assert secret not in repr(provider)
    assert secret not in str(provider)
    assert "token=set" in repr(provider)


def test_linear_token_absent_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LINEAR_API_KEY", raising=False)
    provider = LinearProvider()
    assert "token=unset" in repr(provider)


def test_linear_get_ticket_uses_injected_transport() -> None:
    secret = "lin_api_SUPERSECRET_should_never_appear"
    captured: dict = {}

    def fake_opener(req, timeout_s):
        captured["auth"] = req.get_header("Authorization")
        captured["body"] = req.data.decode("utf-8")
        payload = {
            "data": {
                "issue": {
                    "id": "uuid-eng-42",
                    "identifier": "ENG-42",
                    "title": "Wire up ticket sync",
                    "state": {"id": "s1", "name": "Todo"},
                    "team": {"id": "team-1"},
                }
            }
        }
        return json.dumps(payload).encode("utf-8")

    provider = LinearProvider(token_provider=lambda: secret, opener=fake_opener)
    ticket = provider.get_ticket("ENG-42")

    assert ticket["identifier"] == "ENG-42"
    # token is used in the request header but must never be logged by us
    assert captured["auth"] == secret
    # our serialized GraphQL body carries variables, never the token
    assert secret not in captured["body"]


def test_linear_get_ticket_missing_raises() -> None:
    def fake_opener(req, timeout_s):
        return json.dumps({"data": {"issue": None}}).encode("utf-8")

    provider = LinearProvider(api_key="x", opener=fake_opener)
    from thomas.integrations.tickets import TicketProviderError

    with pytest.raises(TicketProviderError, match="issue not found"):
        provider.get_ticket("ENG-999")
