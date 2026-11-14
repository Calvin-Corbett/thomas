"""A retained supervisor must use the reloaded application's AppKey objects.

Exercise real serve_async startup/cleanup across two key generations. App
bootstrap, socket binding and background jobs are offline fixtures; no live
server or process is touched, and no provider is invoked.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from types import ModuleType

import pytest
from aiohttp import web

import thomas.server
from thomas.core.config import AppConfig
from thomas.server import app_keys, app_lifecycle


@pytest.mark.asyncio
@pytest.mark.parametrize("first_check", ["preview", "restart"])
async def test_reloaded_keys_configure_preview_and_allow_repeated_restart(monkeypatch, first_check):
    retained_serve = app_lifecycle.serve_async
    initial_key = app_keys.APP_SHUTDOWN_EVENT
    generations = []

    async def no_background_work():
        return None

    canvas = ModuleType("thomas.server.chat_delegation_canvas")
    canvas.start_canvas_keepalive = lambda: None
    sweep = ModuleType("thomas.server.stale_execution_sweep")
    sweep.run_stale_execution_sweeper = no_background_work
    monkeypatch.setitem(sys.modules, canvas.__name__, canvas)
    monkeypatch.setitem(sys.modules, sweep.__name__, sweep)
    monkeypatch.setattr(app_lifecycle, "_log_landing_heartbeat", no_background_work)

    for _generation in range(2):
        with monkeypatch.context() as patch:
            # Model serve() evicting the key module while retaining its own
            # serve_async function. Other application imports use fresh keys.
            patch.setattr(thomas.server, "app_keys", app_keys)
            patch.delitem(sys.modules, "thomas.server.app_keys")
            keys = importlib.import_module("thomas.server.app_keys")
            assert keys.APP_SHUTDOWN_EVENT is not initial_key
            assert all(keys.APP_SHUTDOWN_EVENT is not key for key in generations)
            generations.append(keys.APP_SHUTDOWN_EVENT)
            configured = []
            stopped = []
            cleaned = []

            class Preview:
                def configure(self, **kwargs):
                    configured.append(kwargs)

                async def stop(self):
                    stopped.append(True)

            service = Preview()
            app = web.Application()
            app[keys.APP_DELIVERABLE_PREVIEW_SERVICE] = service
            core = ModuleType("thomas.server.app_core")
            core.create_app = lambda _config: app
            patch.setitem(sys.modules, core.__name__, core)

            class Runner:
                def __init__(self, application, **_kwargs):
                    assert application is app

                async def setup(self):
                    return None

                async def cleanup(self):
                    cleaned.append(True)

            class Site:
                def __init__(self, _runner, **_kwargs):
                    pass

                async def start(self):
                    if first_check == "preview":
                        assert configured == [{"main_origin": "http://127.0.0.1:8977"}]
                    event = app.get(keys.APP_SHUTDOWN_EVENT)
                    assert isinstance(event, asyncio.Event), (
                        "restart route cannot find this generation's shutdown event"
                    )
                    assert app[keys.APP_SELF_BASE_URL] == "http://127.0.0.1:8977"
                    assert app[keys.APP_CRASH_COUNT] == 2
                    # The real restart route sets these exact new-generation
                    # keys; the retained lifecycle must observe both of them.
                    app[keys.APP_RESTART_REQUESTED] = True
                    event.set()

            patch.setattr(web, "AppRunner", Runner)
            patch.setattr(web, "TCPSite", Site)
            with pytest.raises(app_lifecycle._ServerRestartRequested):
                await retained_serve(AppConfig(), host="127.0.0.1", port=8977, crash_count=2)
            assert configured == [{"main_origin": "http://127.0.0.1:8977"}]
            assert stopped == [True] and cleaned == [True]
