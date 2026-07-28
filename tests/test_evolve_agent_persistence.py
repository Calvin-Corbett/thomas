from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient

from tests.test_evolve_agent_routes import _drive, _new_repo
from thomas.forge.anvil import forge_code_git, forge_code_store
from thomas.server.app_keys import APP_ENGINE_MANAGER
from thomas.server.routes import evolve_agent_routes, evolve_agent_runtime
from thomas.server.routes.evolve_agent_routes import (
    APP_EVOLVE_AGENT_DRAIN,
    APP_EVOLVE_AGENT_SESSION,
    APP_EVOLVE_AGENT_TASK,
)


def test_active_code_run_keeps_idle_engines_suspended() -> None:
    class _Manager:
        def __init__(self) -> None:
            self.pulses = 0

        def record_user_message(self) -> None:
            self.pulses += 1

    class _Process:
        returncode: int | None = None

    async def _run() -> None:
        app = web.Application()
        manager = _Manager()
        process = _Process()
        app[APP_ENGINE_MANAGER] = manager
        task = asyncio.create_task(evolve_agent_runtime._keep_code_run_active(app, process, interval_s=0.01))
        await asyncio.sleep(0.12)
        process.returncode = 0
        await task
        assert manager.pulses >= 2

    asyncio.run(_run())


def test_completed_code_task_releases_only_its_own_activity_lease() -> None:
    class _Manager:
        def __init__(self) -> None:
            self.ended: list[str] = []

        def begin_interactive_work(self, label: str) -> str:
            return label

        def end_interactive_work(self, token: str) -> None:
            self.ended.append(token)

    async def _run() -> None:
        app = web.Application()
        manager = _Manager()
        app[APP_ENGINE_MANAGER] = manager
        old_token = evolve_agent_runtime._acquire_code_activity_lease(app, "old-run")
        completed = asyncio.get_running_loop().create_future()
        evolve_agent_runtime._attach_code_activity_release(completed, app, old_token)
        new_token = evolve_agent_runtime._acquire_code_activity_lease(app, "new-run")

        completed.set_result(None)
        await asyncio.sleep(0)

        assert manager.ended == ["code:old-run"]
        evolve_agent_runtime._release_code_activity_lease(app, new_token)
        assert manager.ended == ["code:old-run", "code:new-run"]

    asyncio.run(_run())


def test_cancellation_during_background_lease_acquisition_cannot_orphan_lease() -> None:
    entered = threading.Event()
    release = threading.Event()

    class _Manager:
        def __init__(self) -> None:
            self.ended: list[str] = []

        def begin_interactive_work(self, label: str) -> str:
            entered.set()
            assert release.wait(timeout=5)
            return label

        def end_interactive_work(self, token: str) -> None:
            self.ended.append(token)

    async def _run() -> None:
        app = web.Application()
        manager = _Manager()
        app[APP_ENGINE_MANAGER] = manager
        task = asyncio.create_task(evolve_agent_runtime.acquire_code_activity_lease_async(app, "cancelled-run"))
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert manager.ended == ["code:cancelled-run"]

    asyncio.run(_run())


def test_cancelled_start_gate_terminates_child_and_rolls_back_receipt(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo = _new_repo(tmp_path)
    gate_entered = asyncio.Event()

    class _Process:
        pid = 817
        returncode: int | None = None

        async def wait(self) -> int:
            assert self.returncode is not None
            return self.returncode

    process = _Process()

    async def _spawn(*_args: Any, **_kwargs: Any) -> _Process:
        return process

    async def _blocked_gate(*_args: Any, **_kwargs: Any) -> None:
        gate_entered.set()
        await asyncio.Future()

    def _kill(child: _Process) -> None:
        child.returncode = -15

    class _Manager:
        def __init__(self) -> None:
            self.ended: list[str] = []

        def record_user_message(self) -> None:
            return None

        def begin_interactive_work(self, label: str) -> str:
            return label

        def end_interactive_work(self, token: str) -> None:
            self.ended.append(token)

    class _Request:
        async def json(self) -> dict[str, str]:
            return {"message": "Build a game", "request_id": "cancelled-gate"}

    async def _run() -> None:
        app = web.Application()
        manager = _Manager()
        app[APP_ENGINE_MANAGER] = manager
        handler = evolve_agent_routes.build_evolve_agent_handlers(
            app,
            require_api_access=lambda _request: None,
            root_resolver=lambda: repo,
        )["send"]
        monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn)
        monkeypatch.setattr(evolve_agent_runtime, "_release_start_gate", _blocked_gate)
        monkeypatch.setattr(evolve_agent_runtime, "_kill_tree", _kill)

        request_task = asyncio.create_task(handler(_Request()))
        await gate_entered.wait()
        request_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request_task

        assert process.returncode == -15
        assert len(manager.ended) == 1
        assert manager.ended[0].startswith("code:run-")
        assert evolve_agent_runtime._action_receipt(repo, "run", "cancelled-gate") is None
        assert forge_code_store.list_conversations(repo) == []

    asyncio.run(_run())


