"""Data types for the benchmark system."""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class RunMode(Enum):
    """How to run the benchmark."""

    RAW_MODEL = "raw_model"  # Model alone, no tools
    THOMAS_BASIC = "thomas_basic"  # Model + Thomas tools
    THOMAS_FULL = "thomas_full"  # Model + tools + memory + RAG + self-correction
    COMPARISON = "comparison"  # Run both raw and full, compare


class TaskDifficulty(Enum):
    """Difficulty level of a benchmark task."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    EXPERT = "expert"


class EvalMetric(Enum):
    """Types of evaluation metrics."""

    PASS_FAIL = "pass_fail"  # Binary: passed or not
    EXACT_MATCH = "exact_match"  # Output matches expected exactly
    CONTAINS = "contains"  # Output contains expected substring
    TESTS_PASS = "tests_pass"  # Unit tests pass
    FUNCTIONAL = "functional"  # Custom eval function
    SIMILARITY = "similarity"  # Text similarity score
    CODE_QUALITY = "code_quality"  # Linting + style score
    PARTIAL_CREDIT = "partial_credit"  # 0.0 to 1.0 partial score


@dataclass
class BenchmarkTask:
    """A single benchmark task.

    Attributes:
        id: Unique task identifier
        name: Human-readable name
        description: What this task tests
        prompt: The prompt to send to the model/agent
        expected_output: Expected output (for comparison)
        test_code: Python test code to validate the output
        eval_metric: How to evaluate the result
        difficulty: Task difficulty level
        category: Task category (e.g., "code_gen", "debugging", "refactor")
        setup_code: Code to run before the task (create files, etc.)
        teardown_code: Code to run after the task
        time_limit_seconds: Maximum time allowed
        tags: Tags for filtering
        metadata: Additional task metadata
    """

    name: str
    prompt: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    description: str = ""
    expected_output: str = ""
    test_code: str = ""
    eval_metric: EvalMetric = EvalMetric.TESTS_PASS
    eval_fn: Callable | None = None
    difficulty: TaskDifficulty = TaskDifficulty.MEDIUM
    category: str = "general"
    setup_code: str = ""
    teardown_code: str = ""
    time_limit_seconds: int = 120
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary (excludes callables)."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "prompt": self.prompt,
            "expected_output": self.expected_output,
            "test_code": self.test_code,
            "eval_metric": self.eval_metric.value,
            "difficulty": self.difficulty.value,
            "category": self.category,
            "time_limit_seconds": self.time_limit_seconds,
            "tags": self.tags,
            "metadata": self.metadata,
        }


@dataclass
class BenchmarkResult:
    """Result of running a single benchmark task.

    Attributes:
        task_id: Which task this result is for
        task_name: Human-readable task name
        model_name: Which model was used
        run_mode: How the task was run (raw vs Thomas)
        passed: Whether the task passed
        score: Numeric score (0.0 to 1.0)
        output: The model/agent's output
        duration_ms: How long it took
        tokens_used: Total tokens consumed
        tool_calls: Number of tool calls made
        error: Error message if failed
        eval_details: Detailed evaluation info
        timestamp: When the result was recorded
    """

    task_id: str
    task_name: str
    model_name: str
    run_mode: RunMode
    passed: bool = False
    score: float = 0.0
    output: str = ""
    duration_ms: float = 0.0
    tokens_used: int = 0
    tool_calls: int = 0
    error: str = ""
    eval_details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "task_id": self.task_id,
            "task_name": self.task_name,
            "model_name": self.model_name,
            "run_mode": self.run_mode.value,
            "passed": self.passed,
            "score": self.score,
            "output": self.output[:500],
            "duration_ms": self.duration_ms,
            "tokens_used": self.tokens_used,
            "tool_calls": self.tool_calls,
            "error": self.error,
            "eval_details": self.eval_details,
            "timestamp": self.timestamp,
        }


@dataclass
class BenchmarkSuite:
    """A collection of benchmark tasks.

    Attributes:
        name: Suite name
        description: What this suite tests
        tasks: List of tasks
        version: Suite version
    """

    name: str
    description: str = ""
    tasks: list[BenchmarkTask] = field(default_factory=list)
    version: str = "1.0"

    def add_task(self, task: BenchmarkTask) -> None:
        """Add a task to the suite."""
        self.tasks.append(task)

    def get_by_category(self, category: str) -> list[BenchmarkTask]:
        """Get tasks by category."""
        return [t for t in self.tasks if t.category == category]

    def get_by_difficulty(self, diff: TaskDifficulty) -> list[BenchmarkTask]:
        """Get tasks by difficulty."""
        return [t for t in self.tasks if t.difficulty == diff]

    def categories(self) -> list[str]:
        """Get all unique categories."""
        return sorted(set(t.category for t in self.tasks))


@dataclass
class BenchmarkConfig:
    """Configuration for a benchmark run.

    Attributes:
        models: List of model names to test
        run_modes: Which run modes to execute
        parallel: Run tasks in parallel
        max_retries: Max retries per task
        save_results: Save results to disk
        results_dir: Directory for results
        verbose: Enable verbose logging
    """

    models: list[str] = field(default_factory=lambda: ["default"])
    run_modes: list[RunMode] = field(default_factory=lambda: [RunMode.RAW_MODEL, RunMode.THOMAS_FULL])
    parallel: bool = False
    max_retries: int = 1
    save_results: bool = True
    results_dir: str = "benchmark_results"
    verbose: bool = False
