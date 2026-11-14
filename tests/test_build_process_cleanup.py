"""A Build run ends its own caged shell processes and reports cleanup evidence."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from scripts.cage import shell_runner

from tests.test_evolve_agent_routes import _new_repo
from thomas.forge.anvil import forge_code_store
from thomas.server.routes import evolve_agent_runtime
from thomas.tools import cage_shell
from thomas.tools.cage_shell import CagedResult


class _EmptyStdout:
    async def read(self, _n: int = -1) -> bytes:
        return b""


class _ExitedProcess:
    stdout = _EmptyStdout()
    returncode = 0

    async def wait(self) -> int:
        return 0


def test_cleanup_targets_only_the_project_containing_the_run(tmp_path: Path, monkeypatch: Any) -> None:
    project = tmp_path / "green" / "work" / "exec-one"
    nested = project / "src"
    nested.mkdir(parents=True)
    called: list[str] = []
    monkeypatch.setattr(
        cage_shell, "end_green", lambda name: called.append(name) or CagedResult("ok", 0, "processes left: []")
    )

    assert cage_shell.end_project_processes(nested) == "processes left: []"
    assert cage_shell.end_project_processes(tmp_path / "other") == "no caged project process group"
    assert called == ["exec-one"]


def test_runner_with_no_project_job_reports_no_processes(monkeypatch: Any) -> None:
    monkeypatch.setattr(shell_runner, "_GREEN_JOBS", {})
    result = shell_runner._end_green({"id": "request-1", "green": "exec-one"})
    assert result["outcome"] == "ok"
    assert result["returncode"] == 0
    assert "processes left: []" in result["output"]


def test_runner_reports_unknown_if_process_listing_fails(monkeypatch: Any) -> None:
    class Kernel:
        terminated = False
        closed = False

        def TerminateJobObject(self, _handle: int, _code: int) -> bool:
            self.terminated = True
            return True

        def CloseHandle(self, _handle: int) -> None:
            self.closed = True

    kernel = Kernel()
    monkeypatch.setattr(shell_runner, "_GREEN_JOBS", {"exec-one": 42})
    monkeypatch.setattr(shell_runner, "_winapi", lambda: (kernel, None))

    def cannot_list(_handle: int, *, strict: bool = False) -> set[int]:
        assert strict
        raise OSError("job query failed")

    monkeypatch.setattr(shell_runner.process_guard, "pids_in_job", cannot_list)
    result = shell_runner._end_green({"id": "request-1", "green": "exec-one"})
    assert kernel.terminated and kernel.closed
    assert result["outcome"] == "error"
    assert "stopped process IDs: unknown; processes left: unknown" in result["output"]


def test_runner_reports_remaining_ids_after_failed_termination(monkeypatch: Any) -> None:
    class Kernel:
        def TerminateJobObject(self, _handle: int, _code: int) -> bool:
            return False

        def CloseHandle(self, _handle: int) -> None:
            pass

    monkeypatch.setattr(shell_runner, "_GREEN_JOBS", {"exec-one": 42})
    monkeypatch.setattr(shell_runner, "_winapi", lambda: (Kernel(), None))
    monkeypatch.setattr(shell_runner.process_guard, "pids_in_job", lambda _handle, *, strict: {1234})
    result = shell_runner._end_green({"id": "request-1", "green": "exec-one"})
    assert result["outcome"] == "error"
    assert "processes left: [1234]" in result["output"]


def test_cleanup_without_a_runner_fails_fast(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setattr(cage_shell, "runner_alive", lambda _root: False)
    monkeypatch.setattr(cage_shell, "posture", lambda _root: "required")
    monkeypatch.setattr(cage_shell, "run_caged", lambda *_args, **_kwargs: pytest.fail("runner was not alive"))

    result = cage_shell.end_green("exec-one", root=tmp_path)
    assert result.outcome == "no_runner"
    assert result.returncode == -1


def test_no_runner_auto_posture_preserves_successful_run(tmp_path: Path, monkeypatch: Any) -> None:
    green = tmp_path / "green" / "work" / "exec-one"
    green.mkdir(parents=True)
    repo = _new_repo(green)
    conv = forge_code_store.new_conversation(repo)
    transcript = repo / "transcript.txt"
    transcript.write_text("", encoding="utf-8")
    monkeypatch.setattr(cage_shell, "runner_alive", lambda _root: False)
    monkeypatch.setattr(cage_shell, "posture", lambda _root=None: "auto")
    monkeypatch.setattr(cage_shell, "run_caged", lambda *_args, **_kwargs: pytest.fail("runner was not alive"))

    result = asyncio.run(
        evolve_agent_runtime._drain_and_record(
            _ExitedProcess(), transcript, repo, conv["id"], "test-model", {}, web.Application()
        )
    )

    assert result["process_cleanup"] == "no caged runner; no caged processes to end"
    turn = forge_code_store.load_conversation(repo, conv["id"])["turns"][-1]
    assert turn["ok"] is True
    assert turn["outcome"] != "failed"
    assert "cleanup unavailable" not in turn["reason"]


def test_run_cleanup_is_recorded_even_when_run_has_no_changes(tmp_path: Path, monkeypatch: Any) -> None:
    repo = _new_repo(tmp_path)
    conv = forge_code_store.new_conversation(repo)
    transcript = repo / "transcript.txt"
    transcript.write_text("", encoding="utf-8")
    called: list[Path] = []

    def end_project(root: Path) -> str:
        called.append(root)
        return "ended green exec-one; stopped process IDs: [123]; processes left: []"

    monkeypatch.setattr(cage_shell, "end_project_processes", end_project)
    result = asyncio.run(
        evolve_agent_runtime._drain_and_record(
            _ExitedProcess(), transcript, repo, conv["id"], "test-model", {}, web.Application()
        )
    )

    assert called == [repo]
    assert result["process_cleanup"] == "ended green exec-one; stopped process IDs: [123]; processes left: []"
    saved = forge_code_store.load_conversation(repo, conv["id"])
    assert saved["turns"][-1]["report"]["process_cleanup"] == result["process_cleanup"]


def test_run_reports_processes_left_when_cleanup_is_incomplete(tmp_path: Path, monkeypatch: Any) -> None:
    repo = _new_repo(tmp_path)
    conv = forge_code_store.new_conversation(repo)
    transcript = repo / "transcript.txt"
    transcript.write_text("", encoding="utf-8")
    monkeypatch.setattr(cage_shell, "end_project_processes", lambda _root: "processes left: [456]")

    result = asyncio.run(
        evolve_agent_runtime._drain_and_record(
            _ExitedProcess(), transcript, repo, conv["id"], "test-model", {}, web.Application()
        )
    )
    assert result["process_cleanup"] == "processes left: [456]"
    saved = forge_code_store.load_conversation(repo, conv["id"])
    assert "processes left: [456]" in saved["turns"][-1]["reason"]
    assert saved["turns"][-1]["outcome"] == "failed"
    assert saved["turns"][-1]["ok"] is False


def test_run_reports_cleanup_unavailable_as_failure(tmp_path: Path, monkeypatch: Any) -> None:
    repo = _new_repo(tmp_path)
    conv = forge_code_store.new_conversation(repo)
    transcript = repo / "transcript.txt"
    transcript.write_text("", encoding="utf-8")
    monkeypatch.setattr(cage_shell, "end_project_processes", lambda _root: "cleanup unavailable: runner stopped")

    result = asyncio.run(
        evolve_agent_runtime._drain_and_record(
            _ExitedProcess(), transcript, repo, conv["id"], "test-model", {}, web.Application()
        )
    )
    assert result["process_cleanup"] == "cleanup unavailable: runner stopped"
    turn = forge_code_store.load_conversation(repo, conv["id"])["turns"][-1]
    assert turn["outcome"] == "failed"
    assert "cleanup unavailable: runner stopped" in turn["reason"]


def test_run_cleanup_runs_when_drain_raises(tmp_path: Path, monkeypatch: Any) -> None:
    repo = _new_repo(tmp_path)
    conv = forge_code_store.new_conversation(repo)
    called: list[Path] = []

    async def broken_drain(*_args: Any) -> bool:
        raise OSError("transcript read failed")

    monkeypatch.setattr(evolve_agent_runtime, "_drain", broken_drain)
    monkeypatch.setattr(cage_shell, "end_project_processes", lambda root: called.append(root) or "processes left: []")
    with pytest.raises(OSError, match="transcript read failed"):
        asyncio.run(
            evolve_agent_runtime._drain_and_record(
                _ExitedProcess(), repo / "missing.txt", repo, conv["id"], "test-model", {}, web.Application()
            )
        )
    assert called == [repo]
