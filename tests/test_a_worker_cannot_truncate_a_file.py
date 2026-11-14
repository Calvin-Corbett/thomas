"""A self-fix worker cannot truncate a file, and one attempt keeps its momentum.

You asked: "Are you making sure they're actually doing shit? They're not just
being dumb."

Measured from a live self-fix run (controller Ruling S, 2026-09-24): workers
change files only with whole-file `fs.write_file`. Earlier tool arguments are
compacted out of the model's own context, so a worker that rewrites a large
file from memory truncates it -- the project-folder worker did this twice in
one run, each followed by a long chain of "Recover truncated..." helper runs.
A patch tool (`diff.create`) already existed and was allowed for
self-development, but nothing refused the truncating write, nothing told the
worker to reach for the patch tool instead of `fs.write_file`, and a still-
active Autopilot attempt that ran out of passes was told only its single last
progress line before starting over.

Fix round 1 (opus review of ce9f2f43, task-2f-review.md) found two of the
three requirements did not reach the live path: the Autopilot pass multiplier
was applied before the per-model cap, so a capped model (openai_codex, cap 30)
never saw it (C1); `diff.create` was refused for every thomas/server|tools|
agent|core and scripts/ path inside a self-development green, since it
checked protection against its own sandbox root instead of the real project
(C2, covered in tests/test_a_self_fix_can_patch_a_green.py); and the retry
prompt still carried one progress line, not three (I1). This file's new
tests drive the real worker path -- `run_agent_worker_events`,
`_run_agent_worker`, the self-development write guard, and the assembled
prompt -- rather than only the pure helper functions, per the review's I3
finding.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import thomas.agent.loop_execution as loop_execution
import thomas.server.worker_runtime as worker_runtime
from thomas.agent.loop_tool_exec import _self_development_write_guard_event
from thomas.core.config import load_config
from thomas.server import chat_delegation as cd
from thomas.server import chat_delegation_worker_config as worker_config
from thomas.server.app_helpers import _build_tools
from thomas.server.app_keys import APP_CONFIG
from thomas.server.chat_delegation_live_repo import _with_live_repo_change_requirement
from thomas.server.chat_delegation_worker_config import _replan_prompt
from thomas.tools.filesystem import WriteFileTool

_LIVE_PASS_BUDGET_TEXT = (
    "Pass budget exhausted after 30 passes while work was still active. "
    "The task is incomplete; continue it in the same conversation."
)


def _numbered_lines(count: int) -> str:
    return "\n".join(f"line {i}" for i in range(count)) + "\n"


# ── fs.write_file refuses a write that truncates an existing file ──────────


@pytest.mark.asyncio
async def test_write_file_refuses_a_write_that_truncates_an_existing_file(tmp_path):
    target = tmp_path / "big.py"
    target.write_text(_numbered_lines(100), encoding="utf-8")
    tool = WriteFileTool(tmp_path)

    result = await tool.execute({"path": "big.py", "content": _numbered_lines(30)})

    assert result.ok is False
    assert "diff.create" in result.error
    assert target.read_text(encoding="utf-8") == _numbered_lines(100)


@pytest.mark.asyncio
async def test_write_file_replace_whole_file_true_bypasses_the_guard(tmp_path):
    target = tmp_path / "big.py"
    target.write_text(_numbered_lines(100), encoding="utf-8")
    tool = WriteFileTool(tmp_path)

    result = await tool.execute({"path": "big.py", "content": _numbered_lines(30), "replace_whole_file": True})

    assert result.ok is True
    assert target.read_text(encoding="utf-8") == _numbered_lines(30)


@pytest.mark.asyncio
async def test_write_file_creating_a_new_file_is_unaffected(tmp_path):
    tool = WriteFileTool(tmp_path)

    result = await tool.execute({"path": "new.py", "content": "line 0\n"})

    assert result.ok is True
    assert (tmp_path / "new.py").read_text(encoding="utf-8") == "line 0\n"


# ── M1 (Ruling X): below the size floor, the guard does not apply at all ────


@pytest.mark.asyncio
async def test_write_file_allows_a_small_legit_rewrite_below_the_size_floor(tmp_path):
    target = tmp_path / "three.cfg"
    target.write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    tool = WriteFileTool(tmp_path)

    result = await tool.execute({"path": "three.cfg", "content": "x = 1\n"})  # 3 lines -> 1 line

    assert result.ok is True
    assert target.read_text(encoding="utf-8") == "x = 1\n"


# ── M2 (Ruling X): removal is judged by lines OR characters, whichever is larger ──


@pytest.mark.asyncio
async def test_write_file_refuses_a_minified_file_gutted_by_character_count(tmp_path):
    target = tmp_path / "min.js"
    target.write_text("x" * 50_000, encoding="utf-8")  # one long line, well past the char floor
    tool = WriteFileTool(tmp_path)

    result = await tool.execute({"path": "min.js", "content": _numbered_lines(5)})  # 1 line -> 5 (more lines!)

    assert result.ok is False
    assert "diff.create" in result.error
    assert target.read_text(encoding="utf-8") == "x" * 50_000


# ── N4: the 40% boundary gives the same answer with or without a trailing NL ──


def _equal_width_lines(count: int, *, width: int = 12, trailing: bool = True) -> str:
    body = "\n".join("x" * width for _ in range(count))
    return body + ("\n" if trailing and count else "")


@pytest.mark.asyncio
async def test_exactly_40_percent_is_allowed_with_or_without_a_trailing_newline(tmp_path):
    for name, trailing in (("with_nl.txt", True), ("no_nl.txt", False)):
        target = tmp_path / name
        target.write_text(_equal_width_lines(100, trailing=trailing), encoding="utf-8")
        tool = WriteFileTool(tmp_path)

        result = await tool.execute(
            {"path": name, "content": _equal_width_lines(60, trailing=trailing)}  # 100 -> 60 lines, exactly 40%
        )

        assert result.ok is True, f"{name}: {result.error}"


@pytest.mark.asyncio
async def test_41_percent_is_refused_with_or_without_a_trailing_newline(tmp_path):
    for name, trailing in (("with_nl.txt", True), ("no_nl.txt", False)):
        target = tmp_path / name
        target.write_text(_equal_width_lines(100, trailing=trailing), encoding="utf-8")
        tool = WriteFileTool(tmp_path)

        result = await tool.execute(
            {"path": name, "content": _equal_width_lines(59, trailing=trailing)}  # 100 -> 59 lines, 41%
        )

        assert result.ok is False, f"{name} should have been refused"


@pytest.mark.asyncio
async def test_the_size_floor_and_the_reported_counts_use_the_files_own_text(tmp_path):
    # Fix round 3: N4's newline padding counted a 1,999-character file as 2,000,
    # so the floor guarded it, and the refusal reported the padded counts.
    tool = WriteFileTool(tmp_path)
    (tmp_path / "small.txt").write_text("\n".join(["y" * 199] * 10), encoding="utf-8")  # 1,999 chars, 10 lines
    assert (await tool.execute({"path": "small.txt", "content": "short"})).ok is True

    old = "\n".join(["z" * 124] * 20)  # 2,499 chars, no final newline
    (tmp_path / "big.txt").write_text(old, encoding="utf-8")
    refused = await tool.execute({"path": "big.txt", "content": "z" * 99})
    assert refused.ok is False
    assert f"{len(old)} -> 99 chars" in refused.error, refused.error


# ── the self-development worker is offered diff.create, and told to use it ──


def test_self_development_worker_tool_set_contains_diff_create():
    registry = _build_tools(load_config())

    specs = {spec["function"]["name"] for spec in registry.get_openai_specs()}
    assert "diff.create" in specs


def test_worker_task_prompt_tells_the_model_to_patch_existing_files():
    text = worker_runtime._task_prompt_reminder()

    assert "diff.create" in text
    assert "fs.write_file" in text
    assert "replace_whole_file" in text


# ── C1: the Autopilot pass multiplier reaches the live worker, after the cap ─


class _StubUsage:
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0


class _StubLLMClient:
    """No network: construction only. The loop is stopped (via prepare_execution_setup
    below) before any provider call would happen."""

    def __init__(self, cfg, **kwargs):
        self.config = cfg
        self.session_usage = _StubUsage()

    def reset_runtime_trace(self):
        pass

    def set_budget_scope(self, scope):
        pass

    async def close(self):
        pass

    def __getattr__(self, name):
        return None


class _StopAtSetup(Exception):
    pass


async def _max_iter_reaching_the_loop(
    *, profile: str, autonomy_level: int, job_type: str | None = "self_development"
) -> int:
    """Drive the real run_agent_worker_events -> real resolve_override -> real
    build_agent_loop -> real prepare_execution_setup, and capture the max_iterations
    that setup actually receives (what loop_execution.py's `range(max_iter)` uses) --
    the same probe the reviewer drove for C1."""
    captured: dict[str, object] = {}

    def _recording_setup(self, prompt, **kwargs):
        captured["max_iter"] = kwargs.get("max_iterations")
        raise _StopAtSetup()

    cfg = load_config()
    app = {APP_CONFIG: cfg}
    with (
        patch.object(worker_runtime, "LLMClient", _StubLLMClient),
        patch.object(loop_execution, "prepare_execution_setup", _recording_setup),
    ):
        with tempfile.TemporaryDirectory() as tmp:
            gen = worker_runtime.run_agent_worker_events(
                app,
                prompt="Fix the sign-in card.",
                instructions="probe",
                work_dir=Path(tmp),
                profile=profile,
                role=None,
                effort="diligent",
                autonomy_level=autonomy_level,
                job_type=job_type,
                memory_enabled=False,
                can_spawn=False,
            )
            try:
                async for _event in gen:
                    pass
            except _StopAtSetup:
                pass
    assert "max_iter" in captured, "prepare_execution_setup was never reached"
    return int(captured["max_iter"])


@pytest.mark.asyncio
async def test_autopilot_self_development_triples_the_capped_model_budget():
    """Ruling W: the multiplier applies AFTER the per-model cap. openai_codex's
    default override caps at 30 passes; on Autopilot (L5) self-development, the
    worker must actually receive 3 * 30 = 90, not 30 (C1: the cap used to win
    every time because the multiplier was applied to compute_max_passes's own
    result, before the cap)."""
    max_iter = await _max_iter_reaching_the_loop(profile="openai_codex", autonomy_level=5)

    assert max_iter == 90


@pytest.mark.asyncio
async def test_autopilot_multiplier_does_not_apply_below_autonomy_5():
    max_iter = await _max_iter_reaching_the_loop(profile="openai_codex", autonomy_level=4)

    assert max_iter == 30


@pytest.mark.asyncio
async def test_autopilot_multiplier_does_not_apply_outside_self_development():
    """I3 gap: L5 alone is not enough -- the multiplier is gated on BOTH
    autonomy 5 and job_type == self_development."""
    max_iter = await _max_iter_reaching_the_loop(profile="openai_codex", autonomy_level=5, job_type=None)

    assert max_iter == 30


# ── I1: the retry prompt carries the last THREE progress lines, on the real path ──


class _RecordingEmitter:
    def __init__(self) -> None:
        self.progress_lines: list[str] = []

    async def progress(self, record, *, specialist_id, bot, text) -> None:
        self.progress_lines.append(text)

    async def completed(self, record, *, specialist_id, bot, text="") -> None:
        pass

    async def failed(self, record, *, specialist_id, bot, text) -> None:
        pass


def _runtime_event() -> dict:
    return {
        "type": "model_runtime",
        "runtime": {
            "requested": {"profile": "test", "provider": "fixture", "model": "test-model"},
            "active": {"profile": "test", "provider": "fixture", "model": "test-model"},
            "attempts": [{"profile": "test", "provider": "fixture", "model": "test-model", "status": "success"}],
        },
    }


_ATTEMPT_1_EVENTS = [
    {"type": "tool_start", "name": "fs.read_file"},
    {"type": "tool_output", "name": "fs.read_file", "ok": True, "result_text": "a"},
    {"type": "tool_start", "name": "code.search"},
    {"type": "tool_output", "name": "code.search", "ok": True, "result_text": "b"},
    {"type": "tool_start", "name": "fs.write_file"},
    {"type": "tool_output", "name": "fs.write_file", "ok": True, "result_text": "c"},
    {"type": "tool_start", "name": "shell.exec"},
    {"type": "tool_output", "name": "shell.exec", "ok": True, "result_text": "d"},
    {"type": "error", "error": _LIVE_PASS_BUDGET_TEXT, "retryable": True},
]
_ATTEMPT_2_EVENTS = [{"type": "text", "text": "done"}, {"type": "done"}]


@pytest.mark.asyncio
async def test_replan_prompt_carries_three_progress_lines_through_the_real_runner(tmp_path):
    """Drives the real chat_delegation._run_agent_worker with a scripted worker
    stream: attempt 1 finishes four tools then hits the real pass-budget error;
    attempt 2's prompt is inspected for the progress block _replan_prompt built.
    Only the worker stream, the task store, and the workspace snapshot are
    stubbed -- no model, no subprocess, no git (I1's real-path requirement)."""
    calls: list[dict] = []

    async def _scripted_worker(app, **kwargs):
        calls.append(kwargs)
        yield _runtime_event()
        for event in _ATTEMPT_1_EVENTS if len(calls) == 1 else _ATTEMPT_2_EVENTS:
            yield event

    emitter = _RecordingEmitter()
    root = tmp_path
    (root / "ws").mkdir()
    with (
        patch.object(cd, "run_agent_worker_events", new=_scripted_worker),
        patch.object(cd.task_bot_runtime, "update_execution", lambda *a, **k: None),
        patch.object(cd.task_bot_runtime, "get_execution", lambda *a, **k: {"execution_id": "e", "summary": "s"}),
        patch.object(cd.task_bot_runtime, "complete_execution", lambda *a, **k: None),
        patch.object(cd.task_bot_runtime, "fail_execution", lambda *a, **k: None),
        patch.object(cd, "_snapshot_workspace_files", lambda *a, **k: []),
        patch.object(cd, "_normalize_record", lambda payload: dict(payload or {})),
    ):
        await cd._run_agent_worker(
            None,
            execution_id="e",
            prompt="Fix the sign-in card.",
            specialist_id="coding",
            bot=SimpleNamespace(name="Byte", id="byte"),
            emitter=emitter,
            instructions="inst",
            repo_root=root,
            work_dir=root / "ws",
            profile="test",
            model_id="test-model",
            autonomy_level=5,
        )

    assert len(calls) == 2, "the pass-budget stop must trigger a second attempt"
    retry_prompt = str(calls[1]["prompt"])
    start = retry_prompt.find("Progress so far")
    assert start >= 0, "the retry prompt carries no progress block at all"
    end = retry_prompt.find("You ran out of passes")
    block = retry_prompt[start:end] if end >= 0 else retry_prompt[start:]
    bullet_lines = [ln for ln in block.splitlines() if ln.startswith("- ")]
    assert len(bullet_lines) == 3, f"expected 3 progress lines, got {bullet_lines}"
    # The three most RECENT lines from attempt 1 -- the write and the shell step,
    # not the very first tool it happened to try.
    assert any("Saved the file" in ln for ln in bullet_lines)
    assert any("command" in ln.lower() for ln in bullet_lines)


@pytest.mark.asyncio
async def test_each_retry_looks_its_green_up_once_through_the_real_runner(real_green, tmp_path, monkeypatch):
    """Fix round 3: building one retry's prompt ran the green's git diff three
    times (the replan's wording, its file list, then the completion requirement)."""
    from thomas.server import green_checkout

    real_changed_paths, looked = green_checkout.changed_paths, []
    monkeypatch.setattr(green_checkout, "changed_paths", lambda green: looked.append(1) or real_changed_paths(green))
    before_each_attempt: list[int] = []

    async def _scripted_worker(app, **kwargs):
        before_each_attempt.append(len(looked))
        yield _runtime_event()
        yield {"type": "error", "error": _LIVE_PASS_BUDGET_TEXT, "retryable": True}

    with (
        patch.object(cd, "run_agent_worker_events", new=_scripted_worker),
        patch.object(cd.task_bot_runtime, "update_execution", lambda *a, **k: None),
        patch.object(cd.task_bot_runtime, "get_execution", lambda *a, **k: {"execution_id": "e", "summary": "s"}),
        patch.object(cd.task_bot_runtime, "fail_execution", lambda *a, **k: None),
        patch.object(cd, "_normalize_record", lambda payload: dict(payload or {})),
    ):
        await cd._run_agent_worker(
            None,
            execution_id="e",
            prompt="Fix the sign-in card.",
            specialist_id="coding",
            bot=SimpleNamespace(name="Byte", id="byte"),
            emitter=_RecordingEmitter(),
            instructions="inst",
            repo_root=tmp_path,
            work_dir=real_green,
            requires_live_repo_change=True,
            profile="test",
            model_id="test-model",
            autonomy_level=4,  # three attempts
        )

    assert len(before_each_attempt) == 3
    assert [b - a for a, b in zip(before_each_attempt, before_each_attempt[1:])] == [1, 1], before_each_attempt


def test_replan_prompt_carries_changed_files_and_the_last_three_progress_lines(monkeypatch):
    monkeypatch.setattr(worker_config, "_changed_in_green", lambda root: ["a.py", "b.py"])
    lines = [
        "Read thomas/tools/filesystem.py",
        "Wrote thomas/tools/filesystem.py",
        "Ran the new test",
    ]

    prompt = _replan_prompt("Fix the sign-in card.", _LIVE_PASS_BUDGET_TEXT, 2, 12, lines, Path("green/work/x"))

    assert "a.py, b.py" in prompt
    for line in lines:
        assert f"- {line}" in prompt


def test_replan_prompt_keeps_only_the_last_three_progress_lines(monkeypatch):
    monkeypatch.setattr(worker_config, "_changed_in_green", lambda root: [])
    lines = ["first step", "second step", "third step", "fourth step"]

    prompt = _replan_prompt("Fix the sign-in card.", _LIVE_PASS_BUDGET_TEXT, 2, 12, lines, Path("green/work/x"))

    assert "first step" not in prompt
    for line in ("second step", "third step", "fourth step"):
        assert line in prompt


# ── N3: "live repo" wording only reaches a worker whose workspace really is one ──
# A real green (git clone and all) and a plain folder; nothing stubs the green check.

_LIVE_REPO_PHRASES = ("LIVE REPO COMPLETION REQUIREMENT", "live-repo edit", "counted live-repo", "no live repo files")


@pytest.fixture
def real_green(tmp_path, monkeypatch):
    from tests.green_support import make_blue
    from thomas.server import green_checkout

    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(tmp_path / "green-root"))
    return green_checkout.create_green(make_blue(tmp_path), "exec-n3").work


def _runner_failure(work: Path, tools: list[str], failed: list[str]) -> str:
    """The runner's own words for a self-fix attempt that changed nothing in *work*."""
    from thomas.server.chat_delegation_live_repo import _live_repo_workspace_mtimes
    from thomas.server.chat_delegation_runner import _finalize_live_repo_completion, _WorkerRetry

    baseline = _live_repo_workspace_mtimes(work)
    finish = _finalize_live_repo_completion(
        None, "e", work, "Fix it.", baseline, [], tools, tools, failed, SimpleNamespace(name="Byte"), "coding"
    )
    with pytest.raises(_WorkerRetry) as retry:
        asyncio.run(finish)
    return str(retry.value)


@pytest.mark.parametrize(
    ("tools", "failed", "phrases"),
    [
        ([], [], ("live-repo edit",)),  # no write tool was used
        (["fs.write_file"], [], ("counted live-repo",)),  # the write changed no counted file
        (["fs.write_file"], ["shell.exec"], ()),  # transient failed tools
    ],
)
def test_a_green_worker_is_never_told_it_is_changing_the_live_repo(real_green, tmp_path, tools, failed, phrases):
    plain = tmp_path / "plain-workspace"
    plain.mkdir()
    for work, in_green in ((real_green, True), (plain, False)):
        error = _runner_failure(work, tools, failed)
        assert "no live repo files" in error  # the runner's own text, either way
        texts = (
            _replan_prompt("Fix the sign-in card.", error, 2, 12, "x", work),
            _with_live_repo_change_requirement("", work),
        )
        said = [phrase for phrase in _LIVE_REPO_PHRASES if any(phrase in text for text in texts)]
        if in_green:
            assert said == [], (said, texts)
            assert all("SELF-FIX COMPLETION REQUIREMENT: this self-fix run" in text for text in texts)
        else:
            assert said == ["LIVE REPO COMPLETION REQUIREMENT", *phrases, "no live repo files"], said


def test_a_green_worker_whose_proof_was_not_saved_is_not_told_live_repo(real_green, tmp_path):
    error = "live-repo proof persistence failed"  # the runner's text, pinned by test_chat_parity_completion_guards
    in_green = _replan_prompt("Fix the sign-in card.", error, 2, 12, "x", real_green)
    assert "live-repo" not in in_green and "this self-fix run's proof could not be saved" in in_green
    assert error in _replan_prompt("Fix the sign-in card.", error, 2, 12, "x", tmp_path)


# ── I2: every instruction the worker gets says the same thing ───────────────


def _fake_self_development_loop(*, limit: int = 6) -> SimpleNamespace:
    return SimpleNamespace(
        _current_job_type="self_development",
        _self_development_write_guard={"inspection_count": 0, "write_seen": False, "limit": limit},
    )


@pytest.mark.asyncio
async def test_git_show_of_committed_content_is_exempt_from_the_inspection_limit():
    """Task 2d item-12(a), folded into fix round 1's I2: a `git show <rev>:<path>`
    read through the shell counts as a file read, like fs.read_file, and never
    trips the guard -- ten calls, none refused."""
    loop = _fake_self_development_loop()

    for i in range(10):
        event = _self_development_write_guard_event(
            loop,
            name="shell.exec",
            args={"command": "git show HEAD:thomas/tools/filesystem.py"},
            tc_id=f"t{i}",
            iteration=i,
        )
        assert event is None, f"git show read #{i} was refused"
    assert loop._self_development_write_guard["inspection_count"] == 0


@pytest.mark.asyncio
async def test_search_and_listing_loops_stay_limited_and_the_refusal_says_self_fix_run():
    """Search/listing calls still count and still trip the guard once the limit
    is exceeded -- the git-show exemption above must not loosen this. The
    refusal names diff.create and never says "live repo" (item-12(b)): this
    guard only ever fires for a self-development run, which only ever runs in
    a green, never the live repo itself."""
    loop = _fake_self_development_loop(limit=7)

    events = [
        _self_development_write_guard_event(loop, name="fs.search", args={}, tc_id=f"s{i}", iteration=i)
        for i in range(8)
    ]

    assert events[:7] == [None] * 7, "the first 7 search calls must not be refused"
    refusal = events[7]
    assert refusal is not None, "the 8th search call, past the limit, must be refused"
    text = refusal.data["result_text"]
    assert "diff.create" in text
    assert "live repo" not in text
    assert "self-fix run" in text


@pytest.mark.asyncio
async def test_a_real_file_read_still_bypasses_the_guard_unconditionally():
    loop = _fake_self_development_loop(limit=1)

    for i in range(5):
        event = _self_development_write_guard_event(loop, name="fs.read_file", args={}, tc_id=f"r{i}", iteration=i)
        assert event is None


@pytest.mark.asyncio
async def test_a_shell_command_that_is_not_a_committed_read_still_counts():
    """The git-show exemption is narrow: a shell command that merely LOOKS like
    it might touch git, but isn't a bare `git show <rev>:<path>` / `git cat-file
    -p`, is not exempt -- it is still an inspection call, and a chained command
    can never smuggle a write past the exemption."""
    loop = _fake_self_development_loop(limit=1)

    first = _self_development_write_guard_event(
        loop, name="shell.exec", args={"command": "git status"}, tc_id="g1", iteration=1
    )
    second = _self_development_write_guard_event(
        loop,
        name="shell.exec",
        args={"command": "git show HEAD:thomas/tools/filesystem.py && rm -rf ."},
        tc_id="g2",
        iteration=2,
    )

    assert first is None  # within the limit of 1
    assert second is not None  # over the limit, AND not a bare committed-read command


@pytest.mark.asyncio
async def test_git_show_exemption_edges_all_count_as_inspection():
    """Ruling AA (N1): round 1's regex also exempted an unlimited directory
    listing and two forms that write a file. None of these seven commands is
    a one-file committed-blob read, so all seven must count -- the 7th call
    refuses at limit 6."""
    commands = [
        "git show HEAD:thomas/server",  # directory listing, no dotted filename
        "git cat-file -p HEAD^{tree}",  # tree listing
        "git show HEAD:a.py>x",  # no spaces, still one shell token -- writes
        "git show HEAD:a.py > x",  # writes
        "git show --output=x HEAD:a.py",  # writes, no shell metacharacter needed
        "git show HEAD:a.py | grep y",  # piped
        "git show HEAD:a.py; rm z",  # chained
    ]
    loop = _fake_self_development_loop(limit=6)

    events = [
        _self_development_write_guard_event(loop, name="shell.exec", args={"command": cmd}, tc_id=f"e{i}", iteration=i)
        for i, cmd in enumerate(commands)
    ]

    assert events[:6] == [None] * 6, "the first 6 must not be refused"
    assert events[6] is not None, "the 7th, past the limit, must be refused"


def test_worker_task_prompt_tells_the_model_to_patch_existing_files_not_live_repo_wording():
    """M3/I2 sanity: the reminder never claims a write happens in "the live
    repo" -- self-development always runs in a green."""
    text = worker_runtime._task_prompt_reminder()

    assert "live repo" not in text


def _forbidden_fs_write_file_only(text: str) -> bool:
    return (
        "use `fs.write_file` for every file" in text
        or "you MUST use the `fs.write_file` tool" in text
        or ("with fs.write_file" in text and "diff.create" not in text)
    )


async def _capture_worker_kwargs(workspace: str, fake_repo_root: Path, green: Path) -> dict:
    """Drives the real thomas.server.chat_delegation._start_agent_worker_delegation
    up to the point it hands worker_kwargs to the supervisor, for the given
    `workspace` ("project" self-development, or "isolated")."""
    import thomas.server.chat_delegation_build_session as build_session
    from thomas.core.file_access import PROJECT

    captured: dict = {}

    class _Emitter:
        async def started(self, *a, **k):
            pass

        async def failed(self, record, *, specialist_id, bot, text):
            captured["failed"] = text

        async def progress(self, *a, **k):
            pass

    async def _capture_supervised(runner, app, **kwargs):
        captured["worker_kwargs"] = kwargs["worker_kwargs"]

    async def _prep(**kwargs):
        return SimpleNamespace(work_dir=green, refusal=None)

    with (
        patch.object(cd.task_bot_runtime, "create_execution", lambda **k: {"execution_id": "exec-probe"}),
        patch.object(cd.task_bot_runtime, "update_execution", lambda *a, **k: None),
        patch.object(cd.task_bot_runtime, "get_execution", lambda *a, **k: {"execution_id": "exec-probe"}),
        patch.object(cd.task_bot_runtime, "fail_execution", lambda *a, **k: None),
        patch.object(cd.task_bot_runtime.task_checklist_runtime, "attach_contract", lambda *a, **k: ""),
        patch.object(build_session, "prepare_workspace_async", _prep),
        patch.object(cd, "_run_agent_worker_supervised", _capture_supervised),
    ):
        await cd._start_agent_worker_delegation(
            None,
            session_id="s",
            prompt="Fix the sign-in card in thomas/server/web/js/chat_boot.js.",
            specialist_id="coding",
            bot=SimpleNamespace(name="Byte", id="byte"),
            emitter=_Emitter(),
            repo_root=fake_repo_root,
            autonomy_level=5,
            file_access=PROJECT,
            workspace=workspace,
        )
        await asyncio.sleep(0.05)  # the delegation hands off to a background task; let it run

    kw = captured.get("worker_kwargs")
    assert kw is not None, f"no worker_kwargs captured for workspace={workspace!r}: {captured}"
    return kw


@pytest.mark.asyncio
async def test_no_instruction_the_worker_gets_tells_it_to_edit_an_existing_file_with_fs_write_file_only():
    """Assembles the same texts the model actually receives for a
    self-development ("project") workspace: the system prompt (instructions),
    the first user turn (the task-prompt reminder + the live-repo
    requirement), and two retry variants. None of them may tell the model
    that `fs.write_file` is how to change an EXISTING file -- `diff.create`
    is the patch tool now (I2)."""
    with tempfile.TemporaryDirectory() as tmp:
        # An isolated repo_root, never the live checkout: a test that points a
        # worker at Path.cwd()/"." lands its first progress write in the real
        # runtime/coordination/task_bots/, which a later, unrelated test then
        # reads back (tests/test_a_worker_test_does_not_leave_a_live_task_in_the_repo.py).
        fake_repo_root = Path(tmp) / "fake_repo"
        fake_repo_root.mkdir()
        green = Path(tmp) / "green" / "work" / "exec-probe"
        green.mkdir(parents=True)

        kw = await _capture_worker_kwargs("project", fake_repo_root, green)

    system_prompt = kw["instructions"]
    first_turn = f"{worker_runtime._task_prompt_reminder()}\n\n{_with_live_repo_change_requirement(kw['prompt'])}"
    retry_no_write_tool = _replan_prompt(
        kw["prompt"], "self-development task changed no live repo files; no write tool was used", 2, 12, "x", green
    )
    retry_no_change = _replan_prompt(
        kw["prompt"],
        "self-development task changed no live repo files; write tools used did not change counted files: "
        "fs.write_file",
        2,
        12,
        "x",
        green,
    )

    for label, text in (
        ("system prompt", system_prompt),
        ("first user turn", first_turn),
        ("no-write-tool retry", retry_no_write_tool),
        ("no-change retry", retry_no_change),
    ):
        assert not _forbidden_fs_write_file_only(text), (
            f"{label} still tells the model to edit existing files with fs.write_file only:\n{text}"
        )


@pytest.mark.asyncio
async def test_the_isolated_workers_system_prompt_also_agrees():
    """I2 gap (round 2): the self-development probe never built the ISOLATED
    (non-self-development) worker's system prompt, so chat_delegation.py:683's
    stale "you MUST use the `fs.write_file` tool" instruction was missed."""
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo_root = Path(tmp) / "fake_repo"
        fake_repo_root.mkdir()
        green = Path(tmp) / "green" / "work" / "exec-probe"
        green.mkdir(parents=True)

        kw = await _capture_worker_kwargs("isolated", fake_repo_root, green)

    system_prompt = kw["instructions"]
    assert not _forbidden_fs_write_file_only(system_prompt), (
        f"the isolated worker's system prompt still tells the model to edit existing files with "
        f"fs.write_file only:\n{system_prompt}"
    )
    assert "diff.create" in system_prompt
