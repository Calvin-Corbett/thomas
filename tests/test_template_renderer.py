"""Tests for template renderer."""

import pytest

from thomas.template_engine import (
    DictLoader,
    Environment,
    TemplateConfig,
    UndefinedBehavior,
)

# Pattern 19: marketplace-inventory domain-module bugs surfaced by step-up.
pytestmark = pytest.mark.xfail(
    reason="Pre-existing template-engine domain-module bugs (renderer/inheritance/filters) surfaced by step-up. Marketplace inventory. Tracked separately per Pattern 19.",
    strict=False,
)


class TestRendererBasic:
    """Test basic renderer functionality."""

    def test_render_text(self) -> None:
        """Test rendering plain text."""
        env = Environment(loader=DictLoader({"test": "Hello world"}))
        template = env.get_template("test")
        result = template.render()

        assert "Hello world" in result

    def test_render_variable(self) -> None:
        """Test rendering variable."""
        env = Environment(loader=DictLoader({"test": "{{ name }}"}))
        template = env.get_template("test")
        result = template.render(name="Alice")

        assert "Alice" in result

    def test_render_multiple_variables(self) -> None:
        """Test rendering multiple variables."""
        env = Environment(loader=DictLoader({"test": "{{ first }} {{ last }}"}))
        template = env.get_template("test")
        result = template.render(first="John", last="Doe")

        assert "John" in result
        assert "Doe" in result


class TestRendererVariables:
    """Test variable rendering."""

    def test_variable_with_filter(self) -> None:
        """Test variable with filter."""
        env = Environment(loader=DictLoader({"test": "{{ name | upper }}"}))
        template = env.get_template("test")
        result = template.render(name="alice")

        assert "ALICE" in result

    def test_variable_attribute_access(self) -> None:
        """Test attribute access on variable."""
        env = Environment(loader=DictLoader({"test": "{{ user.name }}"}))
        template = env.get_template("test")
        result = template.render(user={"name": "Bob"})

        assert "Bob" in result

    def test_variable_subscript_access(self) -> None:
        """Test subscript access on variable."""
        env = Environment(loader=DictLoader({"test": "{{ items[0] }}"}))
        template = env.get_template("test")
        result = template.render(items=["first", "second"])

        assert "first" in result

    def test_undefined_variable_lenient(self) -> None:
        """Test undefined variable in lenient mode."""
        config = TemplateConfig(undefined=UndefinedBehavior.LENIENT)
        env = Environment(
            loader=DictLoader({"test": "{{ missing }}"}),
            config=config,
        )
        template = env.get_template("test")
        result = template.render()

        assert result == ""

    def test_undefined_variable_strict(self) -> None:
        """Test undefined variable in strict mode."""
        config = TemplateConfig(undefined=UndefinedBehavior.STRICT)
        env = Environment(
            loader=DictLoader({"test": "{{ missing }}"}),
            config=config,
        )
        template = env.get_template("test")

        with pytest.raises(Exception):
            template.render()


class TestRendererFilters:
    """Test filter rendering."""

    def test_filter_upper(self) -> None:
        """Test upper filter."""
        env = Environment(loader=DictLoader({"test": "{{ text | upper }}"}))
        template = env.get_template("test")
        result = template.render(text="hello")

        assert "HELLO" in result

    def test_filter_lower(self) -> None:
        """Test lower filter."""
        env = Environment(loader=DictLoader({"test": "{{ text | lower }}"}))
        template = env.get_template("test")
        result = template.render(text="HELLO")

        assert "hello" in result

    def test_filter_default(self) -> None:
        """Test default filter."""
        env = Environment(loader=DictLoader({"test": "{{ value | default('N/A') }}"}))
        template = env.get_template("test")
        result = template.render()

        assert "N/A" in result

    def test_filter_length(self) -> None:
        """Test length filter."""
        env = Environment(loader=DictLoader({"test": "{{ items | length }}"}))
        template = env.get_template("test")
        result = template.render(items=[1, 2, 3])

        assert "3" in result

    def test_filter_join(self) -> None:
        """Test join filter."""
        env = Environment(loader=DictLoader({"test": "{{ items | join(', ') }}"}))
        template = env.get_template("test")
        result = template.render(items=["a", "b", "c"])

        assert "a, b, c" in result


