"""
State tracking and change detection for configuration management.

Monitors resource state changes, detects drift, generates diffs,
and maintains state history.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class ChangeType(Enum):
    """Types of configuration changes."""

    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    NO_CHANGE = "no_change"
    ROLLED_BACK = "rolled_back"


@dataclass
class DriftDetectionResult:
    """Result of drift detection check."""

    has_drift: bool
    resource_id: str
    resource_name: str
    expected_state: dict[str, Any]
    actual_state: dict[str, Any]
    drift_details: list[dict[str, Any]] = field(default_factory=list)
    detected_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "has_drift": self.has_drift,
            "resource_id": self.resource_id,
            "resource_name": self.resource_name,
            "drift_count": len(self.drift_details),
            "drift_details": self.drift_details,
            "detected_at": self.detected_at.isoformat(),
        }


@dataclass
class StateChange:
    """Represents a single configuration state change."""

    change_id: str
    resource_id: str
    resource_name: str
    change_type: ChangeType
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    diff: dict[str, Any] | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    initiated_by: str = "system"
    tags: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "change_id": self.change_id,
            "resource_id": self.resource_id,
            "resource_name": self.resource_name,
            "change_type": self.change_type.value,
            "timestamp": self.timestamp.isoformat(),
            "initiated_by": self.initiated_by,
        }


@dataclass
class StateHistory:
    """Maintains history of resource state changes."""

    resource_id: str
    changes: list[StateChange] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def add_change(self, change: StateChange) -> None:
        """Add a state change to history."""
        self.changes.append(change)

    def get_latest_change(self) -> StateChange | None:
        """Get most recent change."""
        return self.changes[-1] if self.changes else None

    def get_changes_since(self, since: datetime) -> list[StateChange]:
        """Get all changes since a timestamp."""
        return [c for c in self.changes if c.timestamp >= since]

    def get_change_count(self) -> int:
        """Get total number of changes."""
        return len(self.changes)

    def get_change_types_summary(self) -> dict[str, int]:
        """Get summary of change types."""
        summary: dict[str, int] = {}
        for change in self.changes:
            key = change.change_type.value
            summary[key] = summary.get(key, 0) + 1
        return summary


class StateTracker:
    """Tracks and monitors configuration state changes."""

    def __init__(self) -> None:
        """Initialize state tracker."""
        self.histories: dict[str, StateHistory] = {}
        self.drift_detections: dict[str, DriftDetectionResult] = {}
        self.pending_changes: list[StateChange] = []

    def track_change(self, change: StateChange) -> None:
        """Track a resource state change."""
        resource_id = change.resource_id
        if resource_id not in self.histories:
            self.histories[resource_id] = StateHistory(resource_id=resource_id)

        self.histories[resource_id].add_change(change)

    def record_drift(self, drift_result: DriftDetectionResult) -> None:
        """Record drift detection result."""
        self.drift_detections[drift_result.resource_id] = drift_result

    def get_history(self, resource_id: str) -> StateHistory | None:
        """Get change history for a resource."""
        return self.histories.get(resource_id)

    def get_drift_status(self, resource_id: str) -> DriftDetectionResult | None:
        """Get drift detection status for a resource."""
        return self.drift_detections.get(resource_id)

    def get_resources_with_drift(self) -> list[str]:
        """Get all resources with detected drift."""
        return [r_id for r_id, result in self.drift_detections.items() if result.has_drift]

    def calculate_resource_age(self, resource_id: str) -> float | None:
        """Calculate age of resource in seconds."""
        history = self.get_history(resource_id)
        if not history:
            return None
        if not history.changes:
            return None

        oldest_change = history.changes[0]
        age_seconds = (datetime.utcnow() - oldest_change.timestamp).total_seconds()
        return age_seconds

    def get_state_timeline(self, resource_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get timeline of state changes for a resource."""
        history = self.get_history(resource_id)
        if not history:
            return []

        timeline = []
        for change in history.changes[-limit:]:
            timeline.append(
                {
                    "timestamp": change.timestamp.isoformat(),
                    "change_type": change.change_type.value,
                    "initiated_by": change.initiated_by,
                }
            )

        return timeline

    def generate_change_summary(self) -> dict[str, Any]:
        """Generate summary of all state changes."""
        total_changes = sum(h.get_change_count() for h in self.histories.values())
        resources_with_changes = len(self.histories)
        resources_with_drift = len(self.get_resources_with_drift())

        change_type_counts: dict[str, int] = {}
        for history in self.histories.values():
            for change_type, count in history.get_change_types_summary().items():
                change_type_counts[change_type] = change_type_counts.get(change_type, 0) + count

        return {
            "total_changes": total_changes,
            "resources_with_changes": resources_with_changes,
            "resources_with_drift": resources_with_drift,
            "change_type_breakdown": change_type_counts,
        }

    def get_recent_changes(self, hours: int = 24) -> list[StateChange]:
        """Get changes from last N hours."""
        from datetime import timedelta

        cutoff = datetime.utcnow() - timedelta(hours=hours)

        recent = []
        for history in self.histories.values():
            recent.extend(history.get_changes_since(cutoff))

        return sorted(recent, key=lambda c: c.timestamp, reverse=True)


class DiffGenerator:
    """Generates differences between configuration states."""

    @staticmethod
    def generate_dict_diff(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        """Generate diff between two dictionaries."""
        diff = {
            "added": {},
            "removed": {},
            "modified": {},
            "unchanged": {},
        }

        # Find added and modified keys
        for key, after_value in after.items():
            if key not in before:
                diff["added"][key] = after_value
            elif before[key] != after_value:
                diff["modified"][key] = {
                    "before": before[key],
                    "after": after_value,
                }
            else:
                diff["unchanged"][key] = after_value

        # Find removed keys
        for key, before_value in before.items():
            if key not in after:
                diff["removed"][key] = before_value

        return diff

    @staticmethod
    def generate_unified_diff(before_lines: list[str], after_lines: list[str], filename: str = "config") -> list[str]:
        """Generate unified diff format."""
        diff_lines = [
            f"--- a/{filename}",
            f"+++ b/{filename}",
        ]

        i, j = 0, 0
        while i < len(before_lines) or j < len(after_lines):
            if i < len(before_lines) and j < len(after_lines):
                if before_lines[i] == after_lines[j]:
                    diff_lines.append(f" {before_lines[i]}")
                    i += 1
                    j += 1
                else:
                    diff_lines.append(f"-{before_lines[i]}")
                    i += 1
                    diff_lines.append(f"+{after_lines[j]}")
                    j += 1
            elif i < len(before_lines):
                diff_lines.append(f"-{before_lines[i]}")
                i += 1
            else:
                diff_lines.append(f"+{after_lines[j]}")
                j += 1

        return diff_lines

    @staticmethod
    def calculate_similarity(before: str, after: str) -> float:
        """Calculate similarity percentage between two strings."""
        if before == after:
            return 100.0

        common = sum(1 for a, b in zip(before, after) if a == b)
        max_len = max(len(before), len(after))

        if max_len == 0:
            return 100.0

        return (common / max_len) * 100
