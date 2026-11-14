"""A provider's usage limit pauses Autopilot until it resets, and Autopilot carries on by itself then.

You asked that Autopilot "shouldnt stop until it ha a finoisherfd product it deems good failures will happena nd
he must fix them and continue". Measured 2026-09-24: the ChatGPT Pro plan reached its usage limit at 19:33:19Z,
every Build run then failed within about 5 s with ``ChatGPT/Codex HTTP 429 rate limited. {"error":{"type":
"usage_limit_reached",...``, and ``decide`` retried each as an ordinary failure: five projects spent all 12
continuations in about 75 s on a limit that reset 41 hours later, and their cards blamed the 12 continuations.

:func:`quota_pause` classifies a failed turn by Praxis's own rule (``praxis.quota.QuotaClassifier``), and ``decide``
answers ``wait``, which never counts toward the fuse. :func:`record` stores the park on the conversation
(``autopilot.parked_until``, Unix seconds, and the provider) and in the catalog, so a restart finds it again;
:func:`park_loop` resumes it through ``_start_continuation`` once the limit resets (at once when you steer it), and
a run that meets the limit again is parked again. :func:`card_words` is what the chat's card says meanwhile.

Fix round 1 (review of d2e612f9): a park stays listed until the run after it has recorded its end, so a restart,
a crash or a cancelled start never loses it, and the list is rebuilt from the conversations' stamps when the loop
starts. Each park belongs to the server that made it (two servers can share one checkout), and the list is written
under a lock both see. Nothing waits forever: a reset in the past, or one the 220-character cut left unreadable,
counts as unknown; unknown resets and refused starts back off to a ceiling; and after ``MAX_TRIES`` limits in a row
or ``MAX_REFUSALS`` refused starts, ``decide`` answers ``limited`` and the card says what is true.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

from thomas.core.event_loop_offload import off_loop
from thomas.core.kernel import late, seams
from thomas.core.pause import paused
from thomas.core.provider_limits import read_limit, when_words
from thomas.core.provider_trouble import classify
from thomas.forge.anvil import forge_code_conversations, forge_code_store
from thomas.server import thomas_project
from thomas.server.praxis.quota import QuotaClassifier

log = logging.getLogger(__name__)

LOOP_ENV = "THOMAS_AUTOPILOT_PARK_LOOP"
APP_AUTOPILOT_PARK_TASK = web.AppKey("autopilot_park_task", asyncio.Task)
TICK_S = 30.0  # how often the server looks for a park whose time has come, or one you steered
RECHECK_S = 30 * 60.0  # the error gave no reset time: look again this much later, doubling each time it still holds
REFUSED_RETRY_S = 5 * 60.0  # a resume the start route refused waits this long, doubling each time
CEILING_S = 6 * 3600.0  # no wait backs off past this
STARTED_GRACE_S = 10 * 60.0  # a started run that shows no slot and no end after this died unrecorded
MAX_TRIES = 12  # consecutive usage limits before Autopilot stops; provider trouble has no attempt cap
MAX_REFUSALS = 6  # refused starts after a usage-limit pause before Autopilot stops; trouble keeps retrying
RESUMED_TEXT = "Carrying on by himself: the pause for your usage limit is over, and a new Build run has started."
TROUBLE_RESUMED_TEXT = "Carrying on by himself: the provider had trouble, and a new Build run has started."
_PARKS_NAME = "autopilot_parks.json"
_TAIL_CHARS = 200_000
_EXIT_WRAPPER = re.compile(r"(?:agent loop )?exited \d+", re.IGNORECASE)
_lock = threading.Lock()
_clock = time.time  # module-local, so a test moves only this module's clock
_sleep = asyncio.sleep


@dataclass(frozen=True)
class QuotaPause:
    provider: str  # in your words ("ChatGPT Pro", "Anthropic"), or "" when the error did not name one
    retry_at: float  # Unix seconds
    reset_known: bool  # False: the error gave no reset time, and retry_at is only when to look again
    estimated: bool = False  # the reset was read from the CLI's words in a zone this machine cannot look up
    tries: int = 1  # limits in a row, this one included


@dataclass(frozen=True)
class TroublePause:
    provider: str
    retry_at: float
    kind: str
    tries: int = 1


def _turn_time(turn: dict[str, Any]) -> float | None:
    try:
        stamp = datetime.fromisoformat(str(turn.get("ts") or ""))
    except ValueError:
        return None
    return (stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)).timestamp()


def _error_texts(turn: dict[str, Any]) -> Iterator[str]:
    """The run's errors, newest first, whole, then its reason (which names only the first error, cut to 220)."""
    for line in reversed(str(turn.get("transcript") or "")[-_TAIL_CHARS:].splitlines()):
        if '"error"' not in line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("fc") == "error" and event.get("text"):
            yield str(event["text"])
    yield str(turn.get("reason") or "")


