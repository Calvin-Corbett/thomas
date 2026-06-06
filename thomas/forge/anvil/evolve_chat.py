"""Conversational control for the evolve loop -- "deep chat".

Turns a plain-language message ("focus on hardening this week, but ask me before
promoting") into a structured loop action (start / status / pause / approve /
reject) plus a conversational reply. Deterministic and cheap (no model call), so
it is fully unit tested; an organic model-driven interpreter can replace
``interpret_evolve_message`` later without touching the callers.

The interpreter has NO side effects -- it only decides *what* the user wants.
The server route performs the action using its existing machinery (spawn the
loop, read state, write the pause flag, shell out approve/reject).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .evolve_planner import FOCUS_ALIASES, normalize_focus

# Loop actions a chat message can map to.
ACTION_START = "start"
ACTION_STATUS = "status"
ACTION_PAUSE = "pause"
ACTION_APPROVE = "approve"
ACTION_REJECT = "reject"
ACTION_HELP = "help"

_STATUS_HINTS = (
    "status",
    "what are you",
    "what's happening",
    "whats happening",
    "how's it going",
    "hows it going",
    "working on",
    "progress",
    "what did you",
    "show me",
    "where are you",
)
_PAUSE_HINTS = ("stop", "pause", "halt", "hold on", "wait", "stand down", "freeze")
_APPROVE_HINTS = ("approve", "accept", "ship it", "promote it", "looks good", "lgtm")
_REJECT_HINTS = ("reject", "dismiss", "discard", "skip that", "drop that", "throw away", "no thanks")
_START_HINTS = (
    "evolve",
    "improve",
    "work on",
    "start",
    "go ahead and",
    "make yourself",
    "self-improve",
    "self improve",
    "harden",
    "refactor",
    "clean up",
    "optimize",
    "fix up",
)

# Posture cues.
_PROPOSE_HINTS = ("ask me", "ask first", "let me approve", "review", "careful", "cautious", "propose", "don't promote")
_AUTONOMOUS_HINTS = ("go wild", "full send", "autonomous", "don't ask", "dont ask", "yolo", "let it rip", "full auto")

_HOLD_ID_RE = re.compile(r"\bhold-[0-9a-f]{4,}\b", re.IGNORECASE)


@dataclass
class EvolveChatIntent:
    action: str
    focus: str = ""
    posture: str = ""
    approval_ref: str = ""  # "first" | "all" | a hold-id | ""
    reply: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "focus": self.focus,
            "posture": self.posture,
            "approval_ref": self.approval_ref,
            "reply": self.reply,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> EvolveChatIntent:
        payload = dict(payload or {})
        return cls(
            action=str(payload.get("action") or ACTION_HELP),
            focus=str(payload.get("focus") or ""),
            posture=str(payload.get("posture") or ""),
            approval_ref=str(payload.get("approval_ref") or ""),
            reply=str(payload.get("reply") or ""),
        )


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _extract_focus(text: str) -> str:
    """Pick the strongest category cue in the message."""
    direct = normalize_focus(text)
    if direct:
        return direct
    # Longest alias match wins (so "performance" beats a stray "test").
    for alias in sorted(FOCUS_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", text):
            return FOCUS_ALIASES[alias]
    return ""


def _extract_posture(text: str) -> str:
    if _contains_any(text, _AUTONOMOUS_HINTS):
        return "autonomous"
    if _contains_any(text, _PROPOSE_HINTS):
        return "propose"
    return ""  # let the caller default (auto_safe)


def _extract_approval_ref(text: str) -> str:
    match = _HOLD_ID_RE.search(text)
    if match:
        return match.group(0).lower()
    if _contains_any(text, ("all", "everything", "every", "both")):
        return "all"
    if _contains_any(text, ("first", "top", "that one", "it", "the security", "the one")):
        return "first"
    return "first"


def _start_reply(focus: str, posture: str) -> str:
    focus_clause = f" with a focus on {focus}" if focus else " on the highest-leverage work"
    posture_word = posture or "auto_safe"
    posture_clause = {
        "propose": " I won't touch live Thomas -- I'll queue every change for your approval.",
        "autonomous": " I'll promote anything that passes the tests, no check-ins.",
        "auto_safe": " I'll auto-apply the safe wins and hold anything risky for your approval.",
    }.get(posture_word, "")
    return f"On it -- evolving Thomas{focus_clause}.{posture_clause} Watch progress below; I'll report back here."


def interpret_evolve_message(message: str) -> EvolveChatIntent:
    """Map a plain-language message to a loop action + conversational reply."""
    text = str(message or "").strip().lower()
    if not text:
        return EvolveChatIntent(action=ACTION_HELP, reply=_help_reply())

    # Order matters: pause/approve/reject/status are checked before start so a
    # message like "stop evolving" reads as pause, not start.
    if _contains_any(text, _PAUSE_HINTS):
        return EvolveChatIntent(action=ACTION_PAUSE, reply="Pausing after the current step finishes.")

    if _contains_any(text, _REJECT_HINTS):
        ref = _extract_approval_ref(text)
        return EvolveChatIntent(action=ACTION_REJECT, approval_ref=ref, reply="Dismissed -- I won't promote that one.")

    if _contains_any(text, _APPROVE_HINTS):
        ref = _extract_approval_ref(text)
        return EvolveChatIntent(
            action=ACTION_APPROVE,
            approval_ref=ref,
            reply="Approving -- I'll re-derive that change and promote it.",
        )

    if _contains_any(text, _STATUS_HINTS):
        return EvolveChatIntent(action=ACTION_STATUS, reply="Here's where things stand:")

    if _contains_any(text, _START_HINTS) or _extract_focus(text):
        focus = _extract_focus(text)
        posture = _extract_posture(text)
        return EvolveChatIntent(
            action=ACTION_START,
            focus=focus,
            posture=posture,
            reply=_start_reply(focus, posture),
        )

    return EvolveChatIntent(action=ACTION_HELP, reply=_help_reply())


def _help_reply() -> str:
    return (
        "Tell me what to evolve and how careful to be. Try: "
        '"focus on hardening, but ask me before promoting", '
        '"refactor the big files", "what are you working on?", '
        '"approve that", or "stop".'
    )


def resolve_approval_ids(state: dict[str, Any], ref: str) -> list[str]:
    """Resolve a chat approval reference to concrete pending approval id(s)."""
    pending = [p for p in (state.get("pending_approvals") or []) if p.get("status") == "pending"]
    if not pending:
        return []
    ref = str(ref or "first").lower()
    if ref.startswith("hold-"):
        return [p["id"] for p in pending if str(p.get("id")).lower() == ref]
    if ref == "all":
        return [p["id"] for p in pending]
    return [pending[0]["id"]]


def status_summary(state: dict[str, Any]) -> str:
    """One-line conversational status line built from a loop-state dict."""
    counters = state.get("counters") or {}
    status = state.get("status") or "idle"
    pending = state.get("pending_count") or 0
    parts = [
        f"loop is {status}",
        f"{int(counters.get('promoted', 0))} change(s) promoted",
        f"{int(pending)} awaiting your approval",
    ]
    current = state.get("current")
    if isinstance(current, dict) and current.get("title"):
        parts.append(f"currently working on: {current.get('title')}")
    return " -- ".join(parts) + "."
