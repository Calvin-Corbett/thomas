"""Your window: a deadline held only in the promoter's memory (spec 2026-10-12, section 8.4).

It is opened only after your own Windows sign-in on the pinned ``open_window`` card (scripts/cage/window_loop.py),
with you at this PC in the session that signed in. Nothing about it is written down as authority: the grant is
Express's in-memory one (scripts/cage/referee/grant.py), bound to this promoter run and your logon session, its end the
sooner of the wall clock and the monotonic clock, clamped to the pinned ceiling every time it is read. So it ends on a
promoter restart, a sign-out or a reboot, and a forged file cannot open one.

Before every landing ``why_not`` reads it fresh. It ends the window, for good, when its time is up, it has landed the
number you chose (25 unless you chose another, or none), an off switch is on, the session changed, or your PC has been
locked or idle for longer than the pinned idle limit. While your PC is locked (for less than that) landings wait. A
reading of your presence that fails is a wait, never a landing.

A window you open to keep landing while you are away (your decision, 2026-10-22) skips only the last two: locking and
idle neither pause nor end it. You ask for that on its own card, and only a PC whose elevated setup placed
``window.away`` in the pin folder offers it -- a file no one but SYSTEM and Administrators may have written
(``away_allowed``). It is read before the card, again when the window opens, and on every check after; a window opened
that way ends the moment it no longer holds.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from scripts.cage.referee.authstate import StateError
from scripts.cage.referee.grant import Clock, GrantHolder
from scripts.cage.referee.presence import Presence, PresenceSource, read_presence, touched_recently

OFF_NAME = "window.off"
AWAY_NAME = "window.away"
_TRUSTED_WRITERS = frozenset({"S-1-5-18", "S-1-5-32-544"})  # SYSTEM, Administrators
# Every owner and every Allow entry that can write, for the folder and the file: SIDs, never names (writer_audit.py).
_LIST_ACL = r"""
$ErrorActionPreference = 'Stop'
$writeish = 'Write|Modify|FullControl|Delete|ChangePermissions|TakeOwnership|CreateFiles|AppendData'
foreach ($p in $args) {
  $acl = Get-Acl -LiteralPath $p
  "owner|" + $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
  $acl.Access | Where-Object { $_.AccessControlType -eq 'Allow' -and $_.FileSystemRights.ToString() -match $writeish } |
    ForEach-Object {
      try { "writer|" + $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value }
      catch { "writer|" + $_.IdentityReference.Value }
    }
}
"""


def away_allowed(flag: Path | None) -> str:
    """Empty when *flag* (``window.away`` in the pin folder) turns the away option on for this PC; else why not.

    It counts only when it reads ``on`` and it and its folder are owned by, and writable only by, SYSTEM and
    Administrators: the elevated setup writes it there (scripts/cage/enable_window.ps1 -AwayWindows on), and neither
    your unelevated processes nor the Build teams' account can. A file anyone else could have written does not count."""
    if flag is None:
        return "keeping a window open while you are away is not set up on this PC"
    path = Path(flag)
    try:
        said = path.read_text(encoding="utf-8").strip().lower()
    except OSError:
        said = ""
    if said != "on":
        return "keeping a window open while you are away is off on this PC (an elevated setup step turns it on)"
    if os.name != "nt":
        return "keeping a window open while you are away is checked on Windows only"
    try:
        quoted = " ".join("'" + str(p).replace("'", "''") + "'" for p in (path.parent, path))
        proc = subprocess.run(
            # -Command pastes trailing words onto the script text, so the paths go to a script block (writer_audit.py).
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", f"& {{{_LIST_ACL}}} {quoted}"],
            capture_output=True,
            text=True,
            timeout=60,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),  # no console window on your screen
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"who may write {path} could not be read ({exc})"
    rows = [line.strip().split("|", 1) for line in proc.stdout.splitlines() if "|" in line]
    if proc.returncode != 0 or sum(1 for kind, _ in rows if kind == "owner") != 2:
        return f"who may write {path} could not be read"
    others = sorted({sid for _, sid in rows} - _TRUSTED_WRITERS)
    if others:
        return f"{path} could have been written by someone other than SYSTEM and Administrators ({', '.join(others)})"
    return ""


