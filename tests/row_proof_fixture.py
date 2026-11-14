"""What the proof of every row and the tests of that proof share."""

from __future__ import annotations

import ast
import asyncio
import importlib
import json
import threading
from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import make_mocked_request
from aiohttp.web_urldispatcher import UrlDispatcher

from tests.plugin_view_fixture import until
from thomas.core import plugin_fence
from thomas.core.kernel import Entry
from thomas.server.runtime_plugins import PROFILE_PATH, RuntimePlugins, read_profile

ROOT = Path(__file__).resolve().parents[1]
CYCLES = 100
ROWS = read_profile(PROFILE_PATH).entries

# What no row may hold, by the module that holds it and the routes it answers. Each can be the way back from a row
# turned off: your preferences, the switches themselves, the installed-plugin controls, and the two safety surfaces.
KEEP_IN_SHELL = {
    "thomas.server.routes.preferences_aiohttp": ("GET /api/preferences", "PATCH /api/preferences"),
    "thomas.server.runtime_plugins": (
        "GET /api/plugins/thomas",
        "POST /api/plugins/thomas/{id}/on",
        "POST /api/plugins/thomas/{id}/off",
    ),
    "thomas.server.routes.plugin_kernel_routes": (
        "GET /api/plugins/kernel",
        "POST /api/plugins/kernel/unplug",
        "POST /api/plugins/kernel/replug",
        "POST /api/plugins/kernel/reload",
        "POST /api/plugins/kernel/sync",
    ),
    "thomas.server.routes.third_party_agent_access_aiohttp": (
        "POST /api/security/third-party-agent-access",
        "POST /api/security/breakglass-opt-in",
        "POST /api/security/breakglass-window",
    ),
    "thomas.server.guardrails_api": (
        "GET /api/approvals/pending",
        "POST /api/approvals/resolve",
        "GET /api/guardrails/policy",
        "PUT /api/guardrails/policy",
        "POST /api/guardrails/policy",
    ),
}
KEPT_ROUTES = tuple(route for routes in KEEP_IN_SHELL.values() for route in routes)

# A row names its modules in ``imports``. Companion is older than that attribute, so its promise is written here.
ALSO_NAMED = {"companion": ("thomas.companion",)}


def choose(data_dir: Path, on: Iterable[str]) -> None:
    """Save your choice for every row, so a row shipped off comes through here the same as one shipped on."""
    wanted = set(on)
    choices = data_dir / "plugins" / "choices.json"
    choices.parent.mkdir(parents=True, exist_ok=True)
    choices.write_text(json.dumps({row.id: {"enabled": row.id in wanted} for row in ROWS}), encoding="utf-8")


def module_of(entry: Entry) -> str:
    return str(entry.plugin).partition(":")[0]


def named(entry: Entry) -> tuple[str, ...]:
    module, _, attribute = str(entry.plugin).partition(":")
    plugin = getattr(importlib.import_module(module), attribute)
    return (*getattr(plugin, "imports", ()), *ALSO_NAMED.get(entry.id, ()))


def footprint(runtime: RuntimePlugins, row_id: str) -> dict[str, int]:
    """All a row's stay could add to, as counts. A leak of one for each press reads 100 by the end."""
    app, kernel, service = runtime.web.app, runtime.kernel, runtime.web
    return {
        "effects on the root": kernel.root.pending_effects,
        "effects of the row": runtime._row(row_id).fork.ctx.pending_effects,
        "plugins mounted": len(kernel._forks),
        "services": len(kernel.root._services),
        "event handlers": sum(len(handlers) for handlers in kernel.bus._handlers.values()),
        "routes": len(app.router.routes()),
        "resources": len(app.router.resources()),
        "app keys": len(app._state),
        "route tables": len(service._rows) + len(service._scratch) + len(service._streams),
        "rows waiting to join": len(service._held),
        "rows on the table": len(service._joined),
        "keys with writers": len(service.writers),
        "publish hooks": len(service._rebuilds),
    }


def _named(routes: Iterable[Any]) -> list[str]:
    return sorted(f"{route.method} {route.resource.canonical}" for route in routes)


def routes_of_required_rows(runtime: RuntimePlugins) -> list[str]:
    """What the rows with no off switch answer. They stay up through every press, so a proof of another row leaves them out."""
    table = UrlDispatcher()
    for row in runtime._rows.values():
        if row.required and row.fork is not None:
            for live in runtime.web._rows.get(row.fork.ctx, ()):
                getattr(table, live.call)(*live.args, **live.kwargs)
    return _named(table.routes())


def live_routes(runtime: RuntimePlugins) -> list[str]:
    """The live table without the routes of a required row, which no press takes away."""
    left = Counter(_named(runtime.web._router._live.routes())) - Counter(routes_of_required_rows(runtime))
    return sorted(left.elements())


def rows_not_up(runtime: RuntimePlugins) -> list[tuple[str, str]]:
    """Each row that failed or is off. A row reads loading until a server has run its startup hooks, and that counts as up:
    it has loaded, and what it claims is in the table waiting to join."""
    return [(row["id"], row["state"]) for row in runtime.report()["rows"] if row["state"] not in ("active", "loading")]


async def _finished_starting(runtime: RuntimePlugins, row_id: str) -> dict[str, Any]:
    # A row reads loading while its startup hooks run, and an off now would cancel them, so no press would see what they do.
    await until(lambda: runtime._report_row(runtime._row(row_id))["state"] != "loading")
    return runtime._report_row(runtime._row(row_id))


