from __future__ import annotations

from thomas.core import task_bot_runtime as mod


def test_runtime_record_roundtrip_and_summary(tmp_path):
    execution = mod.create_execution(
        session_id="sess-1",
        summary="Investigate a failing worker lane",
        task_id="task-1",
        intent="chat_task",
        scope=["thomas/agent"],
        actor="task-manager-agent",
        repo_root=tmp_path,
    )

    execution_id = str(execution["execution_id"])
    mod.update_execution(
        execution_id,
        state="classified",
        progress_summary="Classified for delegation.",
        actor="task-manager-agent",
        repo_root=tmp_path,
    )
    mod.update_execution(
        execution_id,
        state="queued",
        progress_summary="Queued for worker pickup.",
        actor="task-manager-agent",
        repo_root=tmp_path,
    )
    mod.update_execution(
        execution_id,
        state="claimed",
        claimed_owner="zach",
        actor="zach",
        repo_root=tmp_path,
    )
    mod.update_execution(
        execution_id,
        state="executing",
        progress_summary="Worker is running checks.",
        actor="zach",
        repo_root=tmp_path,
    )
    mod.attach_proof(
        execution_id,
        artifacts=[{"kind": "log", "path": "runtime/workers/task-1.log"}],
        summary="Worker log attached.",
        actor="zach",
        repo_root=tmp_path,
    )
    mod.complete_execution(
        execution_id,
        actor="zach",
        summary="Task completed cleanly.",
        repo_root=tmp_path,
    )

    record = mod.get_execution(execution_id, tmp_path)
    summary = mod.read_summary(tmp_path, refresh=True)

    assert record is not None
    assert record["state"] == "completed"
    assert record["proof_status"] == "verified"
    assert record["claimed_owner"] == "zach"
    assert record["proof"]["artifacts"][0]["path"] == "runtime/workers/task-1.log"
    assert summary["execution_count"] == 1
    assert summary["active_count"] == 0
    assert summary["executions"][0]["task_id"] == "task-1"


def test_sync_task_state_maps_workboard_statuses(tmp_path):
    execution = mod.create_execution(
        session_id="sess-2",
        summary="Ship a queued task",
        task_id="task-2",
        actor="task-manager-agent",
        repo_root=tmp_path,
    )
    execution_id = str(execution["execution_id"])

    mod.sync_task_state(
        task_id="task-2",
        workboard_status="claimed",
        actor="worker-1",
        claimed_owner="worker-1",
        repo_root=tmp_path,
    )
    mod.sync_task_state(
        task_id="task-2",
        workboard_status="in_progress",
        actor="worker-1",
        claimed_owner="worker-1",
        repo_root=tmp_path,
    )
    mod.attach_proof(
        execution_id,
        artifacts=[{"kind": "proof", "path": "proof.txt"}],
        actor="worker-1",
        repo_root=tmp_path,
    )
    mod.sync_task_state(
        task_id="task-2",
        workboard_status="review",
        actor="worker-1",
        claimed_owner="worker-1",
        repo_root=tmp_path,
    )
    mod.sync_task_state(
        task_id="task-2",
        workboard_status="done",
        actor="worker-1",
        claimed_owner="worker-1",
        repo_root=tmp_path,
    )

    record = mod.get_execution(execution_id, tmp_path)
    assert record is not None
    assert record["claimed_owner"] == "worker-1"
    assert record["state"] in {"verified", "completed"}
    assert record["proof_status"] in {"attached", "verified"}
