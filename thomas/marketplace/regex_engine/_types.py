"""
Type definitions and AST nodes for the regex engine.

Includes AST node hierarchy, match results, flags, and configuration.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Flag, auto


class RegexFlags(Flag):
    """Flags for regex compilation and matching."""

    IGNORECASE = auto()
    MULTILINE = auto()
    DOTALL = auto()
    VERBOSE = auto()


@dataclass
class CompileConfig:
    """Configuration for regex compilation."""

    flags: RegexFlags = RegexFlags(0)
    use_nfa: bool = True
    use_backtracking: bool = True
    dfa_minimize: bool = True
    cache_size: int = 128


@dataclass
class MatchResult:
    """Result of a regex match operation."""

    matched: bool
    groups: tuple[str | None, ...] = ()
    start: int = 0
    end: int = 0

    @property
    def span(self) -> tuple[int, int]:
        """Return (start, end) span of match."""
        return (self.start, self.end)

    @property
    def group(self) -> str | None:
        """Return the entire matched string."""
        return self.groups[0] if self.groups else None


# AST Node Base Class


class ASTNode(ABC):
    """Base class for all AST nodes."""

    @abstractmethod
    def __repr__(self) -> str:
        """Return string representation of node."""
        pass


# Literal Nodes


@dataclass
class Literal(ASTNode):
    """Represents a literal character."""

    char: str

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Literal({repr(self.char)})"


@dataclass
class Dot(ASTNode):
    """Represents . (any character except newline)."""

    def __repr__(self) -> str:
        """Return string representation."""
        return "Dot()"


# Character Classes


@dataclass
class CharClass(ASTNode):
    """Represents a character class [abc] or [^abc]."""

    chars: set[str] = field(default_factory=set)
    ranges: list[tuple[str, str]] = field(default_factory=list)
    negated: bool = False
    escape_classes: set[str] = field(default_factory=set)  # \d, \w, \s, etc.

    def __repr__(self) -> str:
        """Return string representation."""
        neg = "^" if self.negated else ""
        return f"CharClass({neg}{self.chars})"


# Anchors


@dataclass
class Anchor(ASTNode):
    """Represents anchors ^ and $."""

    anchor_type: str  # "start", "end", "word_boundary", "non_word_boundary"

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Anchor({self.anchor_type})"


# Quantifiers


@dataclass
class Quantifier(ASTNode):
    """Represents a quantifier applied to a node."""

    node: ASTNode
    min_count: int
    max_count: int | None
    lazy: bool = False

    def __repr__(self) -> str:
        """Return string representation."""
        lazy_str = "?" if self.lazy else ""
        if self.max_count is None:
            quant = f"{{{self.min_count},}}{lazy_str}"
        elif self.min_count == self.max_count:
            quant = f"{{{self.min_count}}}{lazy_str}"
        else:
            quant = f"{{{self.min_count},{self.max_count}}}{lazy_str}"
        return f"Quantifier({self.node}, {quant})"


# Structural Nodes


@dataclass
class Concatenation(ASTNode):
    """Represents sequential nodes."""

    nodes: list[ASTNode] = field(default_factory=list)

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Concatenation({self.nodes})"


@dataclass
class Alternation(ASTNode):
    """Represents alternatives (a|b)."""

    nodes: list[ASTNode] = field(default_factory=list)

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Alternation({self.nodes})"


@dataclass
class Group(ASTNode):
    """Represents a capturing group (...)."""

    node: ASTNode
    group_id: int = 0
    is_capturing: bool = True  # False for (?:...)

    def __repr__(self) -> str:
        """Return string representation."""
        cap = "capturing" if self.is_capturing else "non-capturing"
        return f"Group({self.node}, {cap}, id={self.group_id})"


@dataclass
class Backreference(ASTNode):
    """Represents a backreference \\1, \\2, etc."""

    group_id: int

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Backreference({self.group_id})"


# Special nodes for lookahead/lookbehind (future expansion)


@dataclass
class Lookahead(ASTNode):
    """Represents positive lookahead (?=...)."""

    node: ASTNode
    negative: bool = False

    def __repr__(self) -> str:
        """Return string representation."""
        neg = "negative" if self.negative else "positive"
        return f"Lookahead({self.node}, {neg})"


@dataclass
class Lookbehind(ASTNode):
    """Represents positive lookbehind (?<=...)."""

    node: ASTNode
    negative: bool = False

    def __repr__(self) -> str:
        """Return string representation."""
        neg = "negative" if self.negative else "positive"
        return f"Lookbehind({self.node}, {neg})"
