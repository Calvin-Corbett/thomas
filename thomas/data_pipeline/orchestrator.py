"""
Pipeline orchestrator for coordinating execution.

Implements DAG-based pipeline definition, execution ordering, parallel execution,
state management, retry logic, and circuit breaker patterns.
"""

import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from thomas.data_pipeline._exceptions import (
    CircuitBreakerOpen,
    ConfigurationError,
    RetryError,
    StageError,
)
from thomas.data_pipeline._types import (
    Checkpoint,
    Metric,
    PipelineConfig,
    PipelineState,
    Record,
    Stage,
)


class CircuitBreaker:
    """
    Circuit breaker pattern for fault tolerance.

    Prevents cascading failures by failing fast when error rate exceeds threshold.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: timedelta = None,
    ) -> None:
        """
        Initialize circuit breaker.

        Args:
            failure_threshold: Number of failures before opening
            recovery_timeout: Time before attempting recovery
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout or timedelta(seconds=60)
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: datetime | None = None
        self._state = "closed"  # "closed", "open", "half-open"

    def call(self, func: Callable[[], Any]) -> Any:
        """Execute function through circuit breaker."""
        if self._state == "open":
            if self._should_attempt_recovery():
                self._state = "half-open"
            else:
                raise CircuitBreakerOpen("Circuit breaker is open")

        try:
            result = func()
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        """Handle successful execution."""
        self._success_count += 1
        if self._state == "half-open":
            self._state = "closed"
            self._failure_count = 0
            self._success_count = 0

    def _on_failure(self) -> None:
        """Handle failed execution."""
        self._failure_count += 1
        self._last_failure_time = datetime.utcnow()

        if self._failure_count >= self.failure_threshold:
            self._state = "open"

    def _should_attempt_recovery(self) -> bool:
        """Check if circuit should attempt recovery."""
        if self._last_failure_time is None:
            return False
        return datetime.utcnow() - self._last_failure_time >= self.recovery_timeout

    def reset(self) -> None:
        """Reset circuit breaker state."""
        self._state = "closed"
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None


