"""Runs the self-change promoter as a service in your session: one instance, a heartbeat, a log.

Started at logon by the scheduled task scripts/cage/enable_promoter.ps1 registers.
The promotion logic lives in scripts/cage/self_change_promoter.py; this only
keeps it running and says what it is doing -- the lessons of the shell runner
(scripts/cage/shell_runner.py): a byte-range lock so two copies never serve one
inbox, a heartbeat on its own thread so a long prompt never looks like a death,
and a log in C:\\ProgramData\\ThomasCage\\promoter so a silent exit is not silent.
"""

from __future__ import annotations

import argparse
import atexit
import logging
import os
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):  # run as a script by the logon task
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.cage import egress_proxy, owner_desk, window_loop  # noqa: E402
from scripts.cage.self_change_promoter import REPO_ROOT, Promoter, _windows_sign_in  # noqa: E402

log = logging.getLogger("thomas.self_change_promoter")


def _take_lock(folder: Path):
    folder.mkdir(parents=True, exist_ok=True)
    handle = open(folder / "promoter.lock", "a+", encoding="utf-8")  # noqa: SIM115 - held for the process lifetime
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


# A restart races the old copy letting go of the lock. On 2026-09-23 an End then
# Run lost that race: the new copy exited without a word under pythonw and took
# the cage's egress proxy with it for a minute.
LOCK_WAIT_S = 15.0


def _wait_for_lock(folder: Path, wait_s: float = LOCK_WAIT_S, step_s: float = 0.5):
    deadline = time.monotonic() + wait_s
    while True:
        handle = _take_lock(folder)
        if handle is not None or time.monotonic() >= deadline:
            return handle
        time.sleep(step_s)


def _beat(path: Path, stop: threading.Event, every_s: float = 5.0) -> None:
    while True:
        path.write_text(datetime.now(timezone.utc).isoformat(timespec="seconds"), encoding="utf-8")
        if stop.wait(every_s):
            return


# What can stop the search broker: an import that fails, a port someone else holds.
_BROKER_FAULTS = (ImportError, SyntaxError, OSError, RuntimeError, ValueError, TypeError, AttributeError, LookupError)
BROKER_RETRY_S = 60.0


def _run_search_broker(stop: threading.Event | None = None, port: int | None = None) -> None:
    """Import and serve the search broker, on this thread only, and write down whatever stops it.

    The broker (search_broker.py) imports aiohttp and the web tools; the egress
    proxy beside it is the cage's only way out. Imported here, in a thread of its
    own, a broker that cannot load or cannot listen never costs the cage its proxy.
    """
    stage = "not started"
    try:
        from scripts.cage import search_broker

        stage = "stopped"
        search_broker.serve_forever(stop=stop, log=log.info, port=port or search_broker.PORT)
    except _BROKER_FAULTS as exc:
        log.error("search broker %s: %s: %s", stage, type(exc).__name__, exc, exc_info=True)
    except BaseException as exc:
        log.exception("search broker %s: %s: %s", stage, type(exc).__name__, exc)
        raise


