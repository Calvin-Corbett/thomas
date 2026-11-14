"""A restart does not stop a Thomas project: the run the server before was doing carries on by itself, once.

Every Build run leaves its start (its user turn, and Build's run receipt saying "running") and its end (the agent
turn the recorder writes). :func:`survey` finds each conversation in the catalog's registry whose last turn is a start
with no end, from before this server started. The catalog is the checkout, which two servers can share, but each keeps
its receipts in its own data folder: a start with no receipt here was another server's. On Autopilot it carries on
once, through ``_start_continuation`` as a park does, with ``evolve_agent_autopilot.restart_message``: the goal stays
your request, the fuse does not count it, and the stopped run's message rides along in full, a repair round's findings
too. The stopped run's helpers that Praxis's startup recovery reopened are closed, so one team works in the folder,
and a project Chat started gets its chat's card back (``chat_self_project.follow_after_restart``).

Left alone: a project handed in, one you stopped, one its usage-limit pause owns, one another server started, one whose
run is going again (here, or still writing in another server). Not carried on, and listed as stopped with the server
(:func:`phase`, read by ``thomas_project.project_phase``): one ``MAX_RESTARTS_IN_A_ROW`` restarts stopped with no run
finishing, one whose result was lost after it ended, one not on Autopilot, and one that went quiet while the previous
server was alive or that server's restart pass had already left waiting for you. Every other unfinished Autopilot run
can carry on, regardless of how long the server was off. Each server records its own life for the next
(:func:`restart_pass`), including runs it found but could not start. A full-capacity server waits without spending
Build tries; without a working start hook, port, or cage it waits up to ``WAIT_LIMIT_S``. Once started, the run is
Autopilot's like any other: if it dies, the fuse and failure handling decide, and this pass never tries it again.
An ordinary Build conversation on Autopilot is the same case, after the Thomas projects.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.core.kernel import late, seams
from thomas.core.pause import paused
from thomas.forge.anvil import forge_code_conversations
from thomas.server import autopilot_enough, autopilot_park, autopilot_silence, thomas_project
from thomas.server.autopilot_silence import Life

log = logging.getLogger(__name__)

APP_AUTOPILOT_RESTART_TASK = web.AppKey("autopilot_restart_task", asyncio.Task)
APP_SERVER_LISTENING = web.AppKey("server_listening", asyncio.Event)  # set by the server once its port is open
LISTEN_WAIT_S = 60.0  # the longest the survey waits for that; a server that never opens its port still surveys
LISTEN_GRACE_S = 3.0  # then a pause, so the first page loads before the survey parses conversation records
READ_ATTEMPTS = 3  # surveys in a row that may fail to read one conversation before it is skipped
MAX_RESTARTS_IN_A_ROW = 3  # restarts that stopped a run with no run finishing in between, before it is left stopped
SETTLE_S = 0.0  # compatibility for callers configuring the former startup delay
TICK_S = 5.0  # retry promptly while the start hook, port, or capacity is not ready
WAIT_LIMIT_S = 15 * 60.0  # wait for a missing start hook, port, or cage runner; capacity waits indefinitely
CARRYING_ON = "Autopilot: carrying on after the restart"
# Why a run is not carried on, worded to follow "stopped before it finished: " on the chat's card.
_ON = "Send a message and Thomas carries on"
STOPPED = f"its Build run stopped when Thomas's server did, and nothing carried it on. {_ON}"
NOT_AUTOPILOT = f"its Build run stopped when Thomas's server restarted. It is not on Autopilot, so it waits: {_ON}"
AGAIN = f"{MAX_RESTARTS_IN_A_ROW} restarts in a row stopped its Build run before any run finished. {_ON}"
UNRECORDED = f"its Build run ended in the server before this one, but its result was never recorded. {_ON}"
REFUSED = f"Build refused to start it again after the restart (the issue log has its answer). {_ON}"
COULD_NOT_START = f"its conversation could not be read or checked to start its Build run after the restart. {_ON}"
NOT_READY = f"this server could not start Build runs in time to carry it on after the restart. {_ON}"
CAGE_DOWN = f"the cage's shell runner was not answering, so no run was started to carry it on after the restart. {_ON}"
EARLIER = f"the restart before this one did not carry its Build run on, and nothing was sent to it since. {_ON}"


def _went_silent(seconds: float) -> str:
    return (
        f"nothing was heard from its Build run for {autopilot_silence.took(seconds)} before Thomas's server "
        f"stopped, while that server was still running, so it was not carried on as a restart. {_ON}"
    )


# Why a run is left to something else, or needs nothing: the listing reads those as it did before.
HANDED_IN, YOU_STOPPED = "it was handed in to your approval card", "you stopped it"
PARKED = "the pause for your usage limit carries it on"
GOING, ELSEWHERE = "a run is going on it again", "its run is still writing, in another server"
OTHER_SERVER = "its run was started by another Thomas server, which has its own record of it"
SENT_SINCE = "something new was sent to it since"
_LIVE_STATES = ("launching", "running")  # Build's run receipt before the recorder writes the run's end
_lock = threading.Lock()
_clock = time.time  # module-local, so a test moves only this module's clock
_sleep = asyncio.sleep


@dataclass(frozen=True)
class Interrupted:
    """A run or pending handoff to carry on after the prior server stopped."""

    cid: str
    project_root: Path
    turn: dict[str, Any]  # the run's start, its user turn, as the file had it
    started_at: float
    thomas_project: bool
    chat: str  # the chat that asked, for a Thomas project Chat started; else ""
    run_id: str  # from Build's run receipt, when it has one
    heard_at: float = 0.0  # the last thing heard from the run: its start, or its transcript's last write
    after_run_pending: bool = False  # recorded run finished during reload drain; decide instead of rerunning Build


@dataclass
class _Pass:
    """What this server's pass found and did. ``booted_at`` stays None when no pass runs (tests, the switch off)."""

    booted_at: float | None = None
    scanned: bool = False
    pending: set[str] = field(default_factory=set)
    pending_reasons: dict[str, str] = field(default_factory=dict)
    resumed: list[str] = field(default_factory=list)
    silent: dict[str, float] = field(default_factory=dict)  # each run carried on: seconds nothing was heard from it
    stopped: dict[str, str] = field(default_factory=dict)  # left alone by the survey; EARLIER on the next boot
    unreadable: dict[str, str] = field(default_factory=dict)  # conversations the survey gave up reading, and why
    read_failures: dict[str, int] = field(default_factory=dict)  # surveys in a row that failed to read each one
    retry: list[Exception] = field(default_factory=list)  # this survey's failed reads that may still succeed
    settled: dict[str, tuple[float, int, int]] = field(default_factory=dict)  # read once, needing nothing: its stamp
    read_cache: dict[Path, tuple[int, int, Any]] = field(default_factory=dict)
    carrying: dict[str, str] = field(default_factory=dict)  # this pass could not start it; the next boot retries
    left: dict[str, str] = field(default_factory=dict)  # left to something else, or needing nothing
    before: Life | None = None  # what the server before this one recorded about itself (autopilot_silence)
    catalog: Path | None = None  # where this server records its own life, once its pass runs


