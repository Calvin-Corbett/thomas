import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from thomas.demo.agentic_benchmark import (
    _ensure_usage_telemetry,
    _estimate_text_tokens,
    _extract_reported_first_token_ms,
    _extract_usage_from_token_report,
    _pass_budget_for_mode,
    _pipeline_topology,
    _resolve_config_path,
    _review_decision_for_candidate,
    _run_thomas_api_task,
    _run_thomas_embedded_task,
    _safe_float,
    _select_elapsed_seconds,
    _select_optional_elapsed_seconds,
    _should_use_coding_pipeline,
    apply_template_context,
    compute_before_after_delta,
    evaluate_task_success,
    load_agentic_task_pack,
)


class _FakeHttpxResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        json_payload: dict | None = None,
        stream_lines: list[str] | None = None,
    ) -> None:
        self.status_code = int(status_code)
        self._json_payload = dict(json_payload or {})
        self._stream_lines = list(stream_lines or [])

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return dict(self._json_payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aiter_lines(self):
        for line in self._stream_lines:
            yield str(line)


class _FakeHttpxAsyncClient:
    def __init__(
        self,
        *,
        session_payload: dict | None = None,
        stream_lines: list[str] | None = None,
        status_code: int = 200,
    ) -> None:
        self._session_payload = dict(session_payload or {})
        self._stream_lines = list(stream_lines or [])
        self._status_code = int(status_code)
        self.post_calls: list[dict] = []
        self.stream_calls: list[dict] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, headers: dict | None = None):
        self.post_calls.append({"url": url, "headers": dict(headers or {})})
        return _FakeHttpxResponse(
            status_code=self._status_code,
            json_payload=self._session_payload,
        )

    def stream(
        self,
        method: str,
        url: str,
        *,
        headers: dict | None = None,
        json: dict | None = None,
    ):
        self.stream_calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers or {}),
                "json": dict(json or {}),
            }
        )
        return _FakeHttpxResponse(status_code=self._status_code, stream_lines=self._stream_lines)


