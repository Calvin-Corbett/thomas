"""Give the oldest due queued Thomas project a turn when Build and the machine have room."""

from __future__ import annotations

import asyncio
import errno
import logging
import os
import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.core import machine_capacity
from thomas.core.kernel import late, seams
from thomas.forge.anvil import forge_code_store
from thomas.server import (
    autopilot_hold_tick,
    capacity_ledger,
    green_checkout,
    self_improvement_planner,
    self_project_queue,
    serve_instance_guard,
    thomas_project,
)
from thomas.server.app_keys import APP_PRAXIS_START_CODE_RUN
from thomas.server.landed_code_reload import APP_LANDED_CODE_DRAIN
from thomas.server.precard import CHECK_DISK_BYTES
from thomas.server.routes import self_project_routes

log = logging.getLogger(__name__)
MAX_START_TRIES = 5
RETRY_AFTER_S = 600
START_GRACE_S = 120
_in_flight: set[str] = set()
_start_tasks: set[asyncio.Task[None]] = set()
_selecting = False


def _active(row: dict[str, Any]) -> bool:
    # A green copy the listing skipped as unreadable may be a working team: it holds its slot (self_project_unreadable).
    return row.get("state") in {"running", "paused", "unreadable"} or str(row.get("state", "")).startswith(
        "repair round "
    )


def _active_count(projects: list[dict[str, Any]], running: set[str]) -> int:
    active = [row for row in projects if _active(row)]
    identified = {row["conversation_id"] for row in active if row.get("conversation_id")}
    return max(len(active), len(running | identified))


def capacity_blocker(active: int, now: float) -> str | None:
    """Describe the first resource that prevents another project from starting."""
    memory = machine_capacity._memory()
    if memory[0] is None or memory[1] is None:
        return "Machine memory could not be read."
    refusal = machine_capacity.admission_refusal(active)
    if refusal:
        return refusal
    return (
        capacity_ledger.refusal(
            capacity_ledger.rows(),
            disk_bytes=CHECK_DISK_BYTES,
            memory_bytes=0,
            drive=capacity_ledger._drive(green_checkout.green_root()),
            room=capacity_ledger.measure(green_checkout.green_root()),
            now=now,
        )
        or None
    )


def _registered_queue_ids(by_id: dict[str, dict[str, Any]], running: set[str]) -> set[str]:
    return {queue_id for queue_id, record in by_id.items() if record.get("conversation_id") in running}


