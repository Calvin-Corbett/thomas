"""Safety + behavior of the Claude-Code build bridge (fake driver; no real PC control).

The whole point of these tests is to prove the bridge CANNOT control the PC unless
every gate passes, and that even then it only types into a matched window.
"""

from __future__ import annotations

import os

import pytest

from thomas.forge.anvil import evolve_claude_bridge as br
from thomas.forge.anvil.evolve_claude_bridge import (
    BridgeConfig,
    ClaudeCodeBridge,
    compose_claude_prompt,
)


class FakeDriver:
    def __init__(self, window: str | None = "Claude Code - VS Code"):
        self.window = window
        self.typed: list[str] = []
        self.enters = 0

    def find_window(self, match: str):
        return self.window if (self.window and match in self.window) else None

    def type_text(self, text: str) -> None:
        self.typed.append(text)

    def press_enter(self) -> None:
        self.enters += 1


def _enabled_cfg(**kw):
    return BridgeConfig(enabled=True, require_confirmation=True, **kw)


def test_compose_prompt_carries_goal_plan_and_branch_only_rule():
    p = compose_claude_prompt("make X faster", definition="X is faster", plan="cache it", branch_only=True)
    assert "make X faster" in p
    assert "cache it" in p
    assert "NEW git branch" in p and "STOP before merging" in p


def test_preview_never_touches_the_pc_and_needs_no_driver():
    bridge = ClaudeCodeBridge(config=_enabled_cfg(), driver=None)
    res = bridge.preview("improve logging")
    assert res.dispatched is False
    assert "improve logging" in res.prompt
    assert any("press Enter" in a for a in res.planned_actions)


def test_dispatch_refused_when_disabled_by_default():
    drv = FakeDriver()
    bridge = ClaudeCodeBridge(config=BridgeConfig(), driver=drv)  # default disabled
    res = bridge.dispatch("do a thing", confirm=True)
    assert res.dispatched is False
    assert "disabled" in res.reason
    assert drv.typed == [] and drv.enters == 0  # nothing typed


def test_dispatch_refused_when_unconfirmed():
    drv = FakeDriver()
    bridge = ClaudeCodeBridge(config=_enabled_cfg(), driver=drv)
    res = bridge.dispatch("do a thing", confirm=False)
    assert res.dispatched is False
    assert "confirm" in res.reason.lower()
    assert drv.typed == []


def test_dispatch_refused_without_driver():
    bridge = ClaudeCodeBridge(config=_enabled_cfg(), driver=None)
    res = bridge.dispatch("do a thing", confirm=True)
    assert res.dispatched is False
    assert "driver" in res.reason


def test_dispatch_refused_when_no_matching_window():
    drv = FakeDriver(window="Some Other App")  # title does not contain "Claude Code"
    bridge = ClaudeCodeBridge(config=_enabled_cfg(), driver=drv)
    res = bridge.dispatch("do a thing", confirm=True)
    assert res.dispatched is False
    assert "window" in res.reason
    assert drv.typed == [] and drv.enters == 0  # refuses to type into the wrong window


def test_dispatch_refused_when_emergency_stop_active(monkeypatch):
    monkeypatch.setattr(br, "emergency_stop_active", lambda: True)
    drv = FakeDriver()
    bridge = ClaudeCodeBridge(config=_enabled_cfg(), driver=drv)
    res = bridge.dispatch("do a thing", confirm=True)
    assert res.dispatched is False
    assert "emergency stop" in res.reason
    assert drv.typed == []


def test_dispatch_refused_when_prompt_too_large():
    drv = FakeDriver()
    bridge = ClaudeCodeBridge(config=_enabled_cfg(max_prompt_chars=50), driver=drv)
    res = bridge.dispatch("x" * 500, confirm=True)
    assert res.dispatched is False
    assert "too large" in res.reason
    assert drv.typed == []


def test_dispatch_types_only_when_all_gates_pass(monkeypatch):
    monkeypatch.setattr(br, "emergency_stop_active", lambda: False)
    events = []
    drv = FakeDriver(window="Claude Code")
    bridge = ClaudeCodeBridge(config=_enabled_cfg(), driver=drv, audit=events.append)
    res = bridge.dispatch("add a docstring", plan="write it", confirm=True)
    assert res.dispatched is True
    assert res.window == "Claude Code"
    assert len(drv.typed) == 1 and "add a docstring" in drv.typed[0]
    assert drv.enters == 1
    assert any(e.get("event") == "claude_dispatched" for e in events)


def test_config_loads_disabled_from_repo_toml(monkeypatch):
    # This asserts the SHIPPED toml default (enabled = false). The operator env
    # override (THOMAS_CLAUDE_BRIDGE_ENABLED) is a deliberate, separately-tested
    # escape hatch -- and the Code route exports it =1 to authorize a live build,
    # so it leaks into this verification subprocess. Clear it so we test the toml,
    # not the inherited override.
    monkeypatch.delenv("THOMAS_CLAUDE_BRIDGE_ENABLED", raising=False)
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = BridgeConfig.load(here)
    assert cfg.enabled is False  # ships OFF
    assert cfg.require_confirmation is True
    assert "Claude Code" in cfg.window_match


def _funnel_fake_model_call(system, user, profile=""):
    import json

    if "reading of what SUCCESS" in system:
        return json.dumps({"items": [{"text": "module has a clear docstring", "rationale": "the goal"}]})
    if "CHECKS that would prove" in system:
        return json.dumps(
            {"items": [{"text": "ast.get_docstring is non-empty", "how_to_test": "pytest -q", "essential": True}]}
        )
    if "implementation PLAN" in system:
        return json.dumps(
            {"plan": "add a triple-quoted module docstring at the top", "items": [{"text": "write the docstring"}]}
        )
    if "Adversarially grade" in system:
        return json.dumps({"score": 0.9, "pass": True, "weaknesses": [], "reason": "ok"})
    if "synthesizer bound to the goal" in system:
        return json.dumps(
            {
                "merged": "MERGED PLAN: add a top-of-file module docstring",
                "kept_items": ["x"],
                "contradictions": [],
                "dropped": [],
            }
        )
    if "needless weight" in system:
        return json.dumps({"cuts": []})
    if "INDEPENDENT evaluator" in system:
        return json.dumps({"broke_it": False, "verdict": "pass", "findings": [], "reason": "ok"})
    return "{}"