class RetryPolicy:
    """
    Retry policy for failed operations.

    Implements exponential backoff with configurable parameters.
    """

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        backoff_multiplier: float = 2.0,
        jitter: bool = True,
    ) -> None:
        """
        Initialize retry policy.

        Args:
            max_retries: Maximum number of retry attempts
            base_delay: Initial delay in seconds
            max_delay: Maximum delay in seconds
            backoff_multiplier: Multiplier for exponential backoff
            jitter: Add random jitter to delays
        """
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_multiplier = backoff_multiplier
        self.jitter = jitter

    def execute(self, func: Callable[[], Any]) -> Any:
        """Execute function with retry logic."""
        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                return func()
            except Exception as e:
                last_exception = e
                if attempt < self.max_retries:
                    delay = self._calculate_delay(attempt)
                    time.sleep(delay)

        raise RetryError(f"Max retries exceeded: {last_exception}", self.max_retries)

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number."""
        delay = self.base_delay * (self.backoff_multiplier**attempt)
        delay = min(delay, self.max_delay)

        if self.jitter:
            import random

            delay = delay * (0.5 + random.random())

        return delay


class DependencyGraph:
    """
    Represents DAG dependencies between stages.

    Tracks stage dependencies for topological ordering.
    """

    def __init__(self) -> None:
        """Initialize dependency graph."""
        self._graph: dict[str, set[str]] = defaultdict(set)
        self._reverse_graph: dict[str, set[str]] = defaultdict(set)
        self._all_stages: set[str] = set()

    def add_stage(self, stage_name: str) -> None:
        """Add a stage to the graph."""
        self._all_stages.add(stage_name)
        if stage_name not in self._graph:
            self._graph[stage_name] = set()

    def add_dependency(self, stage: str, depends_on: str) -> None:
        """Add a dependency (stage depends on depends_on)."""
        self._graph[stage].add(depends_on)
        self._reverse_graph[depends_on].add(stage)
        self._all_stages.add(stage)
        self._all_stages.add(depends_on)

    def topological_sort(self) -> list[str]:
        """Return stages in topological order."""
        in_degree = {s: len(self._graph[s]) for s in self._all_stages}
        queue = deque([s for s in self._all_stages if in_degree[s] == 0])
        result = []

        while queue:
            stage = queue.popleft()
            result.append(stage)

            for dependent in self._reverse_graph.get(stage, []):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    queue.append(dependent)

        if len(result) != len(self._all_stages):
            raise ConfigurationError("Pipeline contains circular dependency")

        return result

    def get_dependencies(self, stage: str) -> set[str]:
        """Get all dependencies of a stage."""
        return self._graph.get(stage, set())


class PipelineOrchestrator:
    """
    Orchestrates pipeline execution.

    Manages DAG-based stage execution, state transitions, retries, and monitoring.
    """

    def __init__(self, config: PipelineConfig) -> None:
        """
        Initialize orchestrator.

        Args:
            config: Pipeline configuration
        """
        self.config = config
        self._state = PipelineState.CREATED
        self._stage_states: dict[str, PipelineState] = {}
        self._stage_results: dict[str, list[Record]] = {}
        self._stage_errors: dict[str, Exception] = {}
        self._dependency_graph = DependencyGraph()
        self._circuit_breakers: dict[str, CircuitBreaker] = {}
        self._retry_policies: dict[str, RetryPolicy] = {}
        self._checkpoints: list[Checkpoint] = []
        self._metrics: list[Metric] = []
        self._start_time: datetime | None = None
        self._end_time: datetime | None = None
        self._build_dependency_graph()
        self._initialize_policies()

    def _build_dependency_graph(self) -> None:
        """Build dependency graph from pipeline config."""
        for stage in self.config.stages:
            self._dependency_graph.add_stage(stage.name)

    def _initialize_policies(self) -> None:
        """Initialize retry and circuit breaker policies."""
        for stage in self.config.stages:
            self._stage_states[stage.name] = PipelineState.CREATED

            self._circuit_breakers[stage.name] = CircuitBreaker()

            retry_config = stage.retry_policy or {}
            self._retry_policies[stage.name] = RetryPolicy(
                max_retries=retry_config.get("max_retries", 3),
                base_delay=retry_config.get("base_delay", 1.0),
            )

    def execute(self) -> bool:
        """
        Execute the pipeline.

        Returns:
            True if execution completed successfully
        """
        try:
            self._state = PipelineState.RUNNING
            self._start_time = datetime.utcnow()

            execution_order = self._dependency_graph.topological_sort()

            for stage_name in execution_order:
                if not self._execute_stage(stage_name):
                    self._state = PipelineState.FAILED
                    self._end_time = datetime.utcnow()
                    return False

            self._state = PipelineState.COMPLETED
            self._end_time = datetime.utcnow()
            return True

        except Exception:
            self._state = PipelineState.FAILED
            self._end_time = datetime.utcnow()
            raise

    def _execute_stage(self, stage_name: str) -> bool:
        """
        Execute a single stage.

        Args:
            stage_name: Name of stage to execute

        Returns:
            True if stage executed successfully
        """
        stage = self.config.get_stage(stage_name)
        if stage is None:
            raise StageError(f"Stage {stage_name} not found", stage_name)

        self._stage_states[stage_name] = PipelineState.RUNNING

        try:
            retry_policy = self._retry_policies[stage_name]
            circuit_breaker = self._circuit_breakers[stage_name]

            def execute_fn() -> list[Record]:
                return circuit_breaker.call(lambda: self._execute_stage_logic(stage))

            results = retry_policy.execute(execute_fn)
            self._stage_results[stage_name] = results
            self._stage_states[stage_name] = PipelineState.COMPLETED

            self._record_metric(stage_name, len(results))
            return True

        except Exception as e:
            self._stage_states[stage_name] = PipelineState.FAILED
            self._stage_errors[stage_name] = e
            return False

    def _execute_stage_logic(self, stage: Stage) -> list[Record]:
        """
        Execute the actual logic of a stage.

        Args:
            stage: Stage to execute

        Returns:
            List of records produced by stage
        """
        # Read from source
        records = stage.source.read()

        # Apply filters
        for f in stage.filters:
            records = [r for r in records if f.matches(r)]

        # Apply transforms
        for transform in stage.transforms:
            transformed = []
            for record in records:
                result = transform.transform(record)
                if isinstance(result, list):
                    transformed.extend(result)
                elif result is not None:
                    transformed.append(result)
            records = transformed

        # Write to sink
        if not self.config.dry_run:
            stage.sink.write_batch(records)
            stage.sink.flush()

        return records

    def _record_metric(self, stage_name: str, record_count: int) -> None:
        """Record execution metric for stage."""
        metric = Metric(
            name=f"stage_{stage_name}_records",
            value=float(record_count),
            tags={"stage": stage_name},
        )
        self._metrics.append(metric)

    def get_state(self) -> PipelineState:
        """Get current pipeline state."""
        return self._state

    def get_stage_state(self, stage_name: str) -> PipelineState:
        """Get state of a specific stage."""
        return self._stage_states.get(stage_name, PipelineState.CREATED)

    def get_metrics(self) -> list[Metric]:
        """Get collected metrics."""
        return self._metrics

    def get_execution_time(self) -> timedelta | None:
        """Get total execution time."""
        if self._start_time and self._end_time:
            return self._end_time - self._start_time
        return None

    def dry_run(self) -> bool:
        """Execute pipeline in dry run mode (no writes)."""
        original_dry_run = self.config.dry_run
        self.config.dry_run = True
        try:
            return self.execute()
        finally:
            self.config.dry_run = original_dry_run

    def create_checkpoint(self, stage_name: str, offset: int) -> Checkpoint:
        """
        Create checkpoint for recovery.

        Args:
            stage_name: Name of stage to checkpoint
            offset: Processing offset

        Returns:
            Created checkpoint
        """
        checkpoint = Checkpoint(
            checkpoint_id=f"cp-{stage_name}-{int(datetime.utcnow().timestamp())}",
            pipeline_name=self.config.name,
            stage_name=stage_name,
            offset=offset,
            processed_count=len(self._stage_results.get(stage_name, [])),
        )
        self._checkpoints.append(checkpoint)
        return checkpoint

    def get_latest_checkpoint(self, stage_name: str) -> Checkpoint | None:
        """Get latest checkpoint for a stage."""
        stage_checkpoints = [c for c in self._checkpoints if c.stage_name == stage_name]
        return max(stage_checkpoints, key=lambda c: c.timestamp) if stage_checkpoints else None


class PipelineBuilder:
    """
    Builder for constructing pipelines fluently.

    Provides a clean API for pipeline definition.
    """

    def __init__(self, name: str, description: str = "") -> None:
        """
        Initialize pipeline builder.

        Args:
            name: Pipeline name
            description: Pipeline description
        """
        self.config = PipelineConfig(name=name, description=description)

    def add_stage(self, stage: Stage) -> "PipelineBuilder":
        """Add a stage to the pipeline."""
        self.config.add_stage(stage)
        return self

    def set_max_parallelism(self, parallelism: int) -> "PipelineBuilder":
        """Set maximum parallelism."""
        self.config.max_parallelism = parallelism
        return self

    def enable_checkpointing(self, enabled: bool = True) -> "PipelineBuilder":
        """Enable or disable checkpointing."""
        self.config.enable_checkpointing = enabled
        return self

    def enable_lineage(self, enabled: bool = True) -> "PipelineBuilder":
        """Enable or disable lineage tracking."""
        self.config.enable_lineage = enabled
        return self

    def set_owner(self, owner: str) -> "PipelineBuilder":
        """Set pipeline owner."""
        self.config.owner = owner
        return self

    def add_tag(self, key: str, value: str) -> "PipelineBuilder":
        """Add a tag to the pipeline."""
        self.config.tags[key] = value
        return self

    def build(self) -> PipelineOrchestrator:
        """Build the pipeline orchestrator."""
        if not self.config.stages:
            raise ConfigurationError("Pipeline must have at least one stage")

        return PipelineOrchestrator(self.config)
