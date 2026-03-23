"""Tests for log search functionality."""

import unittest

from thomas.marketplace.logging_framework._types import LogLevel, LogQuery
from thomas.marketplace.logging_framework.handlers import MemoryHandler
from thomas.marketplace.logging_framework.logger import Logger
from thomas.marketplace.logging_framework.search import (
    FacetedSearch,
    FieldIndexer,
    InvertedIndex,
    LogStore,
    LogTailer,
    ResultHighlighter,
    SearchResultsPaginator,
)


class TestInvertedIndex(unittest.TestCase):
    """Test cases for InvertedIndex."""

    def test_add_record(self) -> None:
        """Test adding records to index."""
        index = InvertedIndex()

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Hello world")
        record = handler.get_records()[0]

        index.add_record(record)
        self.assertEqual(len(index.documents), 1)

    def test_search(self) -> None:
        """Test searching the index."""
        index = InvertedIndex()

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Database connection failed")
        logger.info("User login successful")

        for record in handler.get_records():
            index.add_record(record)

        results = index.search("database")
        self.assertEqual(len(results), 1)
        self.assertIn("database", results[0].message.lower())

    def test_search_multiple_terms(self) -> None:
        """Test searching with multiple terms."""
        index = InvertedIndex()

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Database connection failed")
        logger.info("Connection timeout")
        logger.info("Database error")

        for record in handler.get_records():
            index.add_record(record)

        results = index.search("database connection")
        self.assertEqual(len(results), 1)
        self.assertIn("database", results[0].message.lower())
        self.assertIn("connection", results[0].message.lower())


class TestFieldIndexer(unittest.TestCase):
    """Test cases for FieldIndexer."""

    def test_index_by_level(self) -> None:
        """Test indexing by log level."""
        indexer = FieldIndexer()

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Info message")
        logger.error("Error message")
        logger.warning("Warning message")

        for record in handler.get_records():
            indexer.add_record(record)

        errors = indexer.search_field("level", LogLevel.ERROR)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].level, LogLevel.ERROR)

    def test_index_by_logger(self) -> None:
        """Test indexing by logger name."""
        from thomas.marketplace.logging_framework.logger import get_logger

        Logger._loggers.clear()

        indexer = FieldIndexer()

        db_logger = get_logger("app.database")
        api_logger = get_logger("app.api")

        db_handler = MemoryHandler()
        api_handler = MemoryHandler()

        db_logger.add_handler(db_handler)
        api_logger.add_handler(api_handler)

        db_logger.info("Query executed")
        api_logger.info("Request handled")

        all_records = db_handler.get_records() + api_handler.get_records()
        for record in all_records:
            indexer.add_record(record)

        db_records = indexer.search_field("logger", "app.database")
        self.assertEqual(len(db_records), 1)


class TestLogStore(unittest.TestCase):
    """Test cases for LogStore."""

    def test_add_record(self) -> None:
        """Test adding records to store."""
        store = LogStore()

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Test message")
        record = handler.get_records()[0]

        store.add_record(record)
        self.assertEqual(len(store.records), 1)

    def test_search(self) -> None:
        """Test searching log store."""
        store = LogStore()

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Error in database")
        logger.info("User authenticated")
        logger.error("Connection failed")

        for record in handler.get_records():
            store.add_record(record)

        query = LogQuery(text_search="error")
        results, total = store.search(query)

        self.assertGreater(len(results), 0)

    def test_search_by_level(self) -> None:
        """Test searching by log level."""
        store = LogStore()

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Info")
        logger.warning("Warning")
        logger.error("Error")

        for record in handler.get_records():
            store.add_record(record)

        query = LogQuery(level_min=LogLevel.ERROR, level_max=LogLevel.ERROR)
        results, total = store.search(query)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].level, LogLevel.ERROR)

    def test_store_max_size(self) -> None:
        """Test store respects maximum size."""
        store = LogStore(max_size=5)

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        for i in range(10):
            logger.info(f"Message {i}")

        for record in handler.get_records():
            store.add_record(record)

        self.assertEqual(len(store.records), 5)


class TestLogTailer(unittest.TestCase):
    """Test cases for LogTailer."""

    def test_tailer_matches_query(self) -> None:
        """Test tailer matching query."""
        query = LogQuery(text_search="error")
        tailer = LogTailer(query)

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Normal message")
        logger.error("An error occurred")

        for record in handler.get_records():
            tailer.on_new_record(record)

        new_records = tailer.get_new_records()
        self.assertEqual(len(new_records), 1)
        self.assertIn("error", new_records[0].message.lower())


