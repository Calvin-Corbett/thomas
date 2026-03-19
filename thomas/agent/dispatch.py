"""Dispatch router: decides whether Thomas replies directly or dispatches to task manager.

THIS IS THE FRONT DOOR FOR ALL CHAT MESSAGES.

Two outcomes:
  - CASUAL: Thomas replies directly with personality, no tools, fast.
    Examples: "hey", "thanks", "lol", "what's up", "good morning"
  - ACTIONABLE: Thomas acknowledges instantly, dispatches to the workboard
    task manager pipeline. The task manager breaks it down, assigns workers.
    Examples: "fix the login bug", "create a new endpoint", "research X"

The old IntentRouter had 8 paths with confidence scoring. This replaces it
with a simple binary decision. The task manager handles all the nuance after
dispatch.

Architecture context for AI agents:
  - This module is called from the /api/chat route (chat_aiohttp_part02.py)
  - Casual → fast LLM call with Thomas personality (chat_modes.py)
  - Actionable → chat_dispatcher.py → WORKBOARD.md → workers
  - See docs/CHAT_EXECUTION_MODEL.md for the full picture
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# ── Casual detection patterns ─────────────────────────────────────────────
# These are SHORT, LOW-INTENT messages where Thomas should just reply directly.
# Anything that doesn't match these patterns gets dispatched.

_GREETING_RE = re.compile(
    r"^\s*(?:hi|hello|hey|yo|sup|what'?s up|wassup|howdy|hola|good\s+"
    r"(?:morning|afternoon|evening|night)|gm|gn)\s*[!?.]*\s*$",
    re.I,
)

_THANKS_RE = re.compile(
    r"^\s*(?:thanks?(?:\s+you)?|thx|ty|cheers|appreciated?|"
    r"(?:that'?s\s+)?(?:great|awesome|perfect|cool|nice|dope))\s*[!?.]*\s*$",
    re.I,
)

_FILLER_RE = re.compile(
    r"^\s*(?:ok(?:ay)?|sure|got it|understood|sounds good|bet|word|yep|yup|"
    r"nope|nah|yeah|yes|no|lol|lmao|haha|heh|hmm|ah|oh|wow|damn|"
    r"nice|cool|dope|sick|fire|lit)\s*[!?.]*\s*$",
    re.I,
)

_LIVENESS_RE = re.compile(
    r"^\s*(?:are you (?:there|working|alive|awake)|you there|still there|" r"ping|status|hello\??)\s*[!?.]*\s*$",
    re.I,
)

_HOW_ARE_YOU_RE = re.compile(
    r"^\s*(?:how(?:'re| are) you|how(?:'s| is) it going|what'?s good|"
    r"how'?s your day|how'?s everything)\s*[!?.]*\s*$",
    re.I,
)

# Meta-about-Thomas questions that he should answer directly
_META_RE = re.compile(
    r"^\s*(?:what (?:are|can) you|who are you|what do you do|"
    r"tell me about yourself|what'?s your name)\s*[!?.]*\s*$",
    re.I,
)

_CASUAL_PATTERNS = [
    _GREETING_RE,
    _THANKS_RE,
    _FILLER_RE,
    _LIVENESS_RE,
    _HOW_ARE_YOU_RE,
    _META_RE,
]

# Messages under this token count that match no action verbs are likely casual
_SHORT_MESSAGE_WORD_LIMIT = 4

# Action verbs that signal "this is a task, not small talk"
_ACTION_VERB_RE = re.compile(
    r"\b(?:run|execute|edit|write|create|delete|remove|install|build|deploy|"
    r"fix|debug|test|search|find|read|make|change|update|modify|add|set|"
    r"implement|refactor|rename|replace|merge|revert|configure|setup|"
    r"check|scan|analyze|inspect|start|stop|restart|enable|disable|"
    r"download|upload|fetch|pull|push|sync|copy|convert|generate|"
    r"scaffold|migrate|optimize|clean|format|send|connect|open|"
    r"research|compare|investigate|plan|design|review|audit|help me)\b",
    re.I,
)


@dataclass(frozen=True)
class DispatchDecision:
    """Result of the dispatch router.

    Attributes:
        action: Either "casual" or "dispatch"
        reason: Short explanation of why this decision was made (for logging)
    """

    action: str  # "casual" or "dispatch"
    reason: str


def should_dispatch(text: str) -> DispatchDecision:
    """Decide whether a user message should be dispatched to the task manager.

    Returns DispatchDecision with action="casual" or action="dispatch".

    This is intentionally simple. When in doubt, dispatch. The task manager
    can always decide a task is trivial and handle it quickly. But if Thomas
    tries to handle a real task inline, the user gets a slow, blocking experience.
    """
    src = str(text or "").strip()

    # Empty messages are casual
    if not src:
        return DispatchDecision(action="casual", reason="empty_message")

    # Check explicit casual patterns
    for pattern in _CASUAL_PATTERNS:
        if pattern.match(src):
            return DispatchDecision(action="casual", reason=f"pattern:{pattern.pattern[:30]}")

    # Very short messages without action verbs are probably casual
    words = src.split()
    if len(words) <= _SHORT_MESSAGE_WORD_LIMIT and not _ACTION_VERB_RE.search(src):
        return DispatchDecision(action="casual", reason="short_no_action_verb")

    # Everything else gets dispatched
    return DispatchDecision(action="dispatch", reason="actionable_content")


# ── Compatibility shim ────────────────────────────────────────────────────
# The old routing.py RouteDecision is still referenced by loop_core.py and
# other modules. We keep a minimal version here so imports don't break during
# the transition. The full IntentRouter is in routing.py (deprecated but not
# deleted yet).


def casual_route_decision() -> Any:
    """Return a RouteDecision-compatible object for casual chat.

    Used by the fast-reply path so existing code that expects a RouteDecision
    still works (memory policy, token budgets, etc).
    """
    from thomas.agent.routing import RouteDecision

    return RouteDecision(
        path="casual_chat",
        confidence=0.95,
        reasons=["dispatch_casual"],
        mode="auto",
        tools_policy="none",
        include_purpose=False,
        memory_include_global=True,
        memory_include_profile=True,
        memory_budget_tokens=600,
        is_followup=False,
    )


def actionable_route_decision() -> Any:
    """Return a RouteDecision-compatible object for dispatched tasks.

    Used by the dispatch path so logging/telemetry still gets a route object.
    """
    from thomas.agent.routing import RouteDecision

    return RouteDecision(
        path="dispatched",
        confidence=0.95,
        reasons=["dispatch_actionable"],
        mode="auto",
        tools_policy="auto",
        include_purpose=False,
        memory_include_global=True,
        memory_include_profile=True,
        memory_budget_tokens=800,
        is_followup=False,
    )
