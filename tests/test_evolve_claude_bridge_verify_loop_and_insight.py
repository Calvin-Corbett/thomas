"""The dispatch verify loop, the repairs that restore what a bad fix destroyed, the hybrid decoder, and insight distillation.

Split from test_evolve_claude_bridge.py on 2026-09-07 so each file stays under the monolith guard's limit.
"""

from __future__ import annotations

import pytest

from tests._evolve_bridge_fakes import _commit_all, _init_repo
from thomas.forge.anvil import evolve_claude_bridge as br


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
    assert "engine checks passed" in res.reason


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


def test_cli_fix_pass_receives_the_same_pass_clock(tmp_path):
    import json

    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_claude_cli

    _init_repo(tmp_path)
    (tmp_path / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(tmp_path)
    prompts = []

    def runner(cmd, cwd, to):
        prompts.append((cmd[2], to))
        (tmp_path / "feature.py").write_text("def broken(:\n" if len(prompts) == 1 else "def fixed():\n    return 1\n")
        return 0, json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "editing"}]}})

    result = dispatch_via_claude_cli(
        "build feature", cwd=tmp_path, dry_run=False, runner=runner, claude_bin="claude", timeout=600
    )
    assert result.ok
    assert len(prompts) == 2
    assert "FIX pass" in prompts[1][0]
    assert all("## Build pass clock\nThis Build pass has 10 minutes" in prompt for prompt, _ in prompts)
    assert [to for _, to in prompts] == [600, 600]


