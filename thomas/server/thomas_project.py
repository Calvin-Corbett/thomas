"""A Thomas project: Build's full team, in a private copy, landing through your cards.

You asked: "so when thomas works on himself make sure their is a task
manegrr just for thomas project like he does with every new build." Before
this, asking Thomas to change himself went to one chat worker in a green
copy with no task manager and no builders or reviewers (measured
2026-09-23: a one-level `task.spawn`, tried at most 3 times,
`worker_runtime.py:343-373`).

A Thomas project is the fix: it makes a green copy of Thomas's own source
(:func:`green_checkout.create_green`) and starts an ordinary Build run in it
through the same guarded internal start Chat already uses
(``app[APP_PRAXIS_START_CODE_RUN]``). That run gets the full Build team --
task manager, builders, reviewers, Praxis helpers -- like every other new
project, because it IS an ordinary Build run; the only thing that makes it a
"Thomas project" is the green it runs in and the ``thomas_project`` record
stamped on its conversation. Nothing here ever reaches the running checkout:
the green copy is the fence, and the only door out of it is
:func:`settle_if_finished`, which hands a finished, checked run to
``green_handoff.settle`` -- your promoter card, same as any other self-fix.

Fix round 1 (opus review of 2467fd28, probed against a real green):
``green_handoff.settle`` deletes the whole green, and the Build conversation
lives inside it -- every turn, including the ``thomas_project`` stamp
itself. So the conversation is copied to a root that survives the green
(:func:`forge_code_store.write_conversation`, the catalog root) BEFORE
settling, and ``settled_at`` is stamped there once the hand-off finished:
a submission went out (even if the green could not be removed afterwards,
fix round 2's case H), or the patch was empty and the green is gone.
Deciding WHETHER to settle now lives in ``evolve_agent_autopilot`` (it needs
``decide()``'s own answer, which this module cannot see without importing
back into its caller); :func:`settle_if_finished` here still independently
guards its own preconditions -- a real ``thomas_project`` record, not
already settled -- so a bad call settles nothing rather than trusting the
caller blindly.

Fix round 2 (opus re-review of 212cd52f, an 8-case probe against real
greens): the *first* round's own commit message and changelog claimed
:func:`start_thomas_project`'s blocking calls already ran off the event loop
-- they did not; only :func:`settle_if_finished` (called from
``evolve_agent_autopilot``) did. Measured stalls of 5-7s on a real green.
:func:`create_green`, :func:`~thomas.forge.anvil.forge_code_projects.
bind_conversation` and :func:`~thomas.server.green_checkout.remove_green`
now run through ``asyncio.to_thread``, like the settle call already did.
Two more fixes here: the registry row for a green that a settle genuinely
could not hand off is no longer forgotten (a forgotten row made the still-
live conversation unreachable and left the green to a 24h sweep instead of
a retry); and a ``remove_green`` failure AFTER a real submission was
written no longer gets reported as a failed hand-off -- the card already
went out.

Task 4 (Chat starts these now, ``chat_self_project``): the settle summary
names every file in the green's patch, not only the last turn's; a start
cancelled while ``create_green`` is still in its thread removes that green
once the thread finishes; a project Chat started records
``chat_session_id``, so its cards reach that chat; and a project that stops
unfinished with real changes keeps its green (:func:`keep_unfinished`).

Task 3b: a finished project's green is kept until the promoter's verdict
(``green_handoff.await_verdict``). A refusal because dev moved on stamps a repair
round on the conversation (:func:`prepare_repair`; no limit on how many), and Autopilot sends it back to the team in the same
green; so does a change that breaks the repo's size rule (:class:`ChangeTooLarge`).
The request tells each team the repo's conventions and what the other running
projects have changed so far.

Task 3d: a hand-in checked before your card and withdrawn, or one you declined,
goes back to its team the same way, with the findings (:data:`SENT_BACK`).

Task 3h: :func:`settle_if_finished` runs that check itself (:mod:`thomas.server.precard`); a change that fails
goes back to its team as a :data:`SENT_BACK` round, and one that passes is handed in saying what was checked.
The patch handed in is the one that was checked, byte for byte (``precard.check_for_hand_in``); a change that
moved while it was being checked goes back the same way.

Every repair round stamped is also counted in :mod:`thomas.server.repair_ledger`, and a new project's notes say,
right after the lessons, what earlier teams were sent back for most often.

The words a project writes (its title, subject, summary and team notes) are in
:mod:`thomas.server.thomas_project_words`. Its start is in :mod:`thomas.server.thomas_project_start` and its settle in
:mod:`thomas.server.thomas_project_settle` (spec 2026-10-12 Part 2, "Size first": this file was 795 lines). Both
resolve here through this module's ``__getattr__``, and both look up here, each time they run, what they take from it.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.core import project_root
from thomas.core.config import resolve_thomas_data_dir
from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.server import green_handoff, green_rebase, repair_ledger, thomas_project_quiet

# isort: split
# Kept for the test that patches find_green through thomas_project.green_checkout.
from thomas.server import green_checkout  # noqa: F401

# The start and the settle look up record_issue and the thomas_project_words names here each time they run,
# so tests that patch thomas_project.<name> still reach the code that moved.
from thomas.server.issue_ledger import record_issue  # noqa: F401
from thomas.server.thomas_project_words import TEAM_NOTES as _TEAM_NOTES  # noqa: F401
from thomas.server.thomas_project_words import change_summary as _change_summary  # noqa: F401
from thomas.server.thomas_project_words import patch_files as _patch_files  # noqa: F401
from thomas.server.thomas_project_words import short_title as _short_title  # noqa: F401
from thomas.server.thomas_project_words import siblings_note as _siblings_note  # noqa: F401
from thomas.server.thomas_project_words import subject as _subject  # noqa: F401

log = logging.getLogger(__name__)
# Held from the last "still current" test through the hand-off; request_stop takes it too, so your Stop lands
# either before a hand-in starts or after its card exists, never in between.
_handover_lock = threading.RLock()


class ThomasProjectError(RuntimeError):
    """A Thomas project could not be started."""


class ChangeTooLarge(ThomasProjectError):
    """The change breaks the repo's size rule, which the promoter does not check, so it is not handed in."""


