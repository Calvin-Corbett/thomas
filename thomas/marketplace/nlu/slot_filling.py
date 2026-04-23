"""
Slot filling module for dialogue systems.

Implements template-based slot extraction with typed slots, regex extractors,
context-dependent resolution, validation, multi-turn filling, confirmation,
correction, and normalization for common slot types.
"""

import re
from datetime import datetime
from typing import Any

from thomas.marketplace.nlu._exceptions import ClassificationError
from thomas.marketplace.nlu._types import Entity, Sentence, Slot


class SlotFiller:
    """
    Slot filling for dialogue systems with type checking and normalization.

    Extracts, validates, and normalizes slot values from sentences with
    support for multi-turn dialogue and confirmation flows.
    """

    def __init__(self) -> None:
        """Initialize slot filler."""
        self.slot_schemas: dict[str, dict[str, Any]] = {}
        self.extractors: dict[str, SlotExtractor] = {}
        self.conversation_state: dict[str, dict[str, Any]] = {}

        # Define built-in extractors
        self._register_builtin_extractors()

    def _register_builtin_extractors(self) -> None:
        """Register built-in slot extractors."""
        self.extractors["date"] = DateSlotExtractor()
        self.extractors["time"] = TimeSlotExtractor()
        self.extractors["number"] = NumberSlotExtractor()
        self.extractors["location"] = LocationSlotExtractor()
        self.extractors["person"] = PersonSlotExtractor()
        self.extractors["email"] = EmailSlotExtractor()
        self.extractors["phone"] = PhoneSlotExtractor()

    def define_slot_schema(
        self, slot_name: str, slot_type: str, required: bool = True, default: Any | None = None
    ) -> None:
        """
        Define a slot schema.

        Args:
            slot_name: Name of the slot
            slot_type: Type of the slot (date, time, number, etc.)
            required: Whether slot is required
            default: Default value if not extracted
        """
        self.slot_schemas[slot_name] = {"type": slot_type, "required": required, "default": default}

    def fill_slots(self, sentence: Sentence, entities: list[Entity] | None = None) -> list[Slot]:
        """
        Extract and fill slots from a sentence.

        Args:
            sentence: Sentence to extract slots from
            entities: Pre-extracted entities (optional)

        Returns:
            List of filled slots
        """
        slots = []

        for slot_name, schema in self.slot_schemas.items():
            slot_type = schema["type"]
            extractor = self.extractors.get(slot_type)

            if not extractor:
                continue

            # Extract value
            value = extractor.extract(sentence)

            if value is not None:
                # Validate
                if self._validate_slot(slot_name, value, schema):
                    # Normalize
                    normalized = self._normalize_slot(slot_name, value, schema)

                    slots.append(
                        Slot(
                            name=slot_name,
                            value=value,
                            value_type=slot_type,
                            span=getattr(extractor, "last_span", None),
                            confidence=getattr(extractor, "last_confidence", 0.9),
                            normalized_value=normalized,
                        )
                    )
            elif schema["default"] is not None:
                slots.append(
                    Slot(
                        name=slot_name,
                        value=schema["default"],
                        value_type=slot_type,
                        confidence=0.5,
                        normalized_value=schema["default"],
                    )
                )

        return slots

    def _validate_slot(self, slot_name: str, value: Any, schema: dict[str, Any]) -> bool:
        """
        Validate slot value against schema.

        Args:
            slot_name: Slot name
            value: Value to validate
            schema: Slot schema

        Returns:
            True if valid
        """
        # Type checking
        slot_type = schema["type"]

        if slot_type == "number":
            return isinstance(value, (int, float))
        elif slot_type in ("date", "time"):
            return isinstance(value, str) or isinstance(value, datetime)
        elif slot_type in ("email", "phone") or slot_type in ("location", "person"):
            return isinstance(value, str)

        return True

    def _normalize_slot(self, slot_name: str, value: Any, schema: dict[str, Any]) -> str:
        """
        Normalize slot value to canonical form.

        Args:
            slot_name: Slot name
            value: Raw value
            schema: Slot schema

        Returns:
            Normalized value as string
        """
        slot_type = schema["type"]

        if slot_type == "date" or slot_type == "time" or slot_type == "number":
            return str(value)
        elif slot_type == "email":
            return value.lower() if isinstance(value, str) else str(value)
        elif slot_type == "phone":
            # Remove non-digits
            return "".join(c for c in str(value) if c.isdigit())
        elif slot_type in ("location", "person"):
            return str(value).title() if isinstance(value, str) else str(value)

        return str(value)

    def confirm_slot(self, slot_name: str, value: Any) -> bool:
        """
        Ask for confirmation of a slot value (dialogue flow).

        Args:
            slot_name: Slot to confirm
            value: Value to confirm

        Returns:
            True if value confirmed (in real system, waits for user input)
        """
        # In production, would trigger confirmation dialogue
        return True

    def correct_slot(self, slot_name: str, old_value: Any, new_value: Any) -> Slot:
        """
        Handle slot correction in multi-turn dialogue.

        Args:
            slot_name: Slot being corrected
            old_value: Previous value
            new_value: New value

        Returns:
            Corrected slot
        """
        if slot_name not in self.slot_schemas:
            raise ClassificationError(f"Unknown slot: {slot_name}")

        schema = self.slot_schemas[slot_name]

        # Validate new value
        if not self._validate_slot(slot_name, new_value, schema):
            raise ClassificationError(f"Invalid value for slot {slot_name}")

        normalized = self._normalize_slot(slot_name, new_value, schema)

        return Slot(
            name=slot_name,
            value=new_value,
            value_type=schema["type"],
            confidence=0.95,
            normalized_value=normalized,
            is_confirmed=True,
        )

    def carry_slots(self, previous_slots: list[Slot], current_sentence: Sentence) -> list[Slot]:
        """
        Carry over slots from previous turn(s) if not overridden.

        Args:
            previous_slots: Slots from previous turns
            current_sentence: Current turn sentence

        Returns:
            Combined slot list
        """
        current_slots = self.fill_slots(current_sentence)
        current_slot_names = {s.name for s in current_slots}

        # Carry over slots not mentioned in current turn
        carried = [s for s in previous_slots if s.name not in current_slot_names]

        return current_slots + carried

    def get_unfilled_slots(self, filled_slots: list[Slot]) -> list[str]:
        """
        Get list of required slots that haven't been filled.

        Args:
            filled_slots: Currently filled slots

        Returns:
            List of unfilled required slot names
        """
        filled_names = {s.name for s in filled_slots}

        unfilled = [
            name for name, schema in self.slot_schemas.items() if schema["required"] and name not in filled_names
        ]

        return unfilled

    def extract(self, text: str, slots: dict[str, str] | None = None) -> dict[str, Any]:
        """
        Hybrid extraction from raw text with optional slot type hints.

        Implements extraction for:
        - Dates (ISO, natural language)
        - Numbers (integers, floats)
        - Emails
        - URLs
        - Phone numbers
        - Person names (capitalized words)
        - Locations (capitalized words after context clues)

        Args:
            text: Raw text to extract from
            slots: Optional dict mapping slot_name -> slot_type hints

        Returns:
            Dict mapping slot_name -> {value, confidence}
        """
        results: dict[str, Any] = {}

        if not slots:
            slots = {}

        # Define regex patterns for common types
        patterns = {
            "date": re.compile(
                r"\b(\d{4}-\d{2}-\d{2}|"  # ISO format
                r"\d{1,2}/\d{1,2}/\d{2,4}|"  # US format
                r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}|"  # Named dates
                r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)|"  # Day names
                r"(?:today|tomorrow|yesterday))\b",
                re.IGNORECASE,
            ),
            "number": re.compile(r"\b(\d+(?:\.\d+)?)\b"),
            "email": re.compile(r"\b([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,})\b"),
            "url": re.compile(r"(https?://[^\s]+|www\.[^\s]+)"),
            "phone": re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
        }

        # Extract by type
        for slot_name, slot_type in slots.items():
            pattern = patterns.get(slot_type)
            if pattern:
                match = pattern.search(text)
                if match:
                    results[slot_name] = {
                        "value": match.group(0) if match.lastindex is None else match.group(1),
                        "confidence": 0.95,
                    }
                    continue

            # Special handling for person names (capitalized words)
            if slot_type == "person":
                name_pattern = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b")
                matches = name_pattern.findall(text)
                if matches:
                    # Return first capitalized phrase
                    results[slot_name] = {"value": matches[0], "confidence": 0.80}
                    continue

            # Special handling for location (capitalized words after context clues)
            if slot_type == "location":
                # Look for capitalized words after prepositions like "in", "at", "near"
                loc_pattern = re.compile(r"(?:in|at|near|from|to)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)", re.IGNORECASE)
                match = loc_pattern.search(text)
                if match:
                    results[slot_name] = {"value": match.group(1), "confidence": 0.85}

        return results