def test_agent_loop_fix_and_continue_passes_receive_the_same_clock(tmp_path):
    from thomas.forge.anvil.build_verify import PASS_WALL_CLOCK_RC
    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_agent_loop

    _init_repo(tmp_path)
    (tmp_path / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(tmp_path)
    prompts = []

    def runner(prompt, cwd, timeout, emit):
        prompts.append((prompt, timeout))
        if len(prompts) == 1:
            (tmp_path / "feature.py").write_text("def broken(:\n", encoding="utf-8")
            return 0, "editing"
        (tmp_path / "feature.py").write_text("def fixed():\n    return 1\n", encoding="utf-8")
        if len(prompts) == 2:
            return PASS_WALL_CLOCK_RC, ""
        return 0, "finished"

    def verifier(cwd, changed, emit):
        verified = (tmp_path / "feature.py").read_text(encoding="utf-8").startswith("def fixed")
        return verified, 0 if verified else 1, "failed check"

    result = dispatch_via_agent_loop(
        "build feature",
        cwd=tmp_path,
        dry_run=False,
        runner=runner,
        token_check=lambda: True,
        verifier=verifier,
        timeout=600,
        max_fix_iters=3,
    )
    assert result.ok, result.reason
    assert len(prompts) == 3
    assert "FIX pass" in prompts[1][0]
    assert "CONTINUE pass" in prompts[2][0]
    assert all("## Build pass clock\nThis Build pass has 10 minutes" in prompt for prompt, _ in prompts)
    assert all(limit == 600 for _, limit in prompts)


def test_verification_fix_and_continuation_get_clock_only_when_known(monkeypatch, tmp_path):
    from thomas.forge.anvil import forge_code_git
    from thomas.forge.anvil.build_verify import _verify_and_iterate

    monkeypatch.setattr(forge_code_git, "project_delta_since", lambda cwd, snap: ["feature.py"])
    (tmp_path / "feature.py").write_text("x = 1\n", encoding="utf-8")
    prompts = []
    state = {"verified": False, "met": False}

    def verifier(cwd, changed, emit):
        return state["verified"], 0 if state["verified"] else 1, "failed check"

    def run_pass(prompt):
        prompts.append(prompt)
        state["verified"] = True
        if "CONTINUE pass" in prompt:
            state["met"] = True
        return 0, "ok"

    def contract():
        return {
            "active": True,
            "verdict": {"met": state["met"], "unmet": ["req:1"] if not state["met"] else []},
            "items": [{"item_id": "req:1", "description": "finish", "checked": True, "satisfied": state["met"]}],
        }

    assert (
        _verify_and_iterate(
            tmp_path,
            {},
            lambda event: None,
            run_pass,
            "build",
            verifier=verifier,
            contract=contract,
            max_fix_iters=2,
            timeout=1800,
        )
        == 0
    )
    assert len(prompts) == 2
    assert "FIX pass" in prompts[0] and "CONTINUE pass" in prompts[1]
    assert all("## Build pass clock\nThis Build pass has 30 minutes" in prompt for prompt in prompts)
    assert all(
        prompt.index("## Build pass clock")
        > prompt.index("Keep working" if "CONTINUE pass" in prompt else "Fix the changed files")
        for prompt in prompts
    )

    from thomas.forge.anvil.bridge_prompts import compose_fix_prompt
    from thomas.forge.anvil.build_verify import _contract_pass_prompt

    assert "## Build pass clock" not in compose_fix_prompt("build", "failed")
    assert "## Build pass clock" not in _contract_pass_prompt("build", [("req:1", "finish")])


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


def test_verification_fix_restores_catastrophically_truncated_web_source(tmp_path):
    """A repair pass cannot turn a substantial app stylesheet into a tiny stub."""
    from thomas.forge.anvil import forge_code_git
    from thomas.forge.anvil.build_verify import _verify_and_iterate

    _init_repo(tmp_path)
    (tmp_path / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(tmp_path)
    snap_before = forge_code_git.snapshot(tmp_path)
    original = "\n".join(f".panel-{index} {{ color: rgb({index % 255}, 20, 30); }}" for index in range(80))
    (tmp_path / "styles.css").write_text(original, encoding="utf-8")
    events: list[dict] = []

    def verifier(cwd, changed, emit):
        return False, 1, "BROWSER_SMOKE_FAILED: linked stylesheet did not load"

    def destructive_fix(_prompt):
        (tmp_path / "styles.css").write_text('@import url("./style.css");\n', encoding="utf-8")
        return 0, "repaired"

    rc = _verify_and_iterate(
        tmp_path,
        snap_before,
        events.append,
        destructive_fix,
        "build the app",
        verifier=verifier,
        max_fix_iters=1,
    )

    assert rc != 0
    assert (tmp_path / "styles.css").read_text(encoding="utf-8") == original
    assert any("destructive truncation" in event.get("text", "") for event in events)


def test_verification_fix_restores_previously_clean_owner_truncated_by_repair(tmp_path):
    from thomas.forge.anvil import forge_code_git
    from thomas.forge.anvil.build_verify import _verify_and_iterate

    _init_repo(tmp_path)
    original_html = "<main>" + ("substantial application markup " * 150) + "</main>\n"
    (tmp_path / "index.html").write_text(original_html, encoding="utf-8")
    (tmp_path / "game.js").write_text("window.ready = true;\n", encoding="utf-8")
    _commit_all(tmp_path)
    snap_before = forge_code_git.snapshot(tmp_path)
    (tmp_path / "game.js").write_text("window.ready = false;\n", encoding="utf-8")
    events: list[dict] = []

    def verifier(_cwd, _changed, _emit):
        return False, 1, "browser failed"

    def destructive_fix(_prompt):
        (tmp_path / "index.html").write_text("<main>stub</main>\n", encoding="utf-8")
        return 0, "repaired"

    rc = _verify_and_iterate(
        tmp_path,
        snap_before,
        events.append,
        destructive_fix,
        "repair app",
        verifier=verifier,
        max_fix_iters=1,
    )

    assert rc != 0
    assert (tmp_path / "index.html").read_text(encoding="utf-8") == original_html
    assert any("destructive truncation" in event.get("text", "") for event in events)


@pytest.mark.parametrize("repair_exit", ["nonzero", "exception"])
def test_verification_restores_clean_owner_when_destructive_repair_does_not_exit_cleanly(tmp_path, repair_exit):
    from thomas.forge.anvil import forge_code_git
    from thomas.forge.anvil.build_verify import _verify_and_iterate

    _init_repo(tmp_path)
    original_html = "<main>" + ("substantial application markup " * 150) + "</main>\n"
    (tmp_path / "index.html").write_text(original_html, encoding="utf-8")
    (tmp_path / "game.js").write_text("window.ready = true;\n", encoding="utf-8")
    _commit_all(tmp_path)
    snap_before = forge_code_git.snapshot(tmp_path)
    (tmp_path / "game.js").write_text("window.ready = false;\n", encoding="utf-8")
    events: list[dict] = []

    def verifier(_cwd, _changed, _emit):
        return False, 1, "browser failed"

    def destructive_fix(_prompt):
        (tmp_path / "index.html").write_text("<main>stub</main>\n", encoding="utf-8")
        if repair_exit == "exception":
            raise RuntimeError("repair crashed")
        return 9, "repair failed"

    rc = _verify_and_iterate(
        tmp_path,
        snap_before,
        events.append,
        destructive_fix,
        "repair app",
        verifier=verifier,
        max_fix_iters=1,
    )

    assert rc != 0
    assert (tmp_path / "index.html").read_text(encoding="utf-8") == original_html
    assert any("destructive truncation" in event.get("text", "") for event in events)


def test_verification_fix_restores_previously_clean_file_deleted_by_repair(tmp_path):
    from thomas.forge.anvil import forge_code_git
    from thomas.forge.anvil.build_verify import _verify_and_iterate

    _init_repo(tmp_path)
    original_css = ".panel { color: gold; }\n" * 80
    (tmp_path / "styles.css").write_text(original_css, encoding="utf-8")
    (tmp_path / "game.js").write_text("window.ready = true;\n", encoding="utf-8")
    _commit_all(tmp_path)
    snap_before = forge_code_git.snapshot(tmp_path)
    (tmp_path / "game.js").write_text("window.ready = false;\n", encoding="utf-8")

    def verifier(_cwd, _changed, _emit):
        return False, 1, "browser failed"

    def destructive_fix(_prompt):
        (tmp_path / "styles.css").unlink()
        return 0, "repaired"

    rc = _verify_and_iterate(
        tmp_path,
        snap_before,
        lambda _event: None,
        destructive_fix,
        "repair app",
        verifier=verifier,
        max_fix_iters=1,
    )

    assert rc != 0
    assert (tmp_path / "styles.css").read_text(encoding="utf-8") == original_css


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
