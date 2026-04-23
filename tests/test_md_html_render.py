"""
Tests for HTML rendering.
"""

from thomas.marketplace.markdown._types import Document, RenderConfig
from thomas.marketplace.markdown.html_renderer import HTMLRenderer
from thomas.marketplace.markdown.parser import Parser


class TestHeadingRendering:
    """Test heading HTML rendering."""

    def test_heading_h1(self) -> None:
        """Test h1 heading rendering."""
        parser = Parser()
        doc = parser.parse("# Title")
        renderer = HTMLRenderer()
        html = renderer.render(doc)
        assert "<h1" in html
        assert "Title" in html
        assert "</h1>" in html

    def test_heading_h6(self) -> None:
        """Test h6 heading rendering."""
        parser = Parser()
        doc = parser.parse("###### Deep")
        renderer = HTMLRenderer()
        html = renderer.render(doc)
        assert "<h6" in html

    def test_heading_with_id(self) -> None:
        """Test heading with generated ID."""
        parser = Parser()
        doc = parser.parse("# My Heading")
        config = RenderConfig(heading_ids=True)
        renderer = HTMLRenderer(config)
        html = renderer.render(doc)
        assert 'id="' in html
        assert "my-heading" in html.lower()


class TestParagraphRendering:
    """Test paragraph HTML rendering."""

    def test_paragraph_simple(self) -> None:
        """Test simple paragraph."""
        parser = Parser()
        doc = parser.parse("This is a paragraph.")
        renderer = HTMLRenderer()
        html = renderer.render(doc)
        assert "<p>" in html
        assert "This is a paragraph." in html
        assert "</p>" in html

    def test_paragraph_multiline(self) -> None:
        """Test multi-line paragraph."""
        parser = Parser()
        doc = parser.parse("Line 1\nLine 2\nLine 3")
        renderer = HTMLRenderer()
        html = renderer.render(doc)
        assert "<p>" in html
        assert "Line 1" in html
        assert "Line 3" in html


class TestEmphasisRendering:
    """Test emphasis HTML rendering."""

    def test_emphasis_italic(self) -> None:
        """Test italic emphasis."""
        parser = Parser()
        doc = parser.parse("*italic text*")
        renderer = HTMLRenderer()
        html = renderer.render(doc)
        assert "<em>" in html
        assert "italic text" in html
        assert "</em>" in html

    def test_strong_bold(self) -> None:
        """Test strong bold."""
        parser = Parser()
        doc = parser.parse("**bold text**")
        renderer = HTMLRenderer()
        html = renderer.render(doc)
        assert "<strong>" in html
        assert "bold text" in html
        assert "</strong>" in html


class TestCodeRendering:
    """Test code HTML rendering."""

    def test_inline_code(self) -> None:
        """Test inline code."""
        parser = Parser()
        doc = parser.parse("`code`")
        renderer = HTMLRenderer()
        html = renderer.render(doc)
        assert "<code>" in html
        assert "code" in html
        assert "</code>" in html

    def test_code_block(self) -> None:
        """Test code block."""
        parser = Parser()
        doc = parser.parse("```python\nprint('hello')\n```")
        renderer = HTMLRenderer()
        html = renderer.render(doc)
        assert "<pre>" in html
        assert "<code" in html
        assert "language-python" in html
        assert "</code>" in html
        assert "</pre>" in html

    def test_code_block_no_language(self) -> None:
        """Test code block without language."""
        parser = Parser()
        doc = parser.parse("```\ncode\n```")
        renderer = HTMLRenderer()
        html = renderer.render(doc)
        assert "<pre>" in html


class TestLinkRendering:
    """Test link HTML rendering."""

    def test_link_simple(self) -> None:
        """Test simple link."""
        parser = Parser()
        doc = parser.parse("[text](http://example.com)")
        renderer = HTMLRenderer()
        html = renderer.render(doc)
        assert "<a href=" in html
        assert "http://example.com" in html
        assert "text" in html
        assert "</a>" in html

    def test_link_with_title(self) -> None:
        """Test link with title."""
        parser = Parser()
        doc = parser.parse('[text](url "title")')
        renderer = HTMLRenderer()
        html = renderer.render(doc)
        assert 'title="title"' in html

    def test_link_escaping(self) -> None:
        """Test link URL escaping."""
        parser = Parser()
        doc = parser.parse("[text](url?param=a&b=c)")
        renderer = HTMLRenderer()
        html = renderer.render(doc)
        assert "&amp;" in html  # & should be escaped


class TestImageRendering:
    """Test image HTML rendering."""

    def test_image_simple(self) -> None:
        """Test simple image."""
        parser = Parser()
        doc = parser.parse("![alt text](image.jpg)")
        renderer = HTMLRenderer()
        html = renderer.render(doc)
        assert "<img" in html
        assert 'src="image.jpg"' in html
        assert 'alt="alt text"' in html

    def test_image_with_title(self) -> None:
        """Test image with title."""
        parser = Parser()
        doc = parser.parse('![alt](src "title")')
        renderer = HTMLRenderer()
        html = renderer.render(doc)
        assert 'title="title"' in html


