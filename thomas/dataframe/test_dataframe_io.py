"""Tests for I/O operations."""

from _types import DType
from frame import DataFrame
from ioutils import CSVReader, CSVWriter, JSONHandler, MarkdownTable


class TestCSVReading:
    """Test CSV parsing."""

    def test_read_csv_basic(self) -> None:
        """Test basic CSV reading."""
        csv_data = "a,b,c\n1,2,3\n4,5,6"
        df = CSVReader.read_csv(csv_data)
        assert df.shape == (2, 3)
        assert "a" in df.columns

    def test_read_csv_no_header(self) -> None:
        """Test CSV without header."""
        csv_data = "1,2,3\n4,5,6"
        df = CSVReader.read_csv(csv_data, has_header=False)
        assert df.shape == (2, 3)
        assert "col_0" in df.columns

    def test_read_csv_with_quotes(self) -> None:
        """Test CSV with quoted fields."""
        csv_data = 'a,b\n"hello, world",test\n"value",data'
        df = CSVReader.read_csv(csv_data)
        assert df.shape == (2, 2)

    def test_read_csv_type_inference(self) -> None:
        """Test type inference."""
        csv_data = "a,b,c\n1,2.5,true\n2,3.5,false"
        df = CSVReader.read_csv(csv_data, infer_types=True)
        assert df["a"].dtype == DType.INT
        assert df["b"].dtype == DType.FLOAT
        assert df["c"].dtype == DType.BOOL

    def test_read_csv_with_nulls(self) -> None:
        """Test reading null values."""
        csv_data = "a,b\n1,2\n,4"
        df = CSVReader.read_csv(csv_data)
        assert df["a"][1] is None

    def test_read_csv_custom_delimiter(self) -> None:
        """Test custom delimiter."""
        csv_data = "a|b|c\n1|2|3"
        df = CSVReader.read_csv(csv_data, delimiter="|")
        assert df.shape == (1, 3)

    def test_read_csv_empty(self) -> None:
        """Test reading empty CSV."""
        csv_data = ""
        df = CSVReader.read_csv(csv_data)
        assert df.shape[0] == 0


class TestCSVWriting:
    """Test CSV writing."""

    def test_write_csv_basic(self) -> None:
        """Test basic CSV writing."""
        df = DataFrame({"a": [1, 2], "b": [3, 4]})
        csv_str = CSVWriter.write_csv(df)
        assert "a" in csv_str
        assert "b" in csv_str
        assert "1" in csv_str

    def test_write_csv_no_header(self) -> None:
        """Test CSV writing without header."""
        df = DataFrame({"a": [1, 2], "b": [3, 4]})
        csv_str = CSVWriter.write_csv(df, include_header=False)
        assert "a" not in csv_str

    def test_write_csv_with_index(self) -> None:
        """Test CSV writing with index."""
        df = DataFrame({"a": [1, 2]}, index=["x", "y"])
        csv_str = CSVWriter.write_csv(df, include_index=True)
        assert "index" in csv_str
        assert "x" in csv_str

    def test_write_csv_with_nulls(self) -> None:
        """Test writing nulls."""
        df = DataFrame({"a": [1, None, 3]})
        csv_str = CSVWriter.write_csv(df)
        assert csv_str.count("\n") == 4  # header + 3 rows


class TestJSONReading:
    """Test JSON reading."""

    def test_read_json_records(self) -> None:
        """Test reading JSON records format."""
        json_data = '[{"a": 1, "b": 2}, {"a": 3, "b": 4}]'
        df = JSONHandler.read_json(json_data, orient="records")
        assert df.shape == (2, 2)

    def test_read_json_dict(self) -> None:
        """Test reading JSON dict format."""
        json_data = '{"a": [1, 2], "b": [3, 4]}'
        df = JSONHandler.read_json(json_data, orient="dict")
        assert df.shape == (2, 2)

    def test_read_json_index(self) -> None:
        """Test reading JSON index format."""
        json_data = '{"row1": {"a": 1, "b": 2}, "row2": {"a": 3, "b": 4}}'
        df = JSONHandler.read_json(json_data, orient="index")
        assert df.shape[0] == 2


class TestJSONWriting:
    """Test JSON writing."""

    def test_write_json_records(self) -> None:
        """Test writing JSON records format."""
        df = DataFrame({"a": [1, 2], "b": [3, 4]})
        json_str = JSONHandler.write_json(df, orient="records")
        assert "[" in json_str
        assert '"a"' in json_str

    def test_write_json_dict(self) -> None:
        """Test writing JSON dict format."""
        df = DataFrame({"a": [1, 2], "b": [3, 4]})
        json_str = JSONHandler.write_json(df, orient="dict")
        assert '"a"' in json_str
        assert "[1" in json_str

    def test_write_json_index(self) -> None:
        """Test writing JSON index format."""
        df = DataFrame({"a": [1, 2]}, index=["x", "y"])
        json_str = JSONHandler.write_json(df, orient="index")
        assert '"x"' in json_str or "'x'" in json_str