def test_compose_from_funnel_then_preview_carries_the_plan(monkeypatch):
    from thomas.forge.anvil.evolve_claude_bridge import compose_from_funnel
    from thomas.forge.anvil.evolve_funnel_config import FunnelConfig

    cfg = FunnelConfig(lanes=2, survivors=1, evaluator_candidates=["openai_codex"])
    definition, plan = compose_from_funnel(
        "Add a module docstring",
        project_root="/repo",
        profile="openai_codex",
        funnel_config=cfg,
        model_call=_funnel_fake_model_call,
        model_info=lambda p: ("openai_codex", "gpt-5.5"),
    )
    assert "MERGED PLAN" in plan or "docstring" in plan.lower()
    # the converged plan flows into the Claude-Code prompt
    bridge = ClaudeCodeBridge(config=_enabled_cfg(), driver=FakeDriver())
    res = bridge.preview("Add a module docstring", definition=definition, plan=plan)
    assert "docstring" in res.prompt.lower()
    assert "NEW git branch" in res.prompt  # branch-only safety instruction present


def test_cli_dispatch_dry_run_does_not_invoke_claude():
    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_claude_cli

    called = {"n": 0}

    def runner(cmd, cwd, to):
        called["n"] += 1
        return 0, "should not run"

    res = dispatch_via_claude_cli("do X", cwd="/repo", dry_run=True, runner=runner, claude_bin="claude")
    assert res.ok is False and "dry-run" in res.reason
    assert called["n"] == 0  # claude never invoked in dry-run
    assert "do X" in res.prompt


def test_cli_dispatch_runs_with_safe_toolset_and_reports():
    from thomas.forge.anvil.evolve_claude_bridge import SAFE_CLI_TOOLS, dispatch_via_claude_cli

    captured = {}

    def runner(cmd, cwd, to):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return 0, "built the change"

    res = dispatch_via_claude_cli("add a docstring", cwd="/repo", dry_run=False, runner=runner, claude_bin="claude")
    assert res.ok is True and res.returncode == 0
    assert captured["cmd"][:2] == ["claude", "-p"]
    assert "--allowedTools" in captured["cmd"]
    assert "--model" in captured["cmd"]  # explicit model (headless can't inherit the session model)
    # safe toolset: edit-only, NO shell/git/network
    assert "Bash" not in captured["cmd"]
    for tool in SAFE_CLI_TOOLS:
        assert tool in captured["cmd"]


def test_cli_dispatch_reports_failure_on_nonzero_exit():
    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_claude_cli

    res = dispatch_via_claude_cli(
        "do X", cwd="/repo", dry_run=False, runner=lambda c, w, t: (2, "boom"), claude_bin="claude"
    )
    assert res.ok is False and res.returncode == 2


def test_cli_dispatch_reports_noop_when_nothing_changed():
    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_claude_cli

    # rc=0 but no repo changes (cwd is not a git repo -> empty change set) => no-op surfaced.
    res = dispatch_via_claude_cli(
        "do X", cwd="/repo", dry_run=False, runner=lambda c, w, t: (0, "done"), claude_bin="claude"
    )
    assert res.ok is True
    assert res.changed_files == []
    assert "no-op" in res.reason  # watcher is told nothing changed


def test_cli_dispatch_honors_emergency_stop(monkeypatch):
    from thomas.forge.anvil import evolve_claude_bridge as br2
    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_claude_cli

    monkeypatch.setattr(br2, "emergency_stop_active", lambda: True)
    called = {"n": 0}

    def runner(cmd, cwd, to):
        called["n"] += 1
        return 0, "should not run"

    res = dispatch_via_claude_cli("do X", cwd="/repo", dry_run=False, runner=runner, claude_bin="claude")
    assert res.ok is False and "emergency stop" in res.reason
    assert called["n"] == 0  # the kill switch blocked the live CLI dispatch


def test_compose_headless_prompt_is_edit_only():
    from thomas.forge.anvil.evolve_claude_bridge import compose_headless_prompt

    p = compose_headless_prompt("do x", definition="x is done", plan="edit y.py")
    assert "edit-only builder" in p
    assert "NEW git branch" not in p
    assert "Run the tests" not in p
    assert "do x" in p


def test_cli_dispatch_dry_run_prompt_is_edit_only():
    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_claude_cli

    res = dispatch_via_claude_cli("do x", cwd=".", dry_run=True)
    assert "edit-only builder" in res.prompt
    assert "NEW git branch" not in res.prompt


def test_compose_headless_prompt_is_conversational_not_a_forced_build():
    """The prompt frames a coding ASSISTANT that DECIDES; it no longer forces a build.

    The old forcing line ("Make the required file changes ... now") is gone, the
    conversational framing is present, and there is no intent-classifier language.
    """
    from thomas.forge.anvil.evolve_claude_bridge import compose_headless_prompt

    p = compose_headless_prompt("hi")
    # conversational assistant framing, with an explicit "don't edit for small talk"
    assert "Thomas Code" in p
    assert "greeting" in p.lower() and "small talk" in p.lower()
    assert "do not explore the repo" in p.lower()
    # the message is carried, and editing is CONDITIONAL ("only when ... asks")
    assert "hi" in p
    assert "only when" in p.lower()
    # the old unconditional build order must be gone
    assert "Make the required file changes directly in the working tree now" not in p
    # honesty about the edit/verify loop is preserved for when it DOES build
    assert "edit-only builder" in p and "REAL verification" in p


def test_compose_headless_prompt_weaves_in_conversation_history():
    """Prior turns are woven in so the dispatched turn is a real MULTI-TURN exchange."""
    from thomas.forge.anvil.evolve_claude_bridge import compose_headless_prompt

    history = [
        {"role": "user", "text": "add a hello function"},
        {"role": "assistant", "text": "Done — I added hello() to greet.py."},
    ]
    p = compose_headless_prompt("explain what you just did", history=history)
    assert "Conversation so far" in p
    assert "add a hello function" in p
    assert "I added hello() to greet.py" in p
    assert "explain what you just did" in p


