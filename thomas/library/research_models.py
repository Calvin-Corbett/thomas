"""Data models for research-mode program state and run artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

VALID_METRIC_GOALS = {"maximize", "minimize"}
VALID_RUN_STATUS = {"completed", "failed", "blocked"}
VALID_RUN_DECISIONS = {"pending", "accepted", "rejected"}


def utc_now_iso() -> str:
    """Return a stable UTC timestamp string."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_metric_goal(goal: str) -> str:
    """Validate and normalize a metric goal."""
    normalized = str(goal or "").strip().lower() or "maximize"
    if normalized not in VALID_METRIC_GOALS:
        allowed = ", ".join(sorted(VALID_METRIC_GOALS))
        raise ValueError(f"metric goal must be one of: {allowed}")
    return normalized


def normalize_run_status(status: str) -> str:
    """Validate and normalize run status."""
    normalized = str(status or "").strip().lower() or "completed"
    if normalized not in VALID_RUN_STATUS:
        allowed = ", ".join(sorted(VALID_RUN_STATUS))
        raise ValueError(f"run status must be one of: {allowed}")
    return normalized


def normalize_run_decision(decision: str) -> str:
    """Validate and normalize run decision."""
    normalized = str(decision or "").strip().lower() or "pending"
    if normalized not in VALID_RUN_DECISIONS:
        allowed = ", ".join(sorted(VALID_RUN_DECISIONS))
        raise ValueError(f"run decision must be one of: {allowed}")
    return normalized


def compare_metric(candidate: float, reference: float, goal: str) -> bool:
    """Return whether the candidate beats the reference under the given goal."""
    normalized_goal = normalize_metric_goal(goal)
    if normalized_goal == "minimize":
        return float(candidate) < float(reference)
    return float(candidate) > float(reference)


