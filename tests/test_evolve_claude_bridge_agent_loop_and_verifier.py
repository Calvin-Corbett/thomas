"""The in-process agent loop dispatch, and the verifier that checks what a build left behind.

Split from test_evolve_claude_bridge.py on 2026-09-07 so each file stays under the monolith guard's limit.
"""
from __future__ import annotations

from tests._evolve_bridge_fakes import _commit_all, _init_repo


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
    assert "engine checks passed" in res.reason
    assert "ChatGPT OAuth" in res.reason  # surfaced as the GPT brain, not a CLI


def test_agent_loop_dispatch_does_not_claim_preexisting_dirty_files(tmp_path):
    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_agent_loop

    _init_repo(tmp_path)
    (tmp_path / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(tmp_path)
    (tmp_path / "already-dirty.txt").write_text("older work\n", encoding="utf-8")

    res = dispatch_via_agent_loop(
        "make a new change",
        cwd=tmp_path,
        dry_run=False,
        verify=False,
        runner=lambda *_args: (0, "claimed done"),
        token_check=lambda: True,
    )

    assert res.ok is False
    assert res.changed_files == []
    assert "NO repo changes" in res.reason


def test_agent_loop_dispatch_ignores_thomas_conversation_bookkeeping(tmp_path):
    from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_agent_loop

    _init_repo(tmp_path)
    (tmp_path / "anchor.txt").write_text("anchor\n", encoding="utf-8")
    _commit_all(tmp_path)

    def runner(*_args):
        metadata = tmp_path / ".thomas" / "evolve" / "agent" / "conversations" / "conversation.json"
        metadata.parent.mkdir(parents=True)
        metadata.write_text("{}\n", encoding="utf-8")
        return 0, "claimed done"

    res = dispatch_via_agent_loop(
        "inspect without changing the project",
        cwd=tmp_path,
        dry_run=False,
        verify=False,
        runner=runner,
        token_check=lambda: True,
    )

    assert res.ok is False
    assert res.changed_files == []
    assert "NO repo changes" in res.reason


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


def test_compose_headless_prompt_is_honest_about_engine_verify():
    """The prompt no longer falsely claims nothing is ever run: the engine verifies."""
    from thomas.forge.anvil.evolve_claude_bridge import compose_headless_prompt

    p = compose_headless_prompt("do x")
    # The engine still verifies; the prompt must not invent a direct model shell.
    assert "bounded verifier runs after the edit pass" in p
    assert "edit-only builder" not in p
    assert "Direct shell is unavailable" in p
    assert "feeds failures into the next edit pass" in p
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


def test_verifier_checks_web_artifacts_instead_of_claiming_nothing_to_verify(tmp_path):
    from thomas.forge.anvil.evolve_claude_bridge import verify_python_changes

    (tmp_path / "index.html").write_text(
        "<!doctype html><button id='play'>Play</button><script src='game.js'></script>",
        encoding="utf-8",
    )
    (tmp_path / "game.js").write_text(
        "document.querySelector('#play').onclick = (event) => { event.currentTarget.textContent = 'Playing'; };\n",
        encoding="utf-8",
    )
    events: list[dict] = []

    ok, rc, summary = verify_python_changes(tmp_path, ["index.html", "game.js"], events.append)

    assert ok is True and rc == 0
    assert "STATIC_VERIFY_OK: 2 files checked" in summary
    assert "BROWSER_SMOKE_" in summary
    assert any(event.get("fc") == "tool_result" and not event.get("is_error") for event in events)


def test_verifier_rejects_broken_javascript(tmp_path):
    from thomas.forge.anvil.evolve_claude_bridge import verify_python_changes

    (tmp_path / "broken.js").write_text("function broken( {\n", encoding="utf-8")
    events: list[dict] = []

    ok, rc, _summary = verify_python_changes(tmp_path, ["broken.js"], events.append)

    assert ok is False and rc != 0


def test_verifier_smokes_existing_html_when_linked_javascript_changes(tmp_path):
    from thomas.forge.anvil.evolve_claude_bridge import verify_python_changes

    (tmp_path / "index.html").write_text(
        "<!doctype html><main id='status'>Loading</main><script src='game.js'></script>", encoding="utf-8"
    )
    (tmp_path / "game.js").write_text("document.getElementById('status').textContent = 'Game ready';", encoding="utf-8")
    events: list[dict] = []

    ok, rc, summary = verify_python_changes(tmp_path, ["game.js"], events.append)

    assert ok is True and rc == 0
    assert "BROWSER_SMOKE_OK" in summary
    assert any(event.get("fc") == "tool" and "real-browser smoke" in event.get("text", "") for event in events)


def test_browser_smoke_discovers_nested_html_owner_by_resolved_asset_path(tmp_path):
    from thomas.forge.anvil.build_verify import _browser_smoke_files

    app = tmp_path / "apps" / "foo"
    assets = app / "assets"
    assets.mkdir(parents=True)
    (app / "index.html").write_text("<script src='assets/app.js'></script>", encoding="utf-8")
    (assets / "app.js").write_text("window.ready = true;\n", encoding="utf-8")
    decoy = tmp_path / "other"
    decoy.mkdir()
    (decoy / "index.html").write_text("<!-- assets/app.js --><p>app.js is documentation</p>", encoding="utf-8")

    assert _browser_smoke_files(tmp_path, ["apps/foo/assets/app.js"]) == ["apps/foo/index.html"]


def test_browser_smoke_discovers_owner_after_more_than_twenty_four_decoys(tmp_path):
    from thomas.forge.anvil.build_verify import _browser_smoke_files

    for index in range(30):
        folder = tmp_path / f"decoy-{index:02d}"
        folder.mkdir()
        (folder / "index.html").write_text("<p>decoy</p>", encoding="utf-8")
    owner = tmp_path / "zz-owner"
    owner.mkdir()
    (owner / "index.html").write_text("<link rel='stylesheet' href='app.css'>", encoding="utf-8")
    (owner / "app.css").write_text("body { color: gold; }", encoding="utf-8")

    assert _browser_smoke_files(tmp_path, ["zz-owner/app.css"]) == ["zz-owner/index.html"]


def test_verifier_rejects_html_with_obvious_inline_boot_failure(tmp_path):
    """Parseable HTML is not verified when its inline app aborts at boot."""
    from thomas.forge.anvil.evolve_claude_bridge import verify_python_changes

    (tmp_path / "broken.html").write_text(
        "<!doctype html><main>Looks valid</main><script>\nthrow new Error('boot failed');\n</script>",
        encoding="utf-8",
    )
    events: list[dict] = []

    ok, rc, summary = verify_python_changes(tmp_path, ["broken.html"], events.append)

    assert ok is False and rc != 0
    assert "obvious JavaScript boot failure" in summary
    assert any(event.get("fc") == "tool_result" and event.get("is_error") for event in events)


def test_verifier_does_not_misclassify_nested_or_quoted_throw_text(tmp_path):
    """A handler may throw later; only an unconditional top-level boot throw fails."""
    from thomas.forge.anvil.evolve_claude_bridge import verify_python_changes

    (tmp_path / "valid.html").write_text(
        "<!doctype html><script>\n"
        "const copy = \"throw new Error('not code')\";\n"
        "function failOnClick() {\n  throw new Error('later');\n}\n"
        "</script><button>Ready</button>",
        encoding="utf-8",
    )

    events: list[dict] = []
    ok, rc, _summary = verify_python_changes(tmp_path, ["valid.html"], events.append)

    assert ok is True and rc == 0
