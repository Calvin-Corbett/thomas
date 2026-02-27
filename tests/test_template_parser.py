"""Tests for template parser."""

import pytest

from thomas.template_engine import (
    Block,
    Extends,
    ForLoop,
    IfBlock,
    Include,
    Lexer,
    Macro,
    Parser,
    TemplateConfig,
    Variable,
)


class TestParserBasic:
    """Test basic parser functionality."""

    def test_parse_text(self) -> None:
        """Test parsing plain text."""
        config = TemplateConfig()
        lexer = Lexer("Hello world", config)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        assert len(ast.body) > 0

    def test_parse_variable(self) -> None:
        """Test parsing variable expression."""
        config = TemplateConfig()
        lexer = Lexer("{{ name }}", config)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        assert len(ast.body) > 0
        assert any(isinstance(node, Variable) for node in ast.body)

    def test_parse_mixed_content(self) -> None:
        """Test parsing mixed text and expressions."""
        config = TemplateConfig()
        lexer = Lexer("Hello {{ name }}, welcome!", config)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        assert len(ast.body) > 0


class TestParserVariables:
    """Test variable expression parsing."""

    def test_variable_with_filters(self) -> None:
        """Test variable with filters."""
        config = TemplateConfig()
        lexer = Lexer("{{ name | upper }}", config)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        var_nodes = [n for n in ast.body if isinstance(n, Variable)]
        assert len(var_nodes) > 0
        assert len(var_nodes[0].filters) > 0

    def test_multiple_filters(self) -> None:
        """Test variable with multiple filters."""
        config = TemplateConfig()
        lexer = Lexer("{{ name | upper | trim }}", config)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        var_nodes = [n for n in ast.body if isinstance(n, Variable)]
        assert len(var_nodes) > 0
        assert len(var_nodes[0].filters) == 2

    def test_filter_with_arguments(self) -> None:
        """Test filter with arguments."""
        config = TemplateConfig()
        lexer = Lexer("{{ text | truncate(10) }}", config)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        var_nodes = [n for n in ast.body if isinstance(n, Variable)]
        assert len(var_nodes) > 0


class TestParserControl:
    """Test control flow parsing."""

    def test_for_loop(self) -> None:
        """Test for loop parsing."""
        config = TemplateConfig()
        lexer = Lexer("{% for item in items %}{{ item }}{% endfor %}", config)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        for_nodes = [n for n in ast.body if isinstance(n, ForLoop)]
        assert len(for_nodes) > 0
        assert for_nodes[0].target == "item"

    def test_for_loop_with_else(self) -> None:
        """Test for loop with else clause."""
        config = TemplateConfig()
        lexer = Lexer("{% for i in items %}{{ i }}{% else %}empty{% endfor %}", config)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        for_nodes = [n for n in ast.body if isinstance(n, ForLoop)]
        assert len(for_nodes) > 0
        assert len(for_nodes[0].orelse) > 0

    def test_if_block(self) -> None:
        """Test if block parsing."""
        config = TemplateConfig()
        lexer = Lexer("{% if x %}yes{% endif %}", config)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        if_nodes = [n for n in ast.body if isinstance(n, IfBlock)]
        assert len(if_nodes) > 0

    def test_if_elif_else(self) -> None:
        """Test if/elif/else parsing."""
        config = TemplateConfig()
        lexer = Lexer("{% if x %}a{% elif y %}b{% else %}c{% endif %}", config)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        if_nodes = [n for n in ast.body if isinstance(n, IfBlock)]
        assert len(if_nodes) > 0
        assert len(if_nodes[0].tests) == 3


class TestParserBlocks:
    """Test block definition parsing."""

    def test_named_block(self) -> None:
        """Test named block parsing."""
        config = TemplateConfig()
        lexer = Lexer("{% block content %}text{% endblock %}", config)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        block_nodes = [n for n in ast.body if isinstance(n, Block)]
        assert len(block_nodes) > 0
        assert block_nodes[0].name == "content"

    def test_nested_blocks(self) -> None:
        """Test nested blocks."""
        config = TemplateConfig()
        lexer = Lexer(
            "{% block outer %}{% block inner %}text{% endblock %}{% endblock %}",
            config,
        )
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        block_nodes = [n for n in ast.body if isinstance(n, Block)]
        assert len(block_nodes) > 0


