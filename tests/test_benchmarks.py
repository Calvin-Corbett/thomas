"""Tests for thomas.benchmarks module."""

import json
import os
import tempfile
import time
import unittest
from datetime import datetime

from thomas.benchmarks.amplifier import AmplificationScorer
from thomas.benchmarks.bigcode import create_bigcode_suite
from thomas.benchmarks.gpqa import create_gpqa_suite
from thomas.benchmarks.math_bench import create_gsm8k_suite, create_math_suite
from thomas.benchmarks.mbpp import create_mbpp_suite
from thomas.benchmarks.mt_bench import create_mt_bench_suite
from thomas.benchmarks.report import BenchmarkReport
from thomas.benchmarks.runner import BenchmarkRunner
from thomas.benchmarks.swe_bench import (
    LocalSWEBenchFixture,
    create_humaneval_suite,
    create_local_swe_bench_fixture,
    create_local_swe_bench_suite,
    create_swe_bench_suite,
    score_swe_bench_patch,
)
from thomas.benchmarks.types import (
    BenchmarkConfig,
    BenchmarkResult,
    BenchmarkSuite,
    BenchmarkTask,
    EvalMetric,
    RunMode,
    TaskDifficulty,
)


class TestBenchmarkTask(unittest.TestCase):
    def test_create_task(self):
        task = BenchmarkTask(name="test_task", prompt="Do something")
        self.assertEqual(task.name, "test_task")
        self.assertTrue(len(task.id) > 0)
        self.assertEqual(task.difficulty, TaskDifficulty.MEDIUM)

    def test_task_to_dict(self):
        task = BenchmarkTask(
            name="test",
            prompt="Test prompt",
            category="code_gen",
            difficulty=TaskDifficulty.HARD,
        )
        d = task.to_dict()
        self.assertEqual(d["name"], "test")
        self.assertEqual(d["difficulty"], "hard")
        self.assertEqual(d["category"], "code_gen")

    def test_task_defaults(self):
        task = BenchmarkTask(name="t", prompt="p")
        self.assertEqual(task.eval_metric, EvalMetric.TESTS_PASS)
        self.assertEqual(task.time_limit_seconds, 120)
        self.assertEqual(task.tags, [])


class TestBenchmarkResult(unittest.TestCase):
    def test_create_result(self):
        r = BenchmarkResult(
            task_id="abc",
            task_name="test",
            model_name="gpt-4",
            run_mode=RunMode.RAW_MODEL,
            passed=True,
            score=0.95,
        )
        self.assertEqual(r.task_id, "abc")
        self.assertTrue(r.passed)
        self.assertEqual(r.score, 0.95)

    def test_result_to_dict(self):
        r = BenchmarkResult(
            task_id="x",
            task_name="t",
            model_name="m",
            run_mode=RunMode.THOMAS_FULL,
        )
        d = r.to_dict()
        self.assertEqual(d["run_mode"], "thomas_full")
        self.assertIn("timestamp", d)

    def test_result_defaults(self):
        r = BenchmarkResult(
            task_id="x",
            task_name="t",
            model_name="m",
            run_mode=RunMode.RAW_MODEL,
        )
        self.assertFalse(r.passed)
        self.assertEqual(r.score, 0.0)
        self.assertEqual(r.tool_calls, 0)

    def test_result_timestamp_timezone_aware(self):
        r = BenchmarkResult(
            task_id="x",
            task_name="t",
            model_name="m",
            run_mode=RunMode.RAW_MODEL,
        )
        parsed = datetime.fromisoformat(r.timestamp)
        self.assertIsNotNone(parsed.tzinfo)


