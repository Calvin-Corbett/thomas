"""A landing replaces serving rows without interrupting old requests or tools."""

import asyncio
import importlib
import sys
from types import SimpleNamespace

import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core.kernel import Kernel
from thomas.server.app_keys import APP_TOOLS
from thomas.server.landed_plugin_swap import classify, swap
from thomas.server.live_routes import WebService
from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS, _Row
from thomas.tools.registry import ToolRegistry

SOURCE = """
from aiohttp import web
from thomas.agent.kernel_wiring import contribute_tools
from thomas.tools.base import Tool as BaseTool
class Tool(BaseTool):
    name = "demo.tool"
    description = "test"
    parameters = {{"type": "object", "properties": {{}}}}
    async def execute(self, args):
        return VERSION
VERSION = {version!r}
class Plugin:
    name = "demo"
    inject = ("web",)
    def apply(self, ctx, config):
        view = ctx["web"].view(ctx)
        async def handler(request):
            if request.query.get("wait"):
                request.app["entered"].set()
                await request.app["release"].wait()
            return web.Response(text=VERSION)
        view.router.add_get("/demo", handler)
        contribute_tools(ctx, [Tool()], owner="demo")
        for tool in __import__("thomas.agent.kernel_wiring", fromlist=["contributed_tools"]).contributed_tools(ctx):
            ctx["web"].app[__import__("thomas.server.app_keys", fromlist=["APP_TOOLS"]).APP_TOOLS].register(tool)
    def self_check(self, ctx):
        return {healthy!r}
plugin = Plugin()
"""


