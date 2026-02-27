"""
Tests for pipeline orchestrator.
"""

import sys

sys.path.insert(0, "/sessions/zen-pensive-cannon/mnt/Thomas")

from datetime import timedelta

from thomas.data_pipeline._exceptions import CircuitBreakerOpen, RetryError
from thomas.data_pipeline._types import (
    PipelineConfig,
    PipelineState,
    Record,
    Stage,
)
from thomas.data_pipeline.orchestrator import (
    CircuitBreaker,
    DependencyGraph,
    PipelineBuilder,
    PipelineOrchestrator,
    RetryPolicy,
)
from thomas.data_pipeline.sinks import NullSink


class MockDataSource:
    """Mock data source for testing."""

    def __init__(self, records=None):
        self.records = records or []

    def read(self):
        return self.records

    def get_schema(self):
        from thomas.data_pipeline._types import DataType, Field, Schema

        return Schema(fields=[Field(name="id", data_type=DataType.INTEGER)])

    def supports_streaming(self):
        return False


class TestCircuitBreaker:
    """Test circuit breaker."""

    def test_circuit_breaker_success(self):
        """Test circuit breaker in normal operation."""
        breaker = CircuitBreaker(failure_threshold=3)

        result = breaker.call(lambda: 42)
        assert result == 42

    def test_circuit_breaker_opens(self):
        """Test circuit breaker opens after threshold."""
        breaker = CircuitBreaker(failure_threshold=2)

        def failing_func():
            raise Exception("Test error")

        for _ in range(2):
            try:
                breaker.call(failing_func)
            except Exception:
                pass

        # Circuit should be open now
        with_error = False
        try:
            breaker.call(lambda: 42)
        except CircuitBreakerOpen:
            with_error = True

        assert with_error

    def test_circuit_breaker_recovery(self):
        """Test circuit breaker recovery."""
        breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=timedelta(seconds=0))

        # Force open
        try:
            breaker.call(lambda: 1 / 0)
        except Exception:
            pass

        # Should be open
        try:
            breaker.call(lambda: 42)
            assert False, "Should have raised CircuitBreakerOpen"
        except CircuitBreakerOpen:
            pass

        # Wait and reset
        breaker.reset()
        result = breaker.call(lambda: 42)
        assert result == 42


class TestRetryPolicy:
    """Test retry policy."""

    def test_retry_success_on_retry(self):
        """Test successful retry."""
        attempt_count = 0

        def sometimes_fails():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 2:
                raise Exception("First attempt fails")
            return "success"

        policy = RetryPolicy(max_retries=3, base_delay=0.01)
        result = policy.execute(sometimes_fails)

        assert result == "success"
        assert attempt_count == 2

    def test_retry_exhaustion(self):
        """Test retry exhaustion."""

        def always_fails():
            raise Exception("Always fails")

        policy = RetryPolicy(max_retries=2, base_delay=0.01)

        with_error = False
        try:
            policy.execute(always_fails)
        except RetryError:
            with_error = True

        assert with_error


class TestDependencyGraph:
    """Test dependency graph."""

    def test_topological_sort(self):
        """Test topological sorting."""
        graph = DependencyGraph()

        # Create graph: A -> B -> C
        graph.add_stage("A")
        graph.add_stage("B")
        graph.add_stage("C")
        graph.add_dependency("B", "A")
        graph.add_dependency("C", "B")

        order = graph.topological_sort()

        # A should come before B, B before C
        assert order.index("A") < order.index("B")
        assert order.index("B") < order.index("C")

    def test_get_upstream(self):
        """Test getting upstream stages."""
        graph = DependencyGraph()

        graph.add_stage("A")
        graph.add_stage("B")
        graph.add_stage("C")
        graph.add_dependency("B", "A")
        graph.add_dependency("C", "B")

        upstream = graph.get_upstream("C")

        assert "B" in upstream
        assert "A" in upstream


class TestPipelineOrchestrator:
    """Test pipeline orchestrator."""

    def test_orchestrator_execution(self):
        """Test basic pipeline execution."""
        source = MockDataSource(
            [
                Record(data={"id": 1}),
                Record(data={"id": 2}),
            ]
        )
        sink = NullSink()

        stage = Stage(name="test_stage", source=source, sink=sink)

        config = PipelineConfig(name="test_pipeline")
        config.add_stage(stage)

        orchestrator = PipelineOrchestrator(config)
        success = orchestrator.execute()

        assert success
        assert orchestrator.get_state() == PipelineState.COMPLETED

    def test_orchestrator_state_transition(self):
        """Test state transitions."""
        source = MockDataSource([Record(data={"id": 1})])
        sink = NullSink()
        stage = Stage(name="stage1", source=source, sink=sink)

        config = PipelineConfig(name="pipeline1")
        config.add_stage(stage)

        orchestrator = PipelineOrchestrator(config)

        assert orchestrator.get_state() == PipelineState.CREATED

        orchestrator.execute()

        assert orchestrator.get_state() == PipelineState.COMPLETED

    def test_dry_run_mode(self):
        """Test dry run mode."""
        source = MockDataSource([Record(data={"id": 1})])
        sink = NullSink()
        stage = Stage(name="stage1", source=source, sink=sink)

        config = PipelineConfig(name="pipeline1", dry_run=True)
        config.add_stage(stage)

        orchestrator = PipelineOrchestrator(config)
        success = orchestrator.dry_run()

        assert success

    def test_checkpoint_creation(self):
        """Test checkpoint creation."""
        source = MockDataSource([Record(data={"id": 1})])
        sink = NullSink()
        stage = Stage(name="stage1", source=source, sink=sink)

        config = PipelineConfig(name="pipeline1")
        config.add_stage(stage)

        orchestrator = PipelineOrchestrator(config)
        checkpoint = orchestrator.create_checkpoint("stage1", 100)

        assert checkpoint.stage_name == "stage1"
        assert checkpoint.offset == 100

    def test_metrics_collection(self):
        """Test metrics collection."""
        source = MockDataSource(
            [
                Record(data={"id": 1}),
                Record(data={"id": 2}),
                Record(data={"id": 3}),
            ]
        )
        sink = NullSink()
        stage = Stage(name="stage1", source=source, sink=sink)

        config = PipelineConfig(name="pipeline1")
        config.add_stage(stage)

        orchestrator = PipelineOrchestrator(config)
        orchestrator.execute()

        metrics = orchestrator.get_metrics()
        assert len(metrics) > 0


class TestPipelineBuilder:
    """Test pipeline builder."""

    def test_builder_fluent_api(self):
        """Test fluent builder API."""
        source = MockDataSource([Record(data={"id": 1})])
        sink = NullSink()
        stage = Stage(name="stage1", source=source, sink=sink)

        orchestrator = (
            PipelineBuilder("my_pipeline")
            .add_stage(stage)
            .set_max_parallelism(2)
            .set_owner("data_team")
            .add_tag("env", "test")
            .build()
        )

        assert orchestrator.config.name == "my_pipeline"
        assert orchestrator.config.max_parallelism == 2
        assert orchestrator.config.owner == "data_team"
        assert orchestrator.config.tags["env"] == "test"

    def test_builder_validation(self):
        """Test builder validation."""
        from thomas.data_pipeline._exceptions import ConfigurationError

        builder = PipelineBuilder("empty_pipeline")

        with_error = False
        try:
            builder.build()
        except ConfigurationError:
            with_error = True

        assert with_error


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
