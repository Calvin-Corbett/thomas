"""A process crash without the runner's terminal verdict fails closed."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web

from tests.test_evolve_agent_routes import _new_repo
from thomas.forge.anvil import forge_code_git, forge_code_store
from thomas.server.routes import evolve_agent_runtime


class _EmptyStdout:
    async def readline(self) -> bytes:
        return b""


class _ExitedProcess:
    stdout = _EmptyStdout()
    returncode = 1

    async def wait(self) -> int:
        return self.returncode


def _record_crash(
    repo: Path,
    conversation_id: str,
    transcript: Path,
) -> dict[str, Any]:
    return asyncio.run(
        evolve_agent_runtime._drain_and_record(
            _ExitedProcess(),
            transcript,
            repo,
            conversation_id,
            "claude:sonnet",
            {},
            web.Application(),
            run_id="issue-132",
        )
    )


def test_traceback_after_partial_write_is_failed_without_terminal_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _new_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    transcript = repo / "transcript.txt"
    transcript.write_text(
        "Traceback (most recent call last):\n  File \"forge_code_runner.py\", line 190, in main\nKeyError: 'missing'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(forge_code_git, "project_delta_since", lambda _root, _snap: ["DESIGN.md"])

    result = _record_crash(repo, conversation["id"], transcript)

    assert result["ok"] is False
    assert result["outcome"] == "failed"
    saved = forge_code_store.load_conversation(repo, conversation["id"])
    reason = saved["turns"][-1]["reason"]
    assert "KeyError: 'missing'" in reason
    assert "1 file(s) had changed by then" in reason


def test_unmarked_progress_meta_is_not_mistaken_for_terminal_success(
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
                "text": "a write-capable tool ran; no files changed",
                "is_error": False,
            }
        )
        + "\nTraceback (most recent call last):\nRuntimeError: runner crashed\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(forge_code_git, "project_delta_since", lambda _root, _snap: ["index.html"])

    result = _record_crash(repo, conversation["id"], transcript)

    assert result["ok"] is False
    assert result["outcome"] == "failed"
    saved = forge_code_store.load_conversation(repo, conversation["id"])
    assert "RuntimeError: runner crashed" in saved["turns"][-1]["reason"]
