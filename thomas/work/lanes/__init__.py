"""Work lane runtime: a step ledger a job cannot talk its way past.

A Work job is multi-step, and today the steps are prose aimed at a model that
then reports its own progress. This package makes the progress a verdict instead
of a claim: the agent keeps every tool, but only a gate evaluator advances a
step, and the open step's gate is re-presented every turn so satisfying it never
depends on the agent having remembered a document.

Nothing here writes to ``plans/thomas/``. Lane definitions are user data stored
beside the rest of Work; run ledgers are transient and live under ``runtime/``.
"""

from .model import Gate, Lane, LaneInvalid, Step, validate_lane

__all__ = ["Gate", "Lane", "LaneInvalid", "Step", "validate_lane"]
