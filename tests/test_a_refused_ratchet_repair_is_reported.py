"""A repaired candidate that Thomas refuses at hand-in is reported, not started over every day.

The size rule or the check before your card can refuse a repaired candidate (``settle_if_finished``). Unrecorded, the
``settling`` line it left read as a crash to the next run, which started a new Build team on it every day and held up
every candidate behind it (safety review before the ratchet landed, 2026-09-28). Reported, it counts toward the
candidate's limit like any other report.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from tests.ratchet_support import candidate, submissions
from tests.test_ratchet_repair import Team, _conflicting, _ctx
from thomas.server.precard.check import ChangeFailedCheck
from thomas.server.ratchet.attempt import prove_candidate
from thomas.server.thomas_project import ChangeTooLarge


def test_a_repair_thomas_refuses_at_hand_in_is_reported_not_proven_again(tmp_path: Path) -> None:
    for refusal in (
        ChangeTooLarge("the change is 812 lines in task_bot_runtime.py"),
        ChangeFailedCheck("a test broke"),
    ):
        (tmp_path / type(refusal).__name__).mkdir()
        repo, sha = _conflicting(tmp_path / type(refusal).__name__)
        team = Team(repo)

        def refuse(root: Path, catalog: Path, cid: str, *, summary: str, _why=refusal) -> Path | None:
            raise _why

        team.settle_held = refuse
        ctx = _ctx(repo, tmp_path / type(refusal).__name__ / "ratchet", team)

        assert asyncio.run(prove_candidate(ctx, candidate(sha))) == "reported"
        latest = ctx.ledger.latest()[sha]
        assert latest["state"] == "reported" and str(refusal) in latest["reason"]
        assert team.retired == ["conv-1"] and submissions() == []
