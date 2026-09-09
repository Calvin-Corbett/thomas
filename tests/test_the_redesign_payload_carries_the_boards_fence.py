"""The Redesign route hands the browser the board's fence with the brief (2026-09-07).

The parser, the brief paragraph and the conversation record each have their
own test; this drives the route itself, so the field the client forwards
(``code_thread.protected_paths``) is asserted where it is produced, against
the repository's real workboard, and the brief the same payload carries names
the fence.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.routes import ui_redesign_runtime as rt
from thomas.server.routes import work_dashboard_runtime as dash

REPO_ROOT = Path(dash.__file__).resolve().parents[3]


def _app(monkeypatch) -> web.Application:
    async def fake_plan(root, profile, body, *, job_context=None):  # noqa: ANN001
        return (
            {
                "instruction": str(body.get("instruction") or ""),
                "targets": list(body.get("targets") or []),
                "layout": [],
                "dashboard": {"changed": 0, "applied": []},
                "theme": {"theme": "nebula", "tokens": {}, "identity": {}, "rejected": []},
                "unsupported": [],
            },
            None,
        )

    # The handler imports the planner from ui_redesign_runtime at call time; patch it there.
    monkeypatch.setattr(rt, "redesign_from_selection", fake_plan)
    app = web.Application()
    dash.register_work_dashboard_routes(
        app,
        guard=lambda request: None,
        work_store=None,
        expected_errors=lambda handler: handler,
        ok=lambda payload=None, **fields: web.json_response({"ok": True, **(payload or {}), **fields}),
        deploy_automation=None,
    )
    return app


def test_the_payload_carries_the_fence_and_the_brief_names_it(monkeypatch) -> None:
    app = _app(monkeypatch)

    async def go():
        async with TestClient(TestServer(app)) as client:
            response = await client.post(
                "/api/ui/redesign",
                json={
                    "profile": "test",
                    "instruction": "make the chip blue",
                    "workspace": "chat",
                    "targets": [
                        {
                            "uiId": "chat.action.activity",
                            "label": "Activity button",
                            "component": "button",
                            "text": "Activity",
                        }
                    ],
                },
            )
            return response.status, await response.json()

    status, payload = asyncio.run(go())
    assert status == 200, payload
    thread = payload["code_thread"]
    expected = dash.fenced_paths_for(REPO_ROOT)
    assert thread["protected_paths"] == expected
    if expected:
        assert "Fenced files" in thread["prompt"] and str(len(expected)) in thread["prompt"]
