"""Writable Build helpers have durable server-owned lifecycle receipts."""

from __future__ import annotations

import asyncio
import hashlib

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.forge.anvil.run_channel_client import RunChannelClient
from thomas.server.praxis.recovery import PraxisRunJournal, recover_channel
from thomas.server.praxis.run_channel import RunChannel
from thomas.server.routes.praxis_run_routes import register_praxis_run_routes


async def _unused_runner(*_args):
    raise AssertionError("External builders must never execute the read-only server runner")
    yield


@pytest.mark.asyncio
async def test_external_builder_requires_matching_integrated_bytes_and_survives_restart(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    journal = PraxisRunJournal(tmp_path / "runs.sqlite3")
    channel = RunChannel("run", _unused_runner, journal=journal, project_root=project)
    admitted = await channel.admit_external_builder(
        plan_id="team:0",
        title="Write file",
        brief="Create a bounded file",
        path="output.txt",
    )
    child_id = admitted["agent_id"]
    assert journal.load("run")["children"][0]["execution_origin"] == "external_builder"
    assert channel.status()["agents"][0]["execution_origin"] == "external_builder"
    await channel.report_external_builder(child_id, {"type": "started"})
    (project / "output.txt").write_text("built\n", encoding="utf-8")
    with pytest.raises(ValueError, match="did not match disk"):
        await channel.report_external_builder(child_id, {"type": "integrated", "fingerprint": "0" * 64})
    assert channel.status()["agents"][0]["state"] == "running"
    content = (project / "output.txt").read_bytes()
    digest = f"sha256:{hashlib.sha256(content).hexdigest()}:{len(content)}"
    assert (
        await channel.report_external_builder(
            child_id,
            {"type": "integrated", "fingerprint": digest},
        )
    )["state"] == "completed"
    with pytest.raises(ValueError, match="already settled"):
        await channel.report_external_builder(child_id, {"type": "failed", "error": "late"})
    restored = recover_channel(journal, "run", _unused_runner)
    await asyncio.gather(*restored._tasks.values())
    assert restored.status()["agents"][0]["state"] == "completed"
    assert restored.status()["agents"][0]["execution_origin"] == "external_builder"
    await channel.close()
    await restored.close()


@pytest.mark.asyncio
async def test_external_builder_interrupt_does_not_restart_as_read_only(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    journal = PraxisRunJournal(tmp_path / "runs.sqlite3")
    channel = RunChannel("run", _unused_runner, journal=journal, project_root=project)
    handle = await channel.admit_external_builder(
        plan_id="team:0",
        title="Write file",
        brief="Create a bounded file",
        path="output.txt",
    )
    await channel.report_external_builder(handle["agent_id"], {"type": "started"})
    recovered = recover_channel(journal, "run", _unused_runner)
    await asyncio.gather(*recovered._tasks.values())
    row = recovered.status()["agents"][0]
    assert row["state"] == "interrupted"
    assert row["events"][-1]["error"] == "builder process interrupted; rerun Build to resume"
    assert journal.interrupted_runs() == []
    await channel.suspend()
    await recovered.close()


@pytest.mark.asyncio
async def test_external_builder_explicit_stop_is_terminal(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    journal = PraxisRunJournal(tmp_path / "runs.sqlite3")
    channel = RunChannel("run", _unused_runner, journal=journal, project_root=project)
    first = await channel.admit_external_builder(
        plan_id="team:0",
        title="First",
        brief="Create one file",
        path="first.txt",
    )
    second = await channel.admit_external_builder(
        plan_id="team:1",
        title="Second",
        brief="Create another file",
        path="second.txt",
    )
    await channel.report_external_builder(first["agent_id"], {"type": "started"})
    with pytest.raises(ValueError, match="Stop the Build run"):
        await channel.stop_child(second["agent_id"])
    await channel.close()
    assert {row["state"] for row in journal.load("run")["children"]} == {"stopped"}
    assert journal.interrupted_runs() == []


@pytest.mark.asyncio
async def test_authenticated_loopback_builder_reports_reach_the_same_run(tmp_path, monkeypatch):
    from thomas.server.praxis import startup

    monkeypatch.setattr(startup, "user_praxis_root", lambda: tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    app = web.Application()
    registry = register_praxis_run_routes(app)
    journal = PraxisRunJournal(tmp_path / "runs.sqlite3")
    channel = registry.open("run", _unused_runner, journal=journal, project_root=project)
    async with TestClient(TestServer(app, host="127.0.0.1")) as http:
        client = RunChannelClient(base_url=str(http.make_url("/")), run_id="run", token=channel.token)
        admission = await client.call(
            "admit_builder",
            {
                "plan_id": "team:0",
                "title": "Build one file",
                "brief": "Make the assigned file",
                "path": "output.txt",
            },
        )
        child_id = admission["agent"]["agent_id"]
        await client.call("report_builder", {"agent_id": child_id, "event": {"type": "started"}})
        (project / "output.txt").write_text("built\n", encoding="utf-8")
        content = (project / "output.txt").read_bytes()
        digest = f"sha256:{hashlib.sha256(content).hexdigest()}:{len(content)}"
        await client.call(
            "report_builder",
            {
                "agent_id": child_id,
                "event": {"type": "integrated", "fingerprint": digest},
            },
        )
        row = (await client.call("status", {"agent_ids": [child_id]}))["agents"][0]
        assert row["state"] == "completed"
        assert row["execution_origin"] == "external_builder"
        assert row["events"][-1]["fingerprint"] == digest
        denied = await http.post("/api/praxis/run/run/status", json={})
        assert denied.status == 404