def _iso(wall: float) -> str:
    return datetime.fromtimestamp(wall, timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Opened:
    window_id: str
    minutes: int
    opened_wall: float
    pairing_code: str
    session: str
    max_landings: int | None = None  # what you chose at its card: a number, or None for no limit
    away: bool = False  # you chose at its card that it keeps landing while your PC is locked or you are away

    @property
    def opened_at(self) -> str:
        return _iso(self.opened_wall)

    def trailer(self) -> dict[str, object]:
        """What each commit and verdict of this window names (spec 8.4: when you opened it, and its pairing code)."""
        return {"window_id": self.window_id, "opened_at": self.opened_at, "pairing_code": self.pairing_code}


class WindowRefused(Exception):  # noqa: N818 - reads as what happened
    """The window cannot open now, for the reason given."""


class Window:
    def __init__(
        self,
        *,
        presence: PresenceSource,
        off_markers: Sequence[Path],
        ceiling_minutes: int,
        max_landings: int,
        idle_minutes: int,
        clock: Clock = time,  # type: ignore[assignment]
        away_flag: Path | None = None,
        away_check: Callable[[Path | None], str] = away_allowed,
    ) -> None:
        self._presence = presence
        self._markers = tuple(Path(marker) for marker in off_markers)
        # max_landings is what a window gets when you choose no number of your own.
        self.ceiling_minutes, self.max_landings, self.idle_minutes = ceiling_minutes, max_landings, idle_minutes
        self._away_flag, self._away_check = away_flag, away_check
        self._clock = clock
        self._holder = GrantHolder(clock)
        self._lock = threading.Lock()
        self._opened: Opened | None = None
        self.landings = 0
        self._locked_since: float | None = None
        self._ended: list[tuple[Opened, str]] = []

    @property
    def opened(self) -> Opened | None:
        return self._opened

    def off_marker(self) -> str:
        return next((str(marker) for marker in self._markers if marker.exists()), "")

    def away_why_not(self) -> str:
        """Empty when this PC lets a window keep landing while you are away (``away_allowed``); else why not."""
        return self._away_check(self._away_flag)

    def may_open(self) -> tuple[str, Presence | None]:
        """("", your presence now) when a window may be asked for; else (why not, None)."""
        marker = self.off_marker()
        if marker:
            return f"an off switch is on ({marker})", None
        try:
            seen = read_presence(self._presence)
        except StateError as exc:
            return f"your presence could not be read ({exc})", None
        if not touched_recently(seen):
            return "you have not used this PC in the last minute, or it is locked", None
        return "", seen

    def open(
        self,
        minutes: int,
        pairing_code: str,
        window_id: str,
        *,
        before: Presence,
        max_landings: object = ...,
        away: bool = False,
    ) -> Opened:
        """Open the window your sign-in approved. *before* is your presence read before the prompt: you must still be
        in that session, unlocked, and have used this PC within the last minute -- for an away window too.
        *max_landings* is the number you chose, None for no limit, the default when you chose none; *away* keeps it
        landing while your PC is locked or you are away, only where ``away_allowed`` says so."""
        if type(minutes) is not int or not 1 <= minutes <= self.ceiling_minutes:
            raise WindowRefused(f"a window lasts 1 to {self.ceiling_minutes} minutes")
        cap = self.max_landings if max_landings is ... else max_landings
        if cap is not None and (type(cap) is not int or cap < 1):
            raise WindowRefused("a window lands at least one change, or has no limit")
        if type(away) is not bool:
            raise WindowRefused("keeping a window open while you are away is a yes or a no")
        if away:
            why = self.away_why_not()
            if why:
                raise WindowRefused(why)
        why, now = self.may_open()
        if why or now is None:
            raise WindowRefused(why or "your presence could not be read")
        if now.logon_session != before.logon_session:
            raise WindowRefused("the session changed while the card was up")
        with self._lock:
            grant = self._holder.open(now.logon_session, minutes, self.ceiling_minutes)
            self._opened = Opened(window_id, minutes, grant.granted_wall, pairing_code, now.logon_session, cap, away)
            self.landings = 0
            self._locked_since = None
            return self._opened

    def why_not(self) -> str:
        """ "" when a landing may start now. Otherwise why not; a reason that ends the window ends it here."""
        with self._lock:
            opened = self._opened
            if opened is None:
                return "no window is open"
            marker = self.off_marker()
            if marker:
                return self._end(f"an off switch is on ({marker})")
            grant = self._holder.current
            if grant is None or grant.session != opened.session:
                return self._end("the window was lost")
            if grant.remaining(self._clock.time(), self._clock.monotonic(), self.ceiling_minutes) <= 0:
                return self._end("its time is up")
            if opened.max_landings is not None and self.landings >= opened.max_landings:
                return self._end(f"it landed {opened.max_landings} changes; open a new one to land more")
            if opened.away:
                why = self.away_why_not()
                if why:
                    return self._end(f"keeping it open while you are away stopped: {why}")
            try:
                seen = read_presence(self._presence)
            except StateError as exc:
                return f"your presence could not be read ({exc}); landings wait"
            if seen.logon_session != opened.session:
                return self._end("you signed out, or the PC restarted")
            if opened.away:  # you chose it at its card: locked or idle, it keeps landing
                self._locked_since = None
                return ""
            limit = self.idle_minutes * 60
            if seen.locked:
                now = self._clock.monotonic()
                self._locked_since = now if self._locked_since is None else self._locked_since
                if now - self._locked_since > limit:
                    return self._end(f"your PC was locked for more than {self.idle_minutes} minutes")
                return "your PC is locked; landings wait until you are back"
            self._locked_since = None
            if seen.idle_seconds > limit:
                return self._end(f"your PC was idle for more than {self.idle_minutes} minutes")
            return ""

    def _end(self, why: str) -> str:
        opened, self._opened = self._opened, None
        self._holder.revoke(why)
        if opened is not None:
            self._ended.append((opened, why))
        return why

    def close(self, why: str) -> Opened | None:
        """End the window now (you closed it, a check after landing failed, the promoter is stopping)."""
        with self._lock:
            opened = self._opened
            if opened is not None:
                self._end(why)
            return opened

    def take_ended(self) -> list[tuple[Opened, str]]:
        """Every window that ended since the last call, with why: each is recorded once."""
        with self._lock:
            ended, self._ended = self._ended, []
            return ended

    def landed(self) -> None:
        with self._lock:
            self.landings += 1

    def status(self) -> dict[str, object]:
        with self._lock:
            opened, grant = self._opened, self._holder.current
            if opened is None or grant is None:
                return {"open": False}
            left = max(0.0, grant.remaining(self._clock.time(), self._clock.monotonic(), self.ceiling_minutes))
            return {
                "open": True,
                **opened.trailer(),
                "minutes": opened.minutes,
                "ends_at": _iso(self._clock.time() + left),
                "landings": self.landings,
                "max_landings": opened.max_landings,  # None: no limit
                "away": opened.away,
            }


__all__ = ["AWAY_NAME", "OFF_NAME", "Opened", "Window", "WindowRefused", "away_allowed"]
