"""Decide whether a derived worker claim has a parent that is actually there.

`claim_ops.claim` derives `role=worker; parent=<task manager>` for an agent that
names no role, from the board's `## Task Manager` row. The claims gate then
requires that parent to hold an active claim of its own (`references unknown
parent`). The row outlives its holder: it named `claude-work-lanes` for three
weeks after that agent stopped, so a default `claim.py --claim` was refused for
every new agent. A seat row is an offer, not a liveness proof. This module
answers the one question the gate asks, so the claim can fall back to `solo`
(the documented first-agent behaviour) instead of being refused.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.crew.workboard.claim_utils import (  # noqa: E402
    _agent_key,
    _find_claim_section,
    _parse_claim_line,
)


def claimed_agent_keys(board_text: str) -> set[str]:
    """Lower-cased agent ids that hold an active claim row on the board."""

    lines = board_text.splitlines(keepends=True)
    start, end = _find_claim_section(lines)
    keys: set[str] = set()
    for idx in range(start, min(end, len(lines))):
        if not lines[idx].strip().startswith("-"):
            continue
        agent, _fields, err = _parse_claim_line(idx + 1, lines[idx])
        if agent and not err:
            keys.add(_agent_key(agent))
    return keys


def parent_holds_a_claim(workboard_path: Path, parent: str) -> bool:
    """True when `parent` has an active claim, which is what the gate needs.

    An unreadable board answers True: the claim then proceeds exactly as it did
    before this check existed and the gate gives the authoritative refusal.
    """

    try:
        text = Path(workboard_path).read_text(encoding="utf-8")
    except OSError:
        return True
    return _agent_key(parent) in claimed_agent_keys(text)
