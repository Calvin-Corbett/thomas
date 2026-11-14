"""The GPT path: the wall clock, intent separation, and the same post-observation insight as Claude.

Split from test_evolve_claude_bridge.py on 2026-09-07 so each file stays under the monolith guard's limit.
"""
from __future__ import annotations

from tests._evolve_bridge_fakes import _commit_all, _init_repo, _run_gpt_translator, clean_git_repo  # noqa: F401


def test_gpt_agent_stream_enforces_wall_clock_timeout():
    import asyncio
    from types import SimpleNamespace

    from thomas.core.events import EventType as ET
    from thomas.forge.anvil.dispatch_agent_loop import _AgentLoopForgeTranslator, _translate_agent_stream

    class SlowAgent:
        async def run(self, *_args, **_kwargs):
            yield SimpleNamespace(type=ET.TOOL_START, data={"tool_name": "fs.read_file", "args": {}})
            await asyncio.sleep(0.2)
            yield SimpleNamespace(type=ET.AGENT_DONE, data={"text": "too late"})

    emitted: list[dict] = []
    translator = _AgentLoopForgeTranslator(emitted.append)
    asyncio.run(
        _translate_agent_stream(
            SlowAgent(),
            "build it",
            timeout=0.01,
            tools_policy="auto",
            translator=translator,
        )
    )
    translator.close()

    # Since 49098ee5 a pass wall clock is a boundary, not a failure: the
    # translator reports PASS_WALL_CLOCK_RC so the engine verifies what changed
    # and continues, instead of the generic 1 this test asserted before.
    from thomas.forge.anvil.build_verify import PASS_WALL_CLOCK_RC

    assert translator.rc == PASS_WALL_CLOCK_RC
    assert translator.final_text == ""
    assert any(event["fc"] == "meta" and "pass wall clock" in event["text"] for event in emitted)
    assert not any(event["fc"] == "error" for event in emitted)


def test_gpt_agent_stream_keeps_model_context_separate_from_current_intent():
    import asyncio
    from types import SimpleNamespace

    from thomas.core.events import EventType as ET
    from thomas.forge.anvil.dispatch_agent_loop import _AgentLoopForgeTranslator, _translate_agent_stream

    class CapturingAgent:
        def __init__(self) -> None:
            self.prompt = ""
            self.intent_text = ""

        async def run(self, prompt, **kwargs):
            self.prompt = prompt
            self.intent_text = str(kwargs.get("intent_text") or "")
            yield SimpleNamespace(type=ET.AGENT_DONE, data={"text": "done"})

    agent = CapturingAgent()
    emitted: list[dict] = []
    translator = _AgentLoopForgeTranslator(emitted.append)
    asyncio.run(
        _translate_agent_stream(
            agent,
            "policy + history + current goal",
            intent_text="make me a playable Viking game",
            timeout=1,
            tools_policy="auto",
            translator=translator,
        )
    )
    translator.close()

    assert agent.prompt == "policy + history + current goal"
    assert agent.intent_text == "make me a playable Viking game"
    assert translator.rc == 0


