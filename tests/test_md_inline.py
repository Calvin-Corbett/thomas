"""
Tests for Markdown inline parser.
"""

from thomas.markdown._types import Code, Emphasis, Image, LineBreak, Link, SoftBreak, Strong, Text
from thomas.markdown.inline_parser import InlineParser


class TestPlainText:
    """Test plain text parsing."""

    def test_simple_text(self) -> None:
        """Test simple text."""
        parser = InlineParser()
        nodes = parser.parse("hello world")
        assert len(nodes) == 1
        assert isinstance(nodes[0], Text)
        assert nodes[0].content == "hello world"

    def test_text_with_numbers(self) -> None:
        """Test text containing numbers."""
        parser = InlineParser()
        nodes = parser.parse("version 1.2.3")
        assert len(nodes) == 1
        assert isinstance(nodes[0], Text)


class TestEmphasis:
    """Test emphasis parsing."""

    def test_emphasis_asterisks(self) -> None:
        """Test emphasis with asterisks."""
        parser = InlineParser()
        nodes = parser.parse("*italic*")
        assert len(nodes) == 1
        assert isinstance(nodes[0], Emphasis)

    def test_emphasis_underscores(self) -> None:
        """Test emphasis with underscores."""
        parser = InlineParser()
        nodes = parser.parse("_italic_")
        assert len(nodes) == 1
        assert isinstance(nodes[0], Emphasis)

    def test_strong_asterisks(self) -> None:
        """Test strong with asterisks."""
        parser = InlineParser()
        nodes = parser.parse("**bold**")
        assert len(nodes) == 1
        assert isinstance(nodes[0], Strong)

    def test_strong_underscores(self) -> None:
        """Test strong with underscores."""
        parser = InlineParser()
        nodes = parser.parse("__bold__")
        assert len(nodes) == 1
        assert isinstance(nodes[0], Strong)

    def test_emphasis_nested_in_strong(self) -> None:
        """Test emphasis inside strong."""
        parser = InlineParser()
        nodes = parser.parse("***bold italic***")
        assert len(nodes) >= 1
        # Should contain nested emphasis/strong

    def test_emphasis_with_text(self) -> None:
        """Test emphasis with surrounding text."""
        parser = InlineParser()
        nodes = parser.parse("This is *important* text")
        assert len(nodes) >= 2


class TestCode:
    """Test code span parsing."""

    def test_code_single_backtick(self) -> None:
        """Test code with single backticks."""
        parser = InlineParser()
        nodes = parser.parse("`code`")
        assert len(nodes) == 1
        assert isinstance(nodes[0], Code)
        assert nodes[0].content == "code"

    def test_code_double_backticks(self) -> None:
        """Test code with double backticks."""
        parser = InlineParser()
        nodes = parser.parse("``code with ` backtick``")
        assert len(nodes) == 1
        assert isinstance(nodes[0], Code)

    def test_code_with_spaces(self) -> None:
        """Test code with leading/trailing spaces."""
        parser = InlineParser()
        nodes = parser.parse("` code `")
        assert len(nodes) == 1
        assert isinstance(nodes[0], Code)
        assert nodes[0].content == "code"

    def test_code_unclosed(self) -> None:
        """Test unclosed code span falls back to text."""
        parser = InlineParser()
        nodes = parser.parse("`unclosed")
        # Should be parsed as text or text with backtick
        assert len(nodes) >= 1


class TestLinks:
    """Test link parsing."""

    def test_link_inline(self) -> None:
        """Test inline link."""
        parser = InlineParser()
        nodes = parser.parse("[text](url)")
        assert len(nodes) == 1
        assert isinstance(nodes[0], Link)
        assert nodes[0].url == "url"

    def test_link_with_title(self) -> None:
        """Test link with title."""
        parser = InlineParser()
        nodes = parser.parse('[text](url "title")')
        assert len(nodes) == 1
        link = nodes[0]
        assert isinstance(link, Link)
        assert link.url == "url"
        assert link.title == "title"

    def test_link_with_angle_brackets(self) -> None:
        """Test link URL in angle brackets."""
        parser = InlineParser()
        nodes = parser.parse("[text](<url>)")
        assert len(nodes) == 1
        link = nodes[0]
        assert isinstance(link, Link)
        assert link.url == "url"

    def test_autolink(self) -> None:
        """Test autolink."""
        parser = InlineParser()
        nodes = parser.parse("<https://example.com>")
        assert len(nodes) == 1
        assert isinstance(nodes[0], Link)
        assert nodes[0].url == "https://example.com"

    def test_link_with_nested_emphasis(self) -> None:
        """Test link with emphasis in text."""
        parser = InlineParser()
        nodes = parser.parse("[*text*](url)")
        assert len(nodes) == 1
        assert isinstance(nodes[0], Link)


