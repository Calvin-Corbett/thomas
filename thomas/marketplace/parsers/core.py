"""Parser combinators for tokenization, grammar rules, and AST generation.

Provides functional parser combinators, tokenizers, grammar rules,
and AST (Abstract Syntax Tree) generation.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any


class TokenType(Enum):
    """Token types."""

    IDENTIFIER = "identifier"
    NUMBER = "number"
    STRING = "string"
    OPERATOR = "operator"
    KEYWORD = "keyword"
    PUNCTUATION = "punctuation"
    WHITESPACE = "whitespace"
    EOF = "eof"


@dataclass
class Token:
    """Lexical token."""

    type: TokenType
    value: str
    line: int
    column: int


@dataclass
class ASTNode:
    """Abstract Syntax Tree node."""

    node_type: str
    value: Any
    children: list["ASTNode"] = None
    metadata: dict = None

    def __post_init__(self):
        if self.children is None:
            self.children = []
        if self.metadata is None:
            self.metadata = {}

    def add_child(self, child: "ASTNode") -> None:
        """Add child node."""
        self.children.append(child)


class Tokenizer:
    """Lexical analyzer."""

    def __init__(self):
        self.keywords = {"if", "else", "while", "for", "return"}
        self.operators = {"+", "-", "*", "/", "=", "==", "!="}

    def tokenize(self, source: str) -> list[Token]:
        """Tokenize source code."""
        tokens = []
        line, column = 1, 1
        i = 0

        while i < len(source):
            char = source[i]

            if char.isspace():
                if char == "\n":
                    line += 1
                    column = 1
                else:
                    column += 1
                i += 1
                continue

            if char.isalpha() or char == "_":
                # Identifier or keyword
                start = i
                while i < len(source) and (source[i].isalnum() or source[i] == "_"):
                    i += 1
                value = source[start:i]
                token_type = TokenType.KEYWORD if value in self.keywords else TokenType.IDENTIFIER
                tokens.append(Token(token_type, value, line, column))
                column += i - start
                continue

            if char.isdigit():
                # Number
                start = i
                while i < len(source) and source[i].isdigit():
                    i += 1
                value = source[start:i]
                tokens.append(Token(TokenType.NUMBER, value, line, column))
                column += i - start
                continue

            if char == '"':
                # String
                i += 1
                start = i
                while i < len(source) and source[i] != '"':
                    i += 1
                value = source[start:i]
                tokens.append(Token(TokenType.STRING, value, line, column))
                i += 1
                column += i - start + 1
                continue

            if char in self.operators:
                # Operator
                tokens.append(Token(TokenType.OPERATOR, char, line, column))
                i += 1
                column += 1
                continue

            if char in "(){}[];:,.":
                # Punctuation
                tokens.append(Token(TokenType.PUNCTUATION, char, line, column))
                i += 1
                column += 1
                continue

            i += 1
            column += 1

        tokens.append(Token(TokenType.EOF, "", line, column))
        return tokens


class Parser:
    """Base parser."""

    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def peek(self, offset: int = 0) -> Token | None:
        """Peek at token."""
        index = self.pos + offset
        if index < len(self.tokens):
            return self.tokens[index]
        return None

    def advance(self) -> Token | None:
        """Consume and return current token."""
        token = self.peek()
        if token:
            self.pos += 1
        return token

    def expect(self, token_type: TokenType) -> Token | None:
        """Expect token type."""
        token = self.peek()
        if token and token.type == token_type:
            return self.advance()
        return None

    def is_at_end(self) -> bool:
        """Check if at end of tokens."""
        return self.peek() and self.peek().type == TokenType.EOF


class ExpressionParser(Parser):
    """Simple expression parser."""

    def parse(self) -> ASTNode | None:
        """Parse expression."""
        return self.parse_additive()

    def parse_additive(self) -> ASTNode | None:
        """Parse addition/subtraction."""
        left = self.parse_multiplicative()

        while self.peek() and self.peek().value in ["+", "-"]:
            op_token = self.advance()
            right = self.parse_multiplicative()
            left = ASTNode(node_type="binary_op", value=op_token.value, children=[left, right])

        return left

    def parse_multiplicative(self) -> ASTNode | None:
        """Parse multiplication/division."""
        left = self.parse_primary()

        while self.peek() and self.peek().value in ["*", "/"]:
            op_token = self.advance()
            right = self.parse_primary()
            left = ASTNode(node_type="binary_op", value=op_token.value, children=[left, right])

        return left

    def parse_primary(self) -> ASTNode | None:
        """Parse primary expression."""
        token = self.peek()

        if not token:
            return None

        if token.type == TokenType.NUMBER:
            self.advance()
            return ASTNode(node_type="number", value=token.value)

        if token.type == TokenType.IDENTIFIER:
            self.advance()
            return ASTNode(node_type="identifier", value=token.value)

        if token.type == TokenType.PUNCTUATION and token.value == "(":
            self.advance()
            expr = self.parse()
            self.expect(TokenType.PUNCTUATION)  # )
            return expr

        return None


class ASTVisitor(ABC):
    """AST visitor for traversal."""

    @abstractmethod
    def visit(self, node: ASTNode) -> Any:
        """Visit node."""
        pass


class EvaluatorVisitor(ASTVisitor):
    """Evaluator visitor."""

    def __init__(self):
        self.context = {}

    def visit(self, node: ASTNode) -> Any:
        """Evaluate node."""
        if node.node_type == "number":
            return float(node.value)

        if node.node_type == "identifier":
            return self.context.get(node.value, 0)

        if node.node_type == "binary_op":
            left = self.visit(node.children[0])
            right = self.visit(node.children[1])

            if node.value == "+":
                return left + right
            elif node.value == "-":
                return left - right
            elif node.value == "*":
                return left * right
            elif node.value == "/":
                return left / right if right != 0 else 0

        return 0


class GrammarRule:
    """Grammar rule definition."""

    def __init__(self, name: str, pattern: Callable):
        self.name = name
        self.pattern = pattern

    def match(self, parser: Parser) -> ASTNode | None:
        """Match rule."""
        return self.pattern(parser)


class Grammar:
    """Grammar definition."""

    def __init__(self):
        self.rules: dict = {}

    def add_rule(self, rule: GrammarRule) -> None:
        """Add grammar rule."""
        self.rules[rule.name] = rule

    def get_rule(self, name: str) -> GrammarRule | None:
        """Get rule by name."""
        return self.rules.get(name)
