"""A structured Chat code task starts Build and follows its durable result."""

from __future__ import annotations

import asyncio

import pytest

from thomas.core import task_bot_runtime
from thomas.core.send_task_tool import SEND_TASK_TOOL
from thomas.marketplace.specialists.reasoning import _invoke_send_task
from thomas.server.praxis import intake
from thomas.server.praxis.launch import APP_PRAXIS_START_CODE_RUN, APP_PRAXIS_STOP_CODE_RUN
from thomas.server.routes.evolve_agent_project_selection import _chosen_project


@pytest.mark.asyncio
async def test_structured_chat_dispatch_preserves_model_build_choice():
    captured = {}

    async def callback(**kwargs):
        captured.update(kwargs)

    await _invoke_send_task(
        callback,
        title="Thomas OS",
        instructions="Build a kernel",
        surface="task",
        specialist="coding",
        workspace="isolated",
        kind="code",
        needs_build=True,
        project={"mode": "new"},
    )
    assert SEND_TASK_TOOL["function"]["parameters"]["properties"]["needs_build"]["type"] == "boolean"
    assert captured["needs_build"] is True and captured["kind"] == "code"


@pytest.mark.asyncio
async def test_chat_build_task_links_real_conversation_and_waits_for_changed_file(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "coordination_root", lambda *_: tmp_path)
    (tmp_path / "kernel.c").write_text("int main(void) { return 0; }", encoding="utf-8")
    (tmp_path / "build-proof.json").write_text('{"status":"pass"}', encoding="utf-8")
    events = []
    done = asyncio.Event()
    starts = []

    async def emit(event):
        events.append(event)
        if event.get("type") == "delegation_completed":
            done.set()

    async def start(body, *, port):
        starts.append((body, port))
        return 200, {"ok": True, "project_root": str(tmp_path), "conversation_id": "code-one", "run_id": "run-one"}

    def conversation(_project, _cid):
        return {
            "turns": [
                {
                    "role": "agent",
                    "run_id": "run-one",
                    "returncode": 0,
                    "ok": True,
                    "changed_files": ["kernel.c"],
                    "report": {
                        "verifier_receipts": [
                            {
                                "source": "verifier",
                                "status": "pass",
                                "evidence_ref": "build-proof.json",
                                "covered_files": ["kernel.c"],
                            }
                        ],
                        "open_risks": [],
                    },
                }
            ]
        }

    monkeypatch.setattr(intake.forge_code_store, "load_conversation", conversation)
    record = await intake.submit_build_task(
        {APP_PRAXIS_START_CODE_RUN: start},
        session_id="chat-one",
        title="Build Thomas OS",
        instructions="Build a kernel",
        emit_event=emit,
        port=8765,
        kind="code",
    )
    await asyncio.wait_for(done.wait(), 5)
    saved = task_bot_runtime.get_execution(record["execution_id"], tmp_path)
    assert saved["state"] == "completed"
    assert saved["runtime_profile"]["build_conversation_id"] == "code-one"
    assert starts[0][0]["model_id"] == "gpt-5.6-sol"
    assert starts[0][0]["request_id"].startswith("praxis:exec-")
    assert [event["type"] for event in events] == ["delegation_started", "delegation_progress", "delegation_completed"]