_pass = _Pass()


def _receipts(catalog_root: Path) -> dict[str, dict[str, Any]]:
    from thomas.server.routes.evolve_agent_receipts import _read_receipts

    return _read_receipts(catalog_root)


def defer_until_reload(catalog_root: Path, conversation: dict[str, Any], cid: str) -> None:
    """Mark a completed Build's continuation for restart when its next start hits the drain."""
    from thomas.server.routes.evolve_agent_receipts import _action_receipt, _save_action_receipt

    user = next((turn for turn in reversed(_turns(conversation)) if turn.get("role") == "user"), {})
    request_id = str(user.get("request_id") or "")
    if not request_id:
        log.error("autopilot: cannot defer reload continuation for %s without a run request", cid)
        return
    try:
        receipt = _action_receipt(catalog_root, "run", request_id)
        if not receipt or receipt.get("state") not in ("completed", "finished", "after_run_pending"):
            log.error("autopilot: cannot defer reload continuation for %s without a completed run", cid)
            return
        _save_action_receipt(catalog_root, "run", request_id, {**receipt, "state": "after_run_pending"})
    except (OSError, TypeError, ValueError):
        log.exception("autopilot: could not defer reload continuation for %s", cid)


def _receipt(receipts: dict[str, dict[str, Any]], turn: dict[str, Any]) -> dict[str, Any]:
    from thomas.server.routes.evolve_agent_receipts import _receipt_key

    request_id = str(turn.get("request_id") or "")
    return (receipts.get(_receipt_key("run", request_id)) or {}) if request_id else {}


def _written_since(catalog_root: Path, run_id: str, moment: float) -> bool:
    """The stopped run's transcript was written after ``moment``: another server is still running it."""
    from thomas.forge.anvil.run_files import transcript_path as _transcript_path

    try:
        return bool(run_id) and _transcript_path(catalog_root, run_id).stat().st_mtime > moment
    except OSError:
        return False


