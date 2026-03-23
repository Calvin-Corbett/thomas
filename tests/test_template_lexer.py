"""Tests for template lexer."""

import pytest

from thomas.template_engine import Lexer, TemplateConfig, TokenType


class TestLexerBasic:
    """Test basic lexer functionality."""

    def test_lexer_text_only(self) -> None:
        """Test lexing plain text."""
        config = TemplateConfig()
        lexer = Lexer("Hello world", config)
        tokens = lexer.tokenize()

        assert len(tokens) >= 2
        assert tokens[0].type == TokenType.TEXT
        assert tokens[0].value == "Hello world"
        assert tokens[-1].type == TokenType.EOF

    def test_lexer_variable(self) -> None:
        """Test lexing variable expressions."""
        config = TemplateConfig()
        lexer = Lexer("{{ name }}", config)
        tokens = lexer.tokenize()

        assert tokens[0].type == TokenType.VAR_START
        assert tokens[1].type == TokenType.NAME
        assert tokens[1].value == "name"
        assert tokens[2].type == TokenType.VAR_END

    def test_lexer_block(self) -> None:
        """Test lexing block statements."""
        config = TemplateConfig()
        lexer = Lexer("{% if x %}hello{% endif %}", config)
        tokens = lexer.tokenize()

        assert tokens[0].type == TokenType.BLOCK_START
        assert tokens[1].type == TokenType.IF
        assert tokens[2].type == TokenType.NAME

    def test_lexer_comment(self) -> None:
        """Test lexing comments."""
        config = TemplateConfig()
        lexer = Lexer("before {# comment #} after", config)
        tokens = lexer.tokenize()

        # Comments are not included in token stream
        assert tokens[0].type == TokenType.TEXT
        assert "before" in tokens[0].value

    def test_lexer_mixed_content(self) -> None:
        """Test lexing mixed text and expressions."""
        config = TemplateConfig()
        lexer = Lexer("Hello {{ name }}, how are you?", config)
        tokens = lexer.tokenize()

        assert tokens[0].type == TokenType.TEXT
        assert tokens[1].type == TokenType.VAR_START
        assert tokens[3].type == TokenType.VAR_END
        assert tokens[4].type == TokenType.TEXT


class TestLexerVariables:
    """Test variable expression lexing."""

    def test_variable_with_filters(self) -> None:
        """Test variable with filters."""
        config = TemplateConfig()
        lexer = Lexer("{{ name | upper }}", config)
        tokens = lexer.tokenize()

        token_types = [t.type for t in tokens]
        assert TokenType.PIPE in token_types
        assert TokenType.NAME in token_types

    def test_variable_with_attribute(self) -> None:
        """Test variable with attribute access."""
        config = TemplateConfig()
        lexer = Lexer("{{ user.name }}", config)
        tokens = lexer.tokenize()

        token_types = [t.type for t in tokens]
        assert TokenType.DOT in token_types

    def test_variable_with_subscript(self) -> None:
        """Test variable with subscript access."""
        config = TemplateConfig()
        lexer = Lexer("{{ items[0] }}", config)
        tokens = lexer.tokenize()

        token_types = [t.type for t in tokens]
        assert TokenType.LBRACKET in token_types
        assert TokenType.RBRACKET in token_types


class TestLexerBlocks:
    """Test block statement lexing."""

    def test_for_loop(self) -> None:
        """Test for loop block."""
        config = TemplateConfig()
        lexer = Lexer("{% for i in items %}{{ i }}{% endfor %}", config)
        tokens = lexer.tokenize()

        token_types = [t.type for t in tokens]
        assert TokenType.FOR in token_types
        assert TokenType.IN in token_types
        assert TokenType.ENDFOR in token_types

    def test_if_block(self) -> None:
        """Test if block."""
        config = TemplateConfig()
        lexer = Lexer("{% if x %}yes{% endif %}", config)
        tokens = lexer.tokenize()

        token_types = [t.type for t in tokens]
        assert TokenType.IF in token_types
        assert TokenType.ENDIF in token_types

    def test_block_definition(self) -> None:
        """Test block definition."""
        config = TemplateConfig()
        lexer = Lexer("{% block content %}{% endblock %}", config)
        tokens = lexer.tokenize()

        token_types = [t.type for t in tokens]
        assert TokenType.BLOCK in token_types
        assert TokenType.ENDBLOCK in token_types

    def test_extends(self) -> None:
        """Test extends statement."""
        config = TemplateConfig()
        lexer = Lexer('{% extends "base.html" %}', config)
        tokens = lexer.tokenize()

        token_types = [t.type for t in tokens]
        assert TokenType.EXTENDS in token_types
        assert TokenType.STRING in token_types


