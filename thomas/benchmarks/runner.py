"""Benchmark runner engine.

Executes benchmark tasks in both raw model and Thomas-augmented modes,
collecting detailed metrics for comparison.
"""

import json
import logging
import os
import time
from collections.abc import Callable
from datetime import datetime
from types import MappingProxyType
from typing import Any

from thomas.benchmarks.types import (
    BenchmarkConfig,
    BenchmarkResult,
    BenchmarkSuite,
    BenchmarkTask,
    EvalMetric,
    RunMode,
)

logger = logging.getLogger(__name__)

_ALLOWED_SANDBOX_IMPORTS = {
    "collections",
    "datetime",
    "decimal",
    "fractions",
    "functools",
    "heapq",
    "itertools",
    "json",
    "math",
    "random",
    "re",
    "statistics",
    "string",
    "time",
    "typing",
}


def _sandbox_import(
    name: str,
    globals_: dict[str, Any] | None = None,
    locals_: dict[str, Any] | None = None,
    fromlist: tuple = (),
    level: int = 0,
) -> Any:
    """Allow importing a limited set of safe standard-library modules."""
    root = name.split(".")[0]
    if root not in _ALLOWED_SANDBOX_IMPORTS:
        raise ImportError(f"Import '{name}' is not allowed in benchmark sandbox")
    return __import__(name, globals_, locals_, fromlist, level)


_SAFE_SANDBOX_BUILTINS = MappingProxyType(
    {
        "__build_class__": __build_class__,
        "__import__": _sandbox_import,
        "abs": abs,
        "all": all,
        "any": any,
        "AssertionError": AssertionError,
        "bool": bool,
        "bytes": bytes,
        "callable": callable,
        "classmethod": classmethod,
        "chr": chr,
        "delattr": delattr,
        "dict": dict,
        "divmod": divmod,
        "enumerate": enumerate,
        "Exception": Exception,
        "exec": exec,
        "filter": filter,
        "float": float,
        "frozenset": frozenset,
        "getattr": getattr,
        "hasattr": hasattr,
        "hash": hash,
        "hex": hex,
        "int": int,
        "isinstance": isinstance,
        "issubclass": issubclass,
        "iter": iter,
        "KeyError": KeyError,
        "len": len,
        "list": list,
        "map": map,
        "max": max,
        "min": min,
        "next": next,
        "NameError": NameError,
        "object": object,
        "ord": ord,
        "pow": pow,
        "print": print,
        "property": property,
        "range": range,
        "repr": repr,
        "reversed": reversed,
        "RuntimeError": RuntimeError,
        "round": round,
        "set": set,
        "setattr": setattr,
        "slice": slice,
        "sorted": sorted,
        "staticmethod": staticmethod,
        "str": str,
        "super": super,
        "sum": sum,
        "TypeError": TypeError,
        "tuple": tuple,
        "type": type,
        "ValueError": ValueError,
        "zip": zip,
    }
)


