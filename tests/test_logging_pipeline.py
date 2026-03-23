"""Tests for the log processing pipeline."""

import unittest

from thomas.marketplace.logging_framework._types import LogLevel
from thomas.marketplace.logging_framework.handlers import MemoryHandler
from thomas.marketplace.logging_framework.logger import Logger
from thomas.marketplace.logging_framework.pipeline import (
    EnrichmentProcessor,
    LogPipeline,
    PipelineConfig,
    Router,
    TransformationProcessor,
)


class TestEnrichmentProcessor(unittest.TestCase):
    """Test cases for EnrichmentProcessor."""

    def test_add_hostname(self) -> None:
        """Test enrichment adds hostname."""
        processor = EnrichmentProcessor()
        processor.add_hostname = True

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Test")

        record = handler.get_records()[0]
        processed = processor.process(record)

        self.assertIn("hostname", processed.fields)

    def test_add_timestamp_millis(self) -> None:
        """Test enrichment adds millisecond timestamp."""
        processor = EnrichmentProcessor()
        processor.add_timestamp_millis = True

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Test")

        record = handler.get_records()[0]
        processed = processor.process(record)

        self.assertIn("timestamp_millis", processed.fields)
        self.assertIsInstance(processed.fields["timestamp_millis"].value, int)

    def test_custom_enricher(self) -> None:
        """Test adding custom enricher."""
        processor = EnrichmentProcessor()
        processor.add_enricher("custom_field", lambda r: "custom_value")

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Test")

        record = handler.get_records()[0]
        processed = processor.process(record)

        self.assertIn("custom_field", processed.fields)
        self.assertEqual(processed.fields["custom_field"].value, "custom_value")


class TestTransformationProcessor(unittest.TestCase):
    """Test cases for TransformationProcessor."""

    def test_field_masking(self) -> None:
        """Test field masking."""
        processor = TransformationProcessor()
        processor.add_field_mask("password")

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Test", extra_fields={"password": "secret123"})

        record = handler.get_records()[0]
        processed = processor.process(record)

        masked_value = processed.fields["password"].value
        # Should be masked but not fully redacted
        self.assertNotEqual(masked_value, "secret123")
        self.assertIn("*", str(masked_value))

    def test_field_redaction(self) -> None:
        """Test field redaction."""
        processor = TransformationProcessor()
        processor.add_field_redaction("ssn")

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Test", extra_fields={"ssn": "123-45-6789"})

        record = handler.get_records()[0]
        processed = processor.process(record)

        self.assertEqual(processed.fields["ssn"].value, "[REDACTED]")
        self.assertTrue(processed.fields["ssn"].is_redacted)

    def test_field_rename(self) -> None:
        """Test field renaming."""
        processor = TransformationProcessor()
        processor.rename_field("old_name", "new_name")

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Test", extra_fields={"old_name": "value"})

        record = handler.get_records()[0]
        processed = processor.process(record)

        self.assertNotIn("old_name", processed.fields)
        self.assertIn("new_name", processed.fields)
        self.assertEqual(processed.fields["new_name"].value, "value")

    def test_pii_masking(self) -> None:
        """Test PII masking in message."""
        processor = TransformationProcessor()

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Email: john@example.com and phone: 555-123-4567")

        record = handler.get_records()[0]
        processed = processor.process(record)

        # Message should have PII masked
        self.assertNotIn("john@example.com", processed.message)


class TestRouter(unittest.TestCase):
    """Test cases for Router."""

    def test_routing_by_level(self) -> None:
        """Test routing based on log level."""
        router = Router()
        error_handler = MemoryHandler()
        warning_handler = MemoryHandler()

        router.add_route("errors", lambda r: r.level >= LogLevel.ERROR)
        router.add_route("warnings", lambda r: LogLevel.WARNING <= r.level < LogLevel.ERROR)

        router.add_sink_to_route("errors", error_handler)
        router.add_sink_to_route("warnings", warning_handler)

        logger = Logger("test")
        logger.add_handler(error_handler)
        logger.add_handler(warning_handler)

        logger.warning("Warning")
        logger.error("Error")

        self.assertEqual(len(warning_handler.get_records()), 1)
        self.assertEqual(len(error_handler.get_records()), 1)

    def test_routing_by_logger_name(self) -> None:
        """Test routing based on logger name."""
        from thomas.marketplace.logging_framework.logger import get_logger

        Logger._loggers.clear()

        router = Router()
        db_handler = MemoryHandler()

        router.add_route("database", lambda r: "database" in r.logger_name)
        router.add_sink_to_route("database", db_handler)

        db_logger = get_logger("app.database")
        api_logger = get_logger("app.api")

        db_logger.add_handler(db_handler)
        api_logger.add_handler(db_handler)

        db_logger.info("DB operation")
        api_logger.info("API call")

        records = db_handler.get_records()
        self.assertEqual(len(records), 1)
        self.assertIn("DB operation", records[0].message)