def test_cancelled_start_gate_after_payload_write_keeps_nonretryable_state(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo = _new_repo(tmp_path)
    drain_entered = asyncio.Event()

    class _GateWriter:
        def __init__(self, process: Any) -> None:
            self.process = process

        def write(self, data: bytes) -> None:
            payload = json.loads(data.decode())
            assert payload.get("gate_token")
            self.process.payload_written = True

        async def drain(self) -> None:
            drain_entered.set()
            await asyncio.Future()

        def close(self) -> None:
            return None

    class _Process:
        pid = 818
        returncode: int | None = None

        def __init__(self) -> None:
            self.payload_written = False
            self.stdin = _GateWriter(self)
            self.stdout = SimpleNamespace(readline=self._readline)

        async def _readline(self) -> bytes:
            return b""

        async def wait(self) -> int:
            assert self.returncode is not None
            return self.returncode

    process = _Process()

    async def _spawn(*_args: Any, **_kwargs: Any) -> _Process:
        return process

    def _kill(child: _Process) -> None:
        child.returncode = -15

    class _Manager:
        def __init__(self) -> None:
            self.ended: list[str] = []

        def record_user_message(self) -> None:
            return None

        def begin_interactive_work(self, label: str) -> str:
            return label

        def end_interactive_work(self, token: str) -> None:
            self.ended.append(token)

    class _Request:
        async def json(self) -> dict[str, str]:
            return {"message": "Perform once", "request_id": "cancel-after-write"}

    async def _run() -> None:
        app = web.Application()
        manager = _Manager()
        app[APP_ENGINE_MANAGER] = manager
        handler = evolve_agent_routes.build_evolve_agent_handlers(
            app,
            require_api_access=lambda _request: None,
            root_resolver=lambda: repo,
        )["send"]
        monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn)
        monkeypatch.setattr(evolve_agent_runtime, "_kill_tree", _kill)

        request_task = asyncio.create_task(handler(_Request()))
        await drain_entered.wait()
        request_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await request_task

        drain = app[APP_EVOLVE_AGENT_DRAIN]["task"]
        result = await drain

        assert process.payload_written is True
        assert process.returncode == -15
        assert len(manager.ended) == 1
        receipt = evolve_agent_runtime._action_receipt(repo, "run", "cancel-after-write")
        assert receipt is not None
        assert receipt["state"] == "completed"
        assert result["persistence_confirmed"] is True
        assert result["outcome"] == "failed"
        conversations = forge_code_store.list_conversations(repo)
        assert len(conversations) == 1
        conversation = forge_code_store.load_conversation(repo, conversations[0]["id"])
        assert conversation is not None
        assert any(turn.get("role") == "user" and turn.get("text") == "Perform once" for turn in conversation["turns"])
        assert (await handler(_Request())).status == 200

    asyncio.run(_run())


