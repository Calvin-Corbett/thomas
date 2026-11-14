"""A change the check before your card cannot apply to dev comes back with dev already merged into its copy.

On 2026-09-25 the performance project (thomas-a73c05313d74) finished and said DONE, and the check before your card
found that it no longer applied to dev: two files conflicted. That failure went back to its team as an ordinary
send-back whose findings said "Merge dev into this copy (`git merge dev`)" -- while a promoter's own dev-moved refusal
starts its round with the server merging dev in and naming the files still holding conflict markers
(``green_rebase``). The project had no rounds left, and stopped. A conflict found by the check now takes the
dev-moved round too. Real here: git repos, the green, the check itself and the settle; only Build's start is stood in.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tests.test_a_change_is_checked_before_your_card import (  # noqa: F401 -- world and base_repo are fixtures
    BROKEN_ADDER,
    MOVED_ADDER,
    _finished,
    _git,
    _submissions,
    base_repo,
    world,
)
from thomas.forge.anvil import forge_code_store
from thomas.server import precard, self_change_status, thomas_project
from thomas.server.app_keys import APP_LOCAL_PORT
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN
from thomas.server.routes import evolve_agent_autopilot as ap


def test_a_conflict_found_before_the_card_starts_a_round_with_dev_merged_in(world: SimpleNamespace) -> None:  # noqa: F811
    (world.green.work / "pkg" / "adder.py").write_text(BROKEN_ADDER, encoding="utf-8")  # the team's line 2
    cid = _finished(world, ["pkg/adder.py"])
    (world.blue / "pkg" / "adder.py").write_text(MOVED_ADDER, encoding="utf-8")  # dev changed the same line
    for args in (("add", "-A"), ("commit", "-q", "-m", "dev moved")):
        _git(world.blue, *args)

    async def hook(body: dict[str, Any], *, port: int) -> tuple[int, dict[str, Any]]:
        world.starts.append(body)
        forge_code_store.append_user_turn(world.green.work, body["conversation_id"], body["message"])
        return 200, {"ok": True, "conversation_id": body["conversation_id"]}

    app = {APP_PRAXIS_START_CODE_RUN: hook, APP_LOCAL_PORT: 8899}
    asyncio.run(ap._settle_thomas_project(world.green.work, world.catalog, cid, app=app))

    assert _submissions(world) == [], "nothing reached the promoter's inbox"
    conversation = forge_code_store.load_conversation(world.green.work, cid) or {}
    round_one = (conversation.get("thomas_project") or {}).get("repairs")[0]
    assert (round_one["why"], round_one["merged"], round_one["conflicts"]) == (
        thomas_project.DEV_MOVED,
        True,
        ["pkg/adder.py"],
    )
    merged = (world.green.work / "pkg" / "adder.py").read_text(encoding="utf-8")
    assert "<<<<<<<" in merged and "a * b" in merged and "a - b" in merged, "both sides are in the file, marked"
    assert len(world.starts) == 1
    message = world.starts[0]["message"]
    assert message.startswith(ap.REPAIR_PREFIX) and "merged dev into this copy" in message
    assert "pkg/adder.py" in message and "could not apply this change to dev" in message
    assert "git merge" not in message and "promoter refused" not in message


@pytest.mark.parametrize(
    ("raised", "why"),
    [(precard.ChangeDoesNotApply, thomas_project.DEV_MOVED), (precard.ChangeFailedCheck, thomas_project.SENT_BACK)],
)
def test_hand_in_again_routes_a_failed_check_the_same_way(
    monkeypatch: pytest.MonkeyPatch, raised: type[Exception], why: str
) -> None:
    def settle(*_args: Any) -> None:
        raise raised("what the check found")

    seen: list[str] = []

    async def repair(*_args: Any, why: str, detail: str, sid: str = "") -> None:
        seen.append(why)

    monkeypatch.setattr(self_change_status, "_settle_again", settle)
    monkeypatch.setattr(ap, "start_repair", repair)
    asyncio.run(self_change_status._hand_in_again(object(), Path("."), Path("."), "fc_1", "self-1", fresh=False))
    assert seen == [why]