class TestMarkdownTable:
    """Test Markdown table output."""

    def test_markdown_basic(self) -> None:
        """Test basic Markdown table."""
        df = DataFrame({"a": [1, 2], "b": [3, 4]})
        md = MarkdownTable.to_markdown(df)
        assert "|" in md
        assert "a" in md
        assert "b" in md

    def test_markdown_max_rows(self) -> None:
        """Test Markdown with max rows."""
        df = DataFrame({"a": list(range(100))})
        md = MarkdownTable.to_markdown(df, max_rows=5)
        assert "more rows" in md


class TestCSVRoundTrip:
    """Test round-trip CSV conversion."""

    def test_csv_roundtrip(self) -> None:
        """Test CSV write and read."""
        df = DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        csv_str = CSVWriter.write_csv(df)
        df2 = CSVReader.read_csv(csv_str)
        assert df2.shape == df.shape

    def test_csv_roundtrip_with_nulls(self) -> None:
        """Test roundtrip with nulls."""
        df = DataFrame({"a": [1, None, 3], "b": [4, 5, None]})
        csv_str = CSVWriter.write_csv(df)
        df2 = CSVReader.read_csv(csv_str)
        # Nulls become None
        assert len(df2) == len(df)


class TestJSONRoundTrip:
    """Test round-trip JSON conversion."""

    def test_json_roundtrip_records(self) -> None:
        """Test JSON roundtrip with records."""
        df = DataFrame({"a": [1, 2], "b": [3, 4]})
        json_str = JSONHandler.write_json(df, orient="records")
        df2 = JSONHandler.read_json(json_str, orient="records")
        assert df2.shape == df.shape

    def test_json_roundtrip_dict(self) -> None:
        """Test JSON roundtrip with dict."""
        df = DataFrame({"a": [1, 2], "b": [3, 4]})
        json_str = JSONHandler.write_json(df, orient="dict")
        df2 = JSONHandler.read_json(json_str, orient="dict")
        assert df2.shape == df.shape


class TestTypeInference:
    """Test type inference."""

    def test_infer_int(self) -> None:
        """Test integer inference."""
        csv_data = "a\n1\n2\n3"
        df = CSVReader.read_csv(csv_data)
        assert df["a"].dtype == DType.INT

    def test_infer_float(self) -> None:
        """Test float inference."""
        csv_data = "a\n1.5\n2.5\n3.5"
        df = CSVReader.read_csv(csv_data)
        assert df["a"].dtype == DType.FLOAT

    def test_infer_bool(self) -> None:
        """Test boolean inference."""
        csv_data = "a\ntrue\nfalse\ntrue"
        df = CSVReader.read_csv(csv_data)
        assert df["a"].dtype == DType.BOOL

    def test_infer_string(self) -> None:
        """Test string inference."""
        csv_data = "a\nhello\nworld\nfoo"
        df = CSVReader.read_csv(csv_data)
        assert df["a"].dtype == DType.STRING

    def test_infer_mixed_to_string(self) -> None:
        """Test mixed types fall back to string."""
        csv_data = "a\n1\nhello\n2.5"
        df = CSVReader.read_csv(csv_data, infer_types=True)
        assert df["a"].dtype == DType.STRING


class TestIOEdgeCases:
    """Test edge cases in I/O."""

    def test_csv_empty_fields(self) -> None:
        """Test CSV with empty fields."""
        csv_data = "a,b,c\n1,,3\n4,5,"
        df = CSVReader.read_csv(csv_data)
        assert df.shape == (2, 3)

    def test_json_empty(self) -> None:
        """Test empty JSON."""
        json_data = "[]"
        df = JSONHandler.read_json(json_data, orient="records")
        assert df.shape[0] == 0

    def test_csv_special_chars(self) -> None:
        """Test CSV with special characters."""
        csv_data = 'a,b\n"hello,world","test"\n"foo""bar",baz'
        df = CSVReader.read_csv(csv_data)
        assert df.shape[0] == 2

    def test_json_with_nulls(self) -> None:
        """Test JSON with null values."""
        json_data = '[{"a": 1, "b": null}, {"a": 2, "b": 4}]'
        df = JSONHandler.read_json(json_data, orient="records")
        assert df["b"][1] is None
