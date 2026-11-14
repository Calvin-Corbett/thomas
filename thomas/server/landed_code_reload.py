"""Drain new Code starts before retiring a caged or tray-started server for landed Python code."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from thomas.core import step_log
from thomas.core.config import resolve_thomas_data_dir
from thomas.core.event_loop_offload import off_loop
from thomas.core.git_process import run_git
from thomas.core.head_sha import head_sha
from thomas.core.pause import paused
from thomas.server import autopilot_restart, capacity_ledger, green_handoff, landed_code_resume, self_change_status
from thomas.server.app_keys import APP_RUNTIME_GUARD_STATE, APP_SHUTDOWN_EVENT
from thomas.server.precard import workers
from thomas.server.routes.evolve_agent_run_state import active_code_runs
from thomas.tools import cage_shell, owner_desk

log = logging.getLogger(__name__)
RELOAD_CHECK_S = 30.0
RELOAD_QUIET_S = 30.0
# Build runs keep working while checks, hand-ins and the promoter's inbox finish; only then, or after this long, are
# they asked to yield. On 2026-10-24 every team yielded at 09:00 and sat idle until the checks let the server go at
# 09:33; one drain held them for 2.5 hours (2026-10-25). Since 2026-11-13 this cap is not counted against a running
# check (CHECK_WORK below): while one runs, no Build is asked to yield however long it takes.
RUN_YIELD_AFTER_S = 1200.0
BUILD_RUN = "Build run"
# No new run is admitted during the drain; running agents yield between iterations once signalled.
APP_LANDED_CODE_DRAIN = "landed_code_drain"
# When the drain began. It outlives a second landing and a brief clear (a git call timing out on a busy PC), so
# RUN_YIELD_AFTER_S counts from the first landing; only a clear longer than that starts a new clock.
APP_LANDED_CODE_DRAIN_CLOCK = "landed_code_drain_clock"
# The landing whose rows were last swapped in place; later landings are measured from it (see _landed_change).
APP_LANDED_SWAP_BASE = "landed_swap_base"
# {"notice": {"files": [...], "reason": "..."}} while a landing needs the full restart; the page shows it as a banner
# with the Restart button, and it clears itself once the restart has happened (owner_restart.status reads it).
APP_LANDED_CODE_NOTICE = "landed_code_notice"
# What a plugin-only landing did: {"rows": [...], "at": epoch seconds, "error": None | "..."}; the page's quiet line.
APP_LANDED_PLUGIN_SWAP = "landed_plugin_swap"
APP_LANDED_PLUGIN_SWAPS = "landed_plugin_swaps"
APP_LANDED_PLUGIN_ATTEMPT = "landed_plugin_attempt"
APP_OWNER_RESTART = "owner_restart"  # owner_restart.APP_OWNER_RESTART; named here so this module imports nothing of it
# Server Python with edits nobody has committed, as of the last look. A row whose own module is among them does not
# swap. A full restart waits only for one that cannot load (see _cannot_load): until 2026-11-09 any such file held every
# restart, and Thomas did not restart himself once in three days while 40 files other sessions had left sat there.
APP_LANDED_DIRTY = "landed_dirty_python"
# {"since": when landed code first had to wait for a running Build, "said": the landing the step log has named}.
APP_LANDED_HELD = "landed_code_held"
# How long landed code waits for running Builds before it asks them to stop after all (the drain below). Until
# 2026-11-10 it did not wait: each landing stopped every Build, and 25 landings began a restart that day.
BUILD_HOLD_S = 6 * 3600.0
CHECK_WORKERS = "check workers"
# What a restart waits for before any Build is asked to yield. On 2026-11-13 a restart yielded every Build at once and
# then waited 45 to 60 minutes for one check before your card, the whole fleet idle. Now, while any of these runs, Builds
# keep working and new ones may start; only no new check starts (precard.workers.close_admission), and a hand-in that
# arrives waits for the restart (hand_in_hold.wait_for_restart). Once none runs, the Builds yield as before.
CHECK_WORK = ("check threads", CHECK_WORKERS)
CHECKS_FINISHING = "checks_finishing"  # the restart report's phase while it waits for the checks
BUILDS_KEEP_WORKING = (
    "Builds keep working while the checks already running finish; no new check starts until after the restart. "
    "Then the Builds pause at their next step and carry on after the restart."
)
# {"head", "since", "phase", "waiting_for", "words"} while landed code waits for checks; owner_restart.status reads it.
APP_LANDED_CODE_CHECKS = "landed_code_checks"
DRAIN_SIGNAL_NAME = f"landed-code-reload-drain-{os.getpid()}-{uuid4().hex}"


def drain_signal_path() -> Path:
    return resolve_thomas_data_dir() / DRAIN_SIGNAL_NAME


# Keep in lockstep with cage_keepalive.SERVER_CODE: no imports from scripts/cage at runtime.
SERVER_CODE_PATHS = ("thomas", "scripts/cage", "scripts/monolith_source_loader.py", "scripts/breakglass_auth.py")
MARKER_NAME = "landed-code-reload-head"
TRAY_PORT_ENV = "THOMAS_TRAY_SERVER_PORT"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _tray_port() -> int | None:
    try:
        port = int(os.environ.get(TRAY_PORT_ENV, ""))
    except ValueError:
        return None
    return port if 0 < port <= 65535 and port != 8898 else None


def _reload_allowed() -> bool:
    return owner_desk.enabled() or _tray_port() is not None


def _caged_server_disabled() -> bool:
    return _tray_port() is None and (cage_shell.cage_root() / "caged_server.off").exists()


def _handled_marker() -> Path:
    port = _tray_port()
    name = f"{MARKER_NAME}-tray-{port}" if port is not None else MARKER_NAME
    return resolve_thomas_data_dir() / name


def loop_enabled(port: int) -> bool:
    """Watch the caged server or a tray-started server; tests opt in explicitly."""
    raw = str(os.environ.get("THOMAS_LANDED_CODE_RELOAD_LOOP") or "").strip().lower()
    if os.environ.get("PYTEST_CURRENT_TEST") and raw not in {"1", "true", "yes", "on"}:
        return False
    return (port == 8898 and owner_desk.enabled()) or (port != 8898 and port == _tray_port())


def _git(*args: str) -> str | None:
    try:
        result = run_git(["-C", str(REPO_ROOT), *args], timeout=4.0)
        return result.output() if result.ok else None
    except (OSError, RuntimeError, ValueError):
        return None


def _server_python(paths: str) -> list[str]:
    return [
        path
        for path in paths.replace("\n", "\0").split("\0")
        if path.endswith(".py") and any(path == root or path.startswith(root + "/") for root in SERVER_CODE_PATHS)
    ]


def _promoter_is_landing() -> bool:
    """A hand-in in the promoter's inbox holds the reload unless one of its cards is asking you (2026-10-26).

    A card can wait for you for hours. On 2026-10-26 one held effa5b43's reload for half an hour: every Build run that
    yielded for it, and every team waiting to start its done check, stayed stopped until the server was restarted by
    hand. The promoter asks one card at a time and lands only once every card is answered, so while a card asks it is
    waiting on you and lands nothing. An entry with no card record yet, or with every card answered, still holds it.
    """
    inbox = green_handoff.inbox_dir()
    if not inbox.is_dir():
        return False
    for entry in inbox.iterdir():
        if not entry.is_dir():
            continue
        try:
            record = json.loads((self_change_status.outbox_dir() / f"{entry.name}.pending.json").read_text("utf-8"))
        except (OSError, ValueError):
            return True
        cards = record.get("cards") if isinstance(record, dict) else None
        if not any(isinstance(card, dict) and card.get("state") == "asking" for card in cards or []):
            return True
    return False


def active_work(app: Any) -> tuple[str, ...]:
    waiting: list[str] = []
    if active_code_runs(app):
        waiting.append(BUILD_RUN)
    if workers.active_calls():
        waiting.append("check threads")
    # Work the last restart interrupted is carried on before the next restart, or a run of landings would never
    # resume it. A paused Thomas carries nothing on, so that wait would never end and no fix could load; what is
    # still waiting is written down for the next server (autopilot_restart._save_life), so nothing is lost.
    if autopilot_restart.report().get("pending") and not paused():
        waiting.append("restart pending")
    if _promoter_is_landing():
        waiting.append("promoter inbox")
    hand_ins = self_change_status.active_hand_ins()
    waiting.extend(name for name, count in hand_ins.items() if count)
    return tuple(waiting)


# What _landed_change answers when git could not say: not None, which means "nothing has landed". Each read has four
# seconds, and on a busy PC one running out was read as the change having gone away: the drain ended, the Builds were
# resumed, and the next look began it all again (nine times for one landing, 2026-11-09).
_UNREAD: Any = object()
_UNREAD_SAID: set[str] = set()


def _unread(what: str) -> Any:
    if what not in _UNREAD_SAID:  # once for each kind, not every half minute
        _UNREAD_SAID.add(what)
        log.warning("landed code reload: git could not say %s in time; leaving everything as it is until it can", what)
    step_log.record("reload_unread", what=what)
    return _UNREAD


async def _landed_change(app: Any) -> tuple[str, str, list[str]] | None | Any:
    """Only a clean, unhandled landed server Python change can wait for a reload; ``_UNREAD`` when git could not say."""
    if _caged_server_disabled():
        return None
    boot = str(app.get(APP_RUNTIME_GUARD_STATE, {}).get("boot", {}).get("source", {}).get("git_head") or "")
    if not boot:
        return None
    head = head_sha(REPO_ROOT) or await off_loop("landed_code_reload.head", _git, "rev-parse", "HEAD")
    if not head:
        return _unread("where dev is")
    if head == boot:
        return None
    # Rows a landing swapped in place are serving that landing's code already, so the next landing is measured from
    # it, not from boot: otherwise every later landing would swap the same rows again.
    base = str(app.get(APP_LANDED_SWAP_BASE) or boot)
    if head == base:
        return None
    changed = await off_loop(
        "landed_code_reload.diff", _git, "diff", "--name-only", "-z", base, head, "--", *SERVER_CODE_PATHS
    )
    if changed is None:
        return _unread("what changed")
    files = _server_python(changed)
    if not files:
        return None
    marker = _handled_marker()
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == head:
        return None
    dirty = await off_loop(
        "landed_code_reload.dirty", _git, "diff", "--name-only", "-z", "HEAD", "--", *SERVER_CODE_PATHS
    )
    if dirty is None:
        return _unread("what is uncommitted")
    if _caged_server_disabled():
        return None
    _set(app, APP_LANDED_DIRTY, _server_python(dirty))
    return boot, head, files


async def _finish_drain(app: Any) -> None:
    if app.get(APP_LANDED_CODE_DRAIN):
        await landed_code_resume.finish_drain(app)
    _clear_drain(app)
    if not app[APP_SHUTDOWN_EVENT].is_set() and not workers.generation_stopping():
        if not (app.get(APP_OWNER_RESTART) or {}).get("restarting"):
            workers.open_admission()  # no restart is pending any more: checks may start again
        await landed_code_resume.resume(app)


_NOT_READ = object()


def _clear_drain(app: Any) -> None:
    app.pop(APP_LANDED_CODE_DRAIN, None)
    app.pop(APP_LANDED_CODE_CHECKS, None)
    drain_signal_path().unlink(missing_ok=True)


def checks_in(work: Any) -> list[str]:
    """The checks (and their workers) in ``work`` that a restart waits for with every Build still working."""
    return [name for name in work if name in CHECK_WORK]


def _checks_finishing(app: Any, head: str, now: float, checking: list[str]) -> None:
    """Landed code needs a restart and checks run: hold new checks back, leave every Build working, and say so."""
    workers.close_admission()
    waiting = app.get(APP_LANDED_CODE_CHECKS)
    if not isinstance(waiting, dict) or waiting.get("head") != head:
        waiting = {"head": head, "since": now, "phase": CHECKS_FINISHING, "words": BUILDS_KEEP_WORKING}
        _set(app, APP_LANDED_CODE_CHECKS, waiting)
        step_log.record("reload_checks_finishing", head=head[:12], held_by=", ".join(checking))
        log.info("landed code waits for %s; Builds keep working and no new check starts", ", ".join(checking))
    waiting["waiting_for"] = list(checking)


def _signal_runs(drain: dict[str, Any], head: str, waited: float, held_by: list[str]) -> None:
    """Ask running Build agents to yield at their next step boundary (they read the signal file)."""
    # Atomic replace avoids a reader seeing an empty or partly written signal.
    signal = drain_signal_path()
    if not signal.exists() or signal.read_text(encoding="utf-8").strip() != head:
        temporary = signal.with_suffix(".tmp")
        temporary.write_text(head + "\n", encoding="utf-8")
        os.replace(temporary, signal)
    if not drain.get("signalled"):
        drain["signalled"] = True
        step_log.record("reload_yield", seconds=waited, head=head[:12], held_by=", ".join(held_by) or None)


def _module_files(plan: dict[str, Any]) -> list[str]:
    """The files a swap would load for ``plan``: each module as a file or a package."""
    names = {name for group in (plan.get("modules") or {}).values() for name in group}
    files: list[str] = []
    for name in sorted(names):
        base = name.replace(".", "/")
        files.extend((base + ".py", base + "/__init__.py"))
    return files


def _cannot_load(paths: list[str]) -> list[str]:
    """Which of these uncommitted files Python cannot read as code; a file that is gone is not one of them."""
    broken: list[str] = []
    for path in paths:
        try:
            compile((REPO_ROOT / path).read_bytes(), path, "exec", dont_inherit=True)
        except FileNotFoundError:
            continue
        except (SyntaxError, ValueError, OSError):
            broken.append(path)
    return broken


def _set(app: Any, key: str, value: Any) -> None:
    """Write a plain key on a started aiohttp app without its "changing a started app" warning."""
    getattr(app, "_state", app)[key] = value


def _restart_instead(app: Any, head: str, files: list[str], why: str, *, first: bool) -> bool:
    """A row that cannot be swapped while running gets the ordinary restart: say why, and answer "not handled"."""
    _set(
        app,
        APP_LANDED_CODE_NOTICE,
        {"notice": {"files": list(files), "reason": f"Thomas needs a full restart: {why}."}},
    )
    if first:
        step_log.record("reload_needs_restart", head=head[:12], files=len(files), why=why[:200])
        log.info("landed code needs the full restart: %s", why)
    return False


def _held_for_builds(app: Any, head: str, files: list[str], now: float) -> bool:
    """True while landed code waits for the Builds that are running, which it does for ``BUILD_HOLD_S``.

    It tells the page newer code is waiting and why, and writes one step-log row for each landing. The wait is counted
    from the first landing that had to wait, so a run of landings cannot put the restart off for ever."""
    held = app.get(APP_LANDED_HELD)
    if not isinstance(held, dict):
        held = {"since": now, "said": None}
        _set(app, APP_LANDED_HELD, held)
    if now - float(held["since"]) >= BUILD_HOLD_S:
        return False
    notice = dict((app.get(APP_LANDED_CODE_NOTICE) or {}).get("notice") or {"files": list(files), "reason": ""})
    base = str(notice.get("reason", "")).split(" Waiting:")[0]
    notice["reason"] = (
        f"{base} Waiting: a Build is running, and a landing does not stop one for {BUILD_HOLD_S / 3600:g} hours. "
        "This loads by itself when no Build is running; press Restart to load it now."
    ).strip()
    _set(app, APP_LANDED_CODE_NOTICE, {"notice": notice})
    if held["said"] != head:
        held["said"] = head
        step_log.record("reload_held", head=head[:12], files=len(files))
        log.info("landed code waits for the running Builds; it loads when none is running")
    return True


async def _swapped_in_place(app: Any, head: str, files: list[str]) -> bool:
    """Swap the rows a plugin-only landing changed, live; True when this watcher has nothing to drain for ``head``.

    Every Python landing used to retire the server, and with a landing every 10 to 20 minutes that stopped every Build
    run each time (six times in one evening, 2026-11-06). A landing whose Python all belongs to plugin rows is staged
    beside the live rows and published in one event-loop turn (landed_plugin_runtime.replace); one that fails to stage
    leaves the old rows serving and is told to you as a notice with the Restart button, and nothing is drained for it:
    retiring the server would stop every run to boot code that could not load. Anything the kernel or more than one
    plugin owns needs the full restart; the notice names those files and the drain below goes on as before.
    """
    from thomas.server.landed_plugin_swap import classify, swap
    from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

    try:
        plan = await off_loop("landed_code_reload.classify", classify, REPO_ROOT, files)
    except (OSError, ValueError, SyntaxError) as exc:
        log.warning("landed code could not be classified for a live swap; a restart will load it: %s", exc)
        plan = {"kernel_files": list(files)}
    if app.get(APP_RUNTIME_PLUGINS) is None:
        plan = {"kernel_files": list(files)}
    if plan["kernel_files"]:
        _set(
            app,
            APP_LANDED_CODE_NOTICE,
            {"notice": {"files": plan["kernel_files"], "reason": "Thomas needs a full restart: kernel files changed."}},
        )
        return False
    dirty = set(app.get(APP_LANDED_DIRTY) or ())
    held = sorted(path for path in _module_files(plan) if path in dirty)
    if held:
        # The row would load a file someone is still editing. Wait for its commit; nothing is cached, so the next look
        # swaps as soon as the file is clean.
        _set(
            app,
            APP_LANDED_CODE_NOTICE,
            {
                "notice": {
                    "files": held,
                    "reason": "The swap waits: these files have edits nobody has committed yet.",
                    "uncommitted": held,
                }
            },
        )
        return True
    attempt = app.get(APP_LANDED_PLUGIN_ATTEMPT)
    if isinstance(attempt, dict) and attempt.get("head") == head and attempt.get("needs_restart"):
        return _restart_instead(app, head, files, str(attempt["needs_restart"]), first=False)
    if not isinstance(attempt, dict) or attempt.get("head") != head:
        outcome = await swap(app, REPO_ROOT, files)
        attempt = {"head": head, **outcome}
        _set(app, APP_LANDED_PLUGIN_ATTEMPT, attempt)
        if outcome.get("needs_restart"):
            return _restart_instead(app, head, files, str(outcome["needs_restart"]), first=True)
        _set(
            app,
            APP_LANDED_PLUGIN_SWAP,
            {"rows": outcome.get("swapped_rows", []), "at": outcome.get("swapped_at"), "error": outcome.get("error")},
        )
        if outcome.get("error"):
            step_log.record("reload_swap_refused", head=head[:12], files=len(files), error=str(outcome["error"])[:200])
            _set(
                app,
                APP_LANDED_CODE_NOTICE,
                {
                    "notice": {
                        "files": list(files),
                        "reason": "Thomas needs a full restart: the plugin swap was refused and the old rows are "
                        f"still serving. {outcome['error']}",
                    }
                },
            )
            return True
        marker = _handled_marker()
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(head + "\n", encoding="utf-8")
        _set(app, APP_LANDED_SWAP_BASE, head)
        app.pop(APP_LANDED_CODE_NOTICE, None)
        swaps = app.get(APP_LANDED_PLUGIN_SWAPS)
        if not isinstance(swaps, list):
            swaps = []
            _set(app, APP_LANDED_PLUGIN_SWAPS, swaps)
        swaps.append(
            {"ok": True, "rows": outcome["swapped_rows"], "head": head, "swapped_at": outcome.get("swapped_at")}
        )
        step_log.record("reload_swap", head=head[:12], files=len(files), rows=",".join(outcome["swapped_rows"]))
        log.info("landed code swapped in place: rows %s for %s", outcome["swapped_rows"], head[:12])
    return True


async def check_once(
    app: Any,
    quiet_since: float | None,
    now: float,
    *,
    work: tuple[str, ...] | None = None,
    landed: tuple[str, str, list[str]] | None | object = _NOT_READ,
) -> float | None:
    """Swap a plugin-only landing in place; otherwise drain admitted work, then count a quiet interval before retiring."""
    if (app.get(APP_OWNER_RESTART) or {}).get("restarting"):
        return None  # the owner's restart is draining already (owner_restart); this watcher must not race it
    shutdown = app[APP_SHUTDOWN_EVENT]
    if shutdown.is_set() or workers.generation_stopping() or not _reload_allowed():
        await _finish_drain(app)
        return None
    if _caged_server_disabled():
        await _finish_drain(app)
        return None
    if landed is _NOT_READ:
        landed = await _landed_change(app)
    if landed is _UNREAD:
        return quiet_since  # git could not say: neither begin nor end anything on a guess
    if landed is None:
        app.pop(APP_LANDED_CODE_NOTICE, None)  # the restart happened, or the change went away: the notice clears
        app.pop(APP_LANDED_HELD, None)
        await _finish_drain(app)
        return None
    boot, head, files = landed
    marker = _handled_marker()
    if marker.exists() and marker.read_text(encoding="utf-8").strip() == head:
        await _finish_drain(app)
        return None
    if await _swapped_in_place(app, head, files):
        await _finish_drain(app)
        return None
    dirty = list(app.get(APP_LANDED_DIRTY) or ())
    broken = await off_loop("landed_code_reload.loadable", _cannot_load, dirty) if dirty else []
    if dirty:
        # Every start loads whatever is in the checkout, committed or not, so an edit that loads is running already and
        # is no reason to wait. One that cannot be read as Python would stop the new server from starting: wait for that.
        notice = dict((app.get(APP_LANDED_CODE_NOTICE) or {}).get("notice") or {"files": list(files), "reason": ""})
        notice["uncommitted"] = dirty
        if broken:
            shown = ", ".join(broken[:4]) + (f" and {len(broken) - 4} more" if len(broken) > 4 else "")
            base = str(notice.get("reason", "")).split(" Waiting:")[0]
            notice["reason"] = (
                f"{base} Waiting: {len(broken)} file(s) being edited cannot be loaded yet ({shown}).".strip()
            )
            notice["broken"] = broken
        else:
            notice.pop("broken", None)
        _set(app, APP_LANDED_CODE_NOTICE, {"notice": notice})
        if broken:
            await _finish_drain(app)
            return None
    if work is None:
        work = active_work(app)
    if BUILD_RUN in work and _held_for_builds(app, head, files, now):
        # A landing does not stop a running Build and holds no new start back: say that newer code is waiting, and
        # look again. On 2026-11-10 one landing stopped ten Builds ten minutes into their work and cost each about five.
        await _finish_drain(app)
        return None
    clock = app.get(APP_LANDED_CODE_DRAIN_CLOCK)
    if not isinstance(clock, dict) or now - float(clock.get("seen", now)) > RUN_YIELD_AFTER_S:
        clock = {"since": now}
        app[APP_LANDED_CODE_DRAIN_CLOCK] = clock
    clock["seen"] = now
    drain = app.get(APP_LANDED_CODE_DRAIN)
    checking = checks_in(work)
    if checking and not (isinstance(drain, dict) and drain.get("signalled")):
        # Checks run: every Build keeps working and new ones may start, with no clock that makes them yield; only no
        # new check starts. Until 2026-11-13 new starts were held here and the Builds yielded after 20 minutes.
        if drain is not None:
            app.pop(APP_LANDED_CODE_DRAIN, None)
        _checks_finishing(app, head, now, checking)
        return None
    app.pop(APP_LANDED_CODE_CHECKS, None)
    workers.close_admission()  # no new check starts while the Builds yield and the server retires
    if not isinstance(drain, dict) or drain.get("head") != head:
        drain = {"head": head, "since": clock["since"]}
        app[APP_LANDED_CODE_DRAIN] = drain
        log.info("landed code reload: holding new Code starts while active work drains")
        step_log.record("reload_drain", head=head[:12], files=len(files))
    others = [name for name in work if name != BUILD_RUN]
    waited = now - float(clock["since"])
    if not others or waited >= RUN_YIELD_AFTER_S:
        _signal_runs(drain, head, waited, others)
    # The launch lock serializes admission against this flag. Active runs yield
    # at an iteration boundary and record a resumable turn before shutdown.
    if work:
        landed_code_resume.remember(app)
        return None
    if quiet_since is not None and active_work(app):
        return None
    if quiet_since is None:
        quiet_since = now
    if now - quiet_since < RELOAD_QUIET_S:
        return quiet_since
    # Recheck the stop conditions after the off-loop git calls before recording the exit.
    if shutdown.is_set() or workers.generation_stopping() or not _reload_allowed() or _caged_server_disabled():
        await _finish_drain(app)
        return None
    if active_work(app):
        return None
    # No await between this final check and setting the shutdown event: the
    # admission gate cannot open another Code run in the middle of retirement.
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(head + "\n", encoding="utf-8")
    if shutdown.is_set() or workers.generation_stopping():
        _clear_drain(app)
        return None
    log.warning(
        "server reload: boot HEAD %s, current HEAD %s; changed Python %s; no work active for %s seconds",
        boot,
        head,
        files[:5],
        RELOAD_QUIET_S,
    )
    step_log.record("reload_retire", seconds=now - float(drain.get("since", now)), head=head[:12], files=len(files))
    shutdown.set()
    drain_signal_path().unlink(missing_ok=True)
    return quiet_since


def _admitted_checks(rows: list[dict[str, Any]]) -> int:
    """How many of the ledger's live rows are checks holding a place: a check, or a shard of one, in state admitted."""
    return sum(
        1
        for row in rows
        if row.get("state") == "admitted"
        and (row.get("kind") == "check" or str(row.get("id", "")).startswith("shard:"))
    )