class TestParserInheritance:
    """Test template inheritance parsing."""

    def test_extends(self) -> None:
        """Test extends parsing."""
        config = TemplateConfig()
        lexer = Lexer('{% extends "base.html" %}', config)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        extends_nodes = [n for n in ast.body if isinstance(n, Extends)]
        assert len(extends_nodes) > 0
        assert extends_nodes[0].parent == "base.html"

    def test_include(self) -> None:
        """Test include parsing."""
        config = TemplateConfig()
        lexer = Lexer('{% include "partial.html" %}', config)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        include_nodes = [n for n in ast.body if isinstance(n, Include)]
        assert len(include_nodes) > 0


class TestParserMacros:
    """Test macro parsing."""

    def test_macro_definition(self) -> None:
        """Test macro definition parsing."""
        config = TemplateConfig()
        lexer = Lexer("{% macro greeting(name) %}Hello {{ name }}!{% endmacro %}", config)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        macro_nodes = [n for n in ast.body if isinstance(n, Macro)]
        assert len(macro_nodes) > 0
        assert macro_nodes[0].name == "greeting"
        assert "name" in macro_nodes[0].args

    def test_macro_with_defaults(self) -> None:
        """Test macro with default arguments."""
        config = TemplateConfig()
        lexer = Lexer(
            '{% macro greet(name, greeting="Hello") %}{{ greeting }} {{ name }}!{% endmacro %}',
            config,
        )
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        macro_nodes = [n for n in ast.body if isinstance(n, Macro)]
        assert len(macro_nodes) > 0
        assert "greeting" in macro_nodes[0].defaults


class TestParserExpressions:
    """Test expression parsing."""

    def test_variable_reference(self) -> None:
        """Test simple variable reference."""
        config = TemplateConfig()
        lexer = Lexer("{{ x }}", config)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        assert len(ast.body) > 0

    def test_attribute_access(self) -> None:
        """Test attribute access."""
        config = TemplateConfig()
        lexer = Lexer("{{ user.name }}", config)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        assert len(ast.body) > 0

    def test_subscript_access(self) -> None:
        """Test subscript access."""
        config = TemplateConfig()
        lexer = Lexer("{{ items[0] }}", config)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        assert len(ast.body) > 0

    def test_method_call(self) -> None:
        """Test method calls."""
        config = TemplateConfig()
        lexer = Lexer("{{ text | upper }}", config)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        assert len(ast.body) > 0


class TestParserComplexTemplates:
    """Test parsing complex templates."""

    def test_template_with_inheritance(self) -> None:
        """Test template with block inheritance."""
        config = TemplateConfig()
        source = """
{% extends "base.html" %}
{% block content %}
    {% for item in items %}
        <div>{{ item.name }}</div>
    {% endfor %}
{% endblock %}
"""
        lexer = Lexer(source, config)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        assert len(ast.body) > 0

    def test_deeply_nested_template(self) -> None:
        """Test deeply nested template structures."""
        config = TemplateConfig()
        source = """
{% for x in items %}
    {% if x.active %}
        {% for y in x.subitems %}
            {{ y.name | upper }}
        {% endfor %}
    {% endif %}
{% endfor %}
"""
        lexer = Lexer(source, config)
        tokens = lexer.tokenize()
        parser = Parser(tokens)
        ast = parser.parse()

        assert len(ast.body) > 0


class TestParserErrors:
    """Test error handling."""

    def test_mismatched_block_end(self) -> None:
        """Test mismatched block endings."""
        config = TemplateConfig()
        lexer = Lexer("{% for x in y %}text{% endif %}", config)
        tokens = lexer.tokenize()
        parser = Parser(tokens)

        with pytest.raises(Exception):
            parser.parse()

    def test_unexpected_token(self) -> None:
        """Test unexpected tokens."""
        config = TemplateConfig()
        lexer = Lexer("{% endfor %}", config)
        tokens = lexer.tokenize()
        parser = Parser(tokens)

        with pytest.raises(Exception):
            parser.parse()
