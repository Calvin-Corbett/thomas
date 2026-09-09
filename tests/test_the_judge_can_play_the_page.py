"""The separate judge can play the page instead of trusting the worker's account (2026-09-05).

On the Mario Kart build the judge left every requirement unchecked while the
worker's reply described a working race that ended three seconds after GO.
The judge could ask for shell checks, and a shell cannot press START. It can
now ask for one playtest per call -- the same ``web.playtest`` session the
worker has -- and rules on what the browser showed.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from thomas.agent import acceptance_evaluator as ev
from thomas.core.acceptance_contract import ContractItem
from thomas.tools.base import ToolResult

ITEMS = [
    ContractItem(
        item_id="req:1", kind="requirement", description="It needs a 3-lap race that reaches a results screen."
    ),
]


class _Judge:
    """First reply asks to play; second reply rules on what it saw."""

    def __init__(self) -> None:
        self.messages: list[list[dict]] = []

    async def chat(self, messages):
        self.messages.append(list(messages))
        if len(self.messages) == 1:
            return {
                "text": json.dumps(
                    {
                        "item_verdicts": {"req:1": "unchecked"},
                        "playtests": [
                            {
                                "page": "index.html",
                                "steps": [{"click": "START"}, {"hold": "w", "seconds": 3}, {"observe": "#results"}],
                                "why": "only the results screen proves a race completes",
                            }
                        ],
                    }
                )
            }
        seen = messages[-1]["content"]
        verdict = "met" if "RACE COMPLETE" in seen else "unmet"
        return {"text": json.dumps({"item_verdicts": {"req:1": verdict}, "findings": []})}


def _fake_playtest(text: str):
    async def execute(self, args):
        assert args["page"] == "index.html" and len(args["steps"]) == 3
        return ToolResult(ok=True, data=text)

    return execute


def test_the_judge_asks_to_play_and_rules_on_what_the_browser_showed(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ev, "playtest_available", lambda: True)
    monkeypatch.setattr(
        ev.WebPlaytestTool, "execute", _fake_playtest('3. observe "#results" -> "RACE COMPLETE P1 Bolt WINS"')
    )
    judge = _Judge()
    result = asyncio.run(
        ev.evaluate_with_model(
            judge,
            task_text="build a kart game",
            response_text="Built it.",
            items=ITEMS,
            workspace=tmp_path,
            run_checks=True,
        )
    )
    assert result.available and result.calls == 2
    assert result.items[0].checked and result.items[0].satisfied, result.items
    assert any("playtest" in row for row in result.checks_run), result.checks_run
    assert "RACE COMPLETE" in json.dumps(result.checks_run)
    assert "playtests" in judge.messages[0][-1]["content"]  # the offer was made


def test_a_race_that_never_finished_is_unmet(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ev, "playtest_available", lambda: True)
    monkeypatch.setattr(ev.WebPlaytestTool, "execute", _fake_playtest('3. observe "#results" -> no such element'))
    result = asyncio.run(
        ev.evaluate_with_model(
            _Judge(),
            task_text="build a kart game",
            response_text="Built it.",
            items=ITEMS,
            workspace=tmp_path,
            run_checks=True,
        )
    )
    assert result.items[0].checked and not result.items[0].satisfied


def test_no_playtest_is_offered_when_checks_may_not_run(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ev, "playtest_available", lambda: True)
    judge = _Judge()
    result = asyncio.run(
        ev.evaluate_with_model(
            judge, task_text="t", response_text="r", items=ITEMS, workspace=tmp_path, run_checks=False
        )
    )
    assert result.calls == 1
    assert "playtests" not in judge.messages[0][-1]["content"]


def test_the_judge_reads_the_playtests_the_worker_already_ran(monkeypatch, tmp_path: Path) -> None:
    """Generation 6: the worker ran fourteen playtests proving every item and the
    judge, shown only the worker's prose, said 'no independent web.playtest was
    run' twice. The tool's own output is not the worker's claim; the judge reads
    the last recorded sessions verbatim as evidence."""
    monkeypatch.setattr(ev, "playtest_available", lambda: True)
    judge = _Judge()
    events = [
        {"name": "fs.read_file", "ok": True, "output_preview": "const tracks = 4;"},
        {
            "name": "web.playtest",
            "ok": True,
            "output_preview": '5. observe "#results" -> "RACE COMPLETE P2 Nova WINS 6 FINISHERS"',
        },
    ]
    result = asyncio.run(
        ev.evaluate_with_model(
            judge,
            task_text="build a kart game",
            response_text="Built it.",
            items=ITEMS,
            workspace=tmp_path,
            run_checks=True,
            tool_events=events,
        )
    )
    first = judge.messages[0][-1]["content"]
    assert "RACE COMPLETE P2 Nova WINS" in first, first
    assert "recorded during the work" in first.lower(), first
    assert "const tracks = 4" not in first  # only playtest sessions are quoted, not every tool call
    assert result.available


# Generation 9 of the Mario Kart build (2026-09-05): the judge quoted the
# worker's recorded session from the loop's 2000-character preview, which ended
# before the sixth finisher, and ruled "truncated, so inconclusive"; and the item
# "do not close the goals" stayed unchecked because nothing showed the judge the
# goals file. The full report the playtest saves on disk is the evidence, and a
# goal item brings the goals file with it.


class _Reader:
    """Replies unchecked; the test reads what the judge was shown."""

    def __init__(self) -> None:
        self.messages: list[list[dict]] = []

    async def chat(self, messages):
        self.messages.append(list(messages))
        return {"text": json.dumps({"item_verdicts": {}, "findings": []})}


def test_the_judge_reads_the_full_saved_report_not_the_truncated_preview(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ev, "playtest_available", lambda: False)
    session = tmp_path / ".thomas" / "playtest" / "20260905T160000"
    session.mkdir(parents=True)
    full = "web.playtest index.html\n" + "x" * 2500 + '\n9. observe "#results" -> "RACE COMPLETE 6 FINISHERS"'
    (session / "report.txt").write_text(full, encoding="utf-8")
    events = [{"name": "web.playtest", "output_preview": full[:2000]}]
    judge = _Reader()
    asyncio.run(
        ev.evaluate_with_model(
            judge,
            task_text="t",
            response_text="r",
            items=ITEMS,
            workspace=tmp_path,
            run_checks=True,
            tool_events=events,
        )
    )
    shown = judge.messages[0][-1]["content"]
    assert "6 FINISHERS" in shown, shown[-600:]
    assert "PLAYTEST SESSIONS RECORDED" in shown


def test_a_goal_item_brings_the_goals_file_to_the_judge(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ev, "playtest_available", lambda: False)
    from thomas.core import goal_book

    goal_book.add_goal(tmp_path, "The game must never load anything from the internet.")
    items = [
        ContractItem(item_id="req:2", kind="requirement", description="Do not close the goals; they stay."),
        ContractItem(
            item_id="goal:g1",
            kind="requirement",
            description="Standing goal: never load from the internet",
            source="goal",
        ),
    ]
    judge = _Reader()
    asyncio.run(
        ev.evaluate_with_model(
            judge, task_text="t", response_text="r", items=items, workspace=tmp_path, run_checks=False
        )
    )
    shown = judge.messages[0][-1]["content"]
    assert "GOALS FILE" in shown and '"done": false' in shown and "never load anything" in shown, shown[-800:]


# Nine features in one contract (the Minecraft steer) cannot be settled by one
# playtest; a judge that may only play once leaves the rest unchecked, and an
# unchecked requirement is a gap that sends the run around again.


class _TwoPlays:
    def __init__(self) -> None:
        self.messages: list[list[dict]] = []

    async def chat(self, messages):
        self.messages.append(list(messages))
        if len(self.messages) == 1:
            return {
                "text": json.dumps(
                    {
                        "item_verdicts": {"req:1": "unchecked", "req:2": "unchecked"},
                        "playtests": [
                            {"page": "index.html", "steps": [{"click": "START"}], "why": "the race"},
                            {
                                "page": "index.html",
                                "steps": [{"press": "c"}, {"observe": "#mode"}],
                                "why": "creative mode",
                            },
                        ],
                    }
                )
            }
        seen = messages[-1]["content"]
        return {
            "text": json.dumps(
                {
                    "item_verdicts": {
                        "req:1": "met" if "RACE" in seen else "unmet",
                        "req:2": "met" if "CREATIVE" in seen else "unmet",
                    },
                    "findings": [],
                }
            )
        }


def test_the_judge_may_play_more_than_once_per_verdict(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ev, "playtest_available", lambda: True)

    async def execute(self, args):
        return ToolResult(ok=True, data="RACE COMPLETE" if len(args["steps"]) == 1 else "mode: CREATIVE")

    monkeypatch.setattr(ev.WebPlaytestTool, "execute", execute)
    items = [
        ContractItem(item_id="req:1", kind="requirement", description="A race reaches a results screen."),
        ContractItem(item_id="req:2", kind="requirement", description="A creative mode with flying."),
    ]
    judge = _TwoPlays()
    result = asyncio.run(
        ev.evaluate_with_model(
            judge, task_text="t", response_text="r", items=items, workspace=tmp_path, run_checks=True
        )
    )
    played = [row for row in result.checks_run if row.get("playtest")]
    assert len(played) == 2, result.checks_run
    assert all(it.checked and it.satisfied for it in result.items), result.items
    assert "up to three playtests" in judge.messages[0][-1]["content"].lower()


# Pass 5 of the Minecraft feature run: the judge answered once, every item came
# back unchecked, no findings, no checks. A reply that carries no verdicts at
# all is a judge that did not rule (unparseable output, or a refusal), and it
# must say so instead of reading as "unchecked everything".


class _Mute:
    async def chat(self, messages):
        return {"text": "I cannot evaluate this. The reply is very long and I am not sure."}


def test_a_judge_reply_without_verdicts_is_reported_not_read_as_unchecked(tmp_path: Path) -> None:
    result = asyncio.run(
        ev.evaluate_with_model(
            _Mute(), task_text="t", response_text="r", items=ITEMS, workspace=tmp_path, run_checks=False
        )
    )
    assert result.available and result.calls == 1
    assert "no verdicts" in result.error, result.error
    assert any("I cannot evaluate this" in f for f in result.findings), result.findings
    assert not result.items[0].checked


# The feature-list run: Thomas played nine features across a dozen sessions and
# the judge, shown the three newest in full, kept "play each feature yourself
# and show me" unmet. Every saved session reaches the judge: the newest three
# in full, the rest as one line each (what was played and what it ended on).


def test_older_saved_sessions_reach_the_judge_as_an_index(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ev, "playtest_available", lambda: False)
    store = tmp_path / ".thomas" / "playtest"
    for i, feature in enumerate(["swim", "fly", "craft", "biomes", "split"], start=1):
        session = store / f"20260906T02000{i}"
        session.mkdir(parents=True)
        (session / "report.txt").write_text(
            f'web.playtest index.html (viewport 1280x720)\n1. click "PLAY" -> ok\n2. eval -> {{"{feature}": true}}\nerrors: none',
            encoding="utf-8",
        )
    events = [{"name": "web.playtest", "output_preview": "web.playtest index.html"}]
    judge = _Reader()
    asyncio.run(
        ev.evaluate_with_model(
            judge,
            task_text="t",
            response_text="r",
            items=ITEMS,
            workspace=tmp_path,
            run_checks=True,
            tool_events=events,
        )
    )
    shown = judge.messages[0][-1]["content"]
    assert '{"split": true}' in shown and '{"biomes": true}' in shown and '{"craft": true}' in shown, shown[-1500:]
    assert "EARLIER SESSIONS" in shown and "swim" in shown and "fly" in shown, shown[-1500:]
    assert shown.count("web.playtest index.html (viewport") == 3  # only the newest three in full


# The record-aware proof run: the judge marked "pick up where you left off" and
# "do not replay" unmet, which the transcript shows Thomas did, and the hold text
# said only "(observed: evaluator: unmet)". A verdict without its reason cannot
# be acted on or argued with; the judge gives one per item and it rides in the
# item's detail, which is what the hold shows the worker.


class _Reasoned:
    async def chat(self, messages):
        return {
            "text": json.dumps(
                {
                    "item_verdicts": {"req:1": "unmet"},
                    "item_reasons": {"req:1": "the results screen was never observed; the last session ended on lap 2"},
                    "findings": [],
                }
            )
        }


def test_the_judges_reason_for_a_verdict_rides_in_the_item_detail(tmp_path: Path) -> None:
    result = asyncio.run(
        ev.evaluate_with_model(
            _Reasoned(), task_text="t", response_text="r", items=ITEMS, workspace=tmp_path, run_checks=False
        )
    )
    item = result.items[0]
    assert item.checked and not item.satisfied
    assert "ended on lap 2" in item.detail, item.detail
    assert "item_reasons" in ev._SCHEMA_HINT


# The retention-fixed proof run: the judge ran four shell checks, then in its
# final reply said "the required browser check was not performed" and left the
# items unchecked; after its checks the second reply had been final, so there
# was no way to ask. A judge that asks to play after seeing its check results
# gets that round, once.


class _ChecksThenPlays:
    def __init__(self) -> None:
        self.messages: list[list[dict]] = []

    async def chat(self, messages):
        self.messages.append(list(messages))
        if len(self.messages) == 1:
            return {
                "text": json.dumps(
                    {"item_verdicts": {"req:1": "unchecked"}, "checks": [{"cmd": "dir /b", "why": "files"}]}
                )
            }
        if len(self.messages) == 2:
            return {
                "text": json.dumps(
                    {
                        "item_verdicts": {"req:1": "unchecked"},
                        "playtests": [
                            {
                                "page": "index.html",
                                "steps": [{"click": "START"}, {"hold": "w", "seconds": 3}, {"observe": "#results"}],
                                "why": "the race",
                            }
                        ],
                    }
                )
            }
        seen = messages[-1]["content"]
        return {
            "text": json.dumps(
                {"item_verdicts": {"req:1": "met" if "RACE COMPLETE" in seen else "unmet"}, "findings": []}
            )
        }


def test_a_judge_may_ask_to_play_after_its_shell_checks(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(ev, "playtest_available", lambda: True)
    monkeypatch.setattr(
        ev.WebPlaytestTool, "execute", _fake_playtest('3. observe "#results" -> "RACE COMPLETE P1 Bolt WINS"')
    )
    judge = _ChecksThenPlays()
    result = asyncio.run(
        ev.evaluate_with_model(
            judge,
            task_text="t",
            response_text="r",
            items=ITEMS,
            workspace=tmp_path,
            run_checks=True,
            runner=lambda cmd, ws, timeout: (0, "index.html\n"),
        )
    )
    assert result.calls == 3, result.calls
    assert result.items[0].checked and result.items[0].satisfied, result.items
    assert any(row.get("playtest") for row in result.checks_run), result.checks_run


def test_the_judge_is_told_whose_diff_is_whose() -> None:
    """A self-edit run on the Thomas checkout was ruled "not minimal" on every
    pass: the judge ran git diff and graded the whole checkout's uncommitted
    changes, other agents' work included, as this run's. The scope rule now
    sits in the judge's own instructions."""
    from thomas.agent import acceptance_evaluator as ev

    low = ev.JUDGE_SYSTEM.lower()
    assert "this run" in low and "uncommitted" in low and "not this run" in low