@dataclass(slots=True)
class ResearchProgramConfig:
    """Configuration for one repo-scoped research program."""

    title: str
    objective: str
    metric_name: str
    metric_goal: str = "maximize"
    baseline_value: float | None = None
    evaluation_command: str = ""
    metric_path: str = ""
    metric_key: str = ""
    editable_paths: list[str] = field(default_factory=list)
    runtime_budget_seconds: int = 300
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    schema_version: int = 1

    def __post_init__(self) -> None:
        self.title = str(self.title or "").strip() or "Thomas Research Program"
        self.objective = str(self.objective or "").strip()
        self.metric_name = str(self.metric_name or "").strip()
        self.metric_goal = normalize_metric_goal(self.metric_goal)
        self.evaluation_command = str(self.evaluation_command or "").strip()
        self.metric_path = str(self.metric_path or "").strip()
        self.metric_key = str(self.metric_key or "").strip()
        self.editable_paths = [str(item or "").strip() for item in self.editable_paths if str(item or "").strip()]
        self.runtime_budget_seconds = max(1, int(self.runtime_budget_seconds or 300))
        if not self.objective:
            raise ValueError("objective is required")
        if not self.metric_name:
            raise ValueError("metric_name is required")
        if self.baseline_value is not None:
            self.baseline_value = float(self.baseline_value)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dictionary."""
        return {
            "schema_version": int(self.schema_version),
            "title": self.title,
            "objective": self.objective,
            "metric_name": self.metric_name,
            "metric_goal": self.metric_goal,
            "baseline_value": self.baseline_value,
            "evaluation_command": self.evaluation_command,
            "metric_path": self.metric_path,
            "metric_key": self.metric_key,
            "editable_paths": list(self.editable_paths),
            "runtime_budget_seconds": int(self.runtime_budget_seconds),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ResearchProgramConfig:
        """Build a config object from JSON payload."""
        return cls(
            schema_version=int(payload.get("schema_version", 1) or 1),
            title=str(payload.get("title") or ""),
            objective=str(payload.get("objective") or ""),
            metric_name=str(payload.get("metric_name") or ""),
            metric_goal=str(payload.get("metric_goal") or "maximize"),
            baseline_value=payload.get("baseline_value"),
            evaluation_command=str(payload.get("evaluation_command") or ""),
            metric_path=str(payload.get("metric_path") or ""),
            metric_key=str(payload.get("metric_key") or ""),
            editable_paths=list(payload.get("editable_paths") or []),
            runtime_budget_seconds=int(payload.get("runtime_budget_seconds", 300) or 300),
            created_at=str(payload.get("created_at") or utc_now_iso()),
            updated_at=str(payload.get("updated_at") or utc_now_iso()),
        )


@dataclass(slots=True)
class ResearchRunRecord:
    """Immutable record for one experiment attempt."""

    run_id: str
    created_at: str
    label: str
    status: str
    metric_name: str
    metric_goal: str
    metric_value: float | None = None
    baseline_value: float | None = None
    frontier_value: float | None = None
    best_previous_value: float | None = None
    verdict: str = "pending"
    decision: str = "pending"
    decision_at: str = ""
    decision_reason: str = ""
    repo_root: str = ""
    evaluation_command: str = ""
    metric_path: str = ""
    metric_key: str = ""
    editable_paths: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    disallowed_files: list[str] = field(default_factory=list)
    runtime_budget_seconds: int = 0
    duration_seconds: float | None = None
    exit_code: int | None = None
    git_head: str = ""
    stdout_path: str = ""
    stderr_path: str = ""
    patch_path: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        self.run_id = str(self.run_id or "").strip()
        self.created_at = str(self.created_at or utc_now_iso())
        self.label = str(self.label or "").strip() or self.run_id
        self.status = normalize_run_status(self.status)
        self.metric_name = str(self.metric_name or "").strip()
        self.metric_goal = normalize_metric_goal(self.metric_goal)
        self.verdict = str(self.verdict or "").strip() or "pending"
        self.decision = normalize_run_decision(self.decision)
        self.decision_at = str(self.decision_at or "").strip()
        self.decision_reason = str(self.decision_reason or "").strip()
        self.repo_root = str(self.repo_root or "").strip()
        self.evaluation_command = str(self.evaluation_command or "").strip()
        self.metric_path = str(self.metric_path or "").strip()
        self.metric_key = str(self.metric_key or "").strip()
        self.editable_paths = [str(item or "").strip() for item in self.editable_paths if str(item or "").strip()]
        self.changed_files = [str(item or "").strip() for item in self.changed_files if str(item or "").strip()]
        self.disallowed_files = [str(item or "").strip() for item in self.disallowed_files if str(item or "").strip()]
        self.runtime_budget_seconds = max(0, int(self.runtime_budget_seconds or 0))
        self.git_head = str(self.git_head or "").strip()
        self.stdout_path = str(self.stdout_path or "").strip()
        self.stderr_path = str(self.stderr_path or "").strip()
        self.patch_path = str(self.patch_path or "").strip()
        self.notes = str(self.notes or "").strip()
        if not self.run_id:
            raise ValueError("run_id is required")
        if not self.metric_name:
            raise ValueError("metric_name is required")
        if self.metric_value is not None:
            self.metric_value = float(self.metric_value)
        if self.baseline_value is not None:
            self.baseline_value = float(self.baseline_value)
        if self.frontier_value is not None:
            self.frontier_value = float(self.frontier_value)
        if self.best_previous_value is not None:
            self.best_previous_value = float(self.best_previous_value)
        if self.duration_seconds is not None:
            self.duration_seconds = round(float(self.duration_seconds), 4)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dictionary."""
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "label": self.label,
            "status": self.status,
            "metric_name": self.metric_name,
            "metric_goal": self.metric_goal,
            "metric_value": self.metric_value,
            "baseline_value": self.baseline_value,
            "frontier_value": self.frontier_value,
            "best_previous_value": self.best_previous_value,
            "verdict": self.verdict,
            "decision": self.decision,
            "decision_at": self.decision_at,
            "decision_reason": self.decision_reason,
            "repo_root": self.repo_root,
            "evaluation_command": self.evaluation_command,
            "metric_path": self.metric_path,
            "metric_key": self.metric_key,
            "editable_paths": list(self.editable_paths),
            "changed_files": list(self.changed_files),
            "disallowed_files": list(self.disallowed_files),
            "runtime_budget_seconds": int(self.runtime_budget_seconds),
            "duration_seconds": self.duration_seconds,
            "exit_code": self.exit_code,
            "git_head": self.git_head,
            "stdout_path": self.stdout_path,
            "stderr_path": self.stderr_path,
            "patch_path": self.patch_path,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ResearchRunRecord:
        """Build a run record from JSON payload."""
        return cls(
            run_id=str(payload.get("run_id") or ""),
            created_at=str(payload.get("created_at") or utc_now_iso()),
            label=str(payload.get("label") or ""),
            status=str(payload.get("status") or "completed"),
            metric_name=str(payload.get("metric_name") or ""),
            metric_goal=str(payload.get("metric_goal") or "maximize"),
            metric_value=payload.get("metric_value"),
            baseline_value=payload.get("baseline_value"),
            frontier_value=payload.get("frontier_value"),
            best_previous_value=payload.get("best_previous_value"),
            verdict=str(payload.get("verdict") or "pending"),
            decision=str(payload.get("decision") or "pending"),
            decision_at=str(payload.get("decision_at") or ""),
            decision_reason=str(payload.get("decision_reason") or ""),
            repo_root=str(payload.get("repo_root") or ""),
            evaluation_command=str(payload.get("evaluation_command") or ""),
            metric_path=str(payload.get("metric_path") or ""),
            metric_key=str(payload.get("metric_key") or ""),
            editable_paths=list(payload.get("editable_paths") or []),
            changed_files=list(payload.get("changed_files") or []),
            disallowed_files=list(payload.get("disallowed_files") or []),
            runtime_budget_seconds=int(payload.get("runtime_budget_seconds", 0) or 0),
            duration_seconds=payload.get("duration_seconds"),
            exit_code=payload.get("exit_code"),
            git_head=str(payload.get("git_head") or ""),
            stdout_path=str(payload.get("stdout_path") or ""),
            stderr_path=str(payload.get("stderr_path") or ""),
            patch_path=str(payload.get("patch_path") or ""),
            notes=str(payload.get("notes") or ""),
        )
