"""What Autopilot does when its team says something it cannot do stops it from finishing.

You said: "autopilot ... is meant to actually fix issues with Thomas that prevent him from finish not the actually
work continuous forever like if I said post an ad to Facebook he can't do that so autopilot knows to go download it
all because I already gave permission to do so". And when the team says it is done, it is done.

The team is told (``AUTOPILOT_BLOCKED_RULE`` in ``thomas/core/autonomy.py``) to end its final answer with one line
when something stops it: ``BLOCKED: <what is missing> | NEEDS: <what would unblock it>``, plus ``| OWNER`` when only
you can give it. :func:`judge` reads that line from the run that just ended, ok or not:

* without OWNER, the next round gets what is needed within the permissions you already gave, then goes back and
  finishes the goal (:func:`blocker_message`). The same blocker twice in a row, with nothing changed the second
  time, is no progress: the project pauses for you instead of a third try;
* with OWNER, it pauses for you at once, in words that say exactly what is needed from you.

A pause is ``autopilot_enough``'s, so the project shows as paused and your next message carries it on. A run with no
such line is not judged here. Spending money, accepting terms, entering passwords or payment details, and posting in
public are always yours: the rule tells the team so, and nothing here ever starts them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from thomas.core.acceptance_notes import THOMAS_NOTES_END, THOMAS_NOTES_START
from thomas.core.autonomy import AUTOPILOT_BLOCKED_RULE
from thomas.server.autopilot_enough import REPLY, instruction
from thomas.server.routes.autopilot_goal import CONTINUATION_PREFIX

# The round that gets what a blocked run said it was missing. It starts with CONTINUATION_PREFIX, so the goal stays
# your request and the round counts as one Autopilot wrote.
BLOCKER_PREFIX = f"{CONTINUATION_PREFIX}: getting what the work needs"
WHY = "blocked"  # the pause's why on the project's record
_LINE = re.compile(
    r"^[\s>*_`-]*BLOCKED\s*:\s*(?P<missing>.+?)"
    r"(?:\s*\|\s*NEEDS\s*:\s*(?P<needs>.+?))?"
    r"(?:\s*\|\s*(?P<owner>OWNER))?[\s*_`.]*$",
    re.IGNORECASE,
)
_TAIL_LINES = 20  # the end of the final answer: the line need not be the very last one
_TAIL_CHARS = 8000


@dataclass(frozen=True)
class Blocker:
    """One BLOCKED line: what is missing, what would unblock it, and whether only you can give it."""

    missing: str
    needs: str
    owner: bool

    def same_as(self, other: Blocker | None) -> bool:
        return other is not None and (_plain(self.missing), _plain(self.needs)) == (
            _plain(other.missing),
            _plain(other.needs),
        )


@dataclass(frozen=True)
class Verdict:
    """What ``decide`` answers for a blocked run: ``continue`` with *message*, or ``enough`` with *reason* shown."""

    action: str
    reason: str
    message: str = ""
    why: str = ""


def _plain(text: str) -> str:
    return " ".join(str(text).casefold().split()).rstrip(".")


def read(turn: dict[str, Any] | None) -> Blocker | None:
    """The last BLOCKED line at the end of a run's transcript, or None. The rule's own example is not one."""
    transcript = str((turn or {}).get("transcript") or "")[-_TAIL_CHARS:]
    lines = [line for line in transcript.splitlines() if line.strip()][-_TAIL_LINES:]
    for line in reversed(lines):
        found = _LINE.match(line)
        if found is None or found["missing"].lstrip().startswith("<"):
            continue
        return Blocker(found["missing"].strip(), (found["needs"] or "").strip(), bool(found["owner"]))
    return None


def _notes(text: str) -> str:
    return f"{THOMAS_NOTES_START}\n{text}\n{THOMAS_NOTES_END}"


def blocker_message(goal: str, turn: dict[str, Any], blocker: Blocker | None) -> str:
    """The round after a blocked run: get what is missing within the permissions already given, then finish."""
    blocker = blocker or Blocker("something the last run could not do", "", False)
    changed = turn.get("changed_files") if isinstance(turn.get("changed_files"), list) else []
    report = _notes(
        f"The last run stopped: it is missing {blocker.missing}.\n"
        f"What would unblock it: {blocker.needs or 'not said'}\n\n"
        f"Files changed so far: {', '.join(map(str, changed)) or 'none'}"
    )
    return (
        f"{BLOCKER_PREFIX} toward the goal: {goal}\n\n{report}\n\n"
        "What stopped the last run is the next task, not the end of the work. Get it within the permissions you "
        "were already given: install the tool or package, download what is needed, sign in where a sign-in is "
        "already saved, or write the missing piece of Thomas itself. Then go back and finish the goal, and run its "
        f"checks.\n\n{AUTOPILOT_BLOCKED_RULE}"
    )


def judge(turns: list[dict[str, Any]], goal: str) -> Verdict | None:
    """What Autopilot does about the BLOCKED line the last run ended with, or None when it ended with none."""
    since = turns[instruction(turns) + 1 :]
    runs = [turn for turn in since if isinstance(turn, dict) and turn.get("role") == "agent"]
    if not runs:
        return None
    last = runs[-1]
    blocker = read(last)
    if blocker is None:
        return None
    needs = blocker.needs or "not said"
    if blocker.owner:
        words = (
            f"Paused for you: the team cannot finish without you. It is missing {blocker.missing}. "
            f"What it needs from you: {needs}. {REPLY}"
        )
        return Verdict("enough", words, why=WHY)
    if len(runs) >= 2 and blocker.same_as(read(runs[-2])) and not last.get("changed_files"):
        words = (
            "Paused for you: the same thing stopped the team twice in a row, and it changed nothing the second "
            f"time. It is missing {blocker.missing}. What would unblock it: {needs}. {REPLY}"
        )
        return Verdict("enough", words, why=WHY)
    return Verdict("continue", f"blocked: {blocker.missing}", blocker_message(goal, last, blocker))


__all__ = ["BLOCKER_PREFIX", "WHY", "Blocker", "Verdict", "blocker_message", "judge", "read"]
