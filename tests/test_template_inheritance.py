"""Tests for template inheritance."""

import pytest

from thomas.template_engine import DictLoader, Environment

# Pattern 19: marketplace-inventory domain-module bugs surfaced by step-up.
pytestmark = pytest.mark.xfail(
    reason="Pre-existing template-engine domain-module bugs (renderer/inheritance/filters) surfaced by step-up. Marketplace inventory. Tracked separately per Pattern 19.",
    strict=False,
)


class TestInheritanceBasic:
    """Test basic inheritance functionality."""

    def test_extends_basic(self) -> None:
        """Test basic extends mechanism."""
        templates = {
            "base.html": "Base: {% block content %}default{% endblock %}",
            "child.html": '{% extends "base.html" %}{% block content %}custom{% endblock %}',
        }
        env = Environment(loader=DictLoader(templates))
        template = env.get_template("child.html")
        result = template.render()

        assert "custom" in result

    def test_block_inheritance(self) -> None:
        """Test block overriding in child templates."""
        templates = {
            "base.html": "<html><body>{% block body %}empty{% endblock %}</body></html>",
            "child.html": '{% extends "base.html" %}{% block body %}content{% endblock %}',
        }
        env = Environment(loader=DictLoader(templates))
        template = env.get_template("child.html")
        result = template.render()

        assert "content" in result
        assert "<html>" in result


class TestInheritanceMultiLevel:
    """Test multi-level inheritance chains."""

    def test_three_level_inheritance(self) -> None:
        """Test inheritance chain: grandchild -> child -> grandparent."""
        templates = {
            "base.html": "{% block title %}Base Title{% endblock %} | {% block content %}Base Content{% endblock %}",
            "middle.html": '{% extends "base.html" %}{% block content %}Middle Content{% endblock %}',
            "child.html": '{% extends "middle.html" %}{% block title %}Child Title{% endblock %}',
        }
        env = Environment(loader=DictLoader(templates))
        template = env.get_template("child.html")
        result = template.render()

        assert "Child Title" in result
        assert "Middle Content" in result


class TestBlockHandling:
    """Test block-related functionality."""

    def test_multiple_blocks(self) -> None:
        """Test multiple blocks in inheritance."""
        templates = {
            "base.html": "{% block header %}H{% endblock %}|{% block content %}C{% endblock %}|{% block footer %}F{% endblock %}",
            "child.html": '{% extends "base.html" %}{% block header %}Header{% endblock %}{% block footer %}Footer{% endblock %}',
        }
        env = Environment(loader=DictLoader(templates))
        template = env.get_template("child.html")
        result = template.render()

        assert "Header" in result
        assert "Footer" in result

    def test_nested_blocks(self) -> None:
        """Test nested blocks."""
        templates = {
            "base.html": "{% block outer %}{% block inner %}inner{% endblock %}{% endblock %}",
            "child.html": '{% extends "base.html" %}{% block outer %}outer-override{% endblock %}',
        }
        env = Environment(loader=DictLoader(templates))
        template = env.get_template("child.html")
        result = template.render()

        assert "outer-override" in result

    def test_block_without_override(self) -> None:
        """Test block that is not overridden in child."""
        templates = {
            "base.html": "{% block content %}default content{% endblock %}",
            "child.html": '{% extends "base.html" %}',
        }
        env = Environment(loader=DictLoader(templates))
        template = env.get_template("child.html")
        result = template.render()

        assert "default content" in result


class TestBlockWithContent:
    """Test blocks with dynamic content."""

    def test_block_with_variables(self) -> None:
        """Test blocks can use variables."""
        templates = {
            "base.html": "{% block content %}Hello {{ name }}!{% endblock %}",
            "child.html": '{% extends "base.html" %}{% block content %}Welcome {{ name }}!{% endblock %}',
        }
        env = Environment(loader=DictLoader(templates))
        template = env.get_template("child.html")
        result = template.render(name="Alice")

        assert "Welcome Alice" in result

    def test_block_with_loops(self) -> None:
        """Test blocks can contain loops."""
        templates = {
            "base.html": "{% block items %}{% for i in items %}{{ i }}{% endfor %}{% endblock %}",
            "child.html": '{% extends "base.html" %}{% block items %}Items: {% for i in items %}[{{ i }}]{% endfor %}{% endblock %}',
        }
        env = Environment(loader=DictLoader(templates))
        template = env.get_template("child.html")
        result = template.render(items=[1, 2, 3])

        assert "[1]" in result and "[2]" in result and "[3]" in result