class SlotExtractor:
    """Base class for slot extractors."""

    def __init__(self) -> None:
        """Initialize extractor."""
        self.last_span: Any | None = None
        self.last_confidence: float = 0.0

    def extract(self, sentence: Sentence) -> Any | None:
        """Extract slot value from sentence."""
        raise NotImplementedError


class DateSlotExtractor(SlotExtractor):
    """Extracts date slot values."""

    def __init__(self) -> None:
        """Initialize date extractor."""
        super().__init__()
        self.pattern = re.compile(
            r"\b(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}|"
            r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}|"
            r"(?:January|February|March|April|May|June|July|August|September|October|November|December) \d{1,2},? \d{4}|"
            r"(?:today|tomorrow|yesterday))\b",
            re.IGNORECASE,
        )

    def extract(self, sentence: Sentence) -> str | None:
        """Extract date from sentence."""
        match = self.pattern.search(sentence.text)
        if match:
            self.last_confidence = 0.95
            return match.group(0)
        return None


class TimeSlotExtractor(SlotExtractor):
    """Extracts time slot values."""

    def __init__(self) -> None:
        """Initialize time extractor."""
        super().__init__()
        self.pattern = re.compile(
            r"\b(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[AaPp][Mm])?|"
            r"\d{1,2}\s*[AaPp][Mm]|"
            r"(?:noon|midnight|morning|afternoon|evening))\b",
            re.IGNORECASE,
        )

    def extract(self, sentence: Sentence) -> str | None:
        """Extract time from sentence."""
        match = self.pattern.search(sentence.text)
        if match:
            self.last_confidence = 0.9
            return match.group(0)
        return None


