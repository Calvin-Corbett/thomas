"""Cypher-subset query lexer and tokenizer."""

from enum import Enum
from typing import Any

from thomas.marketplace.graphdb._exceptions import QuerySyntaxError


class TokenType(Enum):
    """Token types for the lexer."""

    # Keywords
    MATCH = "MATCH"
    WHERE = "WHERE"
    RETURN = "RETURN"
    CREATE = "CREATE"
    DELETE = "DELETE"
    SET = "SET"
    ORDER = "ORDER"
    BY = "BY"
    LIMIT = "LIMIT"
    SKIP = "SKIP"
    AND = "AND"
    OR = "OR"
    NOT = "NOT"
    AS = "AS"
    DISTINCT = "DISTINCT"
    ASC = "ASC"
    DESC = "DESC"

    # Operators
    COLON = "COLON"
    LPAREN = "LPAREN"
    RPAREN = "RPAREN"
    LBRACE = "LBRACE"
    RBRACE = "RBRACE"
    LBRACKET = "LBRACKET"
    RBRACKET = "RBRACKET"
    COMMA = "COMMA"
    DOT = "DOT"
    ARROW = "ARROW"
    LEFT_ARROW = "LEFT_ARROW"
    DASH = "DASH"
    EQUALS = "EQUALS"
    LT = "LT"
    GT = "GT"
    LTE = "LTE"
    GTE = "GTE"
    NEQ = "NEQ"
    PLUS = "PLUS"
    MINUS = "MINUS"
    STAR = "STAR"
    SLASH = "SLASH"

    # Literals
    IDENTIFIER = "IDENTIFIER"
    INTEGER = "INTEGER"
    FLOAT = "FLOAT"
    STRING = "STRING"
    TRUE = "TRUE"
    FALSE = "FALSE"
    NULL = "NULL"

    # Special
    EOF = "EOF"
    UNKNOWN = "UNKNOWN"


@staticmethod
def _keyword(keyword: str) -> TokenType:
    """Get token type for keyword.

    Args:
        keyword: The keyword string to classify

    Returns:
        TokenType: The appropriate token type for the keyword
    """
    keywords: dict[str, TokenType] = {
        "MATCH": TokenType.MATCH,
        "WHERE": TokenType.WHERE,
        "RETURN": TokenType.RETURN,
        "CREATE": TokenType.CREATE,
        "DELETE": TokenType.DELETE,
        "SET": TokenType.SET,
        "ORDER": TokenType.ORDER,
        "BY": TokenType.BY,
        "LIMIT": TokenType.LIMIT,
        "SKIP": TokenType.SKIP,
        "AND": TokenType.AND,
        "OR": TokenType.OR,
        "NOT": TokenType.NOT,
        "AS": TokenType.AS,
        "DISTINCT": TokenType.DISTINCT,
        "ASC": TokenType.ASC,
        "DESC": TokenType.DESC,
        "TRUE": TokenType.TRUE,
        "FALSE": TokenType.FALSE,
        "NULL": TokenType.NULL,
    }
    return keywords.get(keyword.upper(), TokenType.IDENTIFIER)


class Token:
    """Represents a token in the query."""

    def __init__(self, type_: TokenType, value: Any, position: int) -> None:
        """Initialize a token.

        Args:
            type_: Token type
            value: Token value
            position: Position in input string
        """
        self.type: TokenType = type_
        self.value: Any = value
        self.position: int = position

    def __repr__(self) -> str:
        """String representation.

        Returns:
            str: A string representation of the token
        """
        return f"Token({self.type.name}, {self.value!r}, {self.position})"


