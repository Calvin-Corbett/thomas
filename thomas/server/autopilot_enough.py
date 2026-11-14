"""When a Thomas project stops getting anywhere, it pauses and asks you, instead of going round for days.

You said "he needs a good this enough to stop". Measured in November 2026: one project's change failed its check
before your card 48 times in a row, with a different patch every round; another's check came back "unavailable" 35
times on the same patch, tried again about every two hours; a dozen Builds ran 30 to 84 hours each. Since 0899834bc
removed ``MAX_REPAIR_ROUNDS`` nothing stopped any of them.

This is not a clock and not a round limit: a project that is still making progress is never stopped. Three rules
each look for progress since your last message, and pause the project only when there has been none for a while:

1. Repairs (:func:`repairs_stalled`): progress is the number of failing tests the check finds reaching a new lowest.
   After :data:`STALL_ROUNDS` sent-back rounds in a row with no new lowest, no new round starts. A new kind of finding,
   or one kind going away, is not progress on its own. A round where dev moved still counts: the team cannot fix
   that either, and the decision is yours.
2. Unavailable (:func:`unavailable_stalled`): after :data:`UNAVAILABLE_LIMIT` checks in a row that could not run,
   with no verdict between them, no further try is scheduled.
3. Done checks (:func:`tweaking`, Autopilot only): after :data:`TWEAK_CHECKS` done checks in a row that each changed
   files again, the team is tweaking instead of finishing, and no further done check starts.

A pause is a stamp on the project's record (``thomas_project.enough``: why, the words shown, the turn count and when),
written like ``repairs_spent``. While it stands, ``decide`` answers ``enough`` and starts nothing, a restart does not
carry it on, the hand-in is not retried or booked again, and the project shows as **paused** -- never ended -- so its
copy is kept. Your next message lifts it: typed in Build, or replied in Chat, which holds it as steering that the park
loop starts (:func:`resume`). Each pause is recorded as an issue.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.forge.anvil import forge_code_store
from thomas.server import autopilot_park, thomas_project
from thomas.server.issue_ledger import record_issue
from thomas.server.routes.autopilot_goal import CONTINUATION_PREFIX, steers_in
from thomas.server.routes.autopilot_messages import REVIEW_PREFIX

# Five rounds in a row without fewer failing tests: enough for a team to try several different fixes, and a team that
# is getting somewhere lowers the count well within that. Any new lowest starts the five again, so progress is never
# cut off however many rounds it takes.
STALL_ROUNDS = 5
# Four checks in a row that could not run: at hand_in_hold's back-off (900 s, 900 s, 1800 s) that is about an hour of
# a check that cannot run. Waiting longer only waits; whether to free room, fix the check or drop it is yours.
UNAVAILABLE_LIMIT = 4
# Six done checks in a row that each changed files again: a finished change survives its first done check or two; six
# rounds of edits after "finished" is the team polishing instead of stopping.
TWEAK_CHECKS = 6
REPLY = "Reply and Thomas carries on."
_ROUND_WHYS = (thomas_project.SENT_BACK, thomas_project.DEV_MOVED)  # the rounds the check before your card starts
_NODE = re.compile(r"^(?:FAILED|ERROR) (\S+::\S+)", re.M)  # pytest's own summary lines
_LISTED = re.compile(r"^- (?!and \d+ more$)\S", re.M)  # precard.report lists each finding as "- name"
_MORE = re.compile(r"^- and (\d+) more$", re.M)
_PROBLEMS = re.compile(r"\b(\d+) problem\(s\)")
_WORDS_MAX = 2000


def _turns(conversation: dict[str, Any] | None) -> list[dict[str, Any]]:
    turns = (conversation or {}).get("turns")
    return [turn for turn in turns if isinstance(turn, dict)] if isinstance(turns, list) else []


def _record(conversation: dict[str, Any] | None) -> dict[str, Any]:
    project = (conversation or {}).get("thomas_project")
    return project if isinstance(project, dict) else {}


def yours(turn: dict[str, Any]) -> bool:
    """A message you wrote: any user turn Autopilot did not write, and an Autopilot round carrying your steering."""
    if not isinstance(turn, dict) or turn.get("role") != "user":
        return False
    text = str(turn.get("text") or "")
    return not text.startswith(CONTINUATION_PREFIX) or bool(steers_in(text))


def instruction(turns: list[dict[str, Any]]) -> int:
    """The index of your last message in *turns*, or -1."""
    return next((i for i in range(len(turns) - 1, -1, -1) if yours(turns[i])), -1)


def standing(conversation: dict[str, Any] | None) -> str:
    """The words of the pause on this project while it stands, else "". Your next message lifts it."""
    stamp = _record(conversation).get("enough")
    if not isinstance(stamp, dict):
        return ""
    try:
        since = max(0, int(stamp.get("turns") or 0))
    except (TypeError, ValueError):
        since = 0
    if any(yours(turn) for turn in _turns(conversation)[since:]):
        return ""
    return str(stamp.get("words") or stamp.get("why") or "paused")


def failing_count(detail: Any) -> int | None:
    """How many failing tests (or other findings) a check's findings name; None when they name no number."""
    text = str(detail or "")
    listed = len(_LISTED.findall(text)) + sum(int(n) for n in _MORE.findall(text))
    counted = max(len(set(_NODE.findall(text))), listed)
    if counted:
        return counted
    problems = [int(n) for n in _PROBLEMS.findall(text)]
    return max(problems) if problems else None


