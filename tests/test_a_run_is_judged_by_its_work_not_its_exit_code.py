"""A run that did the work is not filed as a failure by its exit code.

The Claude CLI exits 1 even when the files landed and work -- observed live by
the owner, and the reason "successful runs are recorded as failures" was the
top defect on his list. ``_drain_and_record`` used to require ``rc == 0``
before it would believe ANY evidence: git said two files changed, the
transcript carried the CLI's own ``final`` result frame, and the run was still
written into the conversation as ``failed / exited 1``.

The evidence hierarchy these tests pin, in the order the recorder now applies
it:

- Files changed  -> ``completed``, whatever the exit code says. The nonzero
  code is still visible in the reason, so nothing is hidden -- it just stops
  outvoting the work.
- No changes, but the transcript carries a ``final`` frame -- the frame the
  stream translator emits ONLY for a non-error CLI ``result`` message -- and
  no mutating tool ran -> ``conversation``. The protocol said the answer
  arrived; the exit code is the part that lied.
- No changes and only streamed ``say`` text (a run that died mid-thought)
  with a nonzero exit -> still ``failed``. Partial narration is not an answer,
  and this control is what keeps the fix from over-forgiving crashes.
- The person stopped or steered the run -> ``stopped``, in those words, not
  ``failed / exited 1``. An interruption someone asked for is not an error.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from aiohttp import web

from tests.test_evolve_agent_routes import _new_repo
from thomas.forge.anvil import forge_code_git, forge_code_store
from thomas.server.routes import evolve_agent_runtime


class _EmptyStdout:
    async def readline(self) -> bytes:
        return b""


class _ExitedProcess:
    stdout = _EmptyStdout()

    def __init__(self, returncode: int) -> None:
        self.returncode = returncode

    async def wait(self) -> int:
        return self.returncode


def _record(repo: Path, conversation_id: str, transcript: Path, proc: Any, snap: dict[str, str]) -> dict[str, Any]:
    return asyncio.run(
        evolve_agent_runtime._drain_and_record(
            proc,
            transcript,
            repo,
            conversation_id,
            "test-model",
            snap,
            web.Application(),
            run_id="run-exit-code-truth",
        )
    )


def test_files_landed_but_the_cli_exited_1_records_completed(tmp_path: Path, monkeypatch: Any) -> None:
    repo = _new_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    transcript = repo / "transcript.txt"
    transcript.write_text('{"fc":"say","text":"building the page"}\n', encoding="utf-8")
    monkeypatch.setattr(forge_code_git, "project_delta_since", lambda *_args: ["index.html", "app.js"])

    result = _record(repo, conversation["id"], transcript, _ExitedProcess(1), {})

    assert result["ok"] is True
    assert result["noop"] is False
    assert result["outcome"] == "completed"
    saved = forge_code_store.load_conversation(repo, conversation["id"])
    reason = saved["turns"][-1]["reason"]
    assert "2 file(s) changed" in reason
    # The exit code is still on the record -- visible, just no longer a verdict.
    assert "1" in reason.replace("2 file(s)", "")


def test_a_confirmed_final_answer_outvotes_a_lying_exit_code(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    transcript = repo / "transcript.txt"
    transcript.write_text(
        '{"fc":"final","text":"Your project reads sales.csv and renders three charts."}\n',
        encoding="utf-8",
    )
    snap = forge_code_git.snapshot(repo)

    result = _record(repo, conversation["id"], transcript, _ExitedProcess(1), snap)

    assert result["ok"] is True
    assert result["outcome"] == "conversation"


def test_a_crashed_run_with_only_streamed_say_text_is_still_failed(tmp_path: Path) -> None:
    # The control: partial narration plus a nonzero exit stays a failure, so the
    # fix cannot be rewritten into "any output counts as success".
    repo = _new_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    transcript = repo / "transcript.txt"
    transcript.write_text('{"fc":"say","text":"I will start by"}\n', encoding="utf-8")
    snap = forge_code_git.snapshot(repo)

    result = _record(repo, conversation["id"], transcript, _ExitedProcess(1), snap)

    assert result["ok"] is False
    assert result["outcome"] == "failed"


def test_a_stopped_run_is_recorded_as_stopped_not_failed(tmp_path: Path, monkeypatch: Any) -> None:
    repo = _new_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    transcript = repo / "transcript.txt"
    transcript.write_text('{"fc":"say","text":"halfway through"}\n', encoding="utf-8")
    monkeypatch.setattr(forge_code_git, "project_delta_since", lambda *_args: ["index.html"])
    proc = _ExitedProcess(1)
    proc.thomas_stop_requested = "stop"

    result = _record(repo, conversation["id"], transcript, proc, {})

    assert result["ok"] is False
    assert result["outcome"] == "stopped"
    saved = forge_code_store.load_conversation(repo, conversation["id"])
    turn = saved["turns"][-1]
    reason = turn["reason"]
    assert "stopped" in reason.lower()
    assert "exited" not in reason.lower()
    # The interrupted work is still named, so Keep/Revert has a subject.
    assert "1 file(s)" in reason
    # The outcome word is PERSISTED, so a reloaded transcript can render the
    # stop as a stop instead of re-deriving "failed" from ok=False.
    assert turn["outcome"] == "stopped"


def test_a_steered_run_is_recorded_as_steering_not_failed(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    transcript = repo / "transcript.txt"
    transcript.write_text('{"fc":"say","text":"halfway through"}\n', encoding="utf-8")
    snap = forge_code_git.snapshot(repo)
    proc = _ExitedProcess(1)
    proc.thomas_stop_requested = "steer"

    result = _record(repo, conversation["id"], transcript, proc, snap)

    assert result["ok"] is False
    assert result["outcome"] == "stopped"
    saved = forge_code_store.load_conversation(repo, conversation["id"])
    assert "steering" in saved["turns"][-1]["reason"].lower()


def test_a_crash_after_partial_files_is_failed_not_completed(tmp_path: Path, monkeypatch: Any) -> None:
    # The tarot-game shape (2026-08-10): a one-pass build wrote a design doc,
    # then its next model call crashed on a dead LLM route. "Files changed"
    # filed it as COMPLETED, so a crash was presented as a finished
    # deliverable. The engine's own terminal error event must outrank the
    # changed-file count.
    repo = _new_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    transcript = repo / "transcript.txt"
    transcript.write_text(
        '{"fc":"tool_result","name":"fs.write_file","text":"wrote DESIGN.md","is_error":false}\n'
        '{"fc":"error","text":"Lost the connection to openai_codex mid-run"}\n'
        '{"fc":"error","text":"agent loop exited 1","is_error":true}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(forge_code_git, "project_delta_since", lambda *_args: ["DESIGN.md"])

    result = _record(repo, conversation["id"], transcript, _ExitedProcess(1), {})

    assert result["ok"] is False
    assert result["outcome"] == "failed"
    reason = forge_code_store.load_conversation(repo, conversation["id"])["turns"][-1]["reason"]
    assert "crashed" in reason.lower()
    # The partial work is still named so Keep/Revert has a subject, and the
    # root cause (not the generic loop-exit) is surfaced.
    assert "1 file(s)" in reason
    assert "connection" in reason.lower()


def test_a_clean_cli_success_at_exit_1_is_not_misread_as_a_crash(tmp_path: Path, monkeypatch: Any) -> None:
    # The guard against over-correction: the Claude CLI exits 1 on runs whose
    # files landed and work, and its terminal event is is_error:false. That
    # must still record COMPLETED -- the crash detector keys on the engine's
    # OWN error verdict, not the exit code.
    repo = _new_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    transcript = repo / "transcript.txt"
    transcript.write_text(
        '{"fc":"error","text":"a transient tool retry"}\n'
        '{"fc":"tool_result","name":"fs.write_file","text":"wrote index.html","is_error":false}\n'
        '{"fc":"meta","text":"dispatched via claude CLI (1 file(s) changed; engine checks passed)","is_error":false}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(forge_code_git, "project_delta_since", lambda *_args: ["index.html"])

    result = _record(repo, conversation["id"], transcript, _ExitedProcess(1), {})

    assert result["ok"] is True
    assert result["outcome"] == "completed"
