"""A message sent while Thomas waits to reload is queued for the composer, not turned away.

You said: "i dotn liek trade offs ... its all about speed". A landing that changes Python makes Thomas wait for the
checks that are running before he reloads, and that wait can last as long as a check. During it the send route
answered 503 "landed code is reloading", a red error on a message that only needed to wait. The Build composer sends
``queue_if_busy``; the route now answers 202 "Queued, runs next" and the composer asks again until the run starts.
Callers that do not send the flag (Autopilot, Praxis intake) keep the 503 they branch on.
"""

from __future__ import annotations

from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient

from tests.evolve_agent_route_support import _drive, _new_repo
from thomas.server.landed_code_reload import APP_LANDED_CODE_DRAIN


def _draining(app: web.Application) -> None:
    app[APP_LANDED_CODE_DRAIN] = "landed-head"


def test_the_composer_is_told_its_message_is_queued_while_a_reload_waits(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)

    async def _body(client: TestClient) -> None:
        response = await client.post(
            "/api/evolve/agent/send",
            json={"message": "Build while a reload waits", "request_id": "queued", "queue_if_busy": True},
        )
        payload = await response.json()
        assert response.status == 202
        assert payload["ok"] is True
        assert payload["queued"] is True
        assert payload["code"] == "reload_draining"
        assert payload["retry_after_s"] > 0
        assert not list(repo.rglob("*.json")), "a queued message must not create work before the reload"

    _drive(repo, _body, configure=_draining)


def test_a_caller_without_the_flag_keeps_the_refusal_it_branches_on(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)

    async def _body(client: TestClient) -> None:
        response = await client.post(
            "/api/evolve/agent/send", json={"message": "Build while a reload waits", "request_id": "plain"}
        )
        assert response.status == 503
        assert (await response.json())["code"] == "reload_draining"

    _drive(repo, _body, configure=_draining)
