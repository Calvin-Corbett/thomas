"""Type definitions and AST nodes for DSL framework."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Union


class TokenType(Enum):
    """Token types for the lexer."""

    # Literals
    INT = auto()
    FLOAT = auto()
    STRING = auto()
    SYMBOL = auto()
    TRUE = auto()
    FALSE = auto()
    NONE = auto()

    # Identifiers and keywords
    IDENTIFIER = auto()
    KEYWORD = auto()

    # Operators
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    PERCENT = auto()
    POWER = auto()
    EQ = auto()
    NE = auto()
    LT = auto()
    LE = auto()
    GT = auto()
    GE = auto()
    AND = auto()
    OR = auto()
    NOT = auto()
    BIT_AND = auto()
    BIT_OR = auto()
    BIT_XOR = auto()
    BIT_NOT = auto()
    LSHIFT = auto()
    RSHIFT = auto()

    # Assignment and special operators
    ASSIGN = auto()
    PLUS_ASSIGN = auto()
    MINUS_ASSIGN = auto()
    STAR_ASSIGN = auto()
    SLASH_ASSIGN = auto()
    PIPE = auto()
    ARROW = auto()
    FAT_ARROW = auto()
    DOT = auto()
    DOUBLE_COLON = auto()

    # Delimiters
    LPAREN = auto()
    RPAREN = auto()
    LBRACE = auto()
    RBRACE = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    COMMA = auto()
    SEMICOLON = auto()
    COLON = auto()
    QUESTION = auto()

    # Keywords
    IF = auto()
    THEN = auto()
    ELSE = auto()
    ELIF = auto()
    WHILE = auto()
    FOR = auto()
    BREAK = auto()
    CONTINUE = auto()
    RETURN = auto()
    FN = auto()
    LET = auto()
    VAR = auto()
    CONST = auto()
    MATCH = auto()
    WITH = auto()
    CASE = auto()
    DEFAULT = auto()
    IMPORT = auto()
    EXPORT = auto()
    MODULE = auto()
    STRUCT = auto()
    ENUM = auto()
    TRAIT = auto()
    IMPL = auto()
    TYPE = auto()
    AS = auto()
    IN = auto()
    DO = auto()

    # Special
    EOF = auto()
    NEWLINE = auto()
    INDENT = auto()
    DEDENT = auto()
    ERROR = auto()


@dataclass
class Token:
    """Represents a lexical token."""

    type: TokenType
    value: Any
    line: int
    column: int
    filename: str = "<input>"

    def __repr__(self) -> str:
        """String representation of token."""
        return f"Token({self.type.name}, {self.value!r}, {self.line}, {self.column})"


class ASTNode(ABC):
    """Base class for all AST nodes."""

    @property
    @abstractmethod
    def location(self) -> tuple[int, int] | None:
        """Return (line, column) of node or None."""
        pass


@dataclass
class Literal(ASTNode):
    """Literal value: number, string, boolean, etc."""

    value: Any
    type_hint: str | None = None
    line: int = 0
    column: int = 0

    @property
    def location(self) -> tuple[int, int] | None:
        """Return location of literal."""
        return (self.line, self.column) if self.line > 0 else None


@dataclass
class Identifier(ASTNode):
    """Variable or function identifier."""

    name: str
    line: int = 0
    column: int = 0

    @property
    def location(self) -> tuple[int, int] | None:
        """Return location of identifier."""
        return (self.line, self.column) if self.line > 0 else None


@dataclass
class BinaryOp(ASTNode):
    """Binary operation: a op b."""

    left: ASTNode
    operator: str
    right: ASTNode
    line: int = 0
    column: int = 0

    @property
    def location(self) -> tuple[int, int] | None:
        """Return location of operation."""
        return (self.line, self.column) if self.line > 0 else None


@dataclass
class UnaryOp(ASTNode):
    """Unary operation: op a."""

    operator: str
    operand: ASTNode
    line: int = 0
    column: int = 0

    @property
    def location(self) -> tuple[int, int] | None:
        """Return location of operation."""
        return (self.line, self.column) if self.line > 0 else None


@dataclass
class FunctionCall(ASTNode):
    """Function call: func(args)."""

    function: ASTNode
    arguments: list[ASTNode] = field(default_factory=list)
    line: int = 0
    column: int = 0

    @property
    def location(self) -> tuple[int, int] | None:
        """Return location of call."""
        return (self.line, self.column) if self.line > 0 else None


@dataclass
class Assignment(ASTNode):
    """Variable assignment: name = value."""

    target: str
    value: ASTNode
    operator: str = "="
    line: int = 0
    column: int = 0

    @property
    def location(self) -> tuple[int, int] | None:
        """Return location of assignment."""
        return (self.line, self.column) if self.line > 0 else None


@dataclass
class IfExpr(ASTNode):
    """Conditional expression: if cond then expr else expr."""

    condition: ASTNode
    then_expr: ASTNode
    else_expr: ASTNode | None = None
    line: int = 0
    column: int = 0

    @property
    def location(self) -> tuple[int, int] | None:
        """Return location of if expression."""
        return (self.line, self.column) if self.line > 0 else None


@dataclass
class WhileLoop(ASTNode):
    """While loop: while cond do body."""

    condition: ASTNode
    body: ASTNode
    line: int = 0
    column: int = 0

    @property
    def location(self) -> tuple[int, int] | None:
        """Return location of while loop."""
        return (self.line, self.column) if self.line > 0 else None


@dataclass
class ForLoop(ASTNode):
    """For loop: for var in iterable do body."""

    variable: str
    iterable: ASTNode
    body: ASTNode
    line: int = 0
    column: int = 0

    @property
    def location(self) -> tuple[int, int] | None:
        """Return location of for loop."""
        return (self.line, self.column) if self.line > 0 else None


@dataclass
class Block(ASTNode):
    """Sequence of statements."""

    statements: list[ASTNode] = field(default_factory=list)
    line: int = 0
    column: int = 0

    @property
    def location(self) -> tuple[int, int] | None:
        """Return location of block."""
        return (self.line, self.column) if self.line > 0 else None


@dataclass
class LetBinding(ASTNode):
    """Let binding: let name = value in expr."""

    name: str
    value: ASTNode
    body: ASTNode
    mutable: bool = False
    line: int = 0
    column: int = 0

    @property
    def location(self) -> tuple[int, int] | None:
        """Return location of let binding."""
        return (self.line, self.column) if self.line > 0 else None


@dataclass
class LambdaExpr(ASTNode):
    """Lambda function: fn |params| body."""

    parameters: list[str] = field(default_factory=list)
    body: ASTNode | None = None
    line: int = 0
    column: int = 0

    @property
    def location(self) -> tuple[int, int] | None:
        """Return location of lambda."""
        return (self.line, self.column) if self.line > 0 else None


@dataclass
class FunctionDef(ASTNode):
    """Function definition: fn name(params) { body }."""

    name: str
    parameters: list[str] = field(default_factory=list)
    body: ASTNode | None = None
    return_type: str | None = None
    line: int = 0
    column: int = 0

    @property
    def location(self) -> tuple[int, int] | None:
        """Return location of function."""
        return (self.line, self.column) if self.line > 0 else None


@dataclass
class MatchExpr(ASTNode):
    """Pattern matching: match expr with patterns."""

    expr: ASTNode
    patterns: list[tuple[ASTNode, ASTNode]] = field(default_factory=list)
    default: ASTNode | None = None
    line: int = 0
    column: int = 0

    @property
    def location(self) -> tuple[int, int] | None:
        """Return location of match expression."""
        return (self.line, self.column) if self.line > 0 else None


@dataclass
class IndexExpr(ASTNode):
    """Index expression: obj[index]."""

    object: ASTNode
    index: ASTNode
    line: int = 0
    column: int = 0

    @property
    def location(self) -> tuple[int, int] | None:
        """Return location of index expression."""
        return (self.line, self.column) if self.line > 0 else None


@dataclass
class ListExpr(ASTNode):
    """List literal: [a, b, c]."""

    elements: list[ASTNode] = field(default_factory=list)
    line: int = 0
    column: int = 0

    @property
    def location(self) -> tuple[int, int] | None:
        """Return location of list."""
        return (self.line, self.column) if self.line > 0 else None


@dataclass
class DictExpr(ASTNode):
    """Dict literal: {key: value, ...}."""

    pairs: list[tuple[ASTNode, ASTNode]] = field(default_factory=list)
    line: int = 0
    column: int = 0

    @property
    def location(self) -> tuple[int, int] | None:
        """Return location of dict."""
        return (self.line, self.column) if self.line > 0 else None


@dataclass
class ReturnExpr(ASTNode):
    """Return statement: return expr."""

    value: ASTNode | None = None
    line: int = 0
    column: int = 0

    @property
    def location(self) -> tuple[int, int] | None:
        """Return location of return statement."""
        return (self.line, self.column) if self.line > 0 else None


@dataclass
class BreakExpr(ASTNode):
    """Break statement: break."""

    line: int = 0
    column: int = 0

    @property
    def location(self) -> tuple[int, int] | None:
        """Return location of break statement."""
        return (self.line, self.column) if self.line > 0 else None


@dataclass
class ContinueExpr(ASTNode):
    """Continue statement: continue."""

    line: int = 0
    column: int = 0

    @property
    def location(self) -> tuple[int, int] | None:
        """Return location of continue statement."""
        return (self.line, self.column) if self.line > 0 else None


# Type system types
@dataclass
class DSLType:
    """Base class for DSL types."""

    pass


@dataclass
class SimpleType(DSLType):
    """Simple named type like Int, String."""

    name: str

    def __str__(self) -> str:
        """String representation."""
        return self.name

    def __eq__(self, other: Any) -> bool:
        """Check equality."""
        return isinstance(other, SimpleType) and self.name == other.name


@dataclass
class FunctionType(DSLType):
    """Function type: arg_type -> return_type."""

    arg_types: list[DSLType] = field(default_factory=list)
    return_type: DSLType | None = None

    def __str__(self) -> str:
        """String representation."""
        arg_str = " -> ".join(str(t) for t in self.arg_types)
        if self.return_type:
            return f"({arg_str}) -> {self.return_type}"
        return arg_str

    def __eq__(self, other: Any) -> bool:
        """Check equality."""
        if not isinstance(other, FunctionType):
            return False
        return self.arg_types == other.arg_types and self.return_type == other.return_type


@dataclass
class TypeVariable(DSLType):
    """Type variable for polymorphism."""

    name: str
    instance: DSLType | None = None

    def __str__(self) -> str:
        """String representation."""
        if self.instance:
            return str(self.instance)
        return f"'{self.name}"

    def __eq__(self, other: Any) -> bool:
        """Check equality."""
        return isinstance(other, TypeVariable) and self.name == other.name


@dataclass
class ListType(DSLType):
    """List type: [element_type]."""

    element_type: DSLType

    def __str__(self) -> str:
        """String representation."""
        return f"[{self.element_type}]"

    def __eq__(self, other: Any) -> bool:
        """Check equality."""
        return isinstance(other, ListType) and self.element_type == other.element_type


# Value types for runtime
Value = Union[
    None,
    bool,
    int,
    float,
    str,
    list[Any],
    dict[str, Any],
    Callable,
]


@dataclass
class Environment:
    """Lexical environment for variable bindings."""

    parent: Environment | None = None
    bindings: dict[str, Value] = field(default_factory=dict)
    types: dict[str, DSLType] = field(default_factory=dict)

    def define(self, name: str, value: Value, type_hint: DSLType | None = None) -> None:
        """Define a variable in this environment.

        Args:
            name: Variable name
            value: Variable value
            type_hint: Optional type annotation
        """
        self.bindings[name] = value
        if type_hint:
            self.types[name] = type_hint

    def get(self, name: str) -> Value:
        """Get variable value.

        Args:
            name: Variable name

        Returns:
            Variable value

        Raises:
            KeyError: If variable not found
        """
        if name in self.bindings:
            return self.bindings[name]
        if self.parent:
            return self.parent.get(name)
        raise KeyError(name)

    def set(self, name: str, value: Value) -> None:
        """Set variable value.

        Args:
            name: Variable name
            value: New value

        Raises:
            KeyError: If variable not found
        """
        if name in self.bindings:
            self.bindings[name] = value
            return
        if self.parent:
            self.parent.set(name, value)
            return
        raise KeyError(name)

    def lookup_type(self, name: str) -> DSLType | None:
        """Look up type of variable.

        Args:
            name: Variable name

        Returns:
            Type or None
        """
        if name in self.types:
            return self.types[name]
        if self.parent:
            return self.parent.lookup_type(name)
        return None


@dataclass
class DSLConfig:
    """Configuration for DSL behavior."""

    max_recursion_depth: int = 1000
    max_iterations: int = 1000000
    max_cycles: int = 10000000
    enable_tail_call_opt: bool = True
    enable_type_checking: bool = True
    enable_optimization: bool = True
    debug_mode: bool = False
    strict_types: bool = False
    allow_implicit_conversion: bool = True
    keywords: list[str] = field(
        default_factory=lambda: [
            "if",
            "then",
            "else",
            "elif",
            "while",
            "for",
            "in",
            "fn",
            "let",
            "var",
            "const",
            "return",
            "break",
            "continue",
            "match",
            "with",
            "case",
            "default",
            "do",
            "import",
            "export",
            "module",
            "struct",
            "enum",
            "trait",
            "impl",
            "type",
            "as",
            "true",
            "false",
            "none",
        ]
    )