def _runners_of(cid: str) -> tuple[list[Any], list[Any]]:
    """Build runners still going for conversation *cid*: those a live server started, and those whose server is gone.

    A runner reports its run through the pipe to the server that started it, and it outlives that server. A long fix
    pass writes nothing for many minutes, so its transcript looks stopped (2026-09-27: the restart at 07:50 started a
    second runner in the ratchet project's copy, and two teams edited it for four hours; the first one's result went
    nowhere). Each is the top runner process of its tree: a venv launcher and the python it starts are one runner.
    """
    try:
        import psutil
    except ImportError:
        return [], []
    found: dict[int, Any] = {}
    for proc in psutil.process_iter(["cmdline"]):
        args = [str(arg) for arg in proc.info.get("cmdline") or []]
        named = any(
            i + 1 < len(args) and args[i] == "--conversation-id" and args[i + 1] == cid for i in range(len(args))
        )
        if named and any(arg.endswith("forge_code_runner") for arg in args):
            found[proc.pid] = proc
    heard, orphaned = [], []
    for proc in found.values():
        try:
            parent = proc.parent()
            if parent is not None and parent.pid in found:
                continue  # the python a launcher started: ended with its launcher
            alive = parent is not None and parent.create_time() <= proc.create_time()  # not a new process on its pid
        except psutil.Error:
            continue
        (heard if alive else orphaned).append(proc)
    return heard, orphaned


def _end(runners: list[Any]) -> None:
    """End each runner and everything it started."""
    import psutil

    ending = []
    for runner in runners:
        with contextlib.suppress(psutil.Error):
            ending += [*runner.children(recursive=True), runner]
    for proc in ending:
        with contextlib.suppress(psutil.Error):
            proc.kill()
    psutil.wait_procs(ending, timeout=10)


def _turns(conversation: Any) -> list[dict[str, Any]]:
    turns = conversation.get("turns") if isinstance(conversation, dict) else None
    return [turn for turn in turns or [] if isinstance(turn, dict)]


def _started_before(turns: list[dict[str, Any]], booted: float) -> float | None:
    """Start time of a pending user turn or a recorded reload yield before this boot."""
    last = turns[-1] if turns else {}
    if last.get("role") == "agent" and last.get("outcome") == "reload_yielded":
        last = turns[-2] if len(turns) > 1 else {}
    started = autopilot_park._turn_time(last) if last.get("role") == "user" else None
    return started if started is not None and started < booted else None


def _restarts_in_a_row(turns: list[dict[str, Any]], prefix: str) -> int:
    count = 0
    for turn in reversed(turns):
        if turn.get("role") != "user":
            break
        count += str(turn.get("text") or "").startswith(prefix)
    return count


def _note_unreadable(cid: str, exc: Exception) -> None:
    """A conversation that stayed unreadable through ``READ_ATTEMPTS`` surveys is skipped, not fatal: say so once per
    server life, and keep it for :func:`report`. The reason names the kind of failure, never the path or content."""
    why = f"{type(exc).__name__}: {exc.strerror}" if isinstance(exc, OSError) and exc.strerror else type(exc).__name__
    with _lock:
        first = cid not in _pass.unreadable
        _pass.unreadable[cid] = why
    if first:
        log.warning("autopilot: conversation %s could not be read for the restart survey (%s); skipped", cid, why)


def _read_failed(cid: str, exc: Exception) -> None:
    """Retry after all conversations have been visited; skip after ``READ_ATTEMPTS`` consecutive failed surveys."""
    with _lock:
        _pass.read_failures[cid] = _pass.read_failures.get(cid, 0) + 1
        if _pass.read_failures[cid] < READ_ATTEMPTS:
            usual = not isinstance(exc, (MemoryError, RecursionError))  # the pass retries only the usual failures
            _pass.retry.append(exc if usual else ValueError(f"{type(exc).__name__} reading the conversation"))
            return
    _note_unreadable(cid, exc)


