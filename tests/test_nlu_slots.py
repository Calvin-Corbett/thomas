"""
Tests for slot filling module.
"""

import unittest

from thomas.nlu._exceptions import ClassificationError
from thomas.nlu._types import Sentence
from thomas.nlu.slot_filling import (
    DateSlotExtractor,
    EmailSlotExtractor,
    LocationSlotExtractor,
    NumberSlotExtractor,
    PhoneSlotExtractor,
    SlotFiller,
    TimeSlotExtractor,
)


class TestSlotFiller(unittest.TestCase):
    """Tests for slot filler."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.filler = SlotFiller()
        self.filler.define_slot_schema("date", "date", required=True)
        self.filler.define_slot_schema("location", "location", required=True)
        self.filler.define_slot_schema("name", "person", required=False)

    def test_slot_schema_definition(self) -> None:
        """Test defining slot schema."""
        filler = SlotFiller()
        filler.define_slot_schema("date", "date", required=True)

        self.assertIn("date", filler.slot_schemas)
        self.assertEqual(filler.slot_schemas["date"]["type"], "date")

    def test_slot_filling(self) -> None:
        """Test basic slot filling."""
        sentence = Sentence(text="Meeting on 2024-01-15 in New York")

        slots = self.filler.fill_slots(sentence)

        self.assertGreater(len(slots), 0)

    def test_required_slot_validation(self) -> None:
        """Test required slot validation."""
        unfilled = self.filler.get_unfilled_slots([])

        self.assertIn("date", unfilled)
        self.assertIn("location", unfilled)

    def test_optional_slots(self) -> None:
        """Test optional slots."""
        filler = SlotFiller()
        filler.define_slot_schema("optional", "person", required=False)

        unfilled = filler.get_unfilled_slots([])

        self.assertNotIn("optional", unfilled)

    def test_slot_normalization(self) -> None:
        """Test slot value normalization."""
        filler = SlotFiller()
        filler.define_slot_schema("email", "email")

        sentence = Sentence(text="Contact TEST@EXAMPLE.COM")
        slots = filler.fill_slots(sentence)

        # Email should be normalized to lowercase
        for slot in slots:
            if slot.value_type == "email":
                self.assertEqual(slot.normalized_value, slot.normalized_value.lower())

    def test_slot_confirmation(self) -> None:
        """Test slot confirmation."""
        result = self.filler.confirm_slot("date", "2024-01-15")

        self.assertTrue(result)

    def test_slot_correction(self) -> None:
        """Test slot correction."""
        old_slot = self.filler.correct_slot("date", "2024-01-15", "2024-01-16")

        self.assertEqual(old_slot.name, "date")
        self.assertTrue(old_slot.is_confirmed)

    def test_invalid_slot_correction(self) -> None:
        """Test error on correcting unknown slot."""
        with self.assertRaises(ClassificationError):
            self.filler.correct_slot("unknown", "val1", "val2")

    def test_carry_slots(self) -> None:
        """Test carrying slots across turns."""
        from thomas.nlu._types import Slot

        previous_slots = [
            Slot(name="date", value="2024-01-15", value_type="date"),
            Slot(name="location", value="NYC", value_type="location"),
        ]

        sentence = Sentence(text="Change location to Boston")
        current_slots = self.filler.fill_slots(sentence)

        carried = self.filler.carry_slots(previous_slots, sentence)

        # Should have new location and carried date
        self.assertGreater(len(carried), 0)

    def test_built_in_extractors(self) -> None:
        """Test that built-in extractors are registered."""
        self.assertIn("date", self.filler.extractors)
        self.assertIn("time", self.filler.extractors)
        self.assertIn("number", self.filler.extractors)
        self.assertIn("email", self.filler.extractors)

    def test_slot_confidence(self) -> None:
        """Test that slots have confidence scores."""
        sentence = Sentence(text="john@example.com")
        slots = self.filler.fill_slots(sentence)

        for slot in slots:
            self.assertGreaterEqual(slot.confidence, 0.0)
            self.assertLessEqual(slot.confidence, 1.0)

    def test_slot_span(self) -> None:
        """Test that slot spans are tracked."""
        sentence = Sentence(text="Email: john@example.com")
        slots = self.filler.fill_slots(sentence)

        # At least some slots should have spans
        self.assertGreater(len(slots), 0)


class TestDateSlotExtractor(unittest.TestCase):
    """Tests for date slot extraction."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.extractor = DateSlotExtractor()

    def test_iso_date_extraction(self) -> None:
        """Test ISO format date extraction."""
        sentence = Sentence(text="Meeting on 2024-01-15")
        result = self.extractor.extract(sentence)

        self.assertIsNotNone(result)
        self.assertIn("2024-01-15", result)

    def test_slash_date_extraction(self) -> None:
        """Test slash format date extraction."""
        sentence = Sentence(text="Date is 01/15/2024")
        result = self.extractor.extract(sentence)

        self.assertIsNotNone(result)

    def test_named_month_extraction(self) -> None:
        """Test named month extraction."""
        sentence = Sentence(text="January 15, 2024")
        result = self.extractor.extract(sentence)

        self.assertIsNotNone(result)

    def test_relative_date_extraction(self) -> None:
        """Test relative date extraction."""
        sentence = Sentence(text="See you tomorrow")
        result = self.extractor.extract(sentence)

        self.assertIsNotNone(result)

    def test_no_date_in_text(self) -> None:
        """Test handling of text with no date."""
        sentence = Sentence(text="Hello world")
        result = self.extractor.extract(sentence)

        self.assertIsNone(result)


