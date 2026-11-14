"""The bridge translates Claude's stream into forge events, and surfaces insight without restating the prompt.

Split from test_evolve_claude_bridge.py on 2026-09-07 so each file stays under the monolith guard's limit.
"""

from __future__ import annotations

from tests._evolve_bridge_fakes import clean_git_repo  # noqa: F401
from thomas.forge.anvil import evolve_claude_bridge as br


def test_claude_cmd_requests_streaming_json(clean_git_repo):
    """The live claude invocation must ask for incremental structured events."""
    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_claude_cli

    captured = {}

    def runner(cmd, cwd, to):
        captured["cmd"] = cmd
        return 0, ""

    dispatch_via_claude_cli("do x", cwd=clean_git_repo, dry_run=False, runner=runner, claude_bin="claude")
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
    assert say == [{"fc": "say", "text": "I'll edit it.", "source": "model"}]

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
    assert err == [{"fc": "error", "text": "boom", "provider_text": "boom"}]

    final = translate_claude_event(
        json.dumps({"type": "result", "subtype": "success", "result": "Built and verified the app.", "is_error": False})
    )
    assert final == [{"fc": "final", "text": "Built and verified the app."}]


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


def test_cli_dispatch_streams_insight_distinct_from_say_tool_result(clean_git_repo):
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
        cwd=clean_git_repo,
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


def test_pre_observation_plan_suppressed_post_observation_insight_surfaces_and_dedupes(clean_git_repo):
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
        cwd=clean_git_repo,
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
    assert out == [{"fc": "say", "text": "not json at all {{{", "source": "process_output"}]


def test_cli_dispatch_emits_structured_events_in_order(clean_git_repo):
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
        cwd=clean_git_repo,
        dry_run=False,
        runner=lambda c, w, t: (0, stream),
        claude_bin="claude",
        emit=events.append,
    )
    kinds = [e["fc"] for e in events]
    # The leading system/init line is internal CLI plumbing and is never shown as text. Since Build turns record the
    # model that actually answered (build_model_receipt), it produces ONE receipt event that names the model; the
    # turn's real content follows it, in order.
    assert kinds == ["meta", "say", "tool", "tool_result"]
    assert events[0].get("receipt") == "model"
    assert "claude-sonnet" in json.dumps(events[0])


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
