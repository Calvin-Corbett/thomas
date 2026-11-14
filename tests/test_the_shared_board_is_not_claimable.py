"""The workboard is infrastructure every agent writes, so no agent may own it.

Measured 2026-09-09: one agent held `plans/thomas/WORKBOARD.md` in its claim
scope, and every other agent was blocked from committing ANYTHING. Not from
editing the board -- from committing at all. Every board-reading gate (inbox,
agent claim, changed files) reads the copy pre-commit stashes, which is HEAD's,
so an agent's own ack and its own claim are invisible until the board is staged;
staging it is a scope violation while someone else claims it. A message acked
successfully was still reported unread by the gate six attempts running.

A file that every agent must write and every gate must read cannot also be
exclusively owned. It is excluded from conflict detection here, and it stays
legal in a claim scope so agents can still stage their own board edits.
"""

from __future__ import annotations

from scripts.crew.workboard.claim_ownership import SHARED_INFRASTRUCTURE, foreign_scope_conflicts
from scripts.forge.gates import workboard_claims as claims_gate

BOARD = "plans/thomas/WORKBOARD.md"
FRAGMENTS = "changelog.d"

CLAIMS = [
    "## Agent Claims",
    f"- agent=other-agent; name=theirs; role=solo; parent=none; scope=thomas/work/lanes,{BOARD}; task=T1",
    "",
    "## Active Tasks",
]


def test_the_board_is_named_as_shared_infrastructure():
    assert BOARD in SHARED_INFRASTRUCTURE


def test_two_agents_may_both_carry_the_board_in_scope():
    """The deadlock: this collision blocked every other agent's commits."""
    assert foreign_scope_conflicts(CLAIMS, agent="me", scope=BOARD) == {}


def test_a_real_overlap_is_still_a_conflict():
    """Excluding the board must not blind the check to genuine collisions."""
    assert foreign_scope_conflicts(CLAIMS, agent="me", scope="thomas/work/lanes") != {}


def test_the_board_does_not_mask_a_real_overlap_beside_it():
    hits = foreign_scope_conflicts(CLAIMS, agent="me", scope=f"{BOARD},thomas/work/lanes")
    assert hits, "a genuine conflict alongside the board must still be reported"
    assert all(BOARD not in pair for pairs in hits.values() for pair in pairs), "the board is never the reason"


def test_an_agent_never_conflicts_with_itself():
    own = [
        "## Agent Claims",
        f"- agent=me; name=mine; role=solo; parent=none; scope={BOARD}; task=T2",
        "",
        "## Active Tasks",
    ]
    assert foreign_scope_conflicts(own, agent="me", scope=BOARD) == {}


# --- changelog.d: the same rule, found again on a directory -------------------
#
# Measured 2026-09-09: the P0 task LIVE-AUDIT-REPAIRS-904 could not be
# reactivated for ANY agent. Its scope names the bare `changelog.d` directory,
# and the commit gate requires every agent to add a fragment there on every
# commit -- 37 of them are on disk, one per agent per change. So the directory
# collided with `changelog.d/claude-perf-advisory-both-registries.md` and with
# `changelog.d/claude-work-lanes-guard-platform-codec.md`, and a P0 sat
# up-for-grabs that no one could pick up. That is the board deadlock above,
# one directory over.

FRAGMENT_CLAIMS = [
    "## Agent Claims",
    f"- agent=other-agent; name=theirs; role=solo; parent=none; scope={FRAGMENTS}/theirs.md; task=T1",
    "",
    "## Active Tasks",
]


def test_the_fragment_directory_is_named_as_shared_infrastructure():
    assert FRAGMENTS in SHARED_INFRASTRUCTURE


def test_a_task_scoping_the_whole_fragment_directory_can_still_be_claimed():
    """The P0 deadlock: every agent writes here, so the directory owns no one."""
    assert foreign_scope_conflicts(FRAGMENT_CLAIMS, agent="me", scope=FRAGMENTS) == {}


def test_two_agents_may_hold_their_own_fragments_at_once():
    assert foreign_scope_conflicts(FRAGMENT_CLAIMS, agent="me", scope=f"{FRAGMENTS}/mine.md") == {}


def test_the_same_fragment_file_is_still_a_conflict():
    """Exempting the directory must not make individual fragments unownable."""
    assert foreign_scope_conflicts(FRAGMENT_CLAIMS, agent="me", scope=f"{FRAGMENTS}/theirs.md") != {}


def test_the_fragment_directory_does_not_mask_a_real_overlap_beside_it():
    claims = [
        "## Agent Claims",
        f"- agent=other-agent; name=theirs; role=solo; parent=none; scope=thomas/work/lanes,{FRAGMENTS}/theirs.md; task=T1",
        "",
        "## Active Tasks",
    ]
    hits = foreign_scope_conflicts(claims, agent="me", scope=f"{FRAGMENTS},thomas/work/lanes")
    assert hits, "a genuine conflict alongside the fragment directory must still be reported"
    assert all(FRAGMENTS not in pair for pairs in hits.values() for pair in pairs), "the directory is never the reason"


def test_both_registries_of_this_rule_agree():
    """One rule, two files. The gate and the claim tool each declared their own
    set, so a fix applied to either one left the other still deadlocking and
    nothing said so. They must be the same object, not merely equal today.
    """
    assert SHARED_INFRASTRUCTURE is claims_gate.SHARED_INFRASTRUCTURE