def test_prelaunch_preparation_failure_leaves_no_orphan_conversation(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo = _new_repo(tmp_path)

    def _failed_transcript(*_args: Any, **_kwargs: Any) -> Path:
        raise OSError("transcript unavailable")

    monkeypatch.setattr(evolve_agent_routes, "_transcript_path", _failed_transcript)

    async def _body(client: TestClient) -> None:
        response = await client.post(
            "/api/evolve/agent/send",
            json={"message": "Build a local page", "request_id": "prelaunch-failure"},
        )
        assert response.status == 500
        assert forge_code_store.list_conversations(repo) == []

    _drive(repo, _body)


def test_parent_death_before_receipt_release_cannot_execute_first_child(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo = _new_repo(tmp_path)
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "thomas-data"))
    spawned: list[Any] = []

    class _EmptyStdout:
        async def readline(self) -> bytes:
            return b""

    class _GateWriter:
        def __init__(self, child: Any, token: str) -> None:
            self.child = child
            self.token = token

        def write(self, data: bytes) -> None:
            payload = json.loads(data.decode())
            if payload.get("gate_token") == self.token:
                self.child.executed = True

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            self.child.gate_closed = True

    class _BlockedChild:
        pid = 771

        def __init__(self, token: str) -> None:
            self.returncode = None
            self.stdout = _EmptyStdout()
            self.executed = False
            self.gate_closed = False
            self.stdin = _GateWriter(self, token)

        async def wait(self) -> int:
            self.returncode = 0
            return 0

    async def _spawn(*_args: Any, **kwargs: Any) -> _BlockedChild:
        child = _BlockedChild(kwargs["env"]["THOMAS_CODE_START_TOKEN"])
        spawned.append(child)
        return child

    class _Request:
        def __init__(
            self,
            message: str = "Build once",
            request_id: str = "hard-death-request",
            conversation_id: str = "",
        ) -> None:
            self.body = {"message": message, "request_id": request_id, "conversation_id": conversation_id}

        async def json(self) -> dict[str, str]:
            return self.body

    class _HardDeath(BaseException):
        pass

    async def _run() -> None:
        app = web.Application()
        handler = evolve_agent_routes.build_evolve_agent_handlers(
            app,
            require_api_access=lambda _request: None,
            root_resolver=lambda: repo,
        )["send"]
        monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn)
        save_receipt = evolve_agent_routes._save_action_receipt

        def _die_before_receipt(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise _HardDeath()

        monkeypatch.setattr(evolve_agent_routes, "_save_action_receipt", _die_before_receipt)
        with pytest.raises(_HardDeath):
            await handler(_Request())
        spawned[0].stdin.close()  # OS pipe closure when the parent dies.
        assert spawned[0].executed is False
        assert forge_code_store.list_conversations(repo) == []
        assert evolve_agent_runtime._action_receipt(repo, "run", "hard-death-request") is None

        monkeypatch.setattr(evolve_agent_routes, "_save_action_receipt", save_receipt)
        response = await handler(_Request())
        assert response.status == 200
        assert len(spawned) == 2
        assert [child.executed for child in spawned] == [False, True]
        await evolve_agent_runtime._await_recording(app[APP_EVOLVE_AGENT_DRAIN])

        cid = json.loads(response.text)["conversation_id"]

        def _fail_running_receipt(root: Path, kind: str, request_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
            if request_id == "pre-release-request" and receipt["state"] == "running":
                raise OSError("running receipt failed")
            return save_receipt(root, kind, request_id, receipt)

        monkeypatch.setattr(evolve_agent_routes, "_save_action_receipt", _fail_running_receipt)
        retry = _Request("Retry before release", "pre-release-request", cid)
        for _attempt in range(2):
            with pytest.raises(OSError, match="running receipt failed"):
                await handler(retry)
        conversation = forge_code_store.load_conversation(repo, cid)
        user_texts = [turn["text"] for turn in conversation["turns"] if turn["role"] == "user"]
        assert user_texts.count("Retry before release") == 0
        assert evolve_agent_runtime._action_receipt(repo, "run", "pre-release-request") is None

        async def _ambiguous_release(
            proc: Any,
            _token: str,
            *,
            oauth_access_token: str = "",
            goal: str = "",
            release_state: dict[str, bool] | None = None,
        ) -> None:
            assert oauth_access_token == ""
            assert goal == "Keep failed receipt"
            assert release_state is not None
            release_state["payload_write_attempted"] = True
            proc.executed = True
            raise OSError("drain failed after token delivery")

        monkeypatch.setattr(evolve_agent_routes, "_save_action_receipt", save_receipt)
        monkeypatch.setattr(evolve_agent_runtime, "_release_start_gate", _ambiguous_release)
        ambiguous = _Request("Keep failed receipt", "ambiguous-release", cid)
        with pytest.raises(OSError, match="after token delivery"):
            await handler(ambiguous)
        assert evolve_agent_runtime._action_receipt(repo, "run", "ambiguous-release")["state"] == "running"
        spawn_count = len(spawned)
        replayed = await handler(ambiguous)
        assert replayed.status == 200
        assert json.loads(replayed.text)["replayed"] is True
        assert len(spawned) == spawn_count

    asyncio.run(_run())


def test_unconfirmed_process_exit_is_persisted_as_failed_not_success(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo = _new_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    transcript = repo / "unknown-exit.txt"
    transcript.write_text("runner output\n", encoding="utf-8")

    class _EmptyStdout:
        async def readline(self) -> bytes:
            return b""

    class _UnknownExitProcess:
        returncode = None
        stdout = _EmptyStdout()

        async def wait(self) -> int:
            raise ChildProcessError("exit status unavailable")

    monkeypatch.setattr(forge_code_git, "project_delta_since", lambda *_args: ["result.txt"])

    async def _run() -> None:
        result = await evolve_agent_runtime._drain_and_record(
            _UnknownExitProcess(),
            transcript,
            repo,
            conversation["id"],
            "test-model",
            {},
            web.Application(),
            run_id="run-unknown-exit",
        )
        assert result["persistence_confirmed"] is True
        assert result["returncode"] is None
        assert result["ok"] is False
        assert result["noop"] is False
        assert result["outcome"] == "failed"
        saved = forge_code_store.load_conversation(repo, conversation["id"])
        assert saved["turns"][-1]["reason"] == "process output or exit could not be confirmed"
        assert saved["turns"][-1]["ok"] is False

    asyncio.run(_run())


def test_recorder_does_not_count_conversation_bookkeeping_as_project_work(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    transcript = repo / "bookkeeping-only.txt"
    transcript.write_text("conversation reply\n", encoding="utf-8")
    snap = forge_code_git.snapshot(repo)
    conversation_path = repo / ".thomas" / "evolve" / "agent" / "conversations" / f"{conversation['id']}.json"
    conversation_path.write_text(conversation_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    class _EmptyStdout:
        async def readline(self) -> bytes:
            return b""

    class _FinishedProcess:
        returncode = 0
        stdout = _EmptyStdout()

        async def wait(self) -> int:
            return 0

    async def _run() -> None:
        result = await evolve_agent_runtime._drain_and_record(
            _FinishedProcess(),
            transcript,
            repo,
            conversation["id"],
            "test-model",
            snap,
            web.Application(),
            run_id="run-bookkeeping-only",
        )

        assert result["changed_files"] == []
        assert result["ok"] is False
        assert result["noop"] is True
        assert result["outcome"] == "noop"

    asyncio.run(_run())


def test_recorder_preserves_a_confirmed_conversational_outcome(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    transcript = repo / "conversation.txt"
    transcript.write_text('{"fc":"final","text":"Hey! What should we build?"}\n', encoding="utf-8")
    snap = forge_code_git.snapshot(repo)

    class _EmptyStdout:
        async def readline(self) -> bytes:
            return b""

    class _FinishedProcess:
        returncode = 0
        stdout = _EmptyStdout()

        async def wait(self) -> int:
            return 0

    async def _run() -> None:
        result = await evolve_agent_runtime._drain_and_record(
            _FinishedProcess(),
            transcript,
            repo,
            conversation["id"],
            "test-model",
            snap,
            web.Application(),
            run_id="run-conversation",
        )
        assert result["ok"] is True
        assert result["noop"] is False
        assert result["outcome"] == "conversation"

    asyncio.run(_run())


def test_recorder_store_failure_is_reported_by_status_stop_and_sse(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo = _new_repo(tmp_path)
    transcript = repo / "failed-store-transcript.txt"
    transcript.write_text("runner output\n", encoding="utf-8")

    class _RunningProcess:
        returncode: int | None = None
        stdout = None

        async def wait(self) -> int:
            self.returncode = -15
            return self.returncode

    async def _no_drain(_proc: Any, _transcript: Path) -> None:
        return None

    monkeypatch.setattr(evolve_agent_runtime, "_drain", _no_drain)
    monkeypatch.setattr(evolve_agent_runtime, "_kill_tree", lambda _target: None)
    monkeypatch.setattr(forge_code_store, "append_agent_turn", lambda *_args, **_kwargs: None)

    def _configure(app: web.Application) -> None:
        proc = _RunningProcess()
        recording = asyncio.ensure_future(
            evolve_agent_runtime._drain_and_record(
                proc,
                transcript,
                repo,
                "missing-conversation",
                "test-model",
                forge_code_git.snapshot(repo),
                app,
                run_id="run-store-failure",
            )
        )
        app[APP_EVOLVE_AGENT_TASK] = proc
        app[APP_EVOLVE_AGENT_DRAIN] = {
            "generation": 7,
            "run_id": "run-store-failure",
            "task": recording,
        }
        app[APP_EVOLVE_AGENT_SESSION] = {
            "generation": 7,
            "run_id": "run-store-failure",
            "transcript": str(transcript),
            "proc": proc,
        }

    async def _body(client: TestClient) -> None:
        await asyncio.sleep(0)
        status = await (await client.get("/api/evolve/agent/status")).json()
        assert status["persistence_confirmed"] is False
        assert status["persistence_state"] == "failed"
        stopped_response = await client.post(
            "/api/evolve/agent/stop",
            json={"run_id": "run-store-failure"},
        )
        stopped = await stopped_response.json()
        assert stopped_response.status == 200
        assert stopped["termination_confirmed"] is True
        assert stopped["persistence_confirmed"] is False
        assert stopped["persistence_state"] == "failed"
        stream = await client.get("/api/evolve/agent/stream?run_id=run-store-failure")
        frames = [
            json.loads(line.removeprefix("data: "))
            for line in (await stream.text()).splitlines()
            if line.startswith("data: ")
        ]
        done = next(frame for frame in frames if frame["type"] == "done")
        assert done["persistence_confirmed"] is False
        assert done["outcome"] == "persistence_failed"
        assert done["ok"] is False

    _drive(repo, _body, configure=_configure)


def test_a_store_that_claims_a_write_it_did_not_make_is_not_confirmed(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    """`persistence_confirmed` must come from the store, not from the writer's word.

    The flag used to be assigned ``True`` because execution reached the line.
    ``91442cea`` replaced that with a real store read, but nothing pinned it:
    measured by reverting line 612 of ``evolve_agent_runtime.py`` back to
    ``persistence_confirmed = True``, all 52 tests across the four
    evolve-agent modules still passed. A correct fix that no test protects is
    one careless edit from being undone silently.

    So this reproduces the only shape that separates the two implementations:
    ``append_agent_turn`` RETURNS a conversation -- reporting success, so the
    ``persisted is None`` branch never fires -- while nothing reaches disk. The
    self-certifying version calls that a confirmed save. A store read cannot.
    """

    repo = _new_repo(tmp_path)
    conversation = forge_code_store.new_conversation(repo)
    transcript = repo / "phantom-write.txt"
    transcript.write_text("runner output\n", encoding="utf-8")

    real_append = forge_code_store.append_agent_turn

    def _claims_success_without_writing(*args: Any, **kwargs: Any) -> dict[str, Any]:
        # Shaped exactly like a real return value, including the identity
        # `_agent_turn_is_in_store` matches on -- so the only thing that can
        # tell it apart from a genuine write is going back to the disk.
        return {
            "id": conversation["id"],
            "turns": [
                {
                    "role": "agent",
                    "ts": "2026-07-28T23:59:59.123456+00:00",
                    "run_id": kwargs.get("run_id") or "run-phantom",
                }
            ],
        }

    monkeypatch.setattr(forge_code_store, "append_agent_turn", _claims_success_without_writing)

    class _EmptyStdout:
        async def readline(self) -> bytes:
            return b""

    class _FinishedProcess:
        returncode = 0
        stdout = _EmptyStdout()

        async def wait(self) -> int:
            return 0

    async def _run() -> None:
        result = await evolve_agent_runtime._drain_and_record(
            _FinishedProcess(),
            transcript,
            repo,
            conversation["id"],
            "test-model",
            forge_code_git.snapshot(repo),
            web.Application(),
            run_id="run-phantom",
        )
        assert result["persistence_confirmed"] is False, (
            "a turn that never reached the store was reported as saved"
        )
        # And the run is reported as failed rather than quietly succeeding.
        assert result["ok"] is False

        # The other direction, through the same code path: a REAL write is
        # still confirmed, so the check cannot pass by refusing everything.
        monkeypatch.setattr(forge_code_store, "append_agent_turn", real_append)
        genuine = await evolve_agent_runtime._drain_and_record(
            _FinishedProcess(),
            transcript,
            repo,
            conversation["id"],
            "test-model",
            forge_code_git.snapshot(repo),
            web.Application(),
            run_id="run-genuine",
        )
        assert genuine["persistence_confirmed"] is True

    asyncio.run(_run())
