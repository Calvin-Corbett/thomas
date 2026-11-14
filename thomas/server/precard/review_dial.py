"""How many second looks run at once on this machine, and the pause when your Claude plan says no (spec Part 1 item 6).

At most :func:`capacity` second looks run at once across both servers (``THOMAS_SECOND_LOOKS``, 2 unless set): each
takes its turn through the machine-wide ledger (:mod:`thomas.server.capacity_ledger`, kind ``second_look``), first
come, first served. Each server reads that setting for itself and counts the second looks of both against it, so start
both servers with the same value. When the Claude CLI says your plan's usage limit is reached, every second look on this
machine pauses until the reset time the CLI printed (:func:`plan_reset`), or, when no exact time can be read from what
it printed, until the time Thomas works out to look again. The pause is kept beside the ledger
(``second_look_pause.json``), under its file lock, so both servers keep it: one waiting stops waiting at once, and its
hand-in is held until then instead of asking again every 15 minutes.

A limit gives you one notice, however long it lasts, whichever server meets it first (:func:`pause`). The limit is one
episode: it begins at the first pause after a second look that succeeded (or when no pause has been kept yet) and ends
when a second look succeeds while no pause is in force (:func:`answered`). A pause that comes back inside the episode,
because the reset passed and the limit was met again, records no new notice; a limit met after a success does.

What a page or a steer shows of the pause is read by :func:`pause_shown`, which takes no lock: a display never waits
for the ledger. Every decision (a second look's turn, a new pause) reads it under the ledger's lock.

A second look never runs without its turn. When the ledger cannot be read (:class:`TurnUnavailable`) it does not run
at all: the hand-in is held and tried again, which costs nothing.
"""

from __future__ import annotations

import contextlib
import json
import logging
import math
import os
import re
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from thomas.core import atomic_json, claude_plan, provider_limits
from thomas.server import capacity_ledger, green_checkout
from thomas.server import capacity_ledger_locks as locks
from thomas.server.precard import clocks, review_job

log = logging.getLogger(__name__)

SECOND_LOOKS_ENV = "THOMAS_SECOND_LOOKS"
DEFAULT_SECOND_LOOKS = 2
KIND = "second_look"
PAUSE_NAME = "second_look_pause.json"
RECHECK_S = 30 * 60.0  # a refusal with no believable reset time is looked at again this much later
JUST_DUE_S = 75 * 60.0  # a bare time printed up to this long before now is the time just past, never tomorrow's
_LEGACY = re.compile(r"\bClaude AI usage limit reached\b(?:\|(\d{10}))?")
clock: Callable[[], float] = time.time  # this module's own clock, so a test moves only it


class Paused(Exception):
    """Second looks are paused for your plan's usage limit until :attr:`until`."""

    def __init__(self, until: float, estimated: bool) -> None:
        super().__init__(f"second looks are paused until {until:.0f}")
        self.until, self.estimated = until, estimated


class TurnUnavailable(Exception):
    """The ledger that gives second looks their turns could not be read, so this one may not run."""


def _record_notice(until: float, estimated: bool, waiting: int) -> None:
    from thomas.server import issue_ledger

    when = provider_limits.when_words(until)
    if estimated:  # no exact reset could be read: say when Thomas looks again, not a reset he does not know
        message = (
            "Second looks are paused: your Claude plan's usage limit is reached, and Thomas could not read an exact "
            f"reset time from the CLI. Finished changes wait before their cards; Thomas looks again {when}."
        )
    else:
        message = (
            "Second looks are paused: your Claude plan's usage limit is reached. Finished changes wait before their "
            f"cards until it resets {when}; Thomas carries on by himself then."
        )
    issue_ledger.record_issue(
        surface="second_look",
        kind="second_looks_paused",
        message=message,
        context={"until": round(until), "waiting": waiting},
    )


notice: Callable[[float, bool, int], None] = _record_notice


def capacity() -> int:
    """The dial: THOMAS_SECOND_LOOKS when it is a whole number of at least 1, else 2. Read per server process."""
    try:
        value = int(str(os.environ.get(SECOND_LOOKS_ENV) or "").strip())
    except ValueError:
        return DEFAULT_SECOND_LOOKS
    return value if value >= 1 else DEFAULT_SECOND_LOOKS


def _read_pause(place: Path) -> dict[str, Any]:
    """The pause file as {until, estimated, noticed}. Missing or garbled is no pause; an unreadable file raises."""
    try:
        found = json.loads((place / PAUSE_NAME).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, RecursionError):
        found = None
    found = found if isinstance(found, dict) else {}
    try:
        until = float(found.get("until") or 0.0)
    except (TypeError, ValueError, OverflowError):
        until = 0.0
    return {
        "until": until if math.isfinite(until) else 0.0,
        "estimated": bool(found.get("estimated")),
        "noticed": bool(found.get("noticed")),
    }


def _in_force(until: float, now: float) -> bool:
    """Whether a pause until *until* holds at *now*. One further off than a reset is believed to be
    (:data:`~thomas.core.provider_limits.MAX_AHEAD_S`) does not: a clock that was wrong must not hold second looks."""
    return now < until <= now + provider_limits.MAX_AHEAD_S


def _pause(now: float) -> tuple[float, bool]:
    """(until, estimated) of the pause both servers keep at *now*; (0.0, False) when there is none."""
    place = capacity_ledger.folder()
    with locks.locked(place, capacity_ledger.NAME):
        state = _read_pause(place)
    return (state["until"], state["estimated"]) if _in_force(state["until"], now) else (0.0, False)


