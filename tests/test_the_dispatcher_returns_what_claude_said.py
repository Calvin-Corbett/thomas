"""A dispatch reports what Claude said, not only that it said something.

On 2026-09-03 a benchmark run recorded two tasks as ``ok chars=0`` while 368
lines of real work sat in the worktree. Nothing had gone wrong in the run: the
dispatcher read the reply off the stream, set ``saw_reply`` from it, and dropped
the text. :class:`CliDispatchResult` had no field to carry an answer, so every
caller that wanted one got an empty string and recorded a silent success.

``stdout_tail`` is not the answer and cannot stand in for it -- it is the last
2000 characters of raw stream JSON, truncated from the front.

These tests drive the buffered runner path, which feeds the same translator and
the same ``emit_event`` as the live stream.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from thomas.forge.anvil.dispatch_claude_cli import dispatch_via_claude_cli


def _repo(tmp_path: Path) -> str:
    """A real git repo: dispatch refuses a workspace `git status` cannot read."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    return str(tmp_path)


def _runner_returning(*lines: str):
    def runner(cmd, cwd, timeout):  # noqa: ARG001 - injection signature
        return 0, "\n".join(lines)

    return runner


def _result_line(text: str) -> str:
    return json.dumps({"type": "result", "is_error": False, "result": text})


def _assistant_line(text: str) -> str:
    return json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})


def test_the_reply_text_survives_the_dispatch(tmp_path: Path) -> None:
    answer = "/api/chat is the route; see agentic_benchmark_runners.py line 571."
    res = dispatch_via_claude_cli(
        "which route?",
        cwd=_repo(tmp_path),
        dry_run=False,
        runner=_runner_returning(_result_line(answer)),
        claude_bin="claude",
    )
    assert answer in res.reply, "the dispatcher dropped Claude's answer; this is the `ok chars=0` bug"


def test_a_streamed_reply_is_not_truncated_to_its_last_chunk(tmp_path: Path) -> None:
    """Keeping only the newest `say` would report the tail as the whole answer."""
    res = dispatch_via_claude_cli(
        "explain",
        cwd=_repo(tmp_path),
        dry_run=False,
        runner=_runner_returning(
            _assistant_line("FIRST PART. "),
            _assistant_line("SECOND PART."),
        ),
        claude_bin="claude",
    )
    assert "FIRST PART." in res.reply, "an early chunk was overwritten by a later one"
    assert "SECOND PART." in res.reply


def test_a_silent_run_is_reported_as_silent(tmp_path: Path) -> None:
    """Absence must read as absence -- the empty string is the honest answer."""
    res = dispatch_via_claude_cli(
        "say nothing",
        cwd=_repo(tmp_path),
        dry_run=False,
        runner=_runner_returning(""),
        claude_bin="claude",
    )
    assert res.reply == ""
    assert res.to_dict()["reply_chars"] == 0


def test_the_summary_counts_the_reply_so_a_zero_is_visible(tmp_path: Path) -> None:
    """`reply_chars` in to_dict is what makes a dropped answer show up in a log."""
    res = dispatch_via_claude_cli(
        "which route?",
        cwd=_repo(tmp_path),
        dry_run=False,
        runner=_runner_returning(_result_line("hello")),
        claude_bin="claude",
    )
    assert res.to_dict()["reply_chars"] == len(res.reply) > 0