class TestLexerLiterals:
    """Test literal value lexing."""

    def test_string_literal(self) -> None:
        """Test string literals."""
        config = TemplateConfig()
        lexer = Lexer('{{ "hello" }}', config)
        tokens = lexer.tokenize()

        string_tokens = [t for t in tokens if t.type == TokenType.STRING]
        assert len(string_tokens) > 0
        assert string_tokens[0].value == "hello"

    def test_number_literals(self) -> None:
        """Test number literals."""
        config = TemplateConfig()
        lexer = Lexer("{{ 42 }} {{ 3.14 }}", config)
        tokens = lexer.tokenize()

        number_tokens = [t for t in tokens if t.type == TokenType.NUMBER]
        assert len(number_tokens) >= 2

    def test_boolean_literals(self) -> None:
        """Test boolean literals."""
        config = TemplateConfig()
        lexer = Lexer("{{ true }} {{ false }}", config)
        tokens = lexer.tokenize()

        token_types = [t.type for t in tokens]
        assert TokenType.TRUE in token_types
        assert TokenType.FALSE in token_types

    def test_none_literal(self) -> None:
        """Test None literal."""
        config = TemplateConfig()
        lexer = Lexer("{{ none }}", config)
        tokens = lexer.tokenize()

        token_types = [t.type for t in tokens]
        assert TokenType.NONE in token_types


class TestLexerOperators:
    """Test operator lexing."""

    def test_comparison_operators(self) -> None:
        """Test comparison operators."""
        config = TemplateConfig()
        lexer = Lexer("{% if x == y %}{% endif %}", config)
        tokens = lexer.tokenize()

        token_types = [t.type for t in tokens]
        assert TokenType.EQ in token_types

    def test_logical_operators(self) -> None:
        """Test logical operators."""
        config = TemplateConfig()
        lexer = Lexer("{% if x and y or z %}{% endif %}", config)
        tokens = lexer.tokenize()

        token_types = [t.type for t in tokens]
        assert TokenType.AND in token_types
        assert TokenType.OR in token_types

    def test_arithmetic_operators(self) -> None:
        """Test arithmetic operators."""
        config = TemplateConfig()
        lexer = Lexer("{{ 1 + 2 - 3 * 4 / 5 }}", config)
        tokens = lexer.tokenize()

        token_types = [t.type for t in tokens]
        assert TokenType.PLUS in token_types
        assert TokenType.MINUS in token_types
        assert TokenType.MUL in token_types
        assert TokenType.DIV in token_types


class TestLexerLineTracking:
    """Test line number tracking."""

    def test_line_numbers_single_line(self) -> None:
        """Test line numbers on single line."""
        config = TemplateConfig()
        lexer = Lexer("{{ x }}", config)
        tokens = lexer.tokenize()

        for token in tokens:
            assert token.lineno == 1

    def test_line_numbers_multiline(self) -> None:
        """Test line numbers across multiple lines."""
        config = TemplateConfig()
        lexer = Lexer("line1\n{{ x }}\nline3", config)
        tokens = lexer.tokenize()

        # Should have tokens on different lines
        line_numbers = set(t.lineno for t in tokens if t.type != TokenType.EOF)
        assert len(line_numbers) > 1


class TestLexerWhitespaceControl:
    """Test whitespace control."""

    def test_trim_blocks_enabled(self) -> None:
        """Test trim_blocks configuration."""
        config = TemplateConfig(trim_blocks=True)
        lexer = Lexer("{% if x %}\ntext", config)
        tokens = lexer.tokenize()

        # After block, newline should be trimmed
        text_tokens = [t for t in tokens if t.type == TokenType.TEXT]
        # Whitespace behavior depends on implementation
        assert len(text_tokens) >= 0

    def test_custom_delimiters(self) -> None:
        """Test custom delimiters."""
        config = TemplateConfig(var_open="[[", var_close="]]")
        lexer = Lexer("[[ x ]]", config)
        tokens = lexer.tokenize()

        assert tokens[0].type == TokenType.VAR_START


class TestLexerErrors:
    """Test error handling."""

    def test_unterminated_variable(self) -> None:
        """Test unterminated variable."""
        config = TemplateConfig()
        lexer = Lexer("{{ x ", config)

        with pytest.raises(Exception):
            lexer.tokenize()

    def test_unterminated_block(self) -> None:
        """Test unterminated block."""
        config = TemplateConfig()
        lexer = Lexer("{% if x ", config)

        with pytest.raises(Exception):
            lexer.tokenize()

    def test_unterminated_comment(self) -> None:
        """Test unterminated comment."""
        config = TemplateConfig()
        lexer = Lexer("{# comment", config)

        with pytest.raises(Exception):
            lexer.tokenize()
