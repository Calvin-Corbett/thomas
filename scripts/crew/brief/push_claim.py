#!/usr/bin/env python3
"""What a push of already-landed commits tells the claim gate.

The claim gate (``scripts/forge/gates/workboard_agent_claim.py``) answers "may this agent put files in a commit?". At
push time the commits already exist and were each gated when they landed, so there is nothing staged to judge; yet the
hook is registered for every stage, and it still asks for a claim on the board of the tree the push runs from. A push
from a fresh worktree reads that worktree's committed board, where no agent holds a claim, so the push stopped with
"no active workboard claim found for 'claude'" (2026-11-03).

A claim taken in the live checkout cannot help: claims stay on the checkout's own board and the fresh worktree has its
own copy. The gate has one sanctioned answer for an agent that holds no claim, the explicit scope fallback with an audited
reason. The push step uses exactly that, with a scope that names no real file: the gate's other checks still run (the
agent's unresolved issues, another agent's overlapping claim) and a staged file outside that scope still fails, so a
commit cannot ride on it.
"""

from __future__ import annotations

from collections.abc import Mapping

FALLBACK_SCOPE_ENV = "THOMAS_WORKBOARD_SCOPE_FALLBACK"
FALLBACK_REASON_ENV = "THOMAS_WORKBOARD_SCOPE_FALLBACK_REASON"
#: Names no file in the repository. Staged files can never be inside it.
PUSH_SCOPE = "runtime/push-of-landed-commits"
PUSH_REASON = "push of commits that already landed through the gates; nothing is staged"


def landed_push_env(agent: str, base: Mapping[str, str]) -> dict[str, str]:
    """A copy of ``base`` for a push of landed commits by ``agent``."""
    who = str(agent or "").strip()
    if not who:
        raise ValueError("a push needs an agent id")
    env = dict(base)
    env["AGENT_ID"] = who
    env[FALLBACK_SCOPE_ENV] = PUSH_SCOPE
    env[FALLBACK_REASON_ENV] = PUSH_REASON
    return env
