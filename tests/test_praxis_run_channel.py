"""Authenticate and exercise the Build-to-server agent channel without a provider.

This is the route test of the Build run channel row, ``thomas.server.rows.praxis``. It imports the route module
``thomas.server.routes.praxis_run_routes`` and not the row, so a change to the row, to ``thomas.server.praxis.startup``
or to the registry in ``thomas.server.praxis.run_channel`` finds it by these names.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core.config import ModelConfig
from thomas.forge.anvil.forge_code_http_stream import line_to_sse_payload
from thomas.forge.anvil.run_channel_client import RunChannelClient
from thomas.forge.anvil.run_channel_tools import StopAgentTool
from thomas.server.app_keys import APP_CONFIG, APP_SECRETS
from thomas.server.praxis import launch as praxis_launch
from thomas.server.praxis import worker as praxis_worker
from thomas.server.praxis.launch import prepare_launch
from thomas.server.routes.evolve_agent_stop import stop_code_run
from thomas.server.routes.praxis_run_routes import register_praxis_run_routes


@pytest.mark.asyncio
async def test_cited_plan_waits_for_dependencies_and_refuses_uncited_work():
    release = asyncio.Event()
    started = []

    async def child(agent_id, _kind, title, _brief):
        started.append(title)
        if title == "First":
            await release.wait()
        yield {"type": "done", "text": agent_id}

    registry = register_praxis_run_routes(web.Application())
    channel = registry.open("planned", child, instructions="Review the boot path")
    units = [
        {
            "id": "first",
            "kind": "review",
            "title": "First",
            "brief": "Read boot code",
            "reason": "independent",
            "acceptance": [{"text": "Boot path reviewed", "cites": "Review the boot path"}],
        },
        {
            "id": "second",
            "kind": "verify",
            "title": "Second",
            "brief": "Check findings",
            "reason": "depends on review",
            "depends_on": ["first"],
            "acceptance": [{"text": "Findings checked", "cites": "Review the boot path"}],
        },
    ]
    with pytest.raises(ValueError, match="uncited_acceptance"):
        await channel.spawn(
            [{**units[0], "acceptance": [{"text": "wrong", "cites": "unrelated"}]}], why_parallel="independent_reads"
        )
    handles = await channel.spawn(units, why_parallel="independent_verification")
    await asyncio.sleep(0)
    assert started == ["First"]
    assert channel.status([handles[1]["agent_id"]])["agents"][0]["state"] == "starting"
    release.set()
    await asyncio.gather(*channel._tasks.values())
    assert started == ["First", "Second"]
    assert all(row["state"] == "completed" for row in channel.status()["agents"])
    await registry.close("planned")


def test_agent_stream_frame_keeps_identity_state_and_text():
    frame = line_to_sse_payload(
        '{"fc":"agent_status","agent_id":"child-1","parent_agent_id":"run-one",'
        '"agent_title":"Review","agent_state":"running","text":"Review: running"}'
    )
    assert frame == {
        "type": "output",
        "kind": "agent_status",
        "text": "Review: running",
        "agent_id": "child-1",
        "parent_agent_id": "run-one",
        "agent_title": "Review",
        "agent_state": "running",
    }


def test_agent_stream_frame_preserves_quota_resume_state():
    frame = line_to_sse_payload(
        '{"fc":"agent_status","agent_id":"child-1","agent_state":"quota_wait","text":"Review: resuming"}'
    )
    assert frame["agent_state"] == "quota_wait"


@pytest.mark.asyncio
async def test_run_token_is_per_run_and_revoked_on_close():
    app = web.Application()
    registry = register_praxis_run_routes(app)

    async def child(_agent_id, _kind, _title, _brief):
        yield {"type": "done", "text": "reviewed"}

    first = registry.open("first", child)
    second = registry.open("second", child)
    async with TestClient(TestServer(app)) as client:
        wrong = await client.post("/api/praxis/run/second/status", json={}, headers={"X-Thomas-Run-Token": first.token})
        assert wrong.status == 404
        good = await client.post(
            "/api/praxis/run/first/spawn",
            json={"units": [{"kind": "review", "title": "Review", "brief": "Inspect project"}]},
            headers={"X-Thomas-Run-Token": first.token},
        )
        assert good.status == 200
        child_id = (await good.json())["agents"][0]["agent_id"]
        wait = await client.post(
            "/api/praxis/run/first/wait",
            json={"agent_ids": [child_id], "timeout": 1},
            headers={"X-Thomas-Run-Token": first.token},
        )
        assert (await wait.json())["agents"][0]["state"] == "completed"
        await registry.close("first")
        revoked = await client.post(
            "/api/praxis/run/first/status", json={}, headers={"X-Thomas-Run-Token": first.token}
        )
        assert revoked.status == 404
        assert registry.get("second", second.token) is second


@pytest.mark.asyncio
async def test_build_lead_can_stop_one_child_without_stopping_others():
    app = web.Application()
    registry = register_praxis_run_routes(app)
    release = asyncio.Event()

    async def child(_agent_id, _kind, _title, _brief):
        yield {"type": "progress", "text": "working"}
        await release.wait()
        yield {"type": "done"}

    channel = registry.open("stoppable", child)
    handles = await channel.spawn(
        [
            {"kind": "review", "title": "First", "brief": "Inspect one"},
            {"kind": "verify", "title": "Second", "brief": "Inspect two"},
        ]
    )
    await asyncio.sleep(0)
    async with TestClient(TestServer(app)) as server:
        client = RunChannelClient(base_url=f"http://127.0.0.1:{server.port}", run_id="stoppable", token=channel.token)
        events = []
        tool = StopAgentTool(client, events.append)
        result = await tool.execute({"agent_id": handles[0]["agent_id"]})
        assert result.ok and result.data["state"] == "stopped"
        assert events[0]["agent_state"] == "stopped"
        assert channel.status([handles[1]["agent_id"]])["agents"][0]["state"] == "running"
    release.set()
    await asyncio.gather(*channel._tasks.values(), return_exceptions=True)
    await registry.close("stoppable")


@pytest.mark.asyncio
async def test_retryable_provider_failure_restarts_child_without_false_completion():
    app = web.Application()
    registry = register_praxis_run_routes(app)
    attempts = 0

    async def child(_agent_id, _kind, _title, _brief):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            yield {"type": "error", "error": "HTTP 429", "retryable": True}
        else:
            yield {"type": "done", "text": "review complete"}

    channel = registry.open("retry", child)
    handle = (await channel.spawn([{"kind": "review", "title": "Review", "brief": "Inspect project"}]))[0]
    await asyncio.sleep(0)
    first = channel.status([handle["agent_id"]])["agents"][0]
    assert first["state"] == "retrying"
    assert first["attempts"] == 1
    assert channel.status()["metrics"]["active_agents"] == 0
    await asyncio.wait_for(channel._tasks[handle["agent_id"]], 3)
    final = channel.status([handle["agent_id"]])["agents"][0]
    assert final["state"] == "completed"
    assert final["attempts"] == 2
    assert attempts == 2
    await registry.close("retry")


@pytest.mark.asyncio
async def test_connection_reset_restarts_child_and_retains_error_event():
    registry = register_praxis_run_routes(web.Application())
    attempts = 0

    async def child(_agent_id, _kind, _title, _brief):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionResetError("socket reset")
        yield {"type": "done"}

    channel = registry.open("reset", child)
    handle = (await channel.spawn([{"kind": "review", "title": "Review", "brief": "Inspect project"}]))[0]
    await asyncio.wait_for(channel._tasks[handle["agent_id"]], 3)
    row = channel.status([handle["agent_id"]])["agents"][0]
    assert row["state"] == "completed" and row["attempts"] == 2
    assert any(event.get("error") == "socket reset" for event in row["events"])
    await registry.close("reset")


@pytest.mark.asyncio
async def test_channel_tracks_hundred_active_children_without_fake_terminals():
    app = web.Application()
    registry = register_praxis_run_routes(app)
    release = asyncio.Event()
    started = 0
    all_started = asyncio.Event()

    async def child(agent_id, _kind, _title, _brief):
        nonlocal started
        started += 1
        if started == 100:
            all_started.set()
        yield {"type": "progress", "text": f"{agent_id} active"}
        await release.wait()
        yield {"type": "done", "text": "evidence recorded"}

    channel = registry.open("hundred", child, instructions="Inspect an independent component")
    handles = await channel.spawn(
        [
            {
                "id": f"review-{index}",
                "kind": "review",
                "title": f"Review {index}",
                "brief": "Inspect an independent component",
                "reason": "Independent source review",
                "acceptance": [{"text": "Component inspected", "cites": "Inspect an independent component"}],
            }
            for index in range(100)
        ],
        why_parallel="independent_reads",
    )
    await asyncio.wait_for(all_started.wait(), 5)
    assert len(channel.status()["agents"]) == 100
    assert all(row["state"] == "running" for row in channel.status()["agents"])
    assert channel.status()["metrics"]["peak"] == 100
    assert len(handles) == 100
    release.set()
    await asyncio.gather(*channel._tasks.values())
    assert all(row["state"] == "completed" for row in channel.status()["agents"])
    await registry.close("hundred")


@pytest.mark.asyncio
async def test_build_launch_mints_runner_token_and_client_uses_loopback(tmp_path, monkeypatch):
    app = web.Application()
    registry = register_praxis_run_routes(app)
    monkeypatch.setattr(praxis_launch, "user_praxis_root", lambda: tmp_path)
    settings = SimpleNamespace(family="gpt", reviewer_model="gpt-5.6-luna", model_id="gpt-5.6-sol")
    async with TestClient(TestServer(app)) as server:
        env = {}
        start_token, opened = prepare_launch(app, settings, tmp_path, "run-one", "request-one", env, server.port)
        assert opened is registry and start_token == env["THOMAS_CODE_START_TOKEN"]
        assert env["THOMAS_CODE_RUN_ID"] == "run-one"
        assert registry._runs["run-one"]._journal.path == tmp_path / "praxis" / "runs.sqlite3"
        client = RunChannelClient(
            base_url=env["THOMAS_RUN_CHANNEL_URL"], run_id="run-one", token=env["THOMAS_RUN_CHANNEL_TOKEN"]
        )
        status = await client.call("status", {})
        assert status["ok"] and status["agents"] == []
        await registry.close("run-one")
        with pytest.raises(ValueError, match="loopback"):
            RunChannelClient(base_url="https://example.com", run_id="run-one", token="bad")


@pytest.mark.asyncio
async def test_internal_build_stop_targets_only_the_linked_run(monkeypatch):
    from thomas.server.routes import evolve_agent_run_state, evolve_agent_runtime

    app = {}
    proc = SimpleNamespace(returncode=None)
    stopped = []

    async def start(_body, _message, *, local_port):
        return SimpleNamespace(status=200, text='{"ok":true}')

    async def terminate(target):
        stopped.append(target)
        return {"termination_confirmed": True}

    monkeypatch.setattr(
        evolve_agent_run_state,
        "slot_for_run_id",
        lambda _app, run_id: {"session": {"proc": proc}} if run_id == "target-run" else None,
    )
    monkeypatch.setattr(evolve_agent_runtime, "_mark_stop_requested", lambda target: stopped.append(("mark", target)))
    monkeypatch.setattr(evolve_agent_runtime, "_terminate_process", terminate)
    praxis_launch.bind_internal_start(app, start, asyncio.Lock(), stop=stop_code_run)
    stop = app[praxis_launch.APP_PRAXIS_STOP_CODE_RUN]
    assert await stop("other-run") is False
    assert stopped == []
    assert await stop("target-run") is True
    assert stopped == [("mark", proc), proc]


@pytest.mark.asyncio
async def test_server_agent_uses_saved_reviewer_model_and_observed_runtime(tmp_path, monkeypatch):
    captured = {}
    from thomas.server import openai_codex_oauth

    monkeypatch.setattr(openai_codex_oauth, "has_openai_codex_token", lambda _store, _profile: True)

    async def fake_worker(_app, **kwargs):
        captured.update(kwargs)
        yield {
            "type": "model_runtime",
            "runtime": {
                "requested": {"profile": "openai_codex", "provider": "openai_codex", "model": "gpt-5.6-luna"},
                "active": {"profile": "openai_codex", "provider": "openai_codex", "model": "gpt-5.6-luna"},
                "attempts": [
                    {
                        "profile": "openai_codex",
                        "provider": "openai_codex",
                        "model": "gpt-5.6-luna",
                        "status": "success",
                    }
                ],
            },
        }
        yield {"type": "done"}

    monkeypatch.setattr(praxis_worker, "run_agent_worker_events", fake_worker)
    app = {
        APP_CONFIG: SimpleNamespace(
            models={"openai_codex": ModelConfig(name="openai_codex", provider="openai_codex", model="gpt-5.6-sol")}
        ),
        APP_SECRETS: object(),
    }
    runner = praxis_worker.build_read_child_runner(app, tmp_path, model_id="gpt-5.6-luna", run_id="run-one")
    events = [event async for event in runner("agent-one", "review", "Review", "Inspect project")]
    assert captured["model_id"] == events[0]["model_used"] == "gpt-5.6-luna"
    assert captured["file_access"] == 0 and captured["can_spawn"] is False
    assert captured["execution_id"] == "run-one:agent-one"
