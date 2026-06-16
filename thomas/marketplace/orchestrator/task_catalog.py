"""Staffing catalog: specialty list, named team templates, task-type -> team map.

This is the data the task router draws on to compose a crew. It is plain data so
it can be tuned without touching routing logic. (Externalizing to an editable
TOML/JSON overlay is a follow-up; these structures are the v1 source of truth.)

Specialties map onto the bot roster's specialties where a dedicated bot exists;
where one does not, the router falls back to any available bot, so a named bot
still spawns for every role.
"""

from __future__ import annotations

from dataclasses import dataclass

# The full specialty catalog (extends the 5 the dispatcher used historically).
SPECIALTIES: dict[str, str] = {
    "planning": "Break work into a plan, sequence, and estimate.",
    "reasoning": "General problem-solving and multi-step thinking.",
    "coding": "Write, edit, and integrate code.",
    "code-review": "Inspect code for correctness, quality, and security.",
    "debug": "Diagnose errors and find root causes.",
    "testing": "Write tests and verify behavior.",
    "refactoring": "Improve structure without changing behavior.",
    "engineering": "Systems design, architecture, performance.",
    "research": "Investigate, fact-find, synthesize sources.",
    "analysis": "Decompose problems, assess risk and trade-offs.",
    "data": "Process, analyze, and visualize data.",
    "synthesis": "Aggregate, summarize, and report.",
    "design": "UI/UX, layout, visual direction.",
    "creative": "Ideation and content creation.",
    "documentation": "Technical writing and guides.",
    "ops": "Deployment, infrastructure, DevOps.",
    "tools": "Run commands, automation, file/system ops.",
    "security-audit": "Vulnerability scanning and hardening.",
    "comms": "Communicate and present for an audience.",
    "critic": "Adversarial reviewer — argue against the work.",
}


@dataclass(frozen=True)
class TeamRole:
    specialty: str
    count: int = 1


@dataclass(frozen=True)
class Team:
    name: str
    roles: tuple[TeamRole, ...]
    strategy: str = "parallel"  # parallel | sequential
    suited_for: str = ""


# 10 named team templates.
TEAMS: dict[str, Team] = {
    "code-review": Team(
        "Code Review",
        (TeamRole("code-review"), TeamRole("testing"), TeamRole("security-audit")),
        "parallel",
        "deep code inspection across quality + security",
    ),
    "feature-build": Team(
        "Feature Build",
        (TeamRole("planning"), TeamRole("coding"), TeamRole("testing"), TeamRole("design")),
        "sequential",
        "end-to-end feature from plan to tests",
    ),
    "bug-fix": Team(
        "Bug Fix",
        (TeamRole("debug"), TeamRole("coding"), TeamRole("testing")),
        "sequential",
        "diagnose, fix, and regression-test",
    ),
    "refactor": Team(
        "Refactoring",
        (TeamRole("refactoring"), TeamRole("coding"), TeamRole("testing")),
        "sequential",
        "improve structure without behavior change",
    ),
    "research-pod": Team(
        "Research Pod",
        (TeamRole("research"), TeamRole("synthesis"), TeamRole("analysis")),
        "parallel",
        "multi-source investigation",
    ),
    "content-squad": Team(
        "Content Squad",
        (TeamRole("synthesis"), TeamRole("creative"), TeamRole("design")),
        "parallel",
        "content-heavy work with design",
    ),
    "data-analysis": Team(
        "Data Analysis",
        (TeamRole("data"), TeamRole("synthesis"), TeamRole("analysis")),
        "parallel",
        "insights and visualizations",
    ),
    "deployment": Team(
        "Deployment",
        (TeamRole("ops"), TeamRole("tools"), TeamRole("engineering")),
        "sequential",
        "deploy software and manage infra",
    ),
    "design-cell": Team(
        "UI/UX Design",
        (TeamRole("design"), TeamRole("creative"), TeamRole("coding")),
        "parallel",
        "interface design with implementation",
    ),
    "red-team": Team(
        "Security Hardening",
        (TeamRole("security-audit", 2), TeamRole("code-review"), TeamRole("ops"), TeamRole("testing")),
        "parallel",
        "adversarial security audit (Exhaustive-grade)",
    ),
}


@dataclass(frozen=True)
class TaskSpec:
    team: str  # key into TEAMS ("" = solo / no team)
    default_effort: str  # brisk | diligent | exhaustive
    lead: str = "reasoning"  # lead specialty for the solo / fallback case


# task-type -> default team + default Effort. 11 predefined tasks + general.
TASK_SPECS: dict[str, TaskSpec] = {
    "build-feature": TaskSpec("feature-build", "diligent", "coding"),
    "fix-bug": TaskSpec("bug-fix", "diligent", "debug"),
    "code-review": TaskSpec("code-review", "diligent", "code-review"),
    "refactor-code": TaskSpec("refactor", "diligent", "refactoring"),
    "research-topic": TaskSpec("research-pod", "diligent", "research"),
    "analyze-data": TaskSpec("data-analysis", "diligent", "data"),
    "write-docs": TaskSpec("content-squad", "diligent", "documentation"),
    "deploy-software": TaskSpec("deployment", "diligent", "ops"),
    "design-ui": TaskSpec("design-cell", "diligent", "design"),
    "security-audit": TaskSpec("red-team", "exhaustive", "security-audit"),
    "quick-fix": TaskSpec("", "brisk", "coding"),
    "general": TaskSpec("", "diligent", "reasoning"),
}
