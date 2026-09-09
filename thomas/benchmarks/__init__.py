"""Thomas benchmark harness for measuring model amplification.

Tests how much Thomas's OS layer (tools, memory, RAG, sandboxing,
self-correction, delegation) amplifies a model's raw capabilities.

Includes official benchmark suites:
- SWE-bench: Software engineering tasks
- HumanEval: Code generation
- MBPP: Basic Python problems
- MATH: Competition-level math
- GSM8K: Grade-school math
- MT-Bench: Multi-turn conversation
- GPQA: Graduate-level expert Q&A
- BigCodeBench: Practical coding
"""

from thomas.benchmarks.amplifier import AmplificationScorer
from thomas.benchmarks.report import BenchmarkReport
from thomas.benchmarks.runner import BenchmarkRunner
from thomas.benchmarks.types import (
    BenchmarkConfig,
    BenchmarkResult,
    BenchmarkSuite,
    BenchmarkTask,
    EvalMetric,
    RunMode,
    TaskDifficulty,
)

__all__ = [
    "BenchmarkTask",
    "BenchmarkResult",
    "BenchmarkSuite",
    "BenchmarkConfig",
    "RunMode",
    "TaskDifficulty",
    "EvalMetric",
    "BenchmarkRunner",
    "AmplificationScorer",
    "BenchmarkReport",
]
