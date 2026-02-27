"""Data quality checks: null rates, uniqueness, ranges, freshness.

Implements data quality assessment and monitoring.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class CheckType(str, Enum):
    """Types of data quality checks."""

    NULL_RATE = "null_rate"
    UNIQUENESS = "uniqueness"
    RANGE = "range"
    PATTERN = "pattern"
    FRESHNESS = "freshness"
    CUSTOM = "custom"


@dataclass
class Check:
    """A data quality check."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    check_type: CheckType = CheckType.CUSTOM
    dataset_id: str = ""
    column_name: str | None = None
    threshold: float = 0.95  # 95% pass rate
    enabled: bool = True
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.check_type.value,
            "threshold": self.threshold,
            "enabled": self.enabled,
        }


@dataclass
class CheckResult:
    """Result of a data quality check."""

    check_id: str
    check_name: str
    passed: bool
    score: float  # 0.0 to 1.0
    timestamp: datetime = field(default_factory=datetime.now)
    details: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "check_name": self.check_name,
            "passed": self.passed,
            "score": self.score,
            "timestamp": self.timestamp.isoformat(),
            "warnings": self.warnings,
        }


class QualityRule:
    """Base class for quality rules."""

    def __init__(self, name: str):
        self.id = str(uuid.uuid4())
        self.name = name

    async def execute(self, data: list[dict[str, Any]]) -> CheckResult:
        """Execute the rule."""
        raise NotImplementedError


class NullRateRule(QualityRule):
    """Check for null rate in a column."""

    def __init__(self, name: str, column: str, max_null_rate: float = 0.05):
        super().__init__(name)
        self.column = column
        self.max_null_rate = max_null_rate

    async def execute(self, data: list[dict[str, Any]]) -> CheckResult:
        """Execute null rate check."""
        if not data:
            return CheckResult(self.id, self.name, False, 0.0)

        nulls = sum(1 for row in data if row.get(self.column) is None)
        null_rate = nulls / len(data)

        passed = null_rate <= self.max_null_rate
        score = 1.0 - null_rate

        return CheckResult(self.id, self.name, passed, score, details={"null_count": nulls, "null_rate": null_rate})


class UniquenessRule(QualityRule):
    """Check for uniqueness in a column."""

    def __init__(self, name: str, column: str, allow_nulls: bool = True):
        super().__init__(name)
        self.column = column
        self.allow_nulls = allow_nulls

    async def execute(self, data: list[dict[str, Any]]) -> CheckResult:
        """Execute uniqueness check."""
        if not data:
            return CheckResult(self.id, self.name, False, 0.0)

        values = []
        for row in data:
            val = row.get(self.column)
            if val is not None or not self.allow_nulls:
                values.append(val)

        unique_count = len(set(v for v in values if v is not None))
        total_count = len(values)

        uniqueness_score = unique_count / total_count if total_count > 0 else 0

        passed = uniqueness_score > 0.95

        return CheckResult(
            self.id,
            self.name,
            passed,
            uniqueness_score,
            details={"unique_values": unique_count, "total_values": total_count},
        )


class RangeRule(QualityRule):
    """Check if values are within a range."""

    def __init__(self, name: str, column: str, min_val: float = None, max_val: float = None):
        super().__init__(name)
        self.column = column
        self.min_val = min_val
        self.max_val = max_val

    async def execute(self, data: list[dict[str, Any]]) -> CheckResult:
        """Execute range check."""
        if not data:
            return CheckResult(self.id, self.name, False, 0.0)

        valid_count = 0
        for row in data:
            val = row.get(self.column)
            if val is None:
                continue
            try:
                num_val = float(val)
                if (self.min_val is None or num_val >= self.min_val) and (
                    self.max_val is None or num_val <= self.max_val
                ):
                    valid_count += 1
            except (ValueError, TypeError):
                pass

        score = valid_count / len(data) if data else 0
        passed = score > 0.95

        return CheckResult(
            self.id, self.name, passed, score, details={"valid_count": valid_count, "total_count": len(data)}
        )


class FreshnessRule(QualityRule):
    """Check data freshness (last update time)."""

    def __init__(self, name: str, max_age_hours: int = 24):
        super().__init__(name)
        self.max_age_hours = max_age_hours

    async def execute(self, data: list[dict[str, Any]], last_update: datetime = None) -> CheckResult:
        """Execute freshness check."""
        if last_update is None:
            last_update = datetime.now()

        age = datetime.now() - last_update
        age_hours = age.total_seconds() / 3600

        passed = age_hours <= self.max_age_hours
        score = max(0, 1.0 - (age_hours / (self.max_age_hours * 2)))

        return CheckResult(
            self.id, self.name, passed, score, details={"age_hours": age_hours, "max_age_hours": self.max_age_hours}
        )


class QualityMonitor:
    """Monitors data quality."""

    def __init__(self, name: str = "monitor"):
        self.id = str(uuid.uuid4())
        self.name = name
        self.checks: dict[str, Check] = {}
        self.rules: dict[str, QualityRule] = {}
        self.results: list[CheckResult] = []
        self.datasets: dict[str, datetime] = {}  # track last update time

    def register_check(self, check: Check) -> None:
        """Register a quality check."""
        self.checks[check.id] = check

    def register_rule(self, rule: QualityRule) -> None:
        """Register a quality rule."""
        self.rules[rule.id] = rule

    def record_update(self, dataset_id: str) -> None:
        """Record when a dataset was updated."""
        self.datasets[dataset_id] = datetime.now()

    async def execute_checks(self, dataset_id: str, data: list[dict[str, Any]]) -> list[CheckResult]:
        """Execute all checks for a dataset."""
        results = []

        for rule in self.rules.values():
            try:
                result = await rule.execute(data)
                results.append(result)
                self.results.append(result)
            except Exception:
                pass

        return results

    def get_quality_score(self, dataset_id: str = None) -> float:
        """Get overall quality score."""
        if not self.results:
            return 1.0

        dataset_results = (
            self.results[-10:]
            if not dataset_id
            else [r for r in self.results if r.check_id in [c.id for c in self.checks.values()]]
        )

        if not dataset_results:
            return 1.0

        return sum(r.score for r in dataset_results) / len(dataset_results)

    def get_report(self) -> dict[str, Any]:
        """Get a quality report."""
        passed_count = sum(1 for r in self.results if r.passed)
        failed_count = len(self.results) - passed_count

        return {
            "monitor_id": self.id,
            "monitor_name": self.name,
            "total_checks": len(self.checks),
            "total_results": len(self.results),
            "passed_results": passed_count,
            "failed_results": failed_count,
            "overall_score": self.get_quality_score(),
            "recent_results": [r.to_dict() for r in self.results[-5:]],
        }
