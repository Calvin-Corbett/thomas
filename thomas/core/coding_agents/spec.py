"""What a coding agent is, as a contract Thomas can hold at arm's length.

Build already drives an outside coding agent: when the model was a Claude model
it launched Claude Code headless with a tool policy, an MCP bridge back to the
Praxis run channel, and a stream-json reader that turned the agent's output into
Thomas's own events. Everything around that — Autopilot, repair rounds, the
green, the cage, the cards — was Thomas's. Only *which* agent ran was not a
choice: it fell out of the model's family.

These dataclasses are the choice. An agent says

- **who it is** (``id``, ``label``, ``summary``),
- **whether it is here** (``availability`` -> :class:`AgentAvailability`),
- **which models it can run** (``model_families``, ``default_model``),
- **how to launch it** (``dispatch``, a ``module:function`` naming a uniform
  ``(request: AgentRunRequest) -> result`` function, plus :meth:`plan` for the
  provider profile that entry point needs),
- **how its output becomes Thomas's events** — the entry point's own job, since
  each agent's stream shape is its own.

The shell rule and the record of what ran stay Thomas's: they arrive in
:class:`AgentRunRequest`, which the caller fills from the run's policy, and no
agent decides them for itself.

This module imports only ``thomas.core``. The ``dispatch`` string is a *name*,
resolved by the forge runner that owns the dispatchers, so ``core`` never imports
``forge`` (``thomas/_architecture.py`` does not allow it).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from thomas.core.coding_agents.families import UNKNOWN_FAMILY, model_family, strip_wire_prefix


@dataclass(frozen=True)
class AgentAvailability:
    """Whether this agent is installed and signed in, and how to say so.

    Two booleans rather than one, because the ways out differ: Claude Code that
    is missing needs installing, and Claude Code that is present but not signed
    in needs ``claude`` run once in a terminal. Collapsing them into "not
    available" is how a fixable situation reads as a dead end.
    """

    installed: bool
    signed_in: bool
    detail: str = ""

    @property
    def ready(self) -> bool:
        return bool(self.installed and self.signed_in)

    def to_dict(self) -> dict[str, Any]:
        return {
            "installed": bool(self.installed),
            "signed_in": bool(self.signed_in),
            "ready": self.ready,
            "detail": str(self.detail or ""),
        }


@dataclass(frozen=True)
class AgentLaunchPlan:
    """The agent-specific half of a launch: which model, reached how.

    ``profile``/``provider`` are empty for an agent that carries its own sign-in
    (Claude Code), and filled for one that runs through a Thomas LLM profile.
    """

    agent_id: str
    model: str
    profile: str = ""
    provider: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent_id,
            "model": self.model,
            "profile": self.profile,
            "provider": self.provider,
        }


@dataclass
class AgentRunRequest:
    """One Build pass, as every agent receives it.

    Thomas's rules ride here, not in the agent: ``allow_shell`` is already the
    answer ``direct_shell_allowed`` gave for this exact policy, ``protected_paths``
    is the run's fence, and ``emit`` is the sink the agent's translated events go
    to. An agent that wants a different policy does not get one.
    """

    goal: str
    cwd: str | Path
    plan: AgentLaunchPlan
    definition: str = ""
    task_plan: str = ""
    timeout: int = 900
    dry_run: bool = True
    max_fix_iters: int = 2
    history: Any = None
    file_access: str = "project"
    guardrails: str = "guarded"
    autonomy_level: int = 3
    token_economy: str = "balanced"
    allow_shell: bool = False
    protected_paths: list[str] = field(default_factory=list)
    oauth_access_token: str = ""
    allow_without_history: bool = False
    emit: Callable[[dict[str, Any]], None] | None = None
    verify: bool = True
    verifier: Any = None
    runner: Any = None


@dataclass(frozen=True)
class CodingAgentSpec:
    """A coding agent, as declared facts the registry reads.

    ``priority`` orders the picker and breaks the tie when nobody picked: the
    lowest number that can run the model and is ready wins. Thomas's own loop is
    0, so it stays the default.
    """

    id: str
    label: str
    summary: str
    dispatch: str
    model_families: tuple[str, ...]
    availability: Callable[[], AgentAvailability]
    planner: Callable[[str], AgentLaunchPlan]
    default_model: str = ""
    priority: int = 100
    #: A short sentence for the picker when this agent cannot run the pick.
    mismatch_hint: str = ""
    #: Whether this machine can reach a family through this agent right now —
    #: Thomas's loop runs Claude only with an Anthropic key. ``None`` means every
    #: declared family is reachable whenever the agent is ready.
    reaches: Callable[[str], bool] | None = None
    #: The sentence for the picker when this agent runs the family but cannot reach it here.
    unreachable_hint: str = ""

    def runs_family(self, family: str) -> bool:
        return str(family) in self.model_families

    def reaches_family(self, family: str) -> bool:
        return self.runs_family(family) and (self.reaches is None or bool(self.reaches(family)))

    def runs_model(self, model_id: str, *, model: str = "") -> bool:
        family = model_family(model_id, model=model)
        return family != UNKNOWN_FAMILY and self.runs_family(family)

    def plan(self, model_id: str) -> AgentLaunchPlan:
        """The launch plan for a model, with the wire prefix already shed."""
        return self.planner(strip_wire_prefix(model_id) or self.default_model)

    def to_dict(self) -> dict[str, Any]:
        """The picker's view: identity, reach, and readiness — never a secret."""
        return {
            "id": self.id,
            "label": self.label,
            "summary": self.summary,
            "model_families": list(self.model_families),
            "default_model": self.default_model,
            "priority": self.priority,
            "availability": self.availability().to_dict(),
        }