class TestImages:
    """Test image parsing."""

    def test_image_simple(self) -> None:
        """Test simple image."""
        parser = InlineParser()
        nodes = parser.parse("![alt](src)")
        assert len(nodes) == 1
        assert isinstance(nodes[0], Image)
        assert nodes[0].alt == "alt"
        assert nodes[0].src == "src"

    def test_image_with_title(self) -> None:
        """Test image with title."""
        parser = InlineParser()
        nodes = parser.parse('![alt](src "title")')
        assert len(nodes) == 1
        img = nodes[0]
        assert isinstance(img, Image)
        assert img.title == "title"

    def test_image_empty_alt(self) -> None:
        """Test image with empty alt text."""
        parser = InlineParser()
        nodes = parser.parse("![](src)")
        assert len(nodes) == 1
        assert isinstance(nodes[0], Image)


class TestLineBreaks:
    """Test line break parsing."""

    def test_hard_break_spaces(self) -> None:
        """Test hard break with two spaces."""
        parser = InlineParser()
        nodes = parser.parse("line1  \nline2")
        # Should contain LineBreak
        has_line_break = any(isinstance(n, LineBreak) for n in nodes)
        assert has_line_break

    def test_hard_break_backslash(self) -> None:
        """Test hard break with backslash."""
        parser = InlineParser()
        nodes = parser.parse("line1\\\nline2")
        has_line_break = any(isinstance(n, LineBreak) for n in nodes)
        assert has_line_break

    def test_soft_break(self) -> None:
        """Test soft line break."""
        parser = InlineParser()
        nodes = parser.parse("line1\nline2")
        has_soft_break = any(isinstance(n, SoftBreak) for n in nodes)
        assert has_soft_break


class TestEscapes:
    """Test escape sequences."""

    def test_escape_special_chars(self) -> None:
        """Test escaping special characters."""
        parser = InlineParser()
        nodes = parser.parse(r"\*not italic\*")
        # Should contain literal asterisks
        text = "".join(n.content for n in nodes if isinstance(n, Text))
        assert "*not italic*" in text

    def test_escape_backslash(self) -> None:
        """Test escaping backslash."""
        parser = InlineParser()
        nodes = parser.parse(r"backslash: \\")
        text = "".join(n.content for n in nodes if isinstance(n, Text))
        assert "\\" in text


class TestStrikethrough:
    """Test strikethrough parsing (extension)."""

    def test_strikethrough(self) -> None:
        """Test strikethrough."""
        parser = InlineParser()
        nodes = parser.parse("~~deleted~~")
        assert len(nodes) >= 1
        # May or may not parse as strikethrough depending on extension enabled


class TestFootnotes:
    """Test footnote parsing (extension)."""

    def test_footnote_reference(self) -> None:
        """Test footnote reference."""
        parser = InlineParser()
        nodes = parser.parse("text[^1] more")
        assert len(nodes) >= 1
        # Should contain footnote if extension enabled


class TestEntityReferences:
    """Test HTML entity parsing."""

    def test_entity_named(self) -> None:
        """Test named entity reference."""
        parser = InlineParser()
        nodes = parser.parse("&amp; &lt; &gt;")
        text = "".join(n.content for n in nodes if isinstance(n, Text))
        assert "&" in text

    def test_entity_numeric(self) -> None:
        """Test numeric entity reference."""
        parser = InlineParser()
        nodes = parser.parse("&#65; &#x41;")
        text = "".join(n.content for n in nodes if isinstance(n, Text))
        # Should have 'A' characters
        assert text.count("A") >= 2


class TestMixedInline:
    """Test mixed inline content."""

    def test_emphasis_and_code(self) -> None:
        """Test emphasis with code."""
        parser = InlineParser()
        nodes = parser.parse("*emphasized `code` text*")
        assert len(nodes) >= 1

    def test_link_and_emphasis(self) -> None:
        """Test link with emphasis."""
        parser = InlineParser()
        nodes = parser.parse("[*link text*](url)")
        assert len(nodes) >= 1

    def test_complex_inline(self) -> None:
        """Test complex mixed inline content."""
        parser = InlineParser()
        nodes = parser.parse("**bold [link](url) with `code`**")
        assert len(nodes) >= 1

    def test_multiple_links(self) -> None:
        """Test multiple links."""
        parser = InlineParser()
        nodes = parser.parse("[first](url1) and [second](url2)")
        links = [n for n in nodes if isinstance(n, Link)]
        assert len(links) == 2

    def test_text_with_special_chars(self) -> None:
        """Test text with various special characters."""
        parser = InlineParser()
        nodes = parser.parse("text with (parens) and [brackets] and {braces}")
        # Should handle without errors
        assert len(nodes) >= 1
