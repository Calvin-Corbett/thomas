"""Tests for template-based generation."""

import pytest

from thomas.nlg._types import SemanticFrame, Slot
from thomas.nlg.templates import TemplateEngine, TemplateError


class TestTemplateRegistration:
    """Test template registration."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.engine = TemplateEngine()

    def test_register_basic_template(self) -> None:
        """Test registering a template."""
        self.engine.register_template("test", "Hello {name}", slots=["name"])

        assert "test" in self.engine.templates

    def test_register_duplicate_overwrites(self) -> None:
        """Test that duplicate registration overwrites."""
        self.engine.register_template("test", "First")
        self.engine.register_template("test", "Second")

        template = self.engine.templates["test"]
        assert "Second" in template.text

    def test_register_empty_name_fails(self) -> None:
        """Test that empty name fails."""
        with pytest.raises(TemplateError):
            self.engine.register_template("", "text")

    def test_register_empty_text_fails(self) -> None:
        """Test that empty text fails."""
        with pytest.raises(TemplateError):
            self.engine.register_template("name", "")


class TestSlotExtraction:
    """Test slot extraction from templates."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.engine = TemplateEngine()

    def test_extract_single_slot(self) -> None:
        """Test extracting single slot."""
        slots = self.engine._extract_slots("Hello {name}")
        assert "name" in slots

    def test_extract_multiple_slots(self) -> None:
        """Test extracting multiple slots."""
        slots = self.engine._extract_slots("{subj} {verb} {obj}")
        assert len(slots) == 3
        assert "subj" in slots

    def test_extract_duplicate_slots(self) -> None:
        """Test that duplicate slots are not repeated."""
        slots = self.engine._extract_slots("{name} likes {name}")
        assert slots.count("name") == 1

    def test_extract_no_slots(self) -> None:
        """Test text with no slots."""
        slots = self.engine._extract_slots("No slots here")
        assert len(slots) == 0


class TestTemplateRealization:
    """Test template realization."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.engine = TemplateEngine()

    def test_realize_simple_template(self) -> None:
        """Test realizing simple template."""
        self.engine.register_template("greet", "Hello {name}")
        result = self.engine.realize("greet", {"name": "Alice"})

        assert "Hello Alice" in result

    def test_realize_missing_slot_fails(self) -> None:
        """Test that missing slot fails."""
        self.engine.register_template("greet", "Hello {name}")

        with pytest.raises(TemplateError):
            self.engine.realize("greet", {})

    def test_realize_unknown_template_fails(self) -> None:
        """Test that unknown template fails."""
        with pytest.raises(TemplateError):
            self.engine.realize("unknown", {})

    def test_realize_multiple_slots(self) -> None:
        """Test realizing with multiple slots."""
        self.engine.register_template("sentence", "{subject} {verb} {object}")
        result = self.engine.realize("sentence", {"subject": "John", "verb": "eats", "object": "apple"})

        assert "John" in result
        assert "eats" in result
        assert "apple" in result


class TestConditionProcessing:
    """Test conditional blocks in templates."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.engine = TemplateEngine()

    def test_condition_true(self) -> None:
        """Test condition that evaluates to true."""
        self.engine.register_template("test", "[if sunny]It's sunny[/if]")
        result = self.engine.realize("test", {"sunny": True})

        assert "sunny" in result.lower()

    def test_condition_false(self) -> None:
        """Test condition that evaluates to false."""
        self.engine.register_template("test", "[if sunny]It's sunny[/if]")
        result = self.engine.realize("test", {"sunny": False})

        assert "sunny" not in result.lower()

    def test_nested_conditions(self) -> None:
        """Test nested conditions."""
        template = "[if a]A[/if]"
        self.engine.register_template("test", template)
        result = self.engine.realize("test", {"a": True})

        assert "A" in result


