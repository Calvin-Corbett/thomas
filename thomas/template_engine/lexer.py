"""Template lexer for tokenizing template strings."""

from __future__ import annotations

from ._exceptions import TemplateSyntaxError
from ._types import TemplateConfig, Token, TokenType


class Lexer:
    """Tokenizes template strings into tokens."""

    # Keywords mapping
    KEYWORDS = {
        "for": TokenType.FOR,
        "endfor": TokenType.ENDFOR,
        "if": TokenType.IF,
        "elif": TokenType.ELIF,
        "else": TokenType.ELSE,
        "endif": TokenType.ENDIF,
        "block": TokenType.BLOCK,
        "endblock": TokenType.ENDBLOCK,
        "extends": TokenType.EXTENDS,
        "include": TokenType.INCLUDE,
        "import": TokenType.IMPORT,
        "from": TokenType.FROM,
        "macro": TokenType.MACRO,
        "endmacro": TokenType.ENDMACRO,
        "call": TokenType.CALL,
        "endcall": TokenType.ENDCALL,
        "filter": TokenType.FILTER,
        "endfilter": TokenType.ENDFILTER,
        "set": TokenType.SET,
        "endset": TokenType.ENDSET,
        "with": TokenType.WITH,
        "and": TokenType.AND,
        "or": TokenType.OR,
        "not": TokenType.NOT,
        "in": TokenType.IN,
        "is": TokenType.IS,
        "true": TokenType.TRUE,
        "false": TokenType.FALSE,
        "none": TokenType.NONE,
        "True": TokenType.TRUE,
        "False": TokenType.FALSE,
        "None": TokenType.NONE,
    }

    def __init__(self, template: str, config: TemplateConfig) -> None:
        """
        Initialize the lexer.

        Args:
            template: Template string to tokenize
            config: Template configuration
        """
        self.template = template
        self.config = config
        self.pos = 0
        self.lineno = 1
        self.col = 0
        self.tokens: list[Token] = []

    def tokenize(self) -> list[Token]:
        """
        Tokenize the template.

        Returns:
            List of tokens
        """
        while self.pos < len(self.template):
            self._tokenize_next()
        self.tokens.append(Token(TokenType.EOF, None, self.lineno))
        return self.tokens

    def _tokenize_next(self) -> None:
        """Tokenize next element."""
        # Check for comment
        if self._match(self.config.comment_open):
            self._tokenize_comment()
            return

        # Check for block statement
        if self._match(self.config.block_open):
            self._tokenize_block()
            return

        # Check for variable
        if self._match(self.config.var_open):
            self._tokenize_variable()
            return

        # Plain text
        self._tokenize_text()

    def _tokenize_comment(self) -> None:
        """Tokenize a comment block."""
        start_lineno = self.lineno
        self.pos += len(self.config.comment_open)

        # Skip until comment close
        end_pos = self.template.find(self.config.comment_close, self.pos)
        if end_pos == -1:
            raise TemplateSyntaxError(
                f"Unterminated comment starting at line {start_lineno}",
                start_lineno,
            )

        content = self.template[self.pos : end_pos]
        self._advance(content)
        self.pos = end_pos + len(self.config.comment_close)

    def _tokenize_block(self) -> None:
        """Tokenize a block statement: {% ... %}."""
        start_lineno = self.lineno
        self.pos += len(self.config.block_open)

        # Find block end
        end_pos = self.template.find(self.config.block_close, self.pos)
        if end_pos == -1:
            raise TemplateSyntaxError(
                f"Unterminated block starting at line {start_lineno}",
                start_lineno,
            )

        content = self.template[self.pos : end_pos].strip()
        self._tokenize_statement(content, start_lineno)

        self.pos = end_pos + len(self.config.block_close)
        self._skip_newline_if_trimming()

    def _tokenize_variable(self) -> None:
        """Tokenize a variable expression: {{ ... }}."""
        start_lineno = self.lineno
        self.pos += len(self.config.var_open)

        # Find variable end
        end_pos = self.template.find(self.config.var_close, self.pos)
        if end_pos == -1:
            raise TemplateSyntaxError(
                f"Unterminated variable starting at line {start_lineno}",
                start_lineno,
            )

        content = self.template[self.pos : end_pos]
        self._tokenize_expression(content, start_lineno)

        self.pos = end_pos + len(self.config.var_close)

    def _tokenize_text(self) -> None:
        """Tokenize plain text until next delimiter."""
        start_pos = self.pos
        start_lineno = self.lineno

        while self.pos < len(self.template):
            # Check for any delimiter
            if (
                self._peek_match(self.config.var_open)
                or self._peek_match(self.config.block_open)
                or self._peek_match(self.config.comment_open)
            ):
                break
            self._advance(self.template[self.pos])
            self.pos += 1

        text = self.template[start_pos : self.pos]
        if text:
            self.tokens.append(Token(TokenType.TEXT, text, start_lineno))

    def _tokenize_statement(self, content: str, lineno: int) -> None:
        """Tokenize a block statement (control flow, etc)."""
        self.tokens.append(Token(TokenType.BLOCK_START, None, lineno))

        # Handle special case: raw block
        if content.startswith("raw"):
            self._tokenize_raw_block(lineno)
            return

        # Tokenize statement content
        self._tokenize_expr_tokens(content, lineno)

        self.tokens.append(Token(TokenType.BLOCK_END, None, lineno))

    def _tokenize_raw_block(self, start_lineno: int) -> None:
        """Handle {% raw %} ... {% endraw %} blocks."""
        # Find endraw tag
        raw_end = self.config.block_open + "%endraw" + self.config.block_close
        end_pos = self.template.find(raw_end, self.pos)
        if end_pos == -1:
            raise TemplateSyntaxError(
                f"Unterminated raw block starting at line {start_lineno}",
                start_lineno,
            )

        content = self.template[self.pos : end_pos]
        self._advance(content)
        self.pos = end_pos + len(raw_end)

        # Emit raw content as text token
        self.tokens.append(Token(TokenType.TEXT, content, start_lineno))

    def _tokenize_expression(self, content: str, lineno: int) -> None:
        """Tokenize variable expression content."""
        self.tokens.append(Token(TokenType.VAR_START, None, lineno))
        self._tokenize_expr_tokens(content, lineno)
        self.tokens.append(Token(TokenType.VAR_END, None, lineno))

    def _tokenize_expr_tokens(self, content: str, lineno: int) -> None:
        """Tokenize expression tokens from content string."""
        pos = 0

        while pos < len(content):
            # Skip whitespace
            while pos < len(content) and content[pos].isspace():
                if content[pos] == "\n":
                    lineno += 1
                pos += 1

            if pos >= len(content):
                break

            # String literals
            if content[pos] in ("'", '"'):
                quote = content[pos]
                pos += 1
                start = pos
                while pos < len(content):
                    if content[pos] == quote:
                        break
                    if content[pos] == "\\":
                        pos += 2
                        continue
                    pos += 1
                if pos >= len(content):
                    raise TemplateSyntaxError("Unterminated string literal", lineno)
                value = content[start:pos]
                # Process escape sequences
                value = (
                    value.replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\").replace(f"\\{quote}", quote)
                )
                self.tokens.append(Token(TokenType.STRING, value, lineno))
                pos += 1
                continue

            # Numbers
            if content[pos].isdigit() or (
                content[pos] == "." and pos + 1 < len(content) and content[pos + 1].isdigit()
            ):
                start = pos
                while pos < len(content) and (content[pos].isdigit() or content[pos] == "."):
                    pos += 1
                value = content[start:pos]
                if "." in value:
                    self.tokens.append(Token(TokenType.NUMBER, float(value), lineno))
                else:
                    self.tokens.append(Token(TokenType.NUMBER, int(value), lineno))
                continue

            # Names/keywords and operators
            if content[pos].isalpha() or content[pos] == "_":
                start = pos
                while pos < len(content) and (content[pos].isalnum() or content[pos] == "_"):
                    pos += 1
                word = content[start:pos]
                token_type = self.KEYWORDS.get(word, TokenType.NAME)
                value = word if token_type == TokenType.NAME else None
                self.tokens.append(Token(token_type, value, lineno))
                continue

            # Two-character operators
            if pos + 1 < len(content):
                two_char = content[pos : pos + 2]
                token_type = None
                if two_char == "==":
                    token_type = TokenType.EQ
                elif two_char == "!=":
                    token_type = TokenType.NE
                elif two_char == "<=":
                    token_type = TokenType.LE
                elif two_char == ">=":
                    token_type = TokenType.GE
                elif two_char == "**":
                    token_type = TokenType.POW
                elif two_char == "//":
                    token_type = TokenType.DIV
                if token_type:
                    self.tokens.append(Token(token_type, None, lineno))
                    pos += 2
                    continue

            # Single-character tokens
            char = content[pos]
            token_type = None
            if char == "|":
                token_type = TokenType.PIPE
            elif char == ",":
                token_type = TokenType.COMMA
            elif char == ":":
                token_type = TokenType.COLON
            elif char == ".":
                token_type = TokenType.DOT
            elif char == "(":
                token_type = TokenType.LPAREN
            elif char == ")":
                token_type = TokenType.RPAREN
            elif char == "[":
                token_type = TokenType.LBRACKET
            elif char == "]":
                token_type = TokenType.RBRACKET
            elif char == "{":
                token_type = TokenType.LBRACE
            elif char == "}":
                token_type = TokenType.RBRACE
            elif char == "=":
                token_type = TokenType.ASSIGN
            elif char == "<":
                token_type = TokenType.LT
            elif char == ">":
                token_type = TokenType.GT
            elif char == "+":
                token_type = TokenType.PLUS
            elif char == "-":
                token_type = TokenType.MINUS
            elif char == "*":
                token_type = TokenType.MUL
            elif char == "/":
                token_type = TokenType.DIV
            elif char == "%":
                token_type = TokenType.MOD

            if token_type:
                self.tokens.append(Token(token_type, None, lineno))
                pos += 1
            else:
                raise TemplateSyntaxError(f"Unexpected character: {char!r}", lineno)

    def _match(self, text: str) -> bool:
        """Check if text matches at current position."""
        return self.template[self.pos : self.pos + len(text)] == text

    def _peek_match(self, text: str) -> bool:
        """Check if text matches at current position (without advancing)."""
        return self.template[self.pos : self.pos + len(text)] == text

    def _advance(self, text: str) -> None:
        """Advance position tracking newlines."""
        for char in text:
            if char == "\n":
                self.lineno += 1
                self.col = 0
            else:
                self.col += 1

    def _skip_newline_if_trimming(self) -> None:
        """Skip newline after block if trim_blocks is enabled."""
        if self.config.trim_blocks and self.pos < len(self.template):
            if self.template[self.pos] == "\n":
                self.pos += 1
                self.lineno += 1
            elif self.pos + 1 < len(self.template) and self.template[self.pos : self.pos + 2] == "\r\n":
                self.pos += 2
                self.lineno += 1
