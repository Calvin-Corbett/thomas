"""A paused Thomas refuses a new Build or Code run with a sentence the page shows, and starts it again after Resume.

Proves ``thomas.core.pause`` and ``thomas.server.routes.evolve_agent_routes``: the one place every Build, Code,
Autopilot and queued Thomas project run starts is ``_start_run``, so one refusal there covers them all. A run that is
already going is not asked.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from tests.test_evolve_agent_routes import _drive, _new_repo
from thomas.core import pause as pause_mod
from thomas.server.routes import evolve_agent_routes as routes

REQUEST = {
    "message": "Create a synthetic counter",
    "model_id": "gpt-5.6-sol",
    "autonomy_level": 1,
    "file_access": "project",
    "thomas_guardrails": "fortress",
}


def test_a_paused_thomas_refuses_a_new_run_in_words_the_page_shows(tmp_path, monkeypatch):
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("THOMAS_PROFILE", raising=False)
    repo = _new_repo(tmp_path)
    spawn = AsyncMock(side_effect=AssertionError("a paused Thomas spawned a worker"))
    monkeypatch.setattr(routes.asyncio, "create_subprocess_exec", spawn)
    seen: dict[str, object] = {}

    async def check(client):
        pause_mod.pause("test")
        response = await client.post("/api/evolve/agent/send", json=REQUEST)
        seen["paused"] = (response.status, await response.json())
        pause_mod.resume()
        response = await client.post("/api/evolve/agent/send", json=REQUEST)
        seen["resumed"] = (response.status, await response.json())

    _drive(repo, check)
    status, payload = seen["paused"]  # type: ignore[misc]
    assert status == 503
    assert payload == {"ok": False, "error": "Thomas is paused. Press Resume on the Plugins page.", "code": "paused"}
    status, payload = seen["resumed"]  # type: ignore[misc]
    assert payload.get("code") == "execution_settings_blocked"  # past the pause check, and into the usual ones
    spawn.assert_not_awaited()
