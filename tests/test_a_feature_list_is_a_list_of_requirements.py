"""A feature list in the task is a list of requirements, one item each (2026-09-05).

The Mario Kart request said: "It needs local multiplayer (two players on one
keyboard, split screen), a character and kart selection screen with at least 6
distinct racers with different stats, at least 4 distinct race tracks ... AI
opponents ... a results screen, and sound effects." That sentence is 440
characters long and contains no word from the requirement vocabulary (must,
should, every...), so the contract dropped it whole. The only requirements left
were the two closing imperatives ("Keep working until..."), which say nothing a
judge can check a track count against. Thomas shipped one track and "done" held.

A sentence that states needs, and a sentence that lists them, are requirements.
Each list entry becomes its own judged item so a missing one is named.
"""

from __future__ import annotations

from pathlib import Path

from thomas.core import acceptance_contract as ac

PROMPT = (
    "Build a full Mario Kart style racing game in this folder: a real game, not a demo. It needs local "
    "multiplayer (two players on one keyboard, split screen), a character and kart selection screen with at "
    "least 6 distinct racers with different stats, at least 4 distinct race tracks with different layouts and "
    "themes, AI opponents, lap counting with a 3-lap race and finish positions, items you can pick up and use "
    "(speed boost, shell, banana at minimum), drifting with a mini-boost, a results screen, and sound effects. "
    "Use plain HTML, CSS and JavaScript with no build step so it runs by opening index.html. Keep working until "
    "every one of these features is actually playable in the browser and you have played through a full race "
    "yourself to prove it. Do not stop at a first pass and do not hand me a partial game."
)


def _requirements(tmp_path: Path) -> list[str]:
    return [it.description for it in ac.build_contract(PROMPT, tmp_path, learned=[]) if it.kind == ac.KIND_REQUIREMENT]


def test_each_listed_feature_is_its_own_requirement(tmp_path: Path) -> None:
    reqs = _requirements(tmp_path)
    joined = "\n".join(reqs)
    for feature in (
        "local multiplayer (two players on one keyboard, split screen)",
        "at least 6 distinct racers",
        "at least 4 distinct race tracks",
        "AI opponents",
        "lap counting with a 3-lap race and finish positions",
        "items you can pick up and use (speed boost, shell, banana at minimum)",
        "drifting with a mini-boost",
        "a results screen",
        "sound effects",
    ):
        assert feature in joined, f"missing requirement: {feature}\n{joined}"
    # One feature per item: a parenthesised list is not split on its inner commas.
    assert sum("split screen" in r for r in reqs) == 1
    assert not any(r.strip() in {"a results screen", "sound effects"} and "needs" not in r for r in reqs), reqs


def test_the_closing_imperatives_are_still_requirements(tmp_path: Path) -> None:
    reqs = _requirements(tmp_path)
    assert any(r.startswith("Keep working until") for r in reqs), reqs
    assert any(r.startswith("Do not stop at a first pass") for r in reqs), reqs


def test_a_plain_needs_sentence_is_a_requirement(tmp_path: Path) -> None:
    items = ac.build_contract("Write the report. It needs a summary table at the top.", tmp_path, learned=[])
    assert [it.description for it in items if it.kind == ac.KIND_REQUIREMENT] == [
        "Write the report.",
        "It needs a summary table at the top.",
    ]


def test_prose_without_a_stated_need_stays_out(tmp_path: Path) -> None:
    items = ac.build_contract("Thanks for the earlier draft, it read well and the tone was right.", tmp_path, learned=[])
    assert [it for it in items if it.kind == ac.KIND_REQUIREMENT] == []


# The Minecraft steer (2026-09-05): "I want all of this real and working: an
# infinite world with multiple biomes, animals and mobs, ..., and local 4-player
# split-screen." became ONE requirement, so a judge could pass the sentence on
# the strength of the features that exist. A want that introduces a list with a
# colon is one requirement per entry, like "It needs A, B and C".


def test_a_want_that_introduces_a_list_is_one_requirement_per_entry(tmp_path: Path) -> None:
    msg = (
        "The world renders now, but it still feels like a demo, not Minecraft. I want all of this real and working: "
        "an infinite world with multiple biomes, animals and mobs, a lot more block types, crafting, a creative mode "
        "with flying, a third-person camera, working water you can swim in, multiple saved worlds with a settings "
        "screen, and local 4-player split-screen. Play each feature yourself to prove it works and show me."
    )
    reqs = [it.description for it in ac.build_contract(msg, tmp_path) if it.kind == ac.KIND_REQUIREMENT]
    assert any("infinite world" in r for r in reqs), reqs
    assert any(r.strip().rstrip(".").endswith("crafting") or r.strip().rstrip(".").lower() == "crafting" for r in reqs), reqs
    assert any("split-screen" in r for r in reqs), reqs
    assert any("third-person camera" in r for r in reqs), reqs
    assert len([r for r in reqs if "Play each feature" in r]) == 1
    assert len(reqs) >= 10, reqs