def _unfinished(catalog_root: Path, cid: str, row: dict[str, Any], booted: float) -> dict[str, Any] | None:
    """The conversation, joined with its settings, when its last turn predates this boot."""
    if not str(row.get("project_root") or ""):
        return None
    path = thomas_project._live_file(Path(str(row["project_root"])), cid)
    try:
        try:
            seen = path.stat()
        except FileNotFoundError:
            with _lock:
                _pass.read_failures.pop(cid, None)
                _pass.settled.pop(str(path), None)
                _pass.read_cache.pop(path, None)
            return None
        # Read by an earlier survey of this pass and needing nothing: not parsed again while its file is as it was.
        stamp = (booted, seen.st_mtime_ns, seen.st_size)
        with _lock:
            if _pass.settled.get(str(path)) == stamp:
                _pass.read_failures.pop(cid, None)
                _pass.unreadable.pop(cid, None)
                return None
        # Streamed, each run's transcript cut to its tail (a long-running team's record is tens of MB of them, and
        # nothing here reads more than a tail): the survey's memory follows what it keeps, not the file's size.
        from thomas.server.restart_survey_reads import read_conversation

        conversation = read_conversation(path, _pass.read_cache)
    except (OSError, ValueError, MemoryError, RecursionError) as exc:  # denied, a folder, bad bytes or JSON, too big
        with _lock:
            _pass.settled.pop(str(path), None)
            _pass.read_cache.pop(path, None)
        _read_failed(cid, exc)
        return None
    with _lock:
        _pass.read_failures.pop(cid, None)
        _pass.unreadable.pop(cid, None)
    turns = _turns(conversation) if isinstance(conversation, dict) else []
    # A finished run's last turn is an agent turn, not a pending user turn.
    # The receipt in _classify must prove that it has an after_run handoff.
    if _started_before(turns, booted) is None and (
        not turns or turns[-1].get("role") != "agent" or (autopilot_park._turn_time(turns[-1]) or booted) >= booted
    ):
        with _lock:
            _pass.settled[str(path)] = stamp
        return None
    return {**conversation, "settings": row.get("settings") if isinstance(row.get("settings"), dict) else {}}


def _handed_in(catalog_root: Path, cid: str, root: Path, conversation: dict[str, Any]) -> bool:
    """Settled, or copied out to the catalog for its hand-in (``settle_if_finished``; ``retire_held``)."""
    project = conversation.get("thomas_project") if isinstance(conversation.get("thomas_project"), dict) else {}
    if project.get("settled_at"):
        return True
    return bool(project) and Path(root) != Path(catalog_root) and thomas_project._live_file(catalog_root, cid).is_file()


def _classify(
    catalog_root: Path, cid: str, root: Path, conversation: dict, booted: float, receipts: dict, before: Life | None
) -> Any:
    """``Interrupted`` to carry on, or ``("left" | "stopped", why)``."""
    from thomas.server.routes import evolve_agent_autopilot as ap

    turns = _turns(conversation)
    yielded = turns[-1].get("outcome") == "reload_yielded"
    last, started = (turns[-2] if yielded else turns[-1]), _started_before(turns, booted) or 0.0
    project = conversation.get("thomas_project") if isinstance(conversation.get("thomas_project"), dict) else {}
    stamp = conversation.get("autopilot") if isinstance(conversation.get("autopilot"), dict) else {}
    receipt = _receipt(receipts, last)
    pending = False
    if last.get("role") == "agent" and not yielded:
        user = next((turn for turn in reversed(turns[:-1]) if turn.get("role") == "user"), {})
        receipt = _receipt(receipts, user)
        pending = (
            bool(user)
            and receipt is not None
            and receipt.get("state") in (*_LIVE_STATES, "completed", "after_run_pending")
            and (not last.get("run_id") or last.get("run_id") == (receipt.get("response") or {}).get("run_id"))
        )
        started = autopilot_park._turn_time(last) or 0.0
        if not pending or started >= booted:
            return "left", SENT_SINCE
        last = user
    if _handed_in(catalog_root, cid, root, conversation):
        return "left", HANDED_IN
    if thomas_project.stop_requested(conversation):
        return "left", YOU_STOPPED
    if stamp.get("parked_until") or autopilot_park.parked(catalog_root, cid) is not None:
        return "left", PARKED
    if not receipt:  # this server's line of servers never started it
        return "left", OTHER_SERVER
    valid_states = (
        (*_LIVE_STATES, "completed", "after_run_pending")
        if pending
        else ((*_LIVE_STATES, "reload_yielded") if yielded else _LIVE_STATES)
    )
    if receipt.get("state") not in valid_states:
        return "stopped", UNRECORDED
    run_id = str((receipt.get("response") or {}).get("run_id") or "")
    heard = autopilot_silence.last_heard(catalog_root, run_id, started)
    if _restarts_in_a_row(turns, ap.RESTART_PREFIX) >= MAX_RESTARTS_IN_A_ROW:
        return "stopped", AGAIN
    if (
        not yielded
        and not pending
        and ((conversation.get("settings") or {}).get("requested") or {}).get("autonomy_level") != ap.AUTOPILOT
    ):
        return "stopped", NOT_AUTOPILOT
    if not yielded and not pending:
        grace = autopilot_silence.grace_s(conversation)
        why, silent = autopilot_silence.stopped_with_the_server(before, cid, started, heard, booted, grace)
        if why:
            return "stopped", EARLIER if why == "earlier" else _went_silent(silent)
    chat = str(project.get("chat_session_id") or "")
    return Interrupted(cid, root, last, started, bool(project), chat, run_id, heard, pending)


