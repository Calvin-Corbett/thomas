"""The optional landing-slot requirement for the scoped commit tool. Stdlib only.

``--require-slot`` (or ``[landing_queue] require_slot = true`` in agent_safety.toml) makes the commit tool refuse to land
unless the caller holds the landing queue's slot right now: an open ticket of its own, in state ``holding``, with lease
left. It is off by default and changes nothing until someone turns it on.

This module does not depend on the queue. It asks a ``SlotSource`` one question. ``queue_source`` adapts the queue that
lives in scripts/crew/brief/landing_queue.py when that code is present, and raises ``QueueUnavailable`` when it is not,
in which case the flag refuses with that explanation instead of guessing. A caller (or a test) can hand any other source.

What it is not: protection. The queue is tamper-evident and advisory; a forged ticket passes this check. The flag makes
the commit tool cooperate with the queue, so that when only the holder moves the branch, the other landings stop racing it.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from scripts.crew.brief import git_reads

SESSION_ENV = ("THOMAS_AGENT_SESSION_ID", "AGENT_SESSION_ID")
HOW_TO_GET_ONE = (
    'python scripts/crew/brief/land.py --message "<message>"  (it takes a ticket, waits for its turn, and runs this '
    "tool inside the slot; `python scripts/crew/brief/land.py --status` shows who is in line)"
)


class QueueUnavailable(RuntimeError):
    """The landing queue is not installed in this checkout, so no slot can be held."""


@dataclass(frozen=True)
class SlotView:
    ticket: int
    state: str
    lease_left: float


class SlotSource(Protocol):
    def holding(self, *, agent: str, session: str) -> SlotView | None:
        """This identity's open ticket in state ``holding``, or None."""


def session_id(environ: dict[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    return next((str(env.get(key) or "").strip() for key in SESSION_ENV if str(env.get(key) or "").strip()), "")


_REQUIRE_TRUE = re.compile(r"^\s*require_slot\s*=\s*true\b", re.MULTILINE | re.IGNORECASE)


def _text_requires_slot(text: str) -> bool:
    """True when ``[landing_queue] require_slot = true`` is in this agent_safety.toml text.

    A file that does not parse is read line by line instead: a stray error elsewhere in it must not turn the requirement
    off. That can only make this stricter.
    """
    try:
        import tomllib

        section = tomllib.loads(text).get("landing_queue")
    except (ImportError, ValueError):
        return bool(_REQUIRE_TRUE.search(text))
    return isinstance(section, dict) and section.get("require_slot") is True


def configured_default(repo_root: Path) -> bool:
    """``[landing_queue] require_slot`` in agent_safety.toml, as committed OR as it stands in the working tree.

    Either one saying true makes the slot required, so an uncommitted edit to the file can turn the requirement on for one
    landing but never off. False when neither says so, and when the file is absent or unreadable.
    """
    texts: list[str] = []
    try:
        texts.append((Path(repo_root) / "agent_safety.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    try:
        committed = git_reads.cat_file_batch(repo_root, ["HEAD:agent_safety.toml"]).get("HEAD:agent_safety.toml")
    except (git_reads.GitReadError, OSError, subprocess.SubprocessError):
        committed = None
    if committed is not None:
        texts.append(committed.decode("utf-8", "replace"))
    return any(_text_requires_slot(text) for text in texts)


class _LaneSource:
    def __init__(self, lane_class: Callable[..., object], store: object):
        self._lane_class, self._store = lane_class, store

    def holding(self, *, agent: str, session: str) -> SlotView | None:
        lane = self._lane_class(self._store, agent=agent, session=session)
        for number, state in sorted(lane.states().items()):  # type: ignore[attr-defined]
            ticket = state["ticket"]
            owner = ticket.get("session") or ticket.get("agent")
            if state["open"] and state["state"] == "holding" and owner == lane.ident:  # type: ignore[attr-defined]
                return SlotView(number, "holding", float(lane.lease_left(number)))  # type: ignore[attr-defined]
        return None


def queue_source(repo_root: Path) -> SlotSource:
    try:
        from scripts.crew.brief.landing_queue import Lane
        from scripts.crew.brief.landing_store import FileTicketStore, resolve_queue_root
    except ImportError as exc:
        raise QueueUnavailable(f"the landing queue code is not in this checkout ({exc})") from exc
    return _LaneSource(Lane, FileTicketStore(resolve_queue_root(start=Path(repo_root))))


def check_slot(
    repo_root: Path,
    *,
    agent: str,
    session: str = "",
    source: Callable[[Path], SlotSource] | None = None,
) -> str | None:
    """None when the caller holds a live slot, else the refusal text (what is missing and how to get it)."""
    try:
        view = (source or queue_source)(Path(repo_root)).holding(agent=agent, session=session or session_id())
    except QueueUnavailable as exc:
        return f"slot required but unavailable: {exc}. Land without --require-slot, or install the queue first."
    except (
        OSError,
        ValueError,
        LookupError,
        TypeError,
        AttributeError,
        RuntimeError,
        ImportError,
        AssertionError,
        subprocess.SubprocessError,
    ) as exc:
        # a queue that cannot be read, for whatever reason it raised, must not read as "slot held" or as a crash
        return f"slot required but the landing queue could not be read ({type(exc).__name__}: {exc})."
    if view is None:
        return f"slot required: `{agent}` holds no landing slot (no open ticket in state `holding`). Get one with: {HOW_TO_GET_ONE}"
    if not view.lease_left > 0:  # also refuses NaN, which compares false both ways
        return f"slot required: ticket T{view.ticket:06d} has no lease left. Take a new one with: {HOW_TO_GET_ONE}"
    return None
