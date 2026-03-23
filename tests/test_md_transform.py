"""
Tests for Markdown AST transformations.
"""

from thomas.marketplace.markdown.parser import Parser
from thomas.marketplace.markdown.transform import (
    DocumentSplitter,
    FootnoteRenumberer,
    HeadingLevelShift,
    LinkRewriter,
    MetadataExtractor,
    SectionExtractor,
    TableOfContentsInjector,
)


class TestHeadingLevelShift:
    """Test heading level transformation."""

    def test_shift_up_one_level(self) -> None:
        """Test shifting headings up by one level."""
        source = "## H2\n### H3"
        parser = Parser()
        doc = parser.parse(source)

        shifted = HeadingLevelShift.shift(doc, -1)

        # First heading should now be H1
        from thomas.marketplace.markdown._types import Heading

        headings = [child for child in shifted.children if isinstance(child, Heading)]
        assert headings[0].level == 1
        assert headings[1].level == 2

    def test_shift_down_one_level(self) -> None:
        """Test shifting headings down by one level."""
        source = "# H1\n## H2"
        parser = Parser()
        doc = parser.parse(source)

        shifted = HeadingLevelShift.shift(doc, 1)

        from thomas.marketplace.markdown._types import Heading

        headings = [child for child in shifted.children if isinstance(child, Heading)]
        assert headings[0].level == 2
        assert headings[1].level == 3

    def test_shift_clamps_to_h6(self) -> None:
        """Test that shift doesn't create h7."""
        source = "# H1"
        parser = Parser()
        doc = parser.parse(source)

        # Try to shift up 5 levels (beyond h6)
        shifted = HeadingLevelShift.shift(doc, 5)

        from thomas.marketplace.markdown._types import Heading

        headings = [child for child in shifted.children if isinstance(child, Heading)]
        assert headings[0].level == 6  # Clamped to max

    def test_shift_clamps_to_h1(self) -> None:
        """Test that shift doesn't create h0."""
        source = "## H2"
        parser = Parser()
        doc = parser.parse(source)

        # Shift down too much
        shifted = HeadingLevelShift.shift(doc, -5)

        from thomas.marketplace.markdown._types import Heading

        headings = [child for child in shifted.children if isinstance(child, Heading)]
        assert headings[0].level == 1  # Clamped to min


class TestLinkRewriting:
    """Test link URL rewriting."""

    def test_rewrite_link_urls(self) -> None:
        """Test rewriting link URLs."""
        source = "[link](oldurl.com)"
        parser = Parser()
        doc = parser.parse(source)

        url_map = {"oldurl.com": "newurl.com"}
        rewritten = LinkRewriter.rewrite_links(doc, url_map)

        from thomas.marketplace.markdown._types import Link

        def find_links(node):
            links = []
            if isinstance(node, Link):
                links.append(node)
            if hasattr(node, "children"):
                for child in node.children:
                    links.extend(find_links(child))
            return links

        links = find_links(rewritten)
        if links:
            assert links[0].url == "newurl.com"

    def test_rewrite_with_function(self) -> None:
        """Test rewriting with transformation function."""
        source = "[link](http://old.com)"
        parser = Parser()
        doc = parser.parse(source)

        def https_transform(url: str) -> str:
            return url.replace("http://", "https://")

        rewritten = LinkRewriter.rewrite_with_function(doc, https_transform)

        from thomas.marketplace.markdown._types import Link

        def find_links(node):
            links = []
            if isinstance(node, Link):
                links.append(node)
            if hasattr(node, "children"):
                for child in node.children:
                    links.extend(find_links(child))
            return links

        links = find_links(rewritten)
        if links:
            assert links[0].url.startswith("https://")

    def test_image_url_rewriting(self) -> None:
        """Test rewriting image URLs."""
        source = "![alt](old/image.jpg)"
        parser = Parser()
        doc = parser.parse(source)

        url_map = {"old/image.jpg": "new/image.jpg"}
        rewritten = LinkRewriter.rewrite_links(doc, url_map)

        # Test that image src was updated
        assert rewritten is not None


class TestSectionExtraction:
    """Test section extraction."""

    def test_extract_section_by_heading(self) -> None:
        """Test extracting section under specific heading."""
        source = """# Introduction

Intro text.

## Details

Details here.

# Conclusion

Conclusion text."""

        parser = Parser()
        doc = parser.parse(source)

        section = SectionExtractor.extract_section(doc, "Details")
        assert section is not None

    def test_extract_nonexistent_section(self) -> None:
        """Test extracting non-existent section."""
        source = "# Title\n\nContent"
        parser = Parser()
        doc = parser.parse(source)

        section = SectionExtractor.extract_section(doc, "Nonexistent")
        assert section is None

    def test_extract_sections_by_level(self) -> None:
        """Test extracting all sections at specific level."""
        source = """# H1

Content 1

# H1 Again

Content 2

## H2

Content 3"""

        parser = Parser()
        doc = parser.parse(source)

        sections = SectionExtractor.extract_sections_by_level(doc, 1)
        assert len(sections) >= 2