class TestBenchmarkSuite(unittest.TestCase):
    def test_create_suite(self):
        suite = BenchmarkSuite(name="test_suite")
        self.assertEqual(len(suite.tasks), 0)

    def test_add_task(self):
        suite = BenchmarkSuite(name="s")
        suite.add_task(BenchmarkTask(name="t1", prompt="p", category="a"))
        suite.add_task(BenchmarkTask(name="t2", prompt="p", category="b"))
        self.assertEqual(len(suite.tasks), 2)

    def test_get_by_category(self):
        suite = BenchmarkSuite(name="s")
        suite.add_task(BenchmarkTask(name="t1", prompt="p", category="code"))
        suite.add_task(BenchmarkTask(name="t2", prompt="p", category="math"))
        suite.add_task(BenchmarkTask(name="t3", prompt="p", category="code"))
        self.assertEqual(len(suite.get_by_category("code")), 2)

    def test_get_by_difficulty(self):
        suite = BenchmarkSuite(name="s")
        suite.add_task(BenchmarkTask(name="t1", prompt="p", difficulty=TaskDifficulty.EASY))
        suite.add_task(BenchmarkTask(name="t2", prompt="p", difficulty=TaskDifficulty.HARD))
        self.assertEqual(len(suite.get_by_difficulty(TaskDifficulty.EASY)), 1)

    def test_categories(self):
        suite = BenchmarkSuite(name="s")
        suite.add_task(BenchmarkTask(name="t1", prompt="p", category="b"))
        suite.add_task(BenchmarkTask(name="t2", prompt="p", category="a"))
        self.assertEqual(suite.categories(), ["a", "b"])


class TestBenchmarkConfig(unittest.TestCase):
    def test_defaults(self):
        config = BenchmarkConfig()
        self.assertEqual(config.models, ["default"])
        self.assertEqual(len(config.run_modes), 2)
        self.assertFalse(config.parallel)

    def test_custom_config(self):
        config = BenchmarkConfig(
            models=["gpt-4", "claude"],
            run_modes=[RunMode.RAW_MODEL],
            parallel=True,
        )
        self.assertEqual(len(config.models), 2)
        self.assertTrue(config.parallel)


class TestRunMode(unittest.TestCase):
    def test_values(self):
        self.assertEqual(RunMode.RAW_MODEL.value, "raw_model")
        self.assertEqual(RunMode.THOMAS_FULL.value, "thomas_full")
        self.assertEqual(RunMode.THOMAS_BASIC.value, "thomas_basic")
        self.assertEqual(RunMode.COMPARISON.value, "comparison")


