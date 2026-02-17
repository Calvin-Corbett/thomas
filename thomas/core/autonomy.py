"""Autonomy level definitions shared by server, UI controls, and agent loop."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class AutonomyLevelSpec:
    level: int
    name: str
    ui_label: str
    summary: str
    system_directive: str
    force_tools_policy: Optional[str] = None  # "never" | "auto" | "always" | None
    prefers_extended_iterations: bool = False


_SPECS: Dict[int, AutonomyLevelSpec] = {
    1: AutonomyLevelSpec(
        level=1,
        name="Manual Review",
        ui_label="manual",
        summary="Ask before every meaningful action",
        system_directive=(
            "Autonomy Level 1 (Manual Review): do not execute tools or make changes by default. "
            "Break work into small explicit steps and ask for approval before each step."
        ),
        force_tools_policy="never",
        prefers_extended_iterations=False,
    ),
    2: AutonomyLevelSpec(
        level=2,
        name="Guarded Assist",
        ui_label="guarded",
        summary="Proceed on approved/safe tasks; ask frequently before risky actions",
        system_directive=(
            "Autonomy Level 2 (Guarded Assist): complete clearly safe or already-approved tasks. "
            "Ask before risky, destructive, or side-effect-heavy actions (writes, installs, remote calls)."
        ),
        force_tools_policy="auto",
        prefers_extended_iterations=False,
    ),
    3: AutonomyLevelSpec(
        level=3,
        name="Tool-Bounded Auto",
        ui_label="auto",
        summary="Run autonomously until tools/knowledge limits are reached",
        system_directive=(
            "Autonomy Level 3 (Tool-Bounded Auto): execute tasks autonomously with available tools. "
            "Stop only when blocked by missing capabilities, credentials, permissions, or hard uncertainty."
        ),
        force_tools_policy=None,
        prefers_extended_iterations=False,
    ),
    4: AutonomyLevelSpec(
        level=4,
        name="Full Auto",
        ui_label="full",
        summary="Maximum autonomy; self-unblock when possible",
        system_directive=(
            "Autonomy Level 4 (Full Auto): maximize execution autonomy. "
            "If blocked by missing local capability, proactively install/configure needed dependencies when safe, "
            "then continue. Assume sensible defaults and keep going. Only stop when genuinely impossible or unsafe."
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


def autonomy_level_options() -> Dict[int, Dict[str, str]]:
    out: Dict[int, Dict[str, str]] = {}
    for level, spec in _SPECS.items():
        out[level] = {
            "name": spec.name,
            "ui_label": spec.ui_label,
            "summary": spec.summary,
        }
    return out
