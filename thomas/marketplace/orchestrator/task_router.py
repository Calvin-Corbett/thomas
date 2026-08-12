"""Resolve structured task routing fields and assemble a named-bot crew.

Task prose is never inspected here. A model or structured API caller may select
an exact catalog task type and lead specialty. Missing or invalid values resolve
to the neutral general/reasoning route.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from thomas.core.token_economy import effective_effort
from thomas.marketplace.orchestrator import task_catalog as catalog
from thomas.marketplace.orchestrator.bot_roster import Bot, pick_bot_for_specialty

_TEAM_SIZE_BY_EFFORT: dict[str, int] = {"cheap": 1, "optimal": 2, "max": 4}


@dataclass(frozen=True)
class TaskRoute:
    task_type: str
    team_key: str
    default_effort: str
    lead_specialty: str


def route_task(task_type: object = None, *, lead_specialty: object = None) -> TaskRoute:
    """Resolve exact structured enum values; unknown values use a neutral route."""

    requested_type = str(task_type or "").strip().lower()
    resolved_type = requested_type if requested_type in catalog.TASK_SPECS else "general"
    spec = catalog.TASK_SPECS[resolved_type]
    requested_lead = str(lead_specialty or "").strip().lower()
    resolved_lead = requested_lead if requested_lead in catalog.SPECIALTIES else spec.lead
    return TaskRoute(
        task_type=resolved_type,
        team_key=spec.team,
        default_effort=spec.default_effort,
        lead_specialty=resolved_lead,
    )


def _validated_specialties(values: Sequence[object] | None) -> list[str]:
    if not values:
        return []
    return [specialty for value in values if (specialty := str(value or "").strip().lower()) in catalog.SPECIALTIES]


def _roles_for(
    route: TaskRoute,
    internal_effort: str,
    *,
    specialties: Sequence[object] | None = None,
) -> list[str]:
    explicit = _validated_specialties(specialties)
    if explicit:
        return explicit[:8]

    team = catalog.TEAMS.get(route.team_key)
    if team is None:
        base = [route.lead_specialty or "reasoning"]
    else:
        base = []
        for role in team.roles:
            base.extend([role.specialty] * max(1, role.count))
    cap = _TEAM_SIZE_BY_EFFORT.get(internal_effort, 2)
    if cap <= 1:
        return [route.lead_specialty or (base[0] if base else "reasoning")]
    roles = base[:cap] if cap < len(base) else list(base)
    if internal_effort == "max" and "critic" not in roles:
        roles.append("critic")
    return roles


def assemble_team(
    route: TaskRoute,
    effort: Any,
    autonomy_level: int,
    *,
    specialties: Sequence[object] | None = None,
) -> list[tuple[str, Bot]]:
    """Resolve structured routing into a crew without reading task prose."""

    internal = effective_effort(effort, autonomy_level)
    roles = _roles_for(route, internal, specialties=specialties) or [route.lead_specialty or "reasoning"]
    crew: list[tuple[str, Bot]] = []
    exclude: set[str] = set()
    for specialty in roles:
        bot = pick_bot_for_specialty(specialty, exclude=exclude)
        exclude.add(bot.id)
        crew.append((specialty, bot))
    return crew
