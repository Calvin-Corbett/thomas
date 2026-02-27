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
        summary="Conversation only — no tool use",
        system_directive=(
            "Autonomy Level 1 (Chat): you are in chat-only mode. "
            "Do not call tools, execute commands, or make any changes. "
            "Just have a conversation with the user."
        ),
        force_tools_policy="never",
        prefers_extended_iterations=False,
    ),
    2: AutonomyLevelSpec(
        level=2,
        name="Assist",
        ui_label="assist",
        summary="Assist with work — requires manual approval for every tool action",
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
        name="Auto",
        ui_label="auto",
        summary="Autonomous execution including web actions and downloads",
        system_directive=(
            "Autonomy Level 3 (Auto): execute tasks autonomously. "
            "Use tools, browse the web, download files, and complete work "
            "without asking for permission on each step. Only stop if "
            "genuinely blocked or something is ambiguous."
        ),
        force_tools_policy=None,
        prefers_extended_iterations=False,
    ),
    4: AutonomyLevelSpec(
        level=4,
        name="Agent",
        ui_label="agent",
        summary="Full agent mode — does whatever is needed to complete the task",
        system_directive=(
            "Autonomy Level 4 (Agent): full agent mode. Do whatever is needed "
            "to complete the task. Install dependencies, configure tools, make "
            "decisions, and keep going until the job is done. Only stop if "
            "something is truly impossible."
        ),
        force_tools_policy="always",
        prefers_extended_iterations=True,
    ),
}

DEFAULT_AUTONOMY_LEVEL = 3


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
    # Handle names: "chat", "assist", "auto", "agent"
    name_map = {spec.name.lower(): spec.level for spec in _SPECS.values()}
    label_map = {spec.ui_label.lower(): spec.level for spec in _SPECS.values()}
    if s.lower() in name_map:
        return name_map[s.lower()]
    if s.lower() in label_map:
        return label_map[s.lower()]
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
