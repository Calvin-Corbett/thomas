"""The reload route runs the edit, not the bytecode cached beside it.

`plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md`, phase 3.5.

``POST /api/plugins/kernel/reload`` is the path the live app answered
``outcome: reloaded`` on thirteen times while the hook kept stamping ``loop36``
instead of ``loop49`` — so it is the path that has to be checked with the
bytecode cache in play, and not only through the supervisor's own API
(``tests/test_plugin_source_reload.py`` does that half).

Bytecode writing is turned **on** here, against ``tests/conftest.py``, because
that setting is what hid the defect from the suite while every real launch wrote
``.pyc`` files.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from tests.plugin_bytecode_helpers import (
    NEW_MARK,
    OLD_MARK,
    PLUGIN_SOURCE,
    set_stale_pyc_trap,
    write_manifest,
    write_plugin,
)
from thomas.agent.kernel_wiring import default_kernel
from thomas.server.plugin_hook_bridge import make_plugin_hook_runner
from thomas.server.plugin_supervisor import PluginSupervisor
from thomas.server.routes.plugin_kernel_routes import APP_PLUGINS_HANDLE, register_plugin_kernel_routes


class LiveReloadOverHttpTests(AioHTTPTestCase):
    """A plugin installed, mounted, edited, and reloaded over the route."""

    async def get_application(self) -> web.Application:
        previous_bytecode = sys.dont_write_bytecode
        sys.dont_write_bytecode = False
        self.addCleanup(lambda: setattr(sys, "dont_write_bytecode", previous_bytecode))

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        previous_store = os.environ.get("THOMAS_PLUGIN_ENABLEMENT_STORE")
        os.environ["THOMAS_PLUGIN_ENABLEMENT_STORE"] = str(Path(tmp.name) / "enablement.json")

        def _restore_store() -> None:
            if previous_store is None:
                os.environ.pop("THOMAS_PLUGIN_ENABLEMENT_STORE", None)
            else:
                os.environ["THOMAS_PLUGIN_ENABLEMENT_STORE"] = previous_store

        self.addCleanup(_restore_store)

        from thomas.plugins.runtime import clear_cache

        clear_cache()

        self.root = Path(tmp.name) / "plugins"
        self.root.mkdir()
        self.package = write_plugin(self.root, "demo_stamp", OLD_MARK)
        write_manifest(self.root, "demo_stamp")

        kernel = default_kernel()
        self.supervisor = PluginSupervisor(kernel=kernel, install_root=str(self.root)).start()
        self.addCleanup(self.supervisor.dispose)
        self.runner = make_plugin_hook_runner(install_root=str(self.root), kernel=kernel)

        app = web.Application()
        app[APP_PLUGINS_HANDLE] = self.supervisor
        register_plugin_kernel_routes(
            app,
            require_api_access=lambda request: None,
            require_loopback=lambda request: None,
            read_json=lambda request: request.json(),
        )
        return app

    async def _marks(self) -> list[str]:
        payload = await self.runner("before_tool", {})
        return list(payload.get("marks", []))

    async def test_the_reload_route_runs_the_edit_and_not_the_cached_bytecode(self) -> None:
        self.assertEqual(await self._marks(), [OLD_MARK])

        set_stale_pyc_trap(self.package / "__init__.py", PLUGIN_SOURCE.format(name="demo_stamp", mark=NEW_MARK))

        body = await (await self.client.post("/api/plugins/kernel/reload", json={"name": "demo_stamp"})).json()

        self.assertTrue(body["ok"])
        self.assertEqual(body["outcome"], "reloaded")
        self.assertEqual(await self._marks(), [NEW_MARK])