def test_hi_yields_chat_reply_with_no_edits_and_no_verify_loop(tmp_path):
    """Saying "hi" produces a normal reply, edits NOTHING, and never runs the verify
    loop — it is NOT a failed/no-op build, just a chat turn.

    The fake agent does exactly what a reframed model does for small talk: it emits
    a `say` message and touches no files. The engine must then NOT run a verify
    subprocess (no changed files), so no `run` tool event is emitted, and the result
    is a clean rc=0 with an empty change set.
    """
    import json

    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_claude_cli

    _init_repo(tmp_path)
    (tmp_path / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(tmp_path)

    def runner(cmd, cwd, to):
        # a greeting: reply in words, edit NO files
        return 0, json.dumps(
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hey! How can I help?"}]}}
        )

    events: list[dict] = []
    res = dispatch_via_claude_cli(
        "hi", cwd=tmp_path, dry_run=False, runner=runner, claude_bin="claude", emit=events.append
    )
    # a conversational reply was streamed as a normal chat message
    assert any(e.get("fc") == "say" and "How can I help" in e.get("text", "") for e in events)
    # NOTHING was edited and the verify loop never ran (no engine `run` tool event)
    assert res.changed_files == []
    assert not any(e.get("fc") == "tool" and e.get("name") == "run" for e in events)
    # rc is clean -> the UI will NOT render this as a failed build
    assert res.returncode == 0 and res.ok is True


def test_real_build_request_still_edits_and_verifies_with_history(tmp_path):
    """A genuine build request still edits the tree AND the engine verifies it —
    even when prior conversation history is threaded through."""
    import json

    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_claude_cli

    _init_repo(tmp_path)
    (tmp_path / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(tmp_path)

    def runner(cmd, cwd, to):
        # the build prompt must carry the prior turn (multi-turn), then edit a file
        assert "earlier idea" in cmd[2]
        (tmp_path / "feature.py").write_text("def forge_smoke():\n    return 7\n", encoding="utf-8")
        return 0, json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "name": "Write", "input": {"file_path": "feature.py"}}]},
            }
        )

    events: list[dict] = []
    res = dispatch_via_claude_cli(
        "now build it",
        cwd=tmp_path,
        dry_run=False,
        runner=runner,
        claude_bin="claude",
        emit=events.append,
        history=[{"role": "user", "text": "earlier idea: add forge_smoke"}],
    )
    assert res.ok is True and res.returncode == 0
    assert "feature.py" in res.changed_files
    # both halves of the loop fired: a real edit AND the engine's verify run
    assert any(e.get("fc") == "tool" and e.get("name") == "Write" for e in events)
    assert any(e.get("fc") == "tool" and e.get("name") == "run" for e in events)
    assert "verified" in res.reason


# -- streaming forge-event protocol (SC-AL-2 / SC-TR-1) ----------------------


def test_claude_cmd_requests_streaming_json():
    """The live claude invocation must ask for incremental structured events."""
    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_claude_cli

    captured = {}

    def runner(cmd, cwd, to):
        captured["cmd"] = cmd
        return 0, ""

    dispatch_via_claude_cli("do x", cwd="/repo", dry_run=False, runner=runner, claude_bin="claude")
    cmd = captured["cmd"]
    # --output-format stream-json --verbose => one JSON event per line as it happens.
    assert "--output-format" in cmd
    i = cmd.index("--output-format")
    assert cmd[i + 1] == "stream-json"
    assert "--verbose" in cmd


def test_translate_claude_event_distinguishes_say_tool_result_and_error():
    import json

    from thomas.forge.anvil.evolve_claude_bridge import translate_claude_event

    say = translate_claude_event(
        json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "I'll edit it."}]}})
    )
    assert say == [{"fc": "say", "text": "I'll edit it."}]

    tool = translate_claude_event(
        json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "a.py"}}]},
            }
        )
    )
    assert tool[0]["fc"] == "tool" and tool[0]["name"] == "Edit"
    assert "a.py" in tool[0]["text"]

    tres = translate_claude_event(
        json.dumps(
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok", "is_error": False}]}}
        )
    )
    assert tres == [{"fc": "tool_result", "text": "ok", "is_error": False}]

    err = translate_claude_event(json.dumps({"type": "result", "subtype": "error", "result": "boom", "is_error": True}))
    assert err == [{"fc": "error", "text": "boom"}]


def test_translate_reasoning_yields_distinct_insight_and_keeps_full_reason():
    """A reasoning/thinking event yields a DISTINCT ``fc:insight`` (the salient
    mid-task observation) AND still the full ``fc:reason`` for the collapsible view.

    The insight is sourced organically from the model's OWN reasoning — never a
    keyword scan / canned trigger — and is its own kind, not folded into
    say/tool/tool_result.
    """
    import json

    from thomas.forge.anvil.evolve_claude_bridge import translate_claude_event

    thinking = "I'm noticing the auth flow has no test coverage. Let me add a regression test before refactoring."
    out = translate_claude_event(
        json.dumps({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": thinking}]}})
    )
    kinds = [e["fc"] for e in out]
    # a distinct insight is surfaced, BEFORE (above) the full collapsed reasoning
    assert "insight" in kinds and "reason" in kinds
    assert kinds.index("insight") < kinds.index("reason")
    # the insight carries the model's REAL observation (evidence-tied, not invented)
    insight = next(e for e in out if e["fc"] == "insight")
    assert "auth flow" in insight["text"]
    # it is its OWN card type — never a say/tool/tool_result
    assert insight["fc"] not in ("say", "tool", "tool_result")
    # the FULL reasoning is preserved verbatim for the collapsible view
    reason = next(e for e in out if e["fc"] == "reason")
    assert reason["text"] == thinking


def test_thin_reasoning_emits_reason_but_no_fabricated_insight():
    """NO FAKE SUCCESS: reasoning too thin to carry a real observation produces the
    full ``reason`` (collapsible) but NEVER an invented ``insight`` card."""
    import json

    from thomas.forge.anvil.evolve_claude_bridge import translate_claude_event

    out = translate_claude_event(
        json.dumps({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "Ok."}]}})
    )
    kinds = [e["fc"] for e in out]
    assert "reason" in kinds  # the full reasoning is still available
    assert "insight" not in kinds  # nothing salient -> no fabricated insight


def test_cli_dispatch_streams_insight_distinct_from_say_tool_result():
    """End to end (buffered path): a POST-OBSERVATION reasoning event yields a
    ``fc:insight``, surfaced DISTINCT from say/tool/tool_result.

    The insight-bearing reasoning follows a real tool observation (the structural
    gate only admits insights AFTER the run has observed something), and it is its
    own card kind — never folded into say/tool/tool_result."""
    import json

    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_claude_cli

    stream = "\n".join(
        [
            # the run OBSERVES first (reads a file)...
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "parser.py"}}]},
                }
            ),
            json.dumps(
                {
                    "type": "user",
                    "message": {"content": [{"type": "tool_result", "content": "def parse(): ...", "is_error": False}]},
                }
            ),
            # ...THEN reasons about what it saw -> a genuine post-observation insight
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {
                                "type": "thinking",
                                "thinking": "I'm noticing the parser has no test for empty input. I'll cover that edge case.",
                            }
                        ]
                    },
                }
            ),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Adding the test."}]}}),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "a.py"}}]},
                }
            ),
            json.dumps(
                {
                    "type": "user",
                    "message": {"content": [{"type": "tool_result", "content": "done", "is_error": False}]},
                }
            ),
        ]
    )
    events: list[dict] = []
    dispatch_via_claude_cli(
        "do x",
        cwd="/repo",
        dry_run=False,
        runner=lambda c, w, t: (0, stream),
        claude_bin="claude",
        emit=events.append,
    )
    kinds = [e["fc"] for e in events]
    # exactly one insight, carrying the model's REAL observation
    assert kinds.count("insight") == 1
    insight = next(e for e in events if e["fc"] == "insight")
    assert "parser" in insight["text"]
    # the insight sits ABOVE the live tool activity that FOLLOWS it (the Edit)
    assert kinds.index("insight") < len(kinds) - 1 - kinds[::-1].index("tool")
    # the other kinds remain present and separate (insight is not folded into them)
    for k in ("say", "tool", "tool_result"):
        assert k in kinds