@pytest_asyncio.fixture
async def live(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    source = tmp_path / "demo_row.py"
    source.write_text(SOURCE.format(version="old", healthy=True), encoding="utf-8")
    (tmp_path / "plugins").mkdir()
    (tmp_path / "plugins/demo.toml").write_text('name="demo"\ncode=["demo_row.py"]\n')
    profile = tmp_path / "thomas/server/rows/default.toml"
    profile.parent.mkdir(parents=True)
    profile.write_text('[[row]]\nid="demo"\nentry="demo_row:plugin"\n')
    app = web.Application()
    app[APP_TOOLS] = ToolRegistry()
    app["entered"] = asyncio.Event()
    app["release"] = asyncio.Event()
    service = WebService(app, SimpleNamespace(), require_api_access=None, read_json=None)
    kernel = Kernel()
    kernel.root.set("web", service)
    module = importlib.import_module("demo_row")
    fork = kernel.mount(module.plugin)
    service.publish(strict=True)
    row = _Row("demo", "demo_row:plugin", True, {}, fork=fork)
    # No _lock here on purpose: the real RuntimePlugins has none, and the first live swap failed on that (2026-11-07).
    runtime = SimpleNamespace(web=service, kernel=kernel, _rows={"demo": row})
    app[APP_RUNTIME_PLUGINS] = runtime
    from thomas.server.app_keys import APP_SHUTDOWN_EVENT

    app[APP_SHUTDOWN_EVENT] = asyncio.Event()
    client = TestClient(TestServer(app))
    await client.start_server()
    yield tmp_path, source, app, client, runtime
    await client.close()
    kernel.dispose()
    sys.modules.pop("demo_row", None)


@pytest.mark.asyncio
async def test_landing_watcher_swaps_without_drain(live, monkeypatch):
    from thomas.server import landed_code_reload as reload
    from thomas.server.app_keys import APP_SHUTDOWN_EVENT

    repo, source, app, client, runtime = live
    app[APP_SHUTDOWN_EVENT] = asyncio.Event()
    monkeypatch.setattr(reload, "REPO_ROOT", repo)
    monkeypatch.setattr(reload, "_reload_allowed", lambda: True)
    monkeypatch.setattr(reload, "_caged_server_disabled", lambda: False)
    monkeypatch.setattr(reload.workers, "generation_stopping", lambda: False)
    monkeypatch.setattr(reload, "_handled_marker", lambda: repo / "handled")
    source.write_text(SOURCE.format(version="new", healthy=True), encoding="utf-8")
    await reload.check_once(app, None, 1, work=("Build run",), landed=("old", "new", ["demo_row.py"]))
    assert not app[APP_SHUTDOWN_EVENT].is_set()
    assert reload.APP_LANDED_CODE_DRAIN not in app
    assert app["landed_plugin_swaps"][-1]["rows"] == ["demo"]
    from thomas.server.owner_restart import status

    assert status(app)["swaps"][-1]["rows"] == ["demo"]
    assert await (await client.get("/demo")).text() == "new"


@pytest.mark.asyncio
async def test_bad_landing_keeps_serving_without_restart(live, monkeypatch):
    from thomas.server import landed_code_reload as reload

    repo, source, app, client, runtime = live
    monkeypatch.setattr(reload, "REPO_ROOT", repo)
    monkeypatch.setattr(reload, "_reload_allowed", lambda: True)
    monkeypatch.setattr(reload, "_caged_server_disabled", lambda: False)
    monkeypatch.setattr(reload, "_handled_marker", lambda: repo / "handled")
    source.write_text("invalid python !!!", encoding="utf-8")
    result = await reload.check_once(app, 0.0, 1.0, landed=("old", "new", ["demo_row.py"]))
    assert result is None
    assert not app.get(reload.APP_LANDED_CODE_DRAIN)
    assert app["landed_plugin_attempt"]["error"]
    assert (await client.get("/demo")).status == 200
    assert await (await client.get("/demo")).text() == "old"


@pytest.mark.asyncio
async def test_swap_publishes_routes_tools_and_preserves_old_request(live):
    repo, source, app, client, runtime = live
    old_tool = app[APP_TOOLS]._tools["demo.tool"]
    running = asyncio.create_task(client.get("/demo?wait=1"))
    await asyncio.wait_for(app["entered"].wait(), 2)
    source.write_text(SOURCE.format(version="new", healthy=True), encoding="utf-8")
    result = await swap(app, repo, ["demo_row.py"])
    assert result.get("error") is None, result
    assert result["swapped_rows"] == ["demo"]
    assert await (await client.get("/demo")).text() == "new"
    assert await app[APP_TOOLS]._tools["demo.tool"].execute({}) == "new"
    assert await old_tool.execute({}) == "old"
    assert not running.done()
    app["release"].set()
    assert await (await running).text() == "old"


@pytest.mark.asyncio
@pytest.mark.parametrize("broken", ["check", "syntax", "import"])
async def test_failed_candidate_leaves_old_routes_tools_and_module(live, broken):
    repo, source, app, client, runtime = live
    old_module = sys.modules["demo_row"]
    old_tool = app[APP_TOOLS]._tools["demo.tool"]
    replacement = SOURCE.format(version="bad", healthy=False)
    if broken == "syntax":
        replacement = "this is not valid python !!!"
    if broken == "import":
        replacement = "raise RuntimeError('candidate import failed')"
    source.write_text(replacement, encoding="utf-8")
    result = await swap(app, repo, ["demo_row.py"])
    assert result["error"]
    assert await (await client.get("/demo")).text() == "old"
    assert app[APP_TOOLS]._tools["demo.tool"] is old_tool
    assert sys.modules["demo_row"] is old_module


def test_unknown_python_requires_kernel_restart(tmp_path):
    (tmp_path / "plugins").mkdir()
    assert classify(tmp_path, ["unowned.py"])["kernel_files"] == ["unowned.py"]


@pytest.mark.asyncio
async def test_an_uncommitted_edit_elsewhere_does_not_stop_the_swap(live, monkeypatch):
    """Until 2026-11-07 any uncommitted server Python stopped every reload and said nothing; with three sessions editing
    the shared checkout that was nearly always, so a row-only landing never swapped (0b3d4286d sat unloaded)."""
    from thomas.server import landed_code_reload as reload

    repo, source, app, client, runtime = live
    monkeypatch.setattr(reload, "REPO_ROOT", repo)
    monkeypatch.setattr(reload, "_reload_allowed", lambda: True)
    monkeypatch.setattr(reload, "_caged_server_disabled", lambda: False)
    monkeypatch.setattr(reload, "_handled_marker", lambda: repo / "handled")
    app._state[reload.APP_LANDED_DIRTY] = ["thomas/server/somebody_elses_file.py"]
    source.write_text(SOURCE.format(version="new", healthy=True), encoding="utf-8")
    await reload.check_once(app, None, 1, work=(), landed=("old", "new", ["demo_row.py"]))
    assert app["landed_plugin_swaps"][-1]["rows"] == ["demo"]
    assert await (await client.get("/demo")).text() == "new"


@pytest.mark.asyncio
async def test_an_uncommitted_edit_to_the_row_itself_holds_the_swap_and_names_the_file(live, monkeypatch):
    from thomas.server import landed_code_reload as reload

    repo, source, app, client, runtime = live
    monkeypatch.setattr(reload, "REPO_ROOT", repo)
    monkeypatch.setattr(reload, "_reload_allowed", lambda: True)
    monkeypatch.setattr(reload, "_caged_server_disabled", lambda: False)
    monkeypatch.setattr(reload, "_handled_marker", lambda: repo / "handled")
    app._state[reload.APP_LANDED_DIRTY] = ["demo_row.py"]
    source.write_text(SOURCE.format(version="new", healthy=True), encoding="utf-8")
    await reload.check_once(app, None, 1, work=(), landed=("old", "new", ["demo_row.py"]))
    assert "landed_plugin_swaps" not in app
    assert reload.APP_LANDED_CODE_DRAIN not in app
    notice = app[reload.APP_LANDED_CODE_NOTICE]["notice"]
    assert notice["uncommitted"] == ["demo_row.py"]
    assert await (await client.get("/demo")).text() == "old"
    # Once the file is committed, the next look swaps: nothing was cached for this head.
    app._state[reload.APP_LANDED_DIRTY] = []
    await reload.check_once(app, None, 2, work=(), landed=("old", "new", ["demo_row.py"]))
    assert await (await client.get("/demo")).text() == "new"


def _kernel_landing(reload, live, monkeypatch):
    repo, _source, app, _client, _runtime = live
    monkeypatch.setattr(reload, "REPO_ROOT", repo)
    monkeypatch.setattr(reload, "_reload_allowed", lambda: True)
    monkeypatch.setattr(reload, "_caged_server_disabled", lambda: False)
    monkeypatch.setattr(reload, "_handled_marker", lambda: repo / "handled")
    monkeypatch.setattr(reload, "drain_signal_path", lambda: repo / "drain-signal")
    return repo, app


@pytest.mark.asyncio
async def test_a_full_restart_is_not_held_by_an_uncommitted_edit_that_loads(live, monkeypatch):
    """From 2026-11-07 to 11-09 Thomas never restarted himself: 40 files other sessions had left uncommitted held every
    restart, though each sign-in had booted those same files already. An edit that loads is no reason to wait."""
    from thomas.server import landed_code_reload as reload

    repo, app = _kernel_landing(reload, live, monkeypatch)
    (repo / "thomas/server/somebody_elses_file.py").write_text("VALUE = 1\n", encoding="utf-8")
    app._state[reload.APP_LANDED_DIRTY] = ["thomas/server/somebody_elses_file.py", "thomas/server/deleted_file.py"]
    await reload.check_once(app, None, 1, work=(), landed=("old", "new", ["unowned.py"]))
    assert app[reload.APP_LANDED_CODE_DRAIN]["head"] == "new"
    notice = app[reload.APP_LANDED_CODE_NOTICE]["notice"]
    assert "Waiting" not in notice["reason"]
    assert notice["uncommitted"] == ["thomas/server/somebody_elses_file.py", "thomas/server/deleted_file.py"]
    assert "broken" not in notice


@pytest.mark.asyncio
async def test_a_full_restart_waits_for_an_uncommitted_edit_that_cannot_load_and_names_it(live, monkeypatch):
    from thomas.server import landed_code_reload as reload

    repo, app = _kernel_landing(reload, live, monkeypatch)
    (repo / "thomas/server/fine.py").write_text("VALUE = 1\n", encoding="utf-8")
    half = repo / "thomas/server/half_written.py"
    half.write_text("def unfinished(:\n", encoding="utf-8")
    app._state[reload.APP_LANDED_DIRTY] = ["thomas/server/fine.py", "thomas/server/half_written.py"]
    await reload.check_once(app, None, 1, work=(), landed=("old", "new", ["unowned.py"]))
    assert reload.APP_LANDED_CODE_DRAIN not in app
    notice = app[reload.APP_LANDED_CODE_NOTICE]["notice"]
    assert notice["broken"] == ["thomas/server/half_written.py"]
    assert "thomas/server/half_written.py" in notice["reason"] and "fine.py" not in notice["reason"]
    # Once the file loads again the next look drains: nothing was cached for this head.
    half.write_text("def finished():\n    return 1\n", encoding="utf-8")
    await reload.check_once(app, None, 2, work=(), landed=("old", "new", ["unowned.py"]))
    assert app[reload.APP_LANDED_CODE_DRAIN]["head"] == "new"


STARTS_WORK = SOURCE.replace(
    '        view.router.add_get("/demo", handler)',
    '        view.router.add_get("/demo", handler)\n        ctx.on_ready(lambda: None)  # work that starts with the server',
)


@pytest.mark.asyncio
async def test_a_row_that_cannot_swap_while_running_gets_the_full_restart(live, monkeypatch):
    """A row with work that starts with the server cannot be swapped live, and says so. That was read as a broken
    row: no swap, and no restart either, until someone pressed Restart. On 2026-11-09 the Agents row sat that way for
    three hours ("candidate rejected: agents requires a restart for startup work") with newer code landed."""
    from thomas.server import landed_code_reload as reload

    assert "ctx.on_ready" in STARTS_WORK
    repo, source, app, client, runtime = live
    monkeypatch.setattr(reload, "REPO_ROOT", repo)
    monkeypatch.setattr(reload, "_reload_allowed", lambda: True)
    monkeypatch.setattr(reload, "_caged_server_disabled", lambda: False)
    monkeypatch.setattr(reload, "_handled_marker", lambda: repo / "handled")
    monkeypatch.setattr(reload, "drain_signal_path", lambda: repo / "drain-signal")
    source.write_text(STARTS_WORK.format(version="new", healthy=True), encoding="utf-8")

    await reload.check_once(app, None, 1, work=(), landed=("old", "new", ["demo_row.py"]))

    assert app[reload.APP_LANDED_CODE_DRAIN]["head"] == "new"  # the ordinary restart has begun
    notice = app[reload.APP_LANDED_CODE_NOTICE]["notice"]
    assert "restart" in notice["reason"] and "refused" not in notice["reason"]
    assert await (await client.get("/demo")).text() == "old"  # the old row serves until the restart
    # The next look carries on with the restart; it must not be answered from memory as "handled".
    quiet = await reload.check_once(app, None, 2, work=(), landed=("old", "new", ["demo_row.py"]))
    assert quiet == 2 and app[reload.APP_LANDED_CODE_DRAIN]["head"] == "new"


@pytest.mark.asyncio
async def test_a_row_that_is_broken_still_keeps_serving_and_restarts_nothing(live, monkeypatch):
    from thomas.server import landed_code_reload as reload

    repo, source, app, client, runtime = live
    monkeypatch.setattr(reload, "REPO_ROOT", repo)
    monkeypatch.setattr(reload, "_reload_allowed", lambda: True)
    monkeypatch.setattr(reload, "_caged_server_disabled", lambda: False)
    monkeypatch.setattr(reload, "_handled_marker", lambda: repo / "handled")
    source.write_text(SOURCE.format(version="new", healthy=False), encoding="utf-8")  # its own check refuses it

    await reload.check_once(app, None, 1, work=(), landed=("old", "new", ["demo_row.py"]))

    assert reload.APP_LANDED_CODE_DRAIN not in app
    assert "refused" in app[reload.APP_LANDED_CODE_NOTICE]["notice"]["reason"]
    assert await (await client.get("/demo")).text() == "old"


@pytest.mark.asyncio
async def test_a_landing_that_adds_a_new_row_gets_the_full_restart(live, monkeypatch):
    """A row this server never loaded cannot be swapped in, and the swap says so. That too was read as a broken row:
    on 2026-11-10 the landing that added "Look inside the cage" sat with "landing names a row not present in this
    server" and a Restart button, and the server never loaded it."""
    from thomas.server import landed_code_reload as reload

    repo, source, app, client, runtime = live
    monkeypatch.setattr(reload, "REPO_ROOT", repo)
    monkeypatch.setattr(reload, "_reload_allowed", lambda: True)
    monkeypatch.setattr(reload, "_caged_server_disabled", lambda: False)
    monkeypatch.setattr(reload, "_handled_marker", lambda: repo / "handled")
    monkeypatch.setattr(reload, "drain_signal_path", lambda: repo / "drain-signal")
    (repo / "brand_new_row.py").write_text(SOURCE.format(version="new", healthy=True), encoding="utf-8")
    (repo / "plugins/brand_new.toml").write_text('name="brand_new"\ncode=["brand_new_row.py"]\n')
    profile = repo / "thomas/server/rows/default.toml"
    profile.write_text(profile.read_text() + '[[row]]\nid="brand_new"\nentry="brand_new_row:plugin"\n')

    await reload.check_once(app, None, 1, work=(), landed=("old", "new", ["brand_new_row.py"]))

    assert app[reload.APP_LANDED_CODE_DRAIN]["head"] == "new"
    notice = app[reload.APP_LANDED_CODE_NOTICE]["notice"]
    assert "restart" in notice["reason"] and "refused" not in notice["reason"]
    assert await (await client.get("/demo")).text() == "old"
