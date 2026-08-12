from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web

from tests.test_evolve_agent_routes import _new_repo
from thomas.forge.anvil import forge_code_git, forge_code_store
from thomas.server.routes import evolve_agent_receipts, evolve_agent_runtime


def _run_concurrent_receipt_mutations(
    monkeypatch: Any,
    first: Any,
    second: Any,
) -> None:
    original_read = evolve_agent_receipts._read_receipts_path
    entered, release, second_done = threading.Event(), threading.Event(), threading.Event()
    errors: list[BaseException] = []

    def _stalled_read(path: Path) -> dict[str, dict[str, Any]]:
        receipts = original_read(path)
        if threading.current_thread().name == "receipt-first":
            entered.set()
            if not release.wait(5):
                raise TimeoutError("receipt concurrency test timed out")
        return receipts

    def _run(action: Any, done: threading.Event | None = None) -> None:
        try:
            action()
        except (AssertionError, OSError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
            errors.append(exc)
        finally:
            if done is not None:
                done.set()

    monkeypatch.setattr(evolve_agent_receipts, "_read_receipts_path", _stalled_read)
    first_thread = threading.Thread(target=_run, args=(first,), name="receipt-first")
    second_thread = threading.Thread(target=_run, args=(second, second_done), name="receipt-second")
    first_thread.start()
    assert entered.wait(5)
    second_thread.start()
    assert not second_done.wait(0.1)
    release.set()
    first_thread.join(5)
    second_thread.join(5)
    assert not first_thread.is_alive() and not second_thread.is_alive()
    assert errors == []


def test_durable_running_receipt_fails_closed_when_no_live_run_can_verify_it() -> None:
    receipt = {"state": "running", "response": {"run_id": "run-before-restart"}}

    class _Recording:
        @staticmethod
        def done() -> bool:
            return False

    assert evolve_agent_runtime._run_replay_available(receipt, {}, False, None) is False
    assert (
        evolve_agent_runtime._run_replay_available(
            receipt,
            {"run_id": "run-before-restart"},
            False,
            _Recording(),
        )
        is True
    )
    assert evolve_agent_runtime._run_replay_available({**receipt, "state": "completed"}, {}, False, None) is True
    assert evolve_agent_runtime._run_replay_available({**receipt, "state": "corrupt"}, {}, False, None) is False


def test_final_receipt_write_failure_overrides_apparent_run_success(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo = _new_repo(tmp_path)
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "thomas-data"))
    conversation = forge_code_store.new_conversation(repo)
    transcript = repo / "receipt-failure.txt"
    transcript.write_text("completed output\n", encoding="utf-8")
    request_id = "receipt-write-failure"
    evolve_agent_runtime._save_action_receipt(
        repo,
        "run",
        request_id,
        {"state": "running", "response": {"run_id": "run-receipt-failure"}},
    )

    class _EmptyStdout:
        async def readline(self) -> bytes:
            return b""

    class _FinishedProcess:
        returncode = 0
        stdout = _EmptyStdout()

        async def wait(self) -> int:
            return 0

    def _fail_receipt(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise OSError("receipt disk unavailable")

    monkeypatch.setattr(forge_code_git, "delta_since", lambda *_args: ["result.txt"])
    monkeypatch.setattr(evolve_agent_runtime, "_save_action_receipt", _fail_receipt)

    async def _run() -> None:
        result = await evolve_agent_runtime._drain_and_record(
            _FinishedProcess(),
            transcript,
            repo,
            conversation["id"],
            "test-model",
            {},
            web.Application(),
            catalog_root=repo,
            request_id=request_id,
            run_id="run-receipt-failure",
        )
        assert result["persistence_confirmed"] is False
        assert result["ok"] is False
        assert result["noop"] is False
        assert result["outcome"] == "persistence_failed"
        assert result["receipt_error"] == "receipt disk unavailable"
        recording = asyncio.get_running_loop().create_future()
        recording.set_result(result)
        status = evolve_agent_runtime._recording_status(recording)
        assert status["persistence_state"] == "failed"
        assert status["outcome"] == "persistence_failed"

    asyncio.run(_run())


def test_action_receipts_use_data_root_with_repo_scoped_separation(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    data_root = tmp_path / "configured-data"
    repo_a, repo_b = tmp_path / "repo-a", tmp_path / "repo-b"
    repo_a.mkdir()
    repo_b.mkdir()
    monkeypatch.setenv("THOMAS_DATA_DIR", str(data_root))
    monkeypatch.delenv("THOMAS_PROFILE", raising=False)

    evolve_agent_runtime._save_action_receipt(repo_a, "run", "same-request", {"repo": "a"})
    evolve_agent_runtime._save_action_receipt(repo_b, "run", "same-request", {"repo": "b"})

    assert evolve_agent_runtime._action_receipt(repo_a, "run", "same-request") == {"repo": "a"}
    assert evolve_agent_runtime._action_receipt(repo_b, "run", "same-request") == {"repo": "b"}
    receipt_files = list((data_root / "forge_code").glob("*/action_receipts.json"))
    assert len(receipt_files) == 2
    assert not (repo_a / ".thomas" / "evolve" / "agent" / "action_receipts.json").exists()
    assert not (repo_b / ".thomas" / "evolve" / "agent" / "action_receipts.json").exists()


def test_concurrent_receipt_writers_preserve_both_entries_and_use_unique_temps(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    original_mkstemp = evolve_agent_receipts.tempfile.mkstemp
    temporary_paths: list[str] = []

    def _tracked_mkstemp(*args: Any, **kwargs: Any) -> tuple[int, str]:
        fd, path = original_mkstemp(*args, **kwargs)
        temporary_paths.append(path)
        return fd, path

    monkeypatch.setattr(evolve_agent_receipts.tempfile, "mkstemp", _tracked_mkstemp)
    _run_concurrent_receipt_mutations(
        monkeypatch,
        lambda: evolve_agent_receipts._save_action_receipt(repo, "run", "request-a", {"value": "a"}),
        lambda: evolve_agent_receipts._save_action_receipt(repo, "revert", "request-b", {"value": "b"}),
    )

    assert evolve_agent_receipts._action_receipt(repo, "run", "request-a") == {"value": "a"}
    assert evolve_agent_receipts._action_receipt(repo, "revert", "request-b") == {"value": "b"}
    assert len(temporary_paths) == len(set(temporary_paths)) == 2
    assert not any(Path(path).exists() for path in temporary_paths)


def test_concurrent_receipt_delete_cannot_erase_or_resurrect_unrelated_entries(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    evolve_agent_receipts._save_action_receipt(repo, "run", "keep", {"value": "keep"})
    evolve_agent_receipts._save_action_receipt(repo, "run", "remove", {"value": "remove"})

    _run_concurrent_receipt_mutations(
        monkeypatch,
        lambda: evolve_agent_receipts._save_action_receipt(repo, "revert", "new", {"value": "new"}),
        lambda: evolve_agent_receipts._delete_action_receipt(repo, "run", "remove"),
    )

    assert evolve_agent_receipts._action_receipt(repo, "run", "keep") == {"value": "keep"}
    assert evolve_agent_receipts._action_receipt(repo, "revert", "new") == {"value": "new"}
    assert evolve_agent_receipts._action_receipt(repo, "run", "remove") is None


def test_corrupt_receipt_catalog_remains_fail_closed(tmp_path: Path, monkeypatch: Any) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    path = evolve_agent_receipts._receipt_path(repo)
    for corrupt in ("{broken", '{"prior-request": "invalid-entry"}'):
        path.write_text(corrupt, encoding="utf-8")
        with pytest.raises(RuntimeError, match="unreadable|invalid entry"):
            evolve_agent_receipts._save_action_receipt(repo, "run", "request", {"value": "new"})