def test_agent_loop_dispatch_entrypoint_forwards_exact_goal_as_intent(monkeypatch, tmp_path):
    from thomas.forge.anvil import dispatch_agent_loop as dispatch_module
    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_agent_loop

    _init_repo(tmp_path)
    (tmp_path / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(tmp_path)
    captured = {}

    def fake_run(prompt, cwd, timeout, emit, *, intent_text=None, **_kwargs):  # noqa: ANN001
        captured.update(prompt=prompt, cwd=cwd, timeout=timeout, intent_text=intent_text)
        return 0, "done"

    monkeypatch.setattr(dispatch_module, "_run_agent_loop_pass", fake_run)
    goal = "make me a playable Viking game"
    dispatch_via_agent_loop(
        goal,
        cwd=tmp_path,
        dry_run=False,
        verify=False,
        token_check=lambda: True,
        history=[{"role": "user", "text": "what tools did you use in this conversation?"}],
    )

    assert goal in captured["prompt"]
    assert "what tools did you use" in captured["prompt"]
    assert captured["intent_text"] == goal


def test_gpt_path_thinking_yields_same_post_observation_insight_as_claude(clean_git_repo):
    """ENGINE PARITY (operator gap #3): a GPT build run surfaces the SAME genuine
    post-observation insight card + collapsed reasoning a claude run does.

    The GPT engine streams reasoning as ``THINKING`` token deltas; the translator
    accumulates them and flushes each block through the SAME shared gate the claude
    path uses. So the pre-observation enumerated PLAN is suppressed, the salient
    post-observation observation surfaces ONCE (enumeration-stripped), a near-
    identical follow-up dedupes away — and the card is byte-identical to the one the
    claude stream-json path emits for the equivalent scenario."""
    import json
    import re

    from thomas.core.events import EventType as ET
    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_claude_cli

    # --- GPT engine: THINKING deltas interleaved with real tool observations ---
    gpt_events = [
        # FIRST reasoning = the PLAN (enumerated imperatives), arriving as deltas,
        # BEFORE any observation -> must yield NO insight, only its collapsed reason.
        (ET.THINKING, {"text": "1. Create `thomas/forge/anvil/_note3.py` with a 2-sentence module docstring 3. "}),
        (ET.THINKING, {"text": "2. Then wire it into the package."}),
        # the model OBSERVES: lists the directory, sees the result
        (ET.TOOL_START, {"tool_name": "code.glob", "args": {"pattern": "thomas/forge/anvil/*.py"}}),
        (ET.TOOL_RESULT, {"result": "evolve_claude_bridge.py\nforge_code_git.py", "ok": True}),
        # post-observation reasoning #1 -> a genuine insight
        (ET.THINKING, {"text": "Now I have a good understanding of what's in the `thomas/forge/anvil` directory."}),
        # a tool boundary flushes block #1 and keeps the run OBSERVED
        (ET.TOOL_START, {"tool_name": "fs.read_file", "args": {"file_path": "evolve_claude_bridge.py"}}),
        (ET.TOOL_RESULT, {"result": "def translate(): ...", "ok": True}),
        # post-observation reasoning #2 -> the SAME beat, must dedupe away
        (ET.THINKING, {"text": "Now I have a good picture of the `thomas/forge/anvil` package."}),
        (ET.AGENT_DONE, {"text": "Done."}),
    ]
    gpt_out, tr = _run_gpt_translator(gpt_events)
    gpt_insights = [e for e in gpt_out if e["fc"] == "insight"]

    # exactly ONE card; the enumerated pre-observation PLAN never surfaced...
    assert len(gpt_insights) == 1
    gtext = gpt_insights[0]["text"]
    assert "understanding" in gtext
    assert "create" not in gtext.lower()  # task-restatement suppressed (not a keyword scan)
    # ...no dangling enumeration marker rode onto the card (stripped both ends)
    assert not re.match(r"^\d+\s*[.)]", gtext)
    assert not gtext.rstrip().endswith("3.") and not gtext.rstrip().endswith("3")
    # the insight is POST-observation: a tool precedes it in the emitted stream
    kinds = [e["fc"] for e in gpt_out]
    assert "tool" in kinds and "tool_result" in kinds
    assert kinds.index("insight") > kinds.index("tool")
    # the full PLAN reasoning is still preserved for the collapsible view (honest:
    # shown, just not promoted to an insight), and reasoning is its own kind
    assert any(e["fc"] == "reason" and "Create" in e["text"] for e in gpt_out)
    assert tr.rc == 0 and tr.final_text == "Done."
    assert gpt_out[-1] == {"fc": "final", "text": "Done."}

    # --- PARITY: the claude engine on the equivalent scenario emits the SAME card ---
    claude_stream = "\n".join(
        [
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "thinking",
                                "thinking": (
                                    "1. Create `thomas/forge/anvil/_note3.py` with a 2-sentence module docstring 3. "
                                    "2. Then wire it into the package."
                                ),
                            }
                        ]
                    },
                }
            ),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "tool_use", "name": "Glob", "input": {"pattern": "thomas/forge/anvil/*.py"}}
                        ]
                    },
                }
            ),
            json.dumps(
                {
                    "type": "user",
                    "message": {
                        "content": [
                            {
                                "type": "tool_result",
                                "content": "evolve_claude_bridge.py\nforge_code_git.py",
                                "is_error": False,
                            }
                        ]
                    },
                }
            ),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "thinking",
                                "thinking": "Now I have a good understanding of what's in the `thomas/forge/anvil` directory.",
                            }
                        ]
                    },
                }
            ),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "thinking",
                                "thinking": "Now I have a good picture of the `thomas/forge/anvil` package.",
                            }
                        ]
                    },
                }
            ),
        ]
    )
    claude_events: list[dict] = []
    dispatch_via_claude_cli(
        "do x",
        cwd=clean_git_repo,
        dry_run=False,
        runner=lambda c, w, t: (0, claude_stream),
        claude_bin="claude",
        emit=claude_events.append,
    )
    claude_insights = [e for e in claude_events if e["fc"] == "insight"]
    assert len(claude_insights) == 1
    # the headline: BOTH first-class engines surface the IDENTICAL insight card
    assert gtext == claude_insights[0]["text"]


def test_gpt_path_thinking_before_any_tool_yields_no_insight():
    """A GPT stream whose reasoning arrives BEFORE any tool observation surfaces NO
    insight card — only its collapsible reasoning. Same positional honesty as the
    claude path: pre-observation reasoning is the plan, never an "I'm noticing…"."""
    from thomas.core.events import EventType as ET

    out, tr = _run_gpt_translator(
        [
            # reads as a real observation, BUT nothing has been observed yet
            (ET.THINKING, {"text": "The parser has no test for empty input, "}),
            (ET.THINKING, {"text": "which is a genuine gap worth covering."}),
            (ET.AGENT_DONE, {"text": "Done."}),
        ]
    )
    kinds = [e["fc"] for e in out]
    # no observation ever happened -> the reasoning is plan: ZERO insight cards
    assert "insight" not in kinds
    # ...but the full reasoning is still preserved for the collapsible view (honest)
    assert any(e["fc"] == "reason" and "empty input" in e["text"] for e in out)
    assert tr.rc == 0


def test_action_refusal_detects_hallucinated_tool_unavailable_claims():
    """A Code fix that hallucinates "your file tools aren't set up" must score as a
    refusal (ok=False -> retry), not a silent "I can't, go re-enable something" bounce.

    Live: an FPS fix bounced with exactly this phrasing while index.html was on disk
    and the Read/Edit/Write tools were registered. The bounce phrasing slipped past
    the refusal detector, so it was recorded as a normal reply with no retry.
    """
    from thomas.forge.anvil.dispatch_claude_cli import _is_action_refusal

    assert _is_action_refusal(
        "The file tools aren't exposed in this session, so I can't honestly patch the "
        "working tree yet; re-enable the workspace tools and I'll fix the renderer directly."
    )
    assert _is_action_refusal("I can't finish — the write tool isn't available")  # pre-existing marker
    assert _is_action_refusal("I couldn't do it because the tools are not available this session")
    # No false positives on real completions or incidental "exposed"/"workspace" wording.
    assert not _is_action_refusal("Done — I edited index.html and moved the player to a floor tile.")
    assert not _is_action_refusal("The exposed API returns JSON; I updated the handler in the workspace.")
