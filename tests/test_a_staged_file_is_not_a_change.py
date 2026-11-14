"""Staging existing bytes is not new work for a Build run."""

from __future__ import annotations

import asyncio
from pathlib import Path

from aiohttp import web

from thomas.forge.anvil import forge_code_git, forge_code_store
from thomas.server.routes import evolve_agent_runtime


def _run(repo: Path, *args: str) -> None:
    rc, stdout, stderr = forge_code_git._run_git(repo, list(args))
    assert rc == 0, (args, stdout, stderr)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(repo, "init")
    _run(repo, "config", "user.email", "test@example.com")
    _run(repo, "config", "user.name", "Forge Test")
    _run(repo, "config", "commit.gpgsign", "false")
    (repo / "base.txt").write_text("committed\n", encoding="utf-8")
    (repo / "other.txt").write_text("committed too\n", encoding="utf-8")
    _run(repo, "add", "base.txt", "other.txt")
    _run(repo, "commit", "-m", "base")
    return repo


def test_staging_an_untracked_file_does_not_change_its_contents(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "helper.py").write_text("print('ready')\n", encoding="utf-8")
    snap = forge_code_git.snapshot(repo)
    assert snap["helper.py"].startswith("??\0")

    _run(repo, "add", "helper.py")

    assert forge_code_git.delta_since(repo, snap) == []
    assert forge_code_git.project_delta_since(repo, snap) == []


def test_staging_a_modified_committed_file_does_not_change_its_contents(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "base.txt").write_text("changed before run\n", encoding="utf-8")
    snap = forge_code_git.snapshot(repo)
    assert snap["base.txt"].startswith(" M\0")

    _run(repo, "add", "base.txt")

    assert forge_code_git.delta_since(repo, snap) == []


def test_rewriting_a_staged_untracked_file_is_a_change(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    file = repo / "helper.py"
    file.write_text("before\n", encoding="utf-8")
    snap = forge_code_git.snapshot(repo)

    _run(repo, "add", "helper.py")
    file.write_text("after\n", encoding="utf-8")

    assert forge_code_git.delta_since(repo, snap) == ["helper.py"]


def test_new_staged_file_after_snapshot_is_a_change(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    snap = forge_code_git.snapshot(repo)

    (repo / "helper.py").write_text("new\n", encoding="utf-8")
    _run(repo, "add", "helper.py")

    assert forge_code_git.delta_since(repo, snap) == ["helper.py"]


def test_clean_committed_file_deleted_after_snapshot_is_a_change(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    snap = forge_code_git.snapshot(repo)

    (repo / "base.txt").unlink()

    assert forge_code_git.delta_since(repo, snap) == ["base.txt"]


def test_modified_committed_file_deleted_after_snapshot_is_a_change(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "base.txt").write_text("changed before run\n", encoding="utf-8")
    snap = forge_code_git.snapshot(repo)

    (repo / "base.txt").unlink()

    assert forge_code_git.delta_since(repo, snap) == ["base.txt"]


def test_git_rm_after_snapshot_is_a_change(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    snap = forge_code_git.snapshot(repo)

    _run(repo, "rm", "base.txt")

    assert forge_code_git.delta_since(repo, snap) == ["base.txt"]


def test_staging_an_unreadable_file_still_counts_as_a_change(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    (repo / "helper.py").write_text("bytes cannot be confirmed\n", encoding="utf-8")
    real_fingerprint = forge_code_git._content_fingerprint

    def unreadable_fingerprint(root: str | Path, path: str, status: str) -> str:
        if path == "helper.py":
            return f"{status}\0unreadable:PermissionError"
        return real_fingerprint(root, path, status)

    monkeypatch.setattr(forge_code_git, "_content_fingerprint", unreadable_fingerprint)
    snap = forge_code_git.snapshot(repo)

    _run(repo, "add", "helper.py")

    assert forge_code_git.delta_since(repo, snap) == ["helper.py"]


class _EmptyStdout:
    async def readline(self) -> bytes:
        return b""

    async def read(self, n: int) -> bytes:
        return b""


class _ExitedProcess:
    returncode = 0
    stdout = _EmptyStdout()

    async def wait(self) -> int:
        return 0


def test_recorder_files_staging_only_run_as_conversation(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    cid = forge_code_store.new_conversation(repo)["id"]
    (repo / "helper.py").write_text("already written\n", encoding="utf-8")
    transcript = tmp_path / "transcript.txt"
    transcript.write_text('{"fc":"final","text":"DONE"}\n', encoding="utf-8")
    snap = forge_code_git.snapshot(repo)

    _run(repo, "add", "helper.py")
    result = asyncio.run(
        evolve_agent_runtime._drain_and_record(
            _ExitedProcess(), transcript, repo, cid, "test-model", snap, web.Application(), run_id="run-staged"
        )
    )

    assert result["outcome"] == "conversation"
    assert forge_code_store.load_conversation(repo, cid)["turns"][-1]["changed_files"] == []