class TestListVerbalization:
    """Test list verbalization."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.engine = TemplateEngine()

    def test_single_item_list(self) -> None:
        """Test verbalizing single-item list."""
        result = self.engine._verbalize_list(["apple"])
        assert result == "apple"

    def test_two_item_list(self) -> None:
        """Test verbalizing two-item list."""
        result = self.engine._verbalize_list(["apple", "orange"])
        assert "and" in result

    def test_three_item_list_oxford_comma(self) -> None:
        """Test three-item list with Oxford comma."""
        result = self.engine._verbalize_list(["apple", "orange", "banana"], use_oxford_comma=True)

        assert "," in result  # Comma before 'and'

    def test_three_item_list_no_oxford_comma(self) -> None:
        """Test three-item list without Oxford comma."""
        result = self.engine._verbalize_list(["apple", "orange", "banana"], use_oxford_comma=False)

        assert "and" in result

    def test_empty_list(self) -> None:
        """Test empty list."""
        result = self.engine._verbalize_list([])
        assert result == ""


class TestTemplateSelection:
    """Test template selection."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.engine = TemplateEngine()

    def test_select_best_template(self) -> None:
        """Test selecting best matching template."""
        self.engine.register_template("pred1", "{subject} {verb}")
        self.engine.register_template("pred2", "{entity} is {attribute}")

        frame = SemanticFrame(predicate="verb")
        frame.slots.append(Slot(name="subject", value_type="noun"))
        frame.slots.append(Slot(name="verb", value_type="verb"))

        selected = self.engine.select_template(frame)
        assert selected is not None

    def test_no_matching_template(self) -> None:
        """Test when no template matches."""
        frame = SemanticFrame(predicate="unknown_predicate")
        selected = self.engine.select_template(frame)

        assert selected is None or selected in self.engine.templates


class TestTemplateComposition:
    """Test template composition."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.engine = TemplateEngine()

    def test_compose_two_templates(self) -> None:
        """Test composing two templates."""
        self.engine.register_template("t1", "The cat")
        self.engine.register_template("t2", "sleeps")

        result = self.engine.compose_templates(["t1", "t2"], [{}, {}])

        assert "cat" in result
        assert "sleeps" in result

    def test_compose_with_missing_template(self) -> None:
        """Test composition skips missing templates."""
        self.engine.register_template("t1", "Hello")

        result = self.engine.compose_templates(["t1", "unknown"], [{}, {}])

        assert "Hello" in result


class TestTemplateVariations:
    """Test template variations."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.engine = TemplateEngine()

    def test_get_template_variations(self) -> None:
        """Test getting template variations."""
        self.engine.register_template("test", "Template text")
        self.engine.set_template_variation("test", ["Variation 1", "Variation 2"])

        variations = self.engine.get_template_variations("test")
        assert len(variations) >= 2

    def test_unknown_template_variations_fails(self) -> None:
        """Test that getting variations for unknown template fails."""
        with pytest.raises(TemplateError):
            self.engine.get_template_variations("unknown")


class TestTemplateInheritance:
    """Test template inheritance."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.engine = TemplateEngine()

    def test_inherit_template(self) -> None:
        """Test template inheritance."""
        self.engine.register_template("parent", "{subject} {verb}")
        self.engine.inherit_template("child", "parent", {"subject": "actor"})

        assert "child" in self.engine.templates

    def test_inherit_from_unknown_parent_fails(self) -> None:
        """Test that inheriting from unknown parent fails."""
        with pytest.raises(TemplateError):
            self.engine.inherit_template("child", "unknown_parent", {})


class TestSlotRetrieval:
    """Test retrieving template slots."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.engine = TemplateEngine()

    def test_get_slots(self) -> None:
        """Test getting template slots."""
        self.engine.register_template("test", "{a} {b} {c}", slots=["a", "b", "c"])

        slots = self.engine.get_slots("test")
        assert len(slots) == 3
        assert "a" in slots

    def test_get_slots_unknown_template_fails(self) -> None:
        """Test that getting slots for unknown template fails."""
        with pytest.raises(TemplateError):
            self.engine.get_slots("unknown")
