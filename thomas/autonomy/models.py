from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional, Literal

JobStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "failed",
    "dead",
    "awaiting_approval",
    "cancelled",
]

RiskClass = Literal["low", "medium", "high", "critical"]


class AutonomyError(Exception):
    """Base error type for the Autonomy Engine."""


class AutonomyTransientError(AutonomyError):
    """An error that is safe to retry automatically."""


@dataclass(frozen=True)
class RetryPolicy:
    """Per-job retry policy.

    Notes:
    - max_attempts counts total attempts for a *single run* of a job.
    - For recurring jobs (schedule != None), attempts are reset after a successful run,
      and after a final failure we skip to the next scheduled run (so a daily job won't
      permanently die).
    """

    max_attempts: int = 5
    base_delay_s: float = 2.0
    max_delay_s: float = 300.0
    jitter: float = 0.15  # 15% jitter
    backoff: float = 2.0  # exponential

    def compute_delay(self, attempt: int) -> float:
        import random

        # attempt starts at 1
        exp = self.base_delay_s * (self.backoff ** max(0, attempt - 1))
        exp = min(exp, self.max_delay_s)
        j = exp * self.jitter
        # uniform jitter in +/- range
        return max(0.0, exp + (j * (2.0 * random.random() - 1.0)))


@dataclass
class Job:
    id: str
    name: str
    kind: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    next_run_at: Optional[datetime]

    # Relationships / context
    parent_id: Optional[str] = None
    session_id: Optional[str] = None

    payload: Dict[str, Any] = field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    schedule: Optional[Dict[str, Any]] = None

    attempts: int = 0
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)

    risk_class: RiskClass = "low"
    requires_approval: bool = False
    approved: Optional[bool] = None
    cancelled: bool = False


@dataclass
class Approval:
    id: str
    job_id: str
    action: Dict[str, Any]
    risk_class: RiskClass
    status: Literal["pending", "approved", "denied"]
    requested_at: datetime
    decided_at: Optional[datetime] = None
    decided_by: Optional[str] = None
    decision_reason: Optional[str] = None


@dataclass
class AuditEvent:
    id: str
    job_id: Optional[str]
    ts: datetime
    event_type: str
    actor: str
    detail: Dict[str, Any]
    # Optional integrity chain fields
    prev_sig: Optional[str] = None
    sig: Optional[str] = None