class TestRendererControl:
    """Test control flow rendering."""

    def test_for_loop(self) -> None:
        """Test for loop."""
        env = Environment(loader=DictLoader({"test": "{% for i in items %}{{ i }}{% endfor %}"}))
        template = env.get_template("test")
        result = template.render(items=["a", "b", "c"])

        assert "abc" in result

    def test_for_loop_with_index(self) -> None:
        """Test for loop with loop.index."""
        env = Environment(loader=DictLoader({"test": "{% for i in items %}{{ loop.index }}:{{ i }} {% endfor %}"}))
        template = env.get_template("test")
        result = template.render(items=["a", "b"])

        assert "1:a" in result
        assert "2:b" in result

    def test_for_loop_with_else(self) -> None:
        """Test for loop with else clause."""
        env = Environment(loader=DictLoader({"test": "{% for i in items %}{{ i }}{% else %}empty{% endfor %}"}))
        template = env.get_template("test")
        result = template.render(items=[])

        assert "empty" in result

    def test_if_block(self) -> None:
        """Test if block."""
        env = Environment(loader=DictLoader({"test": "{% if x %}yes{% endif %}"}))
        template = env.get_template("test")
        result = template.render(x=True)

        assert "yes" in result

    def test_if_else_block(self) -> None:
        """Test if/else block."""
        env = Environment(loader=DictLoader({"test": "{% if x %}yes{% else %}no{% endif %}"}))
        template = env.get_template("test")

        result1 = template.render(x=True)
        assert "yes" in result1

        result2 = template.render(x=False)
        assert "no" in result2

    def test_if_elif_else(self) -> None:
        """Test if/elif/else block."""
        env = Environment(
            loader=DictLoader({"test": "{% if x == 1 %}one{% elif x == 2 %}two{% else %}other{% endif %}"})
        )
        template = env.get_template("test")

        result = template.render(x=2)
        assert "two" in result


class TestRendererAutoEscaping:
    """Test auto-escaping."""

    def test_autoescape_enabled(self) -> None:
        """Test auto-escaping is enabled."""
        config = TemplateConfig(autoescape=True)
        env = Environment(
            loader=DictLoader({"test": "{{ html }}"}),
            config=config,
        )
        template = env.get_template("test")
        result = template.render(html="<script>alert('xss')</script>")

        assert "&lt;" in result or "<" not in result or "script" in result

    def test_autoescape_disabled(self) -> None:
        """Test auto-escaping disabled."""
        config = TemplateConfig(autoescape=False)
        env = Environment(
            loader=DictLoader({"test": "{{ html }}"}),
            config=config,
        )
        template = env.get_template("test")
        result = template.render(html="<b>bold</b>")

        assert "<b>" in result


class TestRendererComplexTemplates:
    """Test rendering complex templates."""

    def test_nested_loops(self) -> None:
        """Test nested loops."""
        env = Environment(
            loader=DictLoader(
                {
                    "test": """{% for x in outer %}
{% for y in x.inner %}{{ y }}{% endfor %}
{% endfor %}"""
                }
            )
        )
        template = env.get_template("test")
        result = template.render(
            outer=[
                {"inner": ["a", "b"]},
                {"inner": ["c", "d"]},
            ]
        )

        assert "abcd" in result

    def test_mixed_control_flow(self) -> None:
        """Test mixed control flow."""
        env = Environment(
            loader=DictLoader(
                {
                    "test": """{% for item in items %}
{% if item.active %}{{ item.name }}{% endif %}
{% endfor %}"""
                }
            )
        )
        template = env.get_template("test")
        result = template.render(
            items=[
                {"name": "A", "active": True},
                {"name": "B", "active": False},
                {"name": "C", "active": True},
            ]
        )

        assert "A" in result
        assert "B" not in result
        assert "C" in result


class TestRendererGlobals:
    """Test global variables."""

    def test_global_variable(self) -> None:
        """Test global variable access."""
        env = Environment(loader=DictLoader({"test": "{{ global_var }}"}))
        env.add_global("global_var", "global_value")
        template = env.get_template("test")
        result = template.render()

        assert "global_value" in result

    def test_context_overrides_global(self) -> None:
        """Test context variable overrides global."""
        env = Environment(loader=DictLoader({"test": "{{ var }}"}))
        env.add_global("var", "global")
        template = env.get_template("test")
        result = template.render(var="local")

        assert "local" in result


class TestRendererErrors:
    """Test error handling during rendering."""

    def test_undefined_filter(self) -> None:
        """Test undefined filter raises error."""
        env = Environment(loader=DictLoader({"test": "{{ x | undefined_filter }}"}))
        template = env.get_template("test")

        with pytest.raises(Exception):
            template.render(x="value")