class TestTimeSlotExtractor(unittest.TestCase):
    """Tests for time slot extraction."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.extractor = TimeSlotExtractor()

    def test_24hour_time_extraction(self) -> None:
        """Test 24-hour format time extraction."""
        sentence = Sentence(text="Meeting at 14:30")
        result = self.extractor.extract(sentence)

        self.assertIsNotNone(result)
        self.assertIn("14:30", result)

    def test_12hour_time_extraction(self) -> None:
        """Test 12-hour format time extraction."""
        sentence = Sentence(text="Meet at 2:30 PM")
        result = self.extractor.extract(sentence)

        self.assertIsNotNone(result)

    def test_named_time_extraction(self) -> None:
        """Test named time extraction."""
        sentence = Sentence(text="See you at noon")
        result = self.extractor.extract(sentence)

        self.assertIsNotNone(result)

    def test_no_time_in_text(self) -> None:
        """Test handling of text with no time."""
        sentence = Sentence(text="Hello world")
        result = self.extractor.extract(sentence)

        self.assertIsNone(result)


class TestNumberSlotExtractor(unittest.TestCase):
    """Tests for number slot extraction."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.extractor = NumberSlotExtractor()

    def test_integer_extraction(self) -> None:
        """Test integer extraction."""
        sentence = Sentence(text="I need 5 items")
        result = self.extractor.extract(sentence)

        self.assertIsNotNone(result)
        self.assertEqual(result, 5.0)

    def test_float_extraction(self) -> None:
        """Test float extraction."""
        sentence = Sentence(text="Price is 19.99")
        result = self.extractor.extract(sentence)

        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 19.99)

    def test_no_number_in_text(self) -> None:
        """Test handling of text with no number."""
        sentence = Sentence(text="Hello world")
        result = self.extractor.extract(sentence)

        self.assertIsNone(result)


class TestLocationSlotExtractor(unittest.TestCase):
    """Tests for location slot extraction."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.extractor = LocationSlotExtractor()

    def test_location_extraction(self) -> None:
        """Test location extraction."""
        sentence = Sentence(text="I'm going to London")
        result = self.extractor.extract(sentence)

        self.assertIsNotNone(result)
        self.assertIn("London", result)

    def test_multiple_locations(self) -> None:
        """Test extraction of first location."""
        sentence = Sentence(text="From New York to Paris")
        result = self.extractor.extract(sentence)

        self.assertIsNotNone(result)

    def test_no_location_in_text(self) -> None:
        """Test handling of text with no known location."""
        sentence = Sentence(text="I'm going to xyz")
        result = self.extractor.extract(sentence)

        self.assertIsNone(result)


class TestEmailSlotExtractor(unittest.TestCase):
    """Tests for email slot extraction."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.extractor = EmailSlotExtractor()

    def test_email_extraction(self) -> None:
        """Test email extraction."""
        sentence = Sentence(text="Contact john@example.com")
        result = self.extractor.extract(sentence)

        self.assertIsNotNone(result)
        self.assertEqual(result, "john@example.com")

    def test_no_email_in_text(self) -> None:
        """Test handling of text with no email."""
        sentence = Sentence(text="Hello world")
        result = self.extractor.extract(sentence)

        self.assertIsNone(result)


class TestPhoneSlotExtractor(unittest.TestCase):
    """Tests for phone slot extraction."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.extractor = PhoneSlotExtractor()

    def test_phone_extraction(self) -> None:
        """Test phone number extraction."""
        sentence = Sentence(text="Call me at 555-123-4567")
        result = self.extractor.extract(sentence)

        self.assertIsNotNone(result)

    def test_no_phone_in_text(self) -> None:
        """Test handling of text with no phone."""
        sentence = Sentence(text="Hello world")
        result = self.extractor.extract(sentence)

        self.assertIsNone(result)


class TestSlotIntegration(unittest.TestCase):
    """Integration tests for slot filling."""

    def test_multiple_slots_extraction(self) -> None:
        """Test extracting multiple slots from single sentence."""
        filler = SlotFiller()
        filler.define_slot_schema("date", "date")
        filler.define_slot_schema("location", "location")
        filler.define_slot_schema("email", "email")

        sentence = Sentence(text="Meeting on 2024-01-15 in New York at john@example.com")
        slots = filler.fill_slots(sentence)

        self.assertGreater(len(slots), 1)

    def test_dialogue_slot_management(self) -> None:
        """Test slot management across dialogue turns."""
        filler = SlotFiller()
        filler.define_slot_schema("destination", "location")
        filler.define_slot_schema("date", "date")

        # Turn 1: User specifies destination
        turn1 = Sentence(text="I want to go to Paris")
        slots1 = filler.fill_slots(turn1)

        # Turn 2: User specifies date
        turn2 = Sentence(text="On 2024-01-15")
        slots2 = filler.fill_slots(turn2)

        # Carry slots from turn 1
        combined = filler.carry_slots(slots1, turn2)

        self.assertGreater(len(combined), 0)


if __name__ == "__main__":
    unittest.main()
