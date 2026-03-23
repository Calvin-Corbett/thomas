"""Type system and AST node definitions for the Thomas compiler."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class TokenType(Enum):
    """Token types for the Thomas language."""

    # Literals
    INT_LIT = auto()
    FLOAT_LIT = auto()
    STRING_LIT = auto()
    TRUE = auto()
    FALSE = auto()
    NULL = auto()

    # Identifiers and keywords
    IDENT = auto()
    IF = auto()
    ELSE = auto()
    WHILE = auto()
    FOR = auto()
    RETURN = auto()
    FN = auto()
    LET = auto()
    AND = auto()
    OR = auto()
    NOT = auto()

    # Operators
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    PERCENT = auto()
    EQ = auto()
    NE = auto()
    LT = auto()
    GT = auto()
    LE = auto()
    GE = auto()
    ASSIGN = auto()
    PLUS_ASSIGN = auto()
    MINUS_ASSIGN = auto()
    LOGICAL_AND = auto()
    LOGICAL_OR = auto()

    # Delimiters
    LBRACE = auto()
    RBRACE = auto()
    LPAREN = auto()
    RPAREN = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    COMMA = auto()
    SEMICOLON = auto()
    COLON = auto()
    ARROW = auto()

    # Special
    EOF = auto()
    NEWLINE = auto()


@dataclass(frozen=True)
class SourceLocation:
    """Source code location."""

    line: int
    column: int
    filename: str = "<source>"

    def __str__(self) -> str:
        return f"{self.filename}:{self.line}:{self.column}"


@dataclass(frozen=True)
class Token:
    """A lexical token."""

    type: TokenType
    value: Any
    location: SourceLocation

    def __str__(self) -> str:
        if self.value is not None:
            return f"{self.type.name}({self.value})"
        return self.type.name


class ASTNode(ABC):
    """Base class for all AST nodes."""

    location: SourceLocation

    @abstractmethod
    def accept(self, visitor: ASTVisitor) -> Any:
        """Accept a visitor for the visitor pattern."""
        pass


class ASTVisitor(ABC):
    """Visitor pattern interface for AST traversal."""

    pass


@dataclass
class Program(ASTNode):
    """Root AST node."""

    declarations: list[ASTNode]
    location: SourceLocation

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_program(self)


@dataclass
class FuncDecl(ASTNode):
    """Function declaration: fn name(param: type, ...) -> return_type { ... }"""

    name: str
    params: list[tuple[str, Type]]  # (name, type)
    return_type: Type
    body: Block
    location: SourceLocation

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_func_decl(self)


@dataclass
class VarDecl(ASTNode):
    """Variable declaration: let name: type = init_expr"""

    name: str
    var_type: Type
    init_expr: ASTNode | None
    location: SourceLocation

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_var_decl(self)


@dataclass
class Block(ASTNode):
    """Block of statements."""

    statements: list[ASTNode]
    location: SourceLocation

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_block(self)


@dataclass
class IfStmt(ASTNode):
    """If statement: if (cond) { ... } else { ... }"""

    condition: ASTNode
    then_branch: Block
    else_branch: Block | None
    location: SourceLocation

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_if_stmt(self)


@dataclass
class WhileStmt(ASTNode):
    """While loop: while (cond) { ... }"""

    condition: ASTNode
    body: Block
    location: SourceLocation

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_while_stmt(self)


@dataclass
class ForStmt(ASTNode):
    """For loop: for (init; cond; update) { ... }"""

    init: ASTNode | None
    condition: ASTNode | None
    update: ASTNode | None
    body: Block
    location: SourceLocation

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_for_stmt(self)


@dataclass
class ReturnStmt(ASTNode):
    """Return statement."""

    value: ASTNode | None
    location: SourceLocation

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_return_stmt(self)


@dataclass
class AssignStmt(ASTNode):
    """Assignment: target = expr or target += expr"""

    target: str
    value: ASTNode
    op: TokenType  # ASSIGN, PLUS_ASSIGN, MINUS_ASSIGN
    location: SourceLocation

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_assign_stmt(self)


@dataclass
class IndexAssignStmt(ASTNode):
    """Array index assignment: arr[index] = value"""

    target: str
    index: ASTNode
    value: ASTNode
    location: SourceLocation

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_index_assign_stmt(self)


@dataclass
class ExprStmt(ASTNode):
    """Expression statement."""

    expr: ASTNode
    location: SourceLocation

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_expr_stmt(self)


@dataclass
class BinaryExpr(ASTNode):
    """Binary expression: left op right"""

    left: ASTNode
    op: TokenType
    right: ASTNode
    location: SourceLocation

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_binary_expr(self)


@dataclass
class UnaryExpr(ASTNode):
    """Unary expression: op operand"""

    op: TokenType
    operand: ASTNode
    location: SourceLocation

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_unary_expr(self)


@dataclass
class CallExpr(ASTNode):
    """Function call: name(arg1, arg2, ...)"""

    name: str
    args: list[ASTNode]
    location: SourceLocation

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_call_expr(self)


@dataclass
class IndexExpr(ASTNode):
    """Array indexing: arr[index]"""

    target: str
    index: ASTNode
    location: SourceLocation

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_index_expr(self)


@dataclass
class ArrayLit(ASTNode):
    """Array literal: [1, 2, 3] or [0; 5] for 5 zeros"""

    elements: list[ASTNode]
    location: SourceLocation

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_array_lit(self)


@dataclass
class Identifier(ASTNode):
    """Variable identifier."""

    name: str
    location: SourceLocation

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_identifier(self)


@dataclass
class IntLit(ASTNode):
    """Integer literal."""

    value: int
    location: SourceLocation

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_int_lit(self)


@dataclass
class FloatLit(ASTNode):
    """Float literal."""

    value: float
    location: SourceLocation

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_float_lit(self)


@dataclass
class StringLit(ASTNode):
    """String literal."""

    value: str
    location: SourceLocation

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_string_lit(self)


@dataclass
class BoolLit(ASTNode):
    """Boolean literal."""

    value: bool
    location: SourceLocation

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_bool_lit(self)


@dataclass
class NullLit(ASTNode):
    """Null literal."""

    location: SourceLocation

    def accept(self, visitor: ASTVisitor) -> Any:
        return visitor.visit_null_lit(self)


# Type system


class Type(ABC):
    """Base class for types."""

    @abstractmethod
    def __str__(self) -> str:
        pass

    @abstractmethod
    def __eq__(self, other: Any) -> bool:
        pass

    @abstractmethod
    def __hash__(self) -> int:
        pass


@dataclass(frozen=True)
class IntType(Type):
    """Integer type."""

    def __str__(self) -> str:
        return "int"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, IntType)

    def __hash__(self) -> int:
        return hash("int")


@dataclass(frozen=True)
class FloatType(Type):
    """Float type."""

    def __str__(self) -> str:
        return "float"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, FloatType)

    def __hash__(self) -> int:
        return hash("float")


@dataclass(frozen=True)
class BoolType(Type):
    """Boolean type."""

    def __str__(self) -> str:
        return "bool"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, BoolType)

    def __hash__(self) -> int:
        return hash("bool")


@dataclass(frozen=True)
class StringType(Type):
    """String type."""

    def __str__(self) -> str:
        return "string"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, StringType)

    def __hash__(self) -> int:
        return hash("string")


@dataclass(frozen=True)
class VoidType(Type):
    """Void type (no value)."""

    def __str__(self) -> str:
        return "void"

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, VoidType)

    def __hash__(self) -> int:
        return hash("void")


@dataclass(frozen=True)
class ArrayType(Type):
    """Array type: int[], float[], etc."""

    element_type: Type

    def __str__(self) -> str:
        return f"{self.element_type}[]"

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, ArrayType):
            return False
        return self.element_type == other.element_type

    def __hash__(self) -> int:
        return hash(("array", self.element_type))


@dataclass(frozen=True)
class FuncType(Type):
    """Function type: (int, string) -> float"""

    param_types: tuple[Type, ...]
    return_type: Type

    def __str__(self) -> str:
        params = ", ".join(str(t) for t in self.param_types)
        return f"({params}) -> {self.return_type}"

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, FuncType):
            return False
        return self.param_types == other.param_types and self.return_type == other.return_type

    def __hash__(self) -> int:
        return hash(("func", self.param_types, self.return_type))


# Keyword and operator mappings
KEYWORDS: dict[str, TokenType] = {
    "if": TokenType.IF,
    "else": TokenType.ELSE,
    "while": TokenType.WHILE,
    "for": TokenType.FOR,
    "return": TokenType.RETURN,
    "fn": TokenType.FN,
    "let": TokenType.LET,
    "true": TokenType.TRUE,
    "false": TokenType.FALSE,
    "null": TokenType.NULL,
    "and": TokenType.AND,
    "or": TokenType.OR,
    "not": TokenType.NOT,
}