def test_pre_observation_plan_suppressed_post_observation_insight_surfaces_and_dedupes():
    """The structural fix end to end (buffered path).

    A run's FIRST reasoning block is the model's PLAN — an enumerated list of
    imperatives ("1. Create X 2. …") produced BEFORE it has observed anything — so
    it must surface NO insight (only its collapsible ``reason``). After the model
    actually OBSERVES (a tool_use + tool_result), its reactive reasoning DOES
    surface; and two near-identical observations ("good understanding of the
    directory" / "good picture of the package") are the SAME beat, so they dedupe
    to a SINGLE insight card. No "Create X…" restatement, no dangling list number,
    no near-duplicate."""
    import json

    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_claude_cli

    stream = "\n".join(
        [
            # FIRST reasoning block = the PLAN, before any observation. An enumerated
            # list of imperatives, exactly the "Create `_note3.py` … docstring 3."
            # task-restatement the operator saw leak.
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
            # the model OBSERVES: lists the directory, sees the result
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
            # post-observation reasoning #1 -> a genuine insight
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
            # post-observation reasoning #2 -> the SAME beat, must dedupe away
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
    events: list[dict] = []
    dispatch_via_claude_cli(
        "do x",
        cwd="/repo",
        dry_run=False,
        runner=lambda c, w, t: (0, stream),
        claude_bin="claude",
        emit=events.append,
    )
    insights = [e for e in events if e["fc"] == "insight"]
    # ONLY the post-observation observation surfaced, deduped to exactly one card
    assert len(insights) == 1
    text = insights[0]["text"]
    # it is the genuine observation, NOT the pre-observation "Create X…" plan
    assert "understanding" in text
    assert "create" not in text.lower()
    # no dangling enumeration number trailing the card
    assert not text.rstrip().endswith("3.")
    assert not text.rstrip().endswith("3")
    # the plan's FULL reasoning is still preserved for the collapsible view (honesty:
    # the reasoning is shown, it just isn't promoted to an insight)
    assert any(e["fc"] == "reason" and "Create" in e["text"] for e in events)


def test_translate_claude_event_never_crashes_on_garbage():
    from thomas.forge.anvil.evolve_claude_bridge import translate_claude_event

    # A malformed (non-JSON) line degrades to a best-effort say, never raises.
    out = translate_claude_event("not json at all {{{")
    assert out == [{"fc": "say", "text": "not json at all {{{"}]


def test_cli_dispatch_emits_structured_events_in_order():
    """End to end (buffered path): the captured CLI stream is translated into
    distinct forge events the route can re-stream and the UI can render."""
    import json

    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_claude_cli

    stream = "\n".join(
        [
            json.dumps({"type": "system", "subtype": "init", "model": "claude-sonnet"}),
            json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "Editing now."}]}}),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "a.py"}}]},
                }
            ),
            json.dumps(
                {
                    "type": "user",
                    "message": {"content": [{"type": "tool_result", "content": "done", "is_error": False}]},
                }
            ),
        ]
    )
    events: list[dict] = []
    dispatch_via_claude_cli(
        "do x",
        cwd="/repo",
        dry_run=False,
        runner=lambda c, w, t: (0, stream),
        claude_bin="claude",
        emit=events.append,
    )
    kinds = [e["fc"] for e in events]
    # The leading system/init line is internal CLI plumbing -- per the forge-event
    # protocol it is NEVER surfaced (the user must not see session/model plumbing),
    # so it produces no event. Only the real turn content streams through.
    assert kinds == ["say", "tool", "tool_result"]


# -- GPT brain: IN-PROCESS via Thomas's own ChatGPT-OAuth AgentLoop (NO codex CLI) --


def test_forge_build_path_has_no_codex_cli_references():
    """The Forge build path must NEVER shell out to the codex CLI again.

    Source-level guard: the engine modules carry zero codex-CLI surface. This is
    the regression that keeps codex from creeping back into the build path and
    vomiting its broken startup (skill-load / MCP OAuth / 'failed to claim job')
    into the user's face.
    """
    import pathlib

    import thomas.cli.commands.evolve as evolve_cli

    bridge_src = pathlib.Path(br.__file__).read_text(encoding="utf-8")
    cli_src = pathlib.Path(evolve_cli.__file__).read_text(encoding="utf-8")
    for forbidden in ("codex exec", "dispatch_via_codex_cli", 'which("codex"', "translate_codex_event"):
        assert forbidden not in bridge_src, f"{forbidden!r} leaked back into the bridge"
        assert forbidden not in cli_src, f"{forbidden!r} leaked back into the CLI dispatch"
    # The deleted symbols are truly gone from the module API.
    assert not hasattr(br, "dispatch_via_codex_cli")
    assert not hasattr(br, "translate_codex_event")
    # ...but the in-process GPT dispatcher exists.
    assert hasattr(br, "dispatch_via_agent_loop")


def test_agent_loop_dispatch_dry_run_does_not_invoke_anything():
    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_agent_loop

    called = {"runner": 0, "token": 0}

    def runner(p, cwd, to, emit):
        called["runner"] += 1
        return 0, "should not run"

    def token_check():
        called["token"] += 1
        return True

    res = dispatch_via_agent_loop("do X", cwd="/repo", dry_run=True, runner=runner, token_check=token_check)
    assert res.ok is False and "dry-run" in res.reason
    assert called["runner"] == 0  # nothing invoked in dry-run
    assert "do X" in res.prompt


