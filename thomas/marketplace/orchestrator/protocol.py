"""Orchestrator protocol — contracts, tokens, and specialist interface.

Implements schema-validated handoffs inspired by:
    - Google DeepMind's contract-first delegation (Feb 2026)
    - OpenAI Agents SDK guardrails system
    - CrewAI's controlled hierarchies with allowed_agents
"""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Protocol

# ── enums ────────────────────────────────────────────────────────


class SpecialistStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class DelegationPhase(str, Enum):
    """Phases of the orchestrator's thinking process."""

    PLANNING = "planning"
    CLASSIFYING = "classifying"
    DELEGATING = "delegating"
    MONITORING = "monitoring"
    VALIDATING = "validating"
    SYNTHESIZING = "synthesizing"
    RECOVERING = "recovering"


# ── capability token ─────────────────────────────────────────────


@dataclass
class CapabilityToken:
    """Scoped permission token issued by the orchestrator.

    Specialists MUST validate their token before executing any tool.
    Inspired by DeepMind's delegation capability tokens.

    Attributes
    ----------
    token_id:
        Unique identifier for this token.
    specialist_id:
        Which specialist this token authorises.
    session_id:
        Session scope.
    allowed_tools:
        Explicit set of tool names this specialist can invoke.
        Empty set = no tool restrictions (full access).
    allowed_actions:
        Higher-level action categories (e.g., "read", "write", "execute").
    autonomy_level:
        Maximum autonomy this specialist can exercise (1-4).
    issued_at:
        When the token was created.
    expires_at:
        When the token expires (hard timeout).
    """

    token_id: str = field(default_factory=lambda: secrets.token_urlsafe(16))
    specialist_id: str = ""
    session_id: str = ""
    allowed_tools: set[str] = field(default_factory=set)
    allowed_actions: set[str] = field(default_factory=lambda: {"read", "write", "execute"})
    autonomy_level: int = 3
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc) + timedelta(minutes=10))

    def is_valid(self) -> bool:
        """Check if token is still valid (not expired)."""
        return datetime.now(timezone.utc) < self.expires_at

    def permits_tool(self, tool_name: str) -> bool:
        """Check if this token allows a specific tool."""
        if not self.allowed_tools:
            return True  # empty = unrestricted
        # Reasoning tokens already grant the narrow read capabilities below.
        # Treat their web counterparts as the same bounded reads so the chat
        # layer can research without expanding into write or execution tools.
        reasoning_read_bundle = {"fs.read_file", "fs.list_dir", "fs.search"}
        if self.specialist_id == "reasoning" and reasoning_read_bundle.issubset(self.allowed_tools):
            read_aliases = {
                "web.search": "fs.search",
                "web.fetch": "fs.read_file",
            }
            required_capability = read_aliases.get(tool_name)
            if required_capability is not None:
                return required_capability in self.allowed_tools
        return tool_name in self.allowed_tools

    def permits_action(self, action: str) -> bool:
        """Check if this token allows a specific action type."""
        return action in self.allowed_actions


# ── delegation contract ──────────────────────────────────────────


@dataclass
class DelegationContract:
    """Schema-validated contract for orchestrator → specialist handoff.

    The contract defines WHAT the specialist must do, WHAT tools they
    can use, and HOW to validate the output.  This prevents runaway
    specialists and provides clear accountability.

    Attributes
    ----------
    contract_id:
        Unique identifier.
    specialist_id:
        Target specialist for this delegation.
    task_description:
        Human-readable description of what needs to be done.
    input_context:
        Filtered context for this specialist (memory, conversation excerpt).
    success_criteria:
        What constitutes a successful result.  Used by orchestrator to
        validate specialist output.
    allowed_tools:
        Which tools from the 132 domain modules this specialist can use.
    timeout_seconds:
        Hard timeout for specialist execution.
    max_iterations:
        Maximum agent loop iterations.
    priority:
        Execution priority (higher = more important).
    """

    contract_id: str = field(default_factory=lambda: secrets.token_urlsafe(12))
    specialist_id: str = ""
    task_description: str = ""
    input_context: dict[str, Any] = field(default_factory=dict)
    success_criteria: dict[str, Any] = field(default_factory=dict)
    allowed_tools: set[str] = field(default_factory=set)
    timeout_seconds: int = 120
    max_iterations: int = 10
    priority: int = 5

    def validate_output(self, output: dict[str, Any]) -> bool:
        """Validate specialist output against success criteria.

        Returns True if output meets criteria.
        """
        if not self.success_criteria:
            return True  # no criteria = always valid

        # Check required fields
        required = self.success_criteria.get("required_fields", [])
        for f in required:
            if f not in output:
                return False

        # Check minimum content length
        min_len = self.success_criteria.get("min_content_length", 0)
        content = output.get("content", "")
        if isinstance(content, str) and len(content) < min_len:
            return False

        return True


# ── delegation result ────────────────────────────────────────────


@dataclass
class DelegationResult:
    """Result of a specialist execution under contract."""

    contract_id: str = ""
    specialist_id: str = ""
    status: SpecialistStatus = SpecialistStatus.COMPLETED
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    thinking: str = ""
    error: str | None = None
    elapsed_ms: int = 0
    tokens_used: int = 0
    iterations: int = 0

    @property
    def ok(self) -> bool:
        return self.status == SpecialistStatus.COMPLETED and self.error is None


# ── health report ────────────────────────────────────────────────


@dataclass
class HealthReport:
    """Specialist health status for monitoring."""

    specialist_id: str = ""
    healthy: bool = True
    message: str = "OK"
    last_execution_ms: int = 0
    total_executions: int = 0
    error_count: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ── route decision ───────────────────────────────────────────────


@dataclass
class RouteDecision:
    """Orchestrator's routing decision for a user message."""

    specialists: list[str] = field(default_factory=list)
    parallel: bool = False
    reasoning: str = ""
    confidence: float = 0.8
    fallback_specialist: str = "reasoning"
    mode: str = "auto"
    thinking_budget: int = 2_000


# ── specialist protocol ──────────────────────────────────────────


class SpecialistProtocol(Protocol):
    """Interface that all specialist agents must implement.

    Specialists are the workers.  They receive a contract and capability
    token from the orchestrator and execute the delegated task.
    They MUST NOT write directly to the session — only the orchestrator
    manages session state.
    """

    @property
    def specialist_id(self) -> str:
        """Unique identifier for this specialist."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description of capabilities."""
        ...

    @property
    def capabilities(self) -> set[str]:
        """Set of capability tags (e.g., 'coding', 'research', 'analysis')."""
        ...

    async def execute(
        self,
        contract: DelegationContract,
        token: CapabilityToken,
        prompt: str,
        conversation_context: list[dict[str, Any]],
        memory_context: str,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute a delegated task under contract.

        Yields NDJSON-compatible event dicts:
            - {"type": "thinking", "text": "...", "phase": "..."}
            - {"type": "tool_start", "name": "...", "id": "..."}
            - {"type": "tool_result", "name": "...", "result": "...", "ok": bool}
            - {"type": "text", "text": "..."}
            - {"type": "done", "content": "...", "status": "completed"}
        """
        ...

    async def check_health(self) -> HealthReport:
        """Return current health status."""
        ...