class Lexer:
    """Tokenizes Cypher query strings."""

    def __init__(self, query: str) -> None:
        """Initialize lexer.

        Args:
            query: Query string to tokenize
        """
        self.query: str = query
        self.position: int = 0
        self.tokens: list[Token] = []

    def tokenize(self) -> list[Token]:
        """Tokenize the query.

        Returns:
            List[Token]: List of tokens

        Raises:
            QuerySyntaxError: If lexing fails
        """
        while self.position < len(self.query):
            self._skip_whitespace()
            if self.position >= len(self.query):
                break

            char: str = self.query[self.position]

            # Single character tokens
            if char == "(":
                self.tokens.append(Token(TokenType.LPAREN, "(", self.position))
                self.position += 1
            elif char == ")":
                self.tokens.append(Token(TokenType.RPAREN, ")", self.position))
                self.position += 1
            elif char == "{":
                self.tokens.append(Token(TokenType.LBRACE, "{", self.position))
                self.position += 1
            elif char == "}":
                self.tokens.append(Token(TokenType.RBRACE, "}", self.position))
                self.position += 1
            elif char == "[":
                self.tokens.append(Token(TokenType.LBRACKET, "[", self.position))
                self.position += 1
            elif char == "]":
                self.tokens.append(Token(TokenType.RBRACKET, "]", self.position))
                self.position += 1
            elif char == ",":
                self.tokens.append(Token(TokenType.COMMA, ",", self.position))
                self.position += 1
            elif char == ":":
                self.tokens.append(Token(TokenType.COLON, ":", self.position))
                self.position += 1
            elif char == ".":
                self.tokens.append(Token(TokenType.DOT, ".", self.position))
                self.position += 1
            elif char == "+":
                self.tokens.append(Token(TokenType.PLUS, "+", self.position))
                self.position += 1
            elif char == "/":
                self.tokens.append(Token(TokenType.SLASH, "/", self.position))
                self.position += 1
            elif char == "*":
                self.tokens.append(Token(TokenType.STAR, "*", self.position))
                self.position += 1
            elif char == "-":
                # Check for arrow
                if self.position + 1 < len(self.query) and self.query[self.position + 1] == ">":
                    self.tokens.append(Token(TokenType.ARROW, "->", self.position))
                    self.position += 2
                else:
                    self.tokens.append(Token(TokenType.MINUS, "-", self.position))
                    self.position += 1
            elif char == "<":
                # Check for arrow and comparisons
                if self.position + 1 < len(self.query):
                    next_char: str = self.query[self.position + 1]
                    if next_char == "-":
                        self.tokens.append(Token(TokenType.LEFT_ARROW, "<-", self.position))
                        self.position += 2
                    elif next_char == "=":
                        self.tokens.append(Token(TokenType.LTE, "<=", self.position))
                        self.position += 2
                    else:
                        self.tokens.append(Token(TokenType.LT, "<", self.position))
                        self.position += 1
                else:
                    self.tokens.append(Token(TokenType.LT, "<", self.position))
                    self.position += 1
            elif char == ">":
                # Check for comparison
                if self.position + 1 < len(self.query) and self.query[self.position + 1] == "=":
                    self.tokens.append(Token(TokenType.GTE, ">=", self.position))
                    self.position += 2
                else:
                    self.tokens.append(Token(TokenType.GT, ">", self.position))
                    self.position += 1
            elif char == "=":
                self.tokens.append(Token(TokenType.EQUALS, "=", self.position))
                self.position += 1
            elif char == "!":
                # Check for !=
                if self.position + 1 < len(self.query) and self.query[self.position + 1] == "=":
                    self.tokens.append(Token(TokenType.NEQ, "!=", self.position))
                    self.position += 2
                else:
                    raise QuerySyntaxError(f"Unexpected character: {char}", self.position)
            elif char == '"' or char == "'":
                self._read_string()
            elif char.isdigit():
                self._read_number()
            elif char.isalpha() or char == "_":
                self._read_identifier()
            else:
                raise QuerySyntaxError(f"Unexpected character: {char}", self.position)

        self.tokens.append(Token(TokenType.EOF, None, self.position))
        return self.tokens

    def _skip_whitespace(self) -> None:
        """Skip whitespace characters."""
        while self.position < len(self.query) and self.query[self.position].isspace():
            self.position += 1

    def _read_string(self) -> None:
        """Read a string literal.

        Raises:
            QuerySyntaxError: If string is unterminated
        """
        quote_char: str = self.query[self.position]
        start_pos: int = self.position
        self.position += 1
        value: str = ""

        while self.position < len(self.query):
            char: str = self.query[self.position]
            if char == quote_char:
                self.position += 1
                self.tokens.append(Token(TokenType.STRING, value, start_pos))
                return
            elif char == "\\":
                self.position += 1
                if self.position < len(self.query):
                    next_char: str = self.query[self.position]
                    if next_char == "n":
                        value += "\n"
                    elif next_char == "t":
                        value += "\t"
                    elif next_char == "r":
                        value += "\r"
                    elif next_char == "\\":
                        value += "\\"
                    else:
                        value += next_char
                    self.position += 1
            else:
                value += char
                self.position += 1

        raise QuerySyntaxError("Unterminated string", start_pos)

    def _read_number(self) -> None:
        """Read a number literal (integer or float).

        Produces either INTEGER or FLOAT token.
        """
        start_pos: int = self.position
        value: str = ""

        while self.position < len(self.query) and self.query[self.position].isdigit():
            value += self.query[self.position]
            self.position += 1

        if self.position < len(self.query) and self.query[self.position] == ".":
            value += "."
            self.position += 1
            while self.position < len(self.query) and self.query[self.position].isdigit():
                value += self.query[self.position]
                self.position += 1
            self.tokens.append(Token(TokenType.FLOAT, float(value), start_pos))
        else:
            self.tokens.append(Token(TokenType.INTEGER, int(value), start_pos))

    def _read_identifier(self) -> None:
        """Read an identifier or keyword.

        Classifies the identifier as a keyword if it matches
        one of the reserved keywords.
        """
        start_pos: int = self.position
        value: str = ""

        while self.position < len(self.query) and (
            self.query[self.position].isalnum() or self.query[self.position] == "_"
        ):
            value += self.query[self.position]
            self.position += 1

        token_type: TokenType = _keyword(value)
        self.tokens.append(Token(token_type, value, start_pos))
