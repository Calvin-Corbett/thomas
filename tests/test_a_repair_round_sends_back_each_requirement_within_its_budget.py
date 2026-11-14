"""A repair round sends the gaps back beside your request without repeating what it carries (regression of cab55497).

The gaps go back as a pinned turn next to your pinned request. Every requirement is kept whole, so a long one went
back whole, and with 200 listed needs ruled unmet the repair call needed over 11,000 tokens against a 7,915-token
budget, raising out of the run. A long requirement your request carries is now named; past about a quarter of the
window, carried ones go back by their opening words and the rest are counted. Anything your request does not carry
goes back whole, its reason included, and the judge still rules on every requirement whole.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_a_long_requirement_is_not_sent_twice_to_a_small_window import (  # noqa: F401 -- workspace is the fixture
    MANY,
    WHOLE,
    _done,
    _levels,
    _RecordingLLM,
    _run,
    workspace,
)
from thomas.agent import acceptance_runtime
from thomas.core import acceptance_contract as ac
from thomas.core.acceptance_compact_block import repair_gaps

STEERED = "Keep " + "every saved game readable after an update " * 8 + "forever."  # over 300 characters
CONTRACT = "CONTRACT (machine verdicts already applied):"


def _repair(llm: _RecordingLLM) -> str:
    return next(
        str(m.get("content"))
        for m in llm.seen[-1]
        if m.get("role") == "user" and "NOT finished" in str(m.get("content"))
    )


def test_a_repair_round_names_the_requirement_it_sends_back(workspace: Path) -> None:
    """The gaps go back as a pinned turn beside your pinned request; repeating the requirement there did not fit."""
    llm = _RecordingLLM(window=8192, effort="xhigh", unmet_rulings=1)

    _done(_run(llm))

    repair = _repair(llm)
    assert f"({len(WHOLE):,} characters" in repair and WHOLE not in repair
    assert "the reply is unmet" in repair, "the judge's reason still reaches the worker"
    assert len(llm.judged) == 2
    for judged in llm.judged:
        assert f"] {WHOLE}" in str(judged[1]["content"]).split(CONTRACT, 1)[1]


def test_a_repair_message_is_never_what_holds_a_requirement(monkeypatch: pytest.MonkeyPatch) -> None:
    """The last repair message is pinned until add_steering replaces it with the next, so it holds nothing for that."""
    held, steered = f"{WHOLE}.", STEERED
    task, steer = {"role": "user", "content": held}, {"role": "user", "content": steered}
    items = [
        ac.ContractItem(f"req:{n}", ac.KIND_REQUIREMENT, text, "prompt", text, checked=True, detail="evaluator: unmet")
        for n, text in enumerate((held, steered), start=1)
    ]
    loop = SimpleNamespace(
        _context_anchors=[task, steer], _steering_anchor=steer, _acceptance_state={"items": items, "level": "medium"}
    )

    async def evaluated(*_args, **_kwargs):  # noqa: ANN202
        return items, None

    monkeypatch.setattr(acceptance_runtime, "_evaluate", evaluated)

    gaps = asyncio.run(acceptance_runtime.hold_at_finish(loop, response_text="DONE", tool_events=[]))

    assert f"({len(held):,} characters" in gaps and held not in gaps, "your request holds it: named"
    assert f"- {steered} (observed:" in gaps, "only the repair message held it: whole"


def test_a_repair_round_over_a_long_feature_list_fits_and_the_judge_still_gets_every_need(workspace: Path) -> None:
    """The reviewer's probe: every listed need ruled unmet once. The repair call needed over 11,000 of 7,915 tokens."""
    request = _levels(200)
    needs = ac.requirement_statements(request)
    llm = _RecordingLLM(window=8192, effort="xhigh", unmet_rulings=1)

    _done(_run(llm, request))

    assert "more requirements read from the request were ruled unmet" in _repair(llm)
    assert len(llm.judged) == 2
    contract = str(llm.judged[1][1]["content"]).split(CONTRACT, 1)[1]
    assert all(f"] {need}" in contract for need in needs), "the judge's next round still rules on every need whole"


def test_past_its_budget_a_repair_round_shortens_only_what_the_request_carries() -> None:
    request = " ".join(MANY[:40])  # 295 characters each: long enough to be cut to their opening words
    needs = ac.requirement_statements(request)
    assert needs == MANY[:40]
    items = [
        ac.ContractItem(f"req:{n}", ac.KIND_REQUIREMENT, text, "prompt", text, checked=True, detail="evaluator: unmet")
        for n, text in enumerate([*needs, STEERED], start=1)  # STEERED: no pinned message holds it
    ]
    failed_run = "exit 1: " + "collected 40 items, running them one by one " * 6 + "AssertionError: panel 07 is empty"
    items.append(
        ac.ContractItem("cmd:1", ac.KIND_COMMAND, "`pytest` exits 0.", "prompt", "pytest", True, False, failed_run)
    )

    gaps = repair_gaps(items, [request], request=request, budget_tokens=400)

    assert f"- {STEERED} (observed: evaluator: unmet)" in gaps, "a requirement nobody carries goes back whole"
    assert f"(observed: {failed_run})" in gaps, "its reason too: the error is at the end of a failed run's output"
    listed = [need for need in needs if f'- "{need[:60]}..."' in gaps]
    assert listed and not any(need in gaps for need in needs), "carried ones go back by their opening words"
    more = len(needs) - len(listed)
    summary = f"- and {more} more requirements read from the request were ruled unmet; each is still judged whole, as "
    assert f"{summary}the request states it." in gaps, "and nothing claims a report that lists them"
    assert repair_gaps(items, [request], request=request, budget_tokens=10**6).count("\n- ") == len(items) - 1
