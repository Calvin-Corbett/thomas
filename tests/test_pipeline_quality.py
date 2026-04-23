"""
Tests for data quality framework.
"""

import sys

sys.path.insert(0, "/sessions/zen-pensive-cannon/mnt/Thomas")

from thomas.marketplace.data_pipeline._types import (
    DataType,
    Field,
    Record,
    Schema,
)
from thomas.marketplace.data_pipeline.quality import (
    ConstraintValidator,
    DataProfiler,
    QualityRulesEngine,
    SchemaValidator,
    StatisticalQuality,
)


class TestSchemaValidator:
    """Test schema validation."""

    def test_schema_valid(self):
        """Test valid records."""
        schema = Schema(
            fields=[
                Field(name="id", data_type=DataType.INTEGER, nullable=False),
                Field(name="name", data_type=DataType.STRING, nullable=True),
            ]
        )

        records = [
            Record(data={"id": 1, "name": "Alice"}),
            Record(data={"id": 2, "name": None}),
        ]

        is_valid, errors = SchemaValidator.validate_schema(records, schema)

        assert is_valid
        assert len(errors) == 0

    def test_schema_missing_required(self):
        """Test missing required field."""
        schema = Schema(
            fields=[
                Field(name="id", data_type=DataType.INTEGER, nullable=False),
            ]
        )

        records = [
            Record(data={"name": "Alice"}),
        ]

        is_valid, errors = SchemaValidator.validate_schema(records, schema)

        assert not is_valid
        assert len(errors) > 0


class TestConstraintValidator:
    """Test constraint validation."""

    def test_not_null_constraint(self):
        """Test NOT NULL constraint."""
        records = [
            Record(data={"id": 1, "name": "Alice"}),
            Record(data={"id": 2, "name": None}),
        ]

        result = ConstraintValidator.validate_not_null(records, "name")

        assert not result.passed
        assert result.failed_count == 1

    def test_unique_constraint(self):
        """Test UNIQUE constraint."""
        records = [
            Record(data={"id": 1, "email": "alice@example.com"}),
            Record(data={"id": 2, "email": "bob@example.com"}),
            Record(data={"id": 3, "email": "alice@example.com"}),
        ]

        result = ConstraintValidator.validate_unique(records, "email")

        assert not result.passed
        assert result.failed_count == 1

    def test_range_constraint(self):
        """Test range constraint."""
        records = [
            Record(data={"age": 25}),
            Record(data={"age": 35}),
            Record(data={"age": 150}),
        ]

        result = ConstraintValidator.validate_range(records, "age", 0, 120)

        assert not result.passed
        assert result.failed_count == 1

    def test_regex_pattern_constraint(self):
        """Test regex pattern constraint."""
        records = [
            Record(data={"email": "alice@example.com"}),
            Record(data={"email": "bob@example.com"}),
            Record(data={"email": "invalid"}),
        ]

        result = ConstraintValidator.validate_regex_pattern(records, "email", r".+@.+\..+")

        assert not result.passed
        assert result.failed_count == 1


class TestStatisticalQuality:
    """Test statistical quality checks."""

    def test_outlier_detection(self):
        """Test outlier detection."""
        records = [
            Record(data={"value": 10}),
            Record(data={"value": 12}),
            Record(data={"value": 11}),
            Record(data={"value": 100}),  # Outlier
        ]

        result = StatisticalQuality.detect_outliers(records, "value", method="iqr")

        assert not result.passed
        assert result.failed_count > 0

    def test_completeness_check(self):
        """Test completeness check."""
        records = [
            Record(data={"id": 1}),
            Record(data={"id": None}),
            Record(data={"id": 3}),
        ]

        result = StatisticalQuality.check_completeness(records, "id", min_threshold=0.9)

        # 2 out of 3 non-null = 66.7% < 90%
        assert not result.passed


class TestQualityRulesEngine:
    """Test quality rules engine."""

    def test_add_rules(self):
        """Test adding rules."""
        engine = QualityRulesEngine()

        engine.add_not_null_rule("id")
        engine.add_unique_rule("email")
        engine.add_range_rule("age", 0, 120)

        assert len(engine.rules) == 3

    def test_evaluate_rules(self):
        """Test evaluating rules."""
        records = [
            Record(data={"id": 1, "email": "alice@example.com", "age": 30}),
            Record(data={"id": None, "email": "bob@example.com", "age": 25}),
        ]

        engine = QualityRulesEngine()
        engine.add_not_null_rule("id")

        results = engine.evaluate(records)

        assert len(results) > 0
        assert not results[0].passed

    def test_quality_score(self):
        """Test quality score calculation."""
        records = [
            Record(data={"id": 1}),
            Record(data={"id": 2}),
        ]

        engine = QualityRulesEngine()
        engine.add_not_null_rule("id")

        engine.evaluate(records)
        score = engine.get_quality_score()

        assert score == 100.0

    def test_quality_report(self):
        """Test quality report generation."""
        records = [
            Record(data={"id": 1}),
            Record(data={"id": None}),
        ]

        engine = QualityRulesEngine()
        engine.add_not_null_rule("id")

        engine.evaluate(records)
        report = engine.generate_report()

        assert "total_checks" in report
        assert "quality_score" in report
        assert "results" in report


class TestDataProfiler:
    """Test data profiler."""

    def test_profile_field(self):
        """Test field profiling."""
        records = [
            Record(data={"age": 25}),
            Record(data={"age": 30}),
            Record(data={"age": 35}),
            Record(data={"age": None}),
        ]

        schema = Schema(
            fields=[
                Field(name="age", data_type=DataType.INTEGER),
            ]
        )

        profiles = DataProfiler.profile(records, schema)

        assert len(profiles) == 1
        profile = profiles[0]

        assert profile.field_name == "age"
        assert profile.record_count == 4
        assert profile.null_count == 1
        assert profile.distinct_count == 3

    def test_profile_statistics(self):
        """Test statistical profiling."""
        records = [
            Record(data={"value": 10}),
            Record(data={"value": 20}),
            Record(data={"value": 30}),
        ]

        schema = Schema(
            fields=[
                Field(name="value", data_type=DataType.INTEGER),
            ]
        )

        profiles = DataProfiler.profile(records, schema)
        profile = profiles[0]

        assert profile.min_value == 10
        assert profile.max_value == 30
        assert profile.mean_value == 20.0

    def test_profile_cardinality(self):
        """Test cardinality profiling."""
        records = [
            Record(data={"category": "A"}),
            Record(data={"category": "A"}),
            Record(data={"category": "B"}),
        ]

        schema = Schema(
            fields=[
                Field(name="category", data_type=DataType.STRING),
            ]
        )

        profiles = DataProfiler.profile(records, schema)
        profile = profiles[0]

        assert profile.distinct_count == 2
        assert profile.cardinality == 2 / 3


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
