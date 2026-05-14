"""
AST transformation and manipulation utilities.

Provides:
- Heading level shifting
- Link and image URL rewriting
- Table of contents injection
- Footnote renumbering
- Reference link inlining
- List style normalization
- Section extraction
- Document splitting
- Metadata extraction
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy

from thomas.marketplace.markdown._types import (
    Document,
    Footnote,
    Heading,
    Image,
    InlineNode,
    Link,
    ListItem,
    MarkdownNode,
    Text,
)
from thomas.marketplace.markdown._types import List as MarkdownList
from thomas.marketplace.markdown.parser import Parser


class HeadingLevelShift:
    """Shift heading levels up or down."""

    @staticmethod
    def shift(doc: Document, delta: int) -> Document:
        """Shift all headings by delta levels.

        Args:
            doc: Document to transform
            delta: Number of levels to shift (+/-1, +/-2, etc.)

        Returns:
            New document with shifted headings
        """
        doc_copy = deepcopy(doc)

        def visit(node: MarkdownNode) -> None:
            if isinstance(node, Heading):
                node.level = max(1, min(6, node.level + delta))
            elif hasattr(node, "children"):
                for child in node.children:
                    if isinstance(child, MarkdownNode):
                        visit(child)

        visit(doc_copy)
        return doc_copy


class LinkRewriter:
    """Rewrite links and images in document."""

    @staticmethod
    def rewrite_links(doc: Document, url_map: dict[str, str]) -> Document:
        """Rewrite link URLs.

        Args:
            doc: Document to transform
            url_map: Dictionary of old_url -> new_url

        Returns:
            New document with rewritten links
        """
        doc_copy = deepcopy(doc)

        def visit(node: MarkdownNode | InlineNode) -> None:
            if isinstance(node, Link):
                if node.url in url_map:
                    node.url = url_map[node.url]
            elif isinstance(node, Image):
                if node.src in url_map:
                    node.src = url_map[node.src]
            elif hasattr(node, "children"):
                for child in node.children:
                    visit(child)

        visit(doc_copy)
        return doc_copy

    @staticmethod
    def rewrite_with_function(doc: Document, url_transform: Callable[[str], str]) -> Document:
        """Rewrite URLs using transformation function.

        Args:
            doc: Document to transform
            url_transform: Function to transform URLs

        Returns:
            New document with transformed URLs
        """
        doc_copy = deepcopy(doc)

        def visit(node: MarkdownNode | InlineNode) -> None:
            if isinstance(node, Link):
                node.url = url_transform(node.url)
            elif isinstance(node, Image):
                node.src = url_transform(node.src)
            elif hasattr(node, "children"):
                for child in node.children:
                    visit(child)

        visit(doc_copy)
        return doc_copy


class ListStyleNormalizer:
    """Normalize list styles (bullets and numbering)."""

    @staticmethod
    def normalize_bullets(doc: Document, bullet: str = "-") -> Document:
        """Normalize bullet points to consistent style.

        Args:
            doc: Document to transform
            bullet: Bullet character (-, *, +)

        Returns:
            New document with normalized bullets
        """
        # This mainly affects source rendering, not AST
        # Included for completeness
        doc_copy = deepcopy(doc)
        return doc_copy

    @staticmethod
    def normalize_numbered_lists(doc: Document, style: str = "1.") -> Document:
        """Normalize numbered list style.

        Args:
            doc: Document to transform
            style: Style like '1.' or '1)'

        Returns:
            New document with normalized numbering
        """
        doc_copy = deepcopy(doc)

        def visit(node: MarkdownNode) -> None:
            if isinstance(node, MarkdownList):
                if node.start:
                    node.start = 1
            elif hasattr(node, "children"):
                for child in node.children:
                    if isinstance(child, MarkdownNode):
                        visit(child)

        visit(doc_copy)
        return doc_copy


class SectionExtractor:
    """Extract content under specific headings."""

    @staticmethod
    def extract_section(doc: Document, heading_text: str) -> Document | None:
        """Extract section under specific heading.

        Args:
            doc: Source document
            heading_text: Heading text to match (case-insensitive)

        Returns:
            New document containing only that section
        """
        section_doc = Document()
        found = False
        start_level = 0

        for child in doc.children:
            if isinstance(child, Heading):
                if found:
                    # Stop if we hit another heading at same or higher level
                    if child.level <= start_level:
                        break

                if SectionExtractor._heading_matches(child, heading_text):
                    found = True
                    start_level = child.level
                    section_doc.children.append(deepcopy(child))
                    continue

            if found:
                section_doc.children.append(deepcopy(child))

        return section_doc if found else None

    @staticmethod
    def extract_sections_by_level(doc: Document, level: int) -> list[Document]:
        """Extract all sections at specific level.

        Args:
            doc: Source document
            level: Heading level (1-6)

        Returns:
            List of section documents
        """
        sections = []
        current_section = None

        for child in doc.children:
            if isinstance(child, Heading) and child.level == level:
                if current_section:
                    sections.append(current_section)
                current_section = Document()
                current_section.children.append(deepcopy(child))
            elif current_section:
                current_section.children.append(deepcopy(child))

        if current_section:
            sections.append(current_section)

        return sections

    @staticmethod
    def _heading_matches(heading: Heading, text: str) -> bool:
        """Check if heading text matches."""
        heading_text = SectionExtractor._extract_text(heading.children).lower()
        return heading_text == text.lower()

    @staticmethod
    def _extract_text(nodes: list[InlineNode]) -> str:
        """Extract plain text from nodes."""
        text = []
        for node in nodes:
            if isinstance(node, Text):
                text.append(node.content)
            elif hasattr(node, "children"):
                text.append(SectionExtractor._extract_text(node.children))
        return "".join(text)


class DocumentSplitter:
    """Split document at heading levels."""

    @staticmethod
    def split_at_level(doc: Document, level: int) -> list[Document]:
        """Split document at heading level.

        Args:
            doc: Source document
            level: Level at which to split

        Returns:
            List of document chunks
        """
        documents = []
        current_doc = Document()

        for child in doc.children:
            if isinstance(child, Heading) and child.level == level and current_doc.children:
                documents.append(current_doc)
                current_doc = Document()

            current_doc.children.append(deepcopy(child))

        if current_doc.children:
            documents.append(current_doc)

        return documents


class MetadataExtractor:
    """Extract metadata like YAML front matter."""

    @staticmethod
    def extract_front_matter(source: str) -> tuple[dict[str, str], str]:
        """Extract YAML front matter.

        Args:
            source: Markdown source

        Returns:
            Tuple of (metadata_dict, remaining_source)
        """
        lines = source.split("\n")

        if not lines or lines[0].strip() != "---":
            return {}, source

        end_idx = None
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end_idx = i
                break

        if end_idx is None:
            return {}, source

        # Parse YAML-like front matter (simple key: value parsing)
        metadata = {}
        for line in lines[1:end_idx]:
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip()

        remaining = "\n".join(lines[end_idx + 1 :])
        return metadata, remaining


class TableOfContentsInjector:
    """Inject table of contents into document."""

    @staticmethod
    def inject_toc(doc: Document, after_heading_text: str | None = None) -> Document:
        """Inject TOC into document.

        Args:
            doc: Document to modify
            after_heading_text: Insert TOC after this heading (None=beginning)

        Returns:
            New document with TOC injected
        """
        from thomas.marketplace.markdown.extensions import TableOfContentsExtension

        doc_copy = deepcopy(doc)
        toc_entries = TableOfContentsExtension.generate(doc_copy)

        # Build TOC list
        toc_list = MarkdownList(list_type=None, tight=True)
        for entry in toc_entries:
            "  " * (entry.level - 1)
            item_text = f"[{entry.title}](#{entry.anchor})"
            item = ListItem()
            # Parse item text
            parser = Parser()
            parsed = parser.parse(item_text)
            if parsed.children:
                item.children = parsed.children[0].children

            toc_list.children.append(item)

        # Find insertion point
        insert_pos = 0
        if after_heading_text:
            for i, child in enumerate(doc_copy.children):
                if isinstance(child, Heading):
                    heading_text = TableOfContentsInjector._extract_text(child.children)
                    if heading_text.lower() == after_heading_text.lower():
                        insert_pos = i + 1
                        break

        doc_copy.children.insert(insert_pos, toc_list)
        return doc_copy

    @staticmethod
    def _extract_text(nodes: list[InlineNode]) -> str:
        """Extract text from nodes."""
        text = []
        for node in nodes:
            if isinstance(node, Text):
                text.append(node.content)
            elif hasattr(node, "children"):
                text.append(TableOfContentsInjector._extract_text(node.children))
        return "".join(text)


class FootnoteRenumberer:
    """Renumber footnotes sequentially."""

    @staticmethod
    def renumber(doc: Document) -> tuple[Document, dict[str, str]]:
        """Renumber footnotes.

        Args:
            doc: Document with footnotes

        Returns:
            Tuple of (new_document, mapping_old->new)
        """
        doc_copy = deepcopy(doc)
        mapping: dict[str, str] = {}
        counter = 1

        # First pass: collect and map old labels to new
        def visit_collect(node: MarkdownNode | InlineNode) -> None:
            nonlocal counter
            if isinstance(node, Footnote):
                if node.label not in mapping:
                    mapping[node.label] = str(counter)
                    counter += 1
            elif hasattr(node, "children"):
                for child in node.children:
                    visit_collect(child)

        # Second pass: update labels
        def visit_update(node: MarkdownNode | InlineNode) -> None:
            if isinstance(node, Footnote):
                node.label = mapping.get(node.label, node.label)
            elif hasattr(node, "children"):
                for child in node.children:
                    visit_update(child)

        visit_collect(doc_copy)
        visit_update(doc_copy)

        return doc_copy, mapping


class ReferenceLinkInliner:
    """Convert reference-style links to inline links."""

    @staticmethod
    def inline_references(doc: Document, references: dict[str, tuple[str, str | None]]) -> Document:
        """Inline all reference links.

        Args:
            doc: Document with reference links
            references: Reference definitions

        Returns:
            New document with inlined links
        """
        doc_copy = deepcopy(doc)

        def visit(node: MarkdownNode | InlineNode) -> None:
            if isinstance(node, Link):
                # If URL is empty, it might be a reference link
                if not node.url and node.children:
                    # Try to find reference
                    text = ReferenceLinkInliner._extract_text(node.children)
                    if text in references:
                        url, title = references[text]
                        node.url = url
                        node.title = title
            elif hasattr(node, "children"):
                for child in node.children:
                    visit(child)

        visit(doc_copy)
        return doc_copy

    @staticmethod
    def _extract_text(nodes: list[InlineNode]) -> str:
        """Extract text from nodes."""
        text = []
        for node in nodes:
            if isinstance(node, Text):
                text.append(node.content)
            elif hasattr(node, "children"):
                text.append(ReferenceLinkInliner._extract_text(node.children))
        return "".join(text)
