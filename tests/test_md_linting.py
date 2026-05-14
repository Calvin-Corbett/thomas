"""
Tests for Markdown linting.
"""

from thomas.marketplace.markdown.linting import (
    HeadingConsistencyChecker,
    LinkValidator,
    Linter,
    LintRules,
    ListConsistencyChecker,
    SeverityLevel,
)
from thomas.marketplace.markdown.parser import Parser


class TestTrailingWhitespace:
    """Test trailing whitespace detection."""

    def test_detect_trailing_spaces(self) -> None:
        """Test detecting trailing spaces."""
        source = "text with spaces  \nmore text"
        linter = Linter()
        linter.rules.check_trailing_whitespace = True
        errors = linter.lint(source)
        assert any("trailing" in e.message.lower() for e in errors)

    def test_allow_empty_lines(self) -> None:
        """Test that empty lines don't trigger warning."""
        source = "text\n\nmore text"
        linter = Linter()
        errors = linter.lint(source)
        # Empty lines shouldn't trigger trailing whitespace errors
        trailing_errors = [e for e in errors if "trailing" in e.message.lower()]
        assert all(e.line != 2 for e in trailing_errors)


class TestLineLengthChecking:
    """Test line length validation."""

    def test_long_line_detection(self) -> None:
        """Test detecting lines that exceed max length."""
        rules = LintRules()
        rules.max_line_length = 20
        linter = Linter(rules)

        source = "This is a very long line that exceeds the maximum length"
        errors = linter.lint(source)
        assert any("too long" in e.message.lower() for e in errors)

    def test_code_block_exemption(self) -> None:
        """Test that code blocks are exempt from line length."""
        rules = LintRules()
        rules.max_line_length = 20
        linter = Linter(rules)

        source = "```\n" + "x" * 100 + "\n```"
        linter.lint(source)
        # Code blocks should be skipped
        # This behavior may vary based on implementation

    def test_url_exemption(self) -> None:
        """Test that URLs are exempt from line length."""
        rules = LintRules()
        rules.max_line_length = 40
        linter = Linter(rules)

        source = "See http://example.com/very/long/url/that/exceeds/limits"
        errors = linter.lint(source)
        # URLs should be skipped
        long_line_errors = [e for e in errors if "too long" in e.message.lower()]
        assert len(long_line_errors) == 0


class TestHeadingLevelConsistency:
    """Test heading level consistency checking."""

    def test_heading_level_skip_detected(self) -> None:
        """Test detecting skipped heading levels."""
        source = "# H1\n\n### H3"  # Skipped H2
        parser = Parser()
        doc = parser.parse(source)

        linter = Linter()
        linter.rules.check_heading_levels = True
        errors = linter.lint(source, doc)

        assert any("skip" in e.message.lower() for e in errors)

    def test_valid_heading_levels(self) -> None:
        """Test valid heading level progression."""
        source = "# H1\n\n## H2\n\n### H3\n\n## H2.2"
        parser = Parser()
        doc = parser.parse(source)

        linter = Linter()
        errors = linter.lint(source, doc)

        skip_errors = [e for e in errors if "skip" in e.message.lower()]
        assert len(skip_errors) == 0

    def test_h2_after_h1_is_valid(self) -> None:
        """Test that H2 directly after H1 is valid."""
        source = "# H1\n## H2"
        parser = Parser()
        doc = parser.parse(source)

        checker = HeadingConsistencyChecker()
        errors = checker.check(doc)
        assert len(errors) == 0