class TestBenchmarkRunner(unittest.TestCase):
    def setUp(self):
        self.config = BenchmarkConfig(
            save_results=False,
            run_modes=[RunMode.RAW_MODEL],
        )
        self.runner = BenchmarkRunner(self.config)

    def test_create_runner(self):
        runner = BenchmarkRunner()
        self.assertIsNotNone(runner)

    def test_set_model_fn(self):
        self.runner.set_model_fn(lambda prompt, model: "hello")
        result = self.runner.run_task(
            BenchmarkTask(name="t", prompt="p", eval_metric=EvalMetric.PASS_FAIL),
            "test_model",
            RunMode.RAW_MODEL,
        )
        self.assertEqual(result.output, "hello")

    def test_set_agent_fn(self):
        self.runner.set_agent_fn(lambda prompt, model, mode: {"output": "agent out", "tokens": 10, "tool_calls": 2})
        result = self.runner.run_task(
            BenchmarkTask(name="t", prompt="p", eval_metric=EvalMetric.PASS_FAIL),
            "test_model",
            RunMode.THOMAS_FULL,
        )
        self.assertEqual(result.output, "agent out")
        self.assertEqual(result.tokens_used, 10)

    def test_eval_pass_fail(self):
        self.runner.set_model_fn(lambda p, m: "some output")
        result = self.runner.run_task(
            BenchmarkTask(name="t", prompt="p", eval_metric=EvalMetric.PASS_FAIL),
            "m",
            RunMode.RAW_MODEL,
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.score, 1.0)

    def test_eval_exact_match(self):
        self.runner.set_model_fn(lambda p, m: "42")
        result = self.runner.run_task(
            BenchmarkTask(
                name="t",
                prompt="p",
                expected_output="42",
                eval_metric=EvalMetric.EXACT_MATCH,
            ),
            "m",
            RunMode.RAW_MODEL,
        )
        self.assertTrue(result.passed)

    def test_eval_exact_match_fail(self):
        self.runner.set_model_fn(lambda p, m: "43")
        result = self.runner.run_task(
            BenchmarkTask(
                name="t",
                prompt="p",
                expected_output="42",
                eval_metric=EvalMetric.EXACT_MATCH,
            ),
            "m",
            RunMode.RAW_MODEL,
        )
        self.assertFalse(result.passed)

    def test_eval_contains(self):
        self.runner.set_model_fn(lambda p, m: "the answer is 42 ok")
        result = self.runner.run_task(
            BenchmarkTask(
                name="t",
                prompt="p",
                expected_output="42",
                eval_metric=EvalMetric.CONTAINS,
            ),
            "m",
            RunMode.RAW_MODEL,
        )
        self.assertTrue(result.passed)

    def test_eval_tests_pass(self):
        self.runner.set_model_fn(lambda p, m: "def add(a, b): return a + b")
        result = self.runner.run_task(
            BenchmarkTask(
                name="t",
                prompt="p",
                test_code="exec(output)\nassert add(1, 2) == 3\ntest_passed = True\n",
                eval_metric=EvalMetric.TESTS_PASS,
            ),
            "m",
            RunMode.RAW_MODEL,
        )
        self.assertTrue(result.passed)

    def test_eval_tests_fail(self):
        self.runner.set_model_fn(lambda p, m: "def add(a, b): return a - b")
        result = self.runner.run_task(
            BenchmarkTask(
                name="t",
                prompt="p",
                test_code="exec(output)\nassert add(1, 2) == 3\ntest_passed = True\n",
                eval_metric=EvalMetric.TESTS_PASS,
            ),
            "m",
            RunMode.RAW_MODEL,
        )
        self.assertFalse(result.passed)

    def test_eval_similarity(self):
        self.runner.set_model_fn(lambda p, m: "the quick brown fox")
        result = self.runner.run_task(
            BenchmarkTask(
                name="t",
                prompt="p",
                expected_output="the quick brown dog",
                eval_metric=EvalMetric.SIMILARITY,
            ),
            "m",
            RunMode.RAW_MODEL,
        )
        self.assertGreater(result.score, 0.5)

    def test_eval_code_quality(self):
        code = 'def greet(name):\n    """Greet someone."""\n    return f\'Hello {name}\'\n'
        self.runner.set_model_fn(lambda p, m: code)
        result = self.runner.run_task(
            BenchmarkTask(name="t", prompt="p", eval_metric=EvalMetric.CODE_QUALITY),
            "m",
            RunMode.RAW_MODEL,
        )
        self.assertGreater(result.score, 0.5)

    def test_eval_partial_credit(self):
        self.runner.set_model_fn(lambda p, m: "Here is a function:\ndef solve(): pass\nclass Solution: pass")
        result = self.runner.run_task(
            BenchmarkTask(
                name="t",
                prompt="p",
                expected_output="function solve class",
                eval_metric=EvalMetric.PARTIAL_CREDIT,
            ),
            "m",
            RunMode.RAW_MODEL,
        )
        self.assertGreater(result.score, 0.3)

    def test_run_suite(self):
        suite = BenchmarkSuite(name="mini")
        suite.add_task(
            BenchmarkTask(
                name="t1",
                prompt="p",
                eval_metric=EvalMetric.PASS_FAIL,
            )
        )
        suite.add_task(
            BenchmarkTask(
                name="t2",
                prompt="p",
                eval_metric=EvalMetric.PASS_FAIL,
            )
        )
        self.runner.set_model_fn(lambda p, m: "output")
        results = self.runner.run_suite(suite)
        self.assertEqual(len(results), 2)

    def test_get_and_clear_results(self):
        self.runner.set_model_fn(lambda p, m: "out")
        suite = BenchmarkSuite(name="s")
        suite.add_task(BenchmarkTask(name="t", prompt="p", eval_metric=EvalMetric.PASS_FAIL))
        self.runner.run_suite(suite)
        self.assertEqual(len(self.runner.get_results()), 1)
        self.runner.clear_results()
        self.assertEqual(len(self.runner.get_results()), 0)

    def test_no_model_fn_stub(self):
        result = self.runner.run_task(
            BenchmarkTask(name="t", prompt="p", eval_metric=EvalMetric.PASS_FAIL),
            "m",
            RunMode.RAW_MODEL,
        )
        self.assertIn("no model function", result.output)

    def test_duration_tracked(self):
        self.runner.set_model_fn(lambda p, m: "x")
        result = self.runner.run_task(
            BenchmarkTask(name="t", prompt="p", eval_metric=EvalMetric.PASS_FAIL),
            "m",
            RunMode.RAW_MODEL,
        )
        self.assertGreaterEqual(result.duration_ms, 0)

    def test_error_handling(self):
        def bad_fn(p, m):
            raise RuntimeError("model exploded")

        self.runner.set_model_fn(bad_fn)
        result = self.runner.run_task(
            BenchmarkTask(name="t", prompt="p", eval_metric=EvalMetric.PASS_FAIL),
            "m",
            RunMode.RAW_MODEL,
        )
        self.assertIn("model exploded", result.error)

    def test_retries_until_success(self):
        retry_runner = BenchmarkRunner(
            BenchmarkConfig(
                save_results=False,
                run_modes=[RunMode.RAW_MODEL],
                max_retries=2,
            )
        )
        attempts = {"count": 0}

        def flaky_fn(prompt, model):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise RuntimeError(f"transient failure {attempts['count']}")
            return "eventual success"

        retry_runner.set_model_fn(flaky_fn)
        result = retry_runner.run_task(
            BenchmarkTask(name="retry_task", prompt="p", eval_metric=EvalMetric.PASS_FAIL),
            "m",
            RunMode.RAW_MODEL,
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.error, "")
        self.assertEqual(attempts["count"], 3)
        self.assertEqual(result.eval_details["attempt_count"], 3)
        self.assertEqual(result.eval_details["retries_used"], 2)
        self.assertEqual(result.eval_details["attempts"][0]["status"], "error")
        self.assertEqual(result.eval_details["attempts"][-1]["status"], "ok")

    def test_retries_stop_after_limit(self):
        retry_runner = BenchmarkRunner(
            BenchmarkConfig(
                save_results=False,
                run_modes=[RunMode.RAW_MODEL],
                max_retries=1,
            )
        )
        attempts = {"count": 0}

        def always_fail(prompt, model):
            attempts["count"] += 1
            raise RuntimeError("still failing")

        retry_runner.set_model_fn(always_fail)
        result = retry_runner.run_task(
            BenchmarkTask(name="retry_fail", prompt="p", eval_metric=EvalMetric.PASS_FAIL),
            "m",
            RunMode.RAW_MODEL,
        )
        self.assertFalse(result.passed)
        self.assertIn("still failing", result.error)
        self.assertEqual(attempts["count"], 2)
        self.assertEqual(result.eval_details["attempt_count"], 2)
        self.assertEqual(result.eval_details["retries_used"], 1)
        self.assertEqual(result.eval_details["attempts"][-1]["status"], "error")

    def test_time_limit_enforced_after_attempt(self):
        timeout_runner = BenchmarkRunner(
            BenchmarkConfig(
                save_results=False,
                run_modes=[RunMode.RAW_MODEL],
                max_retries=3,
            )
        )
        attempts = {"count": 0}

        def slow_fn(prompt, model):
            attempts["count"] += 1
            time.sleep(0.02)
            return "too slow"

        timeout_runner.set_model_fn(slow_fn)
        result = timeout_runner.run_task(
            BenchmarkTask(
                name="timeout_task",
                prompt="p",
                eval_metric=EvalMetric.PASS_FAIL,
                time_limit_seconds=0.001,
            ),
            "m",
            RunMode.RAW_MODEL,
        )
        self.assertFalse(result.passed)
        self.assertIn("time limit", result.error.lower())
        self.assertEqual(attempts["count"], 1)
        self.assertTrue(result.eval_details["attempts"][0]["timed_out"])