class TestListRendering:
    """Test list HTML rendering."""

    def test_unordered_list(self) -> None:
        """Test unordered list."""
        parser = Parser()
        doc = parser.parse("- item 1\n- item 2\n- item 3")
        renderer = HTMLRenderer()
        html = renderer.render(doc)
        assert "<ul>" in html
        assert "<li>" in html
        assert "item 1" in html
        assert "</ul>" in html

    def test_ordered_list(self) -> None:
        """Test ordered list."""
        parser = Parser()
        doc = parser.parse("1. first\n2. second\n3. third")
        renderer = HTMLRenderer()
        html = renderer.render(doc)
        assert "<ol>" in html
        assert "<li>" in html

    def test_task_list(self) -> None:
        """Test task list items."""
        parser = Parser()
        doc = parser.parse("- [ ] unchecked\n- [x] checked")
        renderer = HTMLRenderer()
        html = renderer.render(doc)
        assert '<input type="checkbox"' in html


class TestBlockQuoteRendering:
    """Test blockquote HTML rendering."""

    def test_blockquote(self) -> None:
        """Test blockquote."""
        parser = Parser()
        doc = parser.parse("> A quote\n> More quote")
        renderer = HTMLRenderer()
        html = renderer.render(doc)
        assert "<blockquote>" in html
        assert "</blockquote>" in html


class TestTableRendering:
    """Test table HTML rendering."""

    def test_table_simple(self) -> None:
        """Test simple table."""
        parser = Parser()
        doc = parser.parse("| h1 | h2 |\n|---|---|\n| a | b |")
        renderer = HTMLRenderer()
        html = renderer.render(doc)
        assert "<table>" in html
        assert "<thead>" in html
        assert "<tbody>" in html
        assert "<th>" in html
        assert "<td>" in html

    def test_table_alignment(self) -> None:
        """Test table column alignment."""
        parser = Parser()
        doc = parser.parse("| L | C | R |\n|:--|:--:|--:|\n| 1 | 2 | 3 |")
        renderer = HTMLRenderer(RenderConfig(table_alignment=True))
        html = renderer.render(doc)
        assert "text-align" in html


class TestHtmlPassthrough:
    """Test raw HTML handling."""

    def test_html_unsafe_disabled(self) -> None:
        """Test HTML is escaped when unsafe disabled."""
        doc = Document()
        from thomas.marketplace.markdown._types import HTMLBlock

        html_block = HTMLBlock("<div>content</div>")
        doc.children.append(html_block)

        config = RenderConfig(unsafe_html=False)
        renderer = HTMLRenderer(config)
        html = renderer.render(doc)
        assert "&lt;div&gt;" in html

    def test_html_unsafe_enabled(self) -> None:
        """Test raw HTML passes through when unsafe enabled."""
        doc = Document()
        from thomas.marketplace.markdown._types import HTMLBlock

        html_block = HTMLBlock("<div>content</div>")
        doc.children.append(html_block)

        config = RenderConfig(unsafe_html=True)
        renderer = HTMLRenderer(config)
        html = renderer.render(doc)
        assert "<div>" in html


class TestXhtmlMode:
    """Test XHTML self-closing tags."""

    def test_xhtml_mode_hr(self) -> None:
        """Test XHTML mode for thematic break."""
        parser = Parser()
        doc = parser.parse("---")
        config = RenderConfig(xhtml=True)
        renderer = HTMLRenderer(config)
        html = renderer.render(doc)
        assert "<hr />" in html

    def test_html5_mode_hr(self) -> None:
        """Test HTML5 mode for thematic break."""
        parser = Parser()
        doc = parser.parse("---")
        config = RenderConfig(xhtml=False)
        renderer = HTMLRenderer(config)
        html = renderer.render(doc)
        assert "<hr>" in html


class TestSpecialCharacterEscaping:
    """Test special character escaping."""

    def test_ampersand_escape(self) -> None:
        """Test & escaping."""
        parser = Parser()
        doc = parser.parse("A & B")
        renderer = HTMLRenderer()
        html = renderer.render(doc)
        assert "&amp;" in html

    def test_less_than_escape(self) -> None:
        """Test < escaping."""
        parser = Parser()
        doc = parser.parse("A < B")
        renderer = HTMLRenderer()
        html = renderer.render(doc)
        assert "&lt;" in html

    def test_greater_than_escape(self) -> None:
        """Test > escaping."""
        parser = Parser()
        doc = parser.parse("A > B")
        renderer = HTMLRenderer()
        html = renderer.render(doc)
        assert "&gt;" in html


class TestComplexDocuments:
    """Test rendering complex documents."""

    def test_mixed_content(self) -> None:
        """Test document with mixed content."""
        source = """# Title

Paragraph with **bold** and *italic*.

- List item 1
- List item 2

> A blockquote

```python
code
```
"""
        parser = Parser()
        doc = parser.parse(source)
        renderer = HTMLRenderer()
        html = renderer.render(doc)

        # Check all elements present
        assert "<h1" in html
        assert "<strong>" in html
        assert "<em>" in html
        assert "<ul>" in html
        assert "<blockquote>" in html
        assert "<pre>" in html
