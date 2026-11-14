"""Build the window's loop and start its thread (spec 2026-10-12, section 8).

Kept out of scripts/cage/window_loop.py so that file stays under the 300-line limit (plan Step 4b; 2026-10-14 review,
D19). If anything here cannot be set up -- the catalogue is not the pinned one, a folder is missing, a module will not
import -- the window does not start and every change keeps its cards (spec 8.1). Everything the loop needs is imported
inside ``start``, so this module and window_loop.py do not import each other at load time.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from scripts.cage import checker_jobs as cj
from scripts.cage import self_change_promoter as sp

from thomas.tools import trusted_card

log = logging.getLogger("thomas.self_change_promoter")


def start(
    *,
    repo: Path,
    cage_root: Path,
    card: sp.Promoter,
    ask: Callable[[str, str], bool | str],
    stop: threading.Event,
    pin_root: Path | None = None,
    check_root: Path = cj.CHECK_ROOT,
    record_root: Path | None = None,
) -> object | None:
    """Build the window's loop and start its thread; None, with every change keeping its cards, when it cannot."""
    from scripts.cage import window_record
    from scripts.cage.window_checker import CheckerLink
    from scripts.cage.window_lane import Lane
    from scripts.cage.window_loop import COPIES, OFF, REQUESTS, WindowLoop, window_home
    from scripts.cage.window_presence import InSession
    from scripts.cage.window_record import Record
    from scripts.cage.window_review import Reviewer
    from scripts.cage.window_rules import Rules
    from scripts.cage.window_state import AWAY_NAME, OFF_NAME, Window
    from scripts.cage.window_undo import Undoer

    from thomas.tools import cage_shell

    try:
        catalogue = trusted_card.load_catalogue()
        home = window_home(cage_root)
        (home / REQUESTS).mkdir(parents=True, exist_ok=True)
        lane_promoter = sp.Promoter(repo=repo, cage_root=cage_root, ask=ask, pin_root=pin_root)
        link, record = CheckerLink(check_root), Record(record_root or window_record.RECORD_ROOT)
        pins = Path(pin_root or cage_shell.DEFAULT_PIN_ROOT)
        markers = [pins / OFF_NAME, home / OFF]
        # The away option is read from the pin folder only, never from the window's home or the cage, which other
        # accounts can reach: only an elevated step writes there (window_state.away_allowed).
        window = Window(presence=InSession(), off_markers=markers, ceiling_minutes=catalogue.WINDOW_CEILING_MINUTES,
                        max_landings=catalogue.WINDOW_MAX_LANDINGS, idle_minutes=catalogue.WINDOW_IDLE_MINUTES,
                        away_flag=pins / AWAY_NAME)  # fmt: skip
        reviewer = Reviewer(repo=repo, copies=home / COPIES)
        lane = Lane(lane_promoter, link=link, reviewer=reviewer, rules=Rules(repo), record=record)
        loop = WindowLoop(card=card, lane=lane, undoer=Undoer(lane_promoter, link=link, record=record),
                          window=window, link=link, record=record, home=home)  # fmt: skip
        loop.recover()
    except (ImportError, OSError, RuntimeError, ValueError, AttributeError, trusted_card.CatalogueTampered):
        log.exception("the window's loop could not start; every change keeps its cards")
        return None
    card.skip = loop.card_skip
    threading.Thread(target=loop.run, args=(stop,), name="window-loop", daemon=True).start()
    log.info("the window's loop started")
    return loop


__all__ = ["start"]
