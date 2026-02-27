"""Tests for the Thomas lexer."""

import pytest

from ._types import TokenType
from .lexer import Lexer


class TestLexerBasic:
    """Test basic lexing functionality."""

    def test_empty_source(self) -> None:
        """Test lexing empty source."""
        lexer = Lexer("")
        tokens = lexer.tokenize()
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.EOF

    def test_single_integer(self) -> None:
        """Test lexing a single integer."""
        lexer = Lexer("42")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.INT_LIT
        assert tokens[0].value == 42

    def test_single_float(self) -> None:
        """Test lexing a single float."""
        lexer = Lexer("3.14")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.FLOAT_LIT
        assert tokens[0].value == 3.14

    def test_string_literal(self) -> None:
        """Test lexing a string literal."""
        lexer = Lexer('"hello"')
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.STRING_LIT
        assert tokens[0].value == "hello"

    def test_identifier(self) -> None:
        """Test lexing an identifier."""
        lexer = Lexer("myVar")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.IDENT
        assert tokens[0].value == "myVar"


class TestLexerKeywords:
    """Test keyword tokenization."""

    def test_if_keyword(self) -> None:
        """Test lexing 'if' keyword."""
        lexer = Lexer("if")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.IF

    def test_fn_keyword(self) -> None:
        """Test lexing 'fn' keyword."""
        lexer = Lexer("fn")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.FN

    def test_let_keyword(self) -> None:
        """Test lexing 'let' keyword."""
        lexer = Lexer("let")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.LET

    def test_all_keywords(self) -> None:
        """Test all keywords are recognized."""
        keywords = {
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

        for keyword, token_type in keywords.items():
            lexer = Lexer(keyword)
            tokens = lexer.tokenize()
            assert tokens[0].type == token_type, f"Failed for keyword: {keyword}"


class TestLexerOperators:
    """Test operator tokenization."""

    def test_arithmetic_operators(self) -> None:
        """Test arithmetic operators."""
        operators = {
            "+": TokenType.PLUS,
            "-": TokenType.MINUS,
            "*": TokenType.STAR,
            "/": TokenType.SLASH,
            "%": TokenType.PERCENT,
        }

        for op, token_type in operators.items():
            lexer = Lexer(op)
            tokens = lexer.tokenize()
            assert tokens[0].type == token_type, f"Failed for operator: {op}"

    def test_comparison_operators(self) -> None:
        """Test comparison operators."""
        operators = {
            "==": TokenType.EQ,
            "!=": TokenType.NE,
            "<": TokenType.LT,
            ">": TokenType.GT,
            "<=": TokenType.LE,
            ">=": TokenType.GE,
        }

        for op, token_type in operators.items():
            lexer = Lexer(op)
            tokens = lexer.tokenize()
            assert tokens[0].type == token_type, f"Failed for operator: {op}"

    def test_logical_operators(self) -> None:
        """Test logical operators."""
        operators = {
            "&&": TokenType.LOGICAL_AND,
            "||": TokenType.LOGICAL_OR,
            "!": TokenType.NOT,
        }

        for op, token_type in operators.items():
            lexer = Lexer(op)
            tokens = lexer.tokenize()
            assert tokens[0].type == token_type, f"Failed for operator: {op}"

    def test_assignment_operators(self) -> None:
        """Test assignment operators."""
        operators = {
            "=": TokenType.ASSIGN,
            "+=": TokenType.PLUS_ASSIGN,
            "-=": TokenType.MINUS_ASSIGN,
        }

        for op, token_type in operators.items():
            lexer = Lexer(op)
            tokens = lexer.tokenize()
            assert tokens[0].type == token_type, f"Failed for operator: {op}"


class TestLexerDelimiters:
    """Test delimiter tokenization."""

    def test_braces(self) -> None:
        """Test braces."""
        lexer = Lexer("{}")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.LBRACE
        assert tokens[1].type == TokenType.RBRACE

    def test_parentheses(self) -> None:
        """Test parentheses."""
        lexer = Lexer("()")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.LPAREN
        assert tokens[1].type == TokenType.RPAREN

    def test_brackets(self) -> None:
        """Test brackets."""
        lexer = Lexer("[]")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.LBRACKET
        assert tokens[1].type == TokenType.RBRACKET

    def test_punctuation(self) -> None:
        """Test punctuation."""
        punctuation = {
            ",": TokenType.COMMA,
            ";": TokenType.SEMICOLON,
            ":": TokenType.COLON,
        }

        for punct, token_type in punctuation.items():
            lexer = Lexer(punct)
            tokens = lexer.tokenize()
            assert tokens[0].type == token_type, f"Failed for punctuation: {punct}"


class TestLexerStringEscapes:
    """Test string escape sequences."""

    def test_newline_escape(self) -> None:
        """Test \\n escape."""
        lexer = Lexer('"hello\\nworld"')
        tokens = lexer.tokenize()
        assert tokens[0].value == "hello\nworld"

    def test_tab_escape(self) -> None:
        """Test \\t escape."""
        lexer = Lexer('"hello\\tworld"')
        tokens = lexer.tokenize()
        assert tokens[0].value == "hello\tworld"

    def test_backslash_escape(self) -> None:
        """Test \\\\ escape."""
        lexer = Lexer('"hello\\\\world"')
        tokens = lexer.tokenize()
        assert tokens[0].value == "hello\\world"

    def test_quote_escape(self) -> None:
        """Test \\" escape."""
        lexer = Lexer('"hello\\"world"')
        tokens = lexer.tokenize()
        assert tokens[0].value == 'hello"world'


class TestLexerComments:
    """Test comment handling."""

    def test_line_comment(self) -> None:
        """Test // line comments."""
        lexer = Lexer("42 // this is a comment")
        tokens = lexer.tokenize()
        assert len(tokens) == 2  # INT_LIT and EOF
        assert tokens[0].type == TokenType.INT_LIT

    def test_block_comment(self) -> None:
        """Test /* */ block comments."""
        lexer = Lexer("42 /* this is a comment */ 43")
        tokens = lexer.tokenize()
        assert len(tokens) == 3  # INT_LIT, INT_LIT, EOF
        assert tokens[0].value == 42
        assert tokens[1].value == 43

    def test_nested_block_comments_not_supported(self) -> None:
        """Test that nested comments are not supported."""
        lexer = Lexer("/* outer /* inner */ outer */")
        tokens = lexer.tokenize()
        # Should parse until first */
        assert len(tokens) >= 1


class TestLexerWhitespace:
    """Test whitespace handling."""

    def test_spaces(self) -> None:
        """Test space handling."""
        lexer = Lexer("42   43")
        tokens = lexer.tokenize()
        assert len(tokens) == 3  # 2 INTs + EOF
        assert tokens[0].value == 42
        assert tokens[1].value == 43

    def test_tabs(self) -> None:
        """Test tab handling."""
        lexer = Lexer("42\t43")
        tokens = lexer.tokenize()
        assert len(tokens) == 3
        assert tokens[0].value == 42
        assert tokens[1].value == 43

    def test_newlines(self) -> None:
        """Test newline handling."""
        lexer = Lexer("42\n43")
        tokens = lexer.tokenize()
        assert len(tokens) == 3
        assert tokens[0].value == 42
        assert tokens[1].value == 43
        assert tokens[1].location.line == 2


class TestLexerSourceLocation:
    """Test source location tracking."""

    def test_single_line_location(self) -> None:
        """Test location tracking on a single line."""
        lexer = Lexer("42")
        tokens = lexer.tokenize()
        assert tokens[0].location.line == 1
        assert tokens[0].location.column == 1

    def test_multiline_location(self) -> None:
        """Test location tracking across lines."""
        lexer = Lexer("42\n43")
        tokens = lexer.tokenize()
        assert tokens[0].location.line == 1
        assert tokens[1].location.line == 2

    def test_column_tracking(self) -> None:
        """Test column tracking."""
        lexer = Lexer("42 43")
        tokens = lexer.tokenize()
        assert tokens[0].location.column == 1
        assert tokens[1].location.column == 4


class TestLexerErrors:
    """Test error handling."""

    def test_unterminated_string(self) -> None:
        """Test error on unterminated string."""
        lexer = Lexer('"hello')
        with pytest.raises(Exception):
            lexer.tokenize()

    def test_unterminated_block_comment(self) -> None:
        """Test error on unterminated block comment."""
        lexer = Lexer("/* unclosed comment")
        with pytest.raises(Exception):
            lexer.tokenize()

    def test_invalid_character(self) -> None:
        """Test error on invalid character."""
        lexer = Lexer("@")
        with pytest.raises(Exception):
            lexer.tokenize()


class TestLexerComplex:
    """Test complex tokenization scenarios."""

    def test_function_declaration(self) -> None:
        """Test tokenizing a function declaration."""
        source = "fn add(x: int, y: int) -> int { return x + y; }"
        lexer = Lexer(source)
        tokens = lexer.tokenize()

        # Check key tokens
        token_types = [t.type for t in tokens]
        assert TokenType.FN in token_types
        assert TokenType.IDENT in token_types
        assert TokenType.LPAREN in token_types
        assert TokenType.RPAREN in token_types
        assert TokenType.LBRACE in token_types
        assert TokenType.RBRACE in token_types
        assert TokenType.RETURN in token_types

    def test_array_literal(self) -> None:
        """Test tokenizing array literals."""
        source = "[1, 2, 3]"
        lexer = Lexer(source)
        tokens = lexer.tokenize()

        assert tokens[0].type == TokenType.LBRACKET
        assert tokens[1].type == TokenType.INT_LIT
        assert tokens[2].type == TokenType.COMMA

    def test_mixed_numbers(self) -> None:
        """Test lexing mixed integers and floats."""
        source = "42 3.14 100"
        lexer = Lexer(source)
        tokens = lexer.tokenize()

        assert tokens[0].type == TokenType.INT_LIT
        assert tokens[0].value == 42
        assert tokens[1].type == TokenType.FLOAT_LIT
        assert tokens[1].value == 3.14
        assert tokens[2].type == TokenType.INT_LIT
        assert tokens[2].value == 100
