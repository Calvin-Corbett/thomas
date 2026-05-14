"""
Markdown diff and merge utilities.

Provides:
- AST-based diff (structural changes)
- Content change detection
- Unified diff output
- Three-way merge for collaborative editing
- Conflict detection
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from enum import Enum

from thomas.marketplace.markdown._types import Document, Heading, MarkdownNode, Paragraph, Text
from thomas.marketplace.markdown.parser import Parser
from thomas.marketplace.markdown.text_renderer import TextRenderer


class DiffType(Enum):
    """Type of difference."""

    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    UNCHANGED = "unchanged"


@dataclass
class DiffEntry:
    """Single diff entry."""

    type: DiffType
    before: MarkdownNode | None = None
    after: MarkdownNode | None = None
    line: int = 0

    def __repr__(self) -> str:
        """Return string representation."""
        return f"DiffEntry({self.type.value} at line {self.line})"


class MarkdownDiff:
    """Compute structural diff between Markdown documents."""

    def __init__(self) -> None:
        """Initialize differ."""
        self.diffs: list[DiffEntry] = []

    def diff(self, before: str | Document, after: str | Document) -> list[DiffEntry]:
        """Compute diff between two documents.

        Args:
            before: Original document (string or AST)
            after: Modified document (string or AST)

        Returns:
            List of diff entries
        """
        # Parse if needed
        if isinstance(before, str):
            parser = Parser()
            before = parser.parse(before)
        if isinstance(after, str):
            parser = Parser()
            after = parser.parse(after)

        self.diffs = []
        self._diff_nodes(before.children, after.children)
        return self.diffs

    def _diff_nodes(self, before_children: list[MarkdownNode], after_children: list[MarkdownNode]) -> None:
        """Recursively diff node lists."""
        # Simple line-based diff
        sm = difflib.SequenceMatcher(None, before_children, after_children)

        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                # Check if content changed
                for before_node, after_node in zip(before_children[i1:i2], after_children[j1:j2]):
                    if self._nodes_differ(before_node, after_node):
                        self.diffs.append(DiffEntry(type=DiffType.MODIFIED, before=before_node, after=after_node))
                    else:
                        self.diffs.append(DiffEntry(type=DiffType.UNCHANGED))

            elif tag == "delete":
                for node in before_children[i1:i2]:
                    self.diffs.append(DiffEntry(type=DiffType.REMOVED, before=node))

            elif tag == "insert":
                for node in after_children[j1:j2]:
                    self.diffs.append(DiffEntry(type=DiffType.ADDED, after=node))

            elif tag == "replace":
                # Handle replacements as delete + insert
                for node in before_children[i1:i2]:
                    self.diffs.append(DiffEntry(type=DiffType.REMOVED, before=node))
                for node in after_children[j1:j2]:
                    self.diffs.append(DiffEntry(type=DiffType.ADDED, after=node))

    def _nodes_differ(self, before: MarkdownNode, after: MarkdownNode) -> bool:
        """Check if two nodes have different content."""
        if type(before) != type(after):
            return True

        if isinstance(before, Heading):
            return before.level != after.level or self._content_differs(before, after)

        if isinstance(before, Paragraph):
            return self._content_differs(before, after)

        if isinstance(before, Text):
            return before.content != after.content

        return False

    def _content_differs(self, before: MarkdownNode, after: MarkdownNode) -> bool:
        """Check if node content differs."""
        before_text = self._extract_text(before.children)
        after_text = self._extract_text(after.children)
        return before_text != after_text

    @staticmethod
    def _extract_text(nodes: list) -> str:
        """Extract text from nodes."""
        text = []
        for node in nodes:
            if isinstance(node, Text):
                text.append(node.content)
            elif hasattr(node, "children"):
                text.append(MarkdownDiff._extract_text(node.children))
        return "".join(text)

    def unified_diff(self, before: str | Document, after: str | Document, filename: str = "document.md") -> list[str]:
        """Generate unified diff output.

        Args:
            before: Original document
            after: Modified document
            filename: Filename for diff header

        Returns:
            List of unified diff lines
        """
        # Convert to text for text-based diff
        if isinstance(before, Document):
            renderer = TextRenderer()
            before_text = renderer.render(before)
        else:
            before_text = before

        if isinstance(after, Document):
            renderer = TextRenderer()
            after_text = renderer.render(after)
        else:
            after_text = after

        before_lines = before_text.splitlines(keepends=True)
        after_lines = after_text.splitlines(keepends=True)

        diff = difflib.unified_diff(before_lines, after_lines, fromfile=filename, tofile=filename, lineterm="")

        return list(diff)


class ThreeWayMerge:
    """Three-way merge for collaborative editing."""

    @staticmethod
    def merge(base: str | Document, ours: str | Document, theirs: str | Document) -> tuple[str, list[str]]:
        """Perform three-way merge.

        Args:
            base: Common ancestor version
            ours: Our changes
            theirs: Their changes

        Returns:
            Tuple of (merged_text, conflicts)
        """
        # Parse documents
        parser = Parser()
        if isinstance(base, str):
            base = parser.parse(base)
        if isinstance(ours, str):
            ours = parser.parse(ours)
        if isinstance(theirs, str):
            theirs = parser.parse(theirs)

        # Convert to text for merge
        renderer = TextRenderer()
        base_text = renderer.render(base).splitlines(keepends=True)
        ours_text = renderer.render(ours).splitlines(keepends=True)
        theirs_text = renderer.render(theirs).splitlines(keepends=True)

        # Three-way merge
        difflib.Differ()
        merged_lines = []
        conflicts = []

        # Use diff3-like approach
        list(difflib.SequenceMatcher(None, base_text, ours_text).get_opcodes())
        list(difflib.SequenceMatcher(None, base_text, theirs_text).get_opcodes())

        # Detect conflicts
        ThreeWayMerge._extract_changes(base_text, ours_text)
        ThreeWayMerge._extract_changes(base_text, theirs_text)

        for line_no in range(max(len(ours_text), len(theirs_text))):
            if line_no < len(ours_text) and line_no < len(theirs_text):
                if ours_text[line_no] == theirs_text[line_no]:
                    merged_lines.append(ours_text[line_no])
                else:
                    # Conflict
                    merged_lines.append(f"<<<<<<< OURS\n{ours_text[line_no]}=======\n")
                    merged_lines.append(f"{theirs_text[line_no]}>>>>>>> THEIRS\n")
                    conflicts.append(f"Conflict at line {line_no + 1}")
            elif line_no < len(ours_text):
                merged_lines.append(ours_text[line_no])
            else:
                merged_lines.append(theirs_text[line_no])

        merged_text = "".join(merged_lines)
        return merged_text, conflicts

    @staticmethod
    def _extract_changes(base: list[str], modified: list[str]) -> dict:
        """Extract change regions."""
        changes = {}
        sm = difflib.SequenceMatcher(None, base, modified)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag != "equal":
                changes[i1] = (tag, i2 - i1, j2 - j1)
        return changes


class ConflictResolver:
    """Help resolve merge conflicts."""

    @staticmethod
    def detect_conflicts(merged_text: str) -> list[tuple[int, str, str]]:
        """Detect conflict markers.

        Args:
            merged_text: Merged text with conflict markers

        Returns:
            List of (line_no, ours, theirs) tuples
        """
        conflicts = []

        lines = merged_text.split("\n")
        i = 0
        while i < len(lines):
            if lines[i].startswith("<<<<<<< OURS"):
                ours_lines = []
                i += 1
                while i < len(lines) and not lines[i].startswith("======="):
                    ours_lines.append(lines[i])
                    i += 1

                if i < len(lines):
                    i += 1  # Skip =======
                    theirs_lines = []
                    while i < len(lines) and not lines[i].startswith(">>>>>>> THEIRS"):
                        theirs_lines.append(lines[i])
                        i += 1

                    ours_text = "\n".join(ours_lines)
                    theirs_text = "\n".join(theirs_lines)
                    conflicts.append((i, ours_text, theirs_text))

                    if i < len(lines):
                        i += 1  # Skip >>>>>>>
            else:
                i += 1

        return conflicts

    @staticmethod
    def resolve(merged_text: str, strategy: str = "ours") -> str:
        """Resolve all conflicts using strategy.

        Args:
            merged_text: Text with conflict markers
            strategy: 'ours', 'theirs', or 'both'

        Returns:
            Text with conflicts resolved
        """
        import re

        if strategy == "ours":
            # Keep ours, remove theirs
            pattern = r"<<<<<<< OURS\n(.*?)\n=======\n.*?\n>>>>>>> THEIRS\n"
            return re.sub(pattern, r"\1\n", merged_text, flags=re.DOTALL)

        elif strategy == "theirs":
            # Keep theirs, remove ours
            pattern = r"<<<<<<< OURS\n.*?\n=======\n(.*?)\n>>>>>>> THEIRS\n"
            return re.sub(pattern, r"\1\n", merged_text, flags=re.DOTALL)

        elif strategy == "both":
            # Keep both
            pattern = r"<<<<<<< OURS\n(.*?)\n=======\n(.*?)\n>>>>>>> THEIRS\n"
            return re.sub(pattern, r"\1\n\2\n", merged_text, flags=re.DOTALL)

        return merged_text
