"""A Build runs until its acceptance contract holds, not until a pass ends (2026-09-05).

Measured on the Mario Kart build. The first pass wrote three files, said "Built
Turbo Trails. Open index.html to play", and the engine's fix loop only ever
re-ran the static and browser smoke checks. The loop's own acceptance contract
was settled inside the pass, and the translator kept only the final text, so
the engine never learnt that the contract was unmet. "Completed" was the one
outcome the engine could reach once the smoke passed, and a one-track demo got
it. You said: "make sure he can do any task until its done not based on passes."

Three pieces, each pinned here:

1. The contract's depth follows the Build, never below the level that has a
   separate judge. At medium nobody checks a judged requirement, so the
   verdict is "met" with nine features unchecked.
2. The translator hands the engine the settlement the loop already computed.
3. The engine keeps handing the unmet items back for another pass, inside the
   same runaway guard as the fix loop, and a spent budget is "unfinished" with
   the gaps named -- never "completed".
"""

from __future__ import annotations

from pathlib import Path

from thomas.core.events import EventType
from thomas.forge.anvil import forge_code_git
from thomas.forge.anvil.build_verify import _verify_and_iterate
from thomas.forge.anvil.dispatch_agent_loop import _AgentLoopForgeTranslator, _contract_level_for_build
from thomas.forge.anvil.forge_event_stream import FORGE_EVENT_KEY

UNMET = {
    "active": True,
    "level": "xhigh",
    "verdict": {"met": False, "unmet": ["req:3"], "unchecked": []},
    "items": [
        {
            "item_id": "req:3",
            "kind": "requirement",
            "description": "It needs at least 4 distinct race tracks with different layouts and themes.",
            "checked": True,
            "satisfied": False,
            "detail": "one track defined in game.js",
        }
    ],
}
MET = {"active": True, "level": "xhigh", "verdict": {"met": True, "unmet": [], "unchecked": []}, "items": []}


def test_the_contract_depth_never_drops_below_the_level_with_a_judge() -> None:
    assert _contract_level_for_build("medium") == "xhigh"
    assert _contract_level_for_build("") == "xhigh"
    assert _contract_level_for_build("low") == "xhigh"
    assert _contract_level_for_build("xhigh") == "xhigh"
    assert _contract_level_for_build("max") == "max"


def test_the_translator_keeps_the_settlement_the_loop_computed() -> None:
    events: list[dict] = []
    translator = _AgentLoopForgeTranslator(events.append)
    translator.feed(EventType.AGENT_DONE.value, {"text": "Built it.", "token_report": {"acceptance_contract": UNMET}})
    assert translator.acceptance == UNMET
    assert translator.final_text == "Built it."
    metas = [e["text"] for e in events if e.get(FORGE_EVENT_KEY) == "meta"]
    assert any("acceptance contract" in m and "not met" in m and "req:3" in m for m in metas), metas


def test_the_transcript_line_says_what_the_judge_did() -> None:
    """Live on the Mario Kart run the line read "met on checked items; 3 unchecked"
    and nothing said whether the judge ran, errored, or declined. It has to."""
    unavailable = {**MET, "verdict": {"met": True, "unmet": [], "unchecked": ["req:1"]},
                   "evaluator": {"available": False, "error": "llm has no chat()", "calls": 0, "findings": []}}
    declined = {**MET, "verdict": {"met": True, "unmet": [], "unchecked": ["req:1"]},
                "evaluator": {"available": True, "error": "", "calls": 1, "findings": ["no browser to play the race"]}}
    no_judge = {**MET, "verdict": {"met": True, "unmet": [], "unchecked": ["req:1"]}, "evaluator": None}
    lines = []
    for payload in (unavailable, declined, no_judge):
        events: list[dict] = []
        _AgentLoopForgeTranslator(events.append).feed(
            EventType.AGENT_DONE.value, {"text": "done", "token_report": {"acceptance_contract": payload}}
        )
        lines.append(next(e["text"] for e in events if e.get(FORGE_EVENT_KEY) == "meta"))
    assert "judge unavailable: llm has no chat()" in lines[0], lines[0]
    assert "judge: 1 call(s); findings: no browser to play the race" in lines[1], lines[1]
    assert "no judge ran at this level" in lines[2], lines[2]


