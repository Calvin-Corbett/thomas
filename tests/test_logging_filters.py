"""Tests for log filters."""

import unittest

from thomas.marketplace.logging_framework._types import LogLevel
from thomas.marketplace.logging_framework.filters import (
    CompositeFilter,
    ContextFilter,
    DeduplicationFilter,
    DynamicFilter,
    ExceptionFilter,
    LevelFilter,
    LoggerNameFilter,
    RateLimitFilter,
    RegexFilter,
    SamplingFilter,
)
from thomas.marketplace.logging_framework.handlers import MemoryHandler
from thomas.marketplace.logging_framework.logger import Logger, get_logger


class TestLevelFilter(unittest.TestCase):
    """Test cases for LevelFilter."""

    def test_level_filter_min(self) -> None:
        """Test level filter minimum level."""
        filter = LevelFilter(min_level=LogLevel.WARNING)

        logger = Logger("test")
        handler = MemoryHandler()
        handler.add_filter(filter)
        logger.add_handler(handler)

        logger.info("Info")
        logger.warning("Warning")
        logger.error("Error")

        records = handler.get_records()
        self.assertEqual(len(records), 2)
        self.assertNotIn("Info", [r.message for r in records])

    def test_level_filter_max(self) -> None:
        """Test level filter maximum level."""
        filter = LevelFilter(max_level=LogLevel.WARNING)

        logger = Logger("test", level=LogLevel.DEBUG)
        handler = MemoryHandler()
        handler.add_filter(filter)
        logger.add_handler(handler)

        logger.warning("Warning")
        logger.error("Error")
        logger.critical("Critical")

        records = handler.get_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].message, "Warning")


class TestRegexFilter(unittest.TestCase):
    """Test cases for RegexFilter."""

    def test_regex_filter_message(self) -> None:
        """Test regex filter on message field."""
        filter = RegexFilter(r"error", field="message")

        logger = Logger("test")
        handler = MemoryHandler()
        handler.add_filter(filter)
        logger.add_handler(handler)

        logger.info("All is well")
        logger.error("An error occurred")
        logger.info("Another error event")

        records = handler.get_records()
        self.assertEqual(len(records), 2)

    def test_regex_filter_invert(self) -> None:
        """Test regex filter with inversion."""
        filter = RegexFilter(r"error", field="message", invert=True)

        logger = Logger("test")
        handler = MemoryHandler()
        handler.add_filter(filter)
        logger.add_handler(handler)

        logger.info("All is well")
        logger.error("An error occurred")
        logger.info("Normal message")

        records = handler.get_records()
        self.assertEqual(len(records), 2)
        self.assertNotIn("error", [r.message.lower() for r in records])

    def test_regex_filter_field(self) -> None:
        """Test regex filter on structured field."""
        filter = RegexFilter(r"^user_\d+$", field="user_id")

        logger = Logger("test")
        handler = MemoryHandler()
        handler.add_filter(filter)
        logger.add_handler(handler)

        logger.info("Test", extra_fields={"user_id": "user_123"})
        logger.info("Test", extra_fields={"user_id": "admin"})
        logger.info("Test", extra_fields={"user_id": "user_456"})

        records = handler.get_records()
        self.assertEqual(len(records), 2)


class TestRateLimitFilter(unittest.TestCase):
    """Test cases for RateLimitFilter."""

    def test_rate_limit_filter(self) -> None:
        """Test rate limit filter."""
        filter = RateLimitFilter(rate_per_second=2.0)

        logger = Logger("test")
        handler = MemoryHandler()
        handler.add_filter(filter)
        logger.add_handler(handler)

        # Log 5 messages rapidly
        for i in range(5):
            logger.info(f"Message {i}")

        # Should only allow 2
        records = handler.get_records()
        self.assertLessEqual(len(records), 2)

    def test_rate_limit_per_key(self) -> None:
        """Test rate limiting per field value."""
        filter = RateLimitFilter(rate_per_second=1.0, key_field="user_id")

        logger = Logger("test")
        handler = MemoryHandler()
        handler.add_filter(filter)
        logger.add_handler(handler)

        # Log from two different users
        logger.info("Test", extra_fields={"user_id": "user1"})
        logger.info("Test", extra_fields={"user_id": "user1"})
        logger.info("Test", extra_fields={"user_id": "user2"})
        logger.info("Test", extra_fields={"user_id": "user2"})

        records = handler.get_records()
        # Should allow some from each user
        self.assertGreater(len(records), 0)


