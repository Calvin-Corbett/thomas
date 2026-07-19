"""Specialist agent registry — discovery, health, and dispatch.

The registry manages all available specialists.  The orchestrator
queries the registry to find the best specialist for a given task.

Specialists register themselves at startup (like Thomas's existing
tool registration pattern — try/except with graceful fallback).
"""

from __future__ import annotations

import logging
from copy import copy
from typing import Any

from thomas.marketplace.orchestrator.protocol import (
    HealthReport,
    SpecialistProtocol,
)

log = logging.getLogger(__name__)


class SpecialistRegistry:
    """Registry of all available specialist agents.

    Provides:
        - Registration with graceful fallback (mirrors tool registry pattern)
        - Capability-based lookup
        - Health monitoring
        - Routing suggestions

    Usage::

        registry = SpecialistRegistry()
        registry.register(CodingSpecialist(config, llm))
        registry.register(ResearchSpecialist(config, llm))

        # Find specialists for a task
        candidates = registry.find_by_capability("coding")

        # Get routing suggestion
        decision = registry.suggest_route("Write a Python function")
    """

    def __init__(self) -> None:
        self._specialists: dict[str, SpecialistProtocol] = {}
        self._health: dict[str, HealthReport] = {}
        self._execution_count: dict[str, int] = {}

    def register(self, specialist: SpecialistProtocol) -> bool:
        """Register a specialist.  Returns True on success.

        Uses the same graceful-fallback pattern as Thomas's tool registry:
        if registration fails, log and continue (never block boot).
        """
        try:
            sid = specialist.specialist_id
            self._specialists[sid] = specialist
            self._health[sid] = HealthReport(
                specialist_id=sid,
                healthy=True,
                message="Registered",
            )
            self._execution_count[sid] = 0
            log.info("Registered specialist: %s (%s)", sid, specialist.description)
            return True
        except Exception as exc:
            log.warning("Failed to register specialist: %s", exc)
            return False

    def get(self, specialist_id: str) -> SpecialistProtocol | None:
        """Get a specialist by ID."""
        return self._specialists.get(specialist_id)

    def bound_to_llm(self, llm: Any) -> SpecialistRegistry:
        """Return a request-scoped registry whose specialists use ``llm``.

        Registered specialists are long-lived process objects. Mutating their ``llm``
        attribute for each chat request lets concurrent sessions replace one another's
        model while a turn is running. Shallow copies preserve each specialist's tools
        and configuration while isolating the per-request model binding. Registry health
        and execution counters remain shared process-level telemetry.
        """
        bound = SpecialistRegistry()
        bound._health = self._health
        bound._execution_count = self._execution_count
        bound._specialists = {}
        for specialist_id, specialist in self._specialists.items():
            request_specialist = copy(specialist)
            request_specialist.llm = llm
            bound._specialists[specialist_id] = request_specialist
        return bound

    def find_by_capability(self, capability: str) -> list[SpecialistProtocol]:
        """Find all specialists with a given capability tag."""
        return [s for s in self._specialists.values() if capability in s.capabilities]

    def find_best(self, capabilities: set[str]) -> SpecialistProtocol | None:
        """Find the specialist with the most matching capabilities."""
        best: SpecialistProtocol | None = None
        best_score = 0
        for s in self._specialists.values():
            score = len(capabilities & s.capabilities)
            if score > best_score:
                best = s
                best_score = score
        return best

    @property
    def all_specialists(self) -> list[SpecialistProtocol]:
        """All registered specialists."""
        return list(self._specialists.values())

    @property
    def specialist_ids(self) -> list[str]:
        """All registered specialist IDs."""
        return list(self._specialists.keys())

    def describe_all(self) -> str:
        """Human-readable description of all specialists (for LLM routing)."""
        parts = []
        for s in self._specialists.values():
            caps = ", ".join(sorted(s.capabilities))
            parts.append(f"- {s.specialist_id}: {s.description} [capabilities: {caps}]")
        return "\n".join(parts)

    # ── health ───────────────────────────────────────────────────

    async def check_all_health(self) -> dict[str, HealthReport]:
        """Check health of all specialists."""
        for sid, specialist in self._specialists.items():
            try:
                report = await specialist.check_health()
                self._health[sid] = report
            except Exception as exc:
                self._health[sid] = HealthReport(
                    specialist_id=sid,
                    healthy=False,
                    message=str(exc),
                )
        return dict(self._health)

    def get_health(self, specialist_id: str) -> HealthReport | None:
        return self._health.get(specialist_id)

    def get_healthy_specialists(self) -> list[SpecialistProtocol]:
        """Return only healthy specialists."""
        return [s for sid, s in self._specialists.items() if self._health.get(sid, HealthReport()).healthy]

    # ── execution tracking ───────────────────────────────────────

    def record_execution(self, specialist_id: str) -> None:
        """Increment execution counter for a specialist."""
        self._execution_count[specialist_id] = self._execution_count.get(specialist_id, 0) + 1

    def get_stats(self) -> dict[str, dict[str, Any]]:
        """Return stats for all specialists."""
        stats = {}
        for sid in self._specialists:
            stats[sid] = {
                "executions": self._execution_count.get(sid, 0),
                "healthy": self._health.get(sid, HealthReport()).healthy,
            }
        return stats

    # ── routing ──────────────────────────────────────────────────

    def build_routing_prompt(self, user_message: str) -> str:
        """Build a prompt for the LLM to decide routing.

        The orchestrator's LLM uses this to classify which specialist
        should handle the user's request.
        """
        specialists_desc = self.describe_all()
        return (
            f"You are an orchestrator brain. Given the user's message, decide "
            f"which specialist(s) should handle it.\n\n"
            f"Available specialists:\n{specialists_desc}\n\n"
            f"User message: {user_message}\n\n"
            f"Respond with a JSON object:\n"
            f'{{"specialists": ["specialist_id", ...], '
            f'"parallel": true/false, '
            f'"reasoning": "brief explanation"}}'
        )
