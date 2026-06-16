"""Route a freeform prompt to a task type and assemble a named-bot crew.

Step 2 of the control plane. ``classify_task`` maps a prompt to one of the
predefined task types (keyword heuristic v1 — the model can override later via an
explicit task type). ``assemble_team`` resolves that task's team template into
actual named bots from the roster, scaling the crew size with Effort (after the
Effort<->Autonomy coupling): Brisk = solo lead, Diligent = a small core,
Exhaustive = the full team plus an adversarial critic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from thomas.core.token_economy import effective_effort
from thomas.marketplace.orchestrator import task_catalog as catalog
from thomas.marketplace.orchestrator.bot_roster import Bot, pick_bot_for_specialty

# Ordered keyword -> task-type rules. First match wins. Heuristic only; explicit
# task types (and, later, a model classifier) take precedence over this.
_KEYWORD_RULES: list[tuple[str, str]] = [
    ("vulnerab", "security-audit"),
    ("security audit", "security-audit"),
    ("pentest", "security-audit"),
    ("harden", "security-audit"),
    ("wireframe", "design-ui"),
    ("mockup", "design-ui"),
    ("ui/ux", "design-ui"),
    (" ux ", "design-ui"),
    ("interface", "design-ui"),
    ("refactor", "refactor-code"),
    ("typo", "quick-fix"),
    ("rename ", "quick-fix"),
    ("small tweak", "quick-fix"),
    ("bug", "fix-bug"),
    ("broken", "fix-bug"),
    ("crash", "fix-bug"),
    ("not working", "fix-bug"),
    ("code review", "code-review"),
    ("review the code", "code-review"),
    ("research", "research-topic"),
    ("investigate", "research-topic"),
    ("look into", "research-topic"),
    ("compare", "research-topic"),
    ("analyze", "analyze-data"),
    ("dataset", "analyze-data"),
    ("data analysis", "analyze-data"),
    ("document", "write-docs"),
    ("readme", "write-docs"),
    ("write docs", "write-docs"),
    ("deploy", "deploy-software"),
    ("release", "deploy-software"),
    ("ci/cd", "deploy-software"),
    ("build", "build-feature"),
    ("implement", "build-feature"),
    ("add a feature", "build-feature"),
    ("create", "build-feature"),
    ("make me", "build-feature"),
]

# Crew size cap per internal effort level.
_TEAM_SIZE_BY_EFFORT: dict[str, int] = {"cheap": 1, "optimal": 2, "max": 4}


@dataclass(frozen=True)
class TaskRoute:
    task_type: str
    team_key: str  # "" = solo
    default_effort: str
    lead_specialty: str


def classify_task(prompt: str) -> TaskRoute:
    """Classify a prompt into a predefined task type (heuristic; GENERAL on miss)."""
    text = f" {str(prompt or '').lower()} "
    matched = "general"
    for keyword, task_type in _KEYWORD_RULES:
        if keyword in text:
            matched = task_type
            break
    spec = catalog.TASK_SPECS.get(matched) or catalog.TASK_SPECS["general"]
    return TaskRoute(
        task_type=matched,
        team_key=spec.team,
        default_effort=spec.default_effort,
        lead_specialty=spec.lead,
    )


def _roles_for(route: TaskRoute, internal_effort: str) -> list[str]:
    team = catalog.TEAMS.get(route.team_key)
    if team is None:
        base = [route.lead_specialty or "reasoning"]
    else:
        base = []
        for role in team.roles:
            base.extend([role.specialty] * max(1, role.count))
    cap = _TEAM_SIZE_BY_EFFORT.get(internal_effort, 2)
    if cap <= 1:
        # Brisk: a single lead bot.
        return [route.lead_specialty or (base[0] if base else "reasoning")]
    roles = base[:cap] if cap < len(base) else list(base)
    # Exhaustive always adds an adversarial critic (kept past the cap).
    if internal_effort == "max" and "critic" not in roles:
        roles.append("critic")
    return roles


def assemble_team(route: TaskRoute, effort: Any, autonomy_level: int) -> list[tuple[str, Bot]]:
    """Resolve a route into a crew of (specialty, Bot), scaled by Effort.

    No bot is staffed twice; size scales with the coupled Effort level.
    """
    internal = effective_effort(effort, autonomy_level)
    roles = _roles_for(route, internal) or [route.lead_specialty or "reasoning"]
    crew: list[tuple[str, Bot]] = []
    exclude: set[str] = set()
    for specialty in roles:
        bot = pick_bot_for_specialty(specialty, exclude=exclude)
        exclude.add(bot.id)
        crew.append((specialty, bot))
    return crew
