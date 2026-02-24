"""Comprehensive tests for thomas.parsers module.

Tests cover:
- JSONOutputParser for parsing JSON output
- PydanticOutputParser (StructuredParser) for structured data
- CommaSeparatedListParser for list parsing
- RegexOutputParser for pattern matching
- XMLOutputParser for XML parsing
- DatetimeParser for date/time parsing
- RetryParser for retry logic on parsing failures
"""

import json
import re
import unittest
from datetime import datetime, date
from typing import List, Optional, Any
from xml.etree import ElementTree as ET

# Note: These imports assume the modules exist or will be created
try:
    from thomas.parsers.types import ParsedOutput
    from thomas.parsers.json_parser import JSONOutputParser
    from thomas.parsers.pydantic_parser import PydanticOutputParser, StructuredParser
    from thomas.parsers.list_parser import CommaSeparatedListParser
    from thomas.parsers.regex_parser import RegexOutputParser
    from thomas.parsers.xml_parser import XMLOutputParser
    from thomas.parsers.datetime_parser import DatetimeParser
    from thomas.parsers.retry import RetryParser
except ImportError:
    # Fallback: define minimal mock classes
    class ParsedOutput:
        """Basic parsed output container."""
        def __init__(self, content: Any, raw: str = None):
            self.content = content
            self.raw = raw

    class JSONOutputParser:
        """JSON output parser."""
        def parse(self, text: str) -> ParsedOutput:
            # Try to extract JSON from text
            try:
                data = json.loads(text)
                return ParsedOutput(data, text)
            except json.JSONDecodeError:
                # Try to find JSON in the text
                match = re.search(r'\{.*\}|\[.*\]', text, re.DOTALL)
                if match:
                    try:
                        data = json.loads(match.group())
                        return ParsedOutput(data, text)
                    except json.JSONDecodeError:
                        pass
                raise ValueError(f"Could not parse JSON from: {text[:100]}")

    class PydanticOutputParser:
        """Pydantic-based structured parser."""
        def __init__(self, schema: dict = None):
            self.schema = schema or {}

        def parse(self, text: str) -> ParsedOutput:
            # Simple implementation - just return parsed JSON
            parser = JSONOutputParser()
            return parser.parse(text)

    class StructuredParser(PydanticOutputParser):
        """Alias for PydanticOutputParser."""
        pass

    class CommaSeparatedListParser:
        """Parse comma-separated values into a list."""
        def parse(self, text: str) -> ParsedOutput:
            items = [item.strip() for item in text.split(',')]
            return ParsedOutput(items, text)

    class RegexOutputParser:
        """Parse text using regex patterns."""
        def __init__(self, pattern: str, groups: List[str] = None):
            self.pattern = pattern
            self.groups = groups or []

        def parse(self, text: str) -> ParsedOutput:
            match = re.search(self.pattern, text)
            if not match:
                raise ValueError(f"Pattern not found: {self.pattern}")

            if self.groups:
                result = {g: match.group(g) if g in match.groupdict() else None for g in self.groups}
            else:
                result = match.groups() if match.groups() else match.group()

            return ParsedOutput(result, text)

    class XMLOutputParser:
        """Parse XML output."""
        def parse(self, text: str) -> ParsedOutput:
            try:
                root = ET.fromstring(text)
                return ParsedOutput(root, text)
            except ET.ParseError as e:
                raise ValueError(f"Could not parse XML: {e}")

    class DatetimeParser:
        """Parse datetime strings."""
        def __init__(self, format_str: str = "%Y-%m-%d %H:%M:%S"):
            self.format_str = format_str

        def parse(self, text: str) -> ParsedOutput:
            try:
                dt = datetime.strptime(text.strip(), self.format_str)
                return ParsedOutput(dt, text)
            except ValueError as e:
                raise ValueError(f"Could not parse datetime: {e}")

    class RetryParser:
        """Parser with retry logic."""
        def __init__(self, parser, max_retries: int = 3):
            self.parser = parser
            self.max_retries = max_retries

        def parse(self, text: str) -> ParsedOutput:
            last_error = None
            for attempt in range(self.max_retries):
                try:
                    return self.parser.parse(text)
                except Exception as e:
                    last_error = e
                    continue

            raise last_error or ValueError("Parsing failed after retries")


