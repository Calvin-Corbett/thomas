"""The agent registry: the built-in agents, in picker order.

Every caller builds it with ``builtin_registry()`` — the settings contract, the
picker route and the Build runner. A kernel-plugin path that mounted agents on
``thomas/core/kernel`` shipped with the picker and was removed on 2026-09-25:
nothing but its own test ever mounted one.

:func:`resolve` is the load-bearing function. It answers "which agent runs this
request?" from an explicit pick when there is one and from priority when there is
not, and it never substitutes silently: a pick that cannot run the model comes
back as a refusal naming both, which is the failure shape Build already chose for
models it cannot run at all.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from thomas.core.coding_agents.families import UNKNOWN_FAMILY, model_family
from thomas.core.coding_agents.spec import CodingAgentSpec

log = logging.getLogger(__name__)

#: Thomas's own agent loop. The default, and the id every surface falls back to.
DEFAULT_AGENT_ID = "thomas"


class UnknownAgent(LookupError):
    """A pick naming an agent nobody registered."""


class AgentCannotRunModel(ValueError):
    """A registered agent was picked for a model it does not serve."""


class CodingAgentRegistry:
    """The mounted agents, in picker order."""

    def __init__(self) -> None:
        self._agents: dict[str, CodingAgentSpec] = {}

    def __repr__(self) -> str:
        return f"<CodingAgentRegistry {', '.join(self.ids()) or 'empty'}>"

    def __iter__(self) -> Iterator[CodingAgentSpec]:
        return iter(self.all())

    def __len__(self) -> int:
        return len(self._agents)

    def register(self, spec: CodingAgentSpec) -> None:
        if not str(spec.id or "").strip():
            raise ValueError("a coding agent needs an id")
        existing = self._agents.get(spec.id)
        if existing is not None and existing is not spec:
            log.debug("coding agent %r re-registered, replacing %r", spec.id, existing.label)
        self._agents[spec.id] = spec

    def unregister(self, agent_id: str) -> None:
        self._agents.pop(str(agent_id), None)

    def get(self, agent_id: str) -> CodingAgentSpec | None:
        return self._agents.get(str(agent_id or "").strip())

    def ids(self) -> list[str]:
        return [spec.id for spec in self.all()]

    def all(self) -> list[CodingAgentSpec]:
        return sorted(self._agents.values(), key=lambda spec: (spec.priority, spec.id))

    def for_model(self, model_id: str, *, model: str = "") -> list[CodingAgentSpec]:
        """Every agent that can run this model, preferred first."""
        return [spec for spec in self.all() if spec.runs_model(model_id, model=model)]

    def to_dict(self, *, model_id: str = "", model: str = "") -> dict[str, Any]:
        """The picker payload: every agent, and which of them can run the pick.

        ``runs_selected_model`` is per-agent rather than a filtered list on
        purpose — an agent that is here but cannot run the chosen model should be
        visible and explained, not quietly missing from the menu.
        """
        family = model_family(model_id, model=model) if (model_id or model) else ""
        agents = []
        for spec in self.all():
            entry = spec.to_dict()
            entry["is_default"] = spec.id == DEFAULT_AGENT_ID
            if family:
                entry["runs_selected_model"] = spec.runs_family(family)
                entry["reaches_selected_model"] = spec.reaches_family(family)
                if spec.runs_family(family) and not entry["reaches_selected_model"]:
                    entry["unreachable"] = spec.unreachable_hint or f"{spec.label} cannot reach {family} models here."
                if not spec.runs_family(family):
                    entry["mismatch"] = spec.mismatch_hint or (
                        f"{spec.label} does not run {family} models; it runs {', '.join(spec.model_families)}."
                    )
            agents.append(entry)
        return {
            "agents": agents,
            "default": DEFAULT_AGENT_ID,
            "selected_model_family": family or None,
        }


@dataclass(frozen=True)
class AgentSelection:
    """Which agent runs, on which model, and whether anybody chose it."""

    spec: CodingAgentSpec
    plan: Any
    picked: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.spec.id,
            "agent_label": self.spec.label,
            "picked": self.picked,
            "launch": self.plan.to_dict(),
        }


def resolve(
    registry: CodingAgentRegistry,
    *,
    model_id: str,
    model: str = "",
    requested: str = "",
) -> AgentSelection:
    """The agent for this request.

    An explicit ``requested`` id is obeyed exactly or refused — never quietly
    swapped, which is the whole complaint this feature answers. With no pick, the
    lowest-priority-number agent that can run the model and is *ready* wins, so
    Thomas's own loop is the default wherever it can serve; an agent that can run
    the model but is not signed in is used only when nothing ready can.

    "Can serve" includes reach: Thomas's loop declares Claude, but with no
    Anthropic key it cannot get there, so an unpicked Claude run goes to Claude
    Code exactly as it did before the picker existed instead of failing on a
    missing key nobody asked it to use.
    """
    family = model_family(model_id, model=model)
    picked_id = str(requested or "").strip()
    if picked_id:
        spec = registry.get(picked_id)
        if spec is None:
            known = ", ".join(registry.ids()) or "none"
            raise UnknownAgent(f"No coding agent named {picked_id!r}. Installed agents: {known}.")
        if family == UNKNOWN_FAMILY or not spec.runs_family(family):
            raise AgentCannotRunModel(
                f"{spec.label} cannot run {(model_id or model) or 'an unnamed model'} — "
                f"{spec.label} runs {', '.join(spec.model_families)} models. "
                "Pick a different agent or a different model."
            )
        return AgentSelection(spec, spec.plan(model_id or model), picked=True)

    candidates = registry.for_model(model_id, model=model)
    if not candidates:
        raise AgentCannotRunModel(
            f"No installed coding agent runs {(model_id or model) or 'an unnamed model'}. "
            f"Installed agents: {', '.join(registry.ids()) or 'none'}."
        )
    # Reach outranks readiness: an agent that could never get to this family is a
    # worse default than one that only needs signing in, whose refusal says how.
    reaching = [spec for spec in candidates if spec.reaches_family(family)] or candidates
    chosen = next((spec for spec in reaching if spec.availability().ready), reaching[0])
    return AgentSelection(chosen, chosen.plan(model_id or model), picked=False)
