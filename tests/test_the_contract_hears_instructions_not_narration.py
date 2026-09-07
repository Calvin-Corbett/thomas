"""A requirement is what the user asks for, not what the user reports (2026-09-05).

Generations 5 and 6 of the Mario Kart build were sent back for another pass
over a requirement nobody could meet. In generation 5 the contract's only
requirement was "So the human controls do not drive the karts." -- the bug
report, chosen because it contains "do not" -- whose "verification" would be
the bug still being there. In generation 6 it was "Driving works on all four
circuits now, I played each one to the results screen." -- the user's own
narration, chosen because it contains "all" -- and the judge could not verify
what the user did. Meanwhile "Fix the keyboard driving for both players", "Prove
they work" and "Show me a race where..." were not requirements at all: the
vocabulary had no imperative verbs.

So: an imperative sentence addressed to Thomas is a requirement; a sentence
that narrates what the user did or saw is not; "do not" counts only when it
opens an instruction, never inside a report.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.core import acceptance_contract as ac

GEN5 = (
    "I played generation 4 myself. With auto-drive on, a full 3-lap race on Neon Nightway completes in about 21 "
    "seconds with six finishers and lap splits, and the results screen is right. With auto-drive off (T), holding W "
    "and ArrowUp for forty seconds does nothing: the four CPU karts finish three laps while P1 Bolt and P2 Nova crawl "
    "from 194 to 233 on lap 1. So the human controls do not drive the karts. Fix the keyboard driving for both "
    "players, keep auto-drive as an option and not the default, then play it yourself with the keys held and tell me "
    "the lap times you saw for P1 and P2. You now have a web.playtest tool that can hold keys and read the HUD; use "
    "it and quote its output."
)
GEN6 = (
    "Driving works on all four circuits now, I played each one to the results screen. Last thing from my original "
    "list: the items. Prove they work. Show me a race where a kart drives over an item box, gets an item, and uses a "
    "speed boost, a shell and a banana, with the HUD or the results showing that it happened, for a human player "
    "using Q and for a CPU. Use web.playtest to do it and quote its output in your reply. If any of the three items "
    "does not work, fix it and play again until it does."
)


def _reqs(text: str, tmp_path: Path) -> list[str]:
    return [it.description for it in ac.build_contract(text, tmp_path, learned=[]) if it.kind == ac.KIND_REQUIREMENT]


def test_a_bug_report_is_not_a_requirement_but_the_fix_request_is(tmp_path: Path) -> None:
    reqs = _reqs(GEN5, tmp_path)
    assert not any(r.startswith("So the human controls do not drive") for r in reqs), reqs
    assert any(r.startswith("Fix the keyboard driving for both players") for r in reqs), reqs
    assert any("quote its output" in r for r in reqs), reqs
    assert not any(r.startswith("I played generation 4 myself") for r in reqs), reqs


def test_the_users_narration_is_not_a_requirement_but_prove_and_show_me_are(tmp_path: Path) -> None:
    reqs = _reqs(GEN6, tmp_path)
    assert not any(r.startswith("Driving works on all four circuits now") for r in reqs), reqs
    assert any(r.startswith("Prove they work") for r in reqs), reqs
    assert any(r.startswith("Show me a race where") for r in reqs), reqs
    assert any(r.startswith("Use web.playtest to do it") for r in reqs), reqs
    assert any(r.startswith("If any of the three items does not work, fix it") for r in reqs), reqs


def test_what_the_screen_said_is_a_report_not_a_requirement(tmp_path: Path) -> None:
    text = (
        "Bolt vs Nova on Neon Nightway: about three seconds after GO the screen says RACE COMPLETE with every kart "
        "at 0:00.00. A 3-lap race has to take real time with the timer running."
    )
    reqs = _reqs(text, tmp_path)
    assert reqs == ["A 3-lap race has to take real time with the timer running."], reqs


def test_do_not_still_counts_when_it_opens_an_instruction(tmp_path: Path) -> None:
    reqs = _reqs("Build the page. Do not use any external fonts. The old build did not load fonts either.", tmp_path)
    assert reqs == ["Build the page.", "Do not use any external fonts."], reqs


def test_i_need_and_i_want_are_still_requirements(tmp_path: Path) -> None:
    reqs = _reqs("I need the export to include every column. I want a dark theme by default.", tmp_path)
    assert len(reqs) == 2, reqs


# The Minecraft steer (2026-09-05): "When I enter a world it is only the HUD over
# a black void, nothing renders." became a requirement because "only" sat in the
# condition clause. After a lead clause, only the clause that follows is judged.
@pytest.mark.parametrize(
    ("sentence", "is_requirement"),
    [
        ("When I enter a world it is only the HUD over a black void, nothing renders.", False),
        ("When I opened it, it only showed the HUD.", False),
        ("When I press Play, the world must render.", True),
        ("If the race ends, show a results screen.", True),
        ("When I enter a world, I want terrain on screen.", True),
    ],
)
def test_a_condition_clause_does_not_lend_its_words_to_narration(sentence: str, is_requirement: bool) -> None:
    assert ac._is_requirement_sentence(sentence) is is_requirement, sentence

