"""Starting a Thomas project: a green copy of Thomas's own source, its conversation, and Build's team in it.

Moved out of :mod:`thomas.server.thomas_project` unchanged when Part 2 of the production line began (spec 2026-10-12
Part 2, "Size first"): that file was 795 lines, five under the repo's 800-line rule, and Part 2 adds work orders to the
start. Every name here still resolves as ``thomas_project.<name>`` (that module's ``__getattr__``), so no caller moved.
What the start takes from ``thomas_project`` -- ``_catalog_root``, its errors, the title and the team's notes -- is
looked up there each time it runs, so a test that patches ``thomas_project._catalog_root`` still reaches it.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from thomas.core import step_log
from thomas.core.acceptance_notes import THOMAS_NOTES_END, THOMAS_NOTES_START
from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.server import green_checkout, green_handoff, repair_ledger
from thomas.server import thomas_project as _tp
from thomas.server.app_keys import APP_PRAXIS_START_CODE_RUN
from thomas.server.thomas_project_stall import Progress, wait_for_preparation, watch_copy

log = _tp.log  # one logger for the whole Thomas project, as before the move

# `thomas_project` fields the caller's own `meta` can never set: `execution_id`
# names the green this record belongs to, and `settled_at` is written exactly
# once, by `settle_if_finished` itself, never by a start request.
_RESERVED_META_FIELDS = ("execution_id", "settled_at")


# Polling reports elapsed preparation time; it never limits how long a start may take.
_POLL_S = 1.0
_Progress = Progress


async def start_thomas_project(
    app: Any,
    *,
    request: str,
    settings: dict[str, Any],
    port: int,
    green: green_checkout.Green | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reserve admission until preparation completes, raises a real fault, or is explicitly cancelled."""
    slot = app.setdefault("self_project_listing_slot", {})
    slot["pending_starts"] = slot.get("pending_starts", 0) + 1
    slot["dirty"] = True
    progress = _Progress()
    try:
        task = asyncio.create_task(
            _start_thomas_project(
                app, request=request, settings=settings, port=port, green=green, meta=meta, progress=progress
            )
        )
        try:
            return await wait_for_preparation(task, progress, _POLL_S)
        except BaseException:
            task.cancel()
            task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
            raise
    finally:
        slot["pending_starts"] -= 1
        slot["dirty"] = True


async def _start_thomas_project(
    app: Any,
    *,
    request: str,
    settings: dict[str, Any],
    port: int,
    green: green_checkout.Green | None = None,
    meta: dict[str, Any] | None = None,
    progress: _Progress | None = None,
) -> dict[str, Any]:
    """Make (or reuse) a green copy of Thomas's own source and start Build's team in it.

    ``green``, when given, is used instead of making a new one -- the caller
    owns it, so a refused start raises without removing it. ``meta`` merges
    extra fields onto the stored ``thomas_project`` record (a ratchet
    candidate's purpose and SHA, for instance); ``execution_id`` and
    ``settled_at`` are reserved and cannot be overridden this way.

    The conversation is created (and, so the live server's own start route
    can find it again by id instead of minting a second one, bound into its
    project registry) BEFORE the start call, so the run's very first turn --
    and everything the run itself writes -- lands on the one conversation
    that carries ``thomas_project``. Everything from the conversation's
    creation onward is one unit: ANY exception, ``asyncio.CancelledError``
    included -- not only a refused start -- unwinds it, forgetting the
    registry row always and removing a green this call made itself (never
    one a caller passed in), then re-raising whatever was caught. A cleanup
    failure is logged, never allowed to replace it. A cancel that lands
    while ``create_green`` is still running in its thread is handled by
    :func:`_create_green`: the green it finishes making is removed too.

    `create_green`, `bind_conversation` and `remove_green` each run through
    ``asyncio.to_thread`` (fix round 2: measured 5-7s stalls on a real green
    without this -- every self-change request would have held the whole
    server that long).
    """
    progress = progress or _Progress()
    requested_at = time.time()
    if meta:
        for field in ("queued_at", "requested_at"):
            value = meta.get(field)
            if isinstance(value, (int, float)) and 0 < value <= requested_at:
                requested_at = value
                break
    blue = await asyncio.to_thread(forge_code_projects.thomas_source_repo_root)
    if blue is None:
        raise _tp.ThomasProjectError("Thomas's own source checkout could not be found")

    owns_green = green is None
    began = time.monotonic()
    if green is None:
        progress.touch("copying Thomas's source")
        green = await _create_green(blue, f"thomas-{uuid4().hex[:12]}", progress)
    progress.touch("making the conversation")
    copied = time.monotonic()

    execution_id = green.execution_id
    catalog_root = _tp._catalog_root()
    cid: str | None = None
    try:
        if owns_green and green.git_dir.is_dir():
            await asyncio.to_thread(green_checkout.record_request_start, green, requested_at)
            green_checkout.begin_first_edit_watch(green)
        record: dict[str, Any] = {k: v for k, v in (meta or {}).items() if k not in _RESERVED_META_FIELDS}
        record["execution_id"] = execution_id

        conv = await asyncio.to_thread(
            forge_code_store.new_conversation, green.work, title=_tp._short_title(request), thomas_project=record
        )
        cid = str(conv["id"])
        progress.touch("registering the project")
        # `allow_without_history=True`: green always has real git history (it
        # is a clone), but binding must never fail this call over a history
        # check -- that check exists for a person's own folder, not a copy
        # Thomas made.
        await asyncio.to_thread(
            forge_code_projects.bind_conversation,
            catalog_root,
            cid,
            green.work,
            settings=dict(settings),
            allow_without_history=True,
        )

        start = app.get(APP_PRAXIS_START_CODE_RUN)
        if start is None:
            raise _tp.ThomasProjectError("no Build start hook is bound -- the server has not finished starting up")

        # These reads are independent; do not make the team wait for one before starting the other.
        reading: list[str] = []
        siblings, learned = await asyncio.gather(
            _advice(
                "reading what the other projects are changing",
                green_handoff.sibling_changes,
                execution_id,
                progress=progress,
                pending=reading,
            ),
            _advice(
                "reading what earlier teams were sent back for",
                repair_ledger.lessons_note,
                progress=progress,
                pending=reading,
            ),
        )
        notes = "\n\n".join(part for part in (_tp._TEAM_NOTES, learned, _tp._siblings_note(siblings)) if part)
        body = {
            **settings,
            "conversation_id": cid,
            "project_root": str(green.work),
            "project_choice": "picked",
            # The notes are Thomas's, not the request: the completion gate reads past them (acceptance_contract).
            # The end marker is a paragraph of its own, so the notes' last section still ends where it did.
            "message": f"{request.rstrip()}\n\n{THOMAS_NOTES_START}\n{notes}\n\n{THOMAS_NOTES_END}",
        }
        progress.touch("starting Build's team")
        bound = time.monotonic()
        status, payload = await start(body, port=port)
        # How long a project takes to start working, in its parts (2026-10-25: one took 28 minutes to its first run).
        step_log.record(
            "project_start",
            seconds=time.monotonic() - began,
            cid=cid,
            execution_id=execution_id,
            copy_s=copied - began,
            bind_s=bound - copied,
            start_s=time.monotonic() - bound,
            status=status,
            own_copy=owns_green,
        )
        if status is None or not (200 <= status < 300):
            refusal = str((payload or {}).get("error") or f"status {status}")
            raise _tp.ThomasProjectError(f"Build refused to start a Thomas project: {refusal}")
    except BaseException:
        if cid is not None:
            try:
                forge_code_projects.forget_conversation(catalog_root, cid)
            except OSError:
                log.warning("could not forget the registry row for %s after a failed start", cid, exc_info=True)
        if owns_green:
            try:
                await asyncio.to_thread(green_checkout.remove_green, green)
            except OSError:
                # The refusal (or whatever exception got us here) is what you
                # need to see; a folder that outlives it is a smaller problem
                # -- the next sweep clears it -- and must not hide the first.
                log.warning("could not remove green %s after a failed start", execution_id, exc_info=True)
        raise

    app.setdefault("self_project_listing_slot", {})["dirty"] = True
    return {
        "conversation_id": cid,
        "execution_id": execution_id,
        "project_root": str(green.work),
        "status": status,
    }


