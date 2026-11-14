"""Pause, direct messages and questions for one Build run, kept on disk between the server and its runner.

A Build run is a subprocess whose stdin closes once the start payload is read, so nothing the server learns after
launch could reach it: Steer stopped the run and started a new one, and a run could not be paused or asked anything.
This module is the channel. The server hands the runner one folder per run (``THOMAS_RUN_CONTROL_DIR``) and both
sides read and write small files in it:

    paused                        present while you have the run paused
    inbox/<agent>/<message>.json  a message for that agent, not read yet
    inbox/<agent>/done/<...>.json the same message once the agent read it (moved with ``os.replace``, so read once)
    listening/<agent>.json        present while that agent's loop runs and reads its inbox
    questions/<question>.json     a question the lead asked you with ``ask.user``
    answers/<question>.json       your answer to it

The server half is the plain functions (``set_paused``, ``queue_message``, ``snapshot``, ``submit_answer``); the
runner half is :class:`RunControl`, which gives each agent loop its hold (``run_hold``), its inbox (a queue whose
``get_nowait`` takes every waiting message) and the lead's question/answer wait. A run launched without the folder
(an older server, the CLI, a test) gets ``None`` from :meth:`RunControl.from_env` and runs exactly as before.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import queue
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

CONTROL_DIR_ENV = "THOMAS_RUN_CONTROL_DIR"
LEAD = "lead"
HOLD_POLL_S = 0.5
MAX_MESSAGE_CHARS = 8000
ASK_WAIT_S = 20 * 60
# The leads that run inside the runner process, so they can hold, read an inbox and ask. The Claude Code lead is one
# `claude -p` process Thomas cannot hold or speak into once it has started.
_HOLDING_AGENTS = frozenset({"thomas"})
NO_CONTROLS = {"pause": False, "message": False, "ask": False}
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_DRAIN_ENV = "THOMAS_CODE_RELOAD_DRAIN_SIGNAL"


def now_ms() -> int:
    return int(time.time() * 1000)


def valid_id(value: Any) -> bool:
    """A run, agent or question id that is safe as one path segment."""
    return isinstance(value, str) and bool(_ID.fullmatch(value))


def controls_for_agent(agent: Any) -> dict[str, bool]:
    """What the UI may offer for a run led by ``agent``: pause, direct messages, and questions to you."""
    able = str(agent or "").strip() in _HOLDING_AGENTS
    return {"pause": able, "message": able, "ask": able}


def configured() -> bool:
    """True when this process was launched with a control folder (read before :meth:`RunControl.from_env` claims it)."""
    return bool(str(os.environ.get(CONTROL_DIR_ENV) or "").strip())


def control_dir(catalog_root: str | Path, run_id: str) -> Path:
    """The run's folder, beside the Build transcripts (``.thomas/evolve/agent``) so it never shows in git status."""
    if not valid_id(run_id):
        raise ValueError("invalid run id")
    return Path(catalog_root) / ".thomas" / "evolve" / "agent" / "run_control" / run_id


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write whole or not at all: a reader in the other process never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    _replace(tmp, path)


def _replace(source: Path, target: Path) -> None:
    # Windows refuses a replace while the other process has the target open for its brief read; that clears in
    # milliseconds, so a few short retries cover it.
    for attempt in range(5):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.02)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _json_files(folder: Path) -> list[Path]:
    try:
        return sorted(p for p in folder.iterdir() if p.suffix == ".json" and not p.name.startswith(".") and p.is_file())
    except OSError:
        return []


# ── the server's half ──


def is_paused(directory: Path) -> bool:
    return (Path(directory) / "paused").is_file()


def set_paused(directory: Path, paused: bool) -> None:
    flag = Path(directory) / "paused"
    if paused:
        _write_json(flag, {"at": now_ms()})
    else:
        flag.unlink(missing_ok=True)


def listening_agents(directory: Path) -> list[str]:
    """The agents whose loops are running and reading their inbox right now."""
    return [path.stem for path in _json_files(Path(directory) / "listening") if valid_id(path.stem)]


def queue_message(directory: Path, agent_id: str, text: str) -> dict[str, Any]:
    """Leave a message in ``agent_id``'s inbox and return its receipt (state ``queued``)."""
    if not valid_id(agent_id):
        raise ValueError("invalid agent id")
    message = {"id": f"m-{secrets.token_hex(6)}", "agent_id": agent_id, "text": text, "queued_at": now_ms()}
    _write_json(Path(directory) / "inbox" / agent_id / f"{message['queued_at']:013d}-{message['id']}.json", message)
    return _receipt(message, "queued")