def survey(catalog_root: Path, booted: float) -> list[Interrupted]:
    """Find interrupted runs and finished-during-drain handoffs to carry on, Thomas
    projects first. Only reads; what it found is what :func:`phase` and :func:`report` say from now on."""
    catalog_root = Path(catalog_root)
    rows = forge_code_conversations._load_registry(catalog_root, strict=True)
    _pass.retry.clear()
    unfinished = {cid: c for cid, row in rows.items() if (c := _unfinished(catalog_root, cid, row, booted))}
    if _pass.retry:  # every conversation has had its read: one more survey tries all the failed ones together
        raise _pass.retry[0]
    receipts = _receipts(catalog_root) if unfinished else {}
    before = autopilot_silence.previous_life(catalog_root, booted)
    found: list[Interrupted] = []
    stopped: dict[str, str] = {}
    left: dict[str, str] = {}
    for cid, conversation in unfinished.items():
        root = Path(str(rows[cid]["project_root"]))
        verdict = _classify(catalog_root, cid, root, conversation, booted, receipts, before)
        if isinstance(verdict, Interrupted):
            found.append(verdict)
        else:
            (stopped if verdict[0] == "stopped" else left)[cid] = verdict[1]
    found.sort(key=lambda item: (not item.thomas_project, item.started_at))
    with _lock:  # a survey starts a pass: what an earlier one said no longer holds
        _pass.booted_at, _pass.scanned, _pass.resumed, _pass.silent = booted, True, [], {}
        _pass.pending, _pass.stopped, _pass.left = {item.cid for item in found}, stopped, left
        _pass.before = before
        _pass.read_cache.clear()
    return found


def _save_life(catalog_root: Path) -> None:
    """Record this server's life, including work still waiting to start on the next server.

    Never raises: if this server cannot write its life, the next surveys unfinished runs without a prior record.
    """
    with _lock:
        if _pass.booted_at is None:
            return
        life = autopilot_silence.life_now(_pass.booted_at, _clock(), _pass.stopped, (*_pass.pending, *_pass.carrying))
        before = _pass.before
    try:
        autopilot_silence.record_life(catalog_root, life, before)
    except (OSError, TypeError, ValueError):
        log.warning("autopilot: this server's life could not be recorded for the next restart", exc_info=True)


def _cage_down() -> bool:
    """The caged shell is required here and its runner is not answering: a run started now could run no command."""
    from thomas.tools import cage_shell

    try:
        return cage_shell.posture() == "required" and not cage_shell.runner_alive()
    except (OSError, ValueError):
        return False


def _keep_green(conversation: dict[str, Any], cid: str) -> None:
    """A carried-on project's green outlives the 24-hour sweeps while its team works in it, as a ratchet repair's
    does (``ratchet.repair``): it can be older than that by the morning after."""
    from thomas.server import green_checkout

    project = conversation.get("thomas_project") if isinstance(conversation.get("thomas_project"), dict) else {}
    green = green_checkout.find_green(str(project.get("execution_id") or ""))
    if green is not None:
        green_checkout.mark_kept(green, f"its Build run was carried on after a restart ({cid})")


async def _close_recovered(app: Any, item: Interrupted) -> None:
    """Close the stopped run's helpers that Praxis's startup recovery reopened: the new run's team works alone."""
    registry = app.get("praxis_run_channels")  # praxis_run_routes.APP_PRAXIS_RUN_CHANNELS
    recovered = (app.get("praxis_recovery_report") or {}).get("resumed") or []  # praxis.startup's report
    mine = [row for row in recovered if isinstance(row, dict) and row.get("conversation_id") == item.cid]
    runs = {str(row.get("run_id") or "") for row in mine} | {item.run_id}
    for run_id in sorted(run for run in runs if run and run in getattr(registry, "_runs", {})):
        try:
            await registry.close(run_id)
        except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
            log.warning("autopilot: the recovered helpers of run %s could not be closed", run_id, exc_info=True)