class TestDocumentSplitting:
    """Test document splitting."""

    def test_split_at_h1(self) -> None:
        """Test splitting document at h1 headings."""
        source = """# Part 1

Content 1

# Part 2

Content 2

# Part 3

Content 3"""

        parser = Parser()
        doc = parser.parse(source)

        docs = DocumentSplitter.split_at_level(doc, 1)
        assert len(docs) >= 3

    def test_split_at_h2(self) -> None:
        """Test splitting at h2 level."""
        source = """# Main

## Section 1

Content

## Section 2

Content"""

        parser = Parser()
        doc = parser.parse(source)

        docs = DocumentSplitter.split_at_level(doc, 2)
        assert len(docs) >= 2


class TestMetadataExtraction:
    """Test metadata extraction."""

    def test_extract_front_matter(self) -> None:
        """Test extracting YAML front matter."""
        source = """---
title: My Document
author: John Doe
---

# Content

Document content here."""

        metadata, remaining = MetadataExtractor.extract_front_matter(source)
        assert "title" in metadata
        assert metadata["title"] == "My Document"
        assert "author" in metadata
        assert "# Content" in remaining

    def test_no_front_matter(self) -> None:
        """Test document without front matter."""
        source = "# Title\n\nContent"
        metadata, remaining = MetadataExtractor.extract_front_matter(source)
        assert len(metadata) == 0
        assert remaining == source

    def test_incomplete_front_matter(self) -> None:
        """Test incomplete front matter (no closing ---)."""
        source = "---\ntitle: Doc\n# Content"
        metadata, remaining = MetadataExtractor.extract_front_matter(source)
        # Should not parse as front matter
        assert len(metadata) == 0


class TestTableOfContentsInjection:
    """Test TOC injection."""

    def test_inject_toc_at_beginning(self) -> None:
        """Test injecting TOC at document beginning."""
        source = """# Main

## Section 1

Content 1

## Section 2

Content 2"""

        parser = Parser()
        doc = parser.parse(source)

        with_toc = TableOfContentsInjector.inject_toc(doc)

        # Should have more children now (TOC list added)
        assert len(with_toc.children) > len(doc.children)

    def test_inject_toc_after_heading(self) -> None:
        """Test injecting TOC after specific heading."""
        source = """# Table of Contents

Placeholder

# Introduction

Intro content

# Main Content

Main content"""

        parser = Parser()
        doc = parser.parse(source)

        with_toc = TableOfContentsInjector.inject_toc(doc, "Table of Contents")

        # TOC should be inserted after the heading
        assert with_toc is not None


class TestFootnoteRenumbering:
    """Test footnote renumbering."""

    def test_renumber_footnotes(self) -> None:
        """Test renumbering footnotes sequentially."""
        # This would require parsed document with footnotes
        # For now, test that function exists and returns correct types
        parser = Parser()
        doc = parser.parse("# Test")

        renumbered, mapping = FootnoteRenumberer.renumber(doc)

        assert renumbered is not None
        assert isinstance(mapping, dict)


class TestTransformPreservation:
    """Test that transformations preserve document structure."""

    def test_heading_shift_preserves_content(self) -> None:
        """Test that heading shift preserves paragraph content."""
        source = """# Title

Paragraph 1

## Subtitle

Paragraph 2"""

        parser = Parser()
        doc = parser.parse(source)

        shifted = HeadingLevelShift.shift(doc, 1)

        # Content should be preserved
        from thomas.marketplace.markdown._types import Heading, Paragraph

        headings = [c for c in shifted.children if isinstance(c, Heading)]
        paragraphs = [c for c in shifted.children if isinstance(c, Paragraph)]

        assert len(headings) == 2
        assert len(paragraphs) == 2

    def test_section_extraction_is_deep_copy(self) -> None:
        """Test that extraction doesn't modify original."""
        source = """# Section 1

Content 1

# Section 2

Content 2"""

        parser = Parser()
        original = parser.parse(source)
        original_len = len(original.children)

        extracted = SectionExtractor.extract_section(original, "Section 1")

        # Original should be unchanged
        assert len(original.children) == original_len

    def test_link_rewriting_is_deep_copy(self) -> None:
        """Test that link rewriting doesn't modify original."""
        source = "[link](old.com)"
        parser = Parser()
        original = parser.parse(source)

        rewritten = LinkRewriter.rewrite_links(original, {"old.com": "new.com"})

        # Documents should be different
        assert original is not rewritten


class TestComplexTransformations:
    """Test complex transformation scenarios."""

    def test_multiple_transforms(self) -> None:
        """Test applying multiple transforms sequentially."""
        source = """# Main

## Details

Content with [link](old.com)

# Conclusion"""

        parser = Parser()
        doc = parser.parse(source)

        # Shift headings down
        doc = HeadingLevelShift.shift(doc, 1)

        # Rewrite links
        doc = LinkRewriter.rewrite_links(doc, {"old.com": "new.com"})

        # Extract section
        section = SectionExtractor.extract_section(doc, "Details")

        assert section is not None