def test_agent_loop_dispatch_missing_chatgpt_token_is_honest_not_spew():
    """No ChatGPT token => the HONEST connect-ChatGPT message, never a codex/MCP
    error spew, never an exception, never a silent fallback to another brain."""
    from thomas.forge.anvil.evolve_claude_bridge import CHATGPT_NOT_CONNECTED_MSG, dispatch_via_agent_loop

    ran = {"n": 0}

    def runner(p, cwd, to, emit):
        ran["n"] += 1
        return 0, "must not run without a token"

    res = dispatch_via_agent_loop(
        "build something",
        cwd="/repo",
        dry_run=False,
        runner=runner,
        token_check=lambda: False,  # ChatGPT NOT connected
    )
    assert res.ok is False
    assert res.reason == CHATGPT_NOT_CONNECTED_MSG
    assert "connect" in res.reason.lower() and "ChatGPT" in res.reason
    assert ran["n"] == 0  # fail-closed: the build never started


def test_agent_loop_dispatch_honors_emergency_stop(monkeypatch):
    from thomas.forge.anvil import evolve_claude_bridge as br2
    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_agent_loop

    monkeypatch.setattr(br2, "emergency_stop_active", lambda: True)
    ran = {"n": 0}

    def runner(p, cwd, to, emit):
        ran["n"] += 1
        return 0, "should not run"

    res = dispatch_via_agent_loop("do X", cwd="/repo", dry_run=False, runner=runner, token_check=lambda: True)
    assert res.ok is False and "emergency stop" in res.reason
    assert ran["n"] == 0  # the kill switch blocked the in-process dispatch too


