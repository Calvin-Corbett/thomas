"""Tries a held hand-in again, on Autopilot's park loop (:mod:`thomas.server.autopilot_park`, every 30 s).

A held change (:mod:`thomas.server.hand_in_hold`) is tried again by :func:`tick` once it is due, on the server
whose port booked it (or a restarted server when that listener is gone), while no Build run or runner process is
working in its conversation and no other try of it is running in any server (``hand_in_hold.check_claim``).
A row whose turn is no longer current -- you stopped it, a steer of yours waits, a newer run wrote a turn -- is
removed, and the steer's run starts at once. A ``checking`` row another boot left behind was interrupted by a
restart: it is held, due again in a minute, and the chat's card follows it again with words that say what it waits for.

The route's own first try (``evolve_agent_autopilot._settle_thomas_project``) uses :func:`port_of` and
:func:`hold_if_unfinished` from here as well.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import socket
import time
from pathlib import Path
from typing import Any

from thomas.core.kernel import late, seams
from thomas.server import hand_in_hold
from thomas.server.app_keys import APP_LOCAL_PORT

log = logging.getLogger(__name__)
LOW_DISK_FREE_BYTES = 512 * 1024 * 1024  # below this, a try is not even started
_TASKS: set[asyncio.Task[Any]] = set()
_RUNNING: set[str] = set()  # conversations a try of this process is running for
_BUSY_WHY = "another hand-in is still using the check slot"


def _room_for_check() -> bool:
    """Read the live ledger and greens' drive once for all held checks in this tick."""
    from thomas.server import capacity_ledger, green_checkout
    from thomas.server.precard import CHECK_DISK_BYTES

    root = green_checkout.green_root()
    place = capacity_ledger.folder()
    with capacity_ledger.locks.locked(place, capacity_ledger.NAME):
        rows, _ = capacity_ledger._live(place)
    room = capacity_ledger.measure(root)
    return not capacity_ledger.refusal(
        rows,
        disk_bytes=CHECK_DISK_BYTES,
        memory_bytes=0,
        drive=capacity_ledger._drive(root),
        room=room,
        now=time.time(),
    )


def port_of(app: Any) -> int:
    return int(app.get(APP_LOCAL_PORT) or 0) if app is not None else 0


