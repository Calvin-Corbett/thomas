"""A card that lands during the lane's writer audit makes the window derive its change again, never refuse it (2026-10-14 review, D6). From Codex's lineage (work/part4)."""

from __future__ import annotations

from pathlib import Path

from tests.green_support import git
from tests.test_a_checked_change_lands_inside_your_window import (
    SID,
    World,
    _hand_in,
    blue,  # noqa: F401 -- shared isolated-repository fixture
    pins,  # noqa: F401 -- shared fake pin fixture
    world,  # noqa: F401 -- shared isolated window fixture
)


def test_a_card_landing_during_writer_audit_derives_again_and_keeps_the_change(world: World) -> None:
    git(world.blue, "config", "commit.gpgsign", "false")
    sub, _ = _hand_in(world.blue, {"thomas/fix_me.py": "VALUE = 2\n"})
    world.open()
    world.run(allowed=False, passes=8)

    def landed_during_audit(repo: Path) -> list[str]:
        (repo / "thomas/fix_me.py").write_text("VALUE = 1\n# Another card landed this comment.\n")
        git(repo, "commit", "-qam", "another approved card")
        return []

    world.promoter.audit = landed_during_audit
    outcome = world.lane.step(world.window, card_busy=frozenset(), landing_allowed=True)

    assert outcome is None, "a committed change is not uncommitted work to refuse"
    assert sub.is_dir() and SID in world.lane.owned()
    assert world.lane._preps[SID].parent == ""
    assert "derived and checked again" in world.lane.waiting()[0]["wait"]
    assert not (world.promoter.cage_root / "outbox" / f"{SID}.verdict.json").exists()
