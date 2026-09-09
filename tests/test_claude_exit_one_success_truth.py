"""A successful Claude result can outvote its unreliable process exit code."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web

from tests.test_evolve_agent_routes import _new_repo
from thomas.forge.anvil import forge_code_git, forge_code_runner, forge_code_store
from thomas.forge.anvil.dispatch_claude_cli import CliDispatchResult, dispatch_via_claude_cli
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


def _record(repo: Path, conversation_id: str, transcript: Path, *, returncode: int) -> dict[str, Any]:
    return asyncio.run(
        evolve_agent_runtime._drain_and_record(
            _ExitedProcess(returncode),
            transcript,
            repo,
            conversation_id,
            "claude:sonnet",
            {},
            web.Application(),
            run_id="issue-116",
        )
    )


def test_claude_final_plus_changed_file_outvotes_exit_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[dict[str, Any]] = []
    raw_result = json.dumps(
        {
            "type": "result",
            "is_error": False,
            "result": "Done; index.html was built.",
        }
    )
    monkeypatch.setattr(forge_code_git, "snapshot", lambda _root: {})
    monkeypatch.setattr(forge_code_git, "project_delta_since", lambda _root, _snap: ["index.html"])

    result = dispatch_via_claude_cli(
        "build it",
        cwd=tmp_path,
        dry_run=False,
        verify=False,
        runner=lambda _cmd, _cwd, _timeout: (1, raw_result),
        claude_bin="claude",
        emit=events.append,
    )

    assert result.ok is True
    assert result.returncode == 1
    assert result.changed_files == ["index.html"]
    assert "build process exited 1" in result.reason
    assert events == [{"fc": "final", "text": "Done; index.html was built."}]


def test_claude_final_plus_exit_one_still_must_pass_verification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_result = json.dumps(
        {
            "type": "result",
            "is_error": False,
            "result": "Done; index.html was built.",
        }
    )
    verifier_calls: list[tuple[Path, list[str]]] = []

    def _failing_verifier(root: Path, changed: list[str], _emit: Any) -> tuple[bool, int, str]:
        verifier_calls.append((root, changed))
        return False, 7, "the focused check failed"

    monkeypatch.setattr(forge_code_git, "snapshot", lambda _root: {})
    monkeypatch.setattr(forge_code_git, "project_delta_since", lambda _root, _snap: ["index.html"])

    result = dispatch_via_claude_cli(
        "build it",
        cwd=tmp_path,
        dry_run=False,
        verify=True,
        verifier=_failing_verifier,
        max_fix_iters=0,
        runner=lambda _cmd, _cwd, _timeout: (1, raw_result),
        claude_bin="claude",
    )

    assert verifier_calls == [(tmp_path, ["index.html"])]
    assert result.ok is False
    assert result.returncode == 7
    assert result.changed_files == ["index.html"]
    assert result.reason == "verification failed (exit 7) after fix attempts"


def test_partial_narration_plus_changed_file_does_not_outvote_exit_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    partial = json.dumps(
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "I am still building it"}]},
        }
    )
    monkeypatch.setattr(forge_code_git, "snapshot", lambda _root: {})
    monkeypatch.setattr(forge_code_git, "project_delta_since", lambda _root, _snap: ["index.html"])

    result = dispatch_via_claude_cli(
        "build it",
        cwd=tmp_path,
        dry_run=False,
        verify=False,
        runner=lambda _cmd, _cwd, _timeout: (1, partial),
        claude_bin="claude",
    )

    assert result.ok is False
    assert result.reason == "claude exited 1"


def test_runner_marks_its_single_final_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[dict[str, Any]] = []
    monkeypatch.setattr(forge_code_runner, "history_turns", lambda _root, _cid: [])
    monkeypatch.setattr(
        forge_code_runner,
        "dispatch_via_claude_cli",
        lambda *_args, **_kwargs: CliDispatchResult(
            True,
            "1 file changed (build process exited 1)",
            "prompt",
            returncode=1,
            changed_files=["index.html"],
        ),
    )
    monkeypatch.setattr(forge_code_runner, "_default_emit", events.append)
    args = forge_code_runner.build_parser().parse_args(
        [
            "build it",
            "--project-root",
            str(tmp_path),
            "--family",
            "claude",
            "--model",
            "sonnet",
        ]
    )

    assert forge_code_runner.run_configured_turn(args) == 1
    assert events == [
        {
            "fc": "meta",
            "text": "1 file changed (build process exited 1)",
            "is_error": False,
            "terminal": True,
        }
    ]


def test_marked_terminal_success_allows_recorder_to_accept_exit_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _new_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    transcript = repo / "transcript.txt"
    transcript.write_text(
        json.dumps(
            {
                "fc": "meta",
                "text": "dispatched via claude CLI (1 file changed; process exited 1)",
                "is_error": False,
                "terminal": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(forge_code_git, "project_delta_since", lambda _root, _snap: ["index.html"])

    result = _record(repo, conversation["id"], transcript, returncode=1)

    assert result["ok"] is True
    assert result["outcome"] == "completed"
    saved = forge_code_store.load_conversation(repo, conversation["id"])
    assert saved["turns"][-1]["reason"] == "1 file(s) changed (build process exited 1)"
