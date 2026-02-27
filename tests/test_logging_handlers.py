"""Tests for log handlers."""

import os
import tempfile
import unittest
from pathlib import Path

from thomas.logging_framework._types import LogLevel, RotationPolicy
from thomas.logging_framework.formatters import JSONFormatter
from thomas.logging_framework.handlers import (
    AsyncHandler,
    ConsoleHandler,
    FileHandler,
    MemoryHandler,
    MultiHandler,
    NullHandler,
    RotatingFileHandler,
    TimedRotatingFileHandler,
)
from thomas.logging_framework.logger import Logger


class TestConsoleHandler(unittest.TestCase):
    """Test cases for ConsoleHandler."""

    def test_console_handler_creation(self) -> None:
        """Test creating console handler."""
        handler = ConsoleHandler()
        self.assertEqual(handler.level, LogLevel.DEBUG)
        self.assertIsNotNone(handler.formatter)

    def test_console_handler_with_formatter(self) -> None:
        """Test console handler with custom formatter."""
        formatter = JSONFormatter()
        handler = ConsoleHandler(formatter=formatter)
        self.assertIs(handler.formatter, formatter)

    def test_console_handler_emit(self) -> None:
        """Test console handler emitting records."""
        handler = ConsoleHandler()
        logger = Logger("test")
        logger.add_handler(handler)

        # Should not raise
        logger.info("Test message")