def test_the_build_pass_asks_for_verification_at_the_judged_level(monkeypatch, tmp_path: Path) -> None:
    """The contract reads the worker model's own effort unless the loop carries a
    ``verification_effort``; the Build pass sets it so a medium worker still gets
    a judge (the hook that reads it lives in acceptance_runtime)."""
    import thomas.agent.loop as loop_module
    from thomas.forge.anvil import dispatch_agent_loop as dal

    built: dict[str, object] = {}

    class FakeLoop:
        def __init__(self, config, llm, tools, **kwargs):
            built["config"] = config
            built["llm"] = llm
            built["tools"] = tools

    async def no_stream(agent, prompt, **kwargs):
        built["agent"] = agent

    monkeypatch.setattr(loop_module, "AgentLoop", FakeLoop)
    monkeypatch.setattr(dal, "_translate_agent_stream", no_stream)
    rc, text = dal._run_agent_loop_pass("build it", str(tmp_path), 5, lambda e: None)
    assert rc == 0 and text == ""
    agent = built["agent"]
    assert agent.verification_effort in {"xhigh", "max"}
    # And the builder can play what it writes: the playtest tool is in its toolset.
    assert "web.playtest" in built["tools"], [t.name for t in built["tools"].list_tools()]
    # The worker model's own effort is untouched by the floor.
    from thomas.core.config import load_config

    profile_effort = load_config(tmp_path / "thomas.toml").get_model(dal.OPENAI_CODEX_PROFILE).reasoning_effort
    assert getattr(built["llm"].config, "reasoning_effort", None) == profile_effort


