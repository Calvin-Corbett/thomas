"""Autopilot stops when its team says it finished, and gets what is missing when something stops it.

You said: "autopilot ... is meant to actually fix issues with Thomas that prevent him from finish not the actually
work continuous forever". A finished run is done, with no done-check round. A run that ends with a ``BLOCKED`` line
gets the missing thing within the permissions you already gave; one that only you can unblock pauses for you at once.
Real here: decide, the conversation store, the pause stamp and the prompts. Stubbed: only what would start a run.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from thomas.core.autonomy import AUTOPILOT_BLOCKED_RULE, autonomy_spec
from thomas.forge.anvil import forge_code_store
from thomas.forge.anvil.bridge_prompts import compose_headless_prompt
from thomas.server import autopilot_blockers as blockers
from thomas.server import autopilot_enough as enough
from thomas.server.routes import evolve_agent_autopilot as ap

CID = "blocked-1"
ASK = {"role": "user", "text": "post an ad to Facebook", "ts": "2026-11-13T00:00:00+00:00"}
FINISHED = {"role": "agent", "ok": True, "outcome": "completed", "changed_files": ["ad.py"], "reason": "done"}
TOOL = "BLOCKED: the Facebook SDK is not installed | NEEDS: pip install facebook-business"
PAY = "BLOCKED: no ad account to post from | NEEDS: you create a Facebook ad account and add a card | OWNER"


def _autopilot(turns: list[dict[str, Any]], level: int = ap.AUTOPILOT) -> dict[str, Any]:
    return {"id": CID, "turns": turns, "settings": {"requested": {"autonomy_level": level}}}


def _ran(last_line: str, *, ok: bool = True, changed: list[str] | None = None) -> dict[str, Any]:
    transcript = f"I wrote the ad copy.\nThe preview is in ad.html.\n\n{last_line}"
    outcome = "completed" if ok else "failed"
    return {**FINISHED, "ok": ok, "outcome": outcome, "changed_files": changed or [], "transcript": transcript}


def _round(text: str) -> dict[str, Any]:
    return {"role": "user", "text": text}


def test_a_finished_run_is_done_with_no_done_check_started() -> None:
    decision = ap.decide(_autopilot([ASK, FINISHED]))
    assert decision.action == "done"
    assert not decision.message.startswith(ap.REVIEW_PREFIX), "no done-check round starts"
    replied = {**FINISHED, "outcome": "conversation", "changed_files": []}
    assert ap.decide(_autopilot([ASK, replied])).action == "done"


def test_a_conversation_already_mid_done_check_is_judged_as_before() -> None:
    check = _round(f"{ap.REVIEW_PREFIX} on the goal: {ASK['text']}")
    clean = ap.decide(_autopilot([ASK, FINISHED, check, {**FINISHED, "changed_files": []}]))
    assert clean.action == "done" and "judged it done" in clean.reason
    tweaked = ap.decide(_autopilot([ASK, FINISHED, check, FINISHED]))
    assert tweaked.action == "review" and tweaked.message.startswith(ap.REVIEW_PREFIX)


def test_a_failed_run_with_no_blocked_line_still_continues() -> None:
    decision = ap.decide(_autopilot([ASK, {**_ran("it crashed", ok=False), "reason": "exit 2"}]))
    assert decision.action == "continue" and "Diagnose what went wrong" in decision.message


def test_blocked_without_owner_continues_with_the_blocker_message() -> None:
    for ok in (True, False):
        decision = ap.decide(_autopilot([ASK, _ran(TOOL, ok=ok)]))
        assert decision.action == "continue", ok
        assert decision.message.startswith(blockers.BLOCKER_PREFIX)
        assert "the Facebook SDK is not installed" in decision.message
        assert "pip install facebook-business" in decision.message
        assert "install the tool or package" in decision.message and "finish the goal" in decision.message
        assert ASK["text"] in decision.message, "the goal rides along"


def test_the_same_blocker_twice_with_nothing_changed_pauses(tmp_path: Path, monkeypatch) -> None:
    again = blockers.blocker_message(ASK["text"], _ran(TOOL), blockers.read(_ran(TOOL)))
    twice = _autopilot([ASK, _ran(TOOL), _round(again), _ran(TOOL + "  ")])
    decision = ap.decide(twice)
    assert decision.action == "enough" and decision.why == "blocked"
    assert "the Facebook SDK is not installed" in decision.reason
    progressed = _autopilot([ASK, _ran(TOOL), _round(again), _ran(TOOL, changed=["ad.py"])])
    assert ap.decide(progressed).action == "continue", "a run that changed something made progress"
    other = _autopilot([ASK, _ran(TOOL), _round(again), _ran("BLOCKED: no network | NEEDS: a connection")])
    assert ap.decide(other).action == "continue", "a different blocker is not a repeat"
    yours = _autopilot([ASK, _ran(TOOL), {**ASK, "text": "try again"}, _ran(TOOL)])
    assert ap.decide(yours).action == "continue", "your message starts the count again"

    root, catalog = tmp_path / "green", tmp_path / "catalog"
    root.mkdir(), catalog.mkdir()
    forge_code_store.write_conversation(root, {"id": CID, "turns": twice["turns"], "thomas_project": {"x": 1}})
    monkeypatch.setattr(ap, "_load_joined_conversation", lambda *a: {**twice, "thomas_project": {"x": 1}})
    stamped: list[dict[str, Any]] = []
    monkeypatch.setattr(enough, "stamp", lambda *a, **k: stamped.append(k) or True)
    assert asyncio.run(ap.continue_after_turn({}, root, catalog, CID)).action == "enough"
    assert stamped and stamped[0]["why"] == "blocked" and "Facebook SDK" in stamped[0]["words"]


def test_blocked_with_owner_pauses_at_once_with_what_is_needed_from_you() -> None:
    decision = ap.decide(_autopilot([ASK, _ran(PAY)]))
    assert decision.action == "enough" and decision.why == "blocked"
    assert "you create a Facebook ad account and add a card" in decision.reason
    assert "no ad account to post from" in decision.reason
    assert enough.REPLY in decision.reason
    assert not ap._thomas_project_should_settle(decision, _autopilot([ASK, _ran(PAY)])), "not handed in"


@pytest.mark.parametrize(
    "line",
    [
        "BLOCKED: no SDK | NEEDS: install it   ",
        "blocked: no SDK | needs: install it",
        "**BLOCKED: no SDK | NEEDS: install it**",
        "- `Blocked:  no SDK |  Needs: install it`",
    ],
)
def test_the_line_is_read_whatever_its_case_and_trailing_spaces(line: str) -> None:
    found = blockers.read(_ran(line))
    assert found is not None and found.missing == "no SDK" and found.needs == "install it" and not found.owner


def test_the_line_need_not_be_the_last_and_owner_is_read_in_any_case() -> None:
    turn = {**FINISHED, "transcript": f"Working.\n{PAY.replace('OWNER', 'owner ')}\n\nEVIDENCE: none\nVERIFY: none\n"}
    found = blockers.read(turn)
    assert found is not None and found.owner and found.needs == "you create a Facebook ad account and add a card"
    assert blockers.read({**FINISHED, "transcript": "All done.\nNo blockers."}) is None
    echoed = {**FINISHED, "transcript": "BLOCKED: <what is missing> | NEEDS: <what would unblock it>"}
    assert blockers.read(echoed) is None, "the rule's own example is not a blocker"


def test_the_rule_reaches_the_team_at_autopilot_only() -> None:
    assert "BLOCKED:" in AUTOPILOT_BLOCKED_RULE and "| OWNER" in AUTOPILOT_BLOCKED_RULE
    for owners_only in ("spend money", "accept terms", "passwords or payment details", "post anything publicly"):
        assert owners_only in AUTOPILOT_BLOCKED_RULE, owners_only
    assert AUTOPILOT_BLOCKED_RULE in autonomy_spec(5).system_directive
    assert AUTOPILOT_BLOCKED_RULE not in autonomy_spec(4).system_directive
    assert AUTOPILOT_BLOCKED_RULE in compose_headless_prompt(ASK["text"], autonomy_level=5)
    assert AUTOPILOT_BLOCKED_RULE not in compose_headless_prompt(ASK["text"], autonomy_level=4)
    failed = ap.decide(_autopilot([ASK, {**_ran("crash", ok=False), "reason": "exit 2"}]))
    assert AUTOPILOT_BLOCKED_RULE in failed.message, "a continuation carries it"
    assert AUTOPILOT_BLOCKED_RULE in ap.decide(_autopilot([ASK, _ran(TOOL)])).message


def test_lower_autonomy_levels_are_unchanged() -> None:
    for level in (1, 2, 3, 4):
        assert ap.decide(_autopilot([ASK, _ran(PAY)], level)).action == "off"
        assert ap.decide(_autopilot([ASK, FINISHED], level)).action == "off"
