"""Two agents can both reach a commit in one checkout.

The presence gate refused every second agent, for two reasons that were each
sufficient alone.

1. `plans/thomas/WORKBOARD.md` counted as exclusive scope. But the board is the
   file agents coordinate THROUGH -- every agent appends a claim to it, so every
   agent's scope contains it, so every pair of agents "overlapped". The
   coordination layer was the thing that deadlocked coordination, and neither
   agent could release the board while working.

2. Every unregistered process produced a warning, and a warning was treated
   exactly like a conflict. A bare pid that has declared no scope cannot be shown
   to overlap anything; there were eighteen of them in this checkout, and the
   gates spawn them themselves. The gate was unconditionally red in the exact
   situation it exists for.

What the gate keeps is everything that rests on knowledge: an active agent
holding scope you want, a stale agent still holding scope you want, and an
unregistered process that DID declare an overlapping scope. What it gives up is
only the veto that rested on nothing.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from thomas.core import agent_presence as mod

BOARD = "plans/thomas/WORKBOARD.md"
OWNED = "thomas/core/config.py"


def _agent(agent_id: str, state: str, scope: list[str]) -> dict[str, Any]:
    return {"agent_id": agent_id, "display_name": agent_id, "state": state, "scope": scope}


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch, tmp_path):
    def _run(scope, agents):
        monkeypatch.setattr(mod, "collect_presence", lambda **_: {"success": True, "agents": agents})
        return mod.evaluate_soft_gate(purpose="commit", repo_root=tmp_path, actor_agent="me", requested_scope=scope)

    return _run


def test_two_agents_on_the_board_do_not_block_each_other(gate):
    """The load-bearing case: this is what deadlocked the checkout."""
    result = gate([BOARD], [_agent("other", "active", [BOARD])])
    assert result["ok"] is True
    assert result["conflicts"] == []


def test_the_board_does_not_launder_a_real_overlap(gate):
    """Sharing the board must not excuse the half of the scope that truly collides."""
    result = gate([BOARD, OWNED], [_agent("other", "active", [OWNED])])
    assert result["ok"] is False
    assert [c["agent_id"] for c in result["conflicts"]] == ["other"]


def test_a_board_only_overlap_leaves_the_rest_of_the_scope_free(gate):
    result = gate([BOARD, OWNED], [_agent("other", "active", [BOARD])])
    assert result["ok"] is True


def test_a_coordination_surface_is_recognised_in_any_project(gate):
    """Every project scaffolds its own praxis root, so the rule is a shape."""
    assert mod._is_coordination_surface("plans/minecraft/WORKBOARD.md") is True
    assert mod._is_coordination_surface("runtime/coordination/messages.json") is True
    assert mod._is_coordination_surface("thomas/core/config.py") is False
    assert mod._is_coordination_surface("docs/WORKBOARD.md.bak") is False


def test_a_scopeless_process_is_noticed_but_does_not_refuse(gate):
    result = gate([OWNED], [_agent("process:7", "unregistered", [])])
    assert result["ok"] is True, "an unknown process is not evidence of a collision"
    assert len(result["warnings"]) == 1, "it is still reported"
    assert "passed with" in result["message"]


def test_a_process_that_declared_an_overlapping_scope_still_refuses(gate):
    """Unregistered is not a free pass -- it is the ABSENCE of scope that is."""
    result = gate([OWNED], [_agent("process:8", "unregistered", [OWNED])])
    assert result["ok"] is False


def test_a_stale_agent_still_holding_your_files_refuses(gate):
    """A lapsed heartbeat is not permission to edit underneath someone."""
    result = gate([OWNED], [_agent("other", "stale", [OWNED])])
    assert result["ok"] is False


def test_an_undeclared_scope_stays_conservative(gate):
    """Declaring nothing is different from declaring only shared surfaces."""
    assert gate(None, [_agent("other", "active", [OWNED])])["ok"] is False


def test_the_refusal_can_still_be_overridden_with_a_reason(gate):
    result = mod.evaluate_soft_gate(
        purpose="commit",
        actor_agent="me",
        requested_scope=[OWNED],
        allow_override=True,
        override_reason="landing a scoped fix while the other agent is idle",
    )
    assert result["ok"] is True


# --- a lapsed agent's hold on your files expires -----------------------------
#
# Nothing in this system ever expired an abandoned session record. On 2026-09-09
# codex-governance-cleanup sat at state=active with a 160-hour-old heartbeat,
# still holding thomas/core/agent_presence.py, and no sweep could see it:
# --sweep-inactive sweeps board claims, and that agent had only a session record.
#
# The hold cannot key off staleness alone, because DEFAULT_STALE_SECONDS is 120 --
# "stale" here means "has not pinged in two minutes", which is a liveness signal.
# An agent that pauses to think is stale. If stale meant abandoned, a three-minute
# pause would lock that agent's files against everyone permanently.


def _aged(agent_id: str, state: str, scope: list[str], seconds: float) -> dict[str, Any]:
    row = _agent(agent_id, state, scope)
    row["last_heartbeat_at"] = mod._to_iso(mod._now() - timedelta(seconds=seconds))
    return row


def test_a_briefly_lapsed_agent_still_holds_its_files(gate):
    """Two minutes of silence is a pause, not an abandonment."""
    result = gate([OWNED], [_aged("thinking", "stale", [OWNED], 180)])
    assert result["ok"] is False, "a three minute pause must not release your files"


def test_a_long_silent_agent_stops_holding_your_files(gate):
    """The load-bearing case: 160 hours idle, still holding, nothing could sweep it."""
    result = gate([OWNED], [_aged("codex-governance-cleanup", "stale", [OWNED], 160 * 3600)])
    assert result["ok"] is True
    assert len(result["not_live"]) == 1, "the expired hold is still reported, not silenced"
    assert result["warnings"] == []


def test_the_hold_window_is_configurable(gate, monkeypatch: pytest.MonkeyPatch):
    row = _aged("napping", "stale", [OWNED], 3600)
    assert gate([OWNED], [row])["ok"] is True, "an hour is past the default window"
    monkeypatch.setenv("THOMAS_AGENT_PRESENCE_SCOPE_HOLD_SECONDS", "7200")
    assert gate([OWNED], [row])["ok"] is False, "a longer window keeps the hold"


def test_an_unmeasurable_row_keeps_its_hold(gate):
    """No timestamp is not evidence of death; do not take a hold away on a guess."""
    result = gate([OWNED], [_agent("no-timestamps", "stale", [OWNED])])
    assert result["ok"] is False


def test_an_expired_hold_does_not_excuse_a_live_agent(gate):
    """Expiry applies to lapsed rows only -- an active agent still refuses."""
    row = _aged("busy", "active", [OWNED], 160 * 3600)
    assert gate([OWNED], [row])["ok"] is False, "an active row is not aged out"


# --- the worktree row names the absence of a claimant ------------------------
#
# `unregistered-worktree` is not an agent. collect_presence synthesises it to
# list dirty paths that NO active scope covers, so it can never be evidence that
# someone else holds your files -- by construction nobody does.
#
# Left able to refuse, it closes a circle. A session goes stale after
# DEFAULT_STALE_SECONDS, which is 120. By the time an agent reaches its own
# commit its own scope no longer counts as covering anything, so its own edits
# resurface in this row as unclaimed activity, and the gate refuses the commit
# because the files being committed are uncommitted. Every agent blocked itself,
# on a timer, which is why it read as intermittent.


def test_your_own_dirty_files_cannot_refuse_your_own_commit(gate):
    """The circle, in one assertion."""
    worktree = _agent(mod.WORKTREE_ACTIVITY_ROW, "unregistered", [OWNED])
    result = gate([OWNED], [worktree])
    assert result["ok"] is True
    assert len(result["warnings"]) == 1, "still reported as unclaimed activity"


def test_the_worktree_row_does_not_excuse_a_named_agent(gate):
    """Only that one synthetic id is exempt; a real overlapping row still refuses."""
    worktree = _agent(mod.WORKTREE_ACTIVITY_ROW, "unregistered", [OWNED])
    real = _agent("someone", "active", [OWNED])
    assert gate([OWNED], [worktree, real])["ok"] is False
