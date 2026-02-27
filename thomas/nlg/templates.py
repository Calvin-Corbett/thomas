"""Template-based generation: pattern-based text realization.

Implements template-based text generation including:
- Template language with slots and conditions
- Template selection based on context
- Template composition and nesting
- Template variation and alternation
- Conditional text blocks
- List verbalization
- Template inheritance
"""

import re
from dataclasses import dataclass
from typing import Any, Optional

from thomas.nlg._exceptions import NLGException
from thomas.nlg._types import SemanticFrame


class TemplateError(NLGException):
    """Raised when template processing fails."""

    pass


@dataclass
class Template:
    """A text generation template."""

    name: str
    text: str
    slots: list[str]
    conditions: dict[str, str] = None
    variations: list[str] = None
    parent: Optional["Template"] = None

    def __post_init__(self) -> None:
        """Initialize template."""
        if self.conditions is None:
            self.conditions = {}
        if self.variations is None:
            self.variations = []


class TemplateEngine:
    """Generates text from templates.

    Implements template-based generation with slots, conditions,
    and inheritance for pattern-based text realization.
    """

    def __init__(self) -> None:
        """Initialize template engine."""
        self.templates: dict[str, Template] = {}
        self.slot_pattern = re.compile(r"\{(\w+)\}")
        self.condition_pattern = re.compile(r"\[if\s+(\w+)\](.*?)\[/if\]")
        self.list_pattern = re.compile(r"\[list\](.*?)\[/list\]")
        self._load_default_templates()

    def _load_default_templates(self) -> None:
        """Load default templates."""
        # Simple predication
        self.register_template(
            "simple_predicate",
            "{subject} {predicate} {object}",
            slots=["subject", "predicate", "object"],
        )

        # Attribution
        self.register_template(
            "attribution",
            "{entity} is {attribute}",
            slots=["entity", "attribute"],
        )

        # Comparison
        self.register_template(
            "comparison",
            "{entity1} is more {property} than {entity2}",
            slots=["entity1", "property", "entity2"],
        )

    def register_template(
        self,
        name: str,
        text: str,
        slots: list[str] | None = None,
        conditions: dict[str, str] | None = None,
    ) -> None:
        """Register a template.

        Args:
            name: Template name
            text: Template text with slots
            slots: List of slot names
            conditions: Conditional blocks

        Raises:
            TemplateError: If template is invalid
        """
        if not name or not text:
            raise TemplateError("Template must have name and text")

        # Extract slots if not provided
        if slots is None:
            slots = self._extract_slots(text)

        template = Template(name=name, text=text, slots=slots, conditions=conditions or {})

        self.templates[name] = template

    def _extract_slots(self, text: str) -> list[str]:
        """Extract slot names from template text.

        Args:
            text: Template text

        Returns:
            List of slot names
        """
        slots = []
        for match in self.slot_pattern.finditer(text):
            slot_name = match.group(1)
            if slot_name not in slots:
                slots.append(slot_name)
        return slots

    def realize(self, template_name: str, bindings: dict[str, Any]) -> str:
        """Realize template with slot bindings.

        Args:
            template_name: Name of template
            bindings: Slot value bindings

        Returns:
            Realized text

        Raises:
            TemplateError: If realization fails
        """
        if template_name not in self.templates:
            raise TemplateError(f"Unknown template: {template_name}")

        template = self.templates[template_name]

        # Check required slots
        for slot in template.slots:
            if slot not in bindings:
                raise TemplateError(f"Missing required slot: {slot}")

        text = template.text

        # Process conditions
        text = self._process_conditions(text, bindings)

        # Process lists
        text = self._process_lists(text, bindings)

        # Fill slots
        text = self._fill_slots(text, bindings)

        return text.strip()

    def _process_conditions(self, text: str, bindings: dict[str, Any]) -> str:
        """Process conditional blocks in template.

        Args:
            text: Template text
            bindings: Slot bindings

        Returns:
            Text with conditions processed
        """

        def replace_condition(match: re.Match) -> str:
            condition = match.group(1)
            content = match.group(2)

            # Simple condition check
            if condition in bindings and bindings[condition]:
                return content
            else:
                return ""

        return self.condition_pattern.sub(replace_condition, text)

    def _process_lists(self, text: str, bindings: dict[str, Any]) -> str:
        """Process list verbalization.

        Args:
            text: Template text
            bindings: Slot bindings

        Returns:
            Text with lists verbalized
        """

        def replace_list(match: re.Match) -> str:
            list_content = match.group(1)
            # Parse list items
            items = [item.strip() for item in list_content.split(",")]

            # Verbalize
            return self._verbalize_list(items, use_oxford_comma=True)

        return self.list_pattern.sub(replace_list, text)

    def _verbalize_list(self, items: list[str], use_oxford_comma: bool = True) -> str:
        """Verbalize a list of items.

        Args:
            items: List items
            use_oxford_comma: Whether to use Oxford comma

        Returns:
            Verbalized list
        """
        if not items:
            return ""

        if len(items) == 1:
            return items[0]

        if len(items) == 2:
            return f"{items[0]} and {items[1]}"

        # Three or more items
        if use_oxford_comma:
            return ", ".join(items[:-1]) + ", and " + items[-1]
        else:
            return ", ".join(items[:-1]) + " and " + items[-1]

    def _fill_slots(self, text: str, bindings: dict[str, Any]) -> str:
        """Fill slots in template text.

        Args:
            text: Template text
            bindings: Slot bindings

        Returns:
            Text with slots filled
        """

        def replace_slot(match: re.Match) -> str:
            slot_name = match.group(1)
            if slot_name in bindings:
                value = bindings[slot_name]
                if isinstance(value, list):
                    return self._verbalize_list(value)
                return str(value)
            return match.group(0)

        return self.slot_pattern.sub(replace_slot, text)

    def select_template(self, frame: SemanticFrame, context: dict[str, Any] | None = None) -> str | None:
        """Select best template for semantic frame.

        Args:
            frame: Semantic frame
            context: Context information

        Returns:
            Name of selected template or None

        Raises:
            TemplateError: If selection fails
        """
        if not frame.predicate:
            return None

        best_template = None
        best_score = -1

        for name, template in self.templates.items():
            score = self._score_template(template, frame, context)
            if score > best_score:
                best_score = score
                best_template = name

        return best_template if best_score > 0 else None

    def _score_template(
        self,
        template: Template,
        frame: SemanticFrame,
        context: dict[str, Any] | None = None,
    ) -> float:
        """Score template suitability for frame.

        Args:
            template: Template
            frame: Semantic frame
            context: Context information

        Returns:
            Suitability score (0-1)
        """
        score = 0.0

        # Slot match
        frame_slots = set(s.name for s in frame.slots)
        template_slots = set(template.slots)

        if template_slots:
            overlap = len(frame_slots & template_slots)
            score += (overlap / len(template_slots)) * 0.5

        # Predicate match
        if template.name in frame.predicate.lower():
            score += 0.3

        # Context match
        if context:
            if template.conditions:
                matches = sum(1 for cond in template.conditions if cond in context and context[cond])
                score += (matches / len(template.conditions)) * 0.2

        return min(score, 1.0)

    def compose_templates(self, template_names: list[str], bindings_list: list[dict[str, Any]]) -> str:
        """Compose multiple templates.

        Args:
            template_names: Names of templates to compose
            bindings_list: Bindings for each template

        Returns:
            Composed text

        Raises:
            TemplateError: If composition fails
        """
        if len(template_names) != len(bindings_list):
            raise TemplateError("Mismatched template and bindings counts")

        realizations = []
        for name, bindings in zip(template_names, bindings_list):
            try:
                text = self.realize(name, bindings)
                realizations.append(text)
            except TemplateError:
                continue

        return " ".join(realizations)

    def get_template_variations(self, template_name: str) -> list[str]:
        """Get variations of a template.

        Args:
            template_name: Template name

        Returns:
            List of template variations

        Raises:
            TemplateError: If template not found
        """
        if template_name not in self.templates:
            raise TemplateError(f"Unknown template: {template_name}")

        template = self.templates[template_name]

        # Generate variations by permuting optional parts
        variations = [template.text]

        # Add any registered variations
        variations.extend(template.variations or [])

        return variations

    def set_template_variation(self, template_name: str, variations: list[str]) -> None:
        """Set template variations.

        Args:
            template_name: Template name
            variations: Alternative phrasings

        Raises:
            TemplateError: If template not found
        """
        if template_name not in self.templates:
            raise TemplateError(f"Unknown template: {template_name}")

        self.templates[template_name].variations = variations

    def inherit_template(self, name: str, parent_name: str, overrides: dict[str, str]) -> None:
        """Create template inheriting from parent.

        Args:
            name: New template name
            parent_name: Parent template name
            overrides: Slot overrides

        Raises:
            TemplateError: If parent not found
        """
        if parent_name not in self.templates:
            raise TemplateError(f"Parent template not found: {parent_name}")

        parent = self.templates[parent_name]

        # Create inherited template
        text = parent.text
        for slot, value in overrides.items():
            text = text.replace("{" + slot + "}", "{" + value + "}")

        self.register_template(name, text, parent.slots)

    def get_slots(self, template_name: str) -> list[str]:
        """Get slots for a template.

        Args:
            template_name: Template name

        Returns:
            List of slot names

        Raises:
            TemplateError: If template not found
        """
        if template_name not in self.templates:
            raise TemplateError(f"Unknown template: {template_name}")

        return self.templates[template_name].slots
