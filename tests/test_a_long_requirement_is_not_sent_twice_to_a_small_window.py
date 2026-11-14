"""Your request is not sent twice to a window too small to hold it twice (regression of cab55497).

Every requirement is kept whole, and the contract block in front of the worker repeats each one, so a 12,076-character
request went out twice on every model call. On an 8,192-token window the two copies did not fit, and the run raised
before its first call (tests/test_agent_loop_token_guard.py); a repair round at xhigh sent it a third time, and fifty
ordinary requirements or a 200-level feature list overflowed the same way. Where the second copy would push anything
out of the window, the block now names a long requirement by its length and opening words, then folds every
requirement into one line, because your request, which every call carries, holds each whole (see also
test_a_repair_round_sends_back_each_requirement_within_its_budget.py). The judge still rules on each whole.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from tests.test_agent_loop_token_guard import _NoopTool
from thomas.agent.loop import AgentLoop
from thomas.core import acceptance_contract as ac
from thomas.core.acceptance_compact_block import compact_contract_prompt_blocks
from thomas.core.acceptance_launch_notice import LONG_REQUIREMENT_CHARS
from thomas.core.config import AppConfig, ModelConfig, QualityConfig
from thomas.core.events import EventType
from thomas.core.llm import StreamEvent
from thomas.tools.registry import ToolRegistry

REQUEST = "run the tool and then answer with enough detail to exceed the local estimate " + ("context " * 1_500)
WHOLE = REQUEST.strip()  # the one requirement the contract reads from REQUEST
SHORT = "Add the Alpha button to the toolbar."
# Sized for a 16,384-token window: the request fits beside the whole block, or beside your memory, but not both.
SIZED = "Make the log viewer " + "keep every line it has shown in the order it arrived " * 370 + "for you"
MEMORY = "MEMORY-MARKER " + "you prefer the dark theme and short replies " * 450
# Fifty requirements of 295 characters: none is long, and the request fits an 8,192-token window only once.
PANEL = "it lists every open item with its owner and its due date and "
MANY = [f"Add panel {n:02d} to the dashboard so that {PANEL * 4}nothing else." for n in range(50)]
FOLDED = (
    "{count} requirements read from the request: each sentence or listed need in it that asks for something is one "
    "item, and each is judged whole."
)
WRAPPER = (
    "Reminder from Thomas: work only inside the project folder and keep replies short.\n\n"  # as worker_runtime does
)


class _RecordingLLM:
    """Calls the no-op tool once, then answers; records every request and every judge call."""

    def __init__(self, window: int, effort: str = "", unmet_rulings: int = 0) -> None:
        self.config = ModelConfig(
            name="dummy", model="dummy", context_window=window, max_tokens=256, reasoning_effort=effort
        )
        self.unmet_rulings = unmet_rulings
        self.seen: list[list[dict]] = []
        self.judged: list[list[dict]] = []

    async def stream_chat(self, messages, tools):  # noqa: ANN001
        _ = tools
        self.seen.append([dict(message) for message in messages])
        if len(self.seen) == 1:
            yield StreamEvent(type="tool_call_start", data={"id": "noop_1", "name": "dummy.noop"})
            yield StreamEvent(type="tool_call_end", data={"id": "noop_1", "name": "dummy.noop", "arguments": "{}"})
        else:
            yield StreamEvent(type="token", data={"text": "DONE"})
        yield StreamEvent(type="done", data={})

    async def chat(self, messages):  # noqa: ANN001
        self.judged.append([dict(message) for message in messages])
        ruling = "unmet" if len(self.judged) <= self.unmet_rulings else "met"
        ids = [f"req:{n}" for n in range(1, 401)]  # every requirement the contract can number here
        verdict = {
            "item_verdicts": dict.fromkeys(ids, ruling),
            "item_reasons": dict.fromkeys(ids, f"the reply is {ruling}"),
        }
        return {"text": json.dumps(verdict), "tool_calls": [], "usage": None}


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)  # the contract reads and checks this folder, never the checkout
    monkeypatch.delenv("THOMAS_VERIFICATION_CONTRACT", raising=False)
    monkeypatch.delenv("THOMAS_PROVIDER_TPM_LIMIT", raising=False)
    # The sizes above are set for 3.5 characters per token; THOMAS_TOKEN_RATIO is read once, at import.
    monkeypatch.setattr("thomas.core.tokens._CHARS_PER_TOKEN", 3.5)
    return tmp_path


def _levels(count: int, lead: str = "The game needs: ") -> str:
    """A listed feature set: the contract reads one requirement per listed level (SC5 keeps every one)."""
    return lead + ", ".join(f"level {n:03d} with its own map and its own enemies" for n in range(count))


def _run(llm: _RecordingLLM, request: str = REQUEST, intent: str | None = None) -> list:
    cfg = AppConfig(
        models={"local": ModelConfig(name="local", model="dummy")},
        default_model="local",
        max_agent_iterations=4,
        quality=QualityConfig(enabled=False, enforce=False),
    )
    tools = ToolRegistry()
    tools.register(_NoopTool())
    agent = AgentLoop(cfg, llm, tools, conversation=[], autonomy_level=4)

    async def collect() -> list:
        events = agent.run(request, intent_text=intent, tools_policy="always", max_iterations=4)
        return [event async for event in events]

    return asyncio.run(collect())


def _done(events: list):
    assert not [event for event in events if event.type == EventType.AGENT_ERROR]
    return next(event for event in events if event.type == EventType.AGENT_DONE)


def test_the_shorter_blocks_name_then_fold_only_what_the_request_carries(tmp_path: Path) -> None:
    long = f"{WHOLE}."
    prompt = f"{long} {SHORT}"
    items = ac.build_contract(prompt, tmp_path, learned=[])
    whole = ac.contract_prompt_block(items)

    named, folded = compact_contract_prompt_blocks(items, [prompt])

    assert long in whole and long not in named
    assert f"- [judge] ({len(long):,} characters" in named and f'"{long[:100]}..."' in named
    assert f"- [judge] {SHORT}" in named, "a short requirement is still shown whole"
    assert named.count("- [judge] ") == whole.count("- [judge] ") == 2, "no item leaves the list"
    assert f"- [judge] {FOLDED.format(count=2)}" in folded and SHORT not in folded and long[:100] not in folded
    assert [item.description for item in items if item.kind == ac.KIND_REQUIREMENT] == [long, SHORT], "untouched"
    assert compact_contract_prompt_blocks(items, ["Something else entirely."]) == [], "nothing carried, nothing named"


def test_a_requirement_no_pinned_message_holds_is_never_folded(tmp_path: Path) -> None:
    items = ac.build_contract(" ".join([f"{WHOLE}.", *MANY[:3]]), tmp_path, learned=[])

    [folded] = compact_contract_prompt_blocks(items, [" ".join(MANY[:3])])  # the long one is not carried

    assert f"- [judge] {WHOLE}." in folded and f"- [judge] {FOLDED.format(count=3)}" in folded
    assert not any(requirement in folded for requirement in MANY[:3])


def test_a_listed_need_counts_as_carried_only_where_the_reader_finds_it(tmp_path: Path) -> None:
    """Each listed need is rebuilt as "<lead> <need>.", text no message holds word for word: the reader decides."""
    request = _levels(3)
    items = ac.build_contract(request, tmp_path, learned=[])
    needs = ac.requirement_statements(request)
    assert len(needs) == 3 and not any(need in request for need in needs)

    [folded] = compact_contract_prompt_blocks(items, [request])
    whole = ac.contract_prompt_block(items)

    assert f"- [judge] {FOLDED.format(count=3)}" in folded and not any(need in folded for need in needs)
    assert compact_contract_prompt_blocks(items, [request.replace("The game needs:", "The game has:")]) == []
    assert all(f"- [judge] {need}" in whole for need in needs), "the whole block is unchanged"


def test_a_request_too_long_to_send_twice_runs_with_the_requirement_whole_once(workspace: Path) -> None:
    llm = _RecordingLLM(window=8192)

    done = _done(_run(llm))

    assert done.data["text"].partition("\n\n")[0] == "DONE"
    assert len(llm.seen) == 2
    for request in llm.seen:
        system = str(request[0]["content"])
        assert "--- Acceptance Contract ---" in system and f"({len(WHOLE):,} characters" in system
        assert sum(str(message.get("content")).count(WHOLE) for message in request) == 1, "once, in your request"
    items = done.data["token_report"]["acceptance_contract"]["items"]
    assert [item["description"] for item in items if item["kind"] == ac.KIND_REQUIREMENT] == [WHOLE]


def test_the_judge_still_rules_on_a_named_requirement_whole(workspace: Path) -> None:
    llm = _RecordingLLM(window=8192, effort="xhigh")

    _done(_run(llm))

    assert WHOLE not in str(llm.seen[0][0]["content"]), "the worker's block named it"
    assert llm.judged, "the separate evaluator ruled"
    judge_prompt = str(llm.judged[0][1]["content"])
    assert f"- req:1 [unchecked] {WHOLE}" in judge_prompt.split("CONTRACT (machine verdicts already applied):", 1)[1]


def test_many_short_requirements_are_not_sent_twice_either(workspace: Path) -> None:
    """Before cab55497 at most 24 requirements of at most 300 characters were repeated; now any number are."""
    assert all(len(requirement) <= LONG_REQUIREMENT_CHARS for requirement in MANY)
    llm = _RecordingLLM(window=8192)

    done = _done(_run(llm, " ".join(MANY)))

    for request in llm.seen:
        system = str(request[0]["content"])
        assert "--- Acceptance Contract ---" in system and FOLDED.format(count=len(MANY)) in system
        assert all(sum(str(m.get("content")).count(r) for m in request) == 1 for r in MANY), "once, in your request"
    items = done.data["token_report"]["acceptance_contract"]["items"]
    assert [item["description"] for item in items if item["kind"] == ac.KIND_REQUIREMENT] == MANY, "judged whole"


@pytest.mark.parametrize("count", [200, 300])
def test_a_long_feature_list_runs_and_the_judge_gets_every_listed_need_whole(workspace: Path, count: int) -> None:
    """Before cab55497 the 24-item cap kept this block small; a listed feature set is one item per feature."""
    request = _levels(count)
    needs = ac.requirement_statements(request)
    assert len(needs) == count
    llm = _RecordingLLM(window=8192, effort="xhigh")

    _done(_run(llm, request))

    for sent in llm.seen:
        system = str(sent[0]["content"])
        assert FOLDED.format(count=count) in system and not any(need in system for need in needs)
    assert llm.judged, "the separate evaluator ruled"
    contract = str(llm.judged[0][1]["content"]).split("CONTRACT (machine verdicts already applied):", 1)[1]
    assert all(f"] {need}" in contract for need in needs), "the judge rules on every listed need whole"


def test_a_request_wrapped_in_a_reminder_still_gets_the_shorter_block(workspace: Path) -> None:
    """A lowercase first sentence runs into the reminder's last one, so the reader cannot find it again on its own."""
    request = _levels(200, lead="the game needs: ")
    assert not set(ac.requirement_statements(request)) & set(ac.requirement_statements(WRAPPER + request))
    llm = _RecordingLLM(window=8192)

    _done(_run(llm, WRAPPER + request, intent=request))

    assert FOLDED.format(count=200) in str(llm.seen[0][0]["content"])


