"""Tests for CAP-126: audit logs with actor attribution, causal chains, export.

Every test is hermetic: a temp JSONL path, an injected deterministic clock,
no network and no live model.
"""

from __future__ import annotations

import itertools

import pytest

from thomas.security.audit_chain import (
    AGENT,
    HUMAN,
    AuditChainError,
    AuditChainLog,
    AuditEntry,
    Principal,
)


class FixedClock:
    """Deterministic clock yielding a fixed, monotonically increasing sequence."""

    def __init__(self, *stamps: str) -> None:
        self._stamps = list(stamps) or ["2026-07-21T00:00:00Z"]
        self._it = itertools.cycle(self._stamps)

    def __call__(self) -> str:
        return next(self._it)


@pytest.fixture()
def log_path(tmp_path):
    return tmp_path / "security" / "audit_chain.jsonl"


@pytest.fixture()
def clock():
    return FixedClock(
        "2026-07-21T09:00:00Z",
        "2026-07-21T09:00:01Z",
        "2026-07-21T09:00:02Z",
        "2026-07-21T09:00:03Z",
    )


# ---------------------------------------------------------------------------
# (1) Complete actor attribution
# ---------------------------------------------------------------------------


def test_entry_records_full_actor_attribution(log_path, clock):
    log = AuditChainLog(log_path, clock=clock)

    human = Principal.human("calvin")
    root = log.record(actor=human, action="request", resource="report/q3")

    agent = Principal.agent("planner-1", on_behalf_of="calvin")
    delegated = log.record(
        actor=agent,
        action="generate",
        resource="report/q3",
        caused_by=root.entry_id,
    )

    # The human action names its actor unambiguously and acts on its own behalf.
    assert root.actor.kind == HUMAN
    assert root.actor.id == "calvin"
    assert root.actor.on_behalf_of == ""
    assert root.actor.initiating_human == "calvin"

    # The delegated agent action carries on_behalf_of the initiating human.
    assert delegated.actor.kind == AGENT
    assert delegated.actor.id == "planner-1"
    assert delegated.actor.on_behalf_of == "calvin"
    assert delegated.actor.initiating_human == "calvin"


def test_human_principal_cannot_act_on_behalf_of_another():
    with pytest.raises(AuditChainError):
        Principal(id="calvin", kind=HUMAN, on_behalf_of="someone-else")


def test_principal_rejects_bad_kind_and_empty_id():
    with pytest.raises(AuditChainError):
        Principal(id="x", kind="robot")
    with pytest.raises(AuditChainError):
        Principal(id="", kind=HUMAN)


# ---------------------------------------------------------------------------
# (2) Human -> agent -> agent causal chain, reconstructed in order
# ---------------------------------------------------------------------------


def test_trace_reconstructs_human_agent_agent_chain_in_order(log_path, clock):
    log = AuditChainLog(log_path, clock=clock)

    human = log.record(actor=Principal.human("calvin"), action="ask", resource="task/42")
    agent_a = log.record(
        actor=Principal.agent("orchestrator", on_behalf_of="calvin"),
        action="plan",
        resource="task/42",
        caused_by=human.entry_id,
    )
    agent_b = log.record(
        actor=Principal.agent("worker", on_behalf_of="calvin"),
        action="execute",
        resource="task/42",
        caused_by=agent_a.entry_id,
    )

    chain = log.trace_causal_chain(agent_b.entry_id)

    # Ordered root-first: human -> orchestrator -> worker.
    assert [e.entry_id for e in chain] == [human.entry_id, agent_a.entry_id, agent_b.entry_id]
    assert [e.actor.kind for e in chain] == [HUMAN, AGENT, AGENT]
    assert [e.action for e in chain] == ["ask", "plan", "execute"]
    assert chain[0].actor.id == "calvin"


def test_trace_from_root_returns_single_entry(log_path, clock):
    log = AuditChainLog(log_path, clock=clock)
    human = log.record(actor=Principal.human("calvin"), action="ask", resource="task/1")
    assert [e.entry_id for e in log.trace_causal_chain(human.entry_id)] == [human.entry_id]


def test_record_rejects_dangling_causal_parent(log_path, clock):
    log = AuditChainLog(log_path, clock=clock)
    with pytest.raises(AuditChainError):
        log.record(
            actor=Principal.agent("worker", on_behalf_of="calvin"),
            action="execute",
            resource="task/42",
            caused_by="ae-00000000-deadbeefcafe",
        )