# A refused hand-in goes back to its team as many times as it takes: there is no round limit. The owner, 2026-11-05:
# a limit is what makes it stop with a fixable problem left, or rush toward the limit. The round count is shown, never enforced.
DEV_MOVED, TOO_LARGE = "dev_moved", "too_large"
# Task 3d: checked before it landed and sent back to its team with the findings (self_project_routes' send-back).
SENT_BACK = "sent_back"
# What prepare_repair says once the rounds are spent, in each reason's own words.
_SPENT = {
    DEV_MOVED: "dev moved on again",
    TOO_LARGE: "it still breaks the size rule",
    SENT_BACK: "it was sent back again",
}
# evolve_agent_autopilot.REPAIR_PREFIX: the user turn that starts a repair round.
REPAIR_TURN = "Autopilot: continuing: repair round"


def _catalog_root() -> Path:
    """The same resolver ``_start_run`` reads for its own ``catalog_root``.

    A conversation bound anywhere else is a conversation the live server's
    own start route will never find by id -- it would silently mint a
    second, unmarked one instead and this one would sit orphaned in green.
    """
    return project_root.code_checkout()


def chat_to_follow(catalog_root: Path, cid: str) -> str:
    """The chat a settled project's approval cards belong in: the Chat that asked, else the Build conversation."""
    conversation = forge_code_store.load_conversation(catalog_root, cid) or {}
    project = conversation.get("thomas_project") if isinstance(conversation.get("thomas_project"), dict) else {}
    return str(project.get("chat_session_id") or "") or cid


def _live_file(project_root: Path, cid: str) -> Path:
    # forge_code_store.conversations_dir's layout, spelled out: that helper creates the folder it names.
    return Path(project_root) / ".thomas" / "evolve" / "agent" / "conversations" / f"{cid}.json"


def _read_live(project_root: Path, catalog_root: Path, cid: str) -> dict[str, Any] | None:
    """The Build conversation in the green, joined with its settings, read without creating anything.

    ``forge_code_store.load_conversation`` makes the conversation folder (``conversations_dir``). Read in a green
    that settling had just removed, it put an empty skeleton back where the green was (Task 4, found by its tests).
    """
    try:
        conversation = json.loads(_live_file(project_root, cid).read_text(encoding="utf-8"))
    except (OSError, ValueError, MemoryError, RecursionError):  # a record this read cannot take is not a crash
        return None
    if not isinstance(conversation, dict):
        return None
    metadata = forge_code_projects.conversation_metadata(catalog_root, cid) or {}
    return {**conversation, "settings": metadata.get("settings") or {}}


