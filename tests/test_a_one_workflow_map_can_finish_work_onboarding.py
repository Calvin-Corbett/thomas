"""A Work onboarding whose model mapped ONE workflow must still be finishable.

Measured 2026-08-05 (w2-work-mode, first organic Work test): the model mapped
the dinner-party job into a single "Dinner party plan" workflow, the user
clicked it, and PATCH /api/work/apps/<id>/onboarding answered 409 "Work
onboarding needs a workflow map and explicit workflow selection before
configuration". The model tool contract (work_onboarding_tool.py) allows one
to six workflows; only the store demanded a minimum of three, so a simple job
could never leave the wizard.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.app_keys import APP_SECRETS
from thomas.server.routes.work import register_work_routes
from thomas.server.secrets import SecretStore
from thomas.work import WorkStore


async def _client(root: Path) -> TestClient:
    app = web.Application()
    app[APP_SECRETS] = SecretStore(root / "secrets")
    register_work_routes(app, require_api_access=lambda request: None, store=WorkStore(root / "work"))
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


async def _create_mapped_app(client: TestClient, *, name: str) -> str:
    created = await client.post("/api/work/apps", json={"name": name, "goal": ""})
    assert created.status == 201, await created.text()
    app_id = (await created.json())["app"]["id"]
    mapped = await client.patch(
        f"/api/work/apps/{app_id}/onboarding",
        json={
            "phase": "workflow_mapping",
            "fields": {"confirmed_goal": "Plan a dinner party for six on Saturday"},
        },
    )
    assert mapped.status == 200, await mapped.text()
    return app_id


def test_an_explicitly_selected_single_workflow_reaches_configuration(tmp_path: Path) -> None:
    async def scenario() -> None:
        client = await _client(tmp_path)
        try:
            app_id = await _create_mapped_app(client, name="Plan a small dinner party for 6")
            configured = await client.patch(
                f"/api/work/apps/{app_id}/onboarding",
                json={
                    "phase": "workflow_configuration",
                    "fields": {
                        "workflow_count": 1,
                        "selected_workflow": "Dinner party plan",
                        "selected_workflow_id": "dinner-party-plan",
                    },
                },
            )
            body = await configured.json()
            assert configured.status == 200, body
            assert body["onboarding"]["phase"] == "workflow_configuration"
        finally:
            await client.close()

    asyncio.run(scenario())


def test_a_missing_map_or_selection_still_cannot_reach_configuration(tmp_path: Path) -> None:
    """The requirement that stays is a real map plus an explicit choice."""

    async def scenario() -> None:
        client = await _client(tmp_path)
        try:
            app_id = await _create_mapped_app(client, name="Guarded app")
            no_map = await client.patch(
                f"/api/work/apps/{app_id}/onboarding",
                json={
                    "phase": "workflow_configuration",
                    "fields": {"workflow_count": 0, "selected_workflow": "Dinner party plan"},
                },
            )
            assert no_map.status == 409, await no_map.text()
            no_selection = await client.patch(
                f"/api/work/apps/{app_id}/onboarding",
                json={
                    "phase": "workflow_configuration",
                    "fields": {"workflow_count": 1, "selected_workflow": ""},
                },
            )
            assert no_selection.status == 409, await no_selection.text()
        finally:
            await client.close()

    asyncio.run(scenario())