class TestAmplificationScorer(unittest.TestCase):
    def _make_results(self):
        return [
            BenchmarkResult(
                task_id="t1", task_name="task1", model_name="m", run_mode=RunMode.RAW_MODEL, passed=False, score=0.3
            ),
            BenchmarkResult(
                task_id="t1", task_name="task1", model_name="m", run_mode=RunMode.THOMAS_FULL, passed=True, score=0.9
            ),
            BenchmarkResult(
                task_id="t2", task_name="task2", model_name="m", run_mode=RunMode.RAW_MODEL, passed=True, score=0.7
            ),
            BenchmarkResult(
                task_id="t2", task_name="task2", model_name="m", run_mode=RunMode.THOMAS_FULL, passed=True, score=0.8
            ),
        ]

    def test_score(self):
        scorer = AmplificationScorer()
        metrics = scorer.score(self._make_results())
        self.assertIn("overall", metrics)
        self.assertIn("task_analysis", metrics)
        self.assertGreater(metrics["overall"]["amplification_factor"], 1.0)

    def test_pass_rate_lift(self):
        scorer = AmplificationScorer()
        metrics = scorer.score(self._make_results())
        self.assertGreater(metrics["overall"]["pass_rate_lift"], 0)

    def test_task_analysis(self):
        scorer = AmplificationScorer()
        metrics = scorer.score(self._make_results())
        t = metrics["task_analysis"]
        self.assertEqual(t["total_tasks"], 2)
        self.assertEqual(t["improved"], 2)
        self.assertEqual(t["regressed"], 0)

    def test_per_task_deltas(self):
        scorer = AmplificationScorer()
        metrics = scorer.score(self._make_results())
        self.assertEqual(len(metrics["per_task"]), 2)
        self.assertTrue(metrics["per_task"][0]["improved"])

    def test_empty_results(self):
        scorer = AmplificationScorer()
        metrics = scorer.score([])
        self.assertIn("error", metrics)

    def test_missing_mode(self):
        scorer = AmplificationScorer()
        raw_only = [
            BenchmarkResult(task_id="t1", task_name="t", model_name="m", run_mode=RunMode.RAW_MODEL, score=0.5),
        ]
        metrics = scorer.score(raw_only)
        self.assertIn("error", metrics)

    def test_format_summary(self):
        scorer = AmplificationScorer()
        metrics = scorer.score(self._make_results())
        text = scorer.format_summary(metrics)
        self.assertIn("THOMAS AMPLIFICATION REPORT", text)
        self.assertIn("Amplification Factor", text)

    def test_format_summary_error(self):
        scorer = AmplificationScorer()
        text = scorer.format_summary({"error": "No data"})
        self.assertIn("Error", text)

    def test_by_model(self):
        scorer = AmplificationScorer()
        metrics = scorer.score(self._make_results())
        self.assertIn("m", metrics["by_model"])


