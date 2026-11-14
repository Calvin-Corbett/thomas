"""A Build pass that ends early is a decision, not the end of the Build (harness report item 3, K1).

Before: an unmet contract the completion gate refused, the 400-iteration cap, a full context window or a provider
error set rc 1; the engine verified only rc 0, so the whole Build ended on "agent loop exited 1" with the files it left
behind never checked. Now each ending is continued (changes verified first), stopped to ask you, or stopped, and two
passes in a row that end the same way and change nothing stop retrying.
"""

from __future__ import annotations

from pathlib import Path

from tests._evolve_bridge_fakes import _commit_all, _init_repo
from thomas.agent.completion_gate import GATE_BLOCKED_ERROR
from thomas.forge.anvil import dispatch_agent_loop as dal
from thomas.forge.anvil import forge_code_git
from thomas.forge.anvil import pass_endings as pe
from thomas.forge.anvil.build_verify import _verify_and_iterate
from thomas.forge.anvil.dispatch_agent_loop_translator import _AgentLoopForgeTranslator
from thomas.forge.anvil.forge_event_stream import FORGE_EVENT_KEY

GATE = pe.PassEnding(pe.CONTRACT_UNMET, f"{GATE_BLOCKED_ERROR}: 2 checked items unmet")
TRANSIENT = pe.PassEnding(pe.PROVIDER_TRANSIENT, "503 upstream overloaded")


def test_each_loop_ending_is_classified() -> None:
    cases = {
        pe.CONTRACT_UNMET: {"error": f"{GATE_BLOCKED_ERROR}: validation failed"},
        pe.ITERATION_CAP: {"error": "Pass budget exhausted after 400 passes while work was still active."},
        pe.REPEATED_TOOL_FAILURE: {"error": "Tool loop stability issue: fs.edit has failed repeatedly."},
        pe.CONTEXT_FULL: {"error": "The request cannot hold 3 tool result(s) from this run (fs.read) ..."},
        pe.PROVIDER_TRANSIENT: {"error": "upstream 503", "status": 503, "retryable": True, "error_code": ""},
        pe.PROVIDER_PERMANENT: {"error": "unauthorized", "status": 401, "retryable": False, "error_code": ""},
        pe.TOKEN_CEILING: {"error": "ceiling", "stop_reason": "token_ceiling_reached"},
        pe.UNKNOWN: {"error": "something odd"},
    }
    for kind, data in cases.items():
        assert pe.classify_agent_error(data).kind == kind, (kind, data)
    # A 429 that names a quota is the person's to fix, not a retry.
    quota = {"error": "429 usage limit reached for your plan", "status": 429, "retryable": False}
    assert pe.classify_agent_error(quota).decision == pe.ASK
    assert pe.classify_agent_error({"error": "Lost the connection to ChatGPT mid-run"}).decision == pe.CONTINUE


def test_the_translator_keeps_how_the_pass_ended() -> None:
    from thomas.core.events import EventType

    tr = _AgentLoopForgeTranslator(lambda _e: None)
    tr.feed(EventType.AGENT_ERROR.value, {"error": "Pass budget exhausted after 400 passes while work was active."})
    assert tr.rc == 1 and tr.ending is not None and tr.ending.kind == pe.ITERATION_CAP


def _engine(monkeypatch, tmp_path: Path, files: list[str]):
    monkeypatch.setattr(forge_code_git, "project_delta_since", lambda cwd, snap: list(files))
    for f in files:
        (tmp_path / f).write_text("const x = 1;\n", encoding="utf-8")


def test_a_gate_refused_pass_is_verified_and_continued_until_the_contract_holds(monkeypatch, tmp_path: Path) -> None:
    _engine(monkeypatch, tmp_path, ["game.js"])
    state: dict = {"ending": GATE}
    prompts: list[str] = []
    events: list[dict] = []

    def run_pass(prompt: str):
        prompts.append(prompt)
        state["ending"] = None  # this pass ended on its own
        return 0, "done"

    rc = _verify_and_iterate(
        tmp_path,
        object(),
        events.append,
        run_pass,
        "Build the game",
        verifier=lambda cwd, changed, emit: (True, 0, "ok"),
        max_fix_iters=5,
        contract=lambda: pe.ending_contract(state["ending"]) if state["ending"] else None,
        pass_ending=lambda: state["ending"],
        first_ending=GATE,
    )
    assert rc == 0
    assert len(prompts) == 1 and "Build the game" in prompts[0] and "ended early" in prompts[0]


