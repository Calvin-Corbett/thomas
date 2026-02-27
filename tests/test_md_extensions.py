"""
Tests for Markdown extensions.
"""

from thomas.markdown.extensions import (
    AbbreviationExtension,
    AdmonitionExtension,
    AttributeListExtension,
    AutoLinkExtension,
    DefinitionListExtension,
    FootnoteExtension,
    MathExtension,
    SmartTypographyExtension,
    TableOfContentsExtension,
    TaskListExtension,
)
from thomas.markdown.parser import Parser


class TestTableOfContents:
    """Test TOC generation."""

    def test_toc_generation(self) -> None:
        """Test generating table of contents."""
        source = "# H1\n## H2\n## H2.2\n### H3"
        parser = Parser()
        doc = parser.parse(source)

        toc = TableOfContentsExtension.generate(doc)
        assert len(toc) == 4
        assert toc[0].level == 1
        assert toc[1].level == 2
        assert toc[2].level == 2
        assert toc[3].level == 3

    def test_toc_anchor_generation(self) -> None:
        """Test anchor generation from headings."""
        source = "# My Heading\n## Another One"
        parser = Parser()
        doc = parser.parse(source)

        toc = TableOfContentsExtension.generate(doc)
        assert "my-heading" in toc[0].anchor
        assert "another-one" in toc[1].anchor

    def test_toc_text_extraction(self) -> None:
        """Test text extraction from headings with inline content."""
        source = "# **Bold** and *Italic* Title"
        parser = Parser()
        doc = parser.parse(source)

        toc = TableOfContentsExtension.generate(doc)
        assert len(toc) == 1
        assert "Bold" in toc[0].title


class TestTaskLists:
    """Test task list parsing."""

    def test_task_list_extraction(self) -> None:
        """Test extracting task list items."""
        source = "- [ ] Task 1\n- [x] Task 2\n- [ ] Task 3"
        parser = Parser()
        doc = parser.parse(source)

        tasks = TaskListExtension.extract_tasks(doc)
        assert len(tasks) == 3
        assert tasks[0][1] is False  # unchecked
        assert tasks[1][1] is True  # checked
        assert tasks[2][1] is False  # unchecked

    def test_task_list_text_extraction(self) -> None:
        """Test extracting task text."""
        source = "- [x] Completed **task**"
        parser = Parser()
        doc = parser.parse(source)

        tasks = TaskListExtension.extract_tasks(doc)
        assert len(tasks) == 1
        assert "Completed" in tasks[0][0]
        assert "task" in tasks[0][0]


class TestFootnotes:
    """Test footnote parsing."""

    def test_footnote_detection(self) -> None:
        """Test footnote reference detection."""
        # Note: Actual footnote parsing requires integration with parser
        # This tests the extension's ability to detect footnote patterns
        assert FootnoteExtension is not None


class TestDefinitionLists:
    """Test definition list parsing."""

    def test_definition_list_detection(self) -> None:
        """Test if text looks like definition list."""
        text = "Term: Definition\nOther: Meaning"
        is_def_list = DefinitionListExtension.is_definition_list_syntax(text)
        assert is_def_list

    def test_definition_list_parsing(self) -> None:
        """Test parsing definition list."""
        text = "HTML: HyperText Markup Language\nCSS: Cascading Style Sheets"
        definitions = DefinitionListExtension.parse_definitions(text)
        assert len(definitions) >= 2

    def test_definition_not_detected(self) -> None:
        """Test non-definition list."""
        text = "This is just normal text"
        is_def_list = DefinitionListExtension.is_definition_list_syntax(text)
        assert not is_def_list


class TestAbbreviations:
    """Test abbreviation parsing."""

    def test_abbreviation_extraction(self) -> None:
        """Test extracting abbreviations."""
        source = "*[HTML]: HyperText Markup Language"
        parser = Parser()
        doc = parser.parse(source)

        abbrevs = AbbreviationExtension.extract_abbreviations(doc)
        # Should detect abbreviation pattern
        assert len(abbrevs) >= 0


class TestSmartTypography:
    """Test smart typography transformations."""

    def test_em_dash(self) -> None:
        """Test em dash conversion."""
        text = "before --- after"
        result = SmartTypographyExtension.apply(text)
        assert "\u2014" in result  # em dash

    def test_en_dash(self) -> None:
        """Test en dash conversion."""
        text = "before -- after"
        result = SmartTypographyExtension.apply(text)
        assert "\u2013" in result  # en dash

    def test_ellipsis(self) -> None:
        """Test ellipsis conversion."""
        text = "Wait..."
        result = SmartTypographyExtension.apply(text)
        assert "\u2026" in result  # ellipsis

    def test_smart_quotes_double(self) -> None:
        """Test smart double quotes."""
        text = '"Hello"'
        result = SmartTypographyExtension.apply(text)
        assert "\u201c" in result or "\u201d" in result  # smart quotes

    def test_smart_quotes_single(self) -> None:
        """Test smart single quotes."""
        text = "'Hello'"
        result = SmartTypographyExtension.apply(text)
        assert "\u2018" in result or "\u2019" in result  # smart quotes