class _BrokerKeeper:
    """Keeps the search broker running: whenever its thread has ended, starts it again, at most once a minute."""

    def __init__(
        self,
        stop: threading.Event,
        *,
        target: Callable[[], None] | None = None,
        every_s: float = BROKER_RETRY_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.stop, self.every_s, self.clock = stop, every_s, clock
        self.target = target or (lambda: _run_search_broker(stop))
        self.thread: threading.Thread | None = None
        self.started_at: float | None = None

    def tick(self) -> bool:
        """Start the broker if it is not running and has not been started in the last minute."""
        if self.thread is not None and self.thread.is_alive():
            return False
        now = self.clock()
        if self.started_at is not None and now - self.started_at < self.every_s:
            return False
        if self.started_at is not None:
            log.info("search broker is not running; starting it again")
        self.started_at = now
        self.thread = threading.Thread(target=self.target, name="search-broker", daemon=True)
        self.thread.start()
        return True

    def start(self) -> None:
        """Start the broker now, then look again every few seconds on a thread of its own."""
        self.tick()

        def watch() -> None:
            while not self.stop.wait(5.0):
                self.tick()

        threading.Thread(target=watch, name="search-broker-keeper", daemon=True).start()


def _exiting() -> None:
    # On 2026-09-23 this process vanished at 21:51 with no line at all. A normal
    # exit, even by an uncaught error, now writes this; a stop without it was a
    # kill from outside (the task ended, a sign-out, TerminateProcess).
    log.info("promoter process exiting")


# A pass whose hand-in left the inbox with a verdict looks for the next one at once: the next card used to wait out
# the pause too (3 s of the 13-15 s between back-to-back cards, measured 2026-10-08). Anything else -- nothing waiting,
# a hand-in put back (withdrawn) or a pass that failed -- rests first, so the loop never spins.
_FINAL = frozenset({"landed", "declined", "refused", "error"})


def _left_the_inbox(outcome: object) -> bool:
    return getattr(outcome, "status", None) in _FINAL


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Put approved self-fixes into the running Thomas.")
    parser.add_argument("--repo", default=str(REPO_ROOT))
    parser.add_argument("--cage-root", default="")
    parser.add_argument("--once", action="store_true", help="promote at most one submission, then exit")
    parser.add_argument("--interval", type=float, default=3.0)
    args = parser.parse_args(argv)
    from thomas.tools.cage_shell import cage_root

    root = Path(args.cage_root) if args.cage_root else cage_root()
    home = root / "promoter"
    home.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(home / "promoter.log"), level=logging.INFO, format="%(asctime)s pid=%(process)d %(message)s"
    )
    lock = _wait_for_lock(home, LOCK_WAIT_S)
    if lock is None:
        log.warning("another promoter still holds the lock after %ss; this copy exits", LOCK_WAIT_S)
        print("another promoter is already running; exiting")
        return 0
    log.info("promoter started for %s", args.repo)
    atexit.register(_exiting)
    stop = threading.Event()
    try:
        threading.Thread(target=_beat, args=(home / "promoter.heartbeat", stop), daemon=True).start()
        # One Windows sign-in at a time, for the cards, the owner's desk and the window alike.
        asker = window_loop.OnePrompt(_windows_sign_in)
        promoter = Promoter(repo=Path(args.repo), cage_root=root, ask=asker)
        if not args.once:
            # The cage's one way out through the network fence runs here too, as you.
            egress_proxy.start_in_thread(log=log.info)
            # Said before its thread binds: `netstat -ano | findstr :8897` shows whether it did.
            log.info("egress proxy starting on 127.0.0.1:%s", egress_proxy.PORT)
            # And, after it, its search broker: web search and reading search
            # results for the caged Thomas, without a search engine on the
            # fence's list. It runs on a thread of its own; see _run_search_broker.
            _BrokerKeeper(stop).start()
            # Part 4: your window, on a thread of its own, so its landings never wait on a card that is up. If it
            # cannot start, it says so in this log and every change keeps its cards.
            window_loop.start(repo=Path(args.repo), cage_root=root, card=promoter, ask=asker, stop=stop)
        while True:
            handled = None
            try:
                handled = promoter.run_once()
            except (OSError, ValueError, RuntimeError):
                log.exception("promotion pass failed")
            try:
                # The same process answers the server's own approval requests,
                # for when the server runs where it cannot show a prompt.
                owner_desk.serve_once(root, ask=lambda action, reason: asker(action, reason) == "approved")
            except (OSError, ValueError, RuntimeError):
                log.exception("owner desk pass failed")
            if args.once:
                return 0
            if not _left_the_inbox(handled):
                time.sleep(args.interval)
    except BaseException:
        log.exception("promoter stopped by an error it did not catch")
        raise
    finally:
        stop.set()


if __name__ == "__main__":
    raise SystemExit(main())
