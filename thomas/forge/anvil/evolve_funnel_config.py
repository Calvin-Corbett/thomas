"""Configuration for the funnel evolve engine.

Reads the ``[evolve.funnel]`` table from ``thomas.toml`` (via tomllib, so this
never has to touch the sensitive bottom-of-tree ``thomas/core/config.py``). All
defaults are safe and OFF: with no config, the funnel mode behaves as a
pass-through and changes nothing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import tomllib


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


@dataclass
class FunnelConfig:
    """Tunable knobs for the funnel engine. Safe/off defaults."""

    enabled: bool = False  # master switch for making funnel the standing default
    lanes: int = 5  # isolated lanes per stage
    survivors: int = 3  # width after the first synthesis neck-down (5 -> 3)
    repair_budget_early: int = 3  # first-stage repair attempts
    repair_budget_late: int = 5  # later-stage repair attempts
    simplification: bool = True  # add the deletion-perspective lane at synthesis
    graft_back: bool = False  # optional hybrid graft step (off until proven)
    independent_check_can_self_veto: bool = True  # evaluator may make promotion harder
    max_model_calls_per_goal: int = 40  # funnel-local ceiling (cost backstop)
    # Provider/model profiles (empty -> fall back to the loop profile / default).
    definition_profile: str = ""
    lane_profile: str = ""
    synth_profile: str = ""
    # Candidate profiles (config keys in [models.*]) for the cross-family evaluator;
    # the first whose family is disjoint from the lanes is chosen.
    evaluator_candidates: list[str] = field(default_factory=lambda: ["anthropic", "gemini"])

    @classmethod
    def from_dict(cls, data: dict) -> FunnelConfig:
        d = dict(data or {})
        base = cls()
        return cls(
            enabled=bool(d.get("enabled", base.enabled)),
            lanes=int(d.get("lanes", base.lanes)),
            survivors=int(d.get("survivors", base.survivors)),
            repair_budget_early=int(d.get("repair_budget_early", base.repair_budget_early)),
            repair_budget_late=int(d.get("repair_budget_late", base.repair_budget_late)),
            simplification=bool(d.get("simplification", base.simplification)),
            graft_back=bool(d.get("graft_back", base.graft_back)),
            independent_check_can_self_veto=bool(
                d.get("independent_check_can_self_veto", base.independent_check_can_self_veto)
            ),
            max_model_calls_per_goal=int(d.get("max_model_calls_per_goal", base.max_model_calls_per_goal)),
            definition_profile=str(d.get("definition_profile", base.definition_profile)),
            lane_profile=str(d.get("lane_profile", base.lane_profile)),
            synth_profile=str(d.get("synth_profile", base.synth_profile)),
            evaluator_candidates=list(d.get("evaluator_candidates", base.evaluator_candidates)),
        )

    def with_env_overrides(self) -> FunnelConfig:
        """Apply FUNNEL_* env overrides (handy for tests and cost-lite runs)."""
        self.enabled = _env_bool("FUNNEL_ENABLED", self.enabled)
        self.lanes = _env_int("FUNNEL_LANES", self.lanes)
        self.survivors = _env_int("FUNNEL_SURVIVORS", self.survivors)
        self.repair_budget_early = _env_int("FUNNEL_REPAIR_EARLY", self.repair_budget_early)
        self.repair_budget_late = _env_int("FUNNEL_REPAIR_LATE", self.repair_budget_late)
        self.simplification = _env_bool("FUNNEL_SIMPLIFICATION", self.simplification)
        self.max_model_calls_per_goal = _env_int("FUNNEL_MAX_CALLS", self.max_model_calls_per_goal)
        return self


def load_funnel_config(project_root: Path | None = None) -> FunnelConfig:
    """Load ``[evolve.funnel]`` from ``thomas.toml`` at the repo root.

    Falls back to safe/off defaults if the file or table is absent or malformed.
    """
    root = Path(project_root) if project_root is not None else Path.cwd()
    toml_path = root / "thomas.toml"
    table: dict = {}
    try:
        if toml_path.is_file():
            data = tomllib.loads(toml_path.read_text(encoding="utf-8"))
            table = dict((data.get("evolve", {}) or {}).get("funnel", {}) or {})
    except (OSError, tomllib.TOMLDecodeError):
        table = {}
    return FunnelConfig.from_dict(table).with_env_overrides()
