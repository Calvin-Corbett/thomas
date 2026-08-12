"""Compatibility facade for the blue-only evolve decision matrix.

The promotion decision primitive lives in ``evolve_supervisor.decision`` so it
is not owned by the green mirror. Keep this module as the old import path for
CLI and tests that still refer to ``thomas.forge.anvil.evolve_autonomy``.
"""

from __future__ import annotations

from evolve_supervisor.decision import (
    ACTION_APPROVE,
    ACTION_PROMOTE,
    ACTION_REJECT,
    DEFAULT_POSTURE,
    POSTURE_LABELS,
    EvolvePosture,
    PromotionDecision,
    SessionOutcome,
    auto_promotable,
    decide_for_session,
    decide_promotion,
    parse_posture,
    summarize_session_outcome,
)

__all__ = [
    "ACTION_APPROVE",
    "ACTION_PROMOTE",
    "ACTION_REJECT",
    "DEFAULT_POSTURE",
    "POSTURE_LABELS",
    "EvolvePosture",
    "PromotionDecision",
    "SessionOutcome",
    "auto_promotable",
    "decide_for_session",
    "decide_promotion",
    "parse_posture",
    "summarize_session_outcome",
]
