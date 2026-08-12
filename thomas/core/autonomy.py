"""Autonomy level definitions shared by server, UI controls, and agent loop."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AutonomyLevelSpec:
    level: int
    name: str
    ui_label: str
    summary: str
    system_directive: str
    force_tools_policy: str | None = None  # "never" | "auto" | "always" | None
    prefers_extended_iterations: bool = False


_SPECS: dict[int, AutonomyLevelSpec] = {
    1: AutonomyLevelSpec(
        level=1,
        name="Chat",
        ui_label="chat",
        summary="Conversation, memory, and read-only observation — no mutation or delegation",
        system_directive=(
            "Autonomy Level 1 (Chat): converse, remember, recall, and use bounded "
            "read-only observation when it helps. Do not mutate state, delegate work, "
            "execute commands, or make external changes."
        ),
        force_tools_policy="never",
        prefers_extended_iterations=False,
    ),
    2: AutonomyLevelSpec(
        level=2,
        name="Assist",
        ui_label="assist",
        summary="Assist with work — confirm before mutation or delegation",
        system_directive=(
            "Autonomy Level 2 (Assist): help the user with their work. "
            "Before every tool call or action, describe what you want to do "
            "and wait for explicit user approval. Never execute a tool without "
            "the user confirming first."
        ),
        force_tools_policy="auto",
        prefers_extended_iterations=False,
    ),
    3: AutonomyLevelSpec(
        level=3,
        name="Agent",
        ui_label="agent",
        summary="Agent mode with autonomous tool use, web actions, and downloads",
        system_directive=(
            "Autonomy Level 3 (Agent): execute tasks autonomously. "
            "Use tools, browse the web, download files, and complete work "
            "without asking for permission on each step. Only stop if "
            "genuinely blocked or something is ambiguous."
        ),
        force_tools_policy=None,
        prefers_extended_iterations=False,
    ),
    4: AutonomyLevelSpec(
        level=4,
        name="Full Autonomy",
        ui_label="full_autonomy",
        summary="Full agent mode — does whatever is needed to complete the task",
        system_directive=(
            "Autonomy Level 4 (Full Autonomy): do whatever is needed "
            "to complete the task. Install dependencies, configure tools, make "
            "decisions, keep momentum, and continue until the job is done. "
            "Use native operating-system authentication for sensitive actions "
            "instead of stopping for routine confirmation. Only stop if "
            "something is truly impossible or unsafe."
        ),
        force_tools_policy="always",
        prefers_extended_iterations=True,
    ),
}

# Default = L2 Assist (asks for approval before acting), NOT L3 Agent. Calvin
# design law (2026-06-14): the system must not act autonomously "by default" — the
# user opts UP into hands-off autonomy; it is never on out of the box. The autonomy
# levels themselves are unchanged; only the default is. Do not raise this back
# to 3 without Calvin.
DEFAULT_AUTONOMY_LEVEL = 2


def clamp_autonomy_level(value: object, *, default: int = DEFAULT_AUTONOMY_LEVEL) -> int:
    try:
        iv = int(value)
    except Exception:
        iv = int(default)
    if iv < 1:
        return 1
    if iv > 4:
        return 4
    return iv


def autonomy_spec(level: object) -> AutonomyLevelSpec:
    lv = clamp_autonomy_level(level)
    return _SPECS.get(lv, _SPECS[DEFAULT_AUTONOMY_LEVEL])


def autonomy_level_name(level: object) -> str:
    return autonomy_spec(level).name


def autonomy_level_ui_label(level: object) -> str:
    return autonomy_spec(level).ui_label


def autonomy_level_summary(level: object) -> str:
    return autonomy_spec(level).summary


def autonomy_system_directive(level: object) -> str:
    return autonomy_spec(level).system_directive


def chat_delegation_directive(level: object) -> str:
    """Autonomy-aware instruction for Thomas's governed conversation surface.

    Identity remains constant. The level changes which bounded actions may run,
    which require confirmation, and when heavy work may be delegated.
    """
    lv = clamp_autonomy_level(level)
    if lv <= 1:
        return (
            "AUTONOMY (Level 1 — Chat): converse, remember, recall, and use read-only "
            "observation. You cannot mutate state or hand work off at this level; if the user "
            "wants that, offer the action and explain that Assist or higher is required."
        )
    if lv == 2:
        return (
            "AUTONOMY (Level 2 — Assist): read-only observation can run directly. Before "
            "mutating even bounded local state or handing work to the task manager, confirm "
            "with the user first. After confirmation, use operate for a bounded action or "
            "send_task for heavy work."
        )
    if lv == 3:
        return (
            "AUTONOMY (Level 3 — Agent): use operate directly for supported bounded local "
            "actions. When the request is heavier or outside that allowlist, hand it to the "
            "task manager immediately via send_task. Do NOT "
            "ask permission first — that 'want me to hand this off?' question does not "
            "apply at this level. Just hand it off and tell them you've done so. Only "
            "pause to ask if the request is genuinely ambiguous."
        )
    return (
        "AUTONOMY (Level 4 — Full Autonomy / Max): the user wants autopilot. Use operate "
        "for supported bounded local actions; hand heavier actionable requests to the task "
        "manager immediately and WITHOUT asking — never "
        "say 'want me to hand this off?' at this level. Hand it off via send_task and "
        "then tell them you've done so. Only pause if the request is genuinely "
        "ambiguous; do not seek routine confirmation. "
        "CAPABILITY GAPS — this is the whole point of Full Autonomy: if the user asks "
        "for something you cannot currently do because a tool or capability is missing "
        "(for example live web search, an integration, or an action you have no tool "
        "for), do NOT just decline and stop. Acknowledge it isn't wired up yet, then "
        "IMMEDIATELY hand the job of BUILDING that capability to the task manager via "
        "send_task — the worker crew can add it. Your organic response should be 'I "
        "can't do that yet — but I'm building it now' followed by an actual hand-off, "
        "never a dead-end 'I don't have that.' Extend yourself to meet the request."
    )


def parse_autonomy_level(value: object, *, default: int = DEFAULT_AUTONOMY_LEVEL) -> int:
    """Parse autonomy level from any format: int, 'L1'-'L4', '1'-'4', etc.

    Bridges the gap between preferences (string 'L1'-'L4') and
    core system (int 1-4). Use this instead of manual level_map dicts.
    """
    if value is None:
        return clamp_autonomy_level(default)
    s = str(value).strip().upper()
    if not s:
        return clamp_autonomy_level(default)
    # Handle "L1", "L2", etc.
    if s.startswith("L") and len(s) >= 2:
        try:
            return clamp_autonomy_level(int(s[1:]))
        except (ValueError, TypeError):
            pass
    # Handle bare integers or stringified ints
    try:
        return clamp_autonomy_level(int(s))
    except (ValueError, TypeError):
        pass
    # Handle names and historical aliases.
    name_map = {spec.name.lower(): spec.level for spec in _SPECS.values()}
    label_map = {spec.ui_label.lower(): spec.level for spec in _SPECS.values()}
    alias_map = {
        "auto": 3,
        "agent": 3,
        "full autonomy": 4,
        "full_autonomy": 4,
        "full-autonomy": 4,
    }
    if s.lower() in name_map:
        return name_map[s.lower()]
    if s.lower() in label_map:
        return label_map[s.lower()]
    if s.lower() in alias_map:
        return alias_map[s.lower()]
    return clamp_autonomy_level(default)


def autonomy_level_to_pref(level: int) -> str:
    """Convert integer autonomy level to preferences format ('L1'-'L4')."""
    clamped = clamp_autonomy_level(level)
    return f"L{clamped}"


def autonomy_level_options() -> dict[int, dict[str, str]]:
    out: dict[int, dict[str, str]] = {}
    for level, spec in _SPECS.items():
        out[level] = {
            "name": spec.name,
            "ui_label": spec.ui_label,
            "summary": spec.summary,
        }
    return out
