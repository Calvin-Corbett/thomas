"""The plugins a running Thomas loads, and the switches that turn them off and on.

``thomas/server/rows/default.toml`` lists the rows. Your choices sit on top of it in ``<data dir>/plugins/choices.json``.
A row that starts off is never imported. One pressed off on a running server stays in memory until the next restart, with
its routes and work ended. No plugin can stop Thomas starting: a row that fails reads ``failed`` with its reason, and the
rows after it still load.

This is a kernel of its own for each app, because every test builds an app and ``get_kernel()`` is one per process. The
installed-plugin supervisor keeps using that one until a later phase joins the two lists.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import importlib
import json
import logging
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 uses the declared tomli dependency.
    import tomli as tomllib

from thomas.agent.kernel_wiring import require_fs, require_models, require_sandbox
from thomas.core.atomic_json import read_text_with_retry, write_json_atomic
from thomas.core.config import resolve_thomas_data_dir
from thomas.core.kernel import (
    FS,
    LLM,
    SANDBOX,
    Entry,
    Fork,
    Kernel,
    KernelError,
    Profile,
    ProfileError,
    refuse_self_stop,
    stop,
    stop_would_wait,
)
from thomas.server.live_routes import WebService
from thomas.server.plugin_startup import provide_session_services

log = logging.getLogger(__name__)

APP_RUNTIME_PLUGINS = web.AppKey("runtime_plugins", object)
PROFILE_PATH = Path(__file__).resolve().parent / "rows" / "default.toml"
# What the Plugins page shows for a row. They live in the profile because a row that starts off is never imported, and the
# server sends them so a new row needs no change to the page. A row without them sends "" and the page says so itself.
WORDS = ("title", "about", "off_means", "stop_now")


class UnknownPlugin(KeyError):
    """A switch named a row the profile does not have."""


class StillStopping(Exception):
    """A row cannot turn on while its stop is waiting: it would finish off, with on saved for the next restart."""


class Required(Exception):
    """A row marked ``required`` has no off switch: Thomas needs it to work."""


def read_profile(path: Path) -> Profile:
    with path.open("rb") as handle:
        loaded = tomllib.load(handle)
    entries = tuple(
        Entry(
            id=str(row["id"]),
            plugin=str(row["entry"]),
            config={
                "enabled": bool(row.get("enabled", True)),
                "required": bool(row.get("required", False)),
                "words": {word: str(row.get(word, "")) for word in WORDS},
            },
        )
        for row in loaded.get("row", [])
    )
    return Profile(name=str(loaded.get("name") or "default"), entries=entries)


def read_choices(path: Path) -> tuple[dict[str, Any], str]:
    """Your saved choices, and what went wrong reading them. A file that is absent is fine; a damaged one is not."""
    try:
        loaded = json.loads(read_text_with_retry(path))
    except FileNotFoundError:
        return {}, ""
    except (OSError, ValueError) as exc:
        return {}, f"Your saved plugin choices could not be read, so Thomas used its defaults: {exc}"
    if not isinstance(loaded, dict):
        return {}, "Your saved plugin choices could not be read, so Thomas used its defaults: wrong shape"
    return loaded, ""


def compose(base: Profile, choices: Mapping[str, Any]) -> Profile:
    composed = base
    for row_id, choice in choices.items():
        if row_id not in composed.ids or not isinstance(choice, Mapping):
            log.warning("Ignoring a saved choice for %r, which is not a plugin here", row_id)
            continue
        row = composed.entries[composed.index_of(row_id)]  # a patch replaces the whole config, words included
        # A required row has no off switch, so a saved off for it (an old file, or one written by hand) is not honoured.
        enabled = True if row.config.get("required") else bool(choice.get("enabled", True))
        composed = composed.patch(row_id, config={**row.config, "enabled": enabled})
    return composed


def _reason(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


def _entry_plugin(entry: str) -> Any:
    """A row's plugin, and whatever it names in ``imports``.

    ``apply`` runs on the event loop and a row's registrar is imported inside it, so on a live turn on the entry's own
    import alone would leave most of the wait on the loop. ``imports`` is how a row moves that wait to the thread.
    """
    module, _, attribute = entry.partition(":")
    plugin = getattr(importlib.import_module(module), attribute)
    for name in getattr(plugin, "imports", ()):
        importlib.import_module(name)
    return plugin


@dataclass
class _Row:
    id: str
    entry: str
    enabled: bool
    words: Mapping[str, str]
    required: bool = False  # no off switch: the page shows it on and locked, and turning it off is refused
    fork: Fork | None = None
    error: str = ""
    stopping: bool = False
    importing: bool = False
    stopped_partway: bool = False  # Stop now ended something that was still running, in the row's last stop


class RuntimePlugins:
    def __init__(self, service: WebService, *, profile_path: Path, choices_path: Path, strict: bool = False) -> None:
        self.web = service
        self.kernel = Kernel()
        self.kernel.root.set("web", service)
        # The slots a row may ask for. Models is the same object default_kernel() carries.
        self.kernel.root.set(LLM, require_models())
        self.kernel.root.set(FS, require_fs())
        self.kernel.root.set(SANDBOX, require_sandbox())
        provide_session_services(self.kernel.root)
        self.notes: list[str] = []
        self.note_codes: list[str] = []  # fixed, one for each note, because the text carries raw error words
        self._profile_path = profile_path
        self._choices_path = choices_path
        self._strict = strict
        self._choices: dict[str, Any] = {}
        self._saver = ThreadPoolExecutor(max_workers=1, thread_name_prefix="plugin-choices")
        self._unreadable = False
        self._rows: dict[str, _Row] = {}

    def load(self) -> None:
        try:
            base = read_profile(self._profile_path)
        except (OSError, ValueError, KeyError, TypeError, ProfileError) as exc:
            self._note("list_unreadable", f"The plugin list could not be read, so no plugins loaded: {exc}")
            return
        self._choices, problem = read_choices(self._choices_path)
        if problem:
            self._unreadable = True
            self._note("choices_unreadable", problem)
        mounted: list[tuple[_Row, Fork]] = []
        for entry in compose(base, self._choices).entries:
            required = bool(entry.config.get("required", False))
            row = _Row(
                entry.id,
                str(entry.plugin),
                required or bool(entry.config.get("enabled")),
                entry.config["words"],
                required=required,
            )
            self._rows[row.id] = row
            if row.enabled:
                # Publishing rebuilds the whole route table, so one press per row is quadratic in the rows.
                # Outside strict mode a press already fails a plugin's routes alone, so the rows go up together.
                fork = self._load_row(row, publish=self._strict)
                if fork is not None and not self._strict:
                    mounted.append((row, fork))
        if mounted:
            self.web.publish(strict=False)
            for row, fork in mounted:
                if fork.error is not None:
                    self._fail_row(row, fork, fork.error)

    def _note(self, code: str, text: str) -> None:
        log.warning("%s", text)
        self.notes.append(text)
        self.note_codes.append(code)

    def _go_live(self, fork: Fork) -> None:
        """Put a fork's routes on the table. Raises if it failed, or if a route cannot join what is already there.

        A row that came up with this one and cannot join reads ``failed`` by itself, and this one is not to blame for it.
        """
        self.web.publish(strict=self._strict)
        if fork.error is not None:
            raise fork.error

    def _fail_row(self, row: _Row, fork: Fork | None, exc: BaseException) -> None:
        log.warning("Plugin %r did not load: %s", row.id, exc)
        row.error = _reason(exc)
        row.fork = None
        if fork is not None:
            # The server is not up yet, so nothing it asked to start has started, and this is all it takes.
            fork.dispose()

    def _load_row(self, row: _Row, *, publish: bool = True) -> Fork | None:
        """Mount a row. ``publish=False`` leaves its routes for the caller's one press; returns the fork if it mounted."""
        fork = None
        try:
            fork = self.kernel.mount(_entry_plugin(row.entry), {}, tolerate=True)
            if publish:
                self._go_live(fork)
            elif fork.error is not None:
                raise fork.error
        except Exception as exc:  # Broad catch: a row's import and routes are its own code, and it may not stop Thomas.
            self._fail_row(row, fork, exc)
            if self._strict:
                raise
            return None
        row.fork = fork
        return fork

    def _report_row(self, row: _Row) -> dict[str, Any]:
        fork = row.fork
        if row.importing:
            state = "loading"
        elif row.error:
            state = "failed"
        elif row.stopping:
            state = "unloading"
        else:
            state = fork.state if fork is not None else "off"
            if state == "active" and self.web.starting(fork.ctx):
                state = "loading"
        working = fork.ctx.working if fork is not None and fork.ctx is not None else 0
        # A row that fails after it mounted, in a start or a startup hook, holds its reason on the fork.
        error = row.error or (_reason(fork.error) if fork is not None and fork.error is not None else "")
        return {
            "id": row.id,
            **row.words,
            "enabled": row.enabled,
            "required": row.required,
            "state": state,
            "error": error if state == "failed" else "",
            "waiting_for": working,
            "stopped_partway": row.stopped_partway,
        }

    def title_of(self, row_id: str) -> str:
        """The name the page shows for a row, for words an answer to you can use in place of the id."""
        row = self._rows.get(row_id)
        return (row.words.get("title") if row is not None else "") or "This plugin"

    def report(self) -> dict[str, Any]:
        return {
            "rows": [self._report_row(row) for row in self._rows.values()],
            "notes": list(self.notes),
            "note_codes": list(self.note_codes),
        }

    def _row(self, row_id: str) -> _Row:
        row = self._rows.get(row_id)
        if row is None:
            raise UnknownPlugin(row_id)
        return row

    async def _remember(self, row: _Row) -> None:
        """Save what this press left, once every earlier press has saved.

        Two saves side by side can land either way round, and a row saved on but off here comes back at the next restart.
        So saves share one thread, and what each one writes is read here, on the event loop, where presses go one at a
        time. Shielded, because a press cancelled while its save is queued has still changed the row.
        """
        self._choices[row.id] = {"enabled": row.enabled}
        saving = asyncio.get_running_loop().run_in_executor(self._saver, self._save, dict(self._choices))
        saving.add_done_callback(self._saved)
        await asyncio.shield(saving)

    def _saved(self, saving: asyncio.Future[None]) -> None:
        """A save that landed is the fresh copy the note about damaged choices promises, so that note has done its job."""
        if saving.cancelled() or saving.exception() is not None or "choices_unreadable" not in self.note_codes:
            return
        at = self.note_codes.index("choices_unreadable")
        del self.notes[at], self.note_codes[at]

    def _save(self, choices: dict[str, Any]) -> None:
        if self._unreadable:
            self._choices_path.replace(self._choices_path.with_name(f"choices.unreadable-{time.time_ns()}.json"))
            self._unreadable = False
        write_json_atomic(self._choices_path, choices)

    def _stop_waiting(self, row: _Row) -> bool:
        """True from the press until the plugin is off. ``Fork.stopping`` also covers a stop that began at its provider."""
        return row.stopping or (row.fork is not None and row.fork.stopping)

    async def _take_off(self, row: _Row) -> None:
        await stop(row.fork)
        row.fork = None
        # A dependant that outlived its provider is back on a fresh scope, and its routes are not live yet.
        self.web.publish(strict=self._strict)

    async def turn_on(self, row_id: str) -> dict[str, Any]:
        row = self._row(row_id)
        if self._stop_waiting(row):
            raise StillStopping(row_id)
        row.enabled = True  # before the import: pressing off while it runs has to be able to take this back
        row.stopped_partway = False
        if row.fork is not None and row.fork.error is not None:
            await self._clear_failure(row)
        if row.enabled and row.fork is None and not row.importing:
            await self._import_and_mount(row)
        await self._remember(row)
        return self._report_row(row)

    async def _clear_failure(self, row: _Row) -> None:
        """Take off a plugin that failed after it mounted, so turning on can start it afresh.

        The kernel never retries a failed fork. One whose startup hook failed is also still plugged in, with cleanups only
        ``stop`` runs and, if that hook was added once it was live, routes a new mount would clash with. So this is a plain
        stop: its running work finishes, and Stop now can end the wait, as with any other stop.
        """
        row.stopping = True
        try:
            await self._take_off(row)
        finally:
            row.stopping = False

    async def _import_and_mount(self, row: _Row) -> None:
        """Import in a thread, so a slow import does not hold up every request on the server while it runs."""
        row.error = ""
        row.importing = True
        fork = None
        running: list[Fork] = []
        try:
            plugin = await asyncio.to_thread(_entry_plugin, row.entry)
            if row.enabled:
                running = self.kernel.mounted()
                fork = self.kernel.mount(plugin, {}, tolerate=True)
                self._go_live(fork)
                row.fork = fork
        except Exception as exc:  # Broad catch: as in ``_load_row``.
            log.warning("Plugin %r did not load: %s", row.id, exc)
            row.error = _reason(exc)
            if fork is not None:
                # Unlike at startup it may have stop steps to run, which only ``stop`` does. Nothing has awaited since the
                # mount, so what was running before cannot have used this row, and a failed press must leave that alone.
                await stop(fork, force=True, spare=running)
                # A row that came up with this one may have outlived it, and its fresh routes are not live yet.
                self.web.publish(strict=self._strict)
            if self._strict:
                raise
        finally:
            row.importing = False

    async def _end_the_wait(self, row: _Row) -> None:
        """What Stop now does. Only a stop that is waiting gives it anything to end.

        A press that lands after the wait is over, from another tab say, finds nothing here and changes nothing. If it
        began a stop of its own, it would cut work the row took on since, without anyone having chosen that.
        """
        fork = row.fork
        if fork is None:
            return
        if row.stopping:
            # Read before the wait, because a poll can find the row off before this press returns.
            row.stopped_partway |= stop_would_wait(fork)
            held = await stop(fork, force=True)  # not just this scope's work: a stop waits for what uses this row first
            # A drain step is not counted as work, so what the stop ended is how to know it ran.
            row.stopped_partway |= any(isinstance(problem, KernelError) for problem in held.errors)
        elif fork.stopping and fork.ctx is not None:
            row.stopped_partway |= fork.ctx.working > 0
            fork.ctx.cancel_work()  # the stop waiting for this row began at its provider, and is that row's to finish

    async def turn_off(self, row_id: str, *, force: bool = False) -> dict[str, Any]:
        row = self._row(row_id)
        if row.required:  # before the force branch too: Stop now would end the row all the same
            raise Required(row_id)
        if force:
            await self._end_the_wait(row)
            return self._report_row(row)
        if row.stopping:
            if row.enabled:  # Try again is clearing away a failure, and this press takes it back
                row.enabled = False
                await self._remember(row)  # saved before the wait ends, as below
            return self._report_row(row)
        if row.fork is not None:  # before anything changes, or a row that runs on is saved off for the next restart
            refuse_self_stop(row.fork)
        row.enabled = False
        row.error = ""
        row.stopped_partway = False
        if row.fork is None:
            # Saving is all this press has to do. A fork that mounts during the save came from an on pressed after it, and
            # taking that off would leave the row reading off with on saved for the next restart.
            await self._remember(row)
            return self._report_row(row)
        row.stopping = True
        try:
            # Saved before the wait: a restart during a long stop must not bring the plugin back.
            await self._remember(row)
            if row.fork is not None:  # shutdown may have got there first
                await self._take_off(row)
        finally:
            row.stopping = False
        return self._report_row(row)

    def mark_ready(self) -> None:
        """The server is up. Rows load while it is built and most route families register after them, so only now can a
        row be compared with every route the server has. One refused here goes as at startup, with nothing begun."""
        self.web.publish(strict=self._strict)
        for row in self._rows.values():
            if row.fork is not None and row.fork.error is not None:
                row.error = _reason(row.fork.error)
                row.fork.dispose()
                row.fork = None
        self.kernel.mark_ready()

    async def stop_all(self) -> None:
        """At shutdown, newest first. Forced, because the server has already stopped taking requests."""
        for row in reversed(list(self._rows.values())):
            if row.fork is not None:
                await stop(row.fork, force=True)
                row.fork = None