def test_a_standing_goal_that_repeats_a_request_sentence_is_counted_once(tmp_path: Path) -> None:
    goal = {"item_id": "goal:g1", "kind": "requirement", "description": SHORT, "source": "goal", "target": SHORT}
    request = " ".join([SHORT, *MANY[:2]])
    items = ac.build_contract(request, tmp_path, learned=[goal])

    [folded] = compact_contract_prompt_blocks(items, [request], request=request)

    assert FOLDED.format(count=3) in folded and f"- [judge] {SHORT}" in folded, "the goal stays its own item"


def test_a_window_with_room_still_shows_the_requirement_whole(workspace: Path) -> None:
    llm = _RecordingLLM(window=65_536)

    _done(_run(llm))

    assert f"- [judge] {WHOLE}" in str(llm.seen[0][0]["content"])


def test_your_memory_outlives_the_second_copy(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Naming the requirement loses nothing, since the request carries it whole; shedding memory loses your memory."""
    monkeypatch.setattr(AgentLoop, "_retrieve_memory", lambda self, *args, **kwargs: MEMORY)
    llm = _RecordingLLM(window=16_384)

    _done(_run(llm, SIZED))

    system = str(llm.seen[0][0]["content"])
    assert "MEMORY-MARKER" in system and SIZED not in system and f"({len(SIZED):,} characters" in system
