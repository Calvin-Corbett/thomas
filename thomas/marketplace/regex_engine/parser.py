"""
Regex pattern parser.

Tokenizes regex patterns and builds AST using recursive descent parsing.
Handles all regex syntax: literals, character classes, quantifiers, groups, etc.
"""

from __future__ import annotations

from enum import Enum, auto

from ._exceptions import ParseError
from ._types import (
    Alternation,
    Anchor,
    ASTNode,
    Backreference,
    CharClass,
    Concatenation,
    Dot,
    Group,
    Literal,
    Quantifier,
)


class TokenType(Enum):
    """Token types for regex lexer."""

    LITERAL = auto()
    DOT = auto()
    CARET = auto()
    DOLLAR = auto()
    LPAREN = auto()
    RPAREN = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    PIPE = auto()
    STAR = auto()
    PLUS = auto()
    QUESTION = auto()
    LBRACE = auto()
    RBRACE = auto()
    BACKSLASH = auto()
    COMMA = auto()
    EOF = auto()


class Token:
    """Represents a lexical token."""

    def __init__(self, token_type: TokenType, value: str, position: int) -> None:
        """Initialize token."""
        self.type = token_type
        self.value = value
        self.position = position

    def __repr__(self) -> str:
        """Return string representation."""
        return f"Token({self.type}, {repr(self.value)}, {self.position})"


class Lexer:
    """Tokenizes regex patterns."""

    def __init__(self, pattern: str) -> None:
        """Initialize lexer with regex pattern."""
        self.pattern = pattern
        self.position = 0
        self.tokens: list[Token] = []

    def tokenize(self) -> list[Token]:
        """Tokenize the pattern."""
        while self.position < len(self.pattern):
            self._scan_token()
        self.tokens.append(Token(TokenType.EOF, "", self.position))
        return self.tokens

    def _scan_token(self) -> None:
        """Scan a single token."""
        char = self.pattern[self.position]
        pos = self.position

        if char == ".":
            self.tokens.append(Token(TokenType.DOT, ".", pos))
            self.position += 1
        elif char == "^":
            self.tokens.append(Token(TokenType.CARET, "^", pos))
            self.position += 1
        elif char == "$":
            self.tokens.append(Token(TokenType.DOLLAR, "$", pos))
            self.position += 1
        elif char == "(":
            self.tokens.append(Token(TokenType.LPAREN, "(", pos))
            self.position += 1
        elif char == ")":
            self.tokens.append(Token(TokenType.RPAREN, ")", pos))
            self.position += 1
        elif char == "[":
            self.tokens.append(Token(TokenType.LBRACKET, "[", pos))
            self.position += 1
        elif char == "]":
            self.tokens.append(Token(TokenType.RBRACKET, "]", pos))
            self.position += 1
        elif char == "|":
            self.tokens.append(Token(TokenType.PIPE, "|", pos))
            self.position += 1
        elif char == "*":
            self.tokens.append(Token(TokenType.STAR, "*", pos))
            self.position += 1
        elif char == "+":
            self.tokens.append(Token(TokenType.PLUS, "+", pos))
            self.position += 1
        elif char == "?":
            self.tokens.append(Token(TokenType.QUESTION, "?", pos))
            self.position += 1
        elif char == "{":
            self.tokens.append(Token(TokenType.LBRACE, "{", pos))
            self.position += 1
        elif char == "}":
            self.tokens.append(Token(TokenType.RBRACE, "}", pos))
            self.position += 1
        elif char == ",":
            self.tokens.append(Token(TokenType.COMMA, ",", pos))
            self.position += 1
        elif char == "\\":
            self.tokens.append(Token(TokenType.BACKSLASH, "\\", pos))
            self.position += 1
        else:
            # Literal character
            self.tokens.append(Token(TokenType.LITERAL, char, pos))
            self.position += 1


