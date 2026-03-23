"""
Data quality framework for the pipeline.

Implements schema validation, constraint checking, statistical quality,
quality rules engine, and data profiling.
"""

import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from thomas.marketplace.data_pipeline._types import (
    DataType,
    Field,
    Record,
    Schema,
)


@dataclass
class QualityRule:
    """Defines a data quality rule."""

    name: str
    rule_type: str  # "schema", "constraint", "statistical"
    field_name: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    severity: str = "warning"  # "warning", "error"


@dataclass
class QualityCheckResult:
    """Result of a quality check."""

    rule_name: str
    passed: bool
    record_count: int
    failed_count: int
    failure_rate: float
    message: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DataProfile:
    """Statistical profile of a field."""

    field_name: str
    data_type: DataType
    record_count: int
    null_count: int
    distinct_count: int
    cardinality: float
    min_value: Any | None = None
    max_value: Any | None = None
    mean_value: float | None = None
    std_dev: float | None = None
    top_values: list[tuple[Any, int]] = field(default_factory=list)


class SchemaValidator:
    """Validates records against schema."""

    @staticmethod
    def validate_schema(records: list[Record], schema: Schema) -> tuple[bool, list[str]]:
        """
        Validate records against schema.

        Args:
            records: Records to validate
            schema: Schema to validate against

        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []
        seen_fields = set()

        for record in records:
            for field in schema.fields:
                seen_fields.add(field.name)

                if field.name not in record.data:
                    if not field.nullable:
                        errors.append(f"Required field '{field.name}' missing in record")
                else:
                    value = record.get(field.name)
                    if value is None and not field.nullable:
                        errors.append(f"Field '{field.name}' is null but not nullable")

        # Check for unexpected fields
        if records:
            first_record = records[0]
            for key in first_record.data.keys():
                if key not in seen_fields:
                    errors.append(f"Unexpected field '{key}' not in schema")

        return len(errors) == 0, errors


class ConstraintValidator:
    """Validates data constraints."""

    @staticmethod
    def validate_not_null(records: list[Record], field_name: str) -> QualityCheckResult:
        """Check that field is not null."""
        failed = [r for r in records if r.get(field_name) is None]
        return QualityCheckResult(
            rule_name=f"not_null_{field_name}",
            passed=len(failed) == 0,
            record_count=len(records),
            failed_count=len(failed),
            failure_rate=len(failed) / len(records) if records else 0,
            message=f"{len(failed)} null values found",
        )

    @staticmethod
    def validate_unique(records: list[Record], field_name: str) -> QualityCheckResult:
        """Check that field values are unique."""
        values = [r.get(field_name) for r in records]
        duplicates = len(values) - len(set(v for v in values if v is not None))
        return QualityCheckResult(
            rule_name=f"unique_{field_name}",
            passed=duplicates == 0,
            record_count=len(records),
            failed_count=duplicates,
            failure_rate=duplicates / len(records) if records else 0,
            message=f"{duplicates} duplicate values found",
        )

    @staticmethod
    def validate_range(
        records: list[Record],
        field_name: str,
        min_val: Any,
        max_val: Any,
    ) -> QualityCheckResult:
        """Check that field values are within range."""
        failed = [r for r in records if r.get(field_name) is not None and not (min_val <= r.get(field_name) <= max_val)]
        return QualityCheckResult(
            rule_name=f"range_{field_name}",
            passed=len(failed) == 0,
            record_count=len(records),
            failed_count=len(failed),
            failure_rate=len(failed) / len(records) if records else 0,
            message=f"{len(failed)} values outside range [{min_val}, {max_val}]",
        )

    @staticmethod
    def validate_regex_pattern(
        records: list[Record],
        field_name: str,
        pattern: str,
    ) -> QualityCheckResult:
        """Check that field matches regex pattern."""
        regex = re.compile(pattern)
        failed = [r for r in records if r.get(field_name) is not None and not regex.match(str(r.get(field_name)))]
        return QualityCheckResult(
            rule_name=f"pattern_{field_name}",
            passed=len(failed) == 0,
            record_count=len(records),
            failed_count=len(failed),
            failure_rate=len(failed) / len(records) if records else 0,
            message=f"{len(failed)} values don't match pattern {pattern}",
        )

    @staticmethod
    def validate_referential_integrity(
        records: list[Record],
        field_name: str,
        reference_values: set[Any],
    ) -> QualityCheckResult:
        """Check referential integrity against reference set."""
        failed = [r for r in records if r.get(field_name) is not None and r.get(field_name) not in reference_values]
        return QualityCheckResult(
            rule_name=f"referential_{field_name}",
            passed=len(failed) == 0,
            record_count=len(records),
            failed_count=len(failed),
            failure_rate=len(failed) / len(records) if records else 0,
            message=f"{len(failed)} values not in reference set",
        )


class StatisticalQuality:
    """Statistical quality checks."""

    @staticmethod
    def detect_outliers(
        records: list[Record],
        field_name: str,
        method: str = "iqr",  # "iqr", "zscore"
        threshold: float = 1.5,
    ) -> QualityCheckResult:
        """
        Detect outliers using IQR or Z-score.

        Args:
            records: Records to check
            field_name: Field to analyze
            method: Outlier detection method
            threshold: Threshold for outlier detection

        Returns:
            Quality check result
        """
        values = [r.get(field_name) for r in records if isinstance(r.get(field_name), (int, float))]
        if not values:
            return QualityCheckResult(
                rule_name=f"outliers_{field_name}",
                passed=True,
                record_count=len(records),
                failed_count=0,
                failure_rate=0,
                message="No numeric values to check",
            )

        if method == "iqr":
            q1 = statistics.quantiles(values, n=4)[0]
            q3 = statistics.quantiles(values, n=4)[2]
            iqr = q3 - q1
            lower_bound = q1 - threshold * iqr
            upper_bound = q3 + threshold * iqr
            outliers = [v for v in values if v < lower_bound or v > upper_bound]
        else:  # zscore
            mean = statistics.mean(values)
            stdev = statistics.stdev(values) if len(values) > 1 else 0
            outliers = [v for v in values if stdev > 0 and abs((v - mean) / stdev) > threshold]

        return QualityCheckResult(
            rule_name=f"outliers_{field_name}",
            passed=len(outliers) == 0,
            record_count=len(records),
            failed_count=len(outliers),
            failure_rate=len(outliers) / len(records) if records else 0,
            message=f"{len(outliers)} outliers detected",
        )

    @staticmethod
    def check_completeness(
        records: list[Record],
        field_name: str,
        min_threshold: float = 0.95,
    ) -> QualityCheckResult:
        """
        Check data completeness ratio.

        Args:
            records: Records to check
            field_name: Field to analyze
            min_threshold: Minimum acceptable completeness ratio

        Returns:
            Quality check result
        """
        if not records:
            return QualityCheckResult(
                rule_name=f"completeness_{field_name}",
                passed=True,
                record_count=0,
                failed_count=0,
                failure_rate=0,
                message="No records to check",
            )

        non_null = sum(1 for r in records if r.get(field_name) is not None)
        completeness = non_null / len(records)

        return QualityCheckResult(
            rule_name=f"completeness_{field_name}",
            passed=completeness >= min_threshold,
            record_count=len(records),
            failed_count=len(records) - non_null,
            failure_rate=1 - completeness,
            message=f"Completeness: {completeness:.2%}",
        )

    @staticmethod
    def check_freshness(
        records: list[Record],
        timestamp_field: str,
        max_age_hours: int = 24,
    ) -> QualityCheckResult:
        """
        Check data freshness.

        Args:
            records: Records to check
            timestamp_field: Field containing timestamp
            max_age_hours: Maximum acceptable age

        Returns:
            Quality check result
        """
        if not records:
            return QualityCheckResult(
                rule_name=f"freshness_{timestamp_field}",
                passed=True,
                record_count=0,
                failed_count=0,
                failure_rate=0,
                message="No records to check",
            )

        now = datetime.utcnow()
        stale_records = []

        for record in records:
            ts_value = record.get(timestamp_field)
            if isinstance(ts_value, datetime):
                age = (now - ts_value).total_seconds() / 3600
                if age > max_age_hours:
                    stale_records.append(record)

        return QualityCheckResult(
            rule_name=f"freshness_{timestamp_field}",
            passed=len(stale_records) == 0,
            record_count=len(records),
            failed_count=len(stale_records),
            failure_rate=len(stale_records) / len(records) if records else 0,
            message=f"{len(stale_records)} stale records (older than {max_age_hours}h)",
        )


class QualityRulesEngine:
    """Engine for applying quality rules."""

    def __init__(self) -> None:
        """Initialize rules engine."""
        self.rules: list[QualityRule] = []
        self._results: list[QualityCheckResult] = []

    def add_rule(self, rule: QualityRule) -> None:
        """Add a quality rule."""
        self.rules.append(rule)

    def add_not_null_rule(self, field_name: str, severity: str = "error") -> None:
        """Add NOT NULL constraint."""
        self.add_rule(
            QualityRule(
                name=f"not_null_{field_name}",
                rule_type="constraint",
                field_name=field_name,
                parameters={"type": "not_null"},
                severity=severity,
            )
        )

    def add_unique_rule(self, field_name: str, severity: str = "warning") -> None:
        """Add UNIQUE constraint."""
        self.add_rule(
            QualityRule(
                name=f"unique_{field_name}",
                rule_type="constraint",
                field_name=field_name,
                parameters={"type": "unique"},
                severity=severity,
            )
        )

    def add_range_rule(
        self,
        field_name: str,
        min_val: Any,
        max_val: Any,
        severity: str = "warning",
    ) -> None:
        """Add range constraint."""
        self.add_rule(
            QualityRule(
                name=f"range_{field_name}",
                rule_type="constraint",
                field_name=field_name,
                parameters={"type": "range", "min": min_val, "max": max_val},
                severity=severity,
            )
        )

    def add_pattern_rule(
        self,
        field_name: str,
        pattern: str,
        severity: str = "warning",
    ) -> None:
        """Add regex pattern rule."""
        self.add_rule(
            QualityRule(
                name=f"pattern_{field_name}",
                rule_type="constraint",
                field_name=field_name,
                parameters={"type": "pattern", "pattern": pattern},
                severity=severity,
            )
        )

    def evaluate(self, records: list[Record]) -> list[QualityCheckResult]:
        """
        Evaluate all rules against records.

        Args:
            records: Records to evaluate

        Returns:
            List of quality check results
        """
        self._results = []

        for rule in self.rules:
            result = self._evaluate_rule(rule, records)
            self._results.append(result)

        return self._results

    def _evaluate_rule(self, rule: QualityRule, records: list[Record]) -> QualityCheckResult:
        """Evaluate a single rule."""
        if rule.rule_type == "constraint":
            constraint_type = rule.parameters.get("type")

            if constraint_type == "not_null":
                return ConstraintValidator.validate_not_null(records, rule.field_name)
            elif constraint_type == "unique":
                return ConstraintValidator.validate_unique(records, rule.field_name)
            elif constraint_type == "range":
                return ConstraintValidator.validate_range(
                    records,
                    rule.field_name,
                    rule.parameters.get("min"),
                    rule.parameters.get("max"),
                )
            elif constraint_type == "pattern":
                return ConstraintValidator.validate_regex_pattern(
                    records,
                    rule.field_name,
                    rule.parameters.get("pattern"),
                )

        elif rule.rule_type == "statistical":
            stat_type = rule.parameters.get("type")

            if stat_type == "outliers":
                return StatisticalQuality.detect_outliers(
                    records,
                    rule.field_name,
                    rule.parameters.get("method", "iqr"),
                )
            elif stat_type == "completeness":
                return StatisticalQuality.check_completeness(
                    records,
                    rule.field_name,
                    rule.parameters.get("min_threshold", 0.95),
                )

        # Default: pass
        return QualityCheckResult(
            rule_name=rule.name,
            passed=True,
            record_count=len(records),
            failed_count=0,
            failure_rate=0,
            message="Rule not implemented",
        )

    def get_quality_score(self) -> float:
        """
        Calculate overall quality score (0-100).

        Returns:
            Quality score
        """
        if not self._results:
            return 100.0

        passed = sum(1 for r in self._results if r.passed)
        return (passed / len(self._results)) * 100

    def generate_report(self) -> dict[str, Any]:
        """Generate quality report."""
        return {
            "total_checks": len(self._results),
            "passed": sum(1 for r in self._results if r.passed),
            "failed": sum(1 for r in self._results if not r.passed),
            "quality_score": self.get_quality_score(),
            "results": [
                {
                    "rule": r.rule_name,
                    "passed": r.passed,
                    "failed_count": r.failed_count,
                    "failure_rate": f"{r.failure_rate:.2%}",
                    "message": r.message,
                }
                for r in self._results
            ],
        }


class DataProfiler:
    """Generates statistical profiles of data."""

    @staticmethod
    def profile(records: list[Record], schema: Schema) -> list[DataProfile]:
        """
        Generate profiles for all fields.

        Args:
            records: Records to profile
            schema: Schema defining fields

        Returns:
            List of data profiles
        """
        profiles = []

        for field in schema.fields:
            profile = DataProfiler._profile_field(records, field)
            profiles.append(profile)

        return profiles

    @staticmethod
    def _profile_field(records: list[Record], field: Field) -> DataProfile:
        """Profile a single field."""
        values = [r.get(field.name) for r in records]
        non_null = [v for v in values if v is not None]

        numeric_values = [v for v in non_null if isinstance(v, (int, float))]
        mean = statistics.mean(numeric_values) if numeric_values and len(numeric_values) > 1 else None
        stdev = statistics.stdev(numeric_values) if numeric_values and len(numeric_values) > 1 else None

        # Top values
        from collections import Counter

        value_counts = Counter(non_null)
        top_values = value_counts.most_common(10)

        return DataProfile(
            field_name=field.name,
            data_type=field.data_type,
            record_count=len(records),
            null_count=len(values) - len(non_null),
            distinct_count=len(value_counts),
            cardinality=len(value_counts) / len(records) if records else 0,
            min_value=min(numeric_values) if numeric_values else None,
            max_value=max(numeric_values) if numeric_values else None,
            mean_value=mean,
            std_dev=stdev,
            top_values=top_values,
        )