class TestSearchResultsPaginator(unittest.TestCase):
    """Test cases for SearchResultsPaginator."""

    def test_pagination(self) -> None:
        """Test pagination of results."""
        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        for i in range(150):
            logger.info(f"Message {i}")

        records = handler.get_records()
        paginator = SearchResultsPaginator(records, page_size=50)

        page1, total_pages = paginator.get_page(0)
        self.assertEqual(len(page1), 50)
        self.assertEqual(total_pages, 3)

        page2, _ = paginator.get_page(1)
        self.assertEqual(len(page2), 50)

        page3, _ = paginator.get_page(2)
        self.assertEqual(len(page3), 50)

    def test_next_prev_pages(self) -> None:
        """Test next/prev page navigation."""
        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        for i in range(100):
            logger.info(f"Message {i}")

        records = handler.get_records()
        paginator = SearchResultsPaginator(records, page_size=25)

        page1, _ = paginator.get_page()
        self.assertEqual(len(page1), 25)

        page2, _ = paginator.next_page()
        self.assertEqual(len(page2), 25)

        page1_again, _ = paginator.prev_page()
        self.assertEqual(len(page1_again), 25)


class TestResultHighlighter(unittest.TestCase):
    """Test cases for ResultHighlighter."""

    def test_highlight_message(self) -> None:
        """Test highlighting terms in message."""
        highlighter = ResultHighlighter(["error", "failed"])

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Database connection error failed")
        record = handler.get_records()[0]

        highlighted = highlighter.highlight_record(record)

        self.assertIn("<mark>", highlighted["message"])
        self.assertIn("</mark>", highlighted["message"])

    def test_highlight_case_insensitive(self) -> None:
        """Test case-insensitive highlighting."""
        highlighter = ResultHighlighter(["ERROR"])

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("An error occurred")
        record = handler.get_records()[0]

        highlighted = highlighter.highlight_record(record)

        # Should highlight despite case difference
        self.assertIn("<mark>", highlighted["message"])


class TestFacetedSearch(unittest.TestCase):
    """Test cases for FacetedSearch."""

    def test_facet_by_level(self) -> None:
        """Test faceted search by level."""
        faceted = FacetedSearch()

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        for _ in range(3):
            logger.info("Info")
        for _ in range(2):
            logger.warning("Warning")
        logger.error("Error")

        for record in handler.get_records():
            faceted.add_record(record)

        level_facets = faceted.get_facet_counts("level")

        self.assertEqual(len(level_facets), 3)
        self.assertIn(("INFO", 3), level_facets)
        self.assertIn(("WARNING", 2), level_facets)

    def test_facet_by_field(self) -> None:
        """Test faceted search by custom field."""
        faceted = FacetedSearch()

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Test 1", extra_fields={"service": "api"})
        logger.info("Test 2", extra_fields={"service": "api"})
        logger.info("Test 3", extra_fields={"service": "database"})

        for record in handler.get_records():
            faceted.add_record(record)

        facets = faceted.get_facet_counts("field_service", top_n=10)

        self.assertEqual(len(facets), 2)
        self.assertEqual(facets[0][1], 2)  # api has 2


class TestLogQuery(unittest.TestCase):
    """Test cases for LogQuery."""

    def test_query_text_search(self) -> None:
        """Test text search in query."""
        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Database error")
        logger.info("User login")

        query = LogQuery(text_search="database")

        for record in handler.get_records():
            if query.matches(record):
                self.assertIn("database", record.message.lower())

    def test_query_by_level(self) -> None:
        """Test level filtering in query."""
        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Info")
        logger.warning("Warning")
        logger.error("Error")

        query = LogQuery(level_min=LogLevel.WARNING, level_max=LogLevel.ERROR)

        matches = [r for r in handler.get_records() if query.matches(r)]
        self.assertEqual(len(matches), 2)

    def test_query_by_logger_name(self) -> None:
        """Test logger name filtering in query."""
        from thomas.marketplace.logging_framework.logger import get_logger

        Logger._loggers.clear()

        logger = get_logger("app.service")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Service message")

        query = LogQuery(logger_name="app.service")

        record = handler.get_records()[0]
        self.assertTrue(query.matches(record))


if __name__ == "__main__":
    unittest.main()