def no_new_lowest(counts: list[int | None]) -> tuple[int, int | None]:
    """How many entries at the end of *counts* reached no new lowest, and the lowest. An uncountable one is none."""
    best: int | None = None
    streak = 0
    for count in counts:
        if count is not None and (best is None or count < best):
            best, streak = count, 0
        else:
            streak += 1
    return streak, best


def _live(project_root: Path, cid: str) -> dict[str, Any] | None:
    if not thomas_project._live_file(project_root, cid).is_file():
        return None
    conversation = forge_code_store.load_conversation(project_root, cid)
    return conversation if isinstance(conversation, dict) and _record(conversation) else None


def stamp(project_root: Path, catalog_root: Path, cid: str, *, why: str, words: str, port: int = 0) -> bool:
    """Pause the project for you: True once a pause stands. A pause already standing is not stamped or recorded again.

    It is also listed on Autopilot's park list (``autopilot_park``), so a reply you send from Chat, held as steering,
    is started by the park loop (:func:`resume`); a restart leaves a listed conversation alone as well.
    """
    root = Path(project_root)
    conversation = _live(root, cid)
    if conversation is None:
        return False
    row = {"project_root": str(root), "enough": str(why), **({"port": int(port)} if port else {})}
    autopilot_park._change_row(Path(catalog_root), cid, row)
    if standing(conversation):
        return True
    shown = str(words)[:_WORDS_MAX]
    at = datetime.now(timezone.utc).isoformat()
    _record(conversation)["enough"] = {"why": str(why), "words": shown, "turns": len(_turns(conversation)), "at": at}
    forge_code_store.write_conversation(root, conversation)
    record_issue(
        surface="autopilot", kind="autopilot_enough", message=shown, context={"conversation_id": cid, "why": why}
    )
    return True


def _moment(turn: dict[str, Any] | None) -> datetime | None:
    return thomas_project._moment((turn or {}).get("ts")) if turn else None