class TestBenchmarkReport(unittest.TestCase):
    def _make_results(self):
        return [
            BenchmarkResult(
                task_id="t1",
                task_name="task1",
                model_name="gpt-4",
                run_mode=RunMode.RAW_MODEL,
                passed=True,
                score=0.8,
                duration_ms=100,
            ),
            BenchmarkResult(
                task_id="t1",
                task_name="task1",
                model_name="gpt-4",
                run_mode=RunMode.THOMAS_FULL,
                passed=True,
                score=0.95,
                duration_ms=200,
            ),
            BenchmarkResult(
                task_id="t2",
                task_name="task2",
                model_name="gpt-4",
                run_mode=RunMode.RAW_MODEL,
                passed=False,
                score=0.3,
                duration_ms=150,
            ),
        ]

    def test_create_report(self):
        report = BenchmarkReport()
        self.assertEqual(report.result_count, 0)

    def test_add_results(self):
        report = BenchmarkReport()
        report.add_results(self._make_results())
        self.assertEqual(report.result_count, 3)

    def test_summary(self):
        report = BenchmarkReport(self._make_results())
        s = report.summary()
        self.assertEqual(s["total_results"], 3)
        self.assertEqual(s["total_passed"], 2)
        self.assertGreater(s["overall_pass_rate"], 0)

    def test_summary_empty(self):
        report = BenchmarkReport()
        s = report.summary()
        self.assertIn("error", s)

    def test_to_text(self):
        report = BenchmarkReport(self._make_results())
        text = report.to_text()
        self.assertIn("THOMAS BENCHMARK REPORT", text)
        self.assertIn("Pass Rate", text)

    def test_to_json(self):
        report = BenchmarkReport(self._make_results())
        j = report.to_json()
        data = json.loads(j)
        self.assertEqual(data["report_type"], "thomas_benchmark")
        self.assertEqual(len(data["results"]), 3)
        generated_at = datetime.fromisoformat(data["generated_at"])
        self.assertIsNotNone(generated_at.tzinfo)

    def test_to_html(self):
        report = BenchmarkReport(self._make_results())
        html = report.to_html()
        self.assertIn("<html>", html)
        self.assertIn("Thomas Benchmark Report", html)
        self.assertIn("PASS", html)

    def test_save_text(self):
        report = BenchmarkReport(self._make_results())
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            path = f.name
        try:
            report.save(path, fmt="text")
            with open(path) as f:
                content = f.read()
            self.assertIn("THOMAS BENCHMARK REPORT", content)
        finally:
            os.unlink(path)

    def test_save_json(self):
        report = BenchmarkReport(self._make_results())
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            report.save(path, fmt="json")
            with open(path) as f:
                data = json.load(f)
            self.assertIn("results", data)
        finally:
            os.unlink(path)

    def test_comparison_table(self):
        report = BenchmarkReport(self._make_results())
        table = report.comparison_table()
        self.assertIn("Task", table)
        self.assertIn("Raw", table)
        self.assertIn("Thomas", table)

    def test_comparison_missing_mode(self):
        raw_only = [
            BenchmarkResult(task_id="t1", task_name="t", model_name="m", run_mode=RunMode.RAW_MODEL, score=0.5),
        ]
        report = BenchmarkReport(raw_only)
        table = report.comparison_table()
        self.assertIn("Need both", table)

    def test_clear(self):
        report = BenchmarkReport(self._make_results())
        report.clear()
        self.assertEqual(report.result_count, 0)

    def test_by_mode_summary(self):
        report = BenchmarkReport(self._make_results())
        s = report.summary()
        self.assertIn("raw_model", s["by_mode"])
        self.assertIn("thomas_full", s["by_mode"])