def test_a_continue_pass_that_ends_early_again_is_continued_not_fatal(monkeypatch, tmp_path: Path) -> None:
    _engine(monkeypatch, tmp_path, ["game.js"])
    state: dict = {"ending": GATE, "n": 0}

    def run_pass(prompt: str):
        state["n"] += 1
        (tmp_path / "game.js").write_text(f"const x = {state['n']};\n", encoding="utf-8")  # progress
        if state["n"] == 1:
            state["ending"] = TRANSIENT
            return 1, ""
        state["ending"] = None
        return 0, "done"

    rc = _verify_and_iterate(
        tmp_path,
        object(),
        lambda _e: None,
        run_pass,
        "goal",
        verifier=lambda cwd, changed, emit: (True, 0, "ok"),
        max_fix_iters=5,
        contract=lambda: pe.ending_contract(state["ending"]) if state["ending"] else None,
        pass_ending=lambda: state["ending"],
        first_ending=GATE,
    )
    assert rc == 0 and state["n"] == 2


def test_two_passes_that_change_nothing_and_end_the_same_way_stop(monkeypatch, tmp_path: Path) -> None:
    _engine(monkeypatch, tmp_path, ["game.js"])
    calls: list[str] = []
    outcome: list[str] = []
    events: list[dict] = []

    def run_pass(prompt: str):
        calls.append(prompt)
        return 1, ""  # ends early the same way every time, touching nothing

    rc = _verify_and_iterate(
        tmp_path,
        object(),
        events.append,
        run_pass,
        "goal",
        verifier=lambda cwd, changed, emit: (True, 0, "ok"),
        max_fix_iters=20,
        contract=lambda: pe.ending_contract(TRANSIENT),
        pass_ending=lambda: TRANSIENT,
        first_ending=None,
        on_outcome=outcome.append,
    )
    assert rc != 0
    assert len(calls) == 2, "bounded by progress, not by the 20-pass budget"
    assert outcome and "two passes in a row" in outcome[0]


def test_an_ending_that_needs_you_stops_and_says_so(monkeypatch, tmp_path: Path) -> None:
    _engine(monkeypatch, tmp_path, ["game.js"])
    auth = pe.classify_agent_error({"error": "token expired", "status": 401, "retryable": False})
    outcome: list[str] = []
    rc = _verify_and_iterate(
        tmp_path,
        object(),
        lambda _e: None,
        lambda _p: (1, ""),
        "goal",
        verifier=lambda cwd, changed, emit: (True, 0, "ok"),
        max_fix_iters=5,
        contract=lambda: pe.ending_contract(GATE),
        pass_ending=lambda: auth,
        on_outcome=outcome.append,
    )
    assert rc != 0 and outcome and outcome[0].startswith("needs you")


def _repo(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(tmp_path)


def test_a_build_whose_first_pass_hit_the_gate_is_continued_and_completes(monkeypatch, tmp_path: Path) -> None:
    _repo(tmp_path)
    passes: list[str] = []

    def fake_pass(prompt, cwd, timeout, emit, **kw):
        passes.append(prompt)
        sink = kw["acceptance_sink"]
        (tmp_path / "feature.py").write_text(f"VALUE = {len(passes)}\n", encoding="utf-8")
        if len(passes) == 1:
            sink["acceptance"], sink["yielded_for_reload"] = None, False
            sink["ending"] = GATE
            return 1, ""
        sink["acceptance"], sink["yielded_for_reload"], sink["ending"] = None, False, None
        return 0, "Done."

    monkeypatch.setattr(dal, "_run_agent_loop_pass", fake_pass)
    events: list[dict] = []
    res = dal.dispatch_via_agent_loop(
        "build feature", cwd=tmp_path, dry_run=False, token_check=lambda: True, emit=events.append, max_fix_iters=5
    )
    assert len(passes) == 2, [
        e.get("text", "")[:300] for e in events if e.get(FORGE_EVENT_KEY) in {"meta", "error", "tool_result"}
    ]
    assert res.ok is True and res.returncode == 0, res.reason
    metas = [e.get("text", "") for e in events if e.get(FORGE_EVENT_KEY) == "meta"]
    assert any("ended early" in m for m in metas), metas


def test_a_build_whose_first_pass_needs_you_is_not_completed(monkeypatch, tmp_path: Path) -> None:
    _repo(tmp_path)
    auth = pe.PassEnding(pe.PROVIDER_PERMANENT, "401 unauthorized")

    def fake_pass(prompt, cwd, timeout, emit, **kw):
        kw["acceptance_sink"].update({"acceptance": None, "yielded_for_reload": False, "ending": auth})
        return 1, ""

    monkeypatch.setattr(dal, "_run_agent_loop_pass", fake_pass)
    res = dal.dispatch_via_agent_loop(
        "build", cwd=tmp_path, dry_run=False, token_check=lambda: True, emit=lambda e: None
    )
    assert res.ok is False and res.reason.startswith("needs you"), res.reason