def pause_shown(now: float | None = None) -> tuple[float, bool] | None:
    """(the reset, whether it is an estimate) a page or a steer shows while second looks are paused; else None.

    None for no pause, and when the file cannot be read. For display only, and safe on the event loop: it takes
    neither the ledger's thread lock nor its file lock, so it never waits. The file is replaced whole (:func:`pause`),
    so a read sees a whole old or a whole new one. The rules that say whether a pause is in force are :func:`_pause`'s;
    every decision keeps using that one, under the lock.
    """
    try:
        state = _read_pause(capacity_ledger.folder())
    except (OSError, ValueError):  # not readable now: the words go without the pause, and the next look reads again
        return None
    held = _in_force(state["until"], clock() if now is None else now)
    return (state["until"], state["estimated"]) if held else None


def _counted(state: str) -> int:
    return sum(1 for row in capacity_ledger.rows() if row.get("kind") == KIND and row.get("state") == state)


def running() -> int:
    """Second looks running now, on either server."""
    return _counted("admitted")


def waiting() -> int:
    """Second looks waiting for their turn, on either server."""
    return _counted("waiting")


def _still_on() -> None:
    until, estimated = _pause(clock())
    if until:
        raise Paused(until, estimated)


@contextmanager
def turn() -> Iterator[None]:
    """Wait for this second look's turn among both servers', in the order asked.

    Raises :class:`Paused` while paused, also while it waits, and :class:`TurnUnavailable` when the ledger (or the
    pause kept beside it) cannot be read: nothing the ``with`` block does is ever run without its turn.
    """
    review_job.check_cancelled()
    queued, started = time.time(), time.monotonic()
    limit, where = capacity(), green_checkout.green_root()

    def watch() -> None:
        review_job.check_cancelled()
        _still_on()

    with contextlib.ExitStack() as held:
        try:
            held.enter_context(
                capacity_ledger.admitted(
                    f"second-look:{uuid.uuid4().hex}", kind=KIND, limit=limit, where=where, watch=watch
                )
            )
            watch()  # a pause or cancellation as this one was admitted never reaches the CLI
        except OSError as exc:  # TimeoutError, PermissionError, LedgerUnreadable: the row it waited in is given back
            raise TurnUnavailable(str(exc)) from exc
        finally:
            clocks.span("second_look_queue", queued, time.time(), seconds=time.monotonic() - started)
        yield


def pause(until: float, *, estimated: bool = False) -> bool:
    """Pause every second look on this machine until *until*; True, and one notice, for a limit's first refusal.

    The notice belongs to the limit's episode (the module docstring), and ``noticed`` lives in the shared file, so a
    server restarted partway through a limit does not give another. A refusal during the pause, or one that comes after
    the pause ended with no second look succeeding since, moves the pause and records no notice; the first refusal after
    a success records one. A pause that cannot be kept (the ledger's folder cannot be written) is logged and returns
    False: the refused second look is held all the same, and the next one asks the CLI itself.
    """
    place = capacity_ledger.folder()
    try:
        with locks.locked(place, capacity_ledger.NAME):
            state = _read_pause(place)
            if not _in_force(state["until"], clock()) or until > state["until"]:
                state.update(until=float(until), estimated=bool(estimated))  # "noticed" stays: the same limit
            first = not state["noticed"]
            state["noticed"] = True
            atomic_json.write_json_atomic(place / PAUSE_NAME, state)
    except OSError:
        log.exception("could not keep the pause for your plan's usage limit in %s", place)
        return False
    if first:
        try:
            others = waiting()
        except OSError:  # a count for the notice only
            others = 0
        notice(state["until"], state["estimated"], others)
    return first


def answered() -> None:
    """A second look succeeded: with no pause in force, the limit's episode is over, and its notice with it.

    The next limit then records its own notice. A success while a pause is in force (a second look that was already
    running when the limit was met) changes nothing: that limit keeps its one notice. Never raises over the answer.
    """
    place = capacity_ledger.folder()
    try:
        with locks.locked(place, capacity_ledger.NAME):
            state = _read_pause(place)
            if state["noticed"] and not _in_force(state["until"], clock()):
                atomic_json.write_json_atomic(place / PAUSE_NAME, {**state, "noticed": False})
    except OSError:
        log.exception("could not note in %s that the reviewer answered", place)


def plan_reset(said: str, *, now: float) -> tuple[float, bool] | None:
    """(when second looks may ask again, whether that time is estimated) for your plan's limit; None for anything else.

    Only the CLI's own sentences count: "You've hit your session limit · resets ..." and the older "Claude AI usage
    limit reached|<epoch>". A short throttle ("not your usage limit") is never a pause. A reset that is missing, past,
    or more than 31 days off is replaced by :data:`RECHECK_S` from now. A bare time is read as of :data:`JUST_DUE_S`
    ago, so one printed just before now is the time just past (looked at again in :data:`RECHECK_S`), never tomorrow's.
    """
    text = str(said or "").strip()
    legacy = _LEGACY.search(text)
    if legacy is None and not claude_plan.plan_limit_words(text):
        return None
    moment: float | None = None
    exact = False
    if legacy is not None and legacy.group(1):
        moment, exact = float(legacy.group(1)), True
    elif legacy is None:
        found = claude_plan.reset_from_words(text, datetime.fromtimestamp(now - JUST_DUE_S).astimezone())
        if found is not None:
            moment, exact = float(found[0]), bool(found[1])
    if moment is None or not now < moment <= now + provider_limits.MAX_AHEAD_S:
        return now + RECHECK_S, True
    return moment, not exact


__all__ = [
    "DEFAULT_SECOND_LOOKS",
    "JUST_DUE_S",
    "KIND",
    "PAUSE_NAME",
    "RECHECK_S",
    "SECOND_LOOKS_ENV",
    "Paused",
    "TurnUnavailable",
    "answered",
    "capacity",
    "pause",
    "pause_shown",
    "plan_reset",
    "running",
    "turn",
    "waiting",
]
