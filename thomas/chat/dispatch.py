"""Pure chat dispatch classifier.

This module decides whether a user message should stay in Thomas's chat lane
or be delegated to the work lane. It intentionally has no agent/runtime
imports so chat orchestration can use it without crossing into worker code.
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
    r"^\s*(?:are you (?:there|working|alive|awake)|you there|still there|"
    r"ping|status|hello\??)\s*[!?.]*\s*$",
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

_MEMORY_NOTE_RE = re.compile(
    r"^\s*(?:remember\s+(?:this|that)\b|keep\s+in\s+mind\b|note\s+this\b|for\s+future\s+reference\b)",
    re.I,
)

_STATUS_RE = re.compile(
    r"\b(?:status|progress|update|done yet|finished|still running|any news|"
    r"what'?s happening|where are we|how(?:'s| is) (?:that|it|this|the task|the project) going)\b",
    re.I,
)

_HISTORY_RECALL_RE = re.compile(
    r"(?:"
    r"\bwhat was i just\b|"
    r"\bwhat had i\b|"
    r"\bwhat did i\b|"
    r"\bwhat was i talking about\b|"
    r"\bwhat were we talking about\b|"
    r"\bbefore this message\b|"
    r"\bearlier in this chat\b|"
    r"\bwhat task\b|"
    r"\bwhat were\b.*\b(?:i asked|we talked about)\b"
    r")",
    re.I,
)

_INLINE_CHAT_REPLY_RE = re.compile(
    r"\bright here in chat\b|\bin this chat\b|\bin chat\b",
    re.I,
)

_EXPLORATORY_RE = re.compile(
    r"(?:\blet'?s think(?: this)? through\b|\bbrainstorm\b|\bwhat do you think\b|"
    r"\bhow could\b|\bmaybe i should\b|\bshould i\b|\bcould we\b|\bcan we\b|"
    r"\bhelp me think\b|\btalk (?:me )?through\b|\bwalk me through\b|"
    r"\bfigure out how\b|\bi guess\b|\bi wonder\b)",
    re.I,
)

_TOOL_OR_FILE_REQUEST_RE = re.compile(
    r"(?:\buse\s+(?:your\s+)?(?:file|files|tool|tools)\b|"
    r"\b(?:file|files|tool|tools)\b.*\b(?:repo|repository|workspace|folder|directory|path)\b|"
    r"\bopen\s+https?://[^\s,\"')]+.*\b(?:headline|title|main\s+(?:text|content)|page\s+text)\b|"
    r"\bcreate\s+the\s+file\s+[A-Za-z]:\\|\bcreate\s+the\s+file\s+/|"
    r"\bfind\s+the\s+file\s+named\b.*\bdesktop\b|"
    r"\b(?:open|launch|start)\s+[A-Za-z0-9 ._()-]{2,80}?(?:,\s*|\s+then\s+).*\b(?:answer|reply|respond|return)\s+with\s+only\b|"
    r"\btop[- ]level\s+files?\b|"
    r"\bcurrent\s+(?:repo|repository|workspace)\b|"
    r"\bname\s+\w*\s*three\s+top[- ]level\s+files?\b)",
    re.I,
)

_DELEGATION_REQUEST_RE = re.compile(
    r"(?:\bdelegate\b|\bin the background\b|\bbackground work\b|"
    r"\bsub[- ]?agents?\b|\bagents?\b.*\b(?:do|handle|work|take)\b|"
    r"\bspawn\b.*\bsub[- ]?agents?\b)",
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
    r"doc|documentation|spec|project|task|ticket|issue|code|repo|repository|"
    r"game|app|site|website|desktop)\b",
    re.I,
)

_ARTIFACT_CONTEXT_RE = re.compile(
    r"\b(?:i\s+(?:built|created|made|updated|fixed|wrote)|"
    r"open\s+that\s+folder|double-click|launch|desktop\\|desktop/|"
    r"\bindex\.html\b|\bapp\.js\b|\bstyle\.css\b)\b",
    re.I,
)

_ARTIFACT_FIX_FOLLOWUP_RE = re.compile(
    r"(?:\bfix\b|\bpatch\b|\bupdate\b|\bimprove\b|\brepair\b|"
    r"\bslow\b|\bbroken\b|\bbug(?:gy)?\b|\bglitch(?:y)?\b|"
    r"\bdoes(?:n't|nt)\b|\bdid(?:n't|nt)\b|\bwon(?:'t|t)\b|\bcan't\b|\bcant\b|"
    r"\bnot\s+working\b|\bdoes\s+not\b|\bdid\s+not\b|\blevel\b|\badvance\b|"
    r"\bcontrols?\b|\bghosts?\b|\bstuck\b|\bdead\s+ends?\b)",
    re.I,
)

_SHORT_MESSAGE_WORD_LIMIT = 4
_CASUAL_PATTERNS = [
    _GREETING_RE,
    _THANKS_RE,
    _FILLER_RE,
    _LIVENESS_RE,
    _HOW_ARE_YOU_RE,
    _META_RE,
    _MEMORY_NOTE_RE,
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


def _recent_assistant_message(recent_messages: list[dict[str, Any]] | None) -> str:
    if not recent_messages:
        return ""
    for msg in reversed(recent_messages):
        if str(msg.get("role") or "") == "assistant":
            return str(msg.get("content") or "")
    return ""


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

    if _HISTORY_RECALL_RE.search(src):
        return DispatchDecision(action="casual", reason="history_recall")

    if _INLINE_CHAT_REPLY_RE.search(src) and not _TOOL_OR_FILE_REQUEST_RE.search(src):
        return DispatchDecision(action="casual", reason="inline_chat_reply_requested")

    words = src.split()
    if len(words) <= _SHORT_MESSAGE_WORD_LIMIT and not _ACTION_VERB_RE.search(src):
        return DispatchDecision(action="casual", reason="short_no_action_verb")

    if _has_active_tasks(active_tasks) and _STATUS_RE.search(src):
        return DispatchDecision(action="casual", reason="active_task_status_followup")

    if _EXPLORATORY_RE.search(src) and not _DIRECTIVE_PREFIX_RE.search(src):
        return DispatchDecision(action="casual", reason="exploratory_conversation")

    if _TOOL_OR_FILE_REQUEST_RE.search(src):
        return DispatchDecision(action="dispatch", reason="explicit_tool_or_file_request")

    if _DELEGATION_REQUEST_RE.search(src):
        return DispatchDecision(action="dispatch", reason="delegation_request")

    recent_assistant = _recent_assistant_message(recent_messages)
    if recent_assistant and _STATUS_RE.search(src) and "background work" in recent_assistant.lower():
        return DispatchDecision(action="casual", reason="delegation_status_followup")

    if recent_assistant and _ARTIFACT_CONTEXT_RE.search(recent_assistant) and _ARTIFACT_FIX_FOLLOWUP_RE.search(src):
        return DispatchDecision(action="dispatch", reason="artifact_fix_followup")

    if _DIRECTIVE_PREFIX_RE.search(src) and (_ACTION_VERB_RE.search(src) or _DELIVERABLE_RE.search(src)):
        return DispatchDecision(action="dispatch", reason="explicit_execution_request")

    if _ACTION_VERB_RE.search(src) and _DELIVERABLE_RE.search(src):
        return DispatchDecision(action="dispatch", reason="action_verb_with_deliverable")

    if mode == "max" and _ACTION_VERB_RE.search(src):
        return DispatchDecision(action="dispatch", reason="max_mode_actionable")

    return DispatchDecision(action="casual", reason="default_conversation")


__all__ = ["DispatchDecision", "should_dispatch"]