def _queue_projects(projects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {row["queue_id"]: row for row in projects if row.get("queue_id")}


def _queue_conversations(catalog: Any, wanted: set[str]) -> dict[str, dict[str, Any]]:
    """Check only unresolved starts for a recorded id; do not scan all greens."""
    by_id: dict[str, dict[str, Any]] = {}
    folder = forge_code_store.conversations_dir(catalog)
    for conversation in self_project_routes._conversations(folder, strict=True):
        record = conversation.get("thomas_project") or {}
        queue_id = record.get("queue_id")
        if queue_id in wanted:
            by_id[queue_id] = {**record, "conversation_id": conversation["id"]}
    return by_id


async def project_listing(app: Any) -> dict[str, Any]:
    """Use the project route's shared, bounded listing refresh."""
    from thomas.server.routes.self_project_listing_cache import read_listing

    slot = app["self_project_listing_slot"]
    snapshot = slot.get("snapshot")
    if (
        snapshot is not None
        and not slot.get("dirty")
        and not slot.get("invalidated")
        and not slot.get("error")
        and time.monotonic() - slot.get("updated", 0) <= 2
    ):
        return snapshot
    await read_listing(
        slot,
        thomas_project._catalog_root(),
        lambda: self_project_routes.running_projects(app),
        self_project_routes.read_projects,
    )
    return _cached_listing(app)


def _cached_listing(app: Any) -> dict[str, Any]:
    slot = app["self_project_listing_slot"]
    report = slot.get("snapshot")
    if (
        not report
        or report.get("ok") is False
        or report.get("incomplete")
        or slot.get("dirty")
        or slot.get("invalidated")
        or slot.get("pending_starts")
        or slot.get("error")
        or slot.get("incomplete")
        or slot.get("unreadable")
        or report.get("unreadable")
        or slot.get("snapshot") is not report
    ):
        return {"projects": [], "unreadable": ["project list is incomplete"]}
    return report


def queue_status(app: Any, data: dict[str, Any]) -> dict[str, Any]:
    """Count active projects from the shared snapshot after its refresh is requested."""
    try:
        running = self_project_routes.running_projects(app)
        captured_at = app["self_project_listing_slot"].get("captured_at", 0)
        listing = _cached_listing(app)
        if listing.get("unreadable"):
            return {"running": None, "blocked_by": "Project workspaces could not all be read."}
        snapshot_ids = {row.get("conversation_id") for row in listing["projects"]}
        if any(
            row.get("started_at", 0) > captured_at and row.get("conversation_id") not in snapshot_ids
            for row in data["started"]
        ):
            slot = app["self_project_listing_slot"]
            task = slot.get("task")
            if task is None or task.done():
                slot["dirty"] = True
            return {"running": None, "blocked_by": "Project capacity changed; try again after the list refreshes."}
        count = _active_count(listing["projects"], running)
        starting_rows = [row for row in data["queued"] if row.get("starting")]
        starting = len(starting_rows)
        # An unresolved start reserves capacity until the starter reconciles it.
        # Status must never scan the catalog to recover a missing queue_id.
        active_ids = running | {
            row["conversation_id"] for row in listing["projects"] if _active(row) and row.get("conversation_id")
        }
        registered_ids = _registered_queue_ids(_queue_projects(listing["projects"]), active_ids)
        unregistered = sum(row["id"] not in registered_ids for row in starting_rows)
        if app.get(APP_LANDED_CODE_DRAIN):
            reason = "Server reload is draining current work."
        elif os.environ.get("THOMAS_OWNER_DESK") != "1":
            reason = "Automatic project starts require the caged server."
        elif app.get(APP_PRAXIS_START_CODE_RUN) is None:
            reason = "The project start service is unavailable."
        else:
            reason = capacity_blocker(_active_count(listing["projects"], running) + unregistered, time.time())
        if _cached_listing(app) is not listing or self_project_routes.running_projects(app) != running:
            return {"running": None, "blocked_by": "Project capacity changed; try again after the list refreshes."}
        return {"running": count, "starting": starting, "blocked_by": reason}
    except Exception:
        log.exception("Could not measure queued Thomas project capacity")
        return {"running": None, "blocked_by": "Project capacity could not be measured."}


def _due(row: dict[str, Any], port: int, now: float) -> bool:
    return (
        not row.get("starting")
        and not row.get("given_up")
        and int(row.get("tries") or 0) < MAX_START_TRIES
        and now - float(row.get("last_tried_at") or 0) >= RETRY_AFTER_S
    )


def _record_failure(row: dict[str, Any], reason: str, now: float) -> None:
    row.pop("starting", None)
    row["tries"] = int(row.get("tries") or 0) + 1
    row["last_reason"] = reason
    row["last_tried_at"] = now
    row["failed_at"] = now
    row["given_up"] = row["tries"] >= MAX_START_TRIES


def _finish(catalog: Any, queue_id: str, result: dict[str, Any]) -> None:
    def update(data: dict[str, Any]) -> None:
        for index, row in enumerate(data["queued"]):
            if row["id"] == queue_id:
                data["queued"].pop(index)
                for key in ("starting", "failed_at", "last_reason", "start_blocker", "recovery_probes", "given_up"):
                    row.pop(key, None)
                data["started"].insert(
                    0,
                    {
                        **row,
                        "conversation_id": result["conversation_id"],
                        "execution_id": result["execution_id"],
                        "started_at": time.time(),
                    },
                )
                data["started"] = data["started"][:50]
                break

    self_project_queue.change(catalog, update)


def _failed(catalog: Any, queue_id: str, reason: str, blocker=None) -> None:
    def update(data: dict[str, Any]) -> None:
        for row in list(data["queued"]):
            if row["id"] == queue_id:
                _record_failure(row, reason, time.time())
                if blocker is not None:
                    row["start_blocker"] = blocker
                else:
                    row.pop("start_blocker", None)
                break

    self_project_queue.change(catalog, update)


def _release_start(catalog: Any, queue_id: str) -> None:
    def release(data: dict[str, Any]) -> None:
        for queued in data["queued"]:
            if queued["id"] == queue_id:
                queued.pop("starting", None)
                break

    self_project_queue.change(catalog, release)


async def _start(app: Any, catalog: Any, row: dict[str, Any], port: int) -> None:
    queue_id = row["id"]
    try:
        if app.get(APP_LANDED_CODE_DRAIN):
            await asyncio.to_thread(_release_start, catalog, queue_id)
            return
        if row.get("origin") and not await asyncio.to_thread(
            lambda: self_improvement_planner.enabled(self_project_queue.read(catalog))
        ):
            await asyncio.to_thread(_release_start, catalog, queue_id)
            return
        meta = {"queue_id": queue_id, "queued_at": row["queued_at"]}
        if row.get("chat_session_id"):
            meta["chat_session_id"] = row["chat_session_id"]
        if app.get(APP_LANDED_CODE_DRAIN):
            await asyncio.to_thread(_release_start, catalog, queue_id)
            return
        try:
            result = await thomas_project.start_thomas_project(
                app, request=row["request"], settings=row["settings"], port=port, meta=meta
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("Queued Thomas project %s could not start: %s", queue_id, exc)
            try:
                blocker = _start_blocker(exc)
                await asyncio.to_thread(_failed, catalog, queue_id, str(exc), blocker)
            except Exception:
                log.exception("Could not record queued Thomas project start failure")
        else:
            app["self_project_listing_slot"]["dirty"] = True
            try:
                await asyncio.to_thread(_finish, catalog, queue_id, result)
            except asyncio.CancelledError:
                raise
            except Exception:
                # Keep the starting mark: the next tick can find the project's queue_id.
                log.exception("Could not record queued Thomas project %s after start", queue_id)
    finally:
        _in_flight.discard(queue_id)


def _reconcile(
    catalog: Any,
    port: int,
    projects: list[dict[str, Any]],
    running: set[str],
    captured_at: float = 0,
    snapshot_current: Callable[[], bool] = lambda: True,
    recovery: dict[str, Any] | None = None,
) -> tuple[set[str], bool]:
    by_id = _queue_projects(projects)
    snapshot_ids = {row.get("conversation_id") for row in projects}
    refresh_needed = False
    for row in projects:
        record = row.get("thomas_project") or {}
        if record.get("queue_id"):
            by_id[record["queue_id"]] = row
    queued = self_project_queue.read(catalog)["queued"]
    # In-memory starts already own a reservation; only interrupted starts need recovery IO.
    wanted = {row["id"]: row["starting"] for row in queued if row.get("starting") and row["id"] not in _in_flight}
    missing = {
        qid
        for qid in wanted.keys() - by_id.keys()
        if int(wanted[qid].get("pid") or 0) == os.getpid()
        or not serve_instance_guard.pid_alive(int(wanted[qid].get("pid") or 0))
    }
    if missing:
        checked = {qid: dict(wanted[qid]) for qid in missing}
        if (
            recovery is not None
            and recovery.get("checked") == checked
            and (missing <= recovery["records"].keys() or time.time() < recovery.get("retry_at", 0))
        ):
            recovered = recovery["records"]
        else:
            recovered = _queue_conversations(catalog, missing)
            if recovery is not None:
                recovery.update(checked=checked, records=recovered, live={}, retry_at=time.time() + START_GRACE_S)
        refresh_needed = any(row.get("conversation_id") not in snapshot_ids for row in recovered.values())
        by_id.update(recovered)
        missing -= by_id.keys()
        if missing and any(captured_at <= float(wanted[qid].get("at") or 0) + START_GRACE_S for qid in missing):
            # Wait through the start's grace period before requesting one shared refresh.
            refresh_needed |= any(time.time() >= float(wanted[qid].get("at") or 0) + START_GRACE_S for qid in missing)
        for row in projects:
            if not missing:
                break
            if row.get("queue_id") or not row.get("execution_id") or not row.get("conversation_id"):
                continue
            key = (row["execution_id"], row["conversation_id"])
            live_reads = recovery.setdefault("live", {}) if recovery is not None else {}
            if key not in live_reads:
                live_reads[key] = thomas_project._read_live(
                    green_checkout.green_root() / "work" / row["execution_id"], catalog, row["conversation_id"]
                )
            record = (live_reads[key] or {}).get("thomas_project") or {}
            queue_id = record.get("queue_id")
            if queue_id in missing:
                by_id[queue_id] = row
                missing.remove(queue_id)

    def update(data: dict[str, Any]) -> None:
        for row in list(data["queued"]):
            if row["id"] not in wanted or row.get("starting") != wanted[row["id"]] or row["id"] in _in_flight:
                continue
            project = by_id.get(row["id"])
            if project and project.get("conversation_id") and project.get("execution_id"):
                data["queued"].remove(row)
                data["started"].insert(
                    0,
                    {
                        **row,
                        "conversation_id": project["conversation_id"],
                        "execution_id": project["execution_id"],
                        "started_at": time.time(),
                    },
                )
                data["started"] = data["started"][:50]
            elif (
                row["id"] in missing
                and captured_at > float(wanted[row["id"]].get("at") or 0) + START_GRACE_S
                and snapshot_current()
            ):
                row["starting"] = None
                data["queued"].remove(row)
                data["given_up"].insert(
                    0,
                    {
                        **row,
                        "failed_at": time.time(),
                        "reason": "The server stopped before this project registered a start. It will retry.",
                    },
                )
                data["given_up"] = data["given_up"][:50]

    self_project_queue.change(catalog, update)
    return _registered_queue_ids(by_id, running), refresh_needed


def _auto_due(row: dict[str, Any], data: dict[str, Any], port: int, now: float) -> bool:
    if row.get("origin") and not self_improvement_planner.enabled(data):
        return False
    return _due(row, port, now)


def _disk_blocker_cleared(row: dict) -> bool:
    reason = str(row.get("last_reason") or "").lower()
    if (row.get("start_blocker") or {}).get("kind") != "disk" and not any(
        text in reason for text in ("disk full", "no space left", "not enough space", "errno 28", "winerror 112")
    ):
        return False
    try:
        path = green_checkout.green_root()
        while not path.exists() and path != path.parent:
            path = path.parent
        return shutil.disk_usage(path).free >= 512 * 1024 * 1024
    except OSError:
        return False


def _blocker_cleared(row: dict) -> bool:
    if _disk_blocker_cleared(row):
        return True
    blocker = row.get("start_blocker") or {}
    if blocker.get("kind") != "permission":
        return False
    try:
        path = Path(blocker["path"])
        if path.is_dir():
            next(path.iterdir(), None)
            with tempfile.TemporaryFile(dir=path) as probe:
                probe.write(b"permission check")
                probe.flush()
        else:
            with path.open("r+b") as stream:
                stream.read(1)
        return True
    except (OSError, ValueError, KeyError):
        return False


def _start_blocker(exc: Exception) -> dict[str, Any] | None:
    if isinstance(exc, PermissionError) and exc.filename:
        return {"kind": "permission", "path": str(exc.filename)}
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return {"kind": "transient"}
    if isinstance(exc, OSError):
        if exc.errno == errno.ENOSPC or getattr(exc, "winerror", None) == 112:
            return {"kind": "disk"}
        elif exc.errno in {errno.EAGAIN, errno.ENOMEM, errno.EMFILE, errno.ENFILE, errno.EBUSY, errno.EINTR} or getattr(
            exc, "winerror", None
        ) in {8, 14, 32, 33, 1450, 1455}:
            return {"kind": "transient", "errno": exc.errno}
        return {"kind": "os_error", "errno": exc.errno}
    return None


def _transient_probe_due(row: dict[str, Any], now: float) -> bool:
    blocker = row.get("start_blocker") or {}
    reason = str(row.get("last_reason") or row.get("reason") or "").lower()
    if blocker:
        if blocker.get("kind") != "transient":
            return False
    elif not any(
        text in reason
        for text in ("preparation exceeded", "preparation stalled", "timed out", "timeout", "build is busy")
    ):
        return False
    probes = min(max(int(row.get("recovery_probes") or 0), 0), 6)
    delay = min(3600, RETRY_AFTER_S * 2 ** (probes + 1))
    return now - float(row.get("last_tried_at") or row.get("failed_at") or 0) >= delay


def _rearm_failure(row: dict[str, Any], now: float) -> None:
    if _blocker_cleared(row):
        row.update(tries=0, given_up=False)
        for key in ("last_reason", "failed_at", "start_blocker", "recovery_probes"):
            row.pop(key, None)
    elif _transient_probe_due(row, now):
        # Admit one attempt, not another batch; a refusal exhausts it again.
        row.update(tries=MAX_START_TRIES - 1, given_up=False)
        row["recovery_probes"] = int(row.get("recovery_probes") or 0) + 1


def _retry_failures(data: dict[str, Any], projects: list[dict[str, Any]], now: float) -> None:
    registered = _queue_projects(projects)
    for row in list(data["given_up"]):
        if row["id"] in registered:
            data["given_up"].remove(row)
        elif now - float(
            row.get("failed_at") or row.get("last_tried_at") or row.get("queued_at") or now
        ) >= RETRY_AFTER_S and (
            _blocker_cleared(row)
            or (
                not row.get("recovery_probes")
                and (
                    row.get("reason") == "The server stopped before this project registered a start. It will retry."
                    or "start could not be confirmed" in str(row.get("reason") or "").lower()
                )
            )
        ):
            data["given_up"].remove(row)
            recovered = {**row, "tries": 0, "starting": None}
            for key in ("given_up", "failed_at", "reason", "last_reason", "last_tried_at", "start_blocker"):
                recovered.pop(key, None)
            data["queued"].append(recovered)
        elif _transient_probe_due(row, now):
            _rearm_failure(row, now)
            data["given_up"].remove(row)
            data["queued"].append(row)
    for row in list(data["queued"]):
        if row.get("given_up") and row["id"] in registered:
            data["queued"].remove(row)
        elif (
            row.get("given_up")
            and now - float(row.get("failed_at") or row.get("last_tried_at") or now) >= RETRY_AFTER_S
        ):
            _rearm_failure(row, now)


def _select(catalog: Any, app: Any, port: int, now: float) -> dict[str, Any] | None:
    data = self_project_queue.read(catalog)  # Only IO on an empty or not-yet-due tick.
    if not data["given_up"] and not any(
        _auto_due(row, data, port, now)
        or row.get("starting")
        or (
            row.get("given_up")
            and now - float(row.get("failed_at") or row.get("last_tried_at") or now) >= RETRY_AFTER_S
        )
        for row in data["queued"]
    ):
        return None
    running = self_project_routes.running_projects(app)
    # Read age first: a refresh must not lend its newer timestamp to older project rows.
    captured_at = app["self_project_listing_slot"].get("captured_at", 0)
    listing = _cached_listing(app)
    if listing.get("unreadable"):
        log.warning("Cannot count Thomas projects: unreadable greens: %s", listing["unreadable"])
        return None
    projects = listing["projects"]
    self_project_queue.change(catalog, lambda data: _retry_failures(data, projects, now))
    slot = app["self_project_listing_slot"]
    recovery = slot.get("recovery")
    if recovery is None or recovery.get("snapshot") is not listing:
        recovery = {"snapshot": listing}
        slot["recovery"] = recovery
    active_ids, refresh_needed = _reconcile(
        catalog, port, projects, running, captured_at, lambda: _cached_listing(app) is listing, recovery
    )
    if refresh_needed:
        slot = app["self_project_listing_slot"]
        task = slot.get("task")
        # Recovery needs a newer capture, not repeated invalidation of the scan already running.
        if task is None or task.done():
            slot["dirty"] = True
        return None
    data = self_project_queue.read(catalog)
    snapshot_ids = {row.get("conversation_id") for row in projects}
    if any(
        row.get("started_at", 0) > captured_at and row.get("conversation_id") not in snapshot_ids
        for row in data["started"]
    ):
        slot = app["self_project_listing_slot"]
        task = slot.get("task")
        if task is None or task.done():
            slot["dirty"] = True
        return None
    due = next((row for row in data["queued"] if _auto_due(row, data, port, now)), None)
    if due is None:
        return None
    # Planner rows booked before the guarded preset fix used the obsolete "standard" value.
    if due.get("origin") and (due.get("settings") or {}).get("guardrails") == "standard":
        due = {**due, "settings": {**due["settings"], "guardrails": "guarded"}}
    checked = self_project_routes._checked(
        {"request": due.get("request"), "settings": due.get("settings"), "chat_session_id": due.get("chat_session_id")}
    )
    if isinstance(checked, web.Response):
        import json

        reason = json.loads(checked.body)["error"]

        def give_up(data: dict[str, Any]) -> None:
            for row in list(data["queued"]):
                if row["id"] == due["id"] and _auto_due(row, data, port, time.time()):
                    data["queued"].remove(row)
                    data["given_up"].insert(0, {**row, "reason": reason})
                    data["given_up"] = data["given_up"][:50]

        self_project_queue.change(catalog, give_up)
        return None
    reservations = {row["id"] for row in data["queued"] if row.get("starting") and row["id"] not in active_ids}
    started_ids = {row["id"] for row in data["started"]}
    starting = sum(bool(row.get("starting")) and row["id"] not in active_ids for row in data["queued"])
    reason = capacity_blocker(_active_count(projects, running) + starting, now)
    if reason:
        log.info("Queued Thomas project waiting: %s", reason)
        return None

    def mark(data: dict[str, Any]) -> dict[str, Any] | None:
        # Capacity was checked before entering the queue lock; do not read the
        # ledger again here because it uses the same non-reentrant lock.
        # Validate the due row and newly marked starts against the latest queue state.
        other_starts = sum(bool(row.get("starting")) and row["id"] not in active_ids for row in data["queued"])
        if other_starts > starting:
            return None
        for row in data["queued"]:
            if row["id"] == due["id"] and _auto_due(row, data, port, time.time()):
                if _cached_listing(app) is not listing or self_project_routes.running_projects(app) != running:
                    return None
                current_reservations = {
                    item["id"] for item in data["queued"] if item.get("starting") and item["id"] not in active_ids
                }
                if (
                    not current_reservations.issubset(reservations)
                    or {item["id"] for item in data["started"]} != started_ids
                ):
                    return None
                if row.get("origin") and (row.get("settings") or {}).get("guardrails") == "standard":
                    row["settings"] = {**row["settings"], "guardrails": "guarded"}
                row["starting"] = {"pid": os.getpid(), "at": time.time()}
                return dict(row)
        return None

    return self_project_queue.change(catalog, mark)


def _room_for_wider_scan(app: Any) -> bool:
    return (
        not app.get(APP_LANDED_CODE_DRAIN)
        and self_improvement_planner.enabled({})
        and capacity_blocker(len(self_project_routes.running_projects(app)), time.time()) is None
    )


async def tick(app: Any, catalog: Any = None) -> None:
    global _selecting
    # The caged server is the sole automatic planner/queue worker. The desktop
    # server shares the catalog but must not book or claim its projects, even
    # when a caller supplies the catalog explicitly.
    if os.environ.get("THOMAS_OWNER_DESK") != "1" or app.get(APP_LANDED_CODE_DRAIN):
        return
    port = autopilot_hold_tick.port_of(app)
    if not port or _selecting or app.get(APP_PRAXIS_START_CODE_RUN) is None:
        return
    _selecting = True
    listing_requested = False
    try:
        catalog = catalog if catalog is not None else thomas_project._catalog_root()
        await asyncio.to_thread(
            self_improvement_planner.scan,
            catalog,
            port,
            wider_when_empty=lambda: _room_for_wider_scan(app),
        )
        while not app.get(APP_LANDED_CODE_DRAIN):
            if not listing_requested:
                data = await asyncio.to_thread(self_project_queue.read, catalog)
                if data["given_up"] or any(
                    _auto_due(row, data, port, time.time()) or row.get("starting") or row.get("given_up")
                    for row in data["queued"]
                ):
                    await project_listing(app)
                listing_requested = True
            selected = await asyncio.to_thread(_select, catalog, app, port, time.time())
            if selected is None:
                break
            _in_flight.add(selected["id"])
            task = asyncio.create_task(_start(app, catalog, selected, port))
            _start_tasks.add(task)
            task.add_done_callback(_start_tasks.discard)
    except self_project_queue.QueueUnreadable:
        log.exception("Queued Thomas projects could not be read")
    except Exception:
        log.exception("Could not check capacity for a queued Thomas project")
    finally:
        _selecting = False


late.provide(seams.PROJECT_QUEUE_TICK, lambda app: tick(app))
