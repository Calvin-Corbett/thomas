"""
Tests for data transformations.
"""

from datetime import datetime

import pytest

from thomas.marketplace.data_pipeline._exceptions import TransformationError
from thomas.marketplace.data_pipeline._types import DataType, Field, JoinSpec, JoinType, Record, Schema
from thomas.marketplace.data_pipeline.transforms import (
    DateTransform,
    DeduplicationTransform,
    ExpressionEvaluatorTransform,
    FieldRenameTransform,
    FilterTransform,
    FlatMapTransform,
    LookupJoinTransform,
    MapTransform,
    NullHandlerTransform,
    PivotTransform,
    StringTransform,
    TypeCastTransform,
    UnpivotTransform,
)


class TestMapTransform:
    """Test map transformation."""

    def test_map_simple(self):
        """Test simple map."""
        record = Record(data={"x": 1, "y": 2})

        def add_z(r):
            r.set("z", r.get("x") + r.get("y"))
            return r

        transform = MapTransform(add_z)
        result = transform.transform(record)

        assert result.get("z") == 3

    def test_map_schema_preserved(self):
        """Test map preserves schema."""
        schema = Schema(fields=[Field(name="x", data_type=DataType.INTEGER)])
        transform = MapTransform(lambda r: r)
        result_schema = transform.get_output_schema(schema)

        assert result_schema == schema


class TestFlatMapTransform:
    """Test flat map transformation."""

    def test_flatmap_expand(self):
        """Test flatmap expansion."""
        record = Record(data={"id": 1, "values": [10, 20, 30]})

        def explode(r):
            records = []
            for val in r.get("values", []):
                new_record = Record(data={"id": r.get("id"), "value": val})
                records.append(new_record)
            return records

        transform = FlatMapTransform(explode)
        results = transform.transform(record)

        assert len(results) == 3
        assert results[0].get("value") == 10


class TestFilterTransform:
    """Test filter transformation."""

    def test_filter_predicate(self):
        """Test filtering."""
        record1 = Record(data={"age": 25})
        record2 = Record(data={"age": 35})

        transform = FilterTransform(lambda r: r.get("age") > 30)

        assert transform.transform(record1) is None
        assert transform.transform(record2) is not None


class TestFieldRenameTransform:
    """Test field rename transformation."""

    def test_rename_fields(self):
        """Test renaming fields."""
        record = Record(data={"old_name": "Alice", "age": 30})
        transform = FieldRenameTransform({"old_name": "new_name"})

        result = transform.transform(record)

        assert result.get("new_name") == "Alice"
        assert result.get("old_name") is None

    def test_rename_schema(self):
        """Test schema after rename."""
        schema = Schema(
            fields=[
                Field(name="old_col", data_type=DataType.STRING),
            ]
        )
        transform = FieldRenameTransform({"old_col": "new_col"})
        result_schema = transform.get_output_schema(schema)

        assert result_schema.get_field("new_col") is not None
        assert result_schema.get_field("old_col") is None


class TestTypeCastTransform:
    """Test type casting transformation."""

    def test_cast_to_integer(self):
        """Test casting to integer."""
        record = Record(data={"value": "42"})
        transform = TypeCastTransform({"value": DataType.INTEGER})

        result = transform.transform(record)

        assert result.get("value") == 42
        assert isinstance(result.get("value"), int)

    def test_cast_to_float(self):
        """Test casting to float."""
        record = Record(data={"price": "19.99"})
        transform = TypeCastTransform({"price": DataType.FLOAT})

        result = transform.transform(record)

        assert result.get("price") == 19.99

    def test_cast_to_boolean(self):
        """Test casting to boolean."""
        record = Record(data={"active": "true"})
        transform = TypeCastTransform({"active": DataType.BOOLEAN})

        result = transform.transform(record)

        assert result.get("active") is True


class TestNullHandlerTransform:
    """Test null handling transformation."""

    def test_drop_nulls(self):
        """Test dropping records with nulls."""
        record1 = Record(data={"id": 1, "name": "Alice"})
        record2 = Record(data={"id": 2, "name": None})

        transform = NullHandlerTransform(mode="drop")

        assert transform.transform(record1) is not None
        assert transform.transform(record2) is None

    def test_fill_nulls(self):
        """Test filling nulls."""
        record = Record(data={"id": 1, "name": None})
        transform = NullHandlerTransform(mode="fill", fill_value="Unknown")

        result = transform.transform(record)

        assert result.get("name") == "Unknown"

    def test_coalesce(self):
        """Test coalesce."""
        record = Record(data={"primary": None, "backup": "backup_value"})
        transform = NullHandlerTransform(mode="coalesce", coalesce_fields={"primary": ["primary", "backup"]})

        result = transform.transform(record)

        assert result.get("primary") == "backup_value"


