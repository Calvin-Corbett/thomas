"""A rejected Praxis plan must tell the Build lead what to correct."""

import httpx
import pytest

from thomas.forge.anvil import run_channel_client as module


@pytest.mark.asyncio
async def test_spawn_refusal_reports_server_reason_without_run_token(monkeypatch):
    original_client = httpx.AsyncClient
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(400, json={"ok": False, "error": "plan_refused: invalid_dependencies"})
    )
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **_options: original_client(transport=transport))
    client = module.RunChannelClient(base_url="http://127.0.0.1:8899", run_id="run-test", token="secret-token")

    with pytest.raises(RuntimeError, match="plan_refused: invalid_dependencies") as refusal:
        await client.call("spawn", {"units": [{"kind": "review"}]})

    assert "secret-token" not in str(refusal.value)
