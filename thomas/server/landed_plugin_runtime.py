"""Stage row replacements away from the serving route and tool tables."""

from __future__ import annotations

import asyncio
import importlib
import importlib.machinery
import importlib.util
import inspect
import sys
from typing import Any

from aiohttp.web_urldispatcher import UrlDispatcher

from thomas.core.kernel import Kernel
from thomas.server.app_keys import APP_TOOLS
from thomas.server.live_routes import LiveRouter, _shared_routes
from thomas.server.runtime_plugin_web import stage_web


class _FreshSource(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname: str) -> Any:
        # Landings can preserve mtimes and file lengths. Never reuse their pyc.
        return self.source_to_code(self.get_data(self.path), self.path)


def _load(names: list[str]) -> dict[str, Any]:
    loaded = {}
    for name in names:
        spec = importlib.util.find_spec(name)
        if spec is None or not spec.origin or not spec.origin.endswith(".py"):
            raise RuntimeError(f"cannot stage source module {name}")
        loader = _FreshSource(name, spec.origin)
        fresh = importlib.util.spec_from_file_location(
            name,
            spec.origin,
            loader=loader,
            submodule_search_locations=spec.submodule_search_locations,
        )
        module = importlib.util.module_from_spec(fresh)
        sys.modules[name] = module
        loader.exec_module(module)
        loaded[name] = module
    return loaded


def _restore(before: dict[str, Any]) -> None:
    for name in set(sys.modules) - before.keys():
        if name.startswith("thomas."):
            sys.modules.pop(name, None)
    sys.modules.update(before)


def _stage(runtime: Any, rows: list[Any], names: list[str]) -> dict[str, Any]:
    original = dict(sys.modules)
    kernel = Kernel()
    service = runtime.web
    tools = service.app.get(APP_TOOLS)
    staged = stage_web(service, {row.id for row in rows})
    views = []
    original_view = staged.view

    def record_view(*args: Any, **kwargs: Any) -> Any:
        view = original_view(*args, **kwargs)
        views.append(view)
        return view

    staged.view = record_view
    for name, value in runtime.kernel.root._services.items():
        kernel.root.set(name, value)
    # Tool loans need their own ledger, not a shallow copy of the live one.
    from thomas.agent.kernel_wiring import LENT_TOOLS, _LentLedger

    ledger = _LentLedger()
    old_ledger = runtime.kernel.root.get(LENT_TOOLS, None)
    owners = {row.id for row in rows}
    if old_ledger is not None:
        ledger._lendings = [loan for loan in old_ledger._lendings if loan.owner not in owners]
    kernel.root.set(LENT_TOOLS, ledger)
    kernel.root.set("web", staged)
    forks = []
    staged_ok = False
    try:
        modules = _load(names)
        for row in rows:
            module, _, attr = row.entry.partition(":")
            plugin = getattr(modules[module], attr or "plugin")
            fork = kernel.mount(plugin)
            if not fork.active:
                raise RuntimeError(f"replacement row {row.id} did not mount")
            forks.append((row, fork))
        # Constructors and route replay are the mandatory structural self-check.
        staged.publish(strict=True)
        staged_ok = True
        return dict(
            kernel=kernel,
            web=staged,
            forks=forks,
            modules=modules,
            before=original,
            ledger=ledger,
            tools=tools,
            views=views,
        )
    finally:
        # Whatever a candidate raised, and it may raise anything, the scratch kernel goes and the live
        # modules come back.
        if not staged_ok:
            kernel.dispose()
        _restore(original)


def _combined(service: Any, staged: Any, old_contexts: set[Any]) -> tuple[Any, Any, Any]:
    rows = {ctx: value for ctx, value in service._rows.items() if ctx not in old_contexts}
    rows.update(staged._rows)
    scratch = {ctx: value for ctx, value in service._scratch.items() if ctx not in old_contexts}
    scratch.update(staged._scratch)
    clashes = _shared_routes(scratch, service._router.server_routes())
    if clashes:
        raise clashes[0][1]
    table = UrlDispatcher()
    for values in rows.values():
        for route in values:
            getattr(table, route.call)(*route.args, **route.kwargs)
    table.freeze()
    return rows, scratch, table