def quota_pause(turn: dict[str, Any] | None, *, now: float | None = None, tries: int = 1) -> QuotaPause | None:
    """Whether this agent turn failed on a provider usage limit, and when Autopilot may try again.

    The newest error that names a provider's HTTP status decides, whole from the transcript when it is there (the
    reason keeps only the run's first error). What the error says is read by ``thomas/core/provider_limits.py``,
    which Chat's failure text now reads too, so a limit cannot be described here one way and there another. The
    time is ``resets_at`` from the body, else a Retry-After counted from the turn's own time, else ``RECHECK_S``
    after it, doubled for each earlier limit in a row (``tries``) up to ``CEILING_S``. A short 429 with none of
    these is a burst, and stays an ordinary failure.
    """
    if not isinstance(turn, dict) or turn.get("ok"):
        return None
    at = _turn_time(turn) or (_clock() if now is None else now)
    limit = next((found for text in _error_texts(turn) if (found := read_limit(text, at=at)) is not None), None)
    if limit is None:
        return None
    verdict = QuotaClassifier().observe(
        limit.provider or "model provider",
        status=limit.status,
        error={"code": limit.quota_code},
        headers=limit.headers,
        now=at,
    )
    if verdict.kind != "quota":
        return None
    recheck = at + min(RECHECK_S * 2 ** max(0, tries - 1), CEILING_S)
    retry_at = float(verdict.retry_at) if limit.reset_known and verdict.retry_at is not None else recheck
    return QuotaPause(limit.account, retry_at, limit.reset_known, limit.estimated, max(1, tries))


def trouble_pause(turn: dict[str, Any] | None, *, now: float | None = None, tries: int = 1) -> TroublePause | None:
    """Wait for provider overload, disconnect, server error or expired login, using the failed turn's time."""
    if not isinstance(turn, dict) or turn.get("ok") or turn.get("outcome") != "failed":
        return None
    error = next((text for text in _error_texts(turn) if not _EXIT_WRAPPER.fullmatch(text.strip())), "")
    trouble = classify(error)
    if trouble is None or trouble.kind not in ("overloaded", "server_error", "signed_out"):
        return None
    model = str(turn.get("model") or "").lower()
    provider = (
        "ChatGPT"
        if "gpt" in model
        else "Claude"
        if any(name in model for name in ("claude", "opus", "sonnet", "haiku"))
        else "your model provider"
    )
    at = _turn_time(turn) or (_clock() if now is None else now)
    return TroublePause(provider, at + min(120 * 2 ** min(max(0, tries - 1), 4), 1800), trouble.kind, max(1, tries))


def trouble_streak(agent_turns: list[dict[str, Any]]) -> int:
    """Count consecutive provider-trouble failures, including the latest one."""
    count = 0
    for turn in reversed(agent_turns):
        if trouble_pause(turn) is None:
            break
        count += 1
    return count


def limit_streak(agent_turns: list[dict[str, Any]]) -> int:
    """How many runs in a row, the last one included, met a usage limit."""
    count = 0
    for turn in reversed(agent_turns):
        if quota_pause(turn) is None:
            break
        count += 1
    return count


def _whose(pause: QuotaPause) -> str:
    return f"your {pause.provider}" if pause.provider else "your model provider's"


def held_reason(conversation: dict[str, Any], pause: QuotaPause | TroublePause) -> str:
    """Why a pause can no longer end by itself, or "" while it can. Worded to follow "stopped before it finished: "."""
    turns = conversation.get("turns") if isinstance(conversation.get("turns"), list) else []
    stamp = conversation.get("autopilot") if isinstance(conversation.get("autopilot"), dict) else {}
    if stamp.get("gave_up") and stamp.get("turns") == len(turns) and not isinstance(pause, TroublePause):
        return str(stamp["gave_up"])
    if pause.tries > MAX_TRIES and not isinstance(pause, TroublePause):
        return (
            f"{_whose(pause)} usage limit was still reached after {pause.tries} tries in a row. Send a message and "
            "Thomas carries on"
        )
    return ""