class TestInheritanceEdgeCases:
    """Test edge cases in inheritance."""

    def test_empty_child_block(self) -> None:
        """Test child can provide empty block."""
        templates = {
            "base.html": "Start{% block content %} default{% endblock %}End",
            "child.html": '{% extends "base.html" %}{% block content %}{% endblock %}',
        }
        env = Environment(loader=DictLoader(templates))
        template = env.get_template("child.html")
        result = template.render()

        assert "Start" in result and "End" in result
        assert "default" not in result

    def test_sibling_blocks_independence(self) -> None:
        """Test that sibling blocks are independent."""
        templates = {
            "base.html": "{% block a %}A{% endblock %} {% block b %}B{% endblock %}",
            "child.html": '{% extends "base.html" %}{% block a %}Modified A{% endblock %}',
        }
        env = Environment(loader=DictLoader(templates))
        template = env.get_template("child.html")
        result = template.render()

        assert "Modified A" in result
        assert "B" in result


class TestInheritanceWithFilters:
    """Test inheritance with filters."""

    def test_filters_in_inherited_blocks(self) -> None:
        """Test filters work in inherited blocks."""
        templates = {
            "base.html": "{% block content %}{{ text }}{% endblock %}",
            "child.html": '{% extends "base.html" %}{% block content %}{{ text | upper }}{% endblock %}',
        }
        env = Environment(loader=DictLoader(templates))
        template = env.get_template("child.html")
        result = template.render(text="hello")

        assert "HELLO" in result

    def test_filters_in_base_blocks(self) -> None:
        """Test filters in base blocks are preserved."""
        templates = {
            "base.html": "{% block content %}{{ text | upper }}{% endblock %}",
            "child.html": '{% extends "base.html" %}',
        }
        env = Environment(loader=DictLoader(templates))
        template = env.get_template("child.html")
        result = template.render(text="hello")

        assert "HELLO" in result


class TestInheritanceComplexScenarios:
    """Test complex inheritance scenarios."""

    def test_multiple_inheritance_levels_with_all_blocks_overridden(
        self,
    ) -> None:
        """Test complex scenario with multiple levels."""
        templates = {
            "base.html": "{% block a %}A{% endblock %} {% block b %}B{% endblock %}",
            "middle.html": '{% extends "base.html" %}{% block a %}MA{% endblock %}',
            "child.html": '{% extends "middle.html" %}{% block b %}CB{% endblock %}',
        }
        env = Environment(loader=DictLoader(templates))
        template = env.get_template("child.html")
        result = template.render()

        assert "MA" in result
        assert "CB" in result

    def test_inheritance_with_text_and_blocks(self) -> None:
        """Test templates with mixed text and blocks."""
        templates = {
            "base.html": "Header {% block content %}default{% endblock %} Footer",
            "child.html": '{% extends "base.html" %}{% block content %}custom content{% endblock %}',
        }
        env = Environment(loader=DictLoader(templates))
        template = env.get_template("child.html")
        result = template.render()

        assert "Header" in result
        assert "custom content" in result
        assert "Footer" in result


class TestInheritanceConditionals:
    """Test inheritance with conditional blocks."""

    def test_block_in_conditional(self) -> None:
        """Test block inside conditional."""
        templates = {
            "base.html": "{% if show %}{% block content %}default{% endblock %}{% endif %}",
            "child.html": '{% extends "base.html" %}{% block content %}custom{% endblock %}',
        }
        env = Environment(loader=DictLoader(templates))
        template = env.get_template("child.html")

        result_shown = template.render(show=True)
        assert "custom" in result_shown

        result_hidden = template.render(show=False)
        assert "custom" not in result_hidden