class TestFileHandler(unittest.TestCase):
    """Test cases for FileHandler."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = os.path.join(self.temp_dir.name, "test.log")

    def tearDown(self) -> None:
        """Clean up."""
        self.temp_dir.cleanup()

    def test_file_handler_creation(self) -> None:
        """Test creating file handler."""
        handler = FileHandler(self.log_file)
        self.assertEqual(handler.filename, self.log_file)
        handler.close()

    def test_file_handler_write(self) -> None:
        """Test file handler writing records."""
        handler = FileHandler(self.log_file)
        logger = Logger("test")
        logger.add_handler(handler)

        logger.info("Test message")
        handler.close()

        # Check file was created
        self.assertTrue(os.path.exists(self.log_file))

        # Check content
        with open(self.log_file) as f:
            content = f.read()
            self.assertIn("Test message", content)

    def test_file_handler_rotation(self) -> None:
        """Test file rotation."""
        rotation = RotationPolicy(
            rotation_type="size",
            max_size=100,  # Small to trigger rotation
            max_count=3,
        )
        handler = FileHandler(self.log_file, rotation_policy=rotation)
        logger = Logger("test")
        logger.add_handler(handler)

        # Write enough to trigger rotation
        for i in range(10):
            logger.info(f"Message {i} with some extra text to make it longer")

        handler.close()

        # Check that backup files were created
        files = list(Path(self.temp_dir.name).glob(f"{os.path.basename(self.log_file)}.*"))
        self.assertGreater(len(files), 0)

    def test_file_handler_append_mode(self) -> None:
        """Test file handler appends to existing file."""
        handler1 = FileHandler(self.log_file)
        logger = Logger("test")
        logger.add_handler(handler1)

        logger.info("First message")
        handler1.close()

        # Create new handler and add more
        handler2 = FileHandler(self.log_file)
        logger.remove_handler(handler1)
        logger.add_handler(handler2)

        logger.info("Second message")
        handler2.close()

        # Check both messages are in file
        with open(self.log_file) as f:
            content = f.read()
            self.assertIn("First message", content)
            self.assertIn("Second message", content)


class TestMemoryHandler(unittest.TestCase):
    """Test cases for MemoryHandler."""

    def test_memory_handler_creation(self) -> None:
        """Test creating memory handler."""
        handler = MemoryHandler()
        self.assertEqual(handler.capacity, 1000)

    def test_memory_handler_store_records(self) -> None:
        """Test memory handler storing records."""
        handler = MemoryHandler()
        logger = Logger("test")
        logger.add_handler(handler)

        logger.info("Message 1")
        logger.info("Message 2")
        logger.info("Message 3")

        records = handler.get_records()
        self.assertEqual(len(records), 3)

    def test_memory_handler_capacity(self) -> None:
        """Test memory handler capacity limit."""
        handler = MemoryHandler(capacity=5)
        logger = Logger("test")
        logger.add_handler(handler)

        for i in range(10):
            logger.info(f"Message {i}")

        records = handler.get_records()
        self.assertEqual(len(records), 5)
        # Should keep last 5
        self.assertIn("Message 9", records[-1].message)

    def test_memory_handler_clear(self) -> None:
        """Test clearing memory handler."""
        handler = MemoryHandler()
        logger = Logger("test")
        logger.add_handler(handler)

        logger.info("Test message")
        self.assertEqual(len(handler.get_records()), 1)

        handler.clear()
        self.assertEqual(len(handler.get_records()), 0)


class TestNullHandler(unittest.TestCase):
    """Test cases for NullHandler."""

    def test_null_handler_discards_records(self) -> None:
        """Test null handler discards all records."""
        handler = NullHandler()
        logger = Logger("test")
        logger.add_handler(handler)

        logger.info("Message 1")
        logger.info("Message 2")

        # NullHandler doesn't store anything - just verify it doesn't error


class TestMultiHandler(unittest.TestCase):
    """Test cases for MultiHandler."""

    def test_multi_handler_fans_out(self) -> None:
        """Test multi handler fans out to multiple handlers."""
        handler1 = MemoryHandler()
        handler2 = MemoryHandler()

        multi = MultiHandler([handler1, handler2])
        logger = Logger("test")
        logger.add_handler(multi)

        logger.info("Test message")

        self.assertEqual(len(handler1.get_records()), 1)
        self.assertEqual(len(handler2.get_records()), 1)

    def test_multi_handler_add_remove(self) -> None:
        """Test adding and removing handlers from multi handler."""
        handler1 = MemoryHandler()
        handler2 = MemoryHandler()

        multi = MultiHandler()
        multi.add_handler(handler1)
        multi.add_handler(handler2)

        logger = Logger("test")
        logger.add_handler(multi)

        logger.info("Message 1")

        multi.remove_handler(handler2)
        logger.info("Message 2")

        # handler1 should have both
        self.assertEqual(len(handler1.get_records()), 2)
        # handler2 should have only first
        self.assertEqual(len(handler2.get_records()), 1)


class TestAsyncHandler(unittest.TestCase):
    """Test cases for AsyncHandler."""

    def test_async_handler_buffers(self) -> None:
        """Test async handler buffers records."""
        target = MemoryHandler()
        async_handler = AsyncHandler(target, buffer_size=3)
        logger = Logger("test")
        logger.add_handler(async_handler)

        logger.info("Message 1")
        logger.info("Message 2")

        # Give a moment for async processing
        import time

        time.sleep(0.5)

        async_handler.flush()
        records = target.get_records()

        self.assertEqual(len(records), 2)
        async_handler.close()

    def test_async_handler_auto_flush(self) -> None:
        """Test async handler auto-flushes when buffer full."""
        target = MemoryHandler()
        async_handler = AsyncHandler(target, buffer_size=2)
        logger = Logger("test")
        logger.add_handler(async_handler)

        logger.info("Message 1")
        logger.info("Message 2")
        logger.info("Message 3")  # Should trigger flush

        import time

        time.sleep(0.2)

        records = target.get_records()
        self.assertGreater(len(records), 0)
        async_handler.close()


class TestRotatingFileHandler(unittest.TestCase):
    """Test cases for RotatingFileHandler."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = os.path.join(self.temp_dir.name, "test.log")

    def tearDown(self) -> None:
        """Clean up."""
        self.temp_dir.cleanup()

    def test_rotating_file_handler_creation(self) -> None:
        """Test creating rotating file handler."""
        handler = RotatingFileHandler(self.log_file, max_bytes=1000, backup_count=3)
        self.assertIsNotNone(handler.rotation_policy)
        self.assertEqual(handler.rotation_policy.max_size, 1000)
        handler.close()

    def test_rotating_file_handler_rotation(self) -> None:
        """Test rotation policy."""
        handler = RotatingFileHandler(self.log_file, max_bytes=200, backup_count=2)
        logger = Logger("test")
        logger.add_handler(handler)

        # Write enough to trigger rotation
        for i in range(20):
            logger.info(f"Message {i} with extra text to make lines longer")

        handler.close()

        # Check backups were created
        files = list(Path(self.temp_dir.name).glob("test.log*"))
        self.assertGreater(len(files), 1)


class TestTimedRotatingFileHandler(unittest.TestCase):
    """Test cases for TimedRotatingFileHandler."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_file = os.path.join(self.temp_dir.name, "test.log")

    def tearDown(self) -> None:
        """Clean up."""
        self.temp_dir.cleanup()

    def test_timed_rotating_file_handler_creation(self) -> None:
        """Test creating timed rotating file handler."""
        handler = TimedRotatingFileHandler(self.log_file, when="midnight", backup_count=5)
        self.assertIsNotNone(handler.rotation_policy)
        self.assertEqual(handler.rotation_policy.time_interval, "daily")
        handler.close()


class TestHandlerFiltering(unittest.TestCase):
    """Test handler-level filtering."""

    def test_handler_level_filter(self) -> None:
        """Test handler filters by level."""
        from thomas.logging_framework.filters import LevelFilter

        handler = MemoryHandler()
        handler.add_filter(LevelFilter(min_level=LogLevel.WARNING))

        logger = Logger("test", level=LogLevel.DEBUG)
        logger.add_handler(handler)

        logger.info("Info")
        logger.warning("Warning")
        logger.error("Error")

        records = handler.get_records()
        self.assertEqual(len(records), 2)


if __name__ == "__main__":
    unittest.main()