class BenchmarkRunner:
    """Executes benchmark suites and collects results.

    Supports pluggable model backends and evaluation strategies.

    Args:
        config: Benchmark configuration
    """

    def __init__(self, config: BenchmarkConfig | None = None) -> None:
        self.config = config or BenchmarkConfig()
        self._results: list[BenchmarkResult] = []
        self._model_fn: Callable | None = None
        self._agent_fn: Callable | None = None
        self._evaluators: dict[EvalMetric, Callable] = {
            EvalMetric.PASS_FAIL: self._eval_pass_fail,
            EvalMetric.EXACT_MATCH: self._eval_exact_match,
            EvalMetric.CONTAINS: self._eval_contains,
            EvalMetric.TESTS_PASS: self._eval_tests_pass,
            EvalMetric.SIMILARITY: self._eval_similarity,
            EvalMetric.CODE_QUALITY: self._eval_code_quality,
            EvalMetric.PARTIAL_CREDIT: self._eval_partial_credit,
        }

    def set_model_fn(self, fn: Callable) -> None:
        """Set the raw model function.

        Args:
            fn: Callable(prompt: str, model: str) -> str
        """
        self._model_fn = fn
        logger.info("Model function registered")

    def set_agent_fn(self, fn: Callable) -> None:
        """Set the Thomas agent function.

        Args:
            fn: Callable(prompt: str, model: str, mode: RunMode) -> dict
                Returns {"output": str, "tokens": int, "tool_calls": int}
        """
        self._agent_fn = fn
        logger.info("Agent function registered")

    def run_suite(self, suite: BenchmarkSuite, models: list[str] | None = None) -> list[BenchmarkResult]:
        """Run a full benchmark suite.

        Args:
            suite: The benchmark suite to run
            models: Override config models

        Returns:
            List of all results
        """
        models = models or self.config.models
        results: list[BenchmarkResult] = []

        logger.info(f"Running suite '{suite.name}' with {len(suite.tasks)} tasks " f"across {len(models)} models")

        for model in models:
            for mode in self.config.run_modes:
                for task in suite.tasks:
                    result = self.run_task(task, model, mode)
                    results.append(result)
                    self._results.append(result)

                    status = "PASS" if result.passed else "FAIL"
                    logger.info(
                        f"  [{status}] {task.name} | {model} | "
                        f"{mode.value} | {result.score:.2f} | "
                        f"{result.duration_ms:.0f}ms"
                    )

        if self.config.save_results:
            self._save_results(suite.name, results)

        return results

    def run_task(self, task: BenchmarkTask, model: str, mode: RunMode) -> BenchmarkResult:
        """Run a single benchmark task.

        Args:
            task: The task to run
            model: Model name
            mode: Run mode

        Returns:
            Benchmark result
        """
        result = BenchmarkResult(
            task_id=task.id,
            task_name=task.name,
            model_name=model,
            run_mode=mode,
        )
        max_retries = max(0, self.config.max_retries)
        max_attempts = max_retries + 1
        attempt_records: list[dict[str, Any]] = []
        start = time.monotonic()

        # Setup
        if task.setup_code:
            try:
                exec(task.setup_code, self._sandbox_globals())
            except Exception as e:
                logger.warning(f"Setup failed for {task.name}: {e}")

        # Execute
        for attempt in range(1, max_attempts + 1):
            attempt_record: dict[str, Any] = {
                "attempt": attempt,
                "max_attempts": max_attempts,
                "timed_out": False,
                "error": "",
            }
            attempt_start = time.monotonic()

            attempt_output = ""
            attempt_tokens = 0
            attempt_tool_calls = 0
            attempt_error = ""

            try:
                if mode == RunMode.RAW_MODEL:
                    attempt_output = self._run_raw(task, model)
                else:
                    agent_result = self._run_thomas(task, model, mode)
                    attempt_output = agent_result.get("output", "")
                    attempt_tokens = agent_result.get("tokens", 0)
                    attempt_tool_calls = agent_result.get("tool_calls", 0)
            except Exception as e:
                attempt_error = str(e)
                logger.error(f"Task {task.name} failed on attempt {attempt}/{max_attempts}: {e}")

            attempt_duration_ms = (time.monotonic() - attempt_start) * 1000
            attempt_record["duration_ms"] = attempt_duration_ms

            time_limit_ms = max(0.0, float(task.time_limit_seconds) * 1000.0)
            if attempt_duration_ms > time_limit_ms:
                attempt_record["timed_out"] = True
                timeout_error = f"Task exceeded time limit ({attempt_duration_ms:.1f}ms > " f"{time_limit_ms:.1f}ms)"
                attempt_error = f"{attempt_error}; {timeout_error}" if attempt_error else timeout_error

            attempt_record["error"] = attempt_error
            attempt_record["status"] = "error" if attempt_error else "ok"
            attempt_records.append(attempt_record)

            if attempt_error:
                result.error = attempt_error
                if attempt_record["timed_out"] or attempt == max_attempts:
                    break
                continue

            result.output = attempt_output
            result.tokens_used = attempt_tokens
            result.tool_calls = attempt_tool_calls
            result.error = ""
            break

        result.duration_ms = (time.monotonic() - start) * 1000

        # Evaluate
        eval_details: dict[str, Any] = {}
        if not result.error:
            score, details = self._evaluate(task, result.output)
            result.score = score
            result.passed = score >= 0.5
            eval_details = details

        # Teardown
        if task.teardown_code:
            try:
                exec(task.teardown_code, self._sandbox_globals())
            except Exception as e:
                logger.warning(f"Teardown failed for {task.name}: {e}")

        result.eval_details = self._with_attempt_metadata(
            eval_details,
            attempt_records,
            max_retries=max_retries,
        )

        return result

    @staticmethod
    def _with_attempt_metadata(
        details: dict[str, Any],
        attempts: list[dict[str, Any]],
        max_retries: int,
    ) -> dict[str, Any]:
        """Attach retry metadata while preserving evaluator details."""
        merged = dict(details)
        merged["attempts"] = attempts
        merged["attempt_count"] = len(attempts)
        merged["retries_configured"] = max_retries
        merged["retries_used"] = max(0, len(attempts) - 1)
        return merged

    @staticmethod
    def _sandbox_globals(extra_globals: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return globals for sandboxed exec calls."""
        sandbox_globals: dict[str, Any] = {
            "__builtins__": _SAFE_SANDBOX_BUILTINS,
            "__name__": "__benchmark_sandbox__",
        }
        if extra_globals:
            sandbox_globals.update(extra_globals)
        return sandbox_globals

    def _run_raw(self, task: BenchmarkTask, model: str) -> str:
        """Run task with raw model (no tools).

        Args:
            task: The task
            model: Model name

        Returns:
            Model output
        """
        if self._model_fn is None:
            logger.warning("No model function set, using stub")
            return "[no model function configured]"
        return self._model_fn(task.prompt, model)

    def _run_thomas(self, task: BenchmarkTask, model: str, mode: RunMode) -> dict:
        """Run task through Thomas agent.

        Args:
            task: The task
            model: Model name
            mode: Run mode

        Returns:
            Dict with output, tokens, tool_calls
        """
        if self._agent_fn is None:
            logger.warning("No agent function set, using stub")
            return {"output": "[no agent function configured]", "tokens": 0, "tool_calls": 0}
        return self._agent_fn(task.prompt, model, mode)

    def _evaluate(self, task: BenchmarkTask, output: str) -> tuple:
        """Evaluate task output.

        Args:
            task: The task with expected output
            output: Actual output

        Returns:
            (score, details) tuple
        """
        # Custom eval function takes priority
        if task.eval_metric == EvalMetric.FUNCTIONAL and task.eval_fn:
            try:
                score = task.eval_fn(output, task.expected_output)
                return (float(score), {"method": "custom_function"})
            except Exception as e:
                return (0.0, {"method": "custom_function", "error": str(e)})

        evaluator = self._evaluators.get(task.eval_metric)
        if evaluator:
            return evaluator(task, output)

        return (0.0, {"error": f"Unknown metric: {task.eval_metric}"})

    def _eval_pass_fail(self, task: BenchmarkTask, output: str) -> tuple:
        """Binary pass/fail evaluation."""
        passed = bool(output and output.strip())
        return (1.0 if passed else 0.0, {"method": "pass_fail"})

    def _eval_exact_match(self, task: BenchmarkTask, output: str) -> tuple:
        """Exact string match."""
        match = output.strip() == task.expected_output.strip()
        return (1.0 if match else 0.0, {"method": "exact_match"})

    def _eval_contains(self, task: BenchmarkTask, output: str) -> tuple:
        """Check if output contains expected substring."""
        found = task.expected_output.strip() in output
        return (1.0 if found else 0.0, {"method": "contains"})

    def _eval_tests_pass(self, task: BenchmarkTask, output: str) -> tuple:
        """Run test code against the output."""
        if not task.test_code:
            return (0.0, {"method": "tests_pass", "error": "no test code"})

        try:
            test_globals = self._sandbox_globals({"output": output, "task": task})
            exec(task.test_code, test_globals)
            passed = test_globals.get("test_passed", True)
            score = test_globals.get("test_score", 1.0 if passed else 0.0)
            return (float(score), {"method": "tests_pass", "passed": passed})
        except AssertionError as e:
            return (0.0, {"method": "tests_pass", "assertion": str(e)})
        except Exception as e:
            return (0.0, {"method": "tests_pass", "error": str(e)})

    def _eval_similarity(self, task: BenchmarkTask, output: str) -> tuple:
        """Text similarity using token overlap."""
        import re

        expected_tokens = set(re.findall(r"\w+", task.expected_output.lower()))
        output_tokens = set(re.findall(r"\w+", output.lower()))

        if not expected_tokens:
            return (0.0, {"method": "similarity", "error": "empty expected"})

        overlap = expected_tokens & output_tokens
        precision = len(overlap) / len(output_tokens) if output_tokens else 0
        recall = len(overlap) / len(expected_tokens)
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0

        return (f1, {"method": "similarity", "f1": f1, "precision": precision, "recall": recall})

    def _eval_code_quality(self, task: BenchmarkTask, output: str) -> tuple:
        """Evaluate code quality via AST parsing."""
        import ast

        try:
            tree = ast.parse(output)
            # Check basic quality signals
            has_functions = any(isinstance(n, ast.FunctionDef) for n in ast.walk(tree))
            has_docstrings = any(
                isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
                for n in ast.walk(tree)
            )
            line_count = len(output.strip().split("\n"))
            score = 0.5  # Base score for valid syntax
            if has_functions:
                score += 0.2
            if has_docstrings:
                score += 0.2
            if line_count > 5:
                score += 0.1
            return (
                min(score, 1.0),
                {
                    "method": "code_quality",
                    "syntax_valid": True,
                    "has_functions": has_functions,
                    "has_docstrings": has_docstrings,
                },
            )
        except SyntaxError as e:
            return (0.0, {"method": "code_quality", "syntax_valid": False, "error": str(e)})

    def _eval_partial_credit(self, task: BenchmarkTask, output: str) -> tuple:
        """Partial credit based on multiple criteria."""
        score = 0.0
        details = {"method": "partial_credit", "checks": []}

        # Check non-empty
        if output.strip():
            score += 0.2
            details["checks"].append("non_empty")

        # Check contains key terms from expected
        if task.expected_output:
            import re

            key_terms = set(re.findall(r"\w+", task.expected_output.lower()))
            output_terms = set(re.findall(r"\w+", output.lower()))
            overlap = len(key_terms & output_terms) / len(key_terms) if key_terms else 0
            score += overlap * 0.5
            details["term_overlap"] = overlap

        # Check reasonable length
        if len(output) > 50:
            score += 0.1
            details["checks"].append("reasonable_length")

        # Check structure (has code blocks, lists, etc.)
        if "```" in output or "def " in output or "class " in output:
            score += 0.2
            details["checks"].append("has_structure")

        return (min(score, 1.0), details)

    def get_results(self) -> list[BenchmarkResult]:
        """Get all collected results."""
        return list(self._results)

    def clear_results(self) -> None:
        """Clear all results."""
        self._results.clear()

    def _save_results(self, suite_name: str, results: list[BenchmarkResult]) -> None:
        """Save results to JSON file."""
        os.makedirs(self.config.results_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(self.config.results_dir, f"{suite_name}_{ts}.json")
        data = {
            "suite": suite_name,
            "timestamp": ts,
            "results": [r.to_dict() for r in results],
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"Results saved to {path}")