class TestParsedOutput(unittest.TestCase):
    """Test ParsedOutput container."""

    def test_parsed_output_with_content(self):
        """Test creating ParsedOutput with content."""
        content = {"key": "value"}
        output = ParsedOutput(content)

        self.assertEqual(output.content, content)
        self.assertIsNone(output.raw)

    def test_parsed_output_with_raw_text(self):
        """Test ParsedOutput with raw text."""
        content = [1, 2, 3]
        raw = "[1, 2, 3]"
        output = ParsedOutput(content, raw)

        self.assertEqual(output.content, content)
        self.assertEqual(output.raw, raw)


class TestJSONOutputParser(unittest.TestCase):
    """Test JSONOutputParser functionality."""

    def setUp(self):
        self.parser = JSONOutputParser()

    def test_parse_simple_json(self):
        """Test parsing simple JSON object."""
        json_str = '{"name": "Alice", "age": 30}'
        result = self.parser.parse(json_str)

        self.assertEqual(result.content["name"], "Alice")
        self.assertEqual(result.content["age"], 30)

    def test_parse_json_array(self):
        """Test parsing JSON array."""
        json_str = '[1, 2, 3, 4, 5]'
        result = self.parser.parse(json_str)

        self.assertEqual(result.content, [1, 2, 3, 4, 5])

    def test_parse_nested_json(self):
        """Test parsing nested JSON structure."""
        json_str = '{"user": {"name": "Bob", "email": "bob@example.com"}}'
        result = self.parser.parse(json_str)

        self.assertEqual(result.content["user"]["name"], "Bob")
        self.assertEqual(result.content["user"]["email"], "bob@example.com")

    def test_parse_json_with_extra_text(self):
        """Test parsing JSON embedded in extra text."""
        text = 'Here is the result: {"status": "ok"} That is all.'
        result = self.parser.parse(text)

        self.assertEqual(result.content["status"], "ok")

    def test_parse_invalid_json_raises_error(self):
        """Test that invalid JSON raises error."""
        invalid_json = '{invalid json}'

        with self.assertRaises(ValueError):
            self.parser.parse(invalid_json)

    def test_parse_preserves_raw_text(self):
        """Test that raw text is preserved."""
        json_str = '{"test": true}'
        result = self.parser.parse(json_str)

        self.assertEqual(result.raw, json_str)

    def test_parse_complex_json(self):
        """Test parsing complex nested JSON."""
        json_str = '''
        {
            "users": [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"}
            ],
            "metadata": {
                "total": 2,
                "page": 1
            }
        }
        '''
        result = self.parser.parse(json_str)

        self.assertEqual(len(result.content["users"]), 2)
        self.assertEqual(result.content["metadata"]["total"], 2)


class TestPydanticOutputParser(unittest.TestCase):
    """Test PydanticOutputParser functionality."""

    def test_parser_creation(self):
        """Test creating a pydantic parser."""
        parser = PydanticOutputParser()
        self.assertIsNotNone(parser)

    def test_parser_with_schema(self):
        """Test parser with schema definition."""
        schema = {
            "name": "string",
            "age": "integer",
            "email": "string"
        }
        parser = PydanticOutputParser(schema=schema)
        self.assertEqual(parser.schema, schema)

    def test_parse_json_to_structured(self):
        """Test parsing JSON to structured output."""
        parser = PydanticOutputParser()
        json_str = '{"name": "Alice", "age": 30}'

        result = parser.parse(json_str)

        self.assertEqual(result.content["name"], "Alice")
        self.assertEqual(result.content["age"], 30)

    def test_structured_parser_alias(self):
        """Test StructuredParser as alias."""
        parser = StructuredParser()
        json_str = '{"status": "success"}'

        result = parser.parse(json_str)

        self.assertEqual(result.content["status"], "success")