def _engine(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(forge_code_git, "project_delta_since", lambda cwd, snap: ["game.js"])
    (tmp_path / "game.js").write_text("const tracks = 1;\n", encoding="utf-8")
    events: list[dict] = []
    prompts: list[str] = []
    return events, prompts


def test_an_unmet_contract_gets_another_pass_and_a_met_one_ends_the_run(monkeypatch, tmp_path: Path) -> None:
    events, prompts = _engine(monkeypatch, tmp_path)
    state = {"acceptance": UNMET}

    def run_pass(prompt: str):
        prompts.append(prompt)
        state["acceptance"] = MET
        return 0, "pass"

    rc = _verify_and_iterate(
        tmp_path,
        object(),
        events.append,
        run_pass,
        "Build a full Mario Kart style racing game",
        verifier=lambda cwd, changed, emit: (True, 0, "ok"),
        max_fix_iters=5,
        contract=lambda: state["acceptance"],
    )

    assert rc == 0
    assert len(prompts) == 1, prompts  # exactly one more pass: the contract was met after it
    assert "at least 4 distinct race tracks" in prompts[0]
    assert "one track defined in game.js" in prompts[0]
    metas = [e["text"] for e in events if e.get(FORGE_EVENT_KEY) == "meta"]
    assert any("not met" in m and "pass 1/5" in m for m in metas), metas


def test_a_spent_budget_is_unfinished_with_the_gaps_named(monkeypatch, tmp_path: Path) -> None:
    events, prompts = _engine(monkeypatch, tmp_path)

    def run_pass(prompt: str):
        prompts.append(prompt)
        return 0, "pass"

    rc = _verify_and_iterate(
        tmp_path,
        object(),
        events.append,
        run_pass,
        "Build a full Mario Kart style racing game",
        verifier=lambda cwd, changed, emit: (True, 0, "ok"),
        max_fix_iters=2,
        contract=lambda: UNMET,
    )

    assert rc != 0
    assert len(prompts) == 2
    errors = [e["text"] for e in events if e.get(FORGE_EVENT_KEY) == "error"]
    assert errors and errors[-1].startswith("unfinished"), errors
    assert "at least 4 distinct race tracks" in errors[-1]


UNCHECKED_BY_JUDGE = {
    "active": True,
    "level": "xhigh",
    "verdict": {"met": True, "unmet": [], "unchecked": ["req:1"]},
    "items": [
        {
            "item_id": "req:1",
            "kind": "requirement",
            "description": "Fix the keyboard driving for both players.",
            "checked": False,
            "satisfied": False,
            "detail": "",
        }
    ],
    "evaluator": {
        "available": True,
        "calls": 2,
        "error": "",
        "findings": ["Manual keyboard driving was not independently verified: both requested shell checks failed"],
    },
}


def test_a_requirement_the_judge_could_not_verify_is_a_gap_in_a_build(monkeypatch, tmp_path: Path) -> None:
    """Live on generation 5: the judge asked for Unix shell checks on Windows, they
    failed, it left the driving requirement unchecked, and unchecked counted as
    met, so a run whose one requirement nobody verified filed completed."""
    events, prompts = _engine(monkeypatch, tmp_path)
    state = {"acceptance": UNCHECKED_BY_JUDGE}

    def run_pass(prompt: str):
        prompts.append(prompt)
        state["acceptance"] = MET
        return 0, "pass"

    rc = _verify_and_iterate(
        tmp_path, object(), events.append, run_pass, "goal",
        verifier=lambda cwd, changed, emit: (True, 0, "ok"), max_fix_iters=3, contract=lambda: state["acceptance"],
    )
    assert rc == 0
    assert len(prompts) == 1, prompts
    assert "Fix the keyboard driving" in prompts[0] and "not verified" in prompts[0], prompts[0]
    assert "web.playtest" in prompts[0]


def test_unchecked_items_without_a_judge_are_not_gaps(monkeypatch, tmp_path: Path) -> None:
    """At a level with no judge nothing can check a judged item; sending it back
    would loop for nothing. That case keeps today's behaviour."""
    events, prompts = _engine(monkeypatch, tmp_path)
    no_judge = {**UNCHECKED_BY_JUDGE, "evaluator": None}
    rc = _verify_and_iterate(
        tmp_path, object(), events.append, lambda p: (prompts.append(p) or (0, "x")), "goal",
        verifier=lambda cwd, changed, emit: (True, 0, "ok"), max_fix_iters=3, contract=lambda: no_judge,
    )
    assert rc == 0 and prompts == []


def test_without_a_contract_the_engine_behaves_as_before(monkeypatch, tmp_path: Path) -> None:
    events, prompts = _engine(monkeypatch, tmp_path)
    rc = _verify_and_iterate(
        tmp_path,
        object(),
        events.append,
        lambda prompt: (prompts.append(prompt) or (0, "pass")),
        "goal",
        verifier=lambda cwd, changed, emit: (True, 0, "ok"),
        max_fix_iters=5,
    )
    assert rc == 0
    assert prompts == []


def test_an_engine_failure_after_a_contract_pass_still_fails(monkeypatch, tmp_path: Path) -> None:
    """A contract pass is re-verified by the engine like any other edit."""
    events, prompts = _engine(monkeypatch, tmp_path)
    verdicts = iter([(True, 0, "ok"), (False, 1, "SyntaxError in game.js")])

    rc = _verify_and_iterate(
        tmp_path,
        object(),
        events.append,
        lambda prompt: (prompts.append(prompt) or (0, "pass")),
        "goal",
        verifier=lambda cwd, changed, emit: next(verdicts, (False, 1, "SyntaxError in game.js")),
        max_fix_iters=1,
        contract=lambda: UNMET,
    )
    assert rc != 0


def test_the_hold_rounds_are_visible_in_the_transcript() -> None:
    """Generation 7 replayed both races seven times under the contract's hold and
    the transcript showed nothing but the replays: the loop's status events
    were dropped. A status about the contract is a line in the record now."""
    events: list[dict] = []
    translator = _AgentLoopForgeTranslator(events.append)
    translator.feed(EventType.STATUS.value, {"message": "Reply checked against the acceptance contract: not finished yet. - req:1 unmet (observed: no quoted results)"})
    translator.feed(EventType.STATUS.value, {"message": "Thinking about the next step"})
    metas = [e["text"] for e in events if e.get(FORGE_EVENT_KEY) == "meta"]
    assert len(metas) == 1, events
    assert "not finished yet" in metas[0] and "req:1" in metas[0]


def test_the_transcript_line_says_what_the_judge_checked() -> None:
    """Generation 9: the judge's shell check was denied and its own playtest failed
    on a key name, and the transcript line said only "3 unchecked". The checks the
    judge ran, and what became of them, belong on that line."""
    payload = {
        **MET,
        "verdict": {"met": True, "unmet": [], "unchecked": ["goal:g4"]},
        "evaluator": {
            "available": True,
            "error": "",
            "calls": 2,
            "findings": ["the internet-loading source scan was denied"],
            "checks_run": [
                {"cmd": 'findstr /s /i "curl wget" *.js', "skipped": "denied: runs curl"},
                {"cmd": "dir /b", "why": "files exist", "exit": 0, "tail": "index.html"},
                {"playtest": "index.html", "steps": 4, "why": "results screen", "ok": False, "result": "2. hold w+ArrowUp -> FAILED: Unknown key"},
            ],
        },
    }
    events: list[dict] = []
    _AgentLoopForgeTranslator(events.append).feed(
        EventType.AGENT_DONE.value, {"text": "done", "token_report": {"acceptance_contract": payload}}
    )
    line = next(e["text"] for e in events if e.get(FORGE_EVENT_KEY) == "meta")
    assert "checks: 1 shell ran (dir /b -> exit 0), 1 denied (findstr /s /i \"curl wget\" *.js: runs curl)" in line, line
    assert "playtest of index.html FAILED (2. hold w+ArrowUp -> FAILED: Unknown key)" in line, line