@pytest.mark.asyncio
async def test_chat_build_reuses_a_catalogued_project(tmp_path, monkeypatch):
    project = tmp_path / "existing"
    project.mkdir()
    (project / "kernel.c").write_text("int main(void) { return 0; }", encoding="utf-8")
    (project / "build-proof.json").write_text('{"status":"pass"}', encoding="utf-8")
    monkeypatch.setattr(intake, "coordination_root", lambda *_: tmp_path)
    monkeypatch.setattr(intake, "_default_repo_root", lambda: tmp_path)
    monkeypatch.setattr(intake.forge_code_projects, "conversation_roots", lambda _: [project])
    monkeypatch.setattr(intake.forge_code_projects, "thomas_source_repo_root", lambda: None)
    started = asyncio.Event()
    completed = asyncio.Event()
    bodies = []

    async def start(body, *, port):
        bodies.append(body)
        started.set()
        return 200, {
            "ok": True,
            "project_root": str(project),
            "conversation_id": "code-existing",
            "run_id": "run-existing",
        }

    async def emit(event):
        if event.get("type") == "delegation_completed":
            completed.set()

    monkeypatch.setattr(
        intake.forge_code_store,
        "load_conversation",
        lambda _project, _cid: {
            "turns": [
                {
                    "role": "agent",
                    "run_id": "run-existing",
                    "returncode": 0,
                    "ok": True,
                    "changed_files": ["kernel.c"],
                    "report": {
                        "verifier_receipts": [
                            {
                                "source": "verifier",
                                "status": "pass",
                                "evidence_ref": "build-proof.json",
                                "covered_files": ["kernel.c"],
                            }
                        ],
                        "open_risks": [],
                    },
                }
            ]
        },
    )
    await intake.submit_build_task(
        {APP_PRAXIS_START_CODE_RUN: start},
        session_id="chat-existing",
        title="Continue kernel",
        instructions="Add a boot test",
        emit_event=emit,
        port=8765,
        project={"mode": "existing", "id": str(project.resolve())},
    )
    await asyncio.wait_for(started.wait(), 5)
    await asyncio.wait_for(completed.wait(), 5)
    assert bodies[0]["project_root"] == str(project)
    assert bodies[0]["project_choice"] == "picked"
    assert _chosen_project(bodies[0]["project_root"], picked=bodies[0]["project_choice"] == "picked") == str(project)


@pytest.mark.asyncio
async def test_chat_build_changes_without_independent_receipt_do_not_turn_green(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "coordination_root", lambda *_: tmp_path)
    (tmp_path / "kernel.c").write_text("int main(void) { return 0; }", encoding="utf-8")
    done = asyncio.Event()

    async def emit(event):
        if event.get("type") == "delegation_failed":
            done.set()

    async def start(_body, *, port):
        return 200, {"ok": True, "project_root": str(tmp_path), "conversation_id": "code-one", "run_id": "run-one"}

    monkeypatch.setattr(
        intake.forge_code_store,
        "load_conversation",
        lambda *_: {
            "turns": [
                {
                    "role": "agent",
                    "run_id": "run-one",
                    "returncode": 0,
                    "ok": True,
                    "changed_files": ["kernel.c"],
                    "report": {"validations": [{"passed": True}]},
                }
            ]
        },
    )
    record = await intake.submit_build_task(
        {APP_PRAXIS_START_CODE_RUN: start},
        session_id="chat-one",
        title="Build kernel",
        instructions="Build a kernel",
        emit_event=emit,
        port=8765,
    )
    await asyncio.wait_for(done.wait(), 5)
    saved = task_bot_runtime.get_execution(record["execution_id"], tmp_path)
    assert saved["state"] == "failed"
    assert saved["blocker"] == "build_unverified"
    assert saved["proof_status"] != "verified"
    assert saved["runtime_profile"]["build_acceptance"]["state"] == "completed_unverified"
    assert saved["runtime_profile"]["build_run_id"] == "run-one"


@pytest.mark.asyncio
async def test_chat_stop_cancels_the_linked_build_run(tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "coordination_root", lambda *_: tmp_path)
    monkeypatch.setattr(intake.forge_code_store, "load_conversation", lambda *_: {"turns": []})
    linked = asyncio.Event()
    stopped = asyncio.Event()
    stopped_runs = []

    async def emit(event):
        if event.get("type") == "delegation_progress" and event.get("runtime_profile", {}).get("build_run_id"):
            linked.set()
        if event.get("state") == "cancelled":
            stopped.set()

    async def start(_body, *, port):
        return 200, {"ok": True, "project_root": str(tmp_path), "conversation_id": "code-stop", "run_id": "run-stop"}

    async def stop(run_id):
        stopped_runs.append(run_id)
        return True

    record = await intake.submit_build_task(
        {APP_PRAXIS_START_CODE_RUN: start, APP_PRAXIS_STOP_CODE_RUN: stop},
        session_id="chat-stop",
        title="Stop this build",
        instructions="Build a kernel",
        emit_event=emit,
        port=8765,
    )
    await asyncio.wait_for(linked.wait(), 5)
    task_bot_runtime.request_cancel(record["execution_id"], actor="user", repo_root=tmp_path)
    await asyncio.wait_for(stopped.wait(), 5)
    assert stopped_runs == ["run-stop"]
    assert task_bot_runtime.get_execution(record["execution_id"], tmp_path)["state"] == "cancelled"
