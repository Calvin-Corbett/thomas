"""A pass that reaches its wall clock ends the pass, not the run (2026-09-05).

A Build pass has a wall clock by economy (600 s cheap, 1800 s balanced, 3600 s
max). Reaching it used to be an agent error: exit 1, "Agent run exceeded the
1800-second execution limit", the run filed failed, and the files the pass had
written sat there unverified. The Mario Kart generation-4 pass ran past twenty
minutes fixing real bugs one after another. You said: "make sure he can do any
task until its done not based on passes." The clock bounds a pass; the run's
end is the contract.

So: the clock returns a distinct code; when files changed, the engine verifies
them and continues; a continue pass that reaches the clock again is treated
the same way; and a pass that ended at the clock without settling its contract
counts as not finished until a later pass settles it. Nothing changed and the
clock ran out is still a failure, as before.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from thomas.forge.anvil import dispatch_agent_loop as dal
from thomas.forge.anvil.build_verify import PASS_WALL_CLOCK_RC
from thomas.forge.anvil.forge_event_stream import FORGE_EVENT_KEY


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    (root / "game.js").write_text("const tracks = 1;\n", encoding="utf-8")
    for args in (["init", "--initial-branch=main"], ["add", "-A"]):
        subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=T", "-c", "user.email=t@x", "commit", "-m", "base"],
        capture_output=True,
        check=False,
    )
    return root


def test_the_clock_returns_a_distinct_code_and_says_so() -> None:
    events: list[dict] = []
    translator = dal._AgentLoopForgeTranslator(events.append)

    class SlowAgent:
        async def run(self, prompt, **kwargs):
            await asyncio.sleep(5)
            yield None  # pragma: no cover - never reached

    asyncio.run(
        dal._translate_agent_stream(SlowAgent(), "build", timeout=0.05, tools_policy="auto", translator=translator)
    )
    assert translator.rc == PASS_WALL_CLOCK_RC
    metas = [e["text"] for e in events if e.get(FORGE_EVENT_KEY) == "meta"]
    assert any("wall clock" in m for m in metas), events
    assert not any(e.get(FORGE_EVENT_KEY) == "error" for e in events), events


def test_files_changed_at_the_clock_are_verified_and_the_run_continues(repo: Path) -> None:
    calls: list[str] = []

    def runner(prompt, cwd, timeout, emit):
        calls.append(prompt)
        if len(calls) == 1:
            (Path(cwd) / "game.js").write_text("const tracks = 4;\n", encoding="utf-8")
            return PASS_WALL_CLOCK_RC, ""
        return 0, "finished"

    result = dal.dispatch_via_agent_loop(
        "build the game",
        cwd=repo,
        dry_run=False,
        runner=runner,
        verify=True,
        verifier=lambda cwd, changed, emit: (True, 0, "ok"),
        max_fix_iters=3,
        token_check=lambda: True,
    )
    assert result.ok, result.reason
    assert len(calls) == 2, calls  # the clock ended pass 1; pass 2 continued and settled
    assert "CONTINUE pass" in calls[1] and "wall clock" in calls[1], calls[1]


def test_nothing_changed_at_the_clock_is_still_a_failure(repo: Path) -> None:
    calls: list[str] = []

    def runner(prompt, cwd, timeout, emit):
        calls.append(prompt)
        return PASS_WALL_CLOCK_RC, ""

    result = dal.dispatch_via_agent_loop(
        "build the game",
        cwd=repo,
        dry_run=False,
        runner=runner,
        verify=True,
        verifier=lambda cwd, changed, emit: (True, 0, "ok"),
        max_fix_iters=3,
        token_check=lambda: True,
    )
    assert not result.ok
    assert len(calls) == 1
    assert "wall clock" in result.reason or str(PASS_WALL_CLOCK_RC) in result.reason, result.reason


def test_a_run_that_keeps_hitting_the_clock_ends_unfinished_not_completed(repo: Path) -> None:
    calls: list[str] = []
    events: list[dict] = []

    def runner(prompt, cwd, timeout, emit):
        calls.append(prompt)
        (Path(cwd) / "game.js").write_text(f"const tracks = {len(calls) + 1};\n", encoding="utf-8")
        return PASS_WALL_CLOCK_RC, ""

    result = dal.dispatch_via_agent_loop(
        "build the game",
        cwd=repo,
        dry_run=False,
        runner=runner,
        verify=True,
        verifier=lambda cwd, changed, emit: (True, 0, "ok"),
        max_fix_iters=2,
        token_check=lambda: True,
        emit=events.append,
    )
    assert not result.ok
    assert len(calls) == 3  # the first pass plus the two-pass budget
    errors = [e["text"] for e in events if e.get(FORGE_EVENT_KEY) == "error"]
    assert errors and errors[-1].startswith("unfinished"), errors


# The Minecraft proof run (2026-09-06): the pass spent its whole clock playing
# eight feature sessions, changed no file because nothing needed changing, and
# was filed "the pass reached its wall clock with no file changed" -- a failure.
# For a pass that only proves, the work is the playtests: tool activity at the
# clock is a pass boundary too; only a pass that did nothing at all is a failure.


def test_a_pass_that_only_played_at_the_clock_continues(repo: Path) -> None:
    calls: list[str] = []

    def runner(prompt, cwd, timeout, emit):
        calls.append(prompt)
        if len(calls) == 1:
            emit({FORGE_EVENT_KEY: "tool", "name": "web.playtest", "text": "web.playtest index.html", "access": "read"})
            emit({FORGE_EVENT_KEY: "tool_result", "text": "1. click PLAY -> ok", "is_error": False})
            return PASS_WALL_CLOCK_RC, ""
        emit({FORGE_EVENT_KEY: "final", "text": "Every feature was played and held up; here is what each screen showed."})
        return 0, "finished"

    result = dal.dispatch_via_agent_loop(
        "play each feature and show me",
        cwd=repo,
        dry_run=False,
        runner=runner,
        verify=True,
        verifier=lambda cwd, changed, emit: (True, 0, "ok"),
        max_fix_iters=3,
        token_check=lambda: True,
    )
    assert result.ok, result.reason
    assert len(calls) == 2, calls
    assert "CONTINUE pass" in calls[1] and "wall clock" in calls[1], calls[1]


# Pass 2 of the resumed proof run replayed the biomes, the inventory and the
# crafting that pass 1 had already proven, and hit the clock again before the
# tour was done. "Continue where you left off" is empty advice when nothing
# says what is already on record; the continue prompt names the saved sessions.


def test_the_continue_prompt_after_a_clock_names_the_saved_sessions(repo: Path) -> None:
    session = repo / ".thomas" / "playtest" / "20260906T040000"
    session.mkdir(parents=True)
    (session / "report.txt").write_text(
        'web.playtest index.html (viewport 1280x720)\n1. click "PLAY" -> ok\n2. eval -> {"biomes": 8}\nerrors: none',
        encoding="utf-8",
    )
    calls: list[str] = []

    def runner(prompt, cwd, timeout, emit):
        calls.append(prompt)
        if len(calls) == 1:
            emit({FORGE_EVENT_KEY: "tool", "name": "web.playtest", "text": "web.playtest index.html", "access": "read"})
            return PASS_WALL_CLOCK_RC, ""
        emit({FORGE_EVENT_KEY: "final", "text": "Every feature was played and held up; here is what each screen showed."})
        return 0, "finished"

    result = dal.dispatch_via_agent_loop(
        "play each feature and show me",
        cwd=repo,
        dry_run=False,
        runner=runner,
        verify=True,
        verifier=lambda cwd, changed, emit: (True, 0, "ok"),
        max_fix_iters=3,
        token_check=lambda: True,
    )
    assert result.ok, result.reason
    assert len(calls) == 2, calls
    assert '{"biomes": 8}' in calls[1] and "already on record" in calls[1], calls[1]