class Parser:
    """Parses regex patterns into AST."""

    def __init__(self, pattern: str) -> None:
        """Initialize parser with regex pattern."""
        self.pattern = pattern
        lexer = Lexer(pattern)
        self.tokens = lexer.tokenize()
        self.position = 0
        self.group_counter = 0

    def parse(self) -> ASTNode:
        """Parse the pattern into an AST."""
        result = self._parse_alternation()
        if not self._check(TokenType.EOF):
            raise ParseError(
                "Unexpected token at end of pattern",
                self.pattern,
                self.tokens[self.position].position,
            )
        return result

    def _parse_alternation(self) -> ASTNode:
        """Parse alternation (|) - lowest precedence."""
        nodes = [self._parse_concatenation()]

        while self._check(TokenType.PIPE):
            self._consume(TokenType.PIPE)
            nodes.append(self._parse_concatenation())

        if len(nodes) == 1:
            return nodes[0]
        return Alternation(nodes)

    def _parse_concatenation(self) -> ASTNode:
        """Parse concatenation - middle precedence."""
        nodes = []

        while not self._check_any(TokenType.PIPE, TokenType.RPAREN, TokenType.EOF):
            nodes.append(self._parse_quantified())

        if len(nodes) == 0:
            raise ParseError(
                "Empty expression",
                self.pattern,
                self.tokens[self.position].position,
            )
        if len(nodes) == 1:
            return nodes[0]
        return Concatenation(nodes)

    def _parse_quantified(self) -> ASTNode:
        """Parse a node with optional quantifier - highest precedence."""
        node = self._parse_primary()

        if self._check(TokenType.STAR):
            self._consume(TokenType.STAR)
            lazy = self._check(TokenType.QUESTION)
            if lazy:
                self._consume(TokenType.QUESTION)
            return Quantifier(node, min_count=0, max_count=None, lazy=lazy)

        elif self._check(TokenType.PLUS):
            self._consume(TokenType.PLUS)
            lazy = self._check(TokenType.QUESTION)
            if lazy:
                self._consume(TokenType.QUESTION)
            return Quantifier(node, min_count=1, max_count=None, lazy=lazy)

        elif self._check(TokenType.QUESTION):
            self._consume(TokenType.QUESTION)
            lazy = self._check(TokenType.QUESTION)
            if lazy:
                self._consume(TokenType.QUESTION)
            return Quantifier(node, min_count=0, max_count=1, lazy=lazy)

        elif self._check(TokenType.LBRACE):
            self._consume(TokenType.LBRACE)
            min_count, max_count = self._parse_quantifier_range()
            self._consume(TokenType.RBRACE)
            lazy = self._check(TokenType.QUESTION)
            if lazy:
                self._consume(TokenType.QUESTION)
            return Quantifier(node, min_count=min_count, max_count=max_count, lazy=lazy)

        return node

    def _parse_quantifier_range(self) -> tuple[int, int | None]:
        """Parse quantifier range {n}, {n,}, {n,m}."""
        if not self._check(TokenType.LITERAL):
            raise ParseError(
                "Expected number in quantifier",
                self.pattern,
                self.tokens[self.position].position,
            )

        # Parse first number
        min_count = 0
        while self._check(TokenType.LITERAL) and self._current().value.isdigit():
            min_count = min_count * 10 + int(self._consume(TokenType.LITERAL).value)

        if self._check(TokenType.RBRACE):
            return min_count, min_count

        self._consume(TokenType.COMMA)

        if self._check(TokenType.RBRACE):
            return min_count, None

        # Parse second number
        max_count = 0
        while self._check(TokenType.LITERAL) and self._current().value.isdigit():
            max_count = max_count * 10 + int(self._consume(TokenType.LITERAL).value)

        return min_count, max_count

    def _parse_primary(self) -> ASTNode:
        """Parse primary element (literal, dot, character class, anchor, group)."""
        if self._check(TokenType.DOT):
            self._consume(TokenType.DOT)
            return Dot()

        elif self._check(TokenType.CARET):
            self._consume(TokenType.CARET)
            return Anchor("start")

        elif self._check(TokenType.DOLLAR):
            self._consume(TokenType.DOLLAR)
            return Anchor("end")

        elif self._check(TokenType.LBRACKET):
            return self._parse_character_class()

        elif self._check(TokenType.LPAREN):
            return self._parse_group()

        elif self._check(TokenType.BACKSLASH):
            return self._parse_escape()

        elif self._check(TokenType.LITERAL):
            char = self._consume(TokenType.LITERAL).value
            return Literal(char)

        else:
            raise ParseError(
                f"Unexpected token: {self._current()}",
                self.pattern,
                self._current().position,
            )

    def _parse_character_class(self) -> CharClass:
        """Parse character class [abc], [^abc], [a-z], etc."""
        self._consume(TokenType.LBRACKET)

        negated = False
        if self._check(TokenType.CARET):
            self._consume(TokenType.CARET)
            negated = True

        chars: set[str] = set()
        ranges: list[tuple[str, str]] = []
        escape_classes: set[str] = set()

        # First character can be ] without closing the class
        if self._check(TokenType.RBRACKET):
            chars.add("]")
            self._consume(TokenType.RBRACKET)
            return CharClass(chars, ranges, negated, escape_classes)

        while not self._check(TokenType.RBRACKET):
            if self._check(TokenType.BACKSLASH):
                self._consume(TokenType.BACKSLASH)
                if self._check(TokenType.LITERAL):
                    escape_char = self._consume(TokenType.LITERAL).value
                    if escape_char in "dDwWsS":
                        escape_classes.add(escape_char)
                    else:
                        chars.add(self._unescape_char(escape_char))
                else:
                    raise ParseError(
                        "Invalid escape in character class",
                        self.pattern,
                        self._current().position,
                    )
            elif self._check(TokenType.LITERAL):
                char = self._consume(TokenType.LITERAL).value
                chars.add(char)

                # Check for range
                if self._check(TokenType.LITERAL) and self._peek_ahead(1).value == "-":
                    self._consume(TokenType.LITERAL)  # consume "-"
                    if self._check(TokenType.LITERAL):
                        end_char = self._consume(TokenType.LITERAL).value
                        ranges.append((char, end_char))
                    else:
                        raise ParseError(
                            "Invalid range in character class",
                            self.pattern,
                            self._current().position,
                        )
            else:
                raise ParseError(
                    "Invalid character class",
                    self.pattern,
                    self._current().position,
                )

        self._consume(TokenType.RBRACKET)
        return CharClass(chars, ranges, negated, escape_classes)

    def _parse_group(self) -> ASTNode:
        """Parse group (...), (?:...), (?=...), (?!...), etc."""
        self._consume(TokenType.LPAREN)

        is_capturing = True

        # Check for special group syntax
        if self._check(TokenType.QUESTION):
            self._consume(TokenType.QUESTION)

            if self._check(TokenType.LITERAL):
                special_char = self._current().value
                if special_char == ":":
                    # Non-capturing group (?:...)
                    self._consume(TokenType.LITERAL)
                    is_capturing = False
                elif special_char == "=":
                    # Positive lookahead (?=...)
                    self._consume(TokenType.LITERAL)
                elif special_char == "!":
                    # Negative lookahead (?!...)
                    self._consume(TokenType.LITERAL)
                else:
                    raise ParseError(
                        f"Unknown group type: (?{special_char}",
                        self.pattern,
                        self._current().position,
                    )
            else:
                raise ParseError(
                    "Invalid group syntax",
                    self.pattern,
                    self._current().position,
                )

        node = self._parse_alternation()
        self._consume(TokenType.RPAREN)

        if is_capturing:
            self.group_counter += 1
            return Group(node, group_id=self.group_counter, is_capturing=True)
        else:
            return Group(node, group_id=0, is_capturing=False)

    def _parse_escape(self) -> ASTNode:
        """Parse escape sequences \\d, \\w, \\s, \\b, backreferences, etc."""
        self._consume(TokenType.BACKSLASH)

        if not self._check(TokenType.LITERAL):
            raise ParseError(
                "Invalid escape sequence",
                self.pattern,
                self._current().position,
            )

        escape_char = self._consume(TokenType.LITERAL).value

        # Escape classes
        if escape_char == "d":
            return CharClass(chars=set(), ranges=[], escape_classes={"d"}, negated=False)
        elif escape_char == "D":
            return CharClass(chars=set(), ranges=[], escape_classes={"D"}, negated=False)
        elif escape_char == "w":
            return CharClass(chars=set(), ranges=[], escape_classes={"w"}, negated=False)
        elif escape_char == "W":
            return CharClass(chars=set(), ranges=[], escape_classes={"W"}, negated=False)
        elif escape_char == "s":
            return CharClass(chars=set(), ranges=[], escape_classes={"s"}, negated=False)
        elif escape_char == "S":
            return CharClass(chars=set(), ranges=[], escape_classes={"S"}, negated=False)

        # Anchors
        elif escape_char == "b":
            return Anchor("word_boundary")
        elif escape_char == "B":
            return Anchor("non_word_boundary")

        # Backreferences
        elif escape_char.isdigit():
            return Backreference(int(escape_char))

        # Special characters
        else:
            return Literal(self._unescape_char(escape_char))

    def _unescape_char(self, char: str) -> str:
        """Unescape a character."""
        escape_map = {
            "n": "\n",
            "t": "\t",
            "r": "\r",
            "f": "\f",
            "v": "\v",
            "0": "\0",
        }
        return escape_map.get(char, char)

    def _current(self) -> Token:
        """Get current token."""
        if self.position < len(self.tokens):
            return self.tokens[self.position]
        return self.tokens[-1]  # EOF

    def _peek_ahead(self, offset: int) -> Token:
        """Peek ahead offset tokens."""
        pos = self.position + offset
        if pos < len(self.tokens):
            return self.tokens[pos]
        return self.tokens[-1]  # EOF

    def _check(self, token_type: TokenType) -> bool:
        """Check if current token matches type."""
        return self._current().type == token_type

    def _check_any(self, *token_types: TokenType) -> bool:
        """Check if current token matches any type."""
        return any(self._check(t) for t in token_types)

    def _consume(self, token_type: TokenType) -> Token:
        """Consume and return token of given type."""
        token = self._current()
        if token.type != token_type:
            raise ParseError(
                f"Expected {token_type}, got {token.type}",
                self.pattern,
                token.position,
            )
        self.position += 1
        return token


def parse(pattern: str) -> ASTNode:
    """Parse a regex pattern into an AST."""
    parser = Parser(pattern)
    return parser.parse()
