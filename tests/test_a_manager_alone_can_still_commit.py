"""A task manager with no peers must not be told to produce workers from nothing.

The parent-throughput rule requires a parent-role agent to hold N active worker
claims before it may commit. That is a good rule when there are agents to delegate
to. It capped the requirement by how many TASKS were ready and never by how many
AGENTS were alive to take them.

Measured on 2026-09-09: one live agent in the repository, every peer stale for
hours, and the gate demanding two active worker claims. No action available to that
agent could satisfy it -- it cannot conjure peers -- so the only agent still working
could not commit anything. Seating a task manager is what put an agent into the
parent role in the first place, so the fix that enabled dispatch also created this.

The rule that governs it: a refusal must name an action that actually clears it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "forge" / "gates"))

import workboard_agent_claim as gate  # noqa: E402


def _rows(*agents):
    return {"agents": [dict(a) for a in agents]}


def _agent(agent_id, state="active", stale=False):
    from thomas.core import agent_presence as ap

    row = {"agent_id": agent_id, "state": state}
    if stale:
        row["last_heartbeat_at"] = ap._to_iso(ap._now() - ap.timedelta(seconds=99999))  # type: ignore[attr-defined]
    return row


def test_a_lone_manager_is_asked_for_no_workers(monkeypatch):
    """The load-bearing case: one live agent, nobody to delegate to."""
    from thomas.core import agent_presence as ap

    monkeypatch.setattr(ap, "collect_presence", lambda **_: _rows(_agent("me")))
    assert gate._available_peer_count("me") == 0


def test_live_peers_are_counted(monkeypatch):
    from thomas.core import agent_presence as ap

    monkeypatch.setattr(ap, "collect_presence", lambda **_: _rows(_agent("me"), _agent("a"), _agent("b")))
    assert gate._available_peer_count("me") == 2


def test_a_long_silent_peer_cannot_take_a_task(monkeypatch):
    """An agent idle for hours is not somebody you can hand work to."""
    from datetime import timedelta

    from thomas.core import agent_presence as ap

    dead = {"agent_id": "ghost", "state": "active", "last_heartbeat_at": ap._to_iso(ap._now() - timedelta(hours=10))}
    monkeypatch.setattr(ap, "collect_presence", lambda **_: {"agents": [{"agent_id": "me", "state": "active"}, dead]})
    assert gate._available_peer_count("me") == 0


def test_bare_processes_are_not_delegates(monkeypatch):
    """A pid with no identity cannot be handed a task."""
    from thomas.core import agent_presence as ap

    monkeypatch.setattr(
        ap,
        "collect_presence",
        lambda **_: {"agents": [{"agent_id": "me", "state": "active"}, {"agent_id": "process:99", "state": "active"}]},
    )
    assert gate._available_peer_count("me") == 0


def test_unreadable_presence_is_unknown_not_zero(monkeypatch):
    """Unknown must not refuse, and must not silently mean 'no peers' either."""
    from thomas.core import agent_presence as ap

    def boom(**_):
        raise OSError("presence unavailable")

    monkeypatch.setattr(ap, "collect_presence", boom)
    assert gate._available_peer_count("me") is None