async def _advice(stage: str, read: Any, *args: Any, progress: _Progress, pending: list[str]) -> Any:
    """Wait for an advisory read, reporting the reads still running without a time limit."""
    pending.append(stage)
    progress.touch(" and ".join(pending))
    try:
        return await asyncio.to_thread(read, *args)
    finally:
        pending.remove(stage)
        progress.touch(" and ".join(pending) or None)  # moving: one read finished; the stage keeps naming the rest


def _remove_quietly(green: green_checkout.Green) -> None:
    try:
        green_checkout.remove_green(green)
    except OSError:
        # Held open for now: a settled marker lets the next sweep take it at any age.
        log.warning("could not remove green %s after a cancelled start", green.execution_id, exc_info=True)
        green_checkout.mark_settled(green)


async def _create_green(blue: Path, execution_id: str, progress: _Progress | None = None) -> green_checkout.Green:
    """`create_green` in a thread, and a cancelled start still removes the green it makes.

    Task 4 (NEW-2 from the re-review of 8b1363d9): cancelling the start while
    `create_green` ran did not stop its thread. The thread finished the green
    afterwards, and nothing removed it until the 24h sweep. Now whichever side
    learns last removes it: the thread, when it finishes a green nobody is
    waiting for, or the cancelled start, when the green was already made but
    not yet handed back. The lock makes that exactly one of them.
    """
    lock = threading.Lock()
    state: dict[str, Any] = {"abandoned": False, "made": None}

    def _create() -> green_checkout.Green:
        made = green_checkout.create_green(blue=blue, execution_id=execution_id)
        with lock:
            abandoned = state["abandoned"]
            state["made"] = None if abandoned else made
        if abandoned:
            _remove_quietly(made)
        return made

    watcher = asyncio.create_task(watch_copy(execution_id, progress, _POLL_S)) if progress else None
    try:
        return await asyncio.to_thread(_create)
    except green_checkout.GreenUnavailable as exc:
        raise _tp.ThomasProjectError(f"could not make a green copy of Thomas's source: {exc}") from exc
    except asyncio.CancelledError:
        with lock:
            state["abandoned"] = True
            made = state["made"]
        if made is not None:
            await asyncio.to_thread(_remove_quietly, made)
        raise
    finally:
        if watcher:
            watcher.cancel()


# The names thomas_project resolves here (its __getattr__).
NAMES = frozenset({"start_thomas_project", "_create_green", "_remove_quietly", "_RESERVED_META_FIELDS"})

__all__ = ["start_thomas_project"]
