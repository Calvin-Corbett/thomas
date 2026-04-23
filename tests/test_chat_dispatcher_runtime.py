from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from thomas.agent import chat_dispatcher as mod
from thomas.core import task_bot_runtime
from thomas.server.routes.chat_aiohttp_streaming import _should_start_task_manager_dispatch


def _write_workboard(tmp_path: Path) -> Path:
    workboard = tmp_path / "WORKBOARD.md"
    workboard.write_text(
        "# Thomas Workboard\n\n## Up For Grabs\n\n- none\n\n## Agent Message Traffic\n\n- none\n",
        encoding="utf-8",
    )
    return workboard


def test_dispatch_creates_runtime_execution_and_queues_task(tmp_path, monkeypatch):
    workboard = _write_workboard(tmp_path)
    monkeypatch.setattr(mod, "_make_task_id", lambda _text: "chat-test-123")
    monkeypatch.setattr(mod, "_send_dispatch_message", lambda *args, **kwargs: True)
    monkeypatch.setattr(mod, "_trigger_immediate_task_assignment", lambda **kwargs: (False, {}, None))

    result = mod.dispatch_to_workboard(
        "Investigate the runtime visibility bug",
        "session-123",
        scope="thomas/server/routes",
        workboard_path=workboard,
        repo_root=tmp_path,
    )

    record = task_bot_runtime.find_by_task_id("chat-test-123", repo_root=tmp_path)
    text = workboard.read_text(encoding="utf-8")

    assert result.ok is True
    assert result.task_id == "chat-test-123"
    assert result.execution_id
    assert record is not None
    assert record["execution_id"] == result.execution_id
    assert record["state"] == "queued"
    assert record["conversation_id"] == "session-123"
    assert record["request_text"] == "Investigate the runtime visibility bug"
    assert record["scope"] == ["thomas/server/routes"]
    assert "task_id=chat-test-123" in text
    assert "reported_by=chat_dispatch" in text


def test_dispatch_bootstraps_empty_workboard(tmp_path, monkeypatch):
    workboard = tmp_path / "WORKBOARD.md"
    workboard.write_text("", encoding="utf-8")
    monkeypatch.setattr(mod, "_make_task_id", lambda _text: "chat-test-bootstrap")
    monkeypatch.setattr(mod, "_send_dispatch_message", lambda *args, **kwargs: True)
    monkeypatch.setattr(mod, "_trigger_immediate_task_assignment", lambda **kwargs: (False, {}, None))

    result = mod.dispatch_to_workboard(
        "Investigate background dispatch visibility",
        "session-bootstrap",
        workboard_path=workboard,
        repo_root=tmp_path,
    )

    text = workboard.read_text(encoding="utf-8")

    assert result.ok is True
    assert "## Agent Claims" in text
    assert "## Active Tasks" in text
    assert "## Up For Grabs" in text
    assert "## Issues / Blockers" in text
    assert "## Agent Message Traffic" in text
    assert "task_id=chat-test-bootstrap" in text
    assert "scope=chat/chat-test-bootstrap;" in text


def test_dispatch_uses_task_specific_chat_scope_by_default(tmp_path, monkeypatch):
    workboard = _write_workboard(tmp_path)
    monkeypatch.setattr(mod, "_make_task_id", lambda _text: "chat-test-scope")
    monkeypatch.setattr(mod, "_send_dispatch_message", lambda *args, **kwargs: True)
    monkeypatch.setattr(mod, "_trigger_immediate_task_assignment", lambda **kwargs: (False, {}, None))

    result = mod.dispatch_to_workboard(
        "Investigate task-manager worker fanout",
        "session-scope",
        workboard_path=workboard,
        repo_root=tmp_path,
    )

    record = task_bot_runtime.find_by_task_id("chat-test-scope", repo_root=tmp_path)
    text = workboard.read_text(encoding="utf-8")

    assert result.ok is True
    assert record is not None
    assert record["scope"] == ["chat/chat-test-scope"]
    assert "scope=chat/chat-test-scope;" in text


def test_dispatch_preserves_multiple_queued_tasks_on_same_workboard(tmp_path, monkeypatch):
    workboard = _write_workboard(tmp_path)
    task_ids = iter(["chat-test-1", "chat-test-2"])
    monkeypatch.setattr(mod, "_make_task_id", lambda _text: next(task_ids))
    monkeypatch.setattr(mod, "_send_dispatch_message", lambda *args, **kwargs: True)
    monkeypatch.setattr(mod, "_trigger_immediate_task_assignment", lambda **kwargs: (False, {}, None))

    first = mod.dispatch_to_workboard(
        "Investigate routing latency",
        "session-1",
        scope="chat",
        workboard_path=workboard,
        repo_root=tmp_path,
    )
    second = mod.dispatch_to_workboard(
        "Investigate queue visibility",
        "session-2",
        scope="chat",
        workboard_path=workboard,
        repo_root=tmp_path,
    )

    text = workboard.read_text(encoding="utf-8")

    assert first.ok is True
    assert second.ok is True
    assert "task_id=chat-test-1;" in text
    assert "task_id=chat-test-2;" in text