def _checks_running() -> int:
    """Checks the capacity ledger says are running now; -1 when it cannot be read, which holds the reload too.

    A check runs as its own process, and the count of check threads alone did not hold the reload back: on 2026-11-06
    the server retired itself within a minute of each landing that changed Python (13:51, 14:38, 15:20) and ended
    checks 40 and 45 minutes into their run, nine shards still going, so no hand-in check finished that afternoon. The
    ledger lists every admitted check with its owner, and :func:`capacity_ledger.rows` keeps only the live owners.
    """
    try:
        return _admitted_checks(capacity_ledger.rows())
    except (OSError, RuntimeError, ValueError):
        log.warning("the capacity ledger could not be read to see whether checks are running", exc_info=True)
        return -1


async def waiting_work(app: Any) -> tuple[str, ...]:
    """What the reload is waiting on: the in-memory work plus any check the ledger shows running."""
    work = active_work(app)
    if CHECK_WORKERS not in work and await off_loop("landed_code_reload.checks", _checks_running):
        work = (*work, CHECK_WORKERS)
    return work


async def watch(app: Any) -> None:
    """Poll landed code and request the ordinary clean shutdown after draining."""
    shutdown = app[APP_SHUTDOWN_EVENT]
    quiet_since: float | None = None
    last_wait: tuple[str, ...] = ()
    while not shutdown.is_set() and not workers.generation_stopping():
        try:
            work = await waiting_work(app)
            landed = await _landed_change(app)
            if shutdown.is_set() or workers.generation_stopping():
                _clear_drain(app)
                return
            waiting = work if landed is not None else ()
            if waiting != last_wait:
                if waiting:
                    log.info("landed code reload waits for %s", ", ".join(waiting))
                last_wait = waiting
            quiet_since = await check_once(app, quiet_since, time.monotonic(), work=work, landed=landed)
            if shutdown.is_set():
                return
        except (OSError, ValueError, RuntimeError):
            log.exception("could not check whether landed code is ready for a quiet reload")
        try:
            await asyncio.wait_for(shutdown.wait(), timeout=RELOAD_CHECK_S)
        except asyncio.TimeoutError:
            pass
