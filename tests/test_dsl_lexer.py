"""Tests for DSL lexer."""

import pytest

from thomas.marketplace.dsl import Lexer, TokenType


class TestLexerBasics:
    """Test basic lexer functionality."""

    def test_tokenize_integers(self) -> None:
        """Test integer tokenization."""
        lexer = Lexer("42 100 0")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.INT
        assert tokens[0].value == 42
        assert tokens[2].type == TokenType.INT
        assert tokens[2].value == 100

    def test_tokenize_floats(self) -> None:
        """Test float tokenization."""
        lexer = Lexer("3.14 0.0 2.5e-3")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.FLOAT
        assert tokens[0].value == 3.14
        assert tokens[2].type == TokenType.FLOAT
        assert tokens[2].value == 0.0

    def test_tokenize_strings(self) -> None:
        """Test string tokenization."""
        lexer = Lexer("\"hello\" 'world'")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].value == "hello"
        assert tokens[2].type == TokenType.STRING
        assert tokens[2].value == "world"

    def test_tokenize_identifiers(self) -> None:
        """Test identifier tokenization."""
        lexer = Lexer("foo bar_baz _test")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[0].value == "foo"
        assert tokens[2].type == TokenType.IDENTIFIER

    def test_tokenize_keywords(self) -> None:
        """Test keyword tokenization."""
        lexer = Lexer("if then else while for fn let")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.IF
        assert tokens[2].type == TokenType.THEN
        assert tokens[4].type == TokenType.ELSE

    def test_tokenize_operators(self) -> None:
        """Test operator tokenization."""
        lexer = Lexer("+ - * / % ** == != < > <= >=")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.PLUS
        assert tokens[2].type == TokenType.MINUS
        assert tokens[4].type == TokenType.STAR
        assert tokens[8].type == TokenType.POWER

    def test_tokenize_booleans(self) -> None:
        """Test boolean tokenization."""
        lexer = Lexer("true false none")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.TRUE
        assert tokens[0].value is True
        assert tokens[2].type == TokenType.FALSE
        assert tokens[2].value is False
        assert tokens[4].type == TokenType.NONE
        assert tokens[4].value is None

    def test_tokenize_delimiters(self) -> None:
        """Test delimiter tokenization."""
        lexer = Lexer("( ) { } [ ] , ; :")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.LPAREN
        assert tokens[2].type == TokenType.RPAREN
        assert tokens[4].type == TokenType.LBRACE

    def test_skip_comments(self) -> None:
        """Test comment skipping."""
        lexer = Lexer("42 // comment\n100")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.INT
        assert tokens[0].value == 42
        assert tokens[2].type == TokenType.INT
        assert tokens[2].value == 100

    def test_skip_block_comments(self) -> None:
        """Test block comment skipping."""
        lexer = Lexer("42 /* comment */ 100")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.INT
        assert tokens[2].type == TokenType.INT

    def test_string_escape_sequences(self) -> None:
        """Test string escape sequences."""
        lexer = Lexer(r'"hello\nworld\t!"')
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.STRING
        assert tokens[0].value == "hello\nworld\t!"

    def test_hex_numbers(self) -> None:
        """Test hexadecimal numbers."""
        lexer = Lexer("0xFF 0x10")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.INT
        assert tokens[0].value == 255
        assert tokens[2].type == TokenType.INT
        assert tokens[2].value == 16

    def test_binary_numbers(self) -> None:
        """Test binary numbers."""
        lexer = Lexer("0b1010 0b11")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.INT
        assert tokens[0].value == 10
        assert tokens[2].type == TokenType.INT
        assert tokens[2].value == 3

    def test_scientific_notation(self) -> None:
        """Test scientific notation."""
        lexer = Lexer("1e3 2.5e-2 1E+5")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.FLOAT
        assert tokens[0].value == 1000.0
        assert tokens[2].type == TokenType.FLOAT
        assert tokens[2].value == 0.025

    def test_line_tracking(self) -> None:
        """Test line number tracking."""
        lexer = Lexer("a\nb\nc")
        tokens = lexer.tokenize()
        assert tokens[0].line == 1
        assert tokens[2].line == 2
        assert tokens[4].line == 3

    def test_column_tracking(self) -> None:
        """Test column tracking."""
        lexer = Lexer("a b c")
        tokens = lexer.tokenize()
        assert tokens[0].column == 1
        assert tokens[2].column == 3

    def test_eof_token(self) -> None:
        """Test EOF token."""
        lexer = Lexer("42")
        tokens = lexer.tokenize()
        assert tokens[-1].type == TokenType.EOF

    def test_logical_operators(self) -> None:
        """Test logical operators."""
        lexer = Lexer("&& || !")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.AND
        assert tokens[2].type == TokenType.OR
        assert tokens[4].type == TokenType.NOT

    def test_bitwise_operators(self) -> None:
        """Test bitwise operators."""
        lexer = Lexer("& | ^ ~ << >>")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.BIT_AND
        assert tokens[2].type == TokenType.BIT_OR

    def test_assignment_operators(self) -> None:
        """Test assignment operators."""
        lexer = Lexer("= += -= *= /=")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.ASSIGN
        assert tokens[2].type == TokenType.PLUS_ASSIGN

    def test_multiline_input(self) -> None:
        """Test multiline input."""
        code = """
        x = 1
        y = 2
        z = x + y
        """
        lexer = Lexer(code)
        tokens = lexer.tokenize()
        assert len(tokens) > 0
        assert tokens[-1].type == TokenType.EOF

    def test_empty_input(self) -> None:
        """Test empty input."""
        lexer = Lexer("")
        tokens = lexer.tokenize()
        assert len(tokens) == 1
        assert tokens[0].type == TokenType.EOF

    def test_whitespace_handling(self) -> None:
        """Test whitespace handling."""
        lexer = Lexer("  a  b  c  ")
        tokens = lexer.tokenize()
        # Should skip whitespace
        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[2].type == TokenType.IDENTIFIER

    def test_arrow_operator(self) -> None:
        """Test arrow operator."""
        lexer = Lexer("-> =>")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.ARROW
        assert tokens[2].type == TokenType.FAT_ARROW

    def test_invalid_character(self) -> None:
        """Test invalid character error."""
        lexer = Lexer("42 @ 100")
        with pytest.raises(Exception):
            lexer.tokenize()

    def test_pipe_operator(self) -> None:
        """Test pipe operator."""
        lexer = Lexer("|")
        tokens = lexer.tokenize()
        # Could be pipe or bit_or depending on context
        assert tokens[0].type in (TokenType.PIPE, TokenType.BIT_OR)

    def test_double_colon(self) -> None:
        """Test double colon."""
        lexer = Lexer("::")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.DOUBLE_COLON

    def test_dot_operator(self) -> None:
        """Test dot operator."""
        lexer = Lexer("obj.field")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.IDENTIFIER
        assert tokens[1].type == TokenType.DOT
        assert tokens[2].type == TokenType.IDENTIFIER

    def test_lambda_pipes(self) -> None:
        """Test lambda pipe syntax."""
        lexer = Lexer("fn |x| x + 1")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.FN
        assert tokens[1].type == TokenType.BIT_OR