def _receipt(message: dict[str, Any], state: str, acked_at: int | None = None) -> dict[str, Any]:
    return {
        "id": str(message.get("id") or ""),
        "agent_id": str(message.get("agent_id") or ""),
        "text": str(message.get("text") or ""),
        "state": state,
        "queued_at": int(message.get("queued_at") or 0),
        "acked_at": acked_at,
    }


def message_receipts(directory: Path, *, running: bool) -> list[dict[str, Any]]:
    """Every message sent to this run: acked once read, queued while waiting, undelivered once the run ended unread."""
    rows: list[dict[str, Any]] = []
    inbox = Path(directory) / "inbox"
    try:
        boxes = [box for box in inbox.iterdir() if box.is_dir() and valid_id(box.name)]
    except OSError:
        boxes = []
    for box in boxes:
        for path in _json_files(box):
            message = _read_json(path)
            if message is not None:
                rows.append(_receipt(message, "queued" if running else "undelivered"))
        for path in _json_files(box / "done"):
            message = _read_json(path)
            if message is None:
                continue
            acked_at = message.get("acked_at")
            if not isinstance(acked_at, int):
                try:
                    acked_at = int(path.stat().st_mtime * 1000)
                except OSError:
                    acked_at = None
            rows.append(_receipt(message, "acked", acked_at))
    return sorted(rows, key=lambda row: (row["queued_at"], row["id"]))


def question_rows(directory: Path, *, running: bool) -> list[dict[str, Any]]:
    """Every question the lead asked: open, answered, or expired (no answer before it gave up or the run ended)."""
    rows: list[dict[str, Any]] = []
    for path in _json_files(Path(directory) / "questions"):
        question = _read_json(path)
        if question is None:
            continue
        state = str(question.get("state") or "open")
        answer = question.get("answer")
        if state == "open":
            given = _read_json(Path(directory) / "answers" / path.name)
            if given is not None:
                state, answer = "answered", str(given.get("answer") or "")
            elif not running:
                state = "expired"
        rows.append(
            {
                "question_id": str(question.get("question_id") or path.stem),
                "question": str(question.get("question") or ""),
                "options": question.get("options") if isinstance(question.get("options"), list) else [],
                "allow_free_text": bool(question.get("allow_free_text")),
                "asked_at": int(question.get("asked_at") or 0),
                "state": state if state in {"open", "answered", "expired"} else "expired",
                "answer": answer if isinstance(answer, str) else None,
            }
        )
    return sorted(rows, key=lambda row: row["asked_at"])


def snapshot(directory: Path, *, running: bool) -> dict[str, Any]:
    """What ``GET /messages`` answers, read in one pass off the event loop."""
    return {
        "paused": running and is_paused(directory),
        "listening": listening_agents(directory) if running else [],
        "messages": message_receipts(directory, running=running),
        "questions": question_rows(directory, running=running),
        "context": __getattr__("read_context")(directory),
    }


def submit_answer(directory: Path, question_id: str, answer: str, *, running: bool) -> str:
    """Record your answer: ``"ok"``, ``"not_found"``, or ``"not_open"`` (answered, expired, or the run ended)."""
    if not valid_id(question_id):
        return "not_found"
    question = _read_json(Path(directory) / "questions" / f"{question_id}.json")
    if question is None:
        return "not_found"
    answer_path = Path(directory) / "answers" / f"{question_id}.json"
    if not running or question.get("state", "open") != "open" or answer_path.exists():
        return "not_open"
    _write_json(answer_path, {"answer": answer, "answered_at": now_ms()})
    return "ok"


# ── the runner's half ──