def test_agent_loop_dispatch_edits_and_verifies_via_in_process_loop(tmp_path):
    """The GPT brain edits the tree and the ENGINE verifies it — same forge stream
    (say / tool / tool_result) and same verify loop as the claude path, but with NO
    codex subprocess: the loop pass runs in-process."""
    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_agent_loop

    _init_repo(tmp_path)
    (tmp_path / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(tmp_path)

    def runner(prompt, cwd, to, emit):
        # stand in for the in-process AgentLoop pass: stream forge events + edit a file
        emit({"fc": "say", "text": "Editing now."})
        emit({"fc": "tool", "name": "fs.write_file", "text": "file_path: feature.py"})
        (tmp_path / "feature.py").write_text("def gpt_smoke():\n    return 7\n", encoding="utf-8")
        emit({"fc": "tool_result", "text": "wrote feature.py", "is_error": False})
        return 0, "Done."

    events: list[dict] = []
    res = dispatch_via_agent_loop(
        "build gpt_smoke",
        cwd=tmp_path,
        dry_run=False,
        runner=runner,
        token_check=lambda: True,
        emit=events.append,
    )
    assert res.ok is True and res.returncode == 0
    assert "feature.py" in res.changed_files
    # the loop's edit AND the engine's verify run both reached the SAME stream
    assert any(e.get("fc") == "say" and "Editing" in e.get("text", "") for e in events)
    assert any(e.get("fc") == "tool" and e.get("name") == "run" for e in events)  # engine verify
    assert "verified" in res.reason
    assert "ChatGPT OAuth" in res.reason  # surfaced as the GPT brain, not a CLI


def test_agent_loop_default_path_uses_agentloop_and_llmclient_not_subprocess(tmp_path, monkeypatch):
    """The DEFAULT (no runner) GPT path constructs Thomas's OWN AgentLoop + LLMClient
    and maps their events to forge events — it never spawns a `codex` subprocess.

    AgentLoop/LLMClient are mocked so no network/CLI is touched; the test proves the
    wiring routes through the in-process loop.
    """
    import thomas.agent.loop as agent_loop_mod
    import thomas.core.llm_client as llm_mod
    from thomas.core.events import AgentEvent
    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_agent_loop

    _init_repo(tmp_path)
    (tmp_path / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(tmp_path)

    built = {"agent": 0, "llm": 0}

    class _FakeLLM:
        def __init__(self, *a, **k):
            built["llm"] += 1

        async def close(self):
            return None

    class _FakeAgentLoop:
        def __init__(self, *a, **k):
            built["agent"] += 1

        async def run(self, prompt, **kw):
            # a real edit in the worktree, then a typed tool call + result + done
            (tmp_path / "feature.py").write_text("def gpt_smoke():\n    return 7\n", encoding="utf-8")
            yield AgentEvent.text_delta("Editing now.")
            yield AgentEvent.tool_start("t1", "fs.write_file", {"file_path": "feature.py"})
            yield AgentEvent.tool_result("t1", "fs.write_file", "wrote feature.py", True, 1.0)
            yield AgentEvent.agent_done("Done.", iterations=1, tool_calls=1)

    monkeypatch.setattr(agent_loop_mod, "AgentLoop", _FakeAgentLoop)
    monkeypatch.setattr(llm_mod, "LLMClient", _FakeLLM)

    events: list[dict] = []
    res = dispatch_via_agent_loop(
        "build gpt_smoke",
        cwd=tmp_path,
        dry_run=False,
        token_check=lambda: True,
        emit=events.append,
    )
    assert built["agent"] == 1 and built["llm"] == 1  # routed through the in-process loop
    assert res.ok is True and res.returncode == 0
    assert "feature.py" in res.changed_files
    # the loop's AgentEvents were mapped onto the forge stream, plus the engine verify
    assert any(e.get("fc") == "say" and "Editing" in e.get("text", "") for e in events)
    assert any(e.get("fc") == "tool" and e.get("name") == "fs.write_file" for e in events)
    assert any(e.get("fc") == "tool_result" and not e.get("is_error") for e in events)
    assert any(e.get("fc") == "tool" and e.get("name") == "run" for e in events)


def test_agent_loop_dispatch_surfaces_failure_when_verify_never_passes(tmp_path):
    """No fake success for GPT either: a change that never verifies is honestly a failure."""
    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_agent_loop

    _init_repo(tmp_path)
    (tmp_path / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(tmp_path)

    def runner(prompt, cwd, to, emit):
        (tmp_path / "feature.py").write_text("def still_broken(:\n", encoding="utf-8")  # always broken
        return 0, "editing"

    res = dispatch_via_agent_loop(
        "build feature",
        cwd=tmp_path,
        dry_run=False,
        runner=runner,
        token_check=lambda: True,
        max_fix_iters=1,
    )
    assert res.ok is False and res.returncode != 0
    assert "verification failed" in res.reason


# -- engine-side verify step (SC-AL-1: real reason→edit→verify→iterate) -------


def _init_repo(root):
    """A throwaway git repo with deterministic identity/signing."""
    from thomas.forge.anvil.forge_code_git import _run_git

    _run_git(root, ["init"])
    _run_git(root, ["config", "user.email", "test@example.com"])
    _run_git(root, ["config", "user.name", "Forge Test"])
    _run_git(root, ["config", "commit.gpgsign", "false"])


def _commit_all(root):
    from thomas.forge.anvil.forge_code_git import _run_git

    _run_git(root, ["add", "-A"])
    _run_git(root, ["commit", "-m", "base"])


def test_compose_headless_prompt_is_honest_about_engine_verify():
    """The prompt no longer falsely claims nothing is ever run: the engine verifies."""
    from thomas.forge.anvil.evolve_claude_bridge import compose_headless_prompt

    p = compose_headless_prompt("do x")
    assert "edit-only builder" in p  # the AGENT is still edit-only (SC-SE-3 honesty)
    assert "reason→edit→verify" in p
    assert "REAL verification" in p
    # but it must NOT re-introduce the desktop/branch-mode language
    assert "NEW git branch" not in p
    assert "Run the tests" not in p


def test_verify_python_changes_passes_on_valid_file(tmp_path):
    """A real subprocess byte-compiles the change; a valid file => exit 0, ok."""
    from thomas.forge.anvil.evolve_claude_bridge import verify_python_changes

    (tmp_path / "good.py").write_text("x = 1 + 1\n", encoding="utf-8")
    events: list[dict] = []
    ok, rc, _summary = verify_python_changes(tmp_path, ["good.py"], events.append)
    assert ok is True and rc == 0
    # a genuine tool CALL + tool RESULT were streamed, the result is not an error
    kinds = [(e.get("fc"), e.get("name"), e.get("is_error")) for e in events]
    assert ("tool", "run", None) in kinds
    assert any(e["fc"] == "tool_result" and not e.get("is_error") for e in events)


def test_verify_python_changes_fails_on_syntax_error(tmp_path):
    """A real subprocess surfaces a REAL non-zero exit for a broken file (no fake pass)."""
    from thomas.forge.anvil.evolve_claude_bridge import verify_python_changes

    (tmp_path / "broken.py").write_text("def oops(:\n", encoding="utf-8")
    events: list[dict] = []
    ok, rc, _summary = verify_python_changes(tmp_path, ["broken.py"], events.append)
    assert ok is False and rc != 0
    # the failure is reflected back as an errored tool result
    assert any(e["fc"] == "tool_result" and e.get("is_error") for e in events)


def test_verify_python_changes_actually_executes_the_module(tmp_path):
    """Import path EXECUTES the changed module (not just compiles it).

    The module writes a sentinel on import; its presence afterward proves the
    engine really ran the code — the "run it and confirm" half of the loop.
    """
    from thomas.forge.anvil.evolve_claude_bridge import verify_python_changes

    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    sentinel = tmp_path / "ran.flag"
    (tmp_path / "pkg" / "mod.py").write_text(
        "import pathlib\n"
        f"pathlib.Path(r'{sentinel}').write_text('ran', encoding='utf-8')\n"
        "def forge_smoke():\n    return 42\n",
        encoding="utf-8",
    )
    events: list[dict] = []
    ok, rc, _summary = verify_python_changes(tmp_path, ["pkg/mod.py"], events.append)
    assert ok is True and rc == 0
    assert sentinel.exists()  # the module was IMPORTED (executed), not just compiled


def test_cli_dispatch_runs_verify_after_edit(tmp_path):
    """One send: the fake edit pass writes a file, then the ENGINE verifies it.

    Proves SC-AL-1 end to end without a real claude: the transcript carries both
    an edit step (the agent's stream) AND a real run/test step (the engine's
    verify tool call + its real exit-0 result)."""
    import json

    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_claude_cli

    _init_repo(tmp_path)
    (tmp_path / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(tmp_path)

    calls = {"n": 0}

    def runner(cmd, cwd, to):
        calls["n"] += 1
        # the "agent" edit: create a valid python file in the worktree
        (tmp_path / "feature.py").write_text("def forge_smoke():\n    return 42\n", encoding="utf-8")
        return 0, json.dumps(
            {
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "name": "Write", "input": {"file_path": "feature.py"}}]},
            }
        )

    events: list[dict] = []
    res = dispatch_via_claude_cli(
        "add forge_smoke", cwd=tmp_path, dry_run=False, runner=runner, claude_bin="claude", emit=events.append
    )
    assert res.ok is True and res.returncode == 0
    assert calls["n"] == 1  # verify passed first try -> no fix pass
    # both halves of the loop are present: an edit tool call AND the engine RUN step
    assert any(e.get("fc") == "tool" and e.get("name") == "Write" for e in events)
    assert any(e.get("fc") == "tool" and e.get("name") == "run" for e in events)
    assert any(e.get("fc") == "tool_result" and not e.get("is_error") for e in events)
    assert "verified" in res.reason


def test_cli_dispatch_iterates_then_succeeds_when_first_edit_fails_verify(tmp_path):
    """Failure feedback loop: the first edit is broken, verify fails, the engine
    feeds the failure back, the fix pass repairs it, re-verify passes."""
    import json as _json

    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_claude_cli

    _init_repo(tmp_path)
    (tmp_path / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(tmp_path)

    state = {"n": 0, "fix_prompt_seen": False}

    def runner(cmd, cwd, to):
        state["n"] += 1
        prompt = cmd[2]  # claude -p <prompt>
        if state["n"] == 1:
            (tmp_path / "feature.py").write_text("def broken(:\n", encoding="utf-8")  # syntax error
        else:
            # the fix pass must receive the real failure output
            if "FIX pass" in prompt and "exit" in prompt:
                state["fix_prompt_seen"] = True
            (tmp_path / "feature.py").write_text("def fixed():\n    return 1\n", encoding="utf-8")
        return 0, _json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "editing"}]}})

    events: list[dict] = []
    res = dispatch_via_claude_cli(
        "build feature",
        cwd=tmp_path,
        dry_run=False,
        runner=runner,
        claude_bin="claude",
        emit=events.append,
        max_fix_iters=2,
    )
    assert res.ok is True and res.returncode == 0
    assert state["n"] == 2  # one edit pass + one fix pass
    assert state["fix_prompt_seen"] is True  # the failure was fed back to the builder
    # at least one errored verify result (the first attempt) and a clean one (after fix)
    assert any(e.get("fc") == "tool_result" and e.get("is_error") for e in events)
    assert any(e.get("fc") == "tool_result" and not e.get("is_error") for e in events)