def _previous_listener_gone(port: int) -> bool:
    """A different listener still using the booked port must keep its own rows."""
    try:
        import psutil
    except ImportError:
        # A missing optional dependency must not strand holds after a restart.
        # A refused connection proves absence; a timeout/unknown error does not.
        try:
            addresses = socket.getaddrinfo("localhost", port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
        except OSError:
            return False
        if not addresses:
            return False
        for family, kind, proto, _, address in addresses:
            try:
                with socket.socket(family, kind, proto) as probe:
                    probe.settimeout(0.2)
                    probe.connect(address)
                    return False
            except ConnectionRefusedError:
                continue
            except OSError:
                return False
        return True

    try:
        return not any(
            conn.status == psutil.CONN_LISTEN and conn.laddr.port == port for conn in psutil.net_connections(kind="tcp")
        )
    except (OSError, psutil.Error):
        return False


def _current(root: Path, catalog: Path, cid: str, token: list[Any], app: Any) -> bool:
    """``still_current``, except that a conversation that cannot be read keeps its row: its try says why."""
    try:
        return hand_in_hold.still_current(root, catalog, cid, token, app=app)
    except hand_in_hold.ConversationUnreadable:
        return True


def hold_if_unfinished(project_root: Path, catalog_root: Path, cid: str, gen: list[Any] | None) -> None:
    """A try that ended with its row still ``checking`` (no card, no repair round) waits for the next one."""
    current = hand_in_hold.row(catalog_root, cid)
    if gen is not None and current and current.get("gen") == gen and current.get("state") == "checking":
        hand_in_hold.hold(project_root, catalog_root, cid, "hand-in", "the check did not finish", gen=gen)


async def run(app: Any, catalog: Path, *, startup: bool = False) -> None:
    """One :func:`tick` for the park loop, at startup and on each of its ticks. Never stops that loop.

    First, a finished project that was never handed in is booked for its hand-in (``hand_in_hold_unsettled``)."""
    from thomas.server import hand_in_hold_unsettled

    try:
        await asyncio.to_thread(hand_in_hold_unsettled.book_unsettled, app, catalog, port_of(app), startup=startup)
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
        log.exception("autopilot: could not look for finished projects that were never handed in")
    try:
        await tick(app, catalog)
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
        when = "at startup" if startup else "on this tick"
        log.exception("autopilot: the held hand-ins could not be tried %s; they are tried again next tick", when)


async def _follow(app: Any, held: dict[str, Any], catalog_root: Path) -> None:
    """After a restart, the chat that asked follows the project again, told what the change waits for."""
    cid, chat = str(held["cid"]), str(held.get("chat") or held["cid"])
    if chat == cid:
        return  # started from Build, not from a chat: no chat card to follow
    step, why = held.get("step") or "check", held.get("why") or "not completed"
    text = f"The finished change waits before your approval card: {step} could not run ({why})."
    await late.call(seams.FOLLOW_AFTER_RESTART, app, cid, Path(held["project_root"]), catalog_root, chat, text=text)


def _space_available(root: Path) -> bool:
    try:
        return shutil.disk_usage(root).free >= LOW_DISK_FREE_BYTES
    except OSError:
        return False


async def _check(app: Any, held: dict[str, Any], catalog_root: Path) -> None:
    """One try of a due row, which :func:`tick` has already moved to ``checking``."""
    from thomas.server import self_change_status
    from thomas.server.routes import evolve_agent_autopilot as route

    cid, root, token = str(held["cid"]), Path(held["project_root"]), held["gen"]
    if _restart_pending(app):
        await asyncio.to_thread(_defer_busy, catalog_root, cid, token, held, hand_in_hold.RESTART_WAIT)
        return
    try:
        current = await asyncio.to_thread(hand_in_hold.still_current, root, catalog_root, cid, token, app=app)
    except hand_in_hold.ConversationUnreadable as exc:  # held for the next try, saying why; never dropped
        await asyncio.to_thread(hand_in_hold.hold, root, catalog_root, cid, "check", str(exc), costly=False, gen=token)
        return
    if not current:
        await asyncio.to_thread(hand_in_hold.drop, catalog_root, cid, token)
        await _steered(app, root, catalog_root, cid)
        return
    try:
        # A server that is still alive may be inside its one-hour check: its claim keeps this try out.
        with hand_in_hold.check_claim(catalog_root, cid) as acquired:
            if not acquired or await asyncio.to_thread(self_change_status.being_handed_in, cid):
                await asyncio.to_thread(_defer_busy, catalog_root, cid, token, held)
                return
            if await asyncio.to_thread(hand_in_hold.row, catalog_root, cid) != held:
                return
            if not await asyncio.to_thread(_space_available, root):
                why = "not enough free space to check the finished change"
                await asyncio.to_thread(hand_in_hold.hold, root, catalog_root, cid, "disk space", why, costly=False)
                return
            if _restart_pending(app):
                await asyncio.to_thread(_defer_busy, catalog_root, cid, token, held, hand_in_hold.RESTART_WAIT)
                return
            await route._settle_thomas_project(root, catalog_root, cid, app=app, gen=token)
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError, MemoryError) as exc:
        log.exception("a try of the held hand-in of Thomas project %s failed", cid)
        why = str(exc) or type(exc).__name__
        await asyncio.to_thread(hand_in_hold.hold, root, catalog_root, cid, "check", why, gen=token)
    finally:
        current = await asyncio.to_thread(hand_in_hold.row, catalog_root, cid)
        if current and current.get("gen") == token and current.get("state") == "checking":
            if not await asyncio.to_thread(_current, root, catalog_root, cid, token, app):
                await asyncio.to_thread(hand_in_hold.drop, catalog_root, cid, token)
                await _steered(app, root, catalog_root, cid)
            elif await asyncio.to_thread(self_change_status.being_handed_in, cid):
                await asyncio.to_thread(_defer_busy, catalog_root, cid, token, current)
            else:
                why = "the hand-in attempt did not complete"
                await asyncio.to_thread(hand_in_hold.hold, root, catalog_root, cid, "check", why, gen=token)


def _restart_pending(app: Any) -> bool:
    """A restart is pending: the landed-code drain holds new starts, or no new check may start (``workers``)."""
    from thomas.server.landed_code_reload import APP_LANDED_CODE_DRAIN
    from thomas.server.precard import workers

    return bool(app.get(APP_LANDED_CODE_DRAIN)) or workers.admission_closed()


def _defer_busy(catalog: Path, cid: str, token: list[Any], held: dict[str, Any], why: str = _BUSY_WHY) -> None:
    """Another hand-in of it is running, or a restart is pending: wait for it, and give back the try this one took."""
    tries = max(0, int(held.get("tries") or 0) - 1)
    update = {**held, "state": "held", "tries": tries, "step": "check", "why": why, "next_at": hand_in_hold.clock()}
    hand_in_hold.change(catalog, cid, token, update, expected=held)


