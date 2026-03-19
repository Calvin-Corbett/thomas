"""Synthesis Specialist — aggregates multi-source results.

Handles tasks that require combining information from multiple
sources, documents, or previous conversation turns into coherent
summaries, reports, or decisions.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from thomas.orchestrator.protocol import CapabilityToken, DelegationContract
from thomas.specialists.base import BaseSpecialist


class SynthesisSpecialist(BaseSpecialist):
    """Multi-source aggregation and synthesis specialist."""

    @property
    def specialist_id(self) -> str:
        return "synthesis"

    @property
    def description(self) -> str:
        return (
            "Aggregates information from multiple sources, creates summaries, "
            "compiles reports, and synthesises complex multi-part responses."
        )

    @property
    def capabilities(self) -> set[str]:
        return {
            "synthesis",
            "aggregation",
            "summarization",
            "report_generation",
            "comparison",
            "decision_support",
            "multi_source",
        }

    async def _execute_impl(
        self,
        contract: DelegationContract,
        token: CapabilityToken,
        prompt: str,
        conversation_context: list[dict[str, Any]],
        memory_context: str,
    ) -> AsyncIterator[dict[str, Any]]:
        yield {
            "type": "thinking",
            "text": "Gathering sources and preparing synthesis...",
            "phase": "synthesis",
        }

        system = (
            "You are Thomas's synthesis specialist. Your job is to combine "
            "information from multiple sources into clear, well-structured "
            "responses. Organise information logically, highlight key points, "
            "and provide balanced analysis.\n\n"
        )
        if memory_context:
            system += f"Available context:\n{memory_context}\n\n"

        messages = [{"role": "system", "content": system}]
        # FIX (2026-03-18): Include full conversation, filter system prompts.
        for msg in conversation_context:
            if msg.get("role") == "system":
                continue
            messages.append(msg)
        messages.append({"role": "user", "content": prompt})

        response = await self._call_llm(messages, max_tokens=6_000)

        yield {"type": "text", "text": response}
        yield {"type": "done", "content": response, "iterations": 1}
