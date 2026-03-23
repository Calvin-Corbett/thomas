"""Tests for the core logger implementation."""

import threading
import unittest

from thomas.marketplace.logging_framework._types import CorrelationId, LogLevel, TraceContext
from thomas.marketplace.logging_framework.filters import LevelFilter
from thomas.marketplace.logging_framework.handlers import MemoryHandler
from thomas.marketplace.logging_framework.logger import Logger, get_logger, root_logger


class TestLogger(unittest.TestCase):
    """Test cases for Logger class."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        # Clear the logger registry
        Logger._loggers.clear()

    def test_logger_creation(self) -> None:
        """Test logger creation."""
        logger = Logger("test")
        self.assertEqual(logger.name, "test")
        self.assertEqual(logger.get_effective_level(), LogLevel.INFO)

    def test_logger_hierarchy(self) -> None:
        """Test hierarchical logger relationships."""
        parent = get_logger("app")
        child = get_logger("app.service")
        grandchild = get_logger("app.service.database")

        self.assertEqual(parent.name, "app")
        self.assertEqual(child.name, "app.service")
        self.assertEqual(grandchild.name, "app.service.database")

    def test_level_propagation(self) -> None:
        """Test log level propagation from parent to child."""
        parent = get_logger("app")
        parent.set_level(LogLevel.WARNING)

        child = get_logger("app.module")
        self.assertEqual(child.get_effective_level(), LogLevel.WARNING)

    def test_set_log_level(self) -> None:
        """Test setting log level."""
        logger = Logger("test")
        logger.set_level(LogLevel.ERROR)
        self.assertEqual(logger.get_effective_level(), LogLevel.ERROR)

    def test_add_remove_handler(self) -> None:
        """Test adding and removing handlers."""
        logger = Logger("test")
        handler = MemoryHandler()

        logger.add_handler(handler)
        self.assertIn(handler, logger.context.handlers)

        logger.remove_handler(handler)
        self.assertNotIn(handler, logger.context.handlers)

    def test_structured_fields(self) -> None:
        """Test adding structured fields to logger context."""
        logger = Logger("test")
        logger.add_structured_field("user_id", "123")
        logger.add_structured_field("request_id", "abc-def")

        fields = logger.context.get_fields()
        self.assertEqual(fields["user_id"]["value"], "123")
        self.assertEqual(fields["request_id"]["value"], "abc-def")

    def test_trace_context(self) -> None:
        """Test setting trace context."""
        logger = Logger("test")
        trace = TraceContext.create()
        logger.set_trace_context(trace)

        self.assertEqual(logger.context.trace_context, trace)

    def test_correlation_id(self) -> None:
        """Test setting correlation ID."""
        logger = Logger("test")
        corr = CorrelationId.create()
        logger.set_correlation_id(corr)

        self.assertEqual(logger.context.correlation_id, corr)

    def test_debug_logging(self) -> None:
        """Test debug level logging."""
        logger = Logger("test", level=LogLevel.DEBUG)
        handler = MemoryHandler(level=LogLevel.DEBUG)
        logger.add_handler(handler)

        logger.debug("Debug message")
        records = handler.get_records()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].level, LogLevel.DEBUG)
        self.assertEqual(records[0].message, "Debug message")

    def test_info_logging(self) -> None:
        """Test info level logging."""
        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Info message")
        records = handler.get_records()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].level, LogLevel.INFO)

    def test_warning_logging(self) -> None:
        """Test warning level logging."""
        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.warning("Warning message")
        records = handler.get_records()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].level, LogLevel.WARNING)

    def test_error_logging(self) -> None:
        """Test error level logging."""
        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.error("Error message")
        records = handler.get_records()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].level, LogLevel.ERROR)

    def test_critical_logging(self) -> None:
        """Test critical level logging."""
        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.critical("Critical message")
        records = handler.get_records()

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].level, LogLevel.CRITICAL)

    def test_exception_logging(self) -> None:
        """Test exception logging."""
        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        try:
            raise ValueError("Test error")
        except ValueError:
            logger.exception("An error occurred")

        records = handler.get_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].level, LogLevel.ERROR)
        self.assertIsNotNone(records[0].exc_info)

    def test_message_formatting(self) -> None:
        """Test lazy message formatting."""
        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("User %s logged in", "john")
        records = handler.get_records()

        self.assertEqual(records[0].message, "User john logged in")

    def test_propagation(self) -> None:
        """Test log propagation to parent."""
        parent = get_logger("app")
        parent_handler = MemoryHandler()
        parent.add_handler(parent_handler)

        child = get_logger("app.child")
        child_handler = MemoryHandler()
        child.add_handler(child_handler)

        child.info("Child message")

        # Message should be in both child and parent handlers
        child_records = child_handler.get_records()
        parent_records = parent_handler.get_records()

        self.assertEqual(len(child_records), 1)
        self.assertEqual(len(parent_records), 1)

    def test_propagation_disabled(self) -> None:
        """Test disabling log propagation."""
        parent = get_logger("app")
        parent_handler = MemoryHandler()
        parent.add_handler(parent_handler)

        child = get_logger("app.child")
        child.set_propagate(False)
        child_handler = MemoryHandler()
        child.add_handler(child_handler)

        child.info("Child message")

        child_records = child_handler.get_records()
        parent_records = parent_handler.get_records()

        self.assertEqual(len(child_records), 1)
        self.assertEqual(len(parent_records), 0)

    def test_logger_registry(self) -> None:
        """Test that loggers are cached in registry."""
        logger1 = get_logger("myapp")
        logger2 = get_logger("myapp")

        self.assertIs(logger1, logger2)

    def test_root_logger(self) -> None:
        """Test root logger access."""
        root = root_logger()
        self.assertEqual(root.name, "root")

    def test_caller_info_capture(self) -> None:
        """Test capturing caller information."""
        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Test message")
        records = handler.get_records()

        self.assertIsNotNone(records[0].caller_frame)
        self.assertIsNotNone(records[0].caller_line)
        self.assertIsNotNone(records[0].caller_function)

    def test_thread_info_capture(self) -> None:
        """Test capturing thread information."""
        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Test message")
        records = handler.get_records()

        self.assertEqual(records[0].thread_id, threading.get_ident())
        self.assertEqual(records[0].thread_name, threading.current_thread().getName())

    def test_level_filtering(self) -> None:
        """Test that log level filtering works."""
        logger = Logger("test", level=LogLevel.WARNING)
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")

        records = handler.get_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].message, "Warning message")

    def test_handler_filter(self) -> None:
        """Test filtering on handler."""
        logger = Logger("test", level=LogLevel.DEBUG)
        handler = MemoryHandler()
        handler.add_filter(LevelFilter(min_level=LogLevel.WARNING))
        logger.add_handler(handler)

        logger.info("Info message")
        logger.warning("Warning message")

        records = handler.get_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].message, "Warning message")

    def test_multiple_handlers(self) -> None:
        """Test logging to multiple handlers."""
        logger = Logger("test")
        handler1 = MemoryHandler()
        handler2 = MemoryHandler()

        logger.add_handler(handler1)
        logger.add_handler(handler2)

        logger.info("Test message")

        self.assertEqual(len(handler1.get_records()), 1)
        self.assertEqual(len(handler2.get_records()), 1)

    def test_structured_field_inheritance(self) -> None:
        """Test that child loggers inherit parent structured fields."""
        parent = get_logger("app")
        parent.add_structured_field("app_version", "1.0")

        child = get_logger("app.service")
        child_handler = MemoryHandler()
        child.add_handler(child_handler)

        child.info("Test")
        records = child_handler.get_records()

        self.assertIn("app_version", records[0].fields)
        self.assertEqual(records[0].fields["app_version"].value, "1.0")

    def test_thread_safety(self) -> None:
        """Test thread-safe logging."""
        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        def log_messages(count: int) -> None:
            for i in range(count):
                logger.info(f"Message {i}")

        threads = [threading.Thread(target=log_messages, args=(10,)) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        records = handler.get_records()
        self.assertEqual(len(records), 50)


class TestLoggerNaming(unittest.TestCase):
    """Test logger naming and hierarchy."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        Logger._loggers.clear()

    def test_dot_separated_names(self) -> None:
        """Test dot-separated logger names."""
        logger = get_logger("myapp.component.subcomponent")
        self.assertEqual(logger.name, "myapp.component.subcomponent")

    def test_hierarchy_creation(self) -> None:
        """Test automatic hierarchy creation."""
        logger = get_logger("app.db.connection")
        # Should automatically create app and app.db loggers
        self.assertIn("app", Logger._loggers)
        self.assertIn("app.db", Logger._loggers)
        self.assertIn("app.db.connection", Logger._loggers)


if __name__ == "__main__":
    unittest.main()