class TestAgenticBenchmark(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmpdir.cleanup)
        self.tmp_path = Path(self._tmpdir.name)

    def test_apply_template_context_nested(self):
        payload = {
            "prompt": "write {{artifact_dir}}/out.txt",
            "success": {
                "required_files": ["{{artifact_dir}}/out.txt"],
                "required_file_contains": {"{{artifact_dir}}/out.txt": "ok"},
            },
        }
        out = apply_template_context(payload, {"artifact_dir": "runtime/bench/a"})
        self.assertEqual(out["prompt"], "write runtime/bench/a/out.txt")
        self.assertEqual(out["success"]["required_files"][0], "runtime/bench/a/out.txt")
        self.assertIn("runtime/bench/a/out.txt", out["success"]["required_file_contains"])
        self.assertEqual(out["success"]["required_file_contains"]["runtime/bench/a/out.txt"], "ok")

    def test_evaluate_task_success_checks_files_and_regex(self):
        artifact = self.tmp_path / "runtime" / "bench"
        artifact.mkdir(parents=True, exist_ok=True)
        target = artifact / "head.txt"
        target.write_text("abc1234\n", encoding="utf-8")

        task = {
            "success": {
                "response_contains": ["head.txt"],
                "required_files": ["runtime/bench/head.txt"],
                "required_file_regex": {"runtime/bench/head.txt": r"[0-9a-f]{7,40}"},
            }
        }
        result = evaluate_task_success(
            task,
            response_text="Done: head.txt abc1234",
            workspace_root=self.tmp_path,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["reasons"], [])

    def test_evaluate_task_success_python_compile_and_entry_point(self):
        task = {
            "success": {
                "response_python_compiles": True,
                "response_python_prefix": "def increment(n):\n",
                "response_entry_point": "increment",
            }
        }
        result = evaluate_task_success(
            task,
            response_text="    return n + 1\n",
            workspace_root=self.tmp_path,
        )
        self.assertTrue(result["success"])
        self.assertTrue(result["checks"]["response_python_compiles"])
        self.assertTrue(result["checks"]["response_entry_point:increment"])

    def test_evaluate_task_success_python_compile_failure(self):
        task = {
            "success": {
                "response_python_compiles": True,
                "response_python_prefix": "def broken(n):\n",
            }
        }
        result = evaluate_task_success(
            task,
            response_text="return n + 1",
            workspace_root=self.tmp_path,
        )
        self.assertFalse(result["success"])
        self.assertFalse(result["checks"]["response_python_compiles"])
        self.assertIn("response failed python compile check", result["reasons"])

    def test_load_agentic_task_pack_rejects_unknown_success_key(self):
        pack_path = self.tmp_path / "pack.json"
        pack_path.write_text(
            json.dumps(
                {
                    "id": "x",
                    "tasks": [
                        {
                            "id": "t1",
                            "title": "T",
                            "prompt": "P",
                            "success": {"made_up_check": "x"},
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(ValueError):
            load_agentic_task_pack(pack_path)

    def test_compute_before_after_delta(self):
        summary = {
            "competitors": {
                "baseline_raw": {
                    "weighted_score": 20.0,
                    "success_rate": 0.25,
                    "avg_elapsed_seconds": 40.0,
                    "evidence_coverage": 0.25,
                },
                "thomas_os": {
                    "weighted_score": 80.0,
                    "success_rate": 1.0,
                    "avg_elapsed_seconds": 55.0,
                    "evidence_coverage": 1.0,
                },
            }
        }
        delta = compute_before_after_delta(
            summary,
            baseline_name="baseline_raw",
            thomas_name="thomas_os",
        )
        self.assertAlmostEqual(delta["metrics"]["weighted_score_delta"], 60.0)
        self.assertAlmostEqual(delta["metrics"]["success_rate_delta"], 0.75)
        self.assertAlmostEqual(delta["metrics"]["avg_elapsed_seconds_delta"], 15.0)

    def test_resolve_config_path_prefers_repo_default_when_empty_and_no_env(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("THOMAS_CONFIG", None)
            out = _resolve_config_path("")
        self.assertIsNotNone(out)
        assert out is not None
        self.assertEqual(out.name, "thomas.toml")
        self.assertTrue(out.exists())

    def test_resolve_config_path_respects_explicit_arg(self):
        custom = self.tmp_path / "custom.toml"
        custom.write_text('default_model = "local"\n', encoding="utf-8")
        out = _resolve_config_path(str(custom))
        self.assertEqual(out, custom.resolve())

    def test_resolve_config_path_returns_none_when_env_is_set(self):
        with patch.dict(os.environ, {"THOMAS_CONFIG": str(self.tmp_path / "env.toml")}, clear=False):
            out = _resolve_config_path("")
        self.assertIsNone(out)

    def test_extract_usage_from_token_report_prefers_positive_fields(self):
        usage = _extract_usage_from_token_report(
            {
                "input_tokens": 120,
                "output_tokens": 45,
                "usage": {"total_tokens": 180},
            }
        )
        self.assertEqual(usage["prompt_tokens"], 120)
        self.assertEqual(usage["completion_tokens"], 45)
        self.assertEqual(usage["total_tokens"], 180)

    def test_ensure_usage_telemetry_uses_token_report_when_usage_missing(self):
        usage = _ensure_usage_telemetry(
            {},
            prompt_text="write a helper",
            response_text="def helper():\n    return 1\n",
            token_report={"input_tokens": 50, "output_tokens": 30},
        )
        self.assertEqual(usage["prompt_tokens"], 50)
        self.assertEqual(usage["completion_tokens"], 30)
        self.assertEqual(usage["total_tokens"], 80)

    def test_ensure_usage_telemetry_estimates_when_provider_returns_zero(self):
        prompt = "Implement fibonacci with memoization."
        response = "def fib(n):\n    return n if n < 2 else fib(n-1)+fib(n-2)\n"
        usage = _ensure_usage_telemetry(
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            prompt_text=prompt,
            response_text=response,
        )
        self.assertGreater(usage["prompt_tokens"], 0)
        self.assertGreater(usage["completion_tokens"], 0)
        self.assertEqual(usage["total_tokens"], usage["prompt_tokens"] + usage["completion_tokens"])

    def test_estimate_text_tokens_returns_zero_for_empty_and_positive_for_text(self):
        self.assertEqual(_estimate_text_tokens(""), 0)
        self.assertGreater(_estimate_text_tokens("tokenized text"), 0)

    def test_select_elapsed_seconds_prefers_reported_ms_when_present(self):
        elapsed = _select_elapsed_seconds(reported_elapsed_ms=812, fallback_elapsed_seconds=2.7)
        self.assertEqual(elapsed, 0.812)

    def test_select_elapsed_seconds_falls_back_when_report_missing(self):
        elapsed = _select_elapsed_seconds(reported_elapsed_ms=None, fallback_elapsed_seconds=1.23456)
        self.assertEqual(elapsed, 1.235)

    def test_safe_float_rejects_non_finite_values(self):
        self.assertEqual(_safe_float("1.25"), 1.25)
        self.assertIsNone(_safe_float("not-a-number"))
        self.assertIsNone(_safe_float(float("nan")))
        self.assertIsNone(_safe_float(float("inf")))

    def test_select_optional_elapsed_seconds_prefers_reported_and_allows_missing(self):
        self.assertEqual(
            _select_optional_elapsed_seconds(reported_elapsed_ms="125", fallback_elapsed_seconds=3.0),
            0.125,
        )
        self.assertEqual(
            _select_optional_elapsed_seconds(reported_elapsed_ms="oops", fallback_elapsed_seconds=2.3456),
            2.346,
        )
        self.assertIsNone(_select_optional_elapsed_seconds(reported_elapsed_ms="oops", fallback_elapsed_seconds=None))

    def test_extract_reported_first_token_ms_supports_event_and_token_report_keys(self):
        self.assertEqual(
            _extract_reported_first_token_ms({"first_token_ms": "210"}, token_report={}),
            210.0,
        )
        self.assertEqual(
            _extract_reported_first_token_ms(
                {},
                token_report={"ttft_ms": "160"},
            ),
            160.0,
        )
        self.assertIsNone(_extract_reported_first_token_ms({}, token_report={}))

    def test_pass_budget_for_mode(self):
        self.assertEqual(_pass_budget_for_mode("fast"), 1)
        self.assertEqual(_pass_budget_for_mode("auto"), 2)
        self.assertEqual(_pass_budget_for_mode("thinking"), 3)
        self.assertEqual(_pass_budget_for_mode("unknown"), 2)

    def test_pipeline_topology_by_token_economy(self):
        self.assertEqual(_pipeline_topology("cheap"), "coder_only")
        self.assertEqual(_pipeline_topology("optimal"), "coder_reviewer_conditional_fixer")
        self.assertEqual(_pipeline_topology("max"), "coder_reviewer_parallel_conditional_fixer")

    def test_should_use_coding_pipeline_for_job_type_or_prompt_signal(self):
        self.assertTrue(_should_use_coding_pipeline(job_type="benchmark", prompt="hello"))
        self.assertTrue(_should_use_coding_pipeline(job_type="general", prompt="fix bug in app.py"))
        self.assertFalse(_should_use_coding_pipeline(job_type="general", prompt="summarize this paragraph"))

    def test_review_decision_skips_when_candidate_looks_healthy(self):
        decision = _review_decision_for_candidate(
            candidate_text="def solve(n):\n    return n + 1\n",
            prompt="Write a python function.",
            mode="thinking",
            token_economy="max",
        )
        self.assertFalse(decision["required"])
        self.assertEqual(decision["reason"], "coder_output_looks_healthy")

    def test_review_decision_requires_when_candidate_signals_uncertainty(self):
        decision = _review_decision_for_candidate(
            candidate_text="I am not sure this is correct, maybe try this approach.",
            prompt="Fix this python code.",
            mode="thinking",
            token_economy="max",
        )
        self.assertTrue(decision["required"])
        self.assertEqual(decision["reason"], "low_confidence_language")

    def test_embedded_task_skips_reviewer_when_decision_not_required(self):
        async def _fake_single_lane(*args, **kwargs):
            return {
                "ok": True,
                "text": "def solve(n):\n    return n + 1\n",
                "error": "",
                "usage": {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
                "tool_calls": 0,
                "token_report": {},
                "elapsed_seconds": 0.03,
            }

        async def _unexpected_reviewer(*args, **kwargs):
            raise AssertionError("reviewer/fixer lane should not run for healthy candidate output")

        with (
            patch("thomas.demo.agentic_benchmark._run_single_agent_lane", new=_fake_single_lane),
            patch("thomas.demo.agentic_benchmark._chat_json_lane", new=_unexpected_reviewer),
        ):
            result = asyncio.run(
                _run_thomas_embedded_task(
                    config=None,  # type: ignore[arg-type]
                    profile="codex",
                    prompt="Write a python function.",
                    mode="thinking",
                    token_economy="max",
                    max_iterations=1,
                    job_type="benchmark",
                )
            )

        self.assertTrue(result["ok"])
        pipeline = dict(result.get("token_report", {}).get("pipeline", {}))
        self.assertFalse(pipeline.get("review_triggered"))
        self.assertEqual(pipeline.get("review_trigger_reason"), "coder_output_looks_healthy")
        self.assertEqual(list(pipeline.get("review_rounds") or []), [])

    def test_embedded_task_triggers_reviewer_on_low_confidence_candidate(self):
        async def _fake_single_lane(*args, **kwargs):
            return {
                "ok": True,
                "text": "I am not sure this is correct, maybe this works:\nreturn n + 1",
                "error": "",
                "usage": {"prompt_tokens": 9, "completion_tokens": 5, "total_tokens": 14},
                "tool_calls": 0,
                "token_report": {},
                "elapsed_seconds": 0.02,
            }

        reviewer_calls: list[str] = []

        async def _fake_chat_lane(*args, **kwargs):
            reviewer_calls.append(str(kwargs.get("system_prompt") or ""))
            return {
                "ok": True,
                "text": '{"pass": true, "issues": [], "summary": "looks good"}',
                "error": "",
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
                "elapsed_seconds": 0.01,
            }

        with (
            patch("thomas.demo.agentic_benchmark._run_single_agent_lane", new=_fake_single_lane),
            patch("thomas.demo.agentic_benchmark._chat_json_lane", new=_fake_chat_lane),
        ):
            result = asyncio.run(
                _run_thomas_embedded_task(
                    config=None,  # type: ignore[arg-type]
                    profile="codex",
                    prompt="Write a python function.",
                    mode="thinking",
                    token_economy="max",
                    max_iterations=1,
                    job_type="benchmark",
                )
            )

        self.assertTrue(result["ok"])
        self.assertEqual(len(reviewer_calls), 1)
        self.assertIn("strict code reviewer", reviewer_calls[0])
        pipeline = dict(result.get("token_report", {}).get("pipeline", {}))
        self.assertTrue(pipeline.get("review_triggered"))
        self.assertEqual(pipeline.get("review_trigger_reason"), "low_confidence_language")
        self.assertEqual(len(list(pipeline.get("review_rounds") or [])), 1)

    def test_run_thomas_api_task_uses_reported_elapsed_and_usage_fallback(self):
        stream_lines = [
            json.dumps(
                {
                    "type": "done",
                    "response": "final answer",
                    "run_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    "token_report": {"input_tokens": 40, "output_tokens": 12},
                    "elapsed_ms": "812",
                    "first_token_ms": "120",
                    "tool_calls": 2,
                }
            )
        ]
        fake_client = _FakeHttpxAsyncClient(
            session_payload={"session_id": "sess-123"},
            stream_lines=stream_lines,
        )

        with patch("thomas.demo.agentic_benchmark.httpx.AsyncClient", new=lambda *args, **kwargs: fake_client):
            result = asyncio.run(
                _run_thomas_api_task(
                    api_base="https://thomas.local",
                    api_token="secret-token",
                    profile="local",
                    prompt="write tests",
                    mode="auto",
                    token_economy="optimal",
                    max_iterations=6,
                )
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "final answer")
        self.assertEqual(result["usage"]["prompt_tokens"], 40)
        self.assertEqual(result["usage"]["completion_tokens"], 12)
        self.assertEqual(result["usage"]["total_tokens"], 52)
        self.assertEqual(result["elapsed_seconds"], 0.812)
        self.assertEqual(result["reported_elapsed_ms"], 812.0)
        self.assertEqual(result["first_token_seconds"], 0.12)
        self.assertEqual(result["reported_first_token_ms"], 120.0)
        self.assertEqual(result["stream_event_count"], 1)
        self.assertEqual(result["text_event_count"], 0)
        self.assertEqual(fake_client.post_calls[0]["headers"]["Authorization"], "Bearer secret-token")
        self.assertEqual(fake_client.stream_calls[0]["json"]["max_iterations"], 6)

    def test_run_thomas_api_task_handles_invalid_elapsed_and_text_fallback(self):
        stream_lines = [
            json.dumps({"type": "text", "text": "partial"}),
            json.dumps(
                {
                    "type": "swarm_done",
                    "final": "",
                    "run_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    "token_report": {},
                    "elapsed_ms": "bad-ms",
                }
            ),
        ]
        fake_client = _FakeHttpxAsyncClient(
            session_payload={"session_id": "sess-456"},
            stream_lines=stream_lines,
        )

        with patch("thomas.demo.agentic_benchmark.httpx.AsyncClient", new=lambda *args, **kwargs: fake_client):
            result = asyncio.run(
                _run_thomas_api_task(
                    api_base="https://thomas.local",
                    api_token="",
                    profile="local",
                    prompt="return partial",
                    mode="swarm",
                    token_economy="max",
                    max_iterations=None,
                )
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], "partial")
        self.assertIsNone(result["reported_elapsed_ms"])
        self.assertIsNone(result["reported_first_token_ms"])
        self.assertGreaterEqual(result["elapsed_seconds"], 0.0)
        self.assertIsNotNone(result["first_token_seconds"])
        self.assertGreaterEqual(result["first_token_seconds"], 0.0)
        self.assertEqual(result["stream_event_count"], 2)
        self.assertEqual(result["text_event_count"], 1)
        self.assertGreater(result["usage"]["total_tokens"], 0)
        self.assertNotIn("Authorization", fake_client.post_calls[0]["headers"])


if __name__ == "__main__":
    unittest.main()
