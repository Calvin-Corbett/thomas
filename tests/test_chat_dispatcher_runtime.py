from __future__ import annotations

from pathlib import Path

from thomas.agent import chat_dispatcher as mod
from thomas.core import task_bot_runtime


def _write_workboard(tmp_path: Path) -> Path:
    workboard = tmp_path / "WORKBOARD.md"
    workboard.write_text(
        "# Thomas Workboard\n\n" "## Up For Grabs\n\n" "- none\n\n" "## Agent Message Traffic\n\n" "- none\n",
        encoding="utf-8",
    )
    return workboard


def test_dispatch_creates_runtime_execution_and_queues_task(tmp_path, monkeypatch):
    workboard = _write_workboard(tmp_path)
    monkeypatch.setattr(mod, "_make_task_id", lambda _text: "chat-test-123")
    monkeypatch.setattr(mod, "_send_dispatch_message", lambda *args, **kwargs: True)

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
    assert record["scope"] == ["thomas/server/routes"]
    assert "task_id=chat-test-123" in text