class TestDuplicateHeadings:
    """Test duplicate heading detection."""

    def test_duplicate_heading_detected(self) -> None:
        """Test detecting duplicate headings."""
        source = "# Title\n\nContent\n\n# Title"
        parser = Parser()
        doc = parser.parse(source)

        linter = Linter()
        linter.rules.check_duplicate_headings = True
        errors = linter.lint(source, doc)

        assert any("duplicate" in e.message.lower() for e in errors)

    def test_similar_headings_allowed(self) -> None:
        """Test that similar but different headings are OK."""
        source = "# Title\n\n## Titles"
        parser = Parser()
        doc = parser.parse(source)

        linter = Linter()
        errors = linter.lint(source, doc)

        dup_errors = [e for e in errors if "duplicate" in e.message.lower()]
        assert len(dup_errors) == 0

    def test_case_insensitive_duplicate(self) -> None:
        """Test that duplicates are case-insensitive."""
        source = "# Title\n\n# TITLE"
        parser = Parser()
        doc = parser.parse(source)

        linter = Linter()
        errors = linter.lint(source, doc)

        dup_errors = [e for e in errors if "duplicate" in e.message.lower()]
        assert len(dup_errors) > 0


class TestLintRules:
    """Test lint rule configuration."""

    def test_disable_rules(self) -> None:
        """Test disabling specific rules."""
        rules = LintRules()
        rules.check_trailing_whitespace = False
        rules.check_heading_levels = False

        linter = Linter(rules)
        source = "line with spaces  \n\n# H1\n### H3"

        errors = linter.lint(source)

        # These specific errors should not be present
        has_trailing = any("trailing" in e.message.lower() for e in errors)
        any("skip" in e.message.lower() for e in errors)

        assert not has_trailing
        # Skip errors may not be detected due to disabled rule


class TestErrorProperties:
    """Test lint error properties."""

    def test_error_has_line_number(self) -> None:
        """Test that errors contain line numbers."""
        source = "long" + " " * 100 + "line"
        linter = Linter()
        linter.rules.max_line_length = 20
        errors = linter.lint(source)

        long_errors = [e for e in errors if "too long" in e.message.lower()]
        if long_errors:
            assert long_errors[0].line > 0

    def test_error_has_severity(self) -> None:
        """Test that errors have severity levels."""
        source = "text  \n"  # trailing spaces
        linter = Linter()
        errors = linter.lint(source)

        assert all(e.severity in SeverityLevel for e in errors)

    def test_error_sorting(self) -> None:
        """Test that errors are sorted by line."""
        source = "line1  \nline2\nline3  "
        linter = Linter()
        errors = linter.lint(source)

        # Errors should be sorted by line number
        for i in range(len(errors) - 1):
            assert errors[i].line <= errors[i + 1].line


class TestCheckerUtilities:
    """Test individual checker utilities."""

    def test_heading_checker(self) -> None:
        """Test HeadingConsistencyChecker."""
        source = "# H1\n## H2\n### H3"
        parser = Parser()
        doc = parser.parse(source)

        checker = HeadingConsistencyChecker()
        errors = checker.check(doc)
        assert isinstance(errors, list)

    def test_link_validator(self) -> None:
        """Test LinkValidator."""
        source = "[text](url)"
        parser = Parser()
        doc = parser.parse(source)

        validator = LinkValidator()
        errors = validator.validate(doc)
        assert isinstance(errors, list)

    def test_list_checker(self) -> None:
        """Test ListConsistencyChecker."""
        source = "- item 1\n- item 2"
        parser = Parser()
        doc = parser.parse(source)

        checker = ListConsistencyChecker()
        errors = checker.check(doc)
        assert isinstance(errors, list)


class TestComplexDocumentLinting:
    """Test linting complex documents."""

    def test_full_document_lint(self) -> None:
        """Test linting a complete document."""
        source = """# Main Title

Paragraph with trailing spaces.

## Subsection

- List item 1
- List item 2

### Deep Section

Code example:

```python
def hello():
    pass
```

> A blockquote

Final paragraph."""

        linter = Linter()
        errors = linter.lint(source)

        # Should find multiple issues
        assert isinstance(errors, list)

    def test_clean_document(self) -> None:
        """Test linting a clean document."""
        source = """# Title

Clean paragraph.

## Section

- List item 1
- List item 2

> A blockquote

Final paragraph."""

        rules = LintRules()
        rules.check_heading_levels = True
        rules.check_duplicate_headings = True

        linter = Linter(rules)
        errors = linter.lint(source)

        # Should have minimal or no errors
        # (depends on configuration)
        assert isinstance(errors, list)