async def _carry_on(
    app: Any,
    catalog_root: Path,
    item: Interrupted,
    *,
    observed_at: float | None = None,
    message: str | None = None,
    can_start: Callable[[], Awaitable[bool]] | None = None,
    gate_guard: Callable[[], bool] | None = None,
) -> tuple[str, str]:
    """Carry on ``item``: started, left alone, Build refused, or a read failure before Build was asked."""
    from thomas.forge.anvil import forge_code_store
    from thomas.server.praxis.launch import guarded_start
    from thomas.server.routes import evolve_agent_autopilot as ap

    if autopilot_park._run_active(app, item.cid):
        return "left", GOING
    cutoff = observed_at if observed_at is not None else (_pass.booted_at or _clock())
    if await asyncio.to_thread(_written_since, catalog_root, item.run_id, cutoff):
        return "left", ELSEWHERE
    heard, orphaned = await asyncio.to_thread(_runners_of, item.cid)
    if heard:
        return "left", ELSEWHERE
    conversation = await asyncio.to_thread(thomas_project._read_live, item.project_root, catalog_root, item.cid)
    turns = _turns(conversation)
    if conversation is None:
        return "read_retry", COULD_NOT_START
    if spent := thomas_project.repairs_spent(conversation) or autopilot_enough.standing(conversation):  # paused for you
        return "left", spent
    if (
        not item.after_run_pending
        and len(turns) > 1
        and turns[-2] == item.turn
        and turns[-1].get("role") == "agent"
        and turns[-1].get("outcome") == "interrupted"
        and turns[-1].get("run_id") == item.run_id
    ):
        item = replace(item, after_run_pending=True)
    if item.after_run_pending:
        # The receipt belongs to a user request in this conversation; the
        # recorded agent result must still be the last turn on disk.
        if not turns or turns[-1].get("role") != "agent" or item.turn not in turns[:-1]:
            return "left", SENT_SINCE
        from thomas.server.routes.evolve_agent_receipts import _action_receipt, _save_action_receipt

        request_id = str(item.turn.get("request_id") or "")
        current = await asyncio.to_thread(_action_receipt, catalog_root, "run", request_id)
        if not current or current.get("state") not in (*_LIVE_STATES, "completed", "after_run_pending"):
            return "left", SENT_SINCE
        if current.get("state") != "after_run_pending":
            _save_action_receipt(catalog_root, "run", request_id, {**current, "state": "after_run_pending"})
        if current.get("response", {}).get("run_id") != item.run_id:
            return "left", SENT_SINCE
    elif not turns or (
        turns[-1] != item.turn
        and not (len(turns) > 1 and turns[-2] == item.turn and turns[-1].get("outcome") == "reload_yielded")
    ):
        return "left", SENT_SINCE
    if await asyncio.to_thread(_handed_in, catalog_root, item.cid, item.project_root, conversation):
        return "left", HANDED_IN  # handed in or retired since the survey: its green is not this team's any more
    if thomas_project.stop_requested(conversation):
        return "left", YOU_STOPPED
    if await asyncio.to_thread(autopilot_park.parked, catalog_root, item.cid) is not None:
        return "left", PARKED
    if orphaned:
        if item.after_run_pending:
            return "left", GOING
        await asyncio.to_thread(_end, orphaned)
    if item.thomas_project:
        await asyncio.to_thread(_keep_green, conversation, item.cid)
    if item.after_run_pending and turns[-1].get("outcome") != "interrupted":
        # The final turn is recorded; leave the pending receipt intact until the
        # decision completes, so a reboot during this handoff can retry it.
        from thomas.server.routes.evolve_agent_receipts import _save_action_receipt

        decision = await ap.after_run(app, item.project_root, catalog_root, item.cid)
        if decision is None:
            return "read_retry", COULD_NOT_START
        if decision.start_pending or thomas_project.held_steers(item.cid):
            return "pending", COULD_NOT_START
        await asyncio.to_thread(
            _save_action_receipt,
            catalog_root,
            "run",
            str(item.turn.get("request_id") or ""),
            {**current, "state": "finished"},
        )
        await _close_recovered(app, item)
        return "started", ""
    if can_start is not None and not await can_start():
        return "retry", REFUSED
    if turns[-1].get("role") == "user" and item.run_id:
        # A power cut can leave work in the run's transcript without its final
        # conversation turn. Save that ending before another request replaces it.
        from thomas.forge.anvil.run_files import transcript_path as _transcript_path

        try:
            transcript = await asyncio.to_thread(
                _transcript_path(catalog_root, item.run_id).read_text, encoding="utf-8", errors="replace"
            )
        except OSError:
            transcript = ""
        from thomas.server.routes.evolve_agent_receipts import _action_receipt, _save_action_receipt

        request_id = str(item.turn.get("request_id") or "")
        receipt = await asyncio.to_thread(_action_receipt, catalog_root, "run", request_id)
        if not receipt:
            receipt = {"state": "running", "response": {"run_id": item.run_id}, "conversation_id": item.cid}
            await asyncio.to_thread(_save_action_receipt, catalog_root, "run", request_id, receipt)
        await asyncio.to_thread(
            forge_code_store.append_agent_turn,
            item.project_root,
            item.cid,
            model="",
            transcript=transcript,
            changed_files=[],
            returncode=None,
            ok=False,
            noop=True,
            reason="Thomas's server stopped before this run recorded an ending; carrying on after the restart.",
            run_id=item.run_id,
            outcome="interrupted",
        )
        await asyncio.to_thread(
            _save_action_receipt,
            catalog_root,
            "run",
            request_id,
            {
                **(receipt or {}),
                "state": "after_run_pending",
                "conversation_id": item.cid,
                "response": {**((receipt or {}).get("response") or {}), "run_id": item.run_id},
            },
        )
        conversation = await asyncio.to_thread(thomas_project._read_live, item.project_root, catalog_root, item.cid)
        if conversation is None:
            return "read_retry", COULD_NOT_START
        turns = _turns(conversation)
    goal = ap._goal(turns)  # everything you asked for (autopilot_goal.goal_text), as every other round's message
    decision = ap.Decision("restart", CARRYING_ON, message or ap.restart_message(goal, ap.run_text(item.turn)))
    with guarded_start(can_start, gate_guard):
        started = await ap._start_continuation(app, item.project_root, catalog_root, conversation, item.cid, decision)
    if started is None:
        return "busy", REFUSED
    if not started:
        return "retry", REFUSED
    if item.after_run_pending:
        from thomas.server.routes.evolve_agent_receipts import _save_action_receipt

        await asyncio.to_thread(
            _save_action_receipt,
            catalog_root,
            "run",
            str(item.turn.get("request_id") or ""),
            {**current, "state": "finished"},
        )
    await _close_recovered(app, item)
    if item.chat:
        try:
            await late.call(seams.FOLLOW_AFTER_RESTART, app, item.cid, item.project_root, catalog_root, item.chat)
        except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
            log.exception("autopilot: the chat card of Thomas project %s is not followed again", item.cid)
    return "started", ""


