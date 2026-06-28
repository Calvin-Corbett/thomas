"""Dispatch router for deciding when background delegation should start.

This classifier is intentionally conservative. Thomas should stay in the
conversation unless the user is clearly asking for execution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

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

_META_RE = re.compile(
    r"^\s*(?:what (?:are|can) you|who are you|what do you do|"
    r"tell me about yourself|what'?s your name)\s*[!?.]*\s*$",
    re.I,
)

_STATUS_RE = re.compile(
    r"\b(?:status|progress|update|done yet|finished|still running|any news|"
    r"what'?s happening|where are we|how(?:'s| is) (?:that|it|this|the task|the project) going)\b",
    re.I,
)

_EXPLORATORY_RE = re.compile(
    r"(?:\blet'?s think(?: this)? through\b|\bbrainstorm\b|\bwhat do you think\b|"
    r"\bhow could\b|\bmaybe i should\b|\bshould i\b|\bcould we\b|\bcan we\b|"
    r"\bhelp me think\b|\btalk (?:me )?through\b|\bwalk me through\b|"
    r"\bfigure out how\b|\bi guess\b|\bi wonder\b)",
    re.I,
)

_MEMORY_DIRECTIVE_RE = re.compile(
    r"\b(?:remember|memorize|store this|save this|keep (?:this|that) in memory|"
    r"what (?:did|do) i (?:ask you to )?remember|recall)\b",
    re.I,
)

_DIRECT_RESPONSE_RE = re.compile(
    r"\b(?:reply|respond|say|answer)\s+(?:with\s+)?exactly\b|"
    r"\bexactly\s*:\s*\S+",
    re.I,
)

_QUESTION_PREFIX_RE = re.compile(r"^\s*(?:what|who|when|where|why|how)\b", re.I)

# An information-seeking question located anywhere in the message: a wh-word
# followed by a "?" within a bounded, newline-free gap. Catches conversational
# questions that do not START with the wh-word, e.g. "quick note - what is 8 x 7?".
# The bounded {0,120} gap (no "?"/newline) avoids polynomial backtracking.
_QUESTION_ANYWHERE_RE = re.compile(
    r"\b(?:what|whats|who|whom|whose|when|where|why|how|which)\b[^?\n]{0,120}\?",
    re.I,
)

_TOOL_OR_FILE_REQUEST_RE = re.compile(
    r"(?:\buse\s+(?:your\s+)?(?:file|files|tool|tools)\b|"
    # Bounded, non-newline gap (cap 80 chars, lazy) instead of `.*` to avoid
    # polynomial backtracking on adversarial input (py/polynomial-redos).
    r"\b(?:file|files|tool|tools)\b[^\n]{0,80}?\b(?:repo|repository|workspace|folder|directory|path)\b|"
    r"\btop[- ]level\s+files?\b|"
    r"\bcurrent\s+(?:repo|repository|workspace)\b|"
    r"\bname\s+\w*\s*three\s+top[- ]level\s+files?\b)",
    re.I,
)

_DIRECTIVE_PREFIX_RE = re.compile(
    r"^\s*(?:please\s+)?(?:can you|could you|would you|will you|i want you to|"
    r"you need to|please|go|do|implement|fix|build|create|write|update|debug|"
    r"review|research|investigate|analyze|inspect|find|search|run|deploy|make)\b",
    re.I,
)

_ACTION_VERB_RE = re.compile(
    r"\b(?:run|execute|edit|write|create|delete|remove|install|build|deploy|"
    r"fix|debug|test|search|find|read|make|change|update|modify|add|set|"
    r"implement|refactor|rename|replace|merge|revert|configure|setup|"
    r"check|scan|analyze|inspect|start|stop|restart|enable|disable|"
    r"download|upload|fetch|pull|push|sync|copy|convert|generate|"
    r"scaffold|migrate|optimize|clean|format|send|connect|open|"
    r"research|compare|investigate|plan|design|review|audit)\b",
    re.I,
)

_DELIVERABLE_RE = re.compile(
    r"\b(?:file|files|endpoint|api|route|component|bug|test|tests|plan|report|"
    r"doc|documentation|spec|project|task|ticket|issue|code|repo|repository)\b",
    re.I,
)

# Imperative intent: a request phrased as a command ("put a file on my desktop",
# "order more paper", "book a flight") is actionable even when it lacks one of the
# whitelisted deliverable nouns. This is the semantic upgrade over the verb+noun
# whitelist that misread natural requests as small talk — the casual/question guards
# above still win first, so only genuine commands reach here.
_TASK_LEAD_VERBS = frozenset(
    {
        "put",
        "get",
        "set",
        "make",
        "build",
        "create",
        "write",
        "draft",
        "compose",
        "send",
        "email",
        "message",
        "post",
        "schedule",
        "book",
        "order",
        "buy",
        "purchase",
        "reserve",
        "remind",
        "add",
        "remove",
        "delete",
        "clean",
        "clear",
        "organize",
        "organise",
        "sort",
        "rename",
        "move",
        "copy",
        "download",
        "upload",
        "install",
        "uninstall",
        "deploy",
        "run",
        "execute",
        "launch",
        "start",
        "stop",
        "find",
        "search",
        "look",
        "research",
        "summarize",
        "summarise",
        "translate",
        "convert",
        "generate",
        "fix",
        "debug",
        "update",
        "change",
        "turn",
        "throw",
        "pull",
        "fetch",
        "grab",
        "check",
        "review",
        "analyze",
        "analyse",
        "investigate",
        "plan",
        "design",
        "draw",
        "compile",
        "format",
        "refactor",
        "configure",
        "setup",
        "connect",
        "cancel",
        "print",
        "open",
        "play",
        "record",
        "scan",
        "calculate",
        "compute",
        "prepare",
        "gather",
        "fill",
        "back",
        "track",
    }
)
_IMPERATIVE_LEAD_RE = re.compile(
    r"^\s*(?:please\s+|kindly\s+|hey,?\s+|ok(?:ay)?,?\s+|so,?\s+|now,?\s+|"
    r"can you\s+|could you\s+|would you\s+|will you\s+|"
    r"i'?d?\s+(?:really\s+)?(?:need|want|like|love)\s+(?:you\s+)?(?:to\s+)?|"
    r"i need\s+(?:you\s+)?(?:to\s+)?|let'?s\s+|go\s+(?:ahead\s+and\s+)?)?"
    r"(?P<verb>[a-z']+)\b",
    re.I,
)
# "I need the report pulled together" / "want this done": a need/want + a
# completed-action participle is a task even when the leading word isn't a verb.
_NEED_DONE_RE = re.compile(
    r"\b(?:need|want|'?d like|gotta|have to|trying to)\b[^.\n]{0,80}?"
    r"\b(?:done|made|built|set ?up|created|pulled|sent|fixed|cleaned|organized|"
    r"organised|scheduled|booked|ordered|installed|deployed|written|drafted|"
    r"generated|updated|renamed|moved|copied|printed|downloaded)\b",
    re.I,
)


def _is_imperative_task(src: str) -> bool:
    m = _IMPERATIVE_LEAD_RE.match(src)
    if m and m.group("verb").lower() in _TASK_LEAD_VERBS:
        return True
    return bool(_NEED_DONE_RE.search(src))


_SHORT_MESSAGE_WORD_LIMIT = 4
_CASUAL_PATTERNS = [
    _GREETING_RE,
    _THANKS_RE,
    _FILLER_RE,
    _LIVENESS_RE,
    _HOW_ARE_YOU_RE,
    _META_RE,
]


@dataclass(frozen=True)
class DispatchDecision:
    action: str
    reason: str


def _has_active_tasks(active_tasks: list[dict[str, Any]] | None) -> bool:
    if not active_tasks:
        return False
    for item in active_tasks:
        state = str((item or {}).get("state") or "").strip().lower()
        if state and state not in {"completed", "failed", "abandoned"}:
            return True
    return False


def should_dispatch(
    text: str,
    *,
    recent_messages: list[dict[str, Any]] | None = None,
    active_tasks: list[dict[str, Any]] | None = None,
    mode: str = "",
) -> DispatchDecision:
    src = str(text or "").strip()
    if not src:
        return DispatchDecision(action="casual", reason="empty_message")

    for pattern in _CASUAL_PATTERNS:
        if pattern.match(src):
            return DispatchDecision(action="casual", reason=f"pattern:{pattern.pattern[:24]}")

    words = src.split()
    if len(words) <= _SHORT_MESSAGE_WORD_LIMIT and not _ACTION_VERB_RE.search(src) and not _is_imperative_task(src):
        return DispatchDecision(action="casual", reason="short_no_action_verb")

    if _has_active_tasks(active_tasks) and _STATUS_RE.search(src):
        return DispatchDecision(action="casual", reason="active_task_status_followup")

    if _EXPLORATORY_RE.search(src) and not _DIRECTIVE_PREFIX_RE.search(src):
        return DispatchDecision(action="casual", reason="exploratory_conversation")

    explicit_tool_or_file = bool(_TOOL_OR_FILE_REQUEST_RE.search(src))
    if not explicit_tool_or_file and _QUESTION_PREFIX_RE.search(src) and not _DIRECTIVE_PREFIX_RE.search(src):
        return DispatchDecision(action="casual", reason="question_prompt")

    # A question embedded mid-message (not just at the start) is still an
    # information request, not a task -- e.g. "quick note, what is 8 x 7?".
    # Guarded so genuine work still dispatches: skipped when there is an explicit
    # tool/file ask or a leading directive ("build me X, what stack?" starts with
    # a directive and routes to dispatch as before).
    if not explicit_tool_or_file and _QUESTION_ANYWHERE_RE.search(src) and not _DIRECTIVE_PREFIX_RE.search(src):
        return DispatchDecision(action="casual", reason="embedded_question")

    if not explicit_tool_or_file and _MEMORY_DIRECTIVE_RE.search(src):
        return DispatchDecision(action="casual", reason="memory_instruction")

    if not explicit_tool_or_file and _DIRECT_RESPONSE_RE.search(src):
        return DispatchDecision(action="casual", reason="direct_response_instruction")

    if explicit_tool_or_file:
        return DispatchDecision(action="dispatch", reason="explicit_tool_or_file_request")

    recent_assistant = ""
    if recent_messages:
        for msg in reversed(recent_messages):
            if str(msg.get("role") or "") == "assistant":
                recent_assistant = str(msg.get("content") or "")
                break
    if recent_assistant and _STATUS_RE.search(src) and "background work" in recent_assistant.lower():
        return DispatchDecision(action="casual", reason="delegation_status_followup")

    if _DIRECTIVE_PREFIX_RE.search(src) and (_ACTION_VERB_RE.search(src) or _DELIVERABLE_RE.search(src)):
        return DispatchDecision(action="dispatch", reason="explicit_execution_request")

    if _ACTION_VERB_RE.search(src) and _DELIVERABLE_RE.search(src):
        return DispatchDecision(action="dispatch", reason="action_verb_with_deliverable")

    # Natural-language command ("put a file…", "order more paper", "book a flight"):
    # actionable even without a whitelisted deliverable noun. Reached only after the
    # casual / question / exploratory / status guards above have declined, so genuine
    # conversation is not misrouted.
    if _is_imperative_task(src):
        return DispatchDecision(action="dispatch", reason="imperative_task")

    if mode == "max" and _ACTION_VERB_RE.search(src):
        return DispatchDecision(action="dispatch", reason="max_mode_actionable")

    return DispatchDecision(action="casual", reason="default_conversation")


def casual_route_decision() -> Any:
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
