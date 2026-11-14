"""The Build handlers hand Praxis the function that really stops a Build run."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from aiohttp import web

from thomas.server.praxis import launch as praxis_launch
from thomas.server.routes import evolve_agent_routes, evolve_agent_run_state, evolve_agent_runtime


@pytest.mark.asyncio
async def test_handlers_built_for_the_app_stop_a_registered_run(monkeypatch, tmp_path):
    app = web.Application()
    evolve_agent_routes.build_evolve_agent_handlers(
        app, require_api_access=lambda _: None, root_resolver=lambda: tmp_path
    )
    proc = SimpleNamespace(returncode=None)
    calls = []

    async def terminate(target):
        calls.append(("terminate", target))
        return {"termination_confirmed": True}

    monkeypatch.setattr(
        evolve_agent_run_state,
        "slot_for_run_id",
        lambda _app, run_id: {"session": {"proc": proc}} if run_id == "live-run" else None,
    )
    monkeypatch.setattr(evolve_agent_runtime, "_mark_stop_requested", lambda target: calls.append(("mark", target)))
    monkeypatch.setattr(evolve_agent_runtime, "_terminate_process", terminate)

    stop = app[praxis_launch.APP_PRAXIS_STOP_CODE_RUN]
    assert await stop("live-run") is True
    assert calls == [("mark", proc), ("terminate", proc)]
    assert await stop("other-run") is False
