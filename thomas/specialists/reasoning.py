"""Reasoning Specialist — deep thinking, planning, multi-step analysis.

The default/fallback specialist.  Handles general conversation,
complex reasoning, and multi-step planning tasks.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from thomas.orchestrator.protocol import CapabilityToken, DelegationContract
from thomas.specialists.base import BaseSpecialist


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

        # Build messages for LLM
        system = (
            "You are Thomas, an AI assistant named Thomas. "
            "Respond naturally in plain text (never respond with JSON). "
            "Think carefully and provide thorough, well-structured responses.\n\n"
        )
        if memory_context:
            system += f"Context from memory:\n{memory_context}\n\n"

        messages = [{"role": "system", "content": system}]
        # Add conversation context (skip duplicate — prompt is appended below)
        for msg in conversation_context[-10:]:
            if msg.get("role") != "user" or msg.get("content") != prompt:
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