def _schedule(app: Any, held: dict[str, Any], catalog_root: Path) -> bool:
    """Run one try as its own task; False when this process already runs one for the conversation."""
    cid = str(held["cid"])
    if cid in _RUNNING:
        return False
    _RUNNING.add(cid)
    try:
        task = asyncio.create_task(_check(app, held, catalog_root), name=f"hand-in-hold:{cid}")
    except RuntimeError:
        _RUNNING.discard(cid)
        raise
    _TASKS.add(task)

    def finish_record() -> None:  # a task that died mid-try leaves its row held, never "checking" for ever
        why = "the check task ended before it could finish"
        step, root = str(held.get("step") or "check"), Path(str(held["project_root"]))
        hand_in_hold.hold(root, catalog_root, cid, step, why, gen=held["gen"], expected=held)

    def finished(done: asyncio.Task[Any]) -> None:
        _TASKS.discard(done)
        _RUNNING.discard(cid)
        if not done.cancelled() and done.exception() is not None:
            log.error("the held hand-in task for %s failed", cid, exc_info=done.exception())
        cleanup = asyncio.create_task(asyncio.to_thread(finish_record), name=f"hand-in-hold-cleanup:{cid}")
        _TASKS.add(cleanup)
        cleanup.add_done_callback(_TASKS.discard)

    task.add_done_callback(finished)
    return True


def _steer_ready(root: Path, catalog: Path, cid: str) -> dict[str, Any] | None:
    from thomas.server import thomas_project

    conversation = hand_in_hold.conversation_of(root, catalog, cid)
    if (
        conversation
        and thomas_project.held_steers(cid)
        and not thomas_project.stop_requested(conversation)
        and not thomas_project.settled_record(catalog, cid)
    ):
        return conversation
    return None


async def _steered(app: Any, root: Path, catalog: Path, cid: str) -> None:
    """Your steer that superseded a held change starts its run now, not after the hold's next due time."""
    from thomas.server.routes import evolve_agent_autopilot as route

    conversation = await asyncio.to_thread(_steer_ready, root, catalog, cid)
    if conversation:
        await route._start_steered_round(app, conversation, cid, catalog)


async def _gone(app: Any, held: dict[str, Any], catalog: Path, active: bool) -> None:
    """A row whose turn is no longer current: start a waiting steer, then remove the row -- unless something
    still runs in the conversation, or the steer's run was refused (both are left for a later tick)."""
    from thomas.server import autopilot_restart, self_change_status

    cid, root, token = str(held["cid"]), Path(str(held.get("project_root") or "")), held["gen"]
    if held.get("state") == "spent" and await asyncio.to_thread(
        lambda: hand_in_hold.generation(hand_in_hold.conversation_of(root, catalog, cid) or {}) == token
    ):
        return  # spent stays spent until a new turn arrives
    if active or cid in _RUNNING or self_change_status.being_handed_in(cid):
        return
    try:
        heard, orphaned = await asyncio.to_thread(autopilot_restart._runners_of, cid)
    except (OSError, RuntimeError, ValueError, AttributeError):
        return
    if heard or orphaned:
        return
    try:
        if await asyncio.to_thread(_steer_ready, root, catalog, cid):
            await _steered(app, root, catalog, cid)
            if await asyncio.to_thread(_steer_ready, root, catalog, cid):
                return  # the start was refused; leave its hold and steer as they are
    except (OSError, RuntimeError, ValueError, AttributeError, KeyError, TypeError):
        log.exception("could not start the steering for Thomas project %s", cid)
        return
    await asyncio.to_thread(hand_in_hold.change, catalog, cid, token, None, expected=held)