class TestSWEBenchSuite(unittest.TestCase):
    def test_create_suite(self):
        suite = create_swe_bench_suite()
        self.assertEqual(suite.name, "swe_bench")
        self.assertGreater(len(suite.tasks), 8)

    def test_has_categories(self):
        suite = create_swe_bench_suite()
        cats = suite.categories()
        self.assertIn("bug_fix", cats)
        self.assertIn("feature", cats)

    def test_tasks_have_prompts(self):
        suite = create_swe_bench_suite()
        for task in suite.tasks:
            self.assertTrue(len(task.prompt) > 10)


class TestLocalSWEBenchFixture(unittest.TestCase):
    def test_fixture_schema_renders_issue_prompt(self):
        fixture = create_local_swe_bench_fixture()
        data = fixture.to_dict()
        self.assertEqual(data["schema_version"], "local-swe-bench-v1")
        self.assertEqual(data["issue_id"], "local-zero-division-001")
        self.assertIn("finance_utils/metrics.py", data["base_files"])

        task = fixture.to_benchmark_task()
        self.assertEqual(task.category, "issue_patch")
        self.assertEqual(task.eval_metric, EvalMetric.FUNCTIONAL)
        self.assertEqual(task.metadata["issue_id"], fixture.issue_id)
        self.assertIn("Return a unified diff patch only", task.prompt)
        self.assertIn("pytest tests/test_metrics.py::test_percentage_zero_denominator", task.prompt)

    def test_fixture_rejects_unsafe_paths(self):
        with self.assertRaises(ValueError):
            LocalSWEBenchFixture(
                issue_id="bad",
                repository="local/bad",
                issue_title="bad path",
                issue_body="bad path",
                base_files={"../escape.py": "x = 1\n"},
                expected_files={"../escape.py": "x = 2\n"},
            )

    def test_score_swe_bench_patch_accepts_reference_patch(self):
        fixture = create_local_swe_bench_fixture()
        result = score_swe_bench_patch(fixture, fixture.reference_patch())
        self.assertTrue(result["passed"])
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(result["modified_files"], ["finance_utils/metrics.py"])

    def test_score_swe_bench_patch_rejects_incomplete_patch(self):
        fixture = create_local_swe_bench_fixture()
        result = score_swe_bench_patch(
            fixture,
            """--- a/finance_utils/metrics.py
+++ b/finance_utils/metrics.py
@@ -1,3 +1,3 @@
 def percentage(numerator, denominator):
     \"\"\"Return numerator as a percentage of denominator.\"\"\"
-    return round((numerator / denominator) * 100, 2)
+    return round((numerator / max(denominator, 1)) * 100, 2)
""",
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["mismatched_files"], ["finance_utils/metrics.py"])

    def test_local_swe_bench_suite_runs_through_benchmark_runner(self):
        fixture = create_local_swe_bench_fixture()
        suite = create_local_swe_bench_suite()
        runner = BenchmarkRunner(BenchmarkConfig(save_results=False, run_modes=[RunMode.RAW_MODEL]))
        runner.set_model_fn(lambda _prompt, _model: fixture.reference_patch())
        results = runner.run_suite(suite, models=["fixture-model"])
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0].passed)
        self.assertEqual(results[0].score, 1.0)


