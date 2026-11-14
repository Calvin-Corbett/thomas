"""A configured Work job can finish without padding its conversation to four turns."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.routes.work import register_work_routes
from thomas.work import WorkConflictError, WorkStore


def _configured_store(root: Path, *, turns: int, marker: object = 2) -> WorkStore:
    store = WorkStore(root)
    store.create_app({"id": "dinner", "name": "Dinner", "goal": ""})
    for turn in range(turns):
        store.append_onboarding_message("dinner", {"role": "user", "text": f"Dinner details {turn}"})
        store.append_onboarding_message("dinner", {"role": "thomas", "text": f"Recorded details {turn}"})
    store.update_onboarding(
        "dinner",
        {"phase": "workflow_mapping", "fields": {"confirmed_goal": "Plan dinner for six on Saturday"}},
    )
    store.update_onboarding(
        "dinner",
        {
            "phase": "workflow_configuration",
            "fields": {
                "workflow_count": 1,
                "selected_workflow": "Dinner plan",
                "selected_workflow_id": "dinner-plan",
                "selected_workflow_user_turn": marker,
                "selected_workflow_configured": True,
            },
        },
    )
    return store


@pytest.mark.parametrize("turns, marker", [(2, 1), (2, 2), (4, 4)])
def test_a_configured_short_conversation_reaches_ready(tmp_path: Path, turns: int, marker: int) -> None:
    async def scenario() -> None:
        store = _configured_store(tmp_path, turns=turns, marker=marker)
        app = web.Application()
        register_work_routes(app, require_api_access=lambda request: None, store=store)
        async with TestClient(TestServer(app)) as client:
            response = await client.patch(
                "/api/work/apps/dinner/onboarding",
                json={"phase": "ready", "state": "ready", "next_prompt": ""},
            )
            body = await response.json()
            assert response.status == 200, body
            assert body["onboarding"]["state"] == "ready"
            assert body["onboarding"]["phase"] == "ready"
            assert store.get_app("dinner")["status"] == "active"

    asyncio.run(scenario())


@pytest.mark.parametrize("marker", [None, 0, -1, True, "2", 1.5, 3])
def test_ready_still_requires_a_selection_at_a_real_user_turn(tmp_path: Path, marker: object) -> None:
    store = _configured_store(tmp_path, turns=2, marker=marker)
    with pytest.raises(WorkConflictError, match="selection at a recorded user turn"):
        store.update_onboarding("dinner", {"phase": "ready", "state": "ready"})
    assert store.get_app("dinner")["onboarding"]["state"] == "collecting"


def test_short_onboarding_still_requires_configuration(tmp_path: Path) -> None:
    store = _configured_store(tmp_path, turns=2)
    with pytest.raises(WorkConflictError, match="answered configuration question"):
        store.update_onboarding("dinner", {"state": "ready", "fields": {"selected_workflow_configured": False}})
    assert store.get_app("dinner")["status"] == "onboarding"