async def tick(app: Any, catalog_root: Path, *, boot: str = "") -> list[str]:
    """Try every due row of this server once; returns the conversations a try was started for."""
    from thomas.server import autopilot_restart, self_change_status
    from thomas.server.precard import NO_ROOM_PHRASE
    from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_RUNS, slot_active

    if _restart_pending(app):  # a held try waits for the restart: it is due at once on the next server
        return []

    catalog = Path(catalog_root)
    port, this_boot = port_of(app), str(boot or hand_in_hold.BOOT)
    started: list[str] = []
    rows = await asyncio.to_thread(hand_in_hold.rows, catalog)
    now = hand_in_hold.clock()
    waiting_for_room = any(
        row.get("state") == "held"
        and row.get("step") == "check"
        and NO_ROOM_PHRASE in str(row.get("why") or "")
        and float(row.get("next_at") or 0) > now
        and float(row.get("room_early_at") or 0) + hand_in_hold.RETRY_S <= now
        for row in rows
    )
    room_ready = False
    previous_listeners: dict[int, bool] = {}
    if waiting_for_room:
        try:
            room_ready = await asyncio.to_thread(_room_for_check)
        except (OSError, RuntimeError, ValueError) as exc:
            log.warning("held check's drive or reservation ledger could not be read: %s", exc)
    for held in rows:
        cid, token = str(held["cid"]), held.get("gen")
        if not port or not token:
            continue
        booked_port = int(held.get("port") or 0)
        if booked_port not in (0, port):
            # A restart may bind a new port. Do not steal a row from a live listener;
            # the generation/claim checks below still guard the abandoned row.
            if booked_port not in previous_listeners:
                previous_listeners[booked_port] = await asyncio.to_thread(_previous_listener_gone, booked_port)
            if not previous_listeners[booked_port]:
                continue
        root = Path(str(held.get("project_root") or ""))
        active = slot_active((app.get(APP_EVOLVE_AGENT_RUNS) or {}).get(cid))
        if not await asyncio.to_thread(_current, root, catalog, cid, token, app):
            await _gone(app, held, catalog, active)
            continue
        state, busy = held.get("state"), active or cid in _RUNNING or self_change_status.being_handed_in(cid)
        if state == "spent" or (state == "checking" and held.get("boot") == this_boot and cid in _RUNNING):
            continue
        if state == "checking" and (held.get("boot") != this_boot or booked_port not in (0, port)):
            # A different listener has inherited this abandoned try, even if the
            # Python process reused the boot identifier on a port change.
            if busy or not await asyncio.to_thread(hand_in_hold.claim_free, catalog, cid):
                continue
            why = "Thomas restarted while it was being checked"
            update = {
                **held,
                "state": "held",
                "why": why,
                "next_at": hand_in_hold.clock() + hand_in_hold.CHECK_GRACE_S,
                "boot": this_boot,
                "port": port,
            }
            if await asyncio.to_thread(hand_in_hold.change, catalog, cid, token, update, expected=held):
                try:
                    await _follow(app, update, catalog)
                except (OSError, RuntimeError, ValueError, AttributeError, KeyError, TypeError):
                    log.exception("could not follow the held Thomas project %s again", cid)
            continue
        due = float(held.get("next_at") or 0) <= hand_in_hold.clock()
        eligible_early = (
            room_ready
            and state == "held"
            and held.get("step") == "check"
            and NO_ROOM_PHRASE in str(held.get("why") or "")
            and float(held.get("room_early_at") or 0) + hand_in_hold.RETRY_S <= hand_in_hold.clock()
        )
        if (not due and not eligible_early) or busy:
            continue
        if not await asyncio.to_thread(hand_in_hold.claim_free, catalog, cid):
            continue
        try:
            heard, orphaned = await asyncio.to_thread(autopilot_restart._runners_of, cid)
        except (OSError, RuntimeError, ValueError, AttributeError):
            continue
        if heard or orphaned:
            continue
        if state == "checking":  # this boot's try ended without a word: it waits for the next
            step = str(held.get("step") or "check")
            why = "the hand-in attempt did not complete"
            await asyncio.to_thread(hand_in_hold.hold, root, catalog, cid, step, why, gen=token, expected=held)
            continue
        if state != "held":
            continue
        tries, strikes = int(held.get("tries") or 0), int(held.get("strikes") or 0)
        if hand_in_hold.retry_limited(held) and (
            tries >= hand_in_hold.MAX_TRIES or strikes >= hand_in_hold.MAX_STRIKES
        ):
            # An interrupted write still retains the second-look retry cap.
            if await asyncio.to_thread(
                hand_in_hold.change, catalog, cid, token, {**held, "state": "checking"}, expected=held
            ):
                step, why = str(held.get("step") or "check"), str(held.get("why") or "not completed")
                await asyncio.to_thread(hand_in_hold.hold, root, catalog, cid, step, why, costly=False, gen=token)
            continue
        update = {
            **held,
            "state": "checking",
            "tries": tries + 1,
            "next_at": hand_in_hold.clock() + hand_in_hold.RETRY_S,
            "port": port,
            "boot": this_boot,
        }
        if not due and eligible_early:
            update["room_early_at"] = hand_in_hold.clock()
        if await asyncio.to_thread(hand_in_hold.change, catalog, cid, token, update, expected=held):
            try:
                if _schedule(app, update, catalog):
                    started.append(cid)
                else:
                    await asyncio.to_thread(_defer_busy, catalog, cid, token, update)
            except RuntimeError:
                log.exception("could not start a try of the held hand-in of Thomas project %s", cid)
                await asyncio.to_thread(_defer_busy, catalog, cid, token, update)
                raise
    return started


__all__ = ["LOW_DISK_FREE_BYTES", "hold_if_unfinished", "port_of", "run", "tick"]