def _duration(ms: int) -> str:
    seconds = max(0, int(round(ms / 1000)))
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60}s" if seconds % 60 else f"{seconds // 60} minutes"


class PassClock:
    """The lead pass's wall clock, stopped while the run is held: paused by you, or waiting for your answer.

    ``_translate_agent_stream`` binds the pass's ``asyncio.timeout`` here. A hold takes the remaining time off the
    timeout and puts it back on release, so a pause never spends the pass's budget; the shifts registered with
    :meth:`add_shift` move the absolute deadlines later helpers and team calls read by the same amount, and work
    already waiting re-reads a :class:`HeldDeadline`, which counts :meth:`held_seconds` as it goes.
    """

    def __init__(self) -> None:
        self._timeout: Any = None
        self._shifts: list[Callable[[float], None]] = []
        self._holds = 0
        self._since = 0.0
        self._remaining: float | None = None
        self._held_total = 0.0

    @property
    def held(self) -> bool:
        return self._holds > 0

    def held_seconds(self, *, current: bool = True) -> float:
        """Every second this pass has been held so far: the finished holds (what the shifts have moved deadlines
        by), plus the hold still going unless ``current`` is false."""
        going = max(0.0, time.monotonic() - self._since) if self._holds and current else 0.0
        return self._held_total + going

    def bind(self, timeout: Any) -> None:
        self._timeout, self._remaining = timeout, None
        if self._holds:
            self._stop()

    def unbind(self) -> None:
        self._timeout, self._remaining = None, None

    def add_shift(self, shift: Callable[[float], None]) -> None:
        self._shifts.append(shift)

    def hold(self) -> None:
        self._holds += 1
        if self._holds == 1:
            self._since = time.monotonic()
            self._stop()

    def release(self) -> None:
        if not self._holds:
            return
        self._holds -= 1
        if self._holds:
            return
        held_s = max(0.0, time.monotonic() - self._since)
        self._held_total += held_s
        self._start()
        for shift in list(self._shifts):
            shift(held_s)

    def _stop(self) -> None:
        timeout = self._timeout
        if timeout is None:
            return
        try:
            when = timeout.when()
            if when is None:
                return
            self._remaining = max(0.0, when - asyncio.get_running_loop().time())
            timeout.reschedule(None)
        except RuntimeError:  # already expired or exited: nothing left to stop
            self._remaining = None

    def _start(self) -> None:
        timeout, remaining = self._timeout, self._remaining
        self._remaining = None
        if timeout is None or remaining is None:
            return
        try:
            timeout.reschedule(asyncio.get_running_loop().time() + remaining)
        except RuntimeError:
            pass


class HeldDeadline:
    """An absolute event-loop deadline for work already in flight, which a hold gives back while it runs.

    The shifts a :class:`PassClock` applies on release move the deadlines later calls read; a helper or a team call
    that is already waiting holds its own. ``when`` is a deadline as those shifts keep it (moved by every finished
    hold), and calling this gives it now: ``when`` plus every second held since then, the hold still going
    included. A wait that re-reads it never runs out while the run is held (it wakes at most every ``HOLD_POLL_S``
    meanwhile) and keeps exactly the time it had once the run resumes. Without a clock (a run without controls) it
    is the fixed deadline it was given.
    """

    def __init__(self, when: float, clock: PassClock | None = None) -> None:
        self._when = float(when)
        self._clock = clock
        self._held_at = clock.held_seconds(current=False) if clock is not None else 0.0

    def __call__(self) -> float:
        clock = self._clock
        if clock is None:
            return self._when
        when = self._when + clock.held_seconds() - self._held_at
        return max(when, asyncio.get_running_loop().time() + HOLD_POLL_S) if clock.held else when

    async def bound(self, awaitable: Awaitable[Any]) -> Any:
        """``asyncio.wait_for`` against this deadline, re-read each time the wait ends; it cancels and joins the
        awaitable and raises ``asyncio.TimeoutError`` once the deadline has passed."""
        task = asyncio.ensure_future(awaitable)
        try:
            while not task.done():
                remaining = self() - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError
                await asyncio.wait({task}, timeout=remaining)
            return task.result()
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


# The pass clock of the Build pass running in this context, for the waits that reach it only through code that
# passes deadlines as plain numbers (the team scheduler's ``run_owned_builders``). Unset outside a Build pass.
_PASS_CLOCK: ContextVar[PassClock | None] = ContextVar("thomas_build_pass_clock", default=None)


def bind_pass_clock(clock: PassClock | None) -> Token[PassClock | None]:
    """Make ``clock`` the running pass's clock for every task this context starts; reset with the returned token."""
    return _PASS_CLOCK.set(clock)


def unbind_pass_clock(token: Token[PassClock | None]) -> None:
    _PASS_CLOCK.reset(token)


def held_deadline(when: float) -> HeldDeadline:
    """``when`` as a :class:`HeldDeadline` on the running pass's clock: fixed outside a Build pass with controls."""
    return HeldDeadline(when, _PASS_CLOCK.get())


class AgentInbox:
    """One agent's messages from you, read the way the agent loop reads its steering queue.

    ``get_nowait`` takes EVERY waiting message, marks each read, writes a ``steering`` event for each (the moment
    the UI shows as acked), and returns them as one turn; nothing waiting raises ``queue.Empty``.
    """

    def __init__(self, control: RunControl, agent_id: str, *, title: str = "") -> None:
        self._control = control
        self.agent_id = agent_id
        self._title = title

    def get_nowait(self) -> str:
        taken = self._control.take_messages(self.agent_id)
        if not taken:
            raise queue.Empty
        tags = {} if self.agent_id == LEAD else {"agent_id": self.agent_id, "agent_title": self._title}
        for message in taken:
            self._control.emit({"fc": "steering", "text": message["text"], "steer_id": message["id"], **tags})
        text = "\n\n".join(str(message["text"]).strip() for message in taken)
        # The loop reads a bare "stop" as its own end-the-run sentinel, which would end the run unrecorded; the Stop
        # button ends a run properly, so typed here it stays your words.
        return text + "." if text.strip().lower() == "stop" else text


class RunControl:
    """The runner's side of one run's control folder (see the module docstring)."""

    def __init__(self, directory: Path, *, emit: Callable[[dict[str, Any]], None]) -> None:
        self.directory = Path(directory)
        self._emit = emit
        self.clock = PassClock()
        self._holders = 0
        self._paused_since: int | None = None
        self._drain_signal = str(os.environ.get(_DRAIN_ENV) or "")

    @classmethod
    def from_env(cls, emit: Callable[[dict[str, Any]], None]) -> RunControl | None:
        """Claim the folder the server named, or ``None`` for a run launched without one.

        The variable is removed from this process's environment once read, so the commands a run starts (its tests,
        a shell, another Thomas under test) never inherit the run's controls.
        """
        raw = str(os.environ.pop(CONTROL_DIR_ENV, "") or "").strip()
        if not raw:
            return None
        directory = Path(raw)
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            log.warning("run control folder %s could not be created; this run has no pause or messages", raw)
            return None
        return cls(directory, emit=emit)

    def emit(self, event: dict[str, Any]) -> None:
        self._emit(event)

    def new_pass_clock(self) -> PassClock:
        """A fresh clock for the next pass: each pass has its own timeout and its own deadlines.

        A pause still open from the last pass (its holder was cancelled while you had the run paused) holds the new
        clock from its start, so its release in :meth:`_end_pause` is matched."""
        self.clock = PassClock()
        if self._paused_since is not None:
            self.clock.hold()
        return self.clock

    def paused(self) -> bool:
        return is_paused(self.directory)

    def _draining(self) -> bool:
        return bool(self._drain_signal) and os.path.isfile(self._drain_signal)

    async def hold(self, iteration: int = 0) -> None:
        """Wait here while you have the run paused. Every Build agent loop calls it before each model call and after
        each tool, so a pause takes effect at the next step boundary. A landed-code reload releases it, so the run can
        yield for the restart.

        Only the flag going away (or the reload) ends a pause. A holder cancelled while you still have the run paused
        (a sibling tool cancelled, a team stopped) leaves it open: the clock stays stopped and no ``resumed`` is
        written until you resume, which the next agent to reach a step boundary then reports."""
        if not self.paused():
            if self._paused_since is not None and not self._holders:
                self._end_pause()  # the pause a cancelled holder left open ended while nothing held
            return
        self._holders += 1
        try:
            while self.paused() and not self._draining():
                self._begin_pause()
                await asyncio.sleep(HOLD_POLL_S)
        finally:
            self._holders -= 1
            if not self.paused() or self._draining():
                self._end_pause()

    def _begin_pause(self) -> None:
        if self._paused_since is not None:
            return
        self._paused_since = now_ms()
        self.clock.hold()
        self.emit({"fc": "paused", "text": "Paused. Each agent holds after its current step."})

    def _end_pause(self) -> None:
        if self._paused_since is None:
            return
        paused_ms = max(0, now_ms() - self._paused_since)
        self._paused_since = None
        self.clock.release()
        if self._draining():
            text = "Released for Thomas's restart; the run continues after it."
        else:
            text = f"Resumed after {_duration(paused_ms)}."
        self.emit({"fc": "resumed", "text": text, "paused_ms": paused_ms})

    def inbox(self, agent_id: str, *, title: str = "") -> AgentInbox:
        return AgentInbox(self, agent_id, title=title)

    def take_messages(self, agent_id: str) -> list[dict[str, Any]]:
        """Move every waiting message for ``agent_id`` to its done folder and return them, oldest first."""
        if not valid_id(agent_id):
            return []
        box = self.directory / "inbox" / agent_id
        taken: list[dict[str, Any]] = []
        for path in _json_files(box):
            done = box / "done" / path.name
            try:
                done.parent.mkdir(parents=True, exist_ok=True)
                os.replace(path, done)
            except OSError:
                continue  # still being written, or another reader took it
            message = _read_json(done)
            if message is None or not str(message.get("text") or "").strip():
                continue
            message["acked_at"] = now_ms()
            try:
                _write_json(done, message)
            except OSError:
                pass  # read and acted on; the receipt falls back to the file's time
            taken.append(message)
        return taken

    def taken_texts(self, agent_id: str) -> list[str]:
        """Every message ``agent_id`` has read in this run, oldest first, read back from its done folder.

        A pass starts from an empty conversation, so what the lead read in an earlier pass is gone from it; the next
        pass's prompt carries these instead, and a message stays in force for the rest of the run."""
        if not valid_id(agent_id):
            return []
        # Named "<queued_at>-<id>.json" by queue_message, so the sorted listing is the order you sent them in.
        rows = [_read_json(path) for path in _json_files(self.directory / "inbox" / agent_id / "done")]
        return [text for text in (str((row or {}).get("text") or "").strip() for row in rows) if text]

    def listen(self, agent_id: str, title: str = "") -> None:
        """Say ``agent_id`` is reading its inbox: from now until :meth:`stop_listening`, messages to it are accepted."""
        try:
            _write_json(self.directory / "listening" / f"{agent_id}.json", {"title": title, "since": now_ms()})
        except OSError:
            log.warning("could not mark %s as listening", agent_id, exc_info=True)

    def stop_listening(self, agent_id: str) -> None:
        try:
            (self.directory / "listening" / f"{agent_id}.json").unlink(missing_ok=True)
        except OSError:
            log.warning("could not clear %s's listening marker", agent_id, exc_info=True)

    async def ask(
        self,
        question: str,
        options: list[dict[str, Any]],
        *,
        allow_free_text: bool,
        default: str = "",
        wait_s: float = ASK_WAIT_S,
    ) -> tuple[str, str | None]:
        """Put a question to you and wait for the answer: ``(question_id, answer)``, answer ``None`` on no answer.

        The wait is held time, not working time: the pass clock stops while it lasts.
        """
        question_id = f"q-{secrets.token_hex(6)}"
        record = {
            "question_id": question_id,
            "question": question,
            "options": options,
            "allow_free_text": allow_free_text,
            "asked_at": now_ms(),
            "state": "open",
            "answer": None,
        }
        path = self.directory / "questions" / f"{question_id}.json"
        _write_json(path, record)
        self.emit(
            {
                "fc": "ask",
                "text": question,
                "question_id": question_id,
                "question": question,
                "options": options,
                "allow_free_text": allow_free_text,
            }
        )
        answer: str | None = None
        deadline = time.monotonic() + max(0.0, float(wait_s))
        self.clock.hold()
        try:
            while True:
                given = _read_json(self.directory / "answers" / f"{question_id}.json")
                if given is not None:
                    answer = str(given.get("answer") or "")
                    break
                if time.monotonic() >= deadline or self._draining():
                    break
                await asyncio.sleep(HOLD_POLL_S)
        finally:
            self.clock.release()
        record.update(state="answered" if answer is not None else "expired", answer=answer, closed_at=now_ms())
        try:
            _write_json(path, record)
        except OSError:
            log.warning("could not close question %s", question_id, exc_info=True)
        if answer is not None:
            self.emit({"fc": "answered", "text": answer, "question_id": question_id, "answer": answer})
        else:
            waited = "Thomas is restarting" if self._draining() else f"No answer in {_duration(int(wait_s * 1000))}"
            self.emit(
                {
                    "fc": "answered",
                    "text": f"{waited}; going with {default}, the recommended option." if default else f"{waited}.",
                    "question_id": question_id,
                    "answer": default,
                }
            )
        return question_id, answer


__all__ = [
    "ASK_WAIT_S",
    "CONTROL_DIR_ENV",
    "LEAD",
    "MAX_MESSAGE_CHARS",
    "NO_CONTROLS",
    "AgentInbox",
    "HeldDeadline",
    "PassClock",
    "RunControl",
    "bind_pass_clock",
    "configured",
    "control_dir",
    "controls_for_agent",
    "held_deadline",
    "is_paused",
    "listening_agents",
    "message_receipts",
    "now_ms",
    "queue_message",
    "question_rows",
    "set_paused",
    "snapshot",
    "submit_answer",
    "unbind_pass_clock",
    "valid_id",
]


def __getattr__(name: str) -> Any:
    """The context, usage, speed and compaction helpers live in :mod:`run_metrics`; they stay reachable here.

    Imported when first asked for, because run_metrics itself needs this module's file helpers."""
    from thomas.forge.anvil import run_metrics

    try:
        return getattr(run_metrics, name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