def test_trace_guards_missing_parent_after_corruption(log_path, clock):
    """A dangling parent reaching the trace layer is handled, not crashed on."""
    log = AuditChainLog(log_path, clock=clock)
    human = log.record(actor=Principal.human("calvin"), action="ask", resource="task/1")
    child = log.record(
        actor=Principal.agent("worker", on_behalf_of="calvin"),
        action="do",
        resource="task/1",
        caused_by=human.entry_id,
    )
    # Simulate a corrupted in-memory graph: parent vanished from the index.
    del log._by_id[human.entry_id]
    with pytest.raises(AuditChainError):
        log.trace_causal_chain(child.entry_id)


def test_trace_unknown_entry_raises(log_path, clock):
    log = AuditChainLog(log_path, clock=clock)
    with pytest.raises(AuditChainError):
        log.trace_causal_chain("ae-00000000-nope00000000")


# ---------------------------------------------------------------------------
# (3) Export -> stable JSONL -> re-import identically (round-trip)
# ---------------------------------------------------------------------------


def _build_sample_log(path, clock) -> AuditChainLog:
    log = AuditChainLog(path, clock=clock)
    human = log.record(actor=Principal.human("calvin"), action="ask", resource="task/42")
    agent_a = log.record(
        actor=Principal.agent("orchestrator", on_behalf_of="calvin"),
        action="plan",
        resource="task/42",
        caused_by=human.entry_id,
        details={"priority": "high"},
    )
    log.record(
        actor=Principal.agent("worker", on_behalf_of="calvin"),
        action="execute",
        resource="task/42",
        caused_by=agent_a.entry_id,
    )
    return log


def test_export_is_stable_and_reimports_identically(log_path, clock, tmp_path):
    log = _build_sample_log(log_path, clock)

    text = log.export()
    # Stable: exporting again yields byte-identical JSONL.
    assert log.export() == text
    assert text.count("\n") == 3

    reimported = AuditChainLog.from_jsonl(
        text,
        tmp_path / "reimport" / "audit.jsonl",
        clock=FixedClock("2099-01-01T00:00:00Z"),
    )
    original = log.all_entries()
    restored = reimported.all_entries()
    assert restored == original
    # Ids and timestamps are preserved exactly (not re-clocked on import).
    assert [e.entry_id for e in restored] == [e.entry_id for e in original]
    assert [e.timestamp for e in restored] == [e.timestamp for e in original]
    # And the re-imported log re-exports to the same bytes.
    assert reimported.export() == text


def test_export_to_file_matches_returned_text(log_path, clock, tmp_path):
    log = _build_sample_log(log_path, clock)
    out = tmp_path / "out" / "export.jsonl"
    text = log.export(out)
    assert out.read_text(encoding="utf-8") == text


def test_entry_dict_roundtrips(log_path, clock):
    log = _build_sample_log(log_path, clock)
    for entry in log.all_entries():
        assert AuditEntry.from_dict(entry.to_dict()) == entry


# ---------------------------------------------------------------------------
# Durability + filtering
# ---------------------------------------------------------------------------


def test_log_is_durable_across_instances(log_path, clock):
    log = _build_sample_log(log_path, clock)
    ids = [e.entry_id for e in log.all_entries()]

    # A fresh instance over the same path recovers the full log.
    reloaded = AuditChainLog(log_path, clock=FixedClock("2099-01-01T00:00:00Z"))
    assert [e.entry_id for e in reloaded.all_entries()] == ids
    assert len(reloaded) == 3


def test_filter_by_actor_and_by_time(log_path, clock):
    log = _build_sample_log(log_path, clock)

    # by actor id
    orchestrator_only = log.filter(actor_id="orchestrator")
    assert [e.action for e in orchestrator_only] == ["plan"]

    # by kind
    agents_only = log.filter(kind=AGENT)
    assert [e.actor.id for e in agents_only] == ["orchestrator", "worker"]
    humans_only = log.filter(kind=HUMAN)
    assert [e.actor.id for e in humans_only] == ["calvin"]

    # by on_behalf_of
    delegated = log.filter(on_behalf_of="calvin")
    assert [e.actor.id for e in delegated] == ["orchestrator", "worker"]

    # by inclusive time window (clock stamped 09:00:00, :01, :02)
    windowed = log.filter(since="2026-07-21T09:00:01Z", until="2026-07-21T09:00:01Z")
    assert [e.action for e in windowed] == ["plan"]


def test_export_filtered_slice(log_path, clock):
    log = _build_sample_log(log_path, clock)
    text = log.export(kind=HUMAN)
    assert text.count("\n") == 1
    # The slice re-imports to exactly the filtered entries.
    reimport = AuditChainLog.from_jsonl(text, log_path.parent / "slice.jsonl", clock=clock)
    assert [e.actor.id for e in reimport.all_entries()] == ["calvin"]


def test_import_rejects_duplicate_ids(log_path, clock):
    log = _build_sample_log(log_path, clock)
    text = log.export()
    with pytest.raises(AuditChainError):
        log.import_jsonl(text)  # same ids already present