async def _attempt(
    app: Any,
    catalog_root: Path,
    found: list[Interrupted],
    tries: dict[str, int],
    pre_start_failures: dict[str, int] | None = None,
) -> None:
    """Try each run in order; unstarted work remains eligible on later polls."""
    if pre_start_failures is None:
        pre_start_failures = {}
    from thomas.core import machine_capacity
    from thomas.server.routes.evolve_agent_run_state import active_code_runs

    for item in list(found):
        if machine_capacity.admission_refusal(len(active_code_runs(app))):
            break  # capacity is checked again before every start, without spending a Build try
        try:
            outcome, why = await _carry_on(app, catalog_root, item)
        except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
            log.exception("autopilot: conversation %s did not carry on after the restart", item.cid)
            outcome, why = "read_retry", COULD_NOT_START
        if outcome in ("read_retry", "retry", "pending"):
            with _lock:
                _pass.pending_reasons[item.cid] = why
        if outcome == "read_retry":
            pre_start_failures[item.cid] = pre_start_failures.get(item.cid, 0) + 1
            continue
        if outcome == "busy":
            continue
        if outcome == "pending":
            tries[item.cid] = tries.get(item.cid, 0) + 1
            continue
        if outcome == "retry":
            # Launch retries are separate from the executed-continuation budget.
            tries[item.cid] = tries.get(item.cid, 0) + 1
            continue
        found.remove(item)
        with _lock:
            _pass.pending.discard(item.cid)
            _pass.pending_reasons.pop(item.cid, None)
            if outcome == "started":
                _pass.resumed.append(item.cid)
                _pass.silent[item.cid] = autopilot_silence.silent_for(item.heard_at, _pass.booted_at or _clock())
            else:
                (_pass.left if outcome == "left" else _pass.carrying)[item.cid] = why


def report() -> dict[str, Any]:
    """What this server's pass did: carried on (and how long nothing was heard from each), not carried on and why,
    and still waiting to start."""
    with _lock:
        return {
            "resumed": list(_pass.resumed),
            "carried_on": {cid: autopilot_silence.carried_on_words(s) for cid, s in _pass.silent.items()},
            "not_resumed": {**_pass.left, **_pass.stopped, **_pass.carrying},
            "pending": sorted(_pass.pending),
            "unreadable": dict(_pass.unreadable),  # skipped by the survey: could not be read, so not carried on
            "pending_reasons": {cid: why for cid, why in _pass.pending_reasons.items() if cid in _pass.pending},
        }