def test_dispatch_immediately_marks_claimed_when_background_worker_is_available(tmp_path, monkeypatch):
    workboard = _write_workboard(tmp_path)
    monkeypatch.setattr(mod, "_make_task_id", lambda _text: "chat-test-claimed")
    monkeypatch.setattr(mod, "_send_dispatch_message", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        mod,
        "_trigger_immediate_task_assignment",
        lambda **kwargs: (
            True,
            {"assignments": [{"task_id": "chat-test-claimed", "agent": "thomas-chat-worker"}]},
            None,
        ),
    )

    result = mod.dispatch_to_workboard(
        "Use your tools to create the file D:\\Desktop\\claim-test.txt containing exactly CLAIM_OK",
        "session-claimed",
        scope="chat",
        workboard_path=workboard,
        repo_root=tmp_path,
    )

    record = task_bot_runtime.find_by_task_id("chat-test-claimed", repo_root=tmp_path)

    assert result.ok is True
    assert record is not None
    assert record["state"] == "claimed"
    assert record["claimed_owner"] == "thomas-chat-worker"


def test_select_available_chat_worker_prefers_idle_pool_member(tmp_path, monkeypatch):
    workboard = _write_workboard(tmp_path)
    workboard.write_text(
        "# Thomas Workboard\n\n"
        "## Active Tasks\n\n"
        "- task_id=chat-busy-1; agent=thomas-chat-worker; scope=chat; summary=Busy task; status=in_progress\n"
        "- task_id=chat-done-1; agent=thomas-chat-worker-2; scope=chat; summary=Done task; status=done\n\n"
        "## Up For Grabs\n\n- none\n\n"
        "## Agent Message Traffic\n\n- none\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("THOMAS_CHAT_WORKER_POOL_SIZE", "3")

    worker, payload = mod._select_available_chat_worker(workboard)

    assert worker == "thomas-chat-worker-2"
    assert payload["idle_workers"] == ["thomas-chat-worker-2", "thomas-chat-worker-3"]


def test_actionable_chat_dispatches_without_force_flag():
    decision = SimpleNamespace(action="dispatch")
    assert _should_start_task_manager_dispatch(decision, {}) is True


def test_force_inline_cannot_bypass_task_manager_dispatch():
    decision = SimpleNamespace(action="dispatch")
    assert _should_start_task_manager_dispatch(decision, {"force_inline": True}) is True


def test_send_dispatch_message_uses_public_workboard_message_api(tmp_path, monkeypatch):
    workboard = _write_workboard(tmp_path)
    calls = []

    class _WorkboardMessageStub:
        @staticmethod
        def send_message(workboard_path, **kwargs):  # noqa: ANN001
            calls.append((workboard_path, dict(kwargs)))
            return True, {"message": kwargs}

    monkeypatch.setattr(mod, "_import_workboard_message", lambda: _WorkboardMessageStub)

    ok = mod._send_dispatch_message("chat-test-123", "Investigate the runtime visibility bug", workboard_path=workboard)

    assert ok is True
    assert len(calls) == 1
    workboard_path, payload = calls[0]
    assert workboard_path == workboard
    assert payload["sender"] == mod.CHAT_DISPATCHER_AGENT
    assert payload["recipient"] == mod.TASK_MANAGER_AGENT
    assert payload["task_id"] == "chat-test-123"
    assert payload["require_claims_to_have_active_task"] is False


def test_task_manager_dispatch_ready_requires_recent_worker_signal(tmp_path, monkeypatch):
    workboard = _write_workboard(tmp_path)

    class _WorkboardMessageStub:
        @staticmethod
        def send_message(*args, **kwargs):  # noqa: ANN002, ANN003
            return True, {}

        @staticmethod
        def list_messages(_workboard_path):  # noqa: ANN001
            return True, {
                "messages": [
                    {
                        "from": "note-worker-1",
                        "to": "thomas",
                        "updated_at": "3026-04-05T00:00:00+00:00",
                    }
                ]
            }

    monkeypatch.setattr(mod, "_import_workboard_message", lambda: _WorkboardMessageStub)

    assert mod.is_task_manager_dispatch_ready(workboard_path=workboard) is True


def test_task_manager_dispatch_ready_accepts_live_worker_processes_without_loop(tmp_path, monkeypatch):
    workboard = _write_workboard(tmp_path)
    monkeypatch.setattr(mod, "_chat_worker_agents", lambda: ["thomas-chat-worker", "thomas-chat-worker-2"])
    monkeypatch.setattr(mod, "_find_chat_worker_pids", lambda agent: [222] if agent == "thomas-chat-worker-2" else [])

    assert mod.is_task_manager_dispatch_ready(workboard_path=workboard) is True


def test_task_manager_dispatch_ready_ignores_benchmark_single_agent_mode(tmp_path, monkeypatch):
    workboard = _write_workboard(tmp_path)
    monkeypatch.setenv("THOMAS_BENCHMARK_SINGLE_AGENT", "1")
    monkeypatch.setattr(mod, "_chat_worker_agents", lambda: ["thomas-chat-worker"])
    monkeypatch.setattr(mod, "_find_chat_worker_pids", lambda agent: [222])

    assert mod.is_task_manager_dispatch_ready(workboard_path=workboard) is True


def test_dispatch_to_workboard_ignores_benchmark_single_agent_mode(tmp_path, monkeypatch):
    workboard = _write_workboard(tmp_path)
    monkeypatch.setenv("THOMAS_BENCHMARK_SINGLE_AGENT", "1")
    monkeypatch.setattr(mod, "_make_task_id", lambda _text: "chat-test-benchmark")
    monkeypatch.setattr(mod, "_send_dispatch_message", lambda *args, **kwargs: True)
    monkeypatch.setattr(mod, "_trigger_immediate_task_assignment", lambda **kwargs: (False, {}, None))

    result = mod.dispatch_to_workboard(
        "Investigate isolation benchmark leak",
        "session-benchmark",
        workboard_path=workboard,
        repo_root=tmp_path,
    )

    record = task_bot_runtime.find_by_task_id("chat-test-benchmark", repo_root=tmp_path)

    assert result.ok is True
    assert result.task_id == "chat-test-benchmark"
    assert result.execution_id
    assert record is not None
    assert record["state"] == "queued"


def test_dispatch_ignores_benchmark_repo_root_and_workboard_overrides(tmp_path, monkeypatch):
    workboard = _write_workboard(tmp_path)
    diverted_root = tmp_path / "diverted-root"
    diverted_root.mkdir(parents=True, exist_ok=True)
    diverted_workboard = diverted_root / "WORKBOARD.md"
    diverted_workboard.write_text("# diverted\n", encoding="utf-8")
    monkeypatch.setenv("THOMAS_BENCHMARK_REPO_ROOT", str(diverted_root))
    monkeypatch.setenv("THOMAS_BENCHMARK_WORKBOARD_PATH", str(diverted_workboard))
    monkeypatch.setattr(mod, "_make_task_id", lambda _text: "chat-test-production-path")
    monkeypatch.setattr(mod, "_send_dispatch_message", lambda *args, **kwargs: True)
    monkeypatch.setattr(mod, "_trigger_immediate_task_assignment", lambda **kwargs: (False, {}, None))

    result = mod.dispatch_to_workboard(
        "Investigate production dispatch path",
        "session-production-path",
        workboard_path=workboard,
        repo_root=tmp_path,
    )

    live_record = task_bot_runtime.find_by_task_id("chat-test-production-path", repo_root=tmp_path)
    diverted_record = task_bot_runtime.find_by_task_id("chat-test-production-path", repo_root=diverted_root)

    assert result.ok is True
    assert live_record is not None
    assert diverted_record is None
    assert "task_id=chat-test-production-path" in workboard.read_text(encoding="utf-8")
    assert "task_id=chat-test-production-path" not in diverted_workboard.read_text(encoding="utf-8")


def test_dispatch_to_workboard_records_production_intent_and_policy(tmp_path, monkeypatch):
    workboard = _write_workboard(tmp_path)
    monkeypatch.setattr(mod, "_make_task_id", lambda _text: "chat-test-production-mode")
    monkeypatch.setattr(mod, "_send_dispatch_message", lambda *args, **kwargs: True)
    monkeypatch.setattr(mod, "_trigger_immediate_task_assignment", lambda **kwargs: (False, {}, None))

    result = mod.dispatch_to_workboard(
        "Build the production-mode task pipeline.",
        "session-production-mode",
        intent="production_task",
        task_policy={"capability_class": "repo_edit_private_checkpointable", "policy_source": "production_mode"},
        workboard_path=workboard,
        repo_root=tmp_path,
    )

    record = task_bot_runtime.find_by_task_id("chat-test-production-mode", repo_root=tmp_path)

    assert result.ok is True
    assert record is not None
    assert record["execution_intent"] == "production_task"
    assert record["task_policy"]["capability_class"] == "repo_edit_private_checkpointable"
