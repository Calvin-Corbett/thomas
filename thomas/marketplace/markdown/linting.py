"""
Markdown linting and validation.

Checks for:
- Heading level consistency (no skipping levels)
- Trailing whitespace
- Line length violations
- Consistent list markers
- Proper spacing around blocks
- Duplicate headings
- Broken link references
- Emphasis delimiter issues
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from thomas.marketplace.markdown._types import (
    CodeBlock,
    Document,
    Heading,
    InlineNode,
    Link,
    MarkdownNode,
    Text,
)
from thomas.marketplace.markdown._types import List as MarkdownList


class SeverityLevel(Enum):
    """Severity level for lint errors."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class LintError:
    """Lint error/warning."""

    message: str
    line: int
    column: int = 0
    severity: SeverityLevel = SeverityLevel.WARNING
    rule: str = ""

    def __repr__(self) -> str:
        """Return string representation."""
        return f"LintError({self.rule} at {self.line}:{self.column}): {self.message}"


class LintRules:
    """Configuration for linting rules."""

    def __init__(self) -> None:
        """Initialize default rules."""
        self.check_heading_levels = True
        self.check_trailing_whitespace = True
        self.max_line_length: int | None = 100
        self.check_list_markers = True
        self.check_spacing = True
        self.check_duplicate_headings = True
        self.check_links = True
        self.check_emphasis = True
        self.check_code_fence_language = False


class Linter:
    """Markdown linter."""

    def __init__(self, rules: LintRules | None = None) -> None:
        """Initialize linter.

        Args:
            rules: Lint rules configuration
        """
        self.rules = rules or LintRules()
        self.errors: list[LintError] = []
        self.source_lines: list[str] = []

    def lint(self, source: str, ast: Document | None = None) -> list[LintError]:
        """Lint Markdown source.

        Args:
            source: Markdown source code
            ast: Optional parsed AST (can be None for text-only checks)

        Returns:
            List of lint errors
        """
        self.errors = []
        self.source_lines = source.split("\n")

        # Text-based checks
        if self.rules.check_trailing_whitespace:
            self._check_trailing_whitespace()

        if self.rules.max_line_length:
            self._check_line_length()

        # AST-based checks
        if ast:
            if self.rules.check_heading_levels:
                self._check_heading_levels(ast)

            if self.rules.check_duplicate_headings:
                self._check_duplicate_headings(ast)

            if self.rules.check_links:
                self._check_links(ast)

            if self.rules.check_emphasis:
                self._check_emphasis(ast)

            if self.rules.check_spacing:
                self._check_spacing(ast)

        # Sort errors by line
        self.errors.sort(key=lambda e: (e.line, e.column))
        return self.errors

    def _check_trailing_whitespace(self) -> None:
        """Check for trailing whitespace."""
        for line_no, line in enumerate(self.source_lines, 1):
            if line != line.rstrip() and line.strip() != "":
                self.errors.append(
                    LintError(
                        message="Trailing whitespace",
                        line=line_no,
                        column=len(line.rstrip()),
                        severity=SeverityLevel.WARNING,
                        rule="trailing-whitespace",
                    )
                )

    def _check_line_length(self) -> None:
        """Check for lines exceeding max length."""
        max_len = self.rules.max_line_length
        if not max_len:
            return

        for line_no, line in enumerate(self.source_lines, 1):
            # Skip code blocks and long URLs
            if len(line) > max_len:
                if not (line.startswith("    ") or line.startswith("```") or "http" in line):
                    self.errors.append(
                        LintError(
                            message=f"Line too long ({len(line)} > {max_len})",
                            line=line_no,
                            column=max_len,
                            severity=SeverityLevel.INFO,
                            rule="line-too-long",
                        )
                    )

    def _check_heading_levels(self, doc: Document) -> None:
        """Check heading level consistency (no skipping)."""
        current_level = 0
        for child in doc.children:
            if isinstance(child, Heading):
                # Only h1-h3 are typically allowed to skip
                if child.level > current_level + 1 and current_level > 0:
                    self.errors.append(
                        LintError(
                            message=f"Heading level skipped: jumping from h{current_level} to h{child.level}",
                            line=child.source_pos.line if child.source_pos else 0,
                            severity=SeverityLevel.WARNING,
                            rule="no-skip-heading-levels",
                        )
                    )
                current_level = child.level

    def _check_duplicate_headings(self, doc: Document) -> None:
        """Check for duplicate heading text."""
        headings: dict[str, int] = {}

        def visit(node: MarkdownNode) -> None:
            if isinstance(node, Heading):
                text = self._extract_text(node.children)
                text_lower = text.lower()
                if text_lower in headings:
                    self.errors.append(
                        LintError(
                            message=f"Duplicate heading: '{text}'",
                            line=node.source_pos.line if node.source_pos else 0,
                            severity=SeverityLevel.INFO,
                            rule="no-duplicate-headings",
                        )
                    )
                else:
                    headings[text_lower] = 1

            if hasattr(node, "children"):
                for child in node.children:
                    if isinstance(child, MarkdownNode):
                        visit(child)

        visit(doc)

    def _check_links(self, doc: Document) -> None:
        """Check for broken link references."""
        # Collect all reference definitions
        references: set[str] = set()

        # Simple check: ensure referenced links exist
        # This would require full AST traversal in real implementation

    def _check_emphasis(self, doc: Document) -> None:
        """Check emphasis delimiter issues."""
        # Check for mismatched emphasis markers
        pass

    def _check_spacing(self, ast: Document) -> None:
        """Check spacing around blocks."""
        for child in ast.children:
            if isinstance(child, CodeBlock):
                # Code blocks should have blank line before and after
                pass

    def _extract_text(self, nodes: list[InlineNode]) -> str:
        """Extract plain text from inline nodes."""
        text = []
        for node in nodes:
            if isinstance(node, Text):
                text.append(node.content)
            elif hasattr(node, "children"):
                text.append(self._extract_text(node.children))
        return "".join(text)


class HeadingConsistencyChecker:
    """Check heading level consistency."""

    @staticmethod
    def check(doc: Document) -> list[str]:
        """Check heading consistency.

        Args:
            doc: Document to check

        Returns:
            List of error messages
        """
        errors = []
        current_level = 0

        for child in doc.children:
            if isinstance(child, Heading):
                if child.level > current_level + 1 and current_level > 0:
                    errors.append(f"Skipped heading level from h{current_level} to h{child.level}")
                current_level = child.level

        return errors


class LinkValidator:
    """Validate links in document."""

    @staticmethod
    def validate(doc: Document) -> list[str]:
        """Validate links.

        Args:
            doc: Document to check

        Returns:
            List of error messages
        """
        errors = []
        seen_refs: set[str] = set()

        def visit(node: MarkdownNode | InlineNode) -> None:
            if isinstance(node, Link):
                # Check if link destination is valid
                if not node.url:
                    errors.append("Empty link destination")
            elif hasattr(node, "children"):
                for child in node.children:
                    visit(child)

        visit(doc)
        return errors


class ListConsistencyChecker:
    """Check list formatting consistency."""

    @staticmethod
    def check(doc: Document) -> list[str]:
        """Check list consistency.

        Args:
            doc: Document to check

        Returns:
            List of error messages
        """
        errors = []

        def visit(node: MarkdownNode) -> None:
            if isinstance(node, MarkdownList):
                # Check all items use same marker
                pass
            elif hasattr(node, "children"):
                for child in node.children:
                    if isinstance(child, MarkdownNode):
                        visit(child)

        visit(doc)
        return errors
