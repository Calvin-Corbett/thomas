"""A remote caller's view of the gateway row while the check of who may call is set to cover the whole server.

``gateway_auth_scope = all`` makes the gateway's check refuse any path on the server that has no token, not only the
gateway's own. The check is installed by the server and not by the row, so it has to hold with the row off, with it on,
and with it off again after a press. One process asks the same paths at each of the three, as a caller on another machine
would, with no token and then with one, and also saves some gateway state before the second press to see it come back.

Asserts stay in the test that calls this, because pytest rewrites them only in a test module.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest import mock

from tests.row_off_fixture import _START_OF_A_SERVER, _in_a_process_of_its_own
from tests.row_proof_fixture import ROWS

TOKEN = "a-token-for-this-test"

# The setting is read from the environment of the process, so it is set around the start of one.
_THE_WHOLE_SERVER = {
    "THOMAS_GATEWAY_AUTH_MODE": "token",
    "THOMAS_GATEWAY_AUTH_TOKEN": TOKEN,
    "THOMAS_GATEWAY_AUTH_SCOPE": "all",
    # Eight refusals in a minute from one caller turn into 429, which would hide the 401 these tests read.
    "THOMAS_GATEWAY_AUTH_RATE_LIMIT_ENABLED": "0",
}
# What the machine running the tests may have set for a real gateway or provider, which a request here must not reach.
_NEVER_INHERITED = ("OPENAI", "THOMAS_GATEWAY", "RESPONSES_COMPAT")

_ASKED_AT_THREE_POINTS = (
    _START_OF_A_SERVER
    + """\


import os


async def ask(client, method, path, headers):
    async with client.request(method, path, json=None if method == "GET" else {}, headers=headers) as answer:
        try:
            body = await answer.json(content_type=None)
        except ValueError:
            body = None
        error = body.get("error") if isinstance(body, dict) else None
        return [answer.status, error.get("code") if isinstance(error, dict) else None]


async def ask_all(client, headers):
    return {ask_: await ask(client, *ask_.split(), headers) for ask_ in asks}


def checks(app):
    return sum(1 for m in app.middlewares if getattr(m, "__name__", "") == "gateway_auth_policy_middleware")


async def run_the_server():
    token = "a-token-for-this-test"
    server = ServerConfig(access_mode=os.environ["THE_ACCESS_MODE_UNDER_TEST"], api_token=token)
    config = AppConfig(models=models, default_model="local", memory=MemoryConfig(root=memory), server=server)
    app = app_core.create_app(config)
    bearer = {"Authorization": f"Bearer {token}"}
    async with TestClient(TestServer(app)) as client:
        await every_row_started(app)
        seen = {"start": (await state_of(app))["state"], "checks_at_start": checks(app)}
        seen["off"] = {"no_token": await ask_all(client, {}), "with_token": await ask_all(client, bearer)}
        seen["pressed_on"] = (await client.post(f"/api/plugins/thomas/{row_id}/on", headers=bearer)).status
        seen["on_state"] = (await state_of(app))["state"]
        seen["on"] = {"no_token": await ask_all(client, {}), "with_token": await ask_all(client, bearer)}
        async with client.put("/v1/gateway/state", json={"state": {"kept": "yes"}}, headers=bearer) as answer:
            seen["saved"] = answer.status
        seen["pressed_off"] = (await client.post(f"/api/plugins/thomas/{row_id}/off", headers=bearer)).status
        seen["off_again_state"] = (await state_of(app))["state"]
        seen["off_again"] = {"no_token": await ask_all(client, {}), "with_token": await ask_all(client, bearer)}
        seen["checks_after_presses"] = checks(app)
        seen["pressed_on_again"] = (await client.post(f"/api/plugins/thomas/{row_id}/on", headers=bearer)).status
        seen["on_again_state"] = (await state_of(app))["state"]
        async with client.get("/v1/gateway/state", headers=bearer) as answer:
            seen["state_back"] = await answer.json()
        return seen


Path(seen_at).write_text(json.dumps(asyncio.run(run_the_server())), encoding="utf-8")
"""
)


def _unset_what_reaches_a_real_gateway() -> None:
    for key in [key for key in os.environ if any(word in key for word in _NEVER_INHERITED)]:
        del os.environ[key]


def ask_with_the_check_covering_the_whole_server(
    asks: list[str], tmp_path: Path, *, access_mode: str = "remote", scope: str = "all"
) -> tuple[Any, Any]:
    """Start with the gateway row off and ask ``asks`` at the start, with it on, and with it off again. See the module."""
    with mock.patch.dict(os.environ):
        _unset_what_reaches_a_real_gateway()
        os.environ.update(_THE_WHOLE_SERVER)
        if scope == "unset":
            del os.environ["THOMAS_GATEWAY_AUTH_SCOPE"]
        else:
            os.environ["THOMAS_GATEWAY_AUTH_SCOPE"] = scope
        os.environ["THE_ACCESS_MODE_UNDER_TEST"] = access_mode
        return _in_a_process_of_its_own(
            _ASKED_AT_THREE_POINTS, "gateway", asks, tmp_path, on=[row.id for row in ROWS if row.id != "gateway"]
        )