def _swap_lock(runtime: Any) -> asyncio.Lock:
    """One lock per runtime for landings, made on first use: RuntimePlugins has none of its own (found live, 2026-11-07)."""
    lock = getattr(runtime, "_landed_swap_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        runtime._landed_swap_lock = lock
    return lock


class NeedsRestart(RuntimeError):
    """A candidate that is sound but cannot be swapped while the server runs; the ordinary restart loads it.

    It is not a refusal. Read as one, the row was neither swapped nor restarted until someone pressed Restart: on
    2026-11-09 the Agents row sat that way for three hours with newer code landed.
    """


async def replace(runtime: Any, plan: dict[str, Any]) -> dict[str, Any]:
    """Publish a whole landing in one event-loop turn, or keep its old rows."""
    async with _swap_lock(runtime):
        ids = plan["plugins"]
        new = sorted(name for name in ids if name not in runtime._rows)
        if new:  # sound, but this server never loaded it: only a start reads the list of rows
            raise NeedsRestart(f"{', '.join(new)} is new, and a new plugin joins when Thomas starts")
        rows = [runtime._rows[name] for name in ids if runtime._rows[name].enabled]
        if any(row.stopping or row.importing for row in rows):
            raise RuntimeError("a replacement row is already changing")
        entries = [row.entry.partition(":")[0] for row in rows]
        names = list(dict.fromkeys([name for name in plan["modules"] if name not in entries] + entries))
        stage = _stage(runtime, rows, names)
        service = runtime.web
        staged = stage["web"]
        checked = False
        try:
            for _, fork in stage["forks"]:
                check = getattr(fork.plugin, "self_check", None)
                if check is not None:
                    answer = check(fork.ctx)
                    if inspect.isawaitable(answer):
                        answer = await answer
                    if answer is False:
                        raise RuntimeError(f"self-check refused {fork.name}")
            old_contexts = {row.fork.ctx for row in rows if row.fork is not None}
            combined, scratch, table = _combined(service, staged, old_contexts)
            # A candidate must not have started work before its transaction commits.
            for _, fork in stage["forks"]:
                if fork.ctx._tasks or fork.ctx._readies:
                    raise NeedsRestart(
                        f"{fork.name} starts work with the server, so it cannot be swapped while running"
                    )
            updates = {
                key: value
                for key, value in staged.app._state.items()
                if key != APP_TOOLS and value is not service.app.get(key)
            }
            checked = True
        finally:
            if not checked:  # a self-check may raise anything; the candidate goes and the old rows stay
                stage["kernel"].dispose()
        # No awaits from here to publication. Resolved old requests retain their
        # counted handler/context; old tool calls retain their old lending.
        retired = getattr(runtime, "_landed_retired", [])
        for row, fork in stage["forks"]:
            if row.fork is not None:
                old = row.fork
                runtime.kernel._forks.remove(old)
                retired.append(old)
            row.fork = fork
            row.error = ""
            fork.kernel = runtime.kernel
            runtime.kernel._forks.append(fork)
        runtime._landed_retired = retired
        from thomas.agent.kernel_wiring import LENT_TOOLS

        runtime.kernel.root._services[LENT_TOOLS] = stage["ledger"]
        if stage["tools"] is not None:
            stage["tools"]._tools = dict(staged.app[APP_TOOLS]._tools)
        service.app._state.update(updates)
        for view in stage["views"]:
            view._app = service.app
        staged.app = service.app
        for name in ("_rows", "_scratch", "_streams"):
            live = getattr(service, name)
            for ctx in old_contexts:
                live.pop(ctx, None)
            live.update(getattr(staged, name))
            setattr(staged, name, live)
        service._rows.update(combined)
        service._scratch.update(scratch)
        service._joined.difference_update(old_contexts)
        service._joined.update(staged._joined)
        staged._joined = service._joined
        staged._router = service._router
        service._router.publish(table)
        sys.modules.update(stage["modules"])
        for name, module in stage["modules"].items():
            parent, _, child = name.rpartition(".")
            if parent in sys.modules:
                setattr(sys.modules[parent], child, module)
        # Old scopes deliberately live until server shutdown: disposing one
        # would revoke tools already held by a running Build or cancel its work.
        runtime.kernel.root.effect(stage["kernel"].root.dispose)
        return {"ok": True, "plugins": ids, "modules": names}
