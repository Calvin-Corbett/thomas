"""Coding Specialist — code generation, review, debugging, refactoring.

Handles all programming tasks.  Uses Thomas's code-related tools
(code_complexity, lint, format_code, dead_code, security_scan, etc.)
with appropriate LLM reasoning.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from thomas.orchestrator.protocol import CapabilityToken, DelegationContract
from thomas.specialists.base import BaseSpecialist


class CodingSpecialist(BaseSpecialist):
    """Code generation, review, debugging, and refactoring specialist."""

    @property
    def specialist_id(self) -> str:
        return "coding"

    @property
    def description(self) -> str:
        return (
            "Code generation, review, debugging, refactoring, testing. "
            "Handles any programming task with access to code analysis tools."
        )

    @property
    def capabilities(self) -> set[str]:
        return {
            "coding",
            "code_review",
            "debugging",
            "refactoring",
            "testing",
            "code_generation",
            "code_analysis",
            "code_complexity",
            "lint",
            "format_code",
            "dead_code",
            "security_scan",
            "git_analysis",
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
            "text": "Analysing coding request...",
            "phase": "code_analysis",
        }

        system = (
            "You are Thomas's coding specialist. You write clean, well-documented, "
            "production-quality code. Follow best practices for the language being used. "
            "Include error handling, type hints (Python), and brief inline comments.\n\n"
        )
        if memory_context:
            system += f"Context:\n{memory_context}\n\n"

        messages = [{"role": "system", "content": system}]
        messages.extend(conversation_context[-8:])
        messages.append({"role": "user", "content": prompt})

        # Use extended thinking if available
        response = await self._call_llm(messages, max_tokens=6_000)

        yield {"type": "text", "text": response}
        yield {"type": "done", "content": response, "iterations": 1}