class TestSamplingFilter(unittest.TestCase):
    """Test cases for SamplingFilter."""

    def test_sampling_filter_50_percent(self) -> None:
        """Test 50% sampling."""
        filter = SamplingFilter(sample_rate=0.5)

        logger = Logger("test")
        handler = MemoryHandler()
        handler.add_filter(filter)
        logger.add_handler(handler)

        # Log many messages
        for i in range(100):
            logger.info(f"Message {i}")

        records = handler.get_records()
        # With 50% sampling, expect roughly 50 (allow some variance)
        self.assertGreater(len(records), 30)
        self.assertLess(len(records), 70)

    def test_sampling_100_percent(self) -> None:
        """Test 100% sampling (all pass through)."""
        filter = SamplingFilter(sample_rate=1.0)

        logger = Logger("test")
        handler = MemoryHandler()
        handler.add_filter(filter)
        logger.add_handler(handler)

        for i in range(10):
            logger.info(f"Message {i}")

        records = handler.get_records()
        self.assertEqual(len(records), 10)


class TestDeduplicationFilter(unittest.TestCase):
    """Test cases for DeduplicationFilter."""

    def test_deduplication_no_duplicates(self) -> None:
        """Test deduplication filter suppresses duplicates."""
        filter = DeduplicationFilter(time_window=1.0, max_duplicates=0)

        logger = Logger("test")
        handler = MemoryHandler()
        handler.add_filter(filter)
        logger.add_handler(handler)

        logger.info("Duplicate message")
        logger.info("Duplicate message")
        logger.info("Duplicate message")
        logger.info("Different message")

        records = handler.get_records()
        self.assertEqual(len(records), 2)

    def test_deduplication_allow_some(self) -> None:
        """Test allowing some duplicates."""
        filter = DeduplicationFilter(time_window=1.0, max_duplicates=1)

        logger = Logger("test")
        handler = MemoryHandler()
        handler.add_filter(filter)
        logger.add_handler(handler)

        logger.info("Message")
        logger.info("Message")
        logger.info("Message")

        records = handler.get_records()
        self.assertEqual(len(records), 2)


class TestContextFilter(unittest.TestCase):
    """Test cases for ContextFilter."""

    def test_context_filter_match_all(self) -> None:
        """Test context filter with AND logic."""
        filter = ContextFilter({"level": "error", "service": "api"}, match_all=True)

        logger = Logger("test")
        handler = MemoryHandler()
        handler.add_filter(filter)
        logger.add_handler(handler)

        logger.info("Test", extra_fields={"service": "api", "level": "error"})
        logger.info("Test", extra_fields={"service": "db", "level": "error"})

        records = handler.get_records()
        self.assertEqual(len(records), 1)

    def test_context_filter_match_any(self) -> None:
        """Test context filter with OR logic."""
        filter = ContextFilter({"env": "prod", "service": "critical"}, match_all=False)

        logger = Logger("test")
        handler = MemoryHandler()
        handler.add_filter(filter)
        logger.add_handler(handler)

        logger.info("Test", extra_fields={"env": "prod"})
        logger.info("Test", extra_fields={"env": "dev"})
        logger.info("Test", extra_fields={"service": "critical"})

        records = handler.get_records()
        self.assertEqual(len(records), 2)


class TestCompositeFilter(unittest.TestCase):
    """Test cases for CompositeFilter."""

    def test_composite_filter_and(self) -> None:
        """Test composite filter with AND logic."""
        composite = CompositeFilter(operator="AND")
        composite.add_filter(LevelFilter(min_level=LogLevel.WARNING))
        composite.add_filter(RegexFilter(r"error"))

        logger = Logger("test")
        handler = MemoryHandler()
        handler.add_filter(composite)
        logger.add_handler(handler)

        logger.warning("Normal warning")
        logger.error("An error")
        logger.error("Normal")

        records = handler.get_records()
        self.assertEqual(len(records), 1)
        self.assertIn("error", records[0].message.lower())

    def test_composite_filter_or(self) -> None:
        """Test composite filter with OR logic."""
        composite = CompositeFilter(operator="OR")
        composite.add_filter(LevelFilter(min_level=LogLevel.ERROR))
        composite.add_filter(RegexFilter(r"critical"))

        logger = Logger("test")
        handler = MemoryHandler()
        handler.add_filter(composite)
        logger.add_handler(handler)

        logger.error("Error")
        logger.warning("This is critical")
        logger.warning("Normal")

        records = handler.get_records()
        self.assertEqual(len(records), 2)


