"""The committed WORKBOARD.md passes the audit backstop check the push hook runs.

Proves: scripts.crew.workboard.audit_backstop.

The 2026-11-03 push stopped on "backstop task `audit-24h-backstop` must be the
last Up For Grabs entry" because the committed board had it in the middle.
"""

from __future__ import annotations

from pathlib import Path

import scripts.crew.workboard.audit_backstop as backstop

BOARD = Path(__file__).resolve().parents[1] / "plans" / "thomas" / "WORKBOARD.md"


def test_the_committed_board_has_the_backstop_last() -> None:
    ok, violations = backstop._check(BOARD)
    assert ok, violations