def paused_text(pause: QuotaPause | TroublePause) -> str:
    """What the chat's card and the chat say while Autopilot waits for its next try."""
    if isinstance(pause, TroublePause):
        return (
            f"Paused: {pause.provider} is having trouble right now ({pause.kind}). "
            f"Thomas tries again {when_words(pause.retry_at)} by himself."
        )
    whose, when = _whose(pause), when_words(pause.retry_at)
    if pause.estimated:
        return f"Paused: {whose} usage limit is reached. Thomas carries on by himself {when}, once it has reset."
    if pause.reset_known:
        return f"Paused: {whose} usage limit is reached. It resets {when}, and Thomas carries on by himself then."
    return (
        f"Paused: {whose} usage limit is reached, and it did not say when it resets. Thomas tries again {when}, "
        "and carries on by himself once it has reset."
    )


def _parks_path(catalog_root: Path) -> Path:
    return Path(catalog_root) / ".thomas" / "evolve" / "agent" / _PARKS_NAME


@contextlib.contextmanager
def _parks_lock(catalog_root: Path) -> Iterator[None]:
    """This process's lock, then a lock on a file beside the list, which another server's process also takes."""
    path = _parks_path(catalog_root).with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock, open(path, "a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)  # waits up to 10 s, then raises OSError
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _read_parks(catalog_root: Path) -> dict[str, dict[str, Any]]:
    try:
        payload = json.loads(_parks_path(catalog_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(cid): row for cid, row in payload.items() if isinstance(row, dict)}


def _write_parks(catalog_root: Path, parks: dict[str, dict[str, Any]]) -> None:
    path = _parks_path(catalog_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(parks, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _change_row(catalog_root: Path, cid: str, row: dict[str, Any] | None) -> None:
    """Replace one row of the list (None removes it), under the lock both servers take."""
    with _parks_lock(catalog_root):
        parks = _read_parks(catalog_root)
        if row is None and cid not in parks:
            return
        if row is None:
            parks.pop(cid, None)
        else:
            parks[cid] = row
        _write_parks(catalog_root, parks)


def _stamp(project_root: Path, cid: str, value: dict[str, Any] | None) -> None:
    """Set the park on the stored conversation, or remove it with None; a missing conversation is never created."""
    if not thomas_project._live_file(project_root, cid).is_file():
        return
    conversation = forge_code_store.load_conversation(project_root, cid)
    if conversation is None or conversation.get("autopilot") == value:
        return
    if value is None:
        conversation.pop("autopilot", None)
    else:
        conversation["autopilot"] = value
    forge_code_store.write_conversation(project_root, conversation)


def park(
    project_root: Path, catalog_root: Path, cid: str, *, until: float, provider: str, port: int = 0, **row: Any
) -> None:
    """Park a conversation until ``until`` (Unix seconds): on the conversation, and in the list the loop reads.
    ``port`` names the server that parked it, the only one that resumes it."""
    stamp = {"parked_until": until, "provider": provider, **({"port": int(port)} if port else {})}
    _stamp(Path(project_root), cid, stamp)
    _change_row(catalog_root, cid, {"project_root": str(project_root), **stamp, **row})


def clear(project_root: Path, catalog_root: Path, cid: str) -> None:
    """End a conversation's park, if it has one: you stopped it, sent something new, or its run has ended."""
    _stamp(Path(project_root), cid, None)
    _change_row(catalog_root, cid, None)


def parked(catalog_root: Path, cid: str) -> dict[str, Any] | None:
    with _parks_lock(catalog_root):
        return _read_parks(catalog_root).get(cid)


def record(
    project_root: Path, catalog_root: Path, cid: str, conversation: dict[str, Any], decision: Any, *, port: int = 0
) -> None:
    """After a run: park the conversation on ``wait``, and end a stored park on any other decision."""
    if decision.action == "wait" and decision.retry_at is not None:
        park(project_root, catalog_root, cid, until=decision.retry_at, provider=decision.provider, port=port)
    elif "autopilot" in conversation or parked(catalog_root, cid) is not None:
        clear(project_root, catalog_root, cid)


def _give_up(project_root: Path, catalog_root: Path, cid: str, conversation: dict[str, Any], why: str) -> None:
    turns = conversation.get("turns") if isinstance(conversation.get("turns"), list) else []
    _change_row(catalog_root, cid, None)
    _stamp(project_root, cid, {"gave_up": why, "turns": len(turns)})  # decide answers "limited" until you write


def rebuild(catalog_root: Path) -> list[str]:
    """List again every park stamped on a conversation but missing from the list: the list was lost or damaged."""
    found: dict[str, dict[str, Any]] = {}
    # Every folder a conversation is bound to, as the registry names it: conversation_roots would skip a folder
    # opened without history, and a park there would stay lost.
    rows = forge_code_conversations._load_registry(catalog_root).values()
    roots = dict.fromkeys([str(catalog_root), *(str(row.get("project_root") or "") for row in rows)])
    for root in (Path(name) for name in roots if name):
        folder = root / ".thomas" / "evolve" / "agent" / "conversations"
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else ():
            try:
                text = path.read_text(encoding="utf-8")
                stamp = json.loads(text).get("autopilot") if '"parked_until"' in text else None
            except (OSError, ValueError, AttributeError):
                continue
            if isinstance(stamp, dict) and stamp.get("parked_until"):
                found[path.stem] = {"project_root": str(root), **stamp}
    with _parks_lock(catalog_root):
        parks = _read_parks(catalog_root)
        added = [cid for cid in found if cid not in parks]
        if added:
            _write_parks(catalog_root, {**parks, **{cid: found[cid] for cid in added}})
    return added


def _run_active(app: Any, cid: str) -> bool:
    from thomas.server.routes.evolve_agent_run_state import APP_EVOLVE_AGENT_RUNS, slot_active

    registry = app.get(APP_EVOLVE_AGENT_RUNS)
    return isinstance(registry, dict) and slot_active(registry.get(cid))


async def _resume_one(app: Any, catalog_root: Path, cid: str, row: dict[str, Any], now: float) -> bool:
    from thomas.server.routes import evolve_agent_autopilot as ap  # it imports this module

    project_root, port = Path(str(row.get("project_root") or "")), int(app.get(ap.APP_LOCAL_PORT) or 0)
    if row.get("port") and port and int(row["port"]) != port:
        return False  # another server's park: only the server that made it resumes it
    if _run_active(app, cid):
        return False  # a run is going (the one after the pause, or yours): its own end decides again
    if not await off_loop("autopilot.park_file", thomas_project._live_file(project_root, cid).is_file):
        await off_loop("autopilot.clear", clear, project_root, catalog_root, cid)
        return False
    conversation = await off_loop("autopilot.read_live", thomas_project._read_live, project_root, catalog_root, cid)
    if conversation is None:
        return False  # caught mid-write: read it again next tick
    decision = ap.decide(conversation)
    if decision.action == "enough":  # paused for you (autopilot_enough): only your reply, held as steering, starts it
        from thomas.server import autopilot_enough  # it imports this module

        return await autopilot_enough.resume(app, project_root, catalog_root, cid, conversation)
    if decision.action == "limited":  # it cannot end by itself; a "gave_up" stamp stays, and decide keeps saying why
        stamp = conversation.get("autopilot") if isinstance(conversation.get("autopilot"), dict) else {}
        await off_loop("autopilot.change_row", _change_row, catalog_root, cid, None)
        if "gave_up" not in stamp:
            await off_loop("autopilot.stamp", _stamp, project_root, cid, None)
        return False
    if decision.action != "wait":  # you stopped it, sent something new, or it is off Autopilot
        await off_loop("autopilot.clear", clear, project_root, catalog_root, cid)
        return False
    turns = [t for t in conversation.get("turns") or [] if isinstance(t, dict)]
    last_agent = next((t for t in reversed(turns) if t.get("role") == "agent"), None)
    last_pause = trouble_pause(last_agent)
    resumed = bool(turns) and str(turns[-1].get("text") or "").startswith((ap.RESUME_PREFIX, ap.TROUBLE_RESUME_PREFIX))
    if resumed and now - float(row.get("started_at") or 0) < STARTED_GRACE_S:
        return False  # its run was started: only one that died without recording its end is started again
    refused_until = float(row.get("refused_until") or 0)
    until = max(float(decision.retry_at or 0), float(row.get("parked_until") or 0), refused_until)
    steered = bool(thomas_project.held_steers(cid)) and now >= refused_until  # your steer ends the pause early
    if now < until and not steered:
        return False
    if app.get(ap.APP_PRAXIS_START_CODE_RUN) is None or not port:
        return False
    # The run's own recorder writes the conversation from here on. The row stays until that run's end parks it
    # again or clears it (record): a restart, a crash or a cancel before then leaves it to be resumed again.
    await off_loop("autopilot.stamp", _stamp, project_root, cid, None)
    if await ap._start_continuation(app, project_root, catalog_root, conversation, cid, decision):
        await off_loop("autopilot.change_row", _change_row, catalog_root, cid, {**row, "started_at": now, "port": port})
        return True
    refusals = int(row.get("refusals") or 0) + 1
    if refusals >= MAX_REFUSALS and not isinstance(last_pause, TroublePause):
        why = f"Build refused to start the run after the pause {refusals} times. Send a message and Thomas carries on"
        await off_loop("autopilot.give_up", _give_up, project_root, catalog_root, cid, conversation, why)
        return False
    wait = min(REFUSED_RETRY_S * 2 ** min(refusals - 1, 10), CEILING_S)
    await off_loop(
        "autopilot.park",
        park,
        project_root,
        catalog_root,
        cid,
        until=float(decision.retry_at or now),
        provider=decision.provider,
        port=port,
        refusals=refusals,
        refused_until=now + wait,
    )
    return False


def _snapshot_parks(catalog_root: Path) -> dict[str, dict[str, Any]]:
    with _parks_lock(catalog_root):
        return _read_parks(catalog_root)


async def resume_due(app: Any, catalog_root: Path, *, now: float | None = None) -> list[str]:
    """Start the next run of every park whose time has come, or that you steered. Returns the ones started."""
    at = _clock() if now is None else now
    parks = await off_loop("autopilot.read_parks", _snapshot_parks, catalog_root)
    started: list[str] = []
    for cid, row in parks.items():
        try:
            if await _resume_one(app, Path(catalog_root), cid, row, at):
                started.append(cid)
        except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
            log.exception("autopilot: the paused conversation %s could not be resumed", cid)
    return started


def card_words(project_root: Path, catalog_root: Path, cid: str) -> tuple[str, str] | None:
    """For the chat's task card: ``("paused", why and until when)`` while a Thomas project waits out a usage
    limit, ``("resumed", ...)`` once the run after the pause has started, else None."""
    from thomas.server.routes import evolve_agent_autopilot as ap  # it imports this module

    conversation = thomas_project._read_live(project_root, catalog_root, cid)
    turns = [t for t in (conversation or {}).get("turns") or [] if isinstance(t, dict)]
    if conversation is None or not turns:
        return None
    if turns[-1].get("role") == "user":
        text = str(turns[-1].get("text") or "")
        if text.startswith(ap.TROUBLE_RESUME_PREFIX):
            return "resumed", TROUBLE_RESUMED_TEXT
        return ("resumed", RESUMED_TEXT) if text.startswith(ap.RESUME_PREFIX) else None
    decision = ap.decide(conversation)
    return ("paused", decision.reason) if decision.action == "wait" else None


def loop_enabled() -> bool:
    """On in the server. Off under pytest unless ``THOMAS_AUTOPILOT_PARK_LOOP`` turns it on (the issue ledger tells a
    test run apart the same way): tests build whole apps, and none may start a Build run from a park."""
    raw = str(os.environ.get(LOOP_ENV) or "").strip().lower()
    if raw:
        return raw not in {"0", "false", "no", "off"}
    return not os.environ.get("PYTEST_CURRENT_TEST")


async def _tick_self_project_queue(app: Any) -> None:
    """Log every queue failure without breaking the park loop."""
    try:
        await late.call(seams.PROJECT_QUEUE_TICK, app)
    except Exception:
        log.exception("Thomas project queue tick failed")


async def park_loop(app: Any, *, catalog_root: Path | None = None) -> None:
    """List any park the list lost, then every ``TICK_S`` start what is due. A failed check is logged and runs
    again next tick; it never raises."""
    catalog = catalog_root or thomas_project._catalog_root()
    try:
        added = await asyncio.to_thread(rebuild, catalog)
        if added:
            log.warning("autopilot: listed %d paused build(s) again from their conversations", len(added))
    except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
        log.exception("autopilot: the paused builds could not be listed again from their conversations")
    from thomas.server import autopilot_hold_tick

    if not paused():
        await autopilot_hold_tick.run(app, catalog, startup=True)
    while True:
        await _sleep(TICK_S)
        if paused():  # nothing is resumed, retried or started from the queue while Thomas is paused
            continue
        try:
            await resume_due(app, catalog)
        except (AttributeError, KeyError, OSError, RuntimeError, TypeError, ValueError):
            log.exception("autopilot: the check for paused builds failed; it runs again in %s s", TICK_S)
        await autopilot_hold_tick.run(app, catalog)
        await _tick_self_project_queue(app)


def start_park_loop(app: Any) -> None:
    if loop_enabled():
        app[APP_AUTOPILOT_PARK_TASK] = asyncio.create_task(park_loop(app), name="autopilot-park-loop")


async def stop_park_loop(app: Any) -> None:
    task = app.get(APP_AUTOPILOT_PARK_TASK)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
