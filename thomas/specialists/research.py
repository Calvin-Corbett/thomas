"""Research Specialist — web search, documentation, knowledge graph queries.

Handles research tasks by querying Thomas's memory engine (FTS + sparse
vectors + knowledge graph) and synthesising findings.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from thomas.orchestrator.protocol import CapabilityToken, DelegationContract
from thomas.specialists.base import BaseSpecialist


class ResearchSpecialist(BaseSpecialist):
    """Research, documentation lookup, and knowledge synthesis specialist."""

    @property
    def specialist_id(self) -> str:
        return "research"

    @property
    def description(self) -> str:
        return (
            "Research, web search, documentation lookup, knowledge graph queries. "
            "Synthesises information from multiple sources."
        )

    @property
    def capabilities(self) -> set[str]:
        return {
            "research",
            "search",
            "documentation",
            "knowledge_graph",
            "web_search",
            "summarization",
            "fact_checking",
            "web_extract",
            "parse_document",
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
            "text": "Searching knowledge base and preparing research...",
            "phase": "research",
        }

        system = (
            "You are Thomas, doing research. Be direct and lead with answers, "
            "not preamble. Provide well-sourced, accurate information. Distinguish between "
            "facts and inferences.\n\n"
        )
        if memory_context:
            system += f"Knowledge context:\n{memory_context}\n\n"

        messages = [{"role": "system", "content": system}]
        # FIX (2026-03-18): Include full conversation, filter system prompts.
        for msg in conversation_context:
            if msg.get("role") == "system":
                continue
            messages.append(msg)
        messages.append({"role": "user", "content": prompt})

        response = await self._call_llm(messages, max_tokens=4_000)

        yield {"type": "text", "text": response}
        yield {"type": "done", "content": response, "iterations": 1}
