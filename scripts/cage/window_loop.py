"""The window's own loop, on a thread beside the card loop in the promoter's process (spec 2026-10-12, 8.3-8.8).

A card prompt has no timeout, and the card loop waits inside it; so the window runs on its own thread and its landings
never wait on a card (spec 8.3). Each pass, about every three seconds:

1. your requests (scripts/cage/window_control.py), read from C:\\ProgramData\\ThomasCage\\promoter\\window\\requests,
   which only your account and SYSTEM can reach: the caged server cannot ask for a window and the owner's desk never
   shows one. An open request shows the pinned ``open_window`` card at your Windows sign-in -- ``open_window_away``
   when you asked for one that keeps landing while you are away, and only where this PC allows it -- with how long
   and how many you chose, and only your approval, with you still at this PC, opens the window;
2. the window read fresh; a window that ended is recorded once, with what it landed, read from dev;
3. the check after the last landing (spec 8.6), when one is running: no other change lands until it answers. A
   failure, or no answer within an hour, closes the window; a failure also starts the revert of that change, asked on
   the ``revert_change`` card once the checker passed the revert. Nothing is reverted without your sign-in;
4. the lane (scripts/cage/window_lane.py): while a window is open, every hand-in the card loop has not taken is
   taken up (under the card loop's own lock), checked by the checker and read by the second look, and at most one is
   landed; when the window ends, or the checker or the record cannot be relied on, every one goes back to the cards;
5. the undo under way (scripts/cage/window_undo.py);
6. the status file the control reads.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import logging
import re
import secrets
import threading
import time
from collections.abc import Callable
from pathlib import Path

from scripts.cage import checker_jobs as cj
from scripts.cage import self_change_checks as checks
from scripts.cage import self_change_promoter as sp
from scripts.cage.window_after import AFTER_DEADLINE_S, After, AfterChecks
from scripts.cage.window_cards import ask_card
from scripts.cage.window_record import Record, window_summary
from scripts.cage.window_state import Window, WindowRefused

from thomas.tools import trusted_card

log = logging.getLogger("thomas.self_change_promoter")
REQUESTS, STATUS, OFF, COPIES = "requests", "status.json", "off", "copies"
REQUEST_TTL_S = 600.0
_SID = re.compile(r"self-[A-Za-z0-9_-]{1,80}")
_LOOP_FAULTS = (OSError, ValueError, RuntimeError, LookupError, TypeError, AttributeError, checks.Refused)


def window_home(cage_root: Path) -> Path:
    return Path(cage_root) / "promoter" / "window"


class OnePrompt:
    """One Windows sign-in at a time across the promoter's loops: two at once could be answered for each other."""

    def __init__(self, ask: Callable[[str, str], bool | str]) -> None:
        self._ask = ask
        self._lock = threading.Lock()
        self._turn = threading.local()

    def __call__(self, action: str, reason: str) -> bool | str:
        with self._lock:
            self._turn.started = time.time()  # the wait behind the other loop's prompt ends here
            return self._ask(action, reason)

    def turn_started(self) -> float | None:
        """When this thread's latest prompt got its turn (time.time()): a card that waited behind a window card, which
        stays up until you answer it, is timed from here, not from the wait (self_change_promoter._sign_in)."""
        return getattr(self._turn, "started", None)