class TestDynamicFilter(unittest.TestCase):
    """Test cases for DynamicFilter."""

    def test_dynamic_filter_rules(self) -> None:
        """Test dynamic filter with rules."""
        dynamic = DynamicFilter()
        dynamic.add_rule("high_level", lambda r: r.level >= LogLevel.ERROR)

        logger = Logger("test")
        handler = MemoryHandler()
        handler.add_filter(dynamic)
        logger.add_handler(handler)

        logger.warning("Warning")
        logger.error("Error")
        logger.critical("Critical")

        records = handler.get_records()
        self.assertEqual(len(records), 2)

    def test_dynamic_filter_update_rule(self) -> None:
        """Test updating rules at runtime."""
        dynamic = DynamicFilter()
        dynamic.add_rule("level_check", lambda r: r.level >= LogLevel.ERROR)

        logger = Logger("test")
        handler = MemoryHandler()
        handler.add_filter(dynamic)
        logger.add_handler(handler)

        logger.warning("Warning 1")
        logger.error("Error 1")

        # Update rule to be more permissive
        dynamic.update_rule("level_check", lambda r: r.level >= LogLevel.WARNING)

        logger.warning("Warning 2")
        logger.error("Error 2")

        records = handler.get_records()
        self.assertEqual(len(records), 3)


class TestLoggerNameFilter(unittest.TestCase):
    """Test cases for LoggerNameFilter."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        Logger._loggers.clear()

    def test_logger_name_exact_match(self) -> None:
        """Test exact logger name matching."""
        filter = LoggerNameFilter("app.service")

        app_logger = get_logger("app")
        service_logger = get_logger("app.service")
        db_logger = get_logger("app.database")

        handler = MemoryHandler()
        handler.add_filter(filter)

        service_logger.add_handler(handler)
        db_logger.add_handler(handler)

        service_logger.info("Service message")
        db_logger.info("Database message")

        records = handler.get_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].logger_name, "app.service")

    def test_logger_name_wildcard(self) -> None:
        """Test logger name with wildcard."""
        filter = LoggerNameFilter("app.*")

        app_logger = get_logger("app")
        service_logger = get_logger("app.service")
        db_logger = get_logger("app.database")
        other_logger = get_logger("other")

        handler = MemoryHandler()
        handler.add_filter(filter)

        service_logger.add_handler(handler)
        db_logger.add_handler(handler)
        other_logger.add_handler(handler)

        service_logger.info("Service")
        db_logger.info("Database")
        other_logger.info("Other")

        records = handler.get_records()
        self.assertEqual(len(records), 2)


class TestExceptionFilter(unittest.TestCase):
    """Test cases for ExceptionFilter."""

    def test_exception_filter_any(self) -> None:
        """Test filter for any exception."""
        filter = ExceptionFilter()

        logger = Logger("test")
        handler = MemoryHandler()
        handler.add_filter(filter)
        logger.add_handler(handler)

        logger.info("Normal")

        try:
            raise ValueError("Test error")
        except ValueError:
            logger.exception("Error occurred")

        records = handler.get_records()
        self.assertEqual(len(records), 1)
        self.assertIsNotNone(records[0].exc_info)

    def test_exception_filter_by_type(self) -> None:
        """Test filter for specific exception types."""
        filter = ExceptionFilter(exception_types=[ValueError, TypeError])

        logger = Logger("test")
        handler = MemoryHandler()
        handler.add_filter(filter)
        logger.add_handler(handler)

        try:
            raise ValueError("Value error")
        except ValueError:
            logger.exception("Value error")

        try:
            raise RuntimeError("Runtime error")
        except RuntimeError:
            logger.exception("Runtime error")

        records = handler.get_records()
        self.assertEqual(len(records), 1)


if __name__ == "__main__":
    unittest.main()
