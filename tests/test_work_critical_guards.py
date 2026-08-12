from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.routes.work import register_work_routes
from thomas.server.tool_extensions import _register_work_google_drive
from thomas.server.work_connector_registry import (
    WorkExecutionBinding,
    bind_work_connector_tools,
)
from thomas.server.work_google_connector import GoogleWorkspaceConnectorExecutor
from thomas.tools.google_drive import get_tools
from thomas.tools.registry import ToolRegistry
from thomas.work import WorkStore


def _mission_store(root: Path) -> WorkStore:
    store = WorkStore(root)
    store.create_app({"id": "ops", "name": "Ops", "goal": "Operate"})
    store.create_job("ops", {"id": "daily", "name": "Daily", "goal": "Run daily"})
    for index in (1, 2):
        automation = store.create_automation(
            "ops",
            "daily",
            {"id": f"auto-{index}", "name": f"Auto {index}", "trigger": {"type": "manual"}},
        )
        store.mark_automation_delegated("ops", "daily", automation["id"], mission_job_id=f"mission-{index}")
    return store


async def _route_client(store: WorkStore, canceller=None) -> TestClient:
    app = web.Application()
    register_work_routes(
        app,
        require_api_access=lambda request: None,
        store=store,
        mission_canceller=canceller,
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


@pytest.mark.parametrize(
    ("method", "suffix", "expected_status"),
    (("post", "/pause", "paused"), ("post", "/archive", "archived"), ("delete", "", "archived")),
)
@pytest.mark.asyncio
async def test_job_pause_and_archive_cancel_every_mission_first(
    tmp_path: Path,
    method: str,
    suffix: str,
    expected_status: str,
) -> None:
    store = _mission_store(tmp_path)
    cancelled: list[str] = []

    async def canceller(mission_id: str) -> dict[str, str]:
        cancelled.append(mission_id)
        return {"id": mission_id, "status": "cancelled"}

    client = await _route_client(store, canceller)
    try:
        response = await getattr(client, method)(f"/api/work/apps/ops/jobs/daily{suffix}")
        assert response.status == 200
        assert cancelled == ["mission-1", "mission-2"]
        assert store.get_job("ops", "daily")["status"] == expected_status
        assert {row["delegation"]["mission_status"] for row in store.list_automations("ops", "daily")} == {"cancelled"}
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_job_pause_fails_closed_when_any_cancellation_is_unproven(tmp_path: Path) -> None:
    store = _mission_store(tmp_path)

    async def canceller(mission_id: str) -> dict[str, str]:
        return {
            "id": mission_id,
            "status": "cancelled" if mission_id == "mission-1" else "running",
        }

    client = await _route_client(store, canceller)
    try:
        response = await client.post("/api/work/apps/ops/jobs/daily/pause")
        assert response.status == 503
        assert store.get_job("ops", "daily")["status"] == "active"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_armed_event_mission_is_cancelled_but_idle_armed_event_needs_no_canceller(
    tmp_path: Path,
) -> None:
    store = WorkStore(tmp_path)
    store.create_app({"id": "ops", "name": "Ops", "goal": "Operate"})
    store.create_job("ops", {"id": "events", "name": "Events", "goal": "Handle events"})
    for automation_id in ("active-event", "idle-event"):
        store.create_automation(
            "ops",
            "events",
            {
                "id": automation_id,
                "name": automation_id,
                "trigger": {"type": "event", "event_name": f"{automation_id}-received"},
            },
        )
        store.arm_event_automation("ops", "events", automation_id)
    store.record_event_delegation("ops", "events", "active-event", mission_job_id="mission-event")
    cancelled: list[str] = []

    async def canceller(mission_id: str) -> dict[str, str]:
        cancelled.append(mission_id)
        return {"id": mission_id, "status": "cancelled"}

    client = await _route_client(store, canceller)
    try:
        response = await client.post("/api/work/apps/ops/jobs/events/pause")
        assert response.status == 200
        assert cancelled == ["mission-event"]
    finally:
        await client.close()


def test_drive_tools_register_and_fail_closed_outside_work() -> None:
    registry = ToolRegistry()
    _register_work_google_drive(registry)
    names = {tool.name for tool in registry.list_tools()}
    assert names == {"drive.list", "drive.get", "drive.search", "drive.create_folder", "drive.share"}
    result = asyncio.run(registry.execute("drive.list", {}))
    assert not result.ok and "require a Work job" in str(result.error)


@pytest.mark.parametrize(
    ("tool_name", "args", "operation"),
    (
        ("drive.list", {"max_results": 7}, "list_files"),
        ("drive.get", {"file_id": "file-1"}, "get_file"),
        ("drive.search", {"query": "invoice"}, "search_files"),
        ("drive.create_folder", {"name": "Reports"}, "create_folder"),
        ("drive.share", {"file_id": "file-1", "email": "owner@example.com"}, "share_file"),
    ),
)
def test_google_executor_maps_job_bound_drive_operations(tool_name: str, args: dict[str, Any], operation: str) -> None:
    observed: list[dict[str, Any]] = []

    class FakeIntegration:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def connect(self) -> None:
            pass

        async def execute(self, **kwargs: Any) -> dict[str, Any]:
            observed.append(kwargs)
            return {"ok": True}

        async def disconnect(self) -> None:
            pass

    binding = WorkExecutionBinding(
        "binding", "drive-owner", "google_drive", frozenset({"read", "write"}), "secret:drive", "active"
    )
    secret = json.dumps({"tokens": {"access_token": "ACCESS"}})
    result = asyncio.run(GoogleWorkspaceConnectorExecutor(FakeIntegration).execute(binding, tool_name, args, secret))
    assert result.ok
    assert observed[0]["service"] == "drive"
    assert observed[0]["operation"] == operation
    assert "ACCESS" not in json.dumps(result.data)


def test_drive_calls_never_fall_through_the_unscoped_base_registry(tmp_path: Path) -> None:
    store = WorkStore(tmp_path)
    store.create_app({"id": "files", "name": "Files", "goal": "Organize files"})
    store.create_job("files", {"id": "owner", "name": "Owner", "goal": "Organize files"})
    store.create_account(
        {
            "id": "drive-owner",
            "provider": "google_drive",
            "label": "Owner Drive",
            "identity": "owner@example.com",
            "credential_ref": "secret:drive-owner",
        }
    )
    store.bind_account("files", "owner", {"account_id": "drive-owner", "scopes": ["read"]})
    registry = ToolRegistry()
    for tool in get_tools():
        registry.register(tool)

    class Secrets:
        def get(self, key: str) -> str:
            return "BOUND_TOKEN" if key == "secret:drive-owner" else ""

    class Executor:
        async def execute(self, binding, tool_name, args, credential_secret):
            assert credential_secret == "BOUND_TOKEN"
            assert binding.account_id == "drive-owner"
            assert "work_account_id" not in args
            from thomas.tools.base import ToolResult

            return ToolResult(ok=True, data={"tool": tool_name})

    tools = bind_work_connector_tools(
        registry, store=store, secret_store=Secrets(), context_id="files:owner", executor=Executor()
    )
    result = asyncio.run(tools.execute("functions.drive.list", {"work_account_id": "drive-owner"}))
    assert result.ok and result.data == {"tool": "drive.list"}