def test_cli_dispatch_surfaces_failure_when_verify_never_passes(tmp_path):
    """No fake success: if the change never verifies, the result is honestly a failure."""
    import json

    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_claude_cli

    _init_repo(tmp_path)
    (tmp_path / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(tmp_path)

    def runner(cmd, cwd, to):
        (tmp_path / "feature.py").write_text("def still_broken(:\n", encoding="utf-8")  # always broken
        return 0, json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "editing"}]}})

    events: list[dict] = []
    res = dispatch_via_claude_cli(
        "build feature",
        cwd=tmp_path,
        dry_run=False,
        runner=runner,
        claude_bin="claude",
        emit=events.append,
        max_fix_iters=1,
    )
    assert res.ok is False and res.returncode != 0
    assert "verification failed" in res.reason


# -- multibyte encoding: subprocess byte-read survives UTF-8 AND cp1252 ---------
# The claude CLI is read in BINARY and decoded through _HybridByteDecoder so prose
# punctuation (em-dashes, curly quotes) renders as the real glyph, never `�` —
# whether the CLI emits UTF-8 or, on Windows, single-byte cp1252.


def test_hybrid_decoder_keeps_split_utf8_emdash_intact():
    """A 3-byte em-dash split across two feed chunks decodes to `—`, not `�`."""
    from thomas.forge.anvil.evolve_claude_bridge import _HybridByteDecoder

    dec = _HybridByteDecoder()
    emdash = "—".encode()  # b"\xe2\x80\x94"
    out = dec.feed(emdash[:2])  # boundary splits the multibyte sequence
    out += dec.feed(emdash[2:])
    out += dec.flush()
    assert out == "—"
    assert "�" not in out


def test_hybrid_decoder_splits_4byte_emoji_across_three_chunks():
    """A 4-byte char fed one byte at a time is buffered until complete."""
    from thomas.forge.anvil.evolve_claude_bridge import _HybridByteDecoder

    dec = _HybridByteDecoder()
    rocket = "🚀".encode()  # 4 bytes
    out = dec.feed(rocket[:1]) + dec.feed(rocket[1:3]) + dec.feed(rocket[3:]) + dec.flush()
    assert out == "🚀"
    assert "�" not in out


def test_hybrid_decoder_decodes_cp1252_punctuation_to_real_glyphs():
    """Lone cp1252 bytes (Windows claude CLI) decode to the real glyph, never `�`.

    em-dash 0x97 -> —, single curly quotes 0x91/0x92 -> ‘ ’, double 0x93/0x94 -> “ ”.
    """
    from thomas.forge.anvil.evolve_claude_bridge import _HybridByteDecoder

    dec = _HybridByteDecoder()
    out = dec.feed(b"a \x97 b \x91c\x92 \x93d\x94") + dec.flush()
    assert "—" in out  # 0x97 em-dash, NOT a replacement char
    assert "‘" in out and "’" in out  # ‘ ’
    assert "“" in out and "”" in out  # “ ”
    assert "�" not in out


def test_hybrid_decoder_pure_utf8_roundtrips_exactly():
    """Well-formed UTF-8 (the normal case) is decoded losslessly."""
    from thomas.forge.anvil.evolve_claude_bridge import _HybridByteDecoder

    dec = _HybridByteDecoder()
    s = "It's a test — with “smart” quotes, an em‑dash and emoji 🚀."
    out = dec.feed(s.encode()) + dec.flush()
    assert out == s
    assert "�" not in out


def test_hybrid_decoder_mixed_utf8_and_cp1252_in_one_stream():
    """A stream mixing a UTF-8 em-dash and a cp1252 em-dash decodes BOTH to `—`."""
    from thomas.forge.anvil.evolve_claude_bridge import _HybridByteDecoder

    dec = _HybridByteDecoder()
    out = dec.feed("ok — yes".encode()) + dec.feed(b" and \x97 too") + dec.flush()
    assert out == "ok — yes and — too"
    assert "�" not in out


# -- mid-task insight quality: observation, not prompt-restatement --------------


def test_distill_insight_skips_task_restatement_and_returns_observation():
    """The first insight must be a genuine observation, not an echo of the prompt."""
    from thomas.forge.anvil.evolve_claude_bridge import _distill_insight

    thinking = (
        "The user wants me to examine the config loader and then add caching. "
        "I'll start by reading the module. "
        "The loader parses the TOML on every call and never caches the parsed result."
    )
    insight = _distill_insight(thinking)
    assert "never caches" in insight
    assert not insight.lower().startswith("the user wants")
    assert not insight.lower().startswith("i'll")


def test_distill_insight_emits_nothing_for_pure_planning():
    """Still-just-planning reasoning (all intent, no observation) -> NO card."""
    from thomas.forge.anvil.evolve_claude_bridge import _distill_insight

    thinking = "I'll open the file first. Let me read the imports. Then I will add the function."
    assert _distill_insight(thinking) == ""


def test_distill_insight_keeps_reactive_openers():
    """Reactions ("I'm noticing…", "Looking at…") are NOT preambles — they surface."""
    from thomas.forge.anvil.evolve_claude_bridge import _distill_insight

    assert "auth flow" in _distill_insight("I'm noticing the auth flow has no test coverage at all.")
    assert "shared helper" in _distill_insight("Looking at the router, every route uses a shared helper.")


def test_first_surfaced_insight_is_observation_not_prompt_restatement():
    """End to end: a reasoning block that OPENS with a restatement still surfaces an
    insight about what was found, and the full reasoning is preserved."""
    import json

    from thomas.forge.anvil.evolve_claude_bridge import translate_claude_event

    thinking = (
        "The user wants me to add a health check endpoint. "
        "Looking at the router, every route already returns JSON via a shared helper."
    )
    out = translate_claude_event(
        json.dumps({"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": thinking}]}})
    )
    insight = next(e for e in out if e["fc"] == "insight")
    assert "shared helper" in insight["text"]
    assert "the user wants" not in insight["text"].lower()
    # the FULL reasoning is still preserved verbatim for the collapsible view
    assert any(e["fc"] == "reason" and e["text"] == thinking for e in out)