def _register_switch_routes(
    app: web.Application,
    runtime: RuntimePlugins,
    *,
    require_api_access: Callable[..., Any],
    require_loopback: Callable[..., Any],
) -> None:
    def guard(request: web.Request) -> None:
        require_api_access(request)
        require_loopback(request)

    async def status(request: web.Request) -> web.Response:
        guard(request)
        return web.json_response(runtime.report())

    async def turn_on(request: web.Request) -> web.Response:
        guard(request)
        try:
            return web.json_response(await runtime.turn_on(request.match_info["id"]))
        except UnknownPlugin as exc:
            raise web.HTTPNotFound(text=f"no plugin named {exc}") from exc
        except StillStopping as exc:
            raise web.HTTPConflict(text=f"{exc} is still turning off") from exc

    async def turn_off(request: web.Request) -> web.Response:
        guard(request)
        force = request.query.get("force") == "1"
        try:
            return web.json_response(await runtime.turn_off(request.match_info["id"], force=force))
        except UnknownPlugin as exc:
            raise web.HTTPNotFound(text=f"no plugin named {exc}") from exc
        except Required as exc:
            title = runtime.title_of(str(exc))
            raise web.HTTPConflict(text=f"{title} is part of how Thomas works, so it cannot be turned off.") from exc

    app.router.add_get("/api/plugins/thomas", status)
    app.router.add_post("/api/plugins/thomas/{id}/on", turn_on)
    app.router.add_post("/api/plugins/thomas/{id}/off", turn_off)


def load_runtime_plugins(
    app: web.Application,
    config: Any,
    *,
    require_api_access: Callable[..., Any] | None,
    read_json: Callable[..., Any] | None,
    require_loopback: Callable[..., Any] | None,
    web_dir: Path | None = None,
) -> RuntimePlugins:
    service = WebService(
        app,
        config,
        require_api_access=require_api_access,
        read_json=read_json,
        require_loopback=require_loopback,
        web_dir=web_dir,
    )
    choices = Path(resolve_thomas_data_dir()) / "plugins" / "choices.json"
    runtime = RuntimePlugins(service, profile_path=PROFILE_PATH, choices_path=choices)
    runtime.load()
    app[APP_RUNTIME_PLUGINS] = runtime
    if callable(require_api_access) and callable(require_loopback):
        _register_switch_routes(app, runtime, require_api_access=require_api_access, require_loopback=require_loopback)
    else:
        log.warning("Plugin switches skipped: missing the access or loopback guard")
    return runtime


__all__ = [
    "APP_RUNTIME_PLUGINS",
    "PROFILE_PATH",
    "Required",
    "RuntimePlugins",
    "StillStopping",
    "UnknownPlugin",
    "compose",
    "load_runtime_plugins",
    "read_choices",
    "read_profile",
]