class NumberSlotExtractor(SlotExtractor):
    """Extracts numeric slot values."""

    def __init__(self) -> None:
        """Initialize number extractor."""
        super().__init__()
        self.pattern = re.compile(r"\b\d+(?:\.\d+)?\b")

    def extract(self, sentence: Sentence) -> float | None:
        """Extract number from sentence."""
        match = self.pattern.search(sentence.text)
        if match:
            self.last_confidence = 0.95
            return float(match.group(0))
        return None


class LocationSlotExtractor(SlotExtractor):
    """Extracts location slot values."""

    def __init__(self) -> None:
        """Initialize location extractor."""
        super().__init__()
        self.locations = {
            "new york",
            "london",
            "paris",
            "tokyo",
            "beijing",
            "usa",
            "uk",
            "france",
            "germany",
            "spain",
            "italy",
            "canada",
            "australia",
            "california",
            "texas",
            "florida",
            "chicago",
            "los angeles",
        }

    def extract(self, sentence: Sentence) -> str | None:
        """Extract location from sentence."""
        text_lower = sentence.text.lower()
        for location in self.locations:
            if location in text_lower:
                self.last_confidence = 0.85
                return location.title()
        return None


class PersonSlotExtractor(SlotExtractor):
    """Extracts person/name slot values."""

    def __init__(self) -> None:
        """Initialize person extractor."""
        super().__init__()
        self.pattern = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b")

    def extract(self, sentence: Sentence) -> str | None:
        """Extract person name from sentence."""
        matches = self.pattern.findall(sentence.text)
        if matches:
            self.last_confidence = 0.8
            return matches[0]
        return None


class EmailSlotExtractor(SlotExtractor):
    """Extracts email slot values."""

    def __init__(self) -> None:
        """Initialize email extractor."""
        super().__init__()
        self.pattern = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")

    def extract(self, sentence: Sentence) -> str | None:
        """Extract email from sentence."""
        match = self.pattern.search(sentence.text)
        if match:
            self.last_confidence = 0.98
            return match.group(0)
        return None


class PhoneSlotExtractor(SlotExtractor):
    """Extracts phone number slot values."""

    def __init__(self) -> None:
        """Initialize phone extractor."""
        super().__init__()
        self.pattern = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")

    def extract(self, sentence: Sentence) -> str | None:
        """Extract phone number from sentence."""
        match = self.pattern.search(sentence.text)
        if match:
            self.last_confidence = 0.95
            return match.group(0)
        return None