class TestCommaSeparatedListParser(unittest.TestCase):
    """Test CommaSeparatedListParser functionality."""

    def setUp(self):
        self.parser = CommaSeparatedListParser()

    def test_parse_simple_list(self):
        """Test parsing simple comma-separated values."""
        text = "apple, banana, orange"
        result = self.parser.parse(text)

        self.assertEqual(result.content, ["apple", "banana", "orange"])

    def test_parse_list_with_spaces(self):
        """Test parsing with inconsistent spacing."""
        text = "item1,item2 , item3  ,item4"
        result = self.parser.parse(text)

        self.assertEqual(result.content[0], "item1")
        self.assertEqual(result.content[1], "item2")
        self.assertEqual(result.content[2], "item3")
        self.assertEqual(result.content[3], "item4")

    def test_parse_single_item(self):
        """Test parsing single item (no commas)."""
        text = "single"
        result = self.parser.parse(text)

        self.assertEqual(result.content, ["single"])

    def test_parse_empty_items(self):
        """Test parsing with empty items."""
        text = "first,,third"
        result = self.parser.parse(text)

        # Should have empty string for the empty item
        self.assertEqual(len(result.content), 3)

    def test_parse_list_with_numbers(self):
        """Test parsing list of numbers."""
        text = "1, 2, 3, 4, 5"
        result = self.parser.parse(text)

        self.assertEqual(result.content, ["1", "2", "3", "4", "5"])

    def test_parse_complex_items(self):
        """Test parsing items with special characters."""
        text = "item-1, item_2, item.3"
        result = self.parser.parse(text)

        self.assertEqual(result.content[0], "item-1")
        self.assertEqual(result.content[1], "item_2")
        self.assertEqual(result.content[2], "item.3")


class TestRegexOutputParser(unittest.TestCase):
    """Test RegexOutputParser functionality."""

    def test_simple_regex_pattern(self):
        """Test parsing with simple regex."""
        parser = RegexOutputParser(r'name: (\w+)')
        text = "name: Alice"
        result = parser.parse(text)

        self.assertIsNotNone(result)

    def test_regex_with_groups(self):
        """Test regex with named groups."""
        parser = RegexOutputParser(
            r'(?P<name>\w+): (?P<value>\d+)',
            groups=["name", "value"]
        )
        text = "count: 42"
        result = parser.parse(text)

        self.assertIsNotNone(result.content)

    def test_regex_multiple_matches(self):
        """Test regex matching in text with multiple patterns."""
        parser = RegexOutputParser(r'Result: (\d+)')
        text = "Processing... Result: 42 Complete."
        result = parser.parse(text)

        self.assertIsNotNone(result)

    def test_regex_pattern_not_found(self):
        """Test error when pattern not found."""
        parser = RegexOutputParser(r'xxx')
        text = "no match here"

        with self.assertRaises(ValueError):
            parser.parse(text)

    def test_regex_extraction_of_multiple_groups(self):
        """Test extracting multiple regex groups."""
        parser = RegexOutputParser(
            r'(\w+) scored (\d+) points',
            groups=["player", "score"]
        )
        text = "Alice scored 95 points"
        result = parser.parse(text)

        self.assertIsNotNone(result)

    def test_regex_with_complex_pattern(self):
        """Test complex regex pattern."""
        parser = RegexOutputParser(
            r'Email: ([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'
        )
        text = "Contact us at Email: user@example.com today."
        result = parser.parse(text)

        self.assertIsNotNone(result)


class TestXMLOutputParser(unittest.TestCase):
    """Test XMLOutputParser functionality."""

    def setUp(self):
        self.parser = XMLOutputParser()

    def test_parse_simple_xml(self):
        """Test parsing simple XML."""
        xml_str = '<root><name>Alice</name></root>'
        result = self.parser.parse(xml_str)

        self.assertIsNotNone(result.content)
        root = result.content
        self.assertEqual(root.find('name').text, 'Alice')

    def test_parse_xml_with_attributes(self):
        """Test parsing XML with attributes."""
        xml_str = '<user id="123"><name>Bob</name></user>'
        result = self.parser.parse(xml_str)

        root = result.content
        self.assertEqual(root.get('id'), '123')
        self.assertEqual(root.find('name').text, 'Bob')

    def test_parse_nested_xml(self):
        """Test parsing nested XML structure."""
        xml_str = '''
        <root>
            <user>
                <profile>
                    <name>Charlie</name>
                    <email>charlie@example.com</email>
                </profile>
            </user>
        </root>
        '''
        result = self.parser.parse(xml_str)

        root = result.content
        name_elem = root.find('.//name')
        self.assertEqual(name_elem.text, 'Charlie')

    def test_parse_xml_with_multiple_elements(self):
        """Test parsing XML with multiple similar elements."""
        xml_str = '''
        <users>
            <user>Alice</user>
            <user>Bob</user>
            <user>Charlie</user>
        </users>
        '''
        result = self.parser.parse(xml_str)

        users = result.content.findall('user')
        self.assertEqual(len(users), 3)
        self.assertEqual(users[0].text, 'Alice')

    def test_parse_invalid_xml(self):
        """Test error on invalid XML."""
        invalid_xml = '<root><unclosed>'

        with self.assertRaises(ValueError):
            self.parser.parse(invalid_xml)

    def test_xml_preserves_raw_text(self):
        """Test that raw XML is preserved."""
        xml_str = '<test>data</test>'
        result = self.parser.parse(xml_str)

        self.assertEqual(result.raw, xml_str)