class TestStringTransform:
    """Test string transformation."""

    def test_trim(self):
        """Test trim operation."""
        record = Record(data={"text": "  hello  "})
        transform = StringTransform({"text": {"op": "trim"}})

        result = transform.transform(record)

        assert result.get("text") == "hello"

    def test_uppercase(self):
        """Test uppercase operation."""
        record = Record(data={"text": "hello"})
        transform = StringTransform({"text": {"op": "uppercase"}})

        result = transform.transform(record)

        assert result.get("text") == "HELLO"

    def test_split(self):
        """Test split operation."""
        record = Record(data={"text": "a,b,c"})
        transform = StringTransform({"text": {"op": "split", "delimiter": ","}})

        result = transform.transform(record)

        assert result.get("text") == ["a", "b", "c"]


class TestDateTransform:
    """Test date transformation."""

    def test_parse_date(self):
        """Test parsing date string."""
        record = Record(data={"date_str": "2023-01-15"})
        transform = DateTransform(parse_fields={"date_str": "%Y-%m-%d"})

        result = transform.transform(record)

        assert isinstance(result.get("date_str"), datetime)

    def test_format_date(self):
        """Test formatting date."""
        dt = datetime(2023, 1, 15)
        record = Record(data={"date": dt})
        transform = DateTransform(format_fields={"date": "%Y-%m-%d"})

        result = transform.transform(record)

        assert result.get("date") == "2023-01-15"


class TestExpressionEvaluatorTransform:
    """Test expression evaluator transformation."""

    def test_arithmetic_expression(self):
        """Test arithmetic expression."""
        record = Record(data={"a": 10, "b": 5})
        transform = ExpressionEvaluatorTransform({"result": "a + b * 2"})

        result = transform.transform(record)

        assert result.get("result") == 20

    def test_function_expression(self):
        """Test function in expression."""
        record = Record(data={"value": 9})
        transform = ExpressionEvaluatorTransform({"sqrt_value": "sqrt(value)"})

        result = transform.transform(record)

        assert result.get("sqrt_value") == 3.0

    def test_disallows_unsafe_expression(self):
        """Test unsafe expression rejection."""
        record = Record(data={"value": 9})
        transform = ExpressionEvaluatorTransform({"bad": "__import__('os').system('echo nope')"})

        with pytest.raises(TransformationError):
            transform.transform(record)


class TestLookupJoinTransform:
    """Test lookup join transformation."""

    def test_lookup_join(self):
        """Test lookup join."""
        lookup_data = {
            "Alice": Record(data={"dept": "Engineering"}),
            "Bob": Record(data={"dept": "Sales"}),
        }

        record = Record(data={"name": "Alice", "salary": 100000})
        transform = LookupJoinTransform(lookup_data, "name", "name")

        result = transform.transform(record)

        assert result.get("dept") == "Engineering"

    def test_lookup_join_missing(self):
        """Test lookup join with missing value."""
        lookup_data = {"Alice": Record(data={"dept": "Engineering"})}
        record = Record(data={"name": "Bob", "salary": 100000})

        join_spec = JoinSpec("name", "name", join_type=JoinType.LEFT)
        transform = LookupJoinTransform(lookup_data, "name", "name", join_spec)

        result = transform.transform(record)

        # Left join should keep the record
        assert result is not None


class TestPivotTransform:
    """Test pivot transformation."""

    def test_pivot(self):
        """Test pivoting data."""
        records = [
            Record(data={"id": 1, "month": "Jan", "sales": 100}),
            Record(data={"id": 1, "month": "Feb", "sales": 200}),
            Record(data={"id": 1, "month": "Mar", "sales": 150}),
        ]

        transform = PivotTransform(index_columns=["id"], pivot_column="month", value_column="sales")

        for record in records:
            transform.add_record(record)

        pivoted = transform.get_pivoted_records()

        assert len(pivoted) == 1
        assert pivoted[0].get("Jan") == 100
        assert pivoted[0].get("Feb") == 200


class TestUnpivotTransform:
    """Test unpivot transformation."""

    def test_unpivot(self):
        """Test unpivoting data."""
        record = Record(
            data={
                "id": 1,
                "Jan": 100,
                "Feb": 200,
                "Mar": 150,
            }
        )

        transform = UnpivotTransform(
            id_vars=["id"], value_vars=["Jan", "Feb", "Mar"], var_name="month", value_name="sales"
        )

        results = transform.transform(record)

        assert len(results) == 3
        assert results[0].get("month") == "Jan"
        assert results[0].get("sales") == 100


class TestDeduplicationTransform:
    """Test deduplication transformation."""

    def test_deduplication(self):
        """Test removing duplicates."""
        records = [
            Record(data={"id": 1, "name": "Alice"}),
            Record(data={"id": 1, "name": "Alice"}),
            Record(data={"id": 2, "name": "Bob"}),
        ]

        transform = DeduplicationTransform()

        for record in records:
            transform.add_record(record)

        deduplicated = transform.get_deduplicated()

        assert len(deduplicated) == 2


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
