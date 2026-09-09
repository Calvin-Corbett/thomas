"""Type definitions and data structures for the template engine."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class TokenType(Enum):
    """Template token types."""

    # Literals
    TEXT = auto()
    # Delimiters
    VAR_START = auto()  # {{
    VAR_END = auto()  # }}
    BLOCK_START = auto()  # {%
    BLOCK_END = auto()  # %}
    COMMENT_START = auto()  # {#
    COMMENT_END = auto()  # #}
    # Keywords
    FOR = auto()
    ENDFOR = auto()
    IF = auto()
    ELIF = auto()
    ELSE = auto()
    ENDIF = auto()
    BLOCK = auto()
    ENDBLOCK = auto()
    EXTENDS = auto()
    INCLUDE = auto()
    IMPORT = auto()
    FROM = auto()
    MACRO = auto()
    ENDMACRO = auto()
    CALL = auto()
    ENDCALL = auto()
    FILTER = auto()
    ENDFILTER = auto()
    SET = auto()
    ENDSET = auto()
    WITH = auto()
    # Operators and punctuation
    PIPE = auto()  # |
    COMMA = auto()
    COLON = auto()
    DOT = auto()
    LPAREN = auto()
    RPAREN = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    LBRACE = auto()
    RBRACE = auto()
    ASSIGN = auto()  # =
    EQ = auto()  # ==
    NE = auto()  # !=
    LT = auto()  # <
    LE = auto()  # <=
    GT = auto()  # >
    GE = auto()  # >=
    PLUS = auto()  # +
    MINUS = auto()  # -
    MUL = auto()  # *
    DIV = auto()  # /
    MOD = auto()  # %
    POW = auto()  # **
    AND = auto()
    OR = auto()
    NOT = auto()
    IN = auto()
    IS = auto()
    TRUE = auto()
    FALSE = auto()
    NONE = auto()
    # Special
    NAME = auto()
    NUMBER = auto()
    STRING = auto()
    NEWLINE = auto()
    EOF = auto()


@dataclass
class Token:
    """A lexical token."""

    type: TokenType
    value: Any
    lineno: int
    col: int = 0

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Token({self.type.name}, {self.value!r}, line {self.lineno})"


# Template AST Node types
class TemplateNode(ABC):
    """Base class for AST nodes."""

    lineno: int

    @abstractmethod
    def accept(self, visitor: Any) -> Any:
        """Accept a visitor."""
        pass


@dataclass
class Text(TemplateNode):
    """Plain text node."""

    value: str
    lineno: int = 0

    def accept(self, visitor: Any) -> Any:
        """Accept visitor."""
        return visitor.visit_text(self)


@dataclass
class Variable(TemplateNode):
    """Variable interpolation: {{ expr }}."""

    name: str
    filters: list[tuple[str, list[Any]]] = field(default_factory=list)
    lineno: int = 0

    def accept(self, visitor: Any) -> Any:
        """Accept visitor."""
        return visitor.visit_variable(self)


@dataclass
class Block(TemplateNode):
    """Named block for inheritance: {% block name %}...{% endblock %}."""

    name: str
    body: list[TemplateNode] = field(default_factory=list)
    lineno: int = 0

    def accept(self, visitor: Any) -> Any:
        """Accept visitor."""
        return visitor.visit_block(self)


@dataclass
class ForLoop(TemplateNode):
    """For loop: {% for var in iterable %}...{% endfor %}."""

    target: str  # loop variable name
    iter: str  # expression to iterate
    body: list[TemplateNode] = field(default_factory=list)
    orelse: list[TemplateNode] = field(default_factory=list)  # else clause
    lineno: int = 0

    def accept(self, visitor: Any) -> Any:
        """Accept visitor."""
        return visitor.visit_for(self)


@dataclass
class IfBlock(TemplateNode):
    """If/elif/else block: {% if %}...{% elif %}...{% else %}...{% endif %}."""

    tests: list[tuple[str | None, list[TemplateNode]]] = field(default_factory=list)
    # List of (condition, body) tuples. None condition = else block
    lineno: int = 0

    def accept(self, visitor: Any) -> Any:
        """Accept visitor."""
        return visitor.visit_if(self)


@dataclass
class Include(TemplateNode):
    """Include another template: {% include 'file.html' %}."""

    template: str
    with_context: bool = True
    lineno: int = 0

    def accept(self, visitor: Any) -> Any:
        """Accept visitor."""
        return visitor.visit_include(self)


@dataclass
class Macro(TemplateNode):
    """Macro definition: {% macro name(args) %}...{% endmacro %}."""

    name: str
    args: list[str] = field(default_factory=list)
    defaults: dict[str, Any] = field(default_factory=dict)
    body: list[TemplateNode] = field(default_factory=list)
    lineno: int = 0

    def accept(self, visitor: Any) -> Any:
        """Accept visitor."""
        return visitor.visit_macro(self)


@dataclass
class Call(TemplateNode):
    """Macro call: {{ macro(args) }}."""

    name: str
    args: list[Any] = field(default_factory=list)
    kwargs: dict[str, Any] = field(default_factory=dict)
    lineno: int = 0

    def accept(self, visitor: Any) -> Any:
        """Accept visitor."""
        return visitor.visit_call(self)


@dataclass
class FilterBlock(TemplateNode):
    """Filter block: {% filter name %}...{% endfilter %}."""

    name: str
    args: list[Any] = field(default_factory=list)
    body: list[TemplateNode] = field(default_factory=list)
    lineno: int = 0

    def accept(self, visitor: Any) -> Any:
        """Accept visitor."""
        return visitor.visit_filter(self)


@dataclass
class Set(TemplateNode):
    """Variable assignment: {% set x = value %}."""

    target: str
    value: Any
    lineno: int = 0

    def accept(self, visitor: Any) -> Any:
        """Accept visitor."""
        return visitor.visit_set(self)


@dataclass
class Extends(TemplateNode):
    """Template inheritance: {% extends 'base.html' %}."""

    parent: str
    lineno: int = 0

    def accept(self, visitor: Any) -> Any:
        """Accept visitor."""
        return visitor.visit_extends(self)


@dataclass
class RawBlock(TemplateNode):
    """Raw text block: {% raw %}...{% endraw %}."""

    content: str
    lineno: int = 0

    def accept(self, visitor: Any) -> Any:
        """Accept visitor."""
        return visitor.visit_raw(self)


@dataclass
class Template(TemplateNode):
    """Root template node."""

    body: list[TemplateNode] = field(default_factory=list)
    lineno: int = 0

    def accept(self, visitor: Any) -> Any:
        """Accept visitor."""
        return visitor.visit_template(self)


# Context and configuration types
@dataclass
class Context:
    """Template rendering context."""

    variables: dict[str, Any] = field(default_factory=dict)
    parent: Context | None = None
    loop_stack: list[dict[str, Any]] = field(default_factory=list)
    macros: dict[str, Macro] = field(default_factory=dict)
    blocks: dict[str, list[TemplateNode]] = field(default_factory=dict)

    def get(self, name: str, default: Any = None) -> Any:
        """Get variable from context."""
        if name in self.variables:
            return self.variables[name]
        if self.parent:
            return self.parent.get(name, default)
        return default

    def set(self, name: str, value: Any) -> None:
        """Set variable in context."""
        self.variables[name] = value

    def push(self) -> Context:
        """Create child context."""
        return Context(parent=self)

    def loop_context(self) -> dict[str, Any] | None:
        """Get current loop context."""
        return self.loop_stack[-1] if self.loop_stack else None


class UndefinedBehavior(Enum):
    """How to handle undefined variables."""

    STRICT = "strict"  # Raise error
    LENIENT = "lenient"  # Return empty string
    DEBUG = "debug"  # Return "{{ undefined }}"


@dataclass
class TemplateConfig:
    """Template engine configuration."""

    # Delimiters
    var_open: str = "{{"
    var_close: str = "}}"
    block_open: str = "{%"
    block_close: str = "%}"
    comment_open: str = "{#"
    comment_close: str = "#}"

    # Features
    autoescape: bool = True
    undefined: UndefinedBehavior = UndefinedBehavior.LENIENT
    trim_blocks: bool = False
    lstrip_blocks: bool = False
    keep_trailing_newline: bool = False

    # Optimization
    cache_compiled: bool = True
    optimize: bool = True


# Filter and test function types
FilterFunc = Callable[[Any, ...], Any]
TestFunc = Callable[[Any, ...], bool]


@dataclass
class Extension:
    """Template engine extension."""

    name: str
    filters: dict[str, FilterFunc] = field(default_factory=dict)
    tests: dict[str, TestFunc] = field(default_factory=dict)
    tags: dict[str, Callable] = field(default_factory=dict)
    globals: dict[str, Any] = field(default_factory=dict)

    def before_render(self, context: Context) -> None:
        """Hook called before rendering."""
        pass

    def after_render(self, output: str, context: Context) -> str:
        """Hook called after rendering."""
        return output

    def on_error(self, error: Exception, context: Context) -> None:
        """Hook called on error."""
        pass
