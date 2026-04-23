"""Reasoning Specialist — deep thinking, planning, multi-step analysis.

The default/fallback specialist.  Handles general conversation,
complex reasoning, and multi-step planning tasks.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import Any

from thomas.marketplace.orchestrator.protocol import CapabilityToken, DelegationContract
from thomas.marketplace.specialists.base import BaseSpecialist


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
    re.IGNORECASE,
)
_LOW_SIGNAL_USER_RE = re.compile(
    r"^(?:ok|okay|yeah|yes|yep|sure|do it|go ahead|please do(?: it)?|sounds good|alright|all right)[.! ]*$",
    re.IGNORECASE,
)
_RECALL_STOPWORDS = {
    "about",
    "had",
    "this",
    "chat",
    "what",
    "just",
    "ask",
    "asked",
    "asking",
    "answer",
    "sentence",
    "message",
    "before",
    "earlier",
    "task",
    "talking",
    "talk",
    "were",
    "your",
    "you",
    "me",
    "for",
    "the",
    "and",
    "had",
    "been",
    "did",
    "that",
    "into",
    "one",
}


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _history_recall_response(prompt: str, conversation_context: list[dict[str, Any]]) -> str:
    prompt_text = _normalize_text(prompt)
    if not _HISTORY_RECALL_RE.search(prompt_text):
        return ""

    keywords = [
        token
        for token in re.findall(r"[a-z0-9']+", prompt_text.lower())
        if len(token) > 2 and token not in _RECALL_STOPWORDS
    ]
    candidates: list[str] = []
    for msg in conversation_context:
        if msg.get("role") != "user":
            continue
        content = _normalize_text(msg.get("content"))
        if not content or content == prompt_text:
            continue
        if _HISTORY_RECALL_RE.search(content):
            continue
        if _LOW_SIGNAL_USER_RE.fullmatch(content):
            continue
        candidates.append(content)

    if not candidates:
        return ""

    wants_two = bool(re.search(r"\b(?:two|2)\s+things\b|\bboth\b", prompt_text.lower()))
    if wants_two and len(candidates) >= 2:
        latest = candidates[-1][:200].rstrip(" .,;:!?")
        previous = candidates[-2][:200].rstrip(" .,;:!?")
        return (
            f'Right before this, you asked me to "{latest}", '
            f'and before that you asked me to "{previous}".'
        )

    scored: list[tuple[int, int, str]] = []
    for index, candidate in enumerate(candidates):
        candidate_lower = candidate.lower()
        score = sum(1 for token in keywords if token in candidate_lower)
        scored.append((score, index, candidate))

    best_score, _best_index, best_candidate = max(scored, key=lambda row: (row[0], row[1]))
    if best_score <= 0:
        best_candidate = candidates[-1]

    excerpt = best_candidate[:240].rstrip(" .,;:!?")
    return f'Earlier in this chat, you asked me to "{excerpt}."'


class ReasoningSpecialist(BaseSpecialist):
    """General-purpose reasoning and conversation specialist."""

    @property
    def specialist_id(self) -> str:
        return "reasoning"

    @property
    def description(self) -> str:
        return (
            "Deep thinking, planning, multi-step analysis, general conversation. "
            "Handles anything that doesn't need specialised tools."
        )

    @property
    def capabilities(self) -> set[str]:
        return {
            "reasoning",
            "planning",
            "analysis",
            "conversation",
            "summarization",
            "explanation",
            "brainstorming",
        }

    async def _execute_impl(
        self,
        contract: DelegationContract,
        token: CapabilityToken,
        prompt: str,
        conversation_context: list[dict[str, Any]],
        memory_context: str,
    ) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "thinking", "text": "Reasoning through the request...", "phase": "reasoning"}

        # Build messages for LLM — Thomas's personality from SOUL.md
        # Let the model respond naturally. Don't over-constrain formatting.
        system = (
            "You are Thomas. Your name is Thomas. "
            "You are a sharp, resourceful friend — not a customer service bot.\n\n"
            "Be direct, warm, and real. Lead with the answer. "
            "Keep it short in casual conversation, match the user's energy. "
            "Never open with filler like 'Great question!' — just help. "
            "Respond in plain text only (never respond with JSON).\n\n"
        )
        if memory_context:
            system += (
                "Conversation memory is authoritative context. "
                "If the user asks what happened earlier in this chat, answer "
                "from that memory and correct prior mistaken assistant claims.\n\n"
                f"Context from memory:\n{memory_context}\n\n"
            )

        messages = [{"role": "system", "content": system}]
        # FIX (2026-03-18): Include ALL conversation context, not just last 10.
        # Previously [-10:] caused Thomas to forget names, topics, and context
        # from earlier in the conversation. Also filters out system-role messages
        # to prevent the orchestrator's routing prompt ("You are an orchestrator
        # brain...") from leaking as a visible message.
        for msg in conversation_context:
            if msg.get("role") == "system":
                continue  # Don't leak orchestrator system prompts
            if msg.get("role") == "user" and msg.get("content") == prompt:
                continue  # Skip duplicate of current prompt
            # Filter out internal orchestrator content that got persisted
            # in old sessions. These should NEVER be visible to the user.
            content = str(msg.get("content", ""))
            if "orchestrator brain" in content.lower():
                continue
            if "specialist(s) should handle" in content.lower():
                continue
            if content.strip().startswith('{"specialists"'):
                continue
            messages.append(msg)
        messages.append({"role": "user", "content": prompt})

        recall_response = _history_recall_response(prompt, conversation_context)
        if recall_response:
            yield {"type": "text", "text": recall_response}
            yield {"type": "done", "content": recall_response, "iterations": 1}
            return

        response = ""
        try:
            if hasattr(self.llm, "stream_chat"):
                streamed_parts: list[str] = []
                async for stream_event in self.llm.stream_chat(messages=messages, tools=None):
                    event_type = str(getattr(stream_event, "type", "") or "")
                    data = getattr(stream_event, "data", {}) or {}
                    if event_type == "token":
                        token_text = str(data.get("text", "") or "")
                        if token_text:
                            streamed_parts.append(token_text)
                            yield {"type": "text", "text": token_text}
                    elif event_type == "error":
                        error_text = str(data.get("error") or "Unknown streaming error")
                        yield {"type": "error", "error": f"Reasoning failed: {error_text}"}
                        return
                response = "".join(streamed_parts).strip()
            else:
                response = await self._call_llm(messages, max_tokens=4_000)
        except Exception as exc:
            yield {"type": "error", "error": f"Reasoning failed: {exc}"}
            return

        if not response or not response.strip():
            yield {"type": "error", "error": "Model returned an empty response"}
            return

        if not hasattr(self.llm, "stream_chat"):
            yield {"type": "text", "text": response}
        yield {"type": "done", "content": response, "iterations": 1}