async def resume_interrupted(app: Any, catalog_root: Path, *, booted: float) -> dict[str, Any]:
    """Survey, then one try at each run to carry on: the pass's work once the server can start runs."""
    found = await asyncio.to_thread(survey, Path(catalog_root), booted)
    await _attempt(app, Path(catalog_root), found, {})
    return report()


def phase(conversation: dict[str, Any]) -> tuple[str, str] | None:
    """Show pending work as waiting; show a failed start as ended with its reason.

    Failed starts stay in this life's carrying list for the next server; other servers' live
    runs and projects already handed elsewhere keep their existing phase.
    """
    with _lock:
        state = _pass
        booted = state.booted_at
        if booted is None:
            return None
        cid = str(conversation.get("id") or "")
        if (
            _started_before(_turns(conversation), booted) is None
            and cid not in state.carrying
            and cid not in state.pending
        ):
            return None
        if cid in state.left:
            return None
        if cid in state.carrying:
            return "ended", state.carrying[cid]
        if not state.scanned or cid in state.pending:
            return "waiting", state.pending_reasons.get(cid, CARRYING_ON)
        return "ended", state.stopped.get(cid, STOPPED)


async def _after_the_server_listens(app: Any) -> None:
    """The survey parses every conversation record in pure Python on a thread, and that competed with the server's own
    start and then with the first page load for the interpreter (about 2.5 s of CPU on a long history). Nothing is
    waiting for it: it starts once the port is open and the first page has had a moment."""
    listening = app.get(APP_SERVER_LISTENING)
    if listening is None:  # not started by the server (a test, a script): survey at once, as before
        return
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(listening.wait(), LISTEN_WAIT_S)
    await _sleep(LISTEN_GRACE_S)


async def restart_pass(app: Any, *, catalog_root: Path | None = None) -> None:
    """Survey at once, then carry on work serially as room allows for as long as the server runs.

    ``WAIT_LIMIT_S`` only ends a pass when no start hook, port, or answering cage is available.
    Record this server's life every ``HEARTBEAT_S`` for the server after it.
    """
    from thomas.server.routes import evolve_agent_autopilot as ap

    catalog = Path(catalog_root or thomas_project._catalog_root())
    booted = _pass.booted_at if _pass.booted_at is not None else _clock()
    await _after_the_server_listens(app)
    while True:
        try:
            found = await asyncio.to_thread(survey, catalog, booted)
            break
        except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
            log.exception("autopilot: what the restart stopped could not be read; retrying")
            await _sleep(TICK_S)
    with _lock:
        _pass.catalog = catalog
    await asyncio.to_thread(_save_life, catalog)
    tries: dict[str, int] = {}
    pre_start_failures: dict[str, int] = {}
    caged = False
    while found:
        ready = app.get(ap.APP_PRAXIS_START_CODE_RUN) is not None and app.get(ap.APP_LOCAL_PORT)
        if ready:
            caged = await asyncio.to_thread(_cage_down)
            if not caged and not paused():  # a paused Thomas carries nothing on until you resume
                await _attempt(app, catalog, found, tries, pre_start_failures)
                await asyncio.to_thread(_save_life, catalog)
        if not ready or caged:
            if _clock() - booted >= WAIT_LIMIT_S:
                break  # the server cannot start runs at all; room alone has no timeout
        if found:
            await _sleep(TICK_S)
    with _lock:
        for item in found:
            _pass.pending.discard(item.cid)
            _pass.carrying[item.cid] = REFUSED if tries.get(item.cid) else CAGE_DOWN if caged else NOT_READY
    await asyncio.to_thread(_save_life, catalog)
    done = report()
    if done["resumed"] or done["not_resumed"]:
        log.warning(
            "autopilot: after the restart, carried on %s; not carried on %s", done["carried_on"], done["not_resumed"]
        )
    while True:  # this server's life, for the next one to read
        await _sleep(autopilot_silence.HEARTBEAT_S)
        await asyncio.to_thread(_save_life, catalog)


def start_restart_pass(app: Any) -> None:
    """On in the server, off under pytest unless asked for: the park loop's own switch (``autopilot_park.LOOP_ENV``)."""
    global _pass
    if autopilot_park.loop_enabled():
        with _lock:
            _pass = _Pass(booted_at=_clock())
        app[APP_SERVER_LISTENING] = asyncio.Event()
        app[APP_AUTOPILOT_RESTART_TASK] = asyncio.create_task(restart_pass(app), name="autopilot-restart-pass")


async def stop_restart_pass(app: Any) -> None:
    """Stop the pass, and record the moment this server stopped: its last sign of life."""
    task = app.get(APP_AUTOPILOT_RESTART_TASK)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        if _pass.catalog is not None:
            await asyncio.to_thread(_save_life, _pass.catalog)
