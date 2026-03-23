"""Reasoning Specialist — deep thinking, planning, multi-step analysis.

The default/fallback specialist.  Handles general conversation,
complex reasoning, and multi-step planning tasks.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from thomas.marketplace.orchestrator.protocol import CapabilityToken, DelegationContract
from thomas.marketplace.specialists.base import BaseSpecialist


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
            system += f"Context from memory:\n{memory_context}\n\n"

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

        try:
            response = await self._call_llm(messages, max_tokens=4_000)
        except Exception as exc:
            yield {"type": "error", "error": f"Reasoning failed: {exc}"}
            return

        if not response or not response.strip():
            yield {"type": "error", "error": "Model returned an empty response"}
            return

        yield {"type": "text", "text": response}
        yield {"type": "done", "content": response, "iterations": 1}
