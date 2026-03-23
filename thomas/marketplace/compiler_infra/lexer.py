"""Lexical analyzer for the Thomas language."""

from __future__ import annotations

from ._exceptions import LexError
from ._types import KEYWORDS, SourceLocation, Token, TokenType


class Lexer:
    """Tokenizes source code into a stream of tokens."""

    def __init__(self, source: str, filename: str = "<source>") -> None:
        """Initialize the lexer.

        Args:
            source: The source code to tokenize.
            filename: The source filename for error reporting.
        """
        self.source = source
        self.filename = filename
        self.pos = 0
        self.line = 1
        self.column = 1
        self.tokens: list[Token] = []

    def error(self, message: str) -> LexError:
        """Create a lexical error at current position."""
        location = SourceLocation(self.line, self.column, self.filename)
        return LexError(message, location)

    def current_char(self) -> str | None:
        """Get the current character without advancing."""
        if self.pos >= len(self.source):
            return None
        return self.source[self.pos]

    def peek_char(self, offset: int = 1) -> str | None:
        """Peek ahead by offset characters."""
        pos = self.pos + offset
        if pos >= len(self.source):
            return None
        return self.source[pos]

    def advance(self) -> str | None:
        """Consume and return the current character."""
        if self.pos >= len(self.source):
            return None
        ch = self.source[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        return ch

    def skip_whitespace(self) -> None:
        """Skip whitespace characters."""
        while self.current_char() and self.current_char() in " \t\r\n":
            self.advance()

    def skip_line_comment(self) -> None:
        """Skip // comment to end of line."""
        self.advance()  # consume first /
        self.advance()  # consume second /
        while self.current_char() and self.current_char() != "\n":
            self.advance()

    def skip_block_comment(self) -> None:
        """Skip /* */ block comment."""
        self.advance()  # consume /
        self.advance()  # consume *
        while self.pos < len(self.source) - 1:
            if self.current_char() == "*" and self.peek_char() == "/":
                self.advance()  # consume *
                self.advance()  # consume /
                return
            self.advance()
        raise self.error("Unterminated block comment")

    def read_string(self, quote_char: str) -> str:
        """Read a string literal with escape sequences."""
        result = ""
        self.advance()  # consume opening quote
        while self.current_char() and self.current_char() != quote_char:
            if self.current_char() == "\\":
                self.advance()
                next_char = self.current_char()
                if next_char == "n":
                    result += "\n"
                elif next_char == "t":
                    result += "\t"
                elif next_char == "\\":
                    result += "\\"
                elif next_char == '"':
                    result += '"'
                elif next_char == "'":
                    result += "'"
                else:
                    result += next_char if next_char else ""
                self.advance()
            else:
                result += self.current_char()
                self.advance()
        if self.current_char() != quote_char:
            raise self.error("Unterminated string literal")
        self.advance()  # consume closing quote
        return result

    def read_number(self) -> Token:
        """Read a numeric literal (int or float)."""
        start_location = SourceLocation(self.line, self.column, self.filename)
        num_str = ""
        has_dot = False

        while self.current_char() and (self.current_char().isdigit() or self.current_char() == "."):
            if self.current_char() == ".":
                if has_dot:
                    break  # Second dot, stop
                has_dot = True
            num_str += self.current_char()
            self.advance()

        if has_dot:
            return Token(TokenType.FLOAT_LIT, float(num_str), start_location)
        else:
            return Token(TokenType.INT_LIT, int(num_str), start_location)

    def read_identifier(self) -> Token:
        """Read an identifier or keyword."""
        start_location = SourceLocation(self.line, self.column, self.filename)
        ident = ""

        while self.current_char() and (self.current_char().isalnum() or self.current_char() in "_"):
            ident += self.current_char()
            self.advance()

        token_type = KEYWORDS.get(ident, TokenType.IDENT)
        value = (
            True
            if token_type == TokenType.TRUE
            else (False if token_type == TokenType.FALSE else None)
            if token_type in (TokenType.TRUE, TokenType.FALSE)
            else ident
        )

        return Token(token_type, value, start_location)

    def tokenize(self) -> list[Token]:
        """Tokenize the entire source code.

        Returns:
            A list of tokens.

        Raises:
            LexError: If an invalid token is encountered.
        """
        while self.pos < len(self.source):
            self.skip_whitespace()

            if self.pos >= len(self.source):
                break

            ch = self.current_char()
            location = SourceLocation(self.line, self.column, self.filename)

            # Comments
            if ch == "/" and self.peek_char() == "/":
                self.skip_line_comment()
                continue
            if ch == "/" and self.peek_char() == "*":
                self.skip_block_comment()
                continue

            # String literals
            if ch in ('"', "'"):
                value = self.read_string(ch)
                self.tokens.append(Token(TokenType.STRING_LIT, value, location))
                continue

            # Numbers
            if ch.isdigit():
                self.tokens.append(self.read_number())
                continue

            # Identifiers and keywords
            if ch.isalpha() or ch == "_":
                self.tokens.append(self.read_identifier())
                continue

            # Operators and delimiters
            if ch == "+":
                self.advance()
                if self.current_char() == "=":
                    self.advance()
                    self.tokens.append(Token(TokenType.PLUS_ASSIGN, "+=", location))
                else:
                    self.tokens.append(Token(TokenType.PLUS, "+", location))
                continue

            if ch == "-":
                self.advance()
                if self.current_char() == "=":
                    self.advance()
                    self.tokens.append(Token(TokenType.MINUS_ASSIGN, "-=", location))
                elif self.current_char() == ">":
                    self.advance()
                    self.tokens.append(Token(TokenType.ARROW, "->", location))
                else:
                    self.tokens.append(Token(TokenType.MINUS, "-", location))
                continue

            if ch == "*":
                self.advance()
                self.tokens.append(Token(TokenType.STAR, "*", location))
                continue

            if ch == "/":
                self.advance()
                self.tokens.append(Token(TokenType.SLASH, "/", location))
                continue

            if ch == "%":
                self.advance()
                self.tokens.append(Token(TokenType.PERCENT, "%", location))
                continue

            if ch == "=":
                self.advance()
                if self.current_char() == "=":
                    self.advance()
                    self.tokens.append(Token(TokenType.EQ, "==", location))
                else:
                    self.tokens.append(Token(TokenType.ASSIGN, "=", location))
                continue

            if ch == "!":
                self.advance()
                if self.current_char() == "=":
                    self.advance()
                    self.tokens.append(Token(TokenType.NE, "!=", location))
                else:
                    self.tokens.append(Token(TokenType.NOT, "!", location))
                continue

            if ch == "<":
                self.advance()
                if self.current_char() == "=":
                    self.advance()
                    self.tokens.append(Token(TokenType.LE, "<=", location))
                else:
                    self.tokens.append(Token(TokenType.LT, "<", location))
                continue

            if ch == ">":
                self.advance()
                if self.current_char() == "=":
                    self.advance()
                    self.tokens.append(Token(TokenType.GE, ">=", location))
                else:
                    self.tokens.append(Token(TokenType.GT, ">", location))
                continue

            if ch == "&":
                self.advance()
                if self.current_char() == "&":
                    self.advance()
                    self.tokens.append(Token(TokenType.LOGICAL_AND, "&&", location))
                else:
                    raise self.error(f"Unexpected character: {ch}")
                continue

            if ch == "|":
                self.advance()
                if self.current_char() == "|":
                    self.advance()
                    self.tokens.append(Token(TokenType.LOGICAL_OR, "||", location))
                else:
                    raise self.error(f"Unexpected character: {ch}")
                continue

            if ch == "{":
                self.advance()
                self.tokens.append(Token(TokenType.LBRACE, "{", location))
                continue

            if ch == "}":
                self.advance()
                self.tokens.append(Token(TokenType.RBRACE, "}", location))
                continue

            if ch == "(":
                self.advance()
                self.tokens.append(Token(TokenType.LPAREN, "(", location))
                continue

            if ch == ")":
                self.advance()
                self.tokens.append(Token(TokenType.RPAREN, ")", location))
                continue

            if ch == "[":
                self.advance()
                self.tokens.append(Token(TokenType.LBRACKET, "[", location))
                continue

            if ch == "]":
                self.advance()
                self.tokens.append(Token(TokenType.RBRACKET, "]", location))
                continue

            if ch == ",":
                self.advance()
                self.tokens.append(Token(TokenType.COMMA, ",", location))
                continue

            if ch == ";":
                self.advance()
                self.tokens.append(Token(TokenType.SEMICOLON, ";", location))
                continue

            if ch == ":":
                self.advance()
                self.tokens.append(Token(TokenType.COLON, ":", location))
                continue

            raise self.error(f"Unexpected character: {ch}")

        self.tokens.append(Token(TokenType.EOF, None, SourceLocation(self.line, self.column, self.filename)))
        return self.tokens