def test_cli_dispatch_verify_can_be_disabled(tmp_path):
    """The verify step is opt-out (verify=False) and then never runs a check."""
    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_claude_cli

    _init_repo(tmp_path)
    (tmp_path / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(tmp_path)

    def runner(cmd, cwd, to):
        (tmp_path / "feature.py").write_text("def broken(:\n", encoding="utf-8")  # would fail verify
        return 0, ""

    events: list[dict] = []
    res = dispatch_via_claude_cli(
        "x", cwd=tmp_path, dry_run=False, runner=runner, claude_bin="claude", emit=events.append, verify=False
    )
    # no verify => no RUN tool event, and the broken file is not caught here
    assert not any(e.get("fc") == "tool" and e.get("name") == "run" for e in events)
    assert res.returncode == 0


def test_default_emit_writes_utf8_bytes_not_cp1252(monkeypatch):
    """The bridge must put forge events on the wire as UTF-8 bytes regardless of the
    process's text-layer code page.

    This is the root-cause guard for the em-dash/curly-quote corruption: the build
    runs as a child whose ``sys.stdout`` defaults to cp1252 on Windows, so a TEXT
    write of ``—`` would emit the single cp1252 byte 0x97 (invalid UTF-8 to the
    server's byte-level reader). We simulate that cp1252 text layer and assert the
    bytes actually written are UTF-8 ``E2 80 94`` — never the cp1252 0x97.
    """
    import io
    import json
    import sys

    raw = io.BytesIO()
    # A text wrapper whose encoding is cp1252 -- exactly the Windows child default.
    # _default_emit must bypass this layer and write UTF-8 bytes to raw via .buffer.
    fake_stdout = io.TextIOWrapper(raw, encoding="cp1252", newline="")
    monkeypatch.setattr(sys, "stdout", fake_stdout)

    br._default_emit({"fc": "say", "text": "Cache the result — it's hot. “Done”"})
    fake_stdout.flush()

    out = raw.getvalue()
    assert b"\xe2\x80\x94" in out  # em-dash as UTF-8, the correct bytes
    assert b"\x97" not in out  # NOT the cp1252 em-dash byte
    assert b"\xe2\x80\x9c" in out and b"\xe2\x80\x9d" in out  # curly quotes as UTF-8
    # the line round-trips back to the exact glyphs when decoded as UTF-8 (the wire)
    decoded = json.loads(out.decode("utf-8"))
    assert decoded["text"] == "Cache the result — it's hot. “Done”"


def test_distill_insight_suppresses_bare_imperative_directory_intent():
    """A first clause that just names where to look ("Examine `dir`") is intent, not
    an observation -- it is skipped so the first SURFACED insight is a real finding."""
    from thomas.forge.anvil.evolve_claude_bridge import _distill_insight

    thinking = (
        "Examine the `thomas/forge/anvil` directory to understand the bridge. "
        "Check the emit function first. "
        "The bridge writes events with the process default encoding, not UTF-8."
    )
    insight = _distill_insight(thinking)
    assert "not UTF-8" in insight
    assert not insight.lower().startswith("examine")
    assert not insight.lower().startswith("check")


def test_distill_insight_imperative_suppression_keeps_gerund_reactions():
    """The imperative suppression is opener-only: gerund REACTIONS still surface."""
    from thomas.forge.anvil.evolve_claude_bridge import _distill_insight

    # base-form imperative openers are suppressed...
    assert _distill_insight("Read the config loader to see how it parses.") == ""
    assert _distill_insight("Look at the router and the middleware stack.") == ""
    # ...but their gerund reaction-forms (a real observation) are kept intact.
    assert "no caching" in _distill_insight("Reading the loader, there is no caching anywhere.")
    assert "shared helper" in _distill_insight("Looking at the router, every route uses a shared helper.")


def test_distill_insight_strips_dangling_enumeration_number():
    """An enumerated plan item must never surface carrying a bare list number —
    leading "3." or a trailing dangling " 3." is sheared off; a number that is part
    of the prose ("2-sentence", "3 modules") is left intact."""
    from thomas.forge.anvil.evolve_claude_bridge import _distill_insight, _strip_list_artifacts

    # the exact leaked shape: trailing dangling list number after the clause
    assert _strip_list_artifacts("a 2-sentence module docstring 3.") == "a 2-sentence module docstring"
    # leading list marker stripped
    assert _strip_list_artifacts("3. wire it into the package") == "wire it into the package"
    # a number that is genuinely part of the prose is NOT stripped
    assert _strip_list_artifacts("the package has 3 modules") == "the package has 3 modules"
    # distilled through the full path: no trailing bare number on the surfaced clause
    insight = _distill_insight("Reading the package, it exposes a clean three-module surface 2.")
    assert insight and not insight.rstrip().endswith("2")
    assert "three-module surface" in insight


def test_near_identical_insights_are_treated_as_the_same_beat():
    """The dedupe similarity recognises two phrasings of one observation as a repeat,
    while keeping two genuinely distinct observations apart."""
    from thomas.forge.anvil.evolve_claude_bridge import _insight_word_set, _insights_similar

    a = _insight_word_set("Now I have a good understanding of what's in the `thomas/forge/anvil` directory.")
    b = _insight_word_set("Now I have a good picture of the `thomas/forge/anvil` package.")
    assert _insights_similar(a, b)  # same beat -> a repeat
    # two genuinely DISTINCT findings are not merged
    c = _insight_word_set("The loader parses the TOML on every call and never caches it.")
    d = _insight_word_set("Every route returns JSON through one shared helper.")
    assert not _insights_similar(c, d)


def test_stream_state_gate_suppresses_pre_observation_and_dedupes():
    """``_StreamState`` admits an insight ONLY after an observation, and drops a
    near-duplicate of one already surfaced."""
    from thomas.forge.anvil.evolve_claude_bridge import _StreamState

    st = _StreamState()
    # before any observation: the plan is never admitted, however it is phrased
    assert st.admit_insight("Now I have a good understanding of the directory.") is False
    # an observation happens
    st.seen_observation = True
    assert st.admit_insight("Now I have a good understanding of the `thomas/forge/anvil` directory.") is True
    # a near-identical follow-up is the same beat -> dropped
    assert st.admit_insight("Now I have a good picture of the `thomas/forge/anvil` package.") is False
    # a genuinely distinct observation still surfaces
    assert st.admit_insight("The bridge writes events with the process default encoding, not UTF-8.") is True


# -- ENGINE PARITY: GPT in-process AgentLoop gets the SAME insight + reasoning -------


def _run_gpt_translator(events):
    """Drive a simulated GPT-engine ``AgentEvent`` stream through the in-process
    translator, returning ``(emitted_forge_events, translator)``.

    Each item is ``(EventType, data)`` — exactly what ``_agent_loop_pass_async``
    feeds the translator for every event the loop yields.
    """
    from thomas.forge.anvil.evolve_claude_bridge import _AgentLoopForgeTranslator

    out: list[dict] = []
    tr = _AgentLoopForgeTranslator(out.append)
    for et, data in events:
        tr.feed(et.value if hasattr(et, "value") else et, data)
    tr.close()
    return out, tr


def test_gpt_path_thinking_yields_same_post_observation_insight_as_claude():
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
        cwd="/repo",
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