# Steering you sent from Chat while no Build run could take it (Task 4 fix round 1, I2), keyed by the Build
# conversation. The next run starts with it (evolve_agent_autopilot). The atomic mailbox
# survives a server generation; entries leave only after a launch accepts them.
_HELD_STEERS: dict[str, list[str]] = {}
# Conversations you stopped from Chat's card (M5), and when, so no next Autopilot round starts even when the
# stamp on the conversation file itself lost a race with the run's own recorder.
_STOPPED: dict[str, str] = {}
_mailbox_lock = threading.Lock()
# evolve_agent_autopilot.CONTINUATION_PREFIX: a user turn that starts with it is Autopilot's, not yours.
_AUTOPILOT_TURN = "Autopilot: continuing"


def _steering_path() -> Path:
    """Under the data folder, as the reload marker is: a test's data folder is its own, a checkout's is shared."""
    return resolve_thomas_data_dir() / "held-steering.json"


def _read_steering() -> dict[str, list[str]]:
    """The mailbox on disk, or what this process holds while no file has been written yet."""
    try:
        value = json.loads(_steering_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {cid: list(items) for cid, items in _HELD_STEERS.items()}
    if not isinstance(value, dict) or any(
        not isinstance(items, list) or any(not isinstance(text, str) for text in items) for items in value.values()
    ):
        raise ValueError("Invalid held steering mailbox; refusing to overwrite queued messages")
    return value


def _write_steering(value: dict[str, list[str]]) -> None:
    path = _steering_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _HELD_STEERS.clear()
    _HELD_STEERS.update(value)


def hold_steer(cid: str, text: str) -> None:
    with _mailbox_lock:
        value = _read_steering()
        value.setdefault(str(cid), []).append(str(text))
        _write_steering(value)


def held_steers(cid: str) -> list[str]:
    with _mailbox_lock:
        return list(_read_steering().get(str(cid), []))


def drop_steers(cid: str, count: int) -> None:
    """Forget a prefix only once a run carrying it has actually started."""
    with _mailbox_lock:
        value = _read_steering()
        remaining = value.get(str(cid), [])[max(0, count) :]
        if remaining:
            value[str(cid)] = remaining
        else:
            value.pop(str(cid), None)
        _write_steering(value)


def steering_message(steers: list[str], rest: str) -> str:
    """A run's message with your steering right after its first paragraph, which names what the run is.

    Round 2, N2: the steering used to come first, so a done check no longer started with its own prefix;
    ``decide()`` then asked for one more done check, and the next goal text nested the whole earlier message.
    """
    if not steers:
        return rest
    block = "Steering update: " + (steers[0] if len(steers) == 1 else "\n".join(f"- {s}" for s in steers))
    head, _, tail = rest.partition("\n\n")
    return "\n\n".join(part for part in (head, block, tail) if part)


def request_stop(project_root: Path, cid: str) -> None:
    """You stopped this project from Chat: ``decide()`` answers "off" from now on, so no next round starts.

    Stamped on the conversation in the green (``thomas_project.stopped_at``) as well as held in memory: the
    file stamp outlives this process, and the memory mark wins a race with the run's own recorder, which
    rewrites the same file from a copy it read before the stamp.
    """
    with _handover_lock:
        stamp = datetime.now(timezone.utc).isoformat()
        with _mailbox_lock:
            _STOPPED[str(cid)] = stamp
            mailbox = _read_steering()
            mailbox.pop(str(cid), None)
            _write_steering(mailbox)
        path = _live_file(project_root, cid)
        try:
            conversation = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(conversation, dict) and isinstance(conversation.get("thomas_project"), dict):
            conversation["thomas_project"]["stopped_at"] = stamp
            forge_code_store.write_conversation(project_root, conversation)


def _moment(value: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def stop_requested(conversation: dict[str, Any]) -> bool:
    """You stopped this project from Chat, and have not started it again yourself since.

    Round 2, N3: the stop was permanent, so a run you later started by hand in Build on the same conversation
    could never settle to your approval card. A message of your own after the stop (not one Autopilot wrote)
    lifts it.
    """
    record = conversation.get("thomas_project") if isinstance(conversation.get("thomas_project"), dict) else {}
    with _mailbox_lock:
        stamps = [_moment(record.get("stopped_at")), _moment(_STOPPED.get(str(conversation.get("id") or "")))]
    stopped = max((moment for moment in stamps if moment is not None), default=None)
    if stopped is None:
        return False
    turns = conversation.get("turns") if isinstance(conversation.get("turns"), list) else []
    yours = [
        _moment(t.get("ts"))
        for t in turns
        if isinstance(t, dict) and t.get("role") == "user" and not str(t.get("text") or "").startswith(_AUTOPILOT_TURN)
    ]
    return not any(moment is not None and moment > stopped for moment in yours)


def settled_record(catalog_root: Path, cid: str) -> dict[str, Any] | None:
    """The settled project's record -- its ``summary`` and ``submission`` -- or None if it has not settled."""
    stored = forge_code_store.load_conversation(catalog_root, cid) or {}
    project = stored.get("thomas_project")
    return dict(project) if isinstance(project, dict) and project.get("settled_at") else None


def project_phase(
    project_root: Path,
    catalog_root: Path,
    cid: str,
    *,
    conversation: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    hold_rows: list[dict[str, Any]] | None = None,
    catalog_conversation: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Where a project stands, from what is stored, for the chat's task card and ``GET /api/self/projects``.

    ``("settled", summary)`` (summary "" when no submission went out), ``("waiting", why)`` while a run or
    Autopilot's next step or the settle is due (why "" before the first run records), ``("paused", why)`` while
    Autopilot waits out your usage limit, or ``("ended", why)`` when nothing more will happen by itself:
    Autopilot's cap, stall or a limit that held, a failed or stopped run below it -- or, since
    :mod:`thomas.server.thomas_project_quiet`, a project whose green has been silent for an hour with no run
    going. Without that last one a project killed before it recorded a turn read as "running" forever.

    Not while this server's restart pass is about to start its run (``autopilot_restart.phase``: at most
    ``WAIT_LIMIT_S`` after the server started). Its file was last written when the stopped run started, hours
    before by the morning after, and "ended" let the ratchet hand in the green that run's team was about to edit.
    """
    from thomas.server import autopilot_restart, hand_in_hold  # autopilot_restart imports this module

    if hold_rows is None:
        hold = hand_in_hold.phase(project_root, catalog_root, cid)
    else:
        hold = hand_in_hold.phase(
            project_root,
            catalog_root,
            cid,
            hold_rows=hold_rows,
            conversation=conversation,
            catalog_conversation=catalog_conversation,
            metadata=metadata,
        )
    if hold is not None:
        return hold
    if hold_rows is None:
        phase, why = _stored_phase(project_root, catalog_root, cid)
    else:
        phase, why = _stored_phase(
            project_root,
            catalog_root,
            cid,
            conversation=conversation,
            metadata=metadata,
            catalog_conversation=catalog_conversation,
        )
    if (phase, why) == ("waiting", autopilot_restart.CARRYING_ON):
        return phase, why
    return thomas_project_quiet.settle_quiet(_live_file(project_root, cid), phase, why)


def _stored_phase(
    project_root: Path,
    catalog_root: Path,
    cid: str,
    *,
    conversation: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    catalog_conversation: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """What the stored conversation says, before the quiet rule above is applied to it."""
    from thomas.server.routes import evolve_agent_autopilot as ap  # it imports this module

    stored = catalog_conversation if metadata is not None else forge_code_store.load_conversation(catalog_root, cid)
    project = (stored or {}).get("thomas_project") or {}
    if project.get("settled_at"):
        return "settled", str(project.get("summary") or "") if project.get("submission") else ""
    if stored is not None:  # settling copies it out first; the green is being handed over, so leave it alone
        return "waiting", thomas_project_quiet.HANDING_OVER
    if held_steers(cid):  # a run stopped for your steering, or a round about to carry it
        return "waiting", "Your steering update goes first in the next run"
    if metadata is None and not _live_file(project_root, cid).is_file():
        return "ended", "its Build conversation is gone"
    if metadata is not None and conversation is None:
        return "ended", "its Build conversation is gone"
    conversation = (
        _read_live(project_root, catalog_root, cid)
        if metadata is None
        else {**conversation, "settings": metadata.get("settings") or {}}
    )
    if conversation is None:  # M6: caught mid-write -- read it again next check, never an ending
        return "waiting", ""
    from thomas.server import autopilot_restart  # it imports this module

    if restarted := autopilot_restart.phase(conversation):  # Task 3f: its run stopped with the server before
        return restarted
    turns = conversation.get("turns") if isinstance(conversation.get("turns"), list) else []
    last = next((t for t in reversed(turns) if isinstance(t, dict) and t.get("role") == "agent"), None)
    if last is None:
        return "waiting", ""
    decision = ap.decide(conversation)
    # Paused on your usage limit, carrying on by itself (autopilot_park); or, "enough", paused for you because it
    # stopped making progress (autopilot_enough): never ended, so its copy is kept and your reply carries it on.
    if decision.action in ("wait", "enough"):
        return "paused", decision.reason
    if decision.action in ("continue", "review", "repair"):
        return "waiting", f"Autopilot: {decision.reason}"
    if ap._thomas_project_should_settle(decision, conversation):
        # Nothing is booked yet (hand_in_hold), so an hour of quiet still ends it: a crash before booking.
        return "waiting", "Its finished change has not started its check before your approval card yet."
    return "ended", decision.reason if decision.action in ("cap", "stall", "limited", "spent") else str(
        last.get("reason") or decision.reason
    )


def _turns(conversation: dict[str, Any]) -> list[dict[str, Any]]:
    turns = conversation.get("turns") if isinstance(conversation.get("turns"), list) else []
    return [turn for turn in turns if isinstance(turn, dict)]


def _project(conversation: dict[str, Any]) -> dict[str, Any]:
    project = conversation.get("thomas_project")
    return project if isinstance(project, dict) else {}


def repairs_done(project: dict[str, Any]) -> int:
    """How many repair rounds a project (its ``thomas_project`` record) has been given."""
    return len([done for done in project.get("repairs") or [] if isinstance(done, dict)])


def repair_due(conversation: dict[str, Any]) -> dict[str, Any] | None:
    """The repair round stamped on this conversation that no run has started yet, or None."""
    rounds = [done for done in _project(conversation).get("repairs") or [] if isinstance(done, dict)]
    user = [str(t.get("text") or "") for t in _turns(conversation) if t.get("role") == "user"]
    return rounds[-1] if len(rounds) > sum(1 for text in user if text.startswith(REPAIR_TURN)) else None


def repairs_spent(conversation: dict[str, Any]) -> str:
    """Why no more repair rounds start, while nothing has happened since they ran out; else ""."""
    spent = _project(conversation).get("repairs_spent")
    if isinstance(spent, dict) and spent.get("turns") == len(_turns(conversation)):
        return str(spent.get("why") or "")
    return ""


def prepare_repair(project_root: Path, catalog_root: Path, cid: str, *, why: str, detail: str, sid: str = "") -> int:
    """Stamp the next repair round on a project's conversation in its green: its number, or 0 when none may start.

    The rounds live on the conversation's own record, so Autopilot's ``decide`` sees one due until a run starts it
    (:func:`repair_due`). A project already handed in is bound to its green again and the copy made when it settled
    is removed: Build refuses to continue a settled conversation, and the one in the green is the live one again.
    """
    conversation = forge_code_store.load_conversation(project_root, cid) or {}
    project = _project(conversation)
    if not project.get("execution_id"):
        return 0
    rounds = [done for done in project.get("repairs") or [] if isinstance(done, dict)]
    merged = green_rebase.rebase_onto_dev(str(project["execution_id"])).stamp() if why == DEV_MOVED else {}
    dev = merged.pop("dev", "") or green_handoff.dev_tip(str(project["execution_id"]))
    stamp = datetime.now(timezone.utc).isoformat()
    rounds.append({"round": len(rounds) + 1, "why": why, "detail": str(detail), "dev": dev, "sid": sid, "at": stamp})
    if why == SENT_BACK:
        rounds[-1]["changed_files"] = _patch_files(str(project["execution_id"]))
    rounds[-1].update(merged)  # Task 3h: its team has no shell, so the server merged dev into its green first
    project["repairs"] = rounds
    project.pop("repairs_spent", None)
    forge_code_store.write_conversation(project_root, conversation)
    repair_ledger.record(why, str(detail))  # the kind it came back for, for every later project; never raises
    handed_in = _project(forge_code_store.load_conversation(catalog_root, cid) or {})
    if handed_in.get("settled_at"):
        settings = handed_in.get("bound_settings") if isinstance(handed_in.get("bound_settings"), dict) else {}
        forge_code_projects.bind_conversation(
            catalog_root, cid, project_root, settings=settings, allow_without_history=True
        )
        if not forge_code_store.delete_conversation(catalog_root, cid):
            log.warning("could not remove %s's settled copy, so Build will refuse its repair round", cid)
    return len(rounds)


def __getattr__(name: str) -> Any:
    """The start and the settle live in their own modules now; their names resolve here too, so no caller moved."""
    from thomas.server import thomas_project_settle, thomas_project_start

    for module in (thomas_project_start, thomas_project_settle):
        if name in module.NAMES:
            return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "DEV_MOVED",
    "REPAIR_TURN",
    "SENT_BACK",
    "TOO_LARGE",
    "ChangeTooLarge",
    "ThomasProjectError",
    "chat_to_follow",
    "drop_steers",
    "held_steers",
    "hold_steer",
    "prepare_repair",
    "project_phase",
    "repair_due",
    "repairs_done",
    "repairs_spent",
    "request_stop",
    "settled_record",
    "steering_message",
    "stop_requested",
]