def repairs_stalled(project_root: Path, catalog_root: Path, cid: str, why: str, detail: str) -> bool:
    """Rule 1: True when this sent-back finding would be the STALL_ROUNDS-th round in a row with no new lowest count
    of failing tests since your last message; the project is then paused for you instead of sent back again."""
    if why not in _ROUND_WHYS:
        return False
    conversation = _live(Path(project_root), cid)
    if conversation is None:
        return False
    turns = _turns(conversation)
    at = instruction(turns)
    since = _moment(turns[at]) if at >= 0 else None
    rounds = [
        done
        for done in _record(conversation).get("repairs") or []
        if isinstance(done, dict) and done.get("why") in _ROUND_WHYS
        if since is None or (moment := thomas_project._moment(done.get("at"))) is None or moment > since
    ]
    counts = [failing_count(done.get("detail")) for done in rounds] + [failing_count(detail)]
    streak, best = no_new_lowest(counts)
    if streak < STALL_ROUNDS:
        return False
    last = counts[-1]
    first = next((line.strip() for line in str(detail).splitlines() if line.strip()), "")[:300]
    words = (
        f"Paused for you: its change was sent back to its team {len(counts)} times since your last message, and the "
        f"last {streak} checks found no fewer failing tests than the fewest so far "
        f"({'none counted' if best is None else best}; this time {'not counted' if last is None else last}). "
        f"What the check found last: {first} {REPLY}"
    )
    return stamp(project_root, catalog_root, cid, why="repairs", words=words)


def unavailable_stalled(project_root: Path, catalog_root: Path, cid: str, line: str, *, key: list[Any]) -> bool:
    """Rule 2: count one check that could not run (*key*: the try, so the same try is never counted twice); True once
    UNAVAILABLE_LIMIT have come in a row with no verdict between them -- the project is then paused for you.

    A verdict that sends the change back adds a repair round, and your message moves the last instruction: either
    starts the count again.
    """
    root = Path(project_root)
    conversation = _live(root, cid)
    if conversation is None:
        return False
    project = _record(conversation)
    mark = [thomas_project.repairs_done(project), instruction(_turns(conversation))]
    seen = project.get("unavailable") if isinstance(project.get("unavailable"), dict) else {}
    fresh = seen.get("mark") == mark
    if fresh and seen.get("key") == key:
        return bool(standing(conversation))
    count = (int(seen.get("count") or 0) if fresh else 0) + 1
    project["unavailable"] = {"count": count, "mark": mark, "key": key, "line": str(line)[:_WORDS_MAX]}
    forge_code_store.write_conversation(root, conversation)
    if count < UNAVAILABLE_LIMIT:
        return False
    words = (
        f"Paused for you: the check before your approval card could not run {count} times in a row, with no verdict "
        f"in between. The last time: {line} {REPLY}"
    )
    return stamp(root, catalog_root, cid, why="unavailable", words=words)


def tweaking(turns: list[dict[str, Any]]) -> str:
    """Rule 3: the pause's words when the last TWEAK_CHECKS done checks since your last message each changed files."""
    streak, pending = 0, False
    for turn in turns[instruction(turns) + 1 :]:
        if turn.get("role") == "user":
            pending = str(turn.get("text") or "").startswith(REVIEW_PREFIX)
        elif turn.get("role") == "agent" and pending:
            streak, pending = (streak + 1 if turn.get("changed_files") else 0), False
    if streak < TWEAK_CHECKS:
        return ""
    return (
        f"Paused for you: {streak} done checks in a row each changed files again instead of finding it finished. "
        f"{REPLY}"
    )


async def resume(app: Any, project_root: Path, catalog_root: Path, cid: str, conversation: dict[str, Any]) -> bool:
    """The park loop's turn for a paused project: your reply from Chat, held as steering, starts its run now."""
    from thomas.server.routes import evolve_agent_autopilot as ap  # it imports this module

    if thomas_project.stop_requested(conversation) or not await asyncio.to_thread(thomas_project.held_steers, cid):
        return False
    await ap._start_steered_round(app, conversation, cid, Path(catalog_root))
    return not await asyncio.to_thread(thomas_project.held_steers, cid)


__all__ = [
    "REPLY",
    "STALL_ROUNDS",
    "TWEAK_CHECKS",
    "UNAVAILABLE_LIMIT",
    "failing_count",
    "instruction",
    "no_new_lowest",
    "repairs_stalled",
    "resume",
    "stamp",
    "standing",
    "tweaking",
    "unavailable_stalled",
    "yours",
]