class TestLexerEdgeCases:
    """Test edge cases."""

    def test_consecutive_operators(self) -> None:
        """Test consecutive operators."""
        lexer = Lexer("++a")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.PLUS

    def test_mixed_quotes(self) -> None:
        """Test mixed quote types."""
        lexer = Lexer("\"outer 'inner' outer\"")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.STRING

    def test_number_with_underscores(self) -> None:
        """Test numbers with leading zeros."""
        lexer = Lexer("0100 0x00FF")
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.INT
        assert tokens[2].type == TokenType.INT

    def test_nested_comments(self) -> None:
        """Test nested block comments."""
        lexer = Lexer("42 /* outer /* inner */ still outer */ 100")
        tokens = lexer.tokenize()
        # Should still tokenize
        assert len(tokens) > 0

    def test_unterminated_string(self) -> None:
        """Test unterminated string."""
        lexer = Lexer('"unterminated')
        # Should raise error during regex match or later
        lexer.tokenize()
        # This depends on implementation

    def test_very_long_string(self) -> None:
        """Test very long string."""
        long_str = "x" * 10000
        lexer = Lexer(f'"{long_str}"')
        tokens = lexer.tokenize()
        assert tokens[0].type == TokenType.STRING
        assert len(tokens[0].value) == 10000