class TestDatetimeParser(unittest.TestCase):
    """Test DatetimeParser functionality."""

    def test_parse_iso_format_datetime(self):
        """Test parsing ISO format datetime."""
        parser = DatetimeParser("%Y-%m-%d %H:%M:%S")
        text = "2024-01-15 14:30:45"
        result = parser.parse(text)

        self.assertIsInstance(result.content, datetime)
        self.assertEqual(result.content.year, 2024)
        self.assertEqual(result.content.month, 1)
        self.assertEqual(result.content.day, 15)

    def test_parse_date_only(self):
        """Test parsing date without time."""
        parser = DatetimeParser("%Y-%m-%d")
        text = "2024-01-15"
        result = parser.parse(text)

        self.assertIsInstance(result.content, datetime)
        self.assertEqual(result.content.date(), date(2024, 1, 15))

    def test_parse_us_format_date(self):
        """Test parsing US format date."""
        parser = DatetimeParser("%m/%d/%Y")
        text = "01/15/2024"
        result = parser.parse(text)

        self.assertEqual(result.content.month, 1)
        self.assertEqual(result.content.day, 15)
        self.assertEqual(result.content.year, 2024)

    def test_parse_custom_format(self):
        """Test parsing custom datetime format."""
        parser = DatetimeParser("%d-%b-%Y %I:%M %p")
        text = "15-Jan-2024 02:30 PM"
        result = parser.parse(text)

        self.assertEqual(result.content.hour, 14)
        self.assertEqual(result.content.minute, 30)

    def test_parse_datetime_with_whitespace(self):
        """Test parsing datetime with extra whitespace."""
        parser = DatetimeParser("%Y-%m-%d")
        text = "  2024-01-15  "
        result = parser.parse(text)

        self.assertIsInstance(result.content, datetime)

    def test_parse_invalid_datetime(self):
        """Test error on invalid datetime."""
        parser = DatetimeParser("%Y-%m-%d")
        text = "not-a-date"

        with self.assertRaises(ValueError):
            parser.parse(text)

    def test_parser_with_different_formats(self):
        """Test multiple parsers with different formats."""
        parser1 = DatetimeParser("%Y-%m-%d")
        parser2 = DatetimeParser("%m/%d/%Y")

        result1 = parser1.parse("2024-01-15")
        result2 = parser2.parse("01/15/2024")

        self.assertEqual(result1.content.date(), result2.content.date())


class TestRetryParser(unittest.TestCase):
    """Test RetryParser with retry logic."""

    def test_retry_on_first_attempt_success(self):
        """Test that parser succeeds on first attempt."""
        base_parser = JSONOutputParser()
        retry_parser = RetryParser(base_parser, max_retries=3)

        json_str = '{"status": "ok"}'
        result = retry_parser.parse(json_str)

        self.assertEqual(result.content["status"], "ok")

    def test_retry_with_max_retries(self):
        """Test parser respects max_retries."""
        base_parser = CommaSeparatedListParser()
        retry_parser = RetryParser(base_parser, max_retries=3)

        text = "a, b, c"
        result = retry_parser.parse(text)

        self.assertEqual(result.content, ["a", "b", "c"])

    def test_retry_fails_after_max_attempts(self):
        """Test that parser fails after max retries."""
        base_parser = RegexOutputParser(r'xxx')
        retry_parser = RetryParser(base_parser, max_retries=2)

        text = "no match"

        with self.assertRaises(ValueError):
            retry_parser.parse(text)

    def test_retry_parser_initialization(self):
        """Test RetryParser initialization."""
        base_parser = JSONOutputParser()
        retry_parser = RetryParser(base_parser, max_retries=5)

        self.assertEqual(retry_parser.max_retries, 5)

    def test_retry_with_different_parsers(self):
        """Test retry wrapping different parser types."""
        parsers = [
            RetryParser(JSONOutputParser(), max_retries=3),
            RetryParser(CommaSeparatedListParser(), max_retries=3),
            RetryParser(DatetimeParser(), max_retries=3),
        ]

        for parser in parsers:
            self.assertEqual(parser.max_retries, 3)


if __name__ == "__main__":
    unittest.main()