class WindowLoop:
    def __init__(
        self,
        *,
        card: sp.Promoter,
        lane: object,
        undoer: object,
        window: Window,
        link: object,
        record: Record,
        home: Path,
        ask: Callable[..., tuple[str, str]] = ask_card,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.card, self.lane, self.undoer, self.window = card, lane, undoer, window
        self.link, self.record, self.home, self.ask, self.clock = link, record, Path(home), ask, clock
        self.after: After | None = None
        self.after_checks = AfterChecks(self)  # each landing's check after it, kept through a restart (review D1)
        self.batch: list[str] = []  # hand-ins landed in the open window
        self.landed_files: list[str] = []  # their files: the check after landing runs all of their tests
        self.notes: list[str] = []
        self.healthy = True  # False after a pass that failed: the cards take the window's changes until one works (D2)

    def card_skip(self) -> frozenset[str]:
        """What the card loop leaves alone: the hand-ins the window's lane took up."""
        if not self.healthy or not self._reliable():
            return frozenset()  # an off switch, or no checker or record to rely on: its changes get cards (D3)
        return self.lane.owned()

    def _reliable(self) -> bool:
        return not (self.window.off_marker() or self.link.answering() or self.record.usable())

    def tick(self) -> None:
        if self.lane.last_landed is not None:
            self._landed()  # its post or record failed on the pass before: no other landing until it is done
        self._serve_requests()
        self.window.why_not()  # ends the window here when it should end
        self._record_ended()
        self._after_check()
        allowed = self.after is None and self.lane.last_landed is None and not self.link.answering()
        with self.card.taking:  # the card loop picks its hand-ins under this lock: none is ever held by both loops
            self.lane.take(self.window, card_busy=self.card.busy, reliable=self._reliable())
            self.healthy = True  # after a failed pass the cards could take them; from here the lane holds its own (D2)
        self.lane.step(self.window, card_busy=self.card.busy, landing_allowed=allowed)
        if self.lane.last_landed is not None:  # its check after landing is posted and recorded, or retried (D1)
            self._landed()
        if (said := self.undoer.step()) and said != (self.notes[-1:] or [""])[0]:
            self._note(said)
        self.after_checks.revert()  # a queued revert starts once the undoer is free (review D8)
        self._write_status()

    def run(self, stop: threading.Event, interval_s: float = 3.0) -> None:
        """Pass after pass until *stop*. Any fault in a pass is logged and hands the window's changes to the cards; when
        the thread ends, however it ends, the cards take them for good and the window closes (2026-10-14 review, D2)."""
        try:
            while not stop.wait(interval_s):
                try:
                    self.tick()
                except Exception:  # noqa: BLE001 - _LOOP_FAULTS once let an ImportError end the thread silently
                    self.healthy = False
                    log.exception("a window pass failed")
        finally:
            self.card.skip = frozenset
            self.window.close("the promoter is stopping")
            try:
                self._record_ended()
            finally:
                self.lane.close()

    def recover(self) -> None:
        """Settle every landing the promoter stopped inside, and rebuild the check after every landing that has none
        recorded, before the thread starts (scripts/cage/window_after.py; review D1)."""
        self.after_checks.recover()

    # -- requests ------------------------------------------------------------ #
    def _serve_requests(self) -> None:
        folder = self.home / REQUESTS
        for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
            try:
                request = cj.read_json(path, 4096)
            except (OSError, ValueError, RecursionError):
                request = None
            path.unlink(missing_ok=True)
            self._note(self._handle(request))

    def _handle(self, request: object) -> str:
        if not isinstance(request, dict) or not isinstance(request.get("at"), (int, float)):
            return "a request that is not one was removed unread"
        if self.clock() - float(request["at"]) > REQUEST_TTL_S:
            return f"a {request.get('kind')} request older than ten minutes was removed unasked"
        kind = request.get("kind")
        if kind == "open" and type(request.get("minutes")) is int:
            cap, away = request.get("max_landings", self.window.max_landings), request.get("away", False)
            if (cap is None or type(cap) is int) and type(away) is bool:
                return self._open(request["minutes"], cap, away)
        if kind == "close":
            opened = self.window.close("you closed it")
            return f"window {opened.window_id} closed" if opened else "no window was open"
        if kind == "undo" and isinstance(request.get("sid"), str) and _SID.fullmatch(request["sid"]):
            return self.undoer.start(request["sid"]) or f"undoing {request['sid']}: started"
        return "a request that is not one was removed unread"

    def _open(self, minutes: int, cap: int | None = None, away: bool = False) -> str:
        """Ask your sign-in for a window of *minutes*, landing at most *cap* changes (None: no limit), and, when *away*,
        landing on while your PC is locked or you are away: each on the card you sign, each in its pairing code."""
        if self.window.opened is not None:
            return "a window is already open"
        why = self.record.usable() or self.link.answering()
        if why:
            return f"no window: {why}"
        why, before = self.window.may_open()
        if why or before is None:
            return f"no window: {why}"
        if not 1 <= minutes <= self.window.ceiling_minutes:
            return f"no window: a window lasts 1 to {self.window.ceiling_minutes} minutes"
        if cap is not None and cap < 1:
            return "no window: a window lands at least one change, or has no limit"
        why = self.window.away_why_not() if away else ""
        if why:
            return f"no window: {why}"
        catalogue = trusted_card.load_catalogue()
        waiting = sorted(self.lane.takeable(self.card.busy))
        # Past six days a weekday and time no longer names the day, so the card names the date (until-off windows).
        ends = time.strftime(
            "%a %H:%M" if minutes <= 6 * 24 * 60 else "%a %Y-%m-%d", time.localtime(self.clock() + minutes * 60)
        )
        window_id = secrets.token_hex(8)
        words = catalogue.window_cap_words(cap)
        details = {"minutes": minutes, "ends": ends, "waiting": len(waiting), "cap": words}
        chosen = {"minutes": minutes, "waiting": waiting, "max_landings": cap, "away": away}
        digest = hashlib.sha256(json.dumps(chosen).encode("utf-8")).hexdigest()
        kind = "open_window_away" if away else "open_window"
        answer, code = self.ask(self.lane.p, kind, details, digest, window_id)
        if answer != "approved":
            return "you cancelled the window" if answer == "cancelled" else "the sign-in did not go through; no window"
        try:
            opened = self.window.open(minutes, code, window_id, before=before, max_landings=cap, away=away)
        except WindowRefused as exc:
            return f"no window: {exc}"
        self.batch, self.landed_files = [], []
        self._event("window_opened", **opened.trailer(), minutes=minutes, ends=ends, waiting=waiting, max_landings=cap,
                    away=away, account=getpass.getuser(), catalogue=trusted_card.catalogue_digest())  # fmt: skip
        said = "; it KEEPS LANDING while your PC is locked or you are away" if away else ""
        return f"window {window_id} open until {ends} (pairing code {code}), landing {words}{said}"

    # -- landings and the check after them ----------------------------------- #
    def _landed(self) -> None:
        self.after_checks.landed()

    def _after_check(self) -> None:
        self.after_checks.check()

    def _record_ended(self) -> None:
        for opened, why in self.window.take_ended():
            rows = window_summary(self.card.repo, self.card.branch, opened.window_id)
            self._event("window_closed", window_id=opened.window_id, reason=why, landed=rows)
            self._note(f"window {opened.window_id} ended: {why}; it landed {len(rows)} change(s)")
            self.batch, self.landed_files = [], []

    # -- what you see -------------------------------------------------------- #
    def _write_status(self) -> None:
        after = self.after
        status = {
            "at": self.clock(),
            "window": self.window.status(),
            "checker": self.link.answering() or "answering",
            "after_check": {"sid": after.sid, "commit": after.commit} if after else None,
            "pending_reverts": [row["sid"] for row in self.after_checks.reverts.pending],
            "waiting": self.lane.waiting(),
            "undo": self.undoer.said if self.undoer.current is not None else "",
            "notes": self.notes[-12:],
        }
        self.home.mkdir(parents=True, exist_ok=True)
        cj.write_json(self.home / STATUS, status)

    def _note(self, words: str) -> None:
        log.info("window: %s", words)
        self.notes = [*self.notes[-40:], f"{time.strftime('%H:%M:%S')} {words}"]

    def _event(self, name: str, **fields: object) -> None:
        try:
            self.record.event(name, **fields)
        except OSError:
            log.warning("the window's record could not take %s", name, exc_info=True)


def start(**kwargs: object) -> WindowLoop | None:
    """Build the window's loop and start its thread: scripts/cage/window_start.py, kept apart for room (review D19)."""
    from scripts.cage.window_start import start as build

    return build(**kwargs)  # type: ignore[arg-type]


__all__ = ["AFTER_DEADLINE_S", "After", "OnePrompt", "WindowLoop", "start", "window_home"]