async def off_and_on(runtime: RuntimePlugins, row_id: str, routes: list[str]) -> None:
    """One off and one on, with the table read after each, because a row that reads active may have come back empty."""
    off = await runtime.turn_off(row_id)
    assert off["state"] == "off", off
    still_up = live_routes(runtime)
    assert still_up == [], f"{row_id} is off and still answers {still_up}"  # the row under test is the only one on
    await runtime.turn_on(row_id)
    on = await _finished_starting(runtime, row_id)
    assert on["state"] == "active", on
    back = live_routes(runtime)
    assert back == routes, f"{row_id} came back on with {back}, and it had {routes}"


async def leaves_nothing_behind(runtime: RuntimePlugins, row_id: str) -> None:
    await _finished_starting(runtime, row_id)
    routes = live_routes(runtime)  # before the first off, or a row whose routes never return would set the bar itself
    await off_and_on(runtime, row_id, routes)  # the first round may load what only ever loads once
    before = footprint(runtime, row_id)
    tasks, threads = len(asyncio.all_tasks()), threading.active_count()

    for _ in range(CYCLES):
        await off_and_on(runtime, row_id, routes)

    after = footprint(runtime, row_id)
    grown = {name: (before[name], after[name]) for name in before if before[name] != after[name]}
    assert not grown, f"{row_id} left this behind, as (before, after): {grown}"
    # Whole-process counts, which the server's own work moves both ways: a thread pool fills, a startup task ends. So
    # these get room, and half is what a leak of one for each press cannot get under.
    tasks_grew = len(asyncio.all_tasks()) - tasks
    assert tasks_grew < CYCLES // 2, f"{row_id} left {tasks_grew} tasks running"
    threads_grew = threading.active_count() - threads
    assert threads_grew < CYCLES // 2, f"{row_id} left threads running: active_count rose by {threads_grew}"


def complaints(caplog: pytest.LogCaptureFixture, entry: Entry) -> list[str]:
    """What a stop step or a registrar said on its way down, which reaches the log and no further.

    A row's registrar logs a failure under its own name and the row reads active, as ``app_routes_companion`` does with
    ``_OPTIONAL_ROUTE_ERRORS``. If that happens on every apply the routes were never there to be missed, so this is the
    only place it can be seen.
    """
    heard = ("thomas.core.kernel", module_of(entry), *named(entry))
    return [record.getMessage() for record in caplog.records if record.name.startswith(heard)]


def _marks_work(module: str) -> bool:
    """True if a module calls ``ctx.busy``: work a stop waits for, which need not be running when anyone looks."""
    path = ROOT / module.replace(".", "/")
    files = path.rglob("*.py") if path.is_dir() else [path.with_suffix(".py")]
    trees = [ast.parse(file.read_text(encoding="utf-8")) for file in files]
    return any(isinstance(node, ast.Attribute) and node.attr == "busy" for tree in trees for node in ast.walk(tree))


def what_holds_a_stop(runtime: RuntimePlugins, entry: Entry) -> list[str]:
    """All a stop of this row could wait for, as far as can be known without one: only such a row needs Stop now's words."""
    ctx = runtime._row(entry.id).fork.ctx
    held = []
    if runtime.web._rows.get(ctx):
        held.append("routes")
    if ctx.working:
        held.append("work running now")
    if ctx._drains:
        held.append("drain steps")
    if ctx._stopped:
        held.append("stop steps")
    held += [f"{module} marks work as busy" for module in (module_of(entry), *named(entry)) if _marks_work(module)]
    return held


async def stop_ends_by_itself(runtime: RuntimePlugins, row_id: str, *, within: float = 30.0) -> bool:
    """Turn a row off and see the stop end with no second press. The bound only turns a hang into an answer."""
    stopping = asyncio.ensure_future(runtime.turn_off(row_id))
    await asyncio.wait({stopping}, timeout=within)
    return stopping.done()


def kept_modules_in(reached: Iterable[str]) -> set[str]:
    return {kept for kept in KEEP_IN_SHELL for name in reached if name == kept or name.startswith(f"{kept}.")}


def reaches_the_shell(entry: Entry) -> set[str]:
    """What a row names or imports that stays in the shell. Its file is read, so an import inside ``apply`` counts."""
    path = module_of(entry).replace(".", "/") + ".py"
    imported = plugin_fence.imports(path, (ROOT / path).read_text(encoding="utf-8"))
    return kept_modules_in([*named(entry), *(module for _, module in imported)])


def _routes_held_back(runtime: RuntimePlugins) -> UrlDispatcher:
    """What rows still waiting for their startup hooks have claimed. It joins the table the moment those hooks end."""
    table = UrlDispatcher()
    for ctx in runtime.web._held:
        for row in runtime.web._rows[ctx]:
            getattr(table, row.call)(*row.args, **row.kwargs)
    return table


async def kept_routes_a_row_answers(runtime: RuntimePlugins) -> list[str]:
    """Each kept route asked of the live table, which is looked at first, so a wide claim counts as well as an exact one.

    A row with startup hooks is not on that table until a server has run them, and the server's own route is often a
    pattern, which the route table's check does not reach. So what is held back is asked too, or that row passes here.
    """
    tables = (runtime.web._router._live, _routes_held_back(runtime))
    held = []
    for route in KEPT_ROUTES:
        method, path = route.split()
        for table in tables:
            found = await table.resolve(make_mocked_request(method, path.replace("{id}", "any")))
            if found.http_exception is None:
                held.append(route)
                break
    return held
