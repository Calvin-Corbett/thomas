"""A presence row must not outrank the measurement that contradicts it.

On 2026-09-03 nine agents read as live in this repository. Every one had pid 0
and no heartbeat; one had last spoken six weeks earlier, on 2026-07-22, in
messages already marked resolved. Between them they blocked scope overlaps for
every other agent, and a real commit had to be landed past them.

The session scan was never wrong. It reads a session file, finds no heartbeat
and no live pid, and correctly calls that row `stale`. `_merge_row` then threw
that away: `declared` - the placeholder `_base_row` stamps on an agent whose
name has been seen and nothing else - outranked it. A default beat a
measurement, so an agent that had been dead for six weeks was reported as
present.

The rule these tests hold down is that `declared` means "no evidence yet" and
must lose to any state that came from looking.
"""

from __future__ import annotations

from typing import Any

from thomas.core import agent_presence as ap


def _base(agent: str = "ghost-agent") -> dict[str, Any]:
    return ap._base_row(ap.ROOT, agent)


def test_a_measured_stale_beats_the_declared_placeholder() -> None:
    """The whole bug in one assertion."""
    merged = ap._merge_row(_base(), {"state": "stale", "confidence": "low"})
    assert merged["state"] == "stale", "the placeholder outranked the measurement; a dead agent reads as present"


def test_every_measured_state_still_beats_declared() -> None:
    for measured in ("active", "alive", "unregistered", "stale"):
        merged = ap._merge_row(_base(), {"state": measured})
        assert merged["state"] == measured, f"{measured} lost to the placeholder"


def test_a_live_agent_is_not_downgraded_by_a_stale_row() -> None:
    """Protection must not weaken: real presence still wins."""
    row = ap._merge_row(_base(), {"state": "active", "confidence": "high"})
    row = ap._merge_row(row, {"state": "stale", "confidence": "low"})
    assert row["state"] == "active", "a stale signal must not bury a live agent"


def test_declared_survives_when_nothing_was_measured() -> None:
    """An agent named on the board with no session is still declared, not stale."""
    merged = ap._merge_row(_base(), {"display_name": "someone"})
    assert merged["state"] == "declared"


def test_a_session_with_no_heartbeat_and_a_dead_pid_is_stale(tmp_path) -> None:
    """End to end through the real session scan, not just the merge."""
    import json

    presence = ap.presence_dir(tmp_path)
    presence.mkdir(parents=True)
    (presence / "s1.json").write_text(
        json.dumps(
            {
                "session_id": "s1",
                "agent_id": "long-gone",
                "pid": 0,
                # The date a real phantom was last heard from.
                "last_heartbeat_at": "2026-07-22T00:00:00+00:00",
                "scope": ["thomas/core/x.py"],
            }
        ),
        encoding="utf-8",
    )
    rows = ap._collect_sessions(tmp_path)
    assert rows, "the session file was not read at all"
    assert rows[0]["state"] == "stale"


def test_that_stale_session_does_not_read_as_present(tmp_path) -> None:
    """The end the owner cares about: a six-week-dead agent is not 'active'."""
    import json

    presence = ap.presence_dir(tmp_path)
    presence.mkdir(parents=True)
    (presence / "s1.json").write_text(
        json.dumps(
            {
                "session_id": "s1",
                "agent_id": "long-gone",
                "pid": 0,
                "last_heartbeat_at": "2026-07-22T00:00:00+00:00",
                "scope": ["thomas/core/x.py"],
            }
        ),
        encoding="utf-8",
    )
    rows = ap._collect_sessions(tmp_path)
    merged = ap._merge_row(ap._base_row(tmp_path, "long-gone"), rows[0])
    assert merged["state"] not in {"active", "alive", "declared"}, (
        "a dead agent still counts as present, and still blocks every scope it named"
    )


def _repo_with_dead_agent(tmp_path, agent: str = "long-gone") -> Any:
    """A repo whose only other 'agent' is a session with no heartbeat, dead pid."""
    import json

    presence = ap.presence_dir(tmp_path)
    presence.mkdir(parents=True)
    (presence / "s1.json").write_text(
        json.dumps(
            {
                "session_id": "s1",
                "agent_id": agent,
                "pid": 0,
                "last_heartbeat_at": "2026-07-22T00:00:00+00:00",
                "scope": ["pyproject.toml"],
                "claim_status": "active",
            }
        ),
        encoding="utf-8",
    )
    board = tmp_path / "WORKBOARD.md"
    board.write_text("# Workboard\n", encoding="utf-8")
    return board


def test_a_dead_agent_warns_instead_of_blocking(tmp_path) -> None:
    """The end this was reported for: it must stop refusing other agents' work.

    Before 2026-09-03 this scope was refused outright, and landing anything on it
    needed an owner Windows Hello tap to override a gate protecting nobody.
    """
    board = _repo_with_dead_agent(tmp_path)
    result = ap.evaluate_soft_gate(
        purpose="commit",
        repo_root=tmp_path,
        workboard_path=board,
        actor_agent="claude",
        requested_scope=["pyproject.toml"],
    )
    assert result.get("conflicts") == [], "a dead agent still blocks the scope"
    messages = " ".join(str(w.get("message") or "") for w in result.get("warnings") or [])
    assert "long-gone" in messages, "it went quiet instead of saying who is stale"
    assert "stale" in messages.lower()


def test_a_live_agent_still_blocks_an_overlapping_scope(tmp_path) -> None:
    """Protection must not be weakened - the gate still refuses a real overlap."""
    import json
    import os

    presence = ap.presence_dir(tmp_path)
    presence.mkdir(parents=True)
    (presence / "s2.json").write_text(
        json.dumps(
            {
                "session_id": "s2",
                "agent_id": "very-much-alive",
                # This process: unambiguously a live pid.
                "pid": os.getpid(),
                "scope": ["pyproject.toml"],
                "claim_status": "active",
            }
        ),
        encoding="utf-8",
    )
    board = tmp_path / "WORKBOARD.md"
    board.write_text("# Workboard\n", encoding="utf-8")
    result = ap.evaluate_soft_gate(
        purpose="commit",
        repo_root=tmp_path,
        workboard_path=board,
        actor_agent="claude",
        requested_scope=["pyproject.toml"],
    )
    agents = [str(c.get("agent_id")) for c in result.get("conflicts") or []]
    assert "very-much-alive" in agents, "a live agent's scope is no longer protected"
