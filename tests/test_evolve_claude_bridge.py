"""Safety + behavior of the Claude-Code build bridge (fake driver; no real PC control).

The whole point of these tests is to prove the bridge CANNOT control the PC unless
every gate passes, and that even then it only types into a matched window.
"""

from __future__ import annotations

import os

import pytest

from tests._evolve_bridge_fakes import (  # noqa: F401
    FakeDriver,
    _commit_all,
    _enabled_cfg,
    _funnel_fake_model_call,
    _init_repo,
    clean_git_repo,
)
from thomas.forge.anvil import evolve_claude_bridge as br
from thomas.forge.anvil.evolve_claude_bridge import (
    BridgeConfig,
    ClaudeCodeBridge,
    compose_claude_prompt,
)


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


def test_cli_dispatch_runs_with_safe_toolset_and_reports(clean_git_repo):
    from thomas.forge.anvil.evolve_claude_bridge import SAFE_CLI_TOOLS, dispatch_via_claude_cli

    captured = {}

    def runner(cmd, cwd, to):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        (clean_git_repo / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")
        return 0, "built the change"

    res = dispatch_via_claude_cli(
        "add a docstring", cwd=clean_git_repo, dry_run=False, runner=runner, claude_bin="claude"
    )
    assert res.ok is True and res.returncode == 0
    assert captured["cmd"][:2] == ["claude", "-p"]
    assert "--allowedTools" in captured["cmd"]
    assert "--model" in captured["cmd"]  # explicit model (headless can't inherit the session model)
    # Guarded is edit-only: Bash is denied, never included in either allowlist.
    allowed = captured["cmd"][captured["cmd"].index("--allowedTools") + 1 : captured["cmd"].index("--disallowedTools")]
    assert "Bash" not in allowed
    assert captured["cmd"][captured["cmd"].index("--disallowedTools") + 1] == "Bash"
    for tool in SAFE_CLI_TOOLS:
        assert tool in captured["cmd"]


def test_cli_dispatch_reports_failure_on_nonzero_exit(clean_git_repo):
    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_claude_cli

    res = dispatch_via_claude_cli(
        "do X", cwd=clean_git_repo, dry_run=False, runner=lambda c, w, t: (2, "boom"), claude_bin="claude"
    )
    assert res.ok is False and res.returncode == 2


def test_cli_dispatch_reports_noop_when_nothing_changed(clean_git_repo):
    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_claude_cli

    # rc=0 with no repo changes and no conversational reply => no-op surfaced.
    res = dispatch_via_claude_cli(
        "do X", cwd=clean_git_repo, dry_run=False, runner=lambda c, w, t: (0, "done"), claude_bin="claude"
    )
    assert res.ok is False
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


def test_compose_headless_prompt_describes_the_build_role_truthfully():
    from thomas.forge.anvil.evolve_claude_bridge import compose_headless_prompt

    p = compose_headless_prompt("do x", definition="x is done", plan="edit y.py")
    # Guarded edits without a direct host shell and consumes engine verification.
    assert "edit-only builder" not in p
    assert "Direct shell is unavailable" in p
    assert "bounded verifier runs after the edit pass" in p
    assert "NEW git branch" not in p
    assert "Run the tests" not in p
    assert "do x" in p


def test_headless_prompt_names_pass_limit_only_when_present():
    from thomas.forge.anvil.evolve_claude_bridge import compose_headless_prompt

    prompt = compose_headless_prompt("build", timeout=1800)
    assert "## User\nbuild\n\n## Build pass clock\nThis Build pass has 30 minutes" in prompt
    assert "Start long test runs early" in prompt
    assert "stop waiting and finish with what you have verified" in prompt
    assert "saying what is still unrun" in prompt
    assert "1 minute before it is stopped" in compose_headless_prompt("build", timeout=60)
    assert "1 minute and 1 second before it is stopped" in compose_headless_prompt("build", timeout=61)
    assert "1 second before it is stopped" in compose_headless_prompt("build", timeout=1)
    assert "1 minute and 30 seconds before it is stopped" in compose_headless_prompt("build", timeout=90.0)
    for limit in (None, 0):
        assert "## Build pass clock" not in compose_headless_prompt("build", timeout=limit)


@pytest.mark.parametrize("dispatcher", ["dispatch_via_claude_cli", "dispatch_via_agent_loop"])
@pytest.mark.parametrize("timeout, duration", [(600, "10 minutes"), (1800, "30 minutes"), (3600, "60 minutes")])
def test_headless_dispatch_dry_run_passes_its_timeout(dispatcher, timeout, duration):
    from thomas.forge.anvil import evolve_claude_bridge

    def unexpected_runner(*args, **kwargs):
        pytest.fail("dry_run must not invoke the injected runner")

    dispatch = getattr(evolve_claude_bridge, dispatcher)
    result = dispatch("build", cwd=".", timeout=timeout, runner=unexpected_runner, dry_run=True)
    assert result.ok is False
    assert f"{duration} before it is stopped, finished or not" in result.prompt


def test_cli_dispatch_dry_run_prompt_describes_the_build_role_truthfully():
    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_claude_cli

    res = dispatch_via_claude_cli("do x", cwd=".", dry_run=True)
    # Dry-run uses the default guarded policy and must describe it honestly.
    assert "edit-only builder" not in res.prompt
    assert "Direct shell is unavailable" in res.prompt
    assert "bounded verifier runs after the edit pass" in res.prompt
    assert "NEW git branch" not in res.prompt


def test_compose_headless_prompt_is_conversational_not_a_forced_build():
    """The prompt frames a coding ASSISTANT that DECIDES; it no longer forces a build.

    The old forcing line ("Make the required file changes ... now") is gone, the
    conversational framing is present, and there is no intent-classifier language.
    """
    from thomas.forge.anvil.evolve_claude_bridge import compose_headless_prompt

    p = compose_headless_prompt("hi")
    # conversational assistant framing, with an explicit "don't edit for small talk"
    assert "You are Thomas" in p
    assert "greeting" in p.lower() and "small talk" in p.lower()
    assert "no reading files" in p.lower()
    # the message is carried, and editing is CONDITIONAL ("only when ... asks")
    assert "hi" in p
    assert "only when" in p.lower()
    # the old unconditional build order must be gone
    assert "Make the required file changes directly in the working tree now" not in p
    # Guarded builds use the engine verifier rather than a direct model shell.
    assert "Direct shell is unavailable" in p
    assert "bounded verifier runs after the edit pass" in p


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


def test_gpt_hi_yields_chat_reply_without_failed_build_state(tmp_path):
    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_agent_loop

    _init_repo(tmp_path)
    (tmp_path / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(tmp_path)

    def runner(prompt, cwd, timeout, emit):
        emit({"fc": "say", "text": "Hey! What are we working on?"})
        return 0, "Hey! What are we working on?"

    res = dispatch_via_agent_loop(
        "hi",
        cwd=tmp_path,
        dry_run=False,
        runner=runner,
        token_check=lambda: True,
    )

    assert res.ok is True
    assert res.changed_files == []
    assert "replied without changing files" in res.reason


@pytest.mark.parametrize("engine", ["claude", "gpt"])
@pytest.mark.parametrize("leaves_partial_change", [False, True])
def test_action_refusal_without_tool_activity_is_not_a_success(tmp_path, engine, leaves_partial_change):
    import json

    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_agent_loop, dispatch_via_claude_cli

    _init_repo(tmp_path)
    (tmp_path / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(tmp_path)
    refusal = "I can't create the app because the required file tool isn't available."
    if engine == "claude":

        def runner(*_args):
            if leaves_partial_change:
                (tmp_path / "partial.html").write_text("<main>unfinished</main>\n", encoding="utf-8")
            return 0, "\n".join(
                [
                    json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": refusal}]}}),
                    json.dumps({"type": "result", "result": refusal, "is_error": False}),
                ]
            )

        result = dispatch_via_claude_cli(
            "Build a web app", cwd=tmp_path, dry_run=False, runner=runner, claude_bin="claude"
        )
    else:

        def runner(_prompt, _cwd, _timeout, emit):
            if leaves_partial_change:
                (tmp_path / "partial.html").write_text("<main>unfinished</main>\n", encoding="utf-8")
            emit({"fc": "final", "text": refusal})
            return 0, refusal

        result = dispatch_via_agent_loop(
            "Build a web app", cwd=tmp_path, dry_run=False, runner=runner, token_check=lambda: True
        )

    assert result.ok is False
    assert result.changed_files == (["partial.html"] if leaves_partial_change else [])
    assert "could not complete" in result.reason
    assert ("partial file changes" in result.reason) is leaves_partial_change


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
    assert "engine checks passed" in res.reason


# -- streaming forge-event protocol (SC-AL-2 / SC-TR-1) ----------------------