class TestLogPipeline(unittest.TestCase):
    """Test cases for LogPipeline."""

    def test_pipeline_processing(self) -> None:
        """Test log processing through pipeline."""
        pipeline = LogPipeline()

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Test message")

        record = handler.get_records()[0]
        processed = pipeline.process(record)

        # Should have enriched fields
        self.assertIsNotNone(processed)
        self.assertIn("timestamp_millis", processed.fields)

    def test_pipeline_disable(self) -> None:
        """Test disabling pipeline."""
        pipeline = LogPipeline()
        pipeline.disable()

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Test")

        record = handler.get_records()[0]
        processed = pipeline.process(record)

        # Should return record unchanged
        self.assertIsNotNone(processed)

    def test_pipeline_enable(self) -> None:
        """Test enabling disabled pipeline."""
        pipeline = LogPipeline()
        pipeline.disable()
        pipeline.enable()

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Test")

        record = handler.get_records()[0]
        processed = pipeline.process(record)

        # Should process normally
        self.assertIsNotNone(processed)


class TestPipelineConfig(unittest.TestCase):
    """Test cases for PipelineConfig."""

    def test_config_from_dict(self) -> None:
        """Test creating pipeline from config dict."""
        config = {
            "enrichment": {
                "add_hostname": True,
                "add_timestamp_millis": True,
            },
            "transformation": {
                "field_masks": ["password"],
                "field_redactions": ["ssn"],
            },
        }

        pipeline = PipelineConfig.from_dict(config)

        self.assertTrue(pipeline.enrichment.add_hostname)
        self.assertTrue(pipeline.enrichment.add_timestamp_millis)
        self.assertIn("password", pipeline.transformation.field_masks)
        self.assertIn("ssn", pipeline.transformation.field_redactions)

    def test_config_enrichment_options(self) -> None:
        """Test enrichment options from config."""
        config = {
            "enrichment": {
                "add_hostname": False,
                "add_timestamp_millis": True,
            },
        }

        pipeline = PipelineConfig.from_dict(config)

        self.assertFalse(pipeline.enrichment.add_hostname)
        self.assertTrue(pipeline.enrichment.add_timestamp_millis)

    def test_config_transformation_options(self) -> None:
        """Test transformation options from config."""
        config = {
            "transformation": {
                "field_masks": ["password", "token", "api_key"],
            },
        }

        pipeline = PipelineConfig.from_dict(config)

        self.assertEqual(len(pipeline.transformation.field_masks), 3)
        self.assertIn("password", pipeline.transformation.field_masks)
        self.assertIn("api_key", pipeline.transformation.field_masks)


class TestPipelineIntegration(unittest.TestCase):
    """Integration tests for pipeline."""

    def test_full_pipeline_flow(self) -> None:
        """Test full pipeline flow with all processors."""
        pipeline = LogPipeline()
        pipeline.enrichment.add_enricher("request_id", lambda r: "req-123")
        pipeline.transformation.add_field_mask("password")

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Login attempt", extra_fields={"password": "secret"})

        record = handler.get_records()[0]
        processed = pipeline.process(record)

        # Should have enriched field
        self.assertIn("request_id", processed.fields)
        self.assertEqual(processed.fields["request_id"].value, "req-123")

        # Should have masked field
        self.assertNotEqual(processed.fields["password"].value, "secret")

    def test_pipeline_with_custom_stage(self) -> None:
        """Test pipeline with custom processing stage."""
        from thomas.marketplace.logging_framework.pipeline import PipelineStage

        class CustomStage(PipelineStage):
            def process(self, record):
                record.fields["custom"] = __import__(
                    "thomas.marketplace.logging_framework._types", fromlist=["StructuredField"]
                ).StructuredField(name="custom", value="processed")
                return record

        pipeline = LogPipeline()
        pipeline.add_stage(CustomStage())

        logger = Logger("test")
        handler = MemoryHandler()
        logger.add_handler(handler)

        logger.info("Test")

        record = handler.get_records()[0]
        processed = pipeline.process(record)

        self.assertIn("custom", processed.fields)
        self.assertEqual(processed.fields["custom"].value, "processed")


if __name__ == "__main__":
    unittest.main()