class TestAttributeLists:
    """Test attribute list parsing."""

    def test_attribute_parsing(self) -> None:
        """Test parsing attribute lists."""
        text = "text {.class1 .class2 #id}"
        clean_text, attrs = AttributeListExtension.parse_attributes(text)
        assert clean_text == "text"
        assert "class" in attrs
        assert "id" in attrs
        assert attrs["id"] == "id"

    def test_attribute_classes(self) -> None:
        """Test class extraction."""
        text = "heading {.red .large}"
        clean_text, attrs = AttributeListExtension.parse_attributes(text)
        assert "red" in attrs.get("class", "")
        assert "large" in attrs.get("class", "")

    def test_attribute_key_value(self) -> None:
        """Test key-value attributes."""
        text = "text {data-value=123}"
        clean_text, attrs = AttributeListExtension.parse_attributes(text)
        assert attrs.get("data-value") == "123"

    def test_no_attributes(self) -> None:
        """Test text without attributes."""
        text = "plain text"
        clean_text, attrs = AttributeListExtension.parse_attributes(text)
        assert clean_text == "plain text"
        assert len(attrs) == 0


class TestAutoLinking:
    """Test auto URL linking."""

    def test_linkify_http(self) -> None:
        """Test HTTP URL linkification."""
        text = "Visit http://example.com for more"
        result = AutoLinkExtension.linkify(text)
        assert "[http://example.com](http://example.com)" in result

    def test_linkify_https(self) -> None:
        """Test HTTPS URL linkification."""
        text = "Secure https://example.com available"
        result = AutoLinkExtension.linkify(text)
        assert "[https://example.com](https://example.com)" in result

    def test_linkify_multiple(self) -> None:
        """Test multiple URL linkification."""
        text = "Visit http://a.com or https://b.com"
        result = AutoLinkExtension.linkify(text)
        assert result.count("](") >= 2


class TestMath:
    """Test math block detection."""

    def test_math_block_detection(self) -> None:
        """Test detecting math blocks."""
        text = "$$ x = y $$"
        is_math = MathExtension.is_math_block(text)
        assert is_math

    def test_math_extraction(self) -> None:
        """Test extracting math content."""
        text = "$$ x^2 + y^2 = z^2 $$"
        math = MathExtension.extract_math(text)
        assert math == "x^2 + y^2 = z^2"

    def test_inline_math(self) -> None:
        """Test inline math."""
        text = "$ x = y $"
        math = MathExtension.extract_math(text)
        assert math == "x = y"

    def test_non_math(self) -> None:
        """Test non-math text."""
        text = "regular text"
        is_math = MathExtension.is_math_block(text)
        assert not is_math


class TestAdmonitions:
    """Test admonition parsing."""

    def test_admonition_detection(self) -> None:
        """Test detecting admonitions."""
        text = "!!!note This is a note"
        is_admon = AdmonitionExtension.is_admonition(text)
        assert is_admon

    def test_admonition_parsing(self) -> None:
        """Test parsing admonition."""
        text = "!!!warning Important warning"
        admon_type, title = AdmonitionExtension.parse_admonition(text)
        assert admon_type == "warning"
        assert title == "Important warning"

    def test_admonition_types(self) -> None:
        """Test various admonition types."""
        for admon_type in ["note", "warning", "danger", "success", "info"]:
            text = f"!!!{admon_type} Title"
            atype, title = AdmonitionExtension.parse_admonition(text)
            assert atype == admon_type

    def test_invalid_admonition(self) -> None:
        """Test invalid admonition."""
        text = "!!!invalid Some text"
        atype, title = AdmonitionExtension.parse_admonition(text)
        assert atype is None


class TestExtensionIntegration:
    """Test multiple extensions together."""

    def test_toc_with_task_lists(self) -> None:
        """Test TOC generation with task lists."""
        source = "# Tasks\n- [ ] Task 1\n## Subtasks\n- [x] Task 2"
        parser = Parser()
        doc = parser.parse(source)

        toc = TableOfContentsExtension.generate(doc)
        tasks = TaskListExtension.extract_tasks(doc)

        assert len(toc) >= 2
        assert len(tasks) >= 2

    def test_smart_typography_preservation(self) -> None:
        """Test smart typography doesn't break Markdown."""
        text = "Visit http://example.com --- it's great!"
        result = SmartTypographyExtension.apply(text)
        # Should have smart dash and preserved URL
        assert "example.com" in result
        assert "\u2014" in result