class TestHumanEvalSuite(unittest.TestCase):
    def test_create_suite(self):
        suite = create_humaneval_suite()
        self.assertEqual(suite.name, "humaneval")
        self.assertGreater(len(suite.tasks), 5)

    def test_all_have_test_code(self):
        suite = create_humaneval_suite()
        for task in suite.tasks:
            self.assertTrue(len(task.test_code) > 0)


class TestMBPPSuite(unittest.TestCase):
    def test_create_suite(self):
        suite = create_mbpp_suite()
        self.assertEqual(suite.name, "mbpp")
        self.assertGreater(len(suite.tasks), 10)

    def test_all_code_gen(self):
        suite = create_mbpp_suite()
        for task in suite.tasks:
            self.assertEqual(task.category, "code_gen")
            self.assertEqual(task.eval_metric, EvalMetric.TESTS_PASS)


class TestMATHSuite(unittest.TestCase):
    def test_create_suite(self):
        suite = create_math_suite()
        self.assertEqual(suite.name, "math")
        self.assertGreater(len(suite.tasks), 10)

    def test_has_math_categories(self):
        suite = create_math_suite()
        cats = suite.categories()
        self.assertIn("algebra", cats)
        self.assertIn("geometry", cats)

    def test_all_contains_eval(self):
        suite = create_math_suite()
        for task in suite.tasks:
            self.assertEqual(task.eval_metric, EvalMetric.CONTAINS)


class TestGSM8KSuite(unittest.TestCase):
    def test_create_suite(self):
        suite = create_gsm8k_suite()
        self.assertEqual(suite.name, "gsm8k")
        self.assertGreater(len(suite.tasks), 8)

    def test_all_word_problems(self):
        suite = create_gsm8k_suite()
        for task in suite.tasks:
            self.assertEqual(task.category, "word_problem")


class TestMTBenchSuite(unittest.TestCase):
    def test_create_suite(self):
        suite = create_mt_bench_suite()
        self.assertEqual(suite.name, "mt_bench")
        self.assertGreater(len(suite.tasks), 8)

    def test_has_categories(self):
        suite = create_mt_bench_suite()
        cats = suite.categories()
        self.assertIn("writing", cats)
        self.assertIn("reasoning", cats)
        self.assertIn("coding", cats)


class TestGPQASuite(unittest.TestCase):
    def test_create_suite(self):
        suite = create_gpqa_suite()
        self.assertEqual(suite.name, "gpqa")
        self.assertGreater(len(suite.tasks), 10)

    def test_has_science_categories(self):
        suite = create_gpqa_suite()
        cats = suite.categories()
        self.assertIn("physics", cats)
        self.assertIn("chemistry", cats)

    def test_has_expert_difficulty(self):
        suite = create_gpqa_suite()
        expert = suite.get_by_difficulty(TaskDifficulty.EXPERT)
        self.assertGreater(len(expert), 0)


class TestBigCodeSuite(unittest.TestCase):
    def test_create_suite(self):
        suite = create_bigcode_suite()
        self.assertEqual(suite.name, "bigcode_bench")
        self.assertGreater(len(suite.tasks), 5)

    def test_all_practical(self):
        suite = create_bigcode_suite()
        for task in suite.tasks:
            self.assertEqual(task.category, "practical_coding")
            self.assertTrue(len(task.test_code) > 0)


class TestAllSuitesTaskCount(unittest.TestCase):
    """Verify total task count across all suites."""

    def test_total_tasks(self):
        total = 0
        for create_fn in [
            create_swe_bench_suite,
            create_humaneval_suite,
            create_mbpp_suite,
            create_math_suite,
            create_gsm8k_suite,
            create_mt_bench_suite,
            create_gpqa_suite,
            create_bigcode_suite,
        ]:
            suite = create_fn()
            total += len(suite.tasks)
        self.assertGreater(total, 80, f"Expected 80+ tasks, got {total}")


if __name__ == "__main__":
    unittest.main()
