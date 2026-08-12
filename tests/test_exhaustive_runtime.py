"""Live wiring of the Exhaustive pipeline into the dispatch path (Step 8)."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from thomas.server import exhaustive_runtime as er
from thomas.server.chat_tool_policy import PolicyToolRegistryView, tool_policy_from_payload


def _runtime(model: str = "gpt-test", *, secret: str = "") -> dict:
    receipt = {
        "requested": {"profile": "local", "provider": "fixture", "model": model},
        "active": {"profile": "local", "provider": "fixture", "model": model},
        "attempts": [{"profile": "local", "provider": "fixture", "model": model, "status": "success"}],
    }
    if secret:
        receipt["api_key"] = secret
        receipt["base_url"] = f"https://example.test/?token={secret}"
    return receipt


def _verified_result(*_args, **_kwargs):  # noqa: ANN002, ANN003
    return SimpleNamespace(passed=True, checks=("ruff",))


class TestExhaustiveRouting(unittest.TestCase):
    def test_is_exhaustive(self):
        self.assertTrue(er.is_exhaustive("exhaustive"))
        self.assertTrue(er.is_exhaustive("max"))
        self.assertFalse(er.is_exhaustive("diligent"))
        self.assertFalse(er.is_exhaustive("brisk"))
        # exhaustive at the lowest autonomy couples down -> not exhaustive
        self.assertFalse(er.is_exhaustive("exhaustive", autonomy_level=1))

    def test_review_result_parser_fails_closed(self):
        self.assertEqual(
            er._parse_review_result('{"score": 8.5, "veto": false, "reason": "solid"}'), (8.5, False, "solid")
        )
        self.assertEqual(
            er._parse_review_result("score: '9.5', veto: false, reason: 'all criteria are covered'"),
            (9.5, False, "all criteria are covered"),
        )
        self.assertEqual(er._parse_review_result("not json"), (0.0, True, "grader returned invalid structured output"))
        self.assertEqual(
            er._parse_review_result("score: 10, veto: probably not, reason: 'looks good'"),
            (0.0, True, "grader returned invalid structured output"),
        )

    def test_prompt_tool_and_artifact_classifiers_are_removed(self):
        self.assertFalse(hasattr(er, "_task_needs_tools"))
        self.assertFalse(hasattr(er, "_task_needs_artifacts"))

    def test_artifact_evidence_reads_back_named_files_and_validates_pdf_header(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "chart.pdf").write_bytes(b"%PDF-1.7\nproof")
            (root / "chart-data.csv").write_text("Quarter,Value\nQ1,12\n", encoding="utf-8")

            passed, artifacts, issues = er._artifact_evidence(
                ["chart.pdf", "chart-data.csv"],
                directory,
            )

        self.assertTrue(passed)
        self.assertEqual(artifacts, ["chart-data.csv", "chart.pdf"])
        self.assertEqual(issues, [])

    def test_artifact_evidence_rejects_unsafe_structured_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "report.pdf").write_bytes(b"%PDF-1.7\nproof")
            passed, _artifacts, issues = er._artifact_evidence(["../report.pdf"], directory)

        self.assertFalse(passed)
        self.assertEqual(issues, ["invalid_expected_path"])


class TestRunExhaustivePipeline(unittest.IsolatedAsyncioTestCase):
    async def test_artifact_reviewers_receive_read_only_cloned_tool_policy(self):
        captured: list[dict] = []
        runtime_policy = {
            "tools": {
                "allow_shell": True,
                "allow_file_write": True,
                "allow_network": True,
                "allow_browser": True,
                "allow_channels": True,
                "allow_git": True,
                "allowed_paths": (".",),
            }
        }

        async def fake_worker_events(app, **kwargs):  # noqa: ANN001, ANN003
            captured.append(dict(kwargs))
            yield {"type": "model_runtime", "runtime": _runtime()}
            if str(kwargs.get("role") or "").startswith("reviewer-"):
                yield {"type": "text", "text": '{"score": 9, "veto": false, "reason": "verified"}'}
            else:
                Path(str(kwargs["work_dir"]), "report.pdf").write_bytes(b"%PDF-1.7\nproof")
                yield {"type": "text", "text": "Created report.pdf."}
            yield {"type": "done"}

        with (
            tempfile.TemporaryDirectory() as work_dir,
            patch.object(er, "run_agent_worker_events", fake_worker_events),
            patch.object(er.verification, "verify_deliverable", _verified_result),
        ):
            await er.run_exhaustive_pipeline(
                app={},
                prompt="Create a PDF report in report.pdf.",
                instructions="build",
                work_dir=work_dir,
                profile="local",
                model_id="gpt-test",
                effort="exhaustive",
                specialist_id="coding",
                file_access=2,
                runtime_policy=runtime_policy,
                expected_artifacts=["report.pdf"],
            )

        reviewer_calls = [call for call in captured if str(call.get("role") or "").startswith("reviewer-")]
        self.assertEqual(len(reviewer_calls), 3)
        for call in reviewer_calls:
            self.assertTrue(call["tools_enabled"])
            self.assertEqual(call["file_access"], 0)
            reviewer_tools = call["runtime_policy"]["tools"]
            self.assertEqual(reviewer_tools["allowed_paths"], (".",))
            self.assertTrue(
                all(
                    reviewer_tools[name] is False
                    for name in (
                        "allow_shell",
                        "allow_file_write",
                        "allow_network",
                        "allow_browser",
                        "allow_channels",
                        "allow_git",
                    )
                )
            )

        self.assertTrue(runtime_policy["tools"]["allow_file_write"])
        self.assertTrue(runtime_policy["tools"]["allow_network"])

        class ProbeRegistry:
            def __init__(self) -> None:
                self.tools = [
                    SimpleNamespace(name="fs.read_file", category="filesystem"),
                    SimpleNamespace(name="fs.write_file", category="filesystem"),
                    SimpleNamespace(name="create_skill", category="skills"),
                ]
                self.executed: list[str] = []

            def get(self, name: str):  # noqa: ANN201
                return next((tool for tool in self.tools if tool.name == name), None)

            def list_tools(self, _category=None):  # noqa: ANN001, ANN201
                return self.tools

            async def execute(self, name: str, _args: dict):  # noqa: ANN201
                self.executed.append(name)
                return SimpleNamespace(ok=True, error="")

        registry = ProbeRegistry()
        policy = tool_policy_from_payload(reviewer_calls[0]["runtime_policy"]["tools"])
        self.assertIsNotNone(policy)
        reviewer_view = PolicyToolRegistryView(registry, policy, base_root=work_dir)
        self.assertIsNotNone(reviewer_view.get("fs.read_file"))
        self.assertIsNone(reviewer_view.get("fs.write_file"))
        self.assertIsNone(reviewer_view.get("create_skill"))
        read_result = await reviewer_view.execute("fs.read_file", {"path": "report.pdf"})
        write_result = await reviewer_view.execute("fs.write_file", {"path": "report.pdf", "content": "changed"})
        skill_result = await reviewer_view.execute("create_skill", {"name": "mutating-reviewer"})
        self.assertTrue(read_result.ok)
        self.assertFalse(write_result.ok)
        self.assertFalse(skill_result.ok)
        self.assertEqual(registry.executed, ["fs.read_file"])

    async def test_runs_pipeline_with_real_worker_build(self):
        crew_prompts: list[str] = []

        async def fake_worker_events(app, **kwargs):  # noqa: ANN001, ANN003
            yield {"type": "model_runtime", "runtime": _runtime()}
            if str(kwargs.get("role") or "").startswith("reviewer-"):
                yield {"type": "text", "text": '{"score": 9, "veto": false, "reason": "verified"}'}
            else:
                crew_prompts.append(str(kwargs.get("prompt") or ""))
                Path(str(kwargs.get("work_dir"))).joinpath("game.html").write_text(
                    "<!doctype html><title>Snake</title>", encoding="utf-8"
                )
                yield {"type": "tool_start", "name": "fs.write_file"}
                yield {
                    "type": "text",
                    "text": f"{kwargs.get('role')} built a snake game in game.html. Main file: game.html for play.",
                }
            yield {"type": "done"}

        tools_seen: list[str] = []
        stages: list[str] = []

        async def on_tool(name: str) -> None:
            tools_seen.append(name)

        async def on_stage(event: dict) -> None:
            stages.append(event["stage"])

        receipts: list[dict] = []

        async def on_model_runtime(receipt: dict) -> None:
            receipts.append(receipt)

        with (
            tempfile.TemporaryDirectory() as work_dir,
            patch.object(er, "run_agent_worker_events", fake_worker_events),
            patch.object(er.verification, "verify_deliverable", _verified_result),
        ):
            ctx = await er.run_exhaustive_pipeline(
                app={},
                prompt="make me a snake game",
                instructions="build",
                work_dir=work_dir,
                profile="local",
                model_id="gpt-test",
                effort="exhaustive",
                specialist_id="coding",
                emit_stage=on_stage,
                on_tool=on_tool,
                on_model_runtime=on_model_runtime,
            )

        self.assertIn("game.html", ctx.result)
        self.assertNotIn("Trey (research):", ctx.result)
        self.assertIn("staff_crew", stages)
        self.assertIn("verify_review", stages)
        self.assertIn("deliver", stages)
        self.assertIn("fs.write_file", tools_seen)
        self.assertTrue(ctx.verified)
        self.assertTrue(ctx.review_passed)
        self.assertIs(ctx.rubric["tools_available"], True)
        self.assertIs(ctx.rubric["tools_required"], False)
        self.assertGreaterEqual(len(receipts), 4)
        self.assertIn("crew_work", {receipt["pass_kind"] for receipt in receipts})
        self.assertEqual(
            sum(receipt["pass_kind"] == "adversarial_review" for receipt in receipts),
            3,
        )
        self.assertGreaterEqual(len(crew_prompts), 2)
        self.assertIn("Prior crew result to audit and improve", crew_prompts[1])
        self.assertIn("snake game in game.html", crew_prompts[1])

    async def test_worker_error_propagates_for_fallback(self):
        async def boom(app, **kwargs):  # noqa: ANN001, ANN003
            yield {"type": "error", "error": "tool blew up"}

        with patch.object(er, "run_agent_worker_events", boom):
            with self.assertRaises(RuntimeError):
                await er.run_exhaustive_pipeline(
                    app={},
                    prompt="build me a feature",
                    instructions="build",
                    work_dir="",
                    profile="local",
                    model_id="gpt-test",
                    effort="exhaustive",
                    specialist_id="coding",
                )

    async def test_worker_runtime_exception_is_mapped_to_secret_safe_failure(self):
        async def boom(app, **kwargs):  # noqa: ANN001, ANN003
            yield {"type": "progress", "text": "provider started"}
            raise OSError("provider details must stay behind the receipt boundary")

        with patch.object(er, "run_agent_worker_events", boom):
            with self.assertRaisesRegex(er.ExhaustivePassFailure, "worker_runtime_exception") as caught:
                await er.run_exhaustive_pipeline(
                    app={},
                    prompt="build me a feature",
                    instructions="build",
                    work_dir="",
                    profile="local",
                    model_id="gpt-test",
                    effort="exhaustive",
                    specialist_id="coding",
                )

        self.assertEqual(caught.exception.exception_type, "OSError")
        self.assertNotIn("provider details", str(caught.exception))

    async def test_cancel_flag_stops_before_starting_another_model_pass(self):
        worker = MagicMock()
        with patch.object(er, "run_agent_worker_events", worker):
            with self.assertRaises(asyncio.CancelledError):
                await er.run_exhaustive_pipeline(
                    app={},
                    prompt="analyze",
                    instructions="analyze",
                    work_dir="",
                    profile="local",
                    model_id="gpt-test",
                    effort="exhaustive",
                    specialist_id="reasoning",
                    should_cancel=lambda: True,
                )

        worker.assert_not_called()

    async def test_forwards_self_development_runtime_dials_to_worker(self):
        captured: list[dict] = []

        async def fake_worker_events(app, **kwargs):  # noqa: ANN001, ANN003
            captured.append(dict(kwargs))
            yield {"type": "model_runtime", "runtime": _runtime("gpt-5.6-sol")}
            if str(kwargs.get("role") or "").startswith("reviewer-"):
                yield {"type": "text", "text": '{"score": 9, "veto": false, "reason": "verified"}'}
            else:
                yield {"type": "tool_start", "name": "fs.write_file"}
                yield {"type": "text", "text": "Changed my_stuff.script01.js and verified it."}
            yield {"type": "done"}

        with (
            patch.object(er, "run_agent_worker_events", fake_worker_events),
            patch.object(er.verification, "verify_deliverable", _verified_result),
        ):
            ctx = await er.run_exhaustive_pipeline(
                app={},
                prompt="fix Thomas in the live repo",
                instructions="build",
                work_dir="",
                profile="local",
                model_id="gpt-5.6-sol",
                reasoning_effort="max",
                effort="exhaustive",
                specialist_id="coding",
                autonomy_level=4,
                file_access=2,
                guardrails="guarded",
                job_type="self_development",
            )

        self.assertIn("my_stuff.script01.js", ctx.result)
        crew_call = next(call for call in captured if not str(call.get("role") or "").startswith("reviewer-"))
        self.assertEqual(crew_call["file_access"], 2)
        self.assertEqual(crew_call["guardrails"], "guarded")
        self.assertEqual(crew_call["job_type"], "self_development")
        self.assertEqual(crew_call["model_id"], "gpt-5.6-sol")
        self.assertEqual(crew_call["reasoning_effort"], "max")
        reviewer_calls = [call for call in captured if str(call.get("role") or "").startswith("reviewer-")]
        self.assertEqual(len(reviewer_calls), 3)
        self.assertTrue(all(call["file_access"] == 0 for call in reviewer_calls))
        self.assertTrue(all(call["tools_enabled"] is False for call in reviewer_calls))
        self.assertTrue(all("under 160 characters" in call["prompt"] for call in reviewer_calls))
        self.assertTrue(all("12 words or fewer" in call["prompt"] for call in reviewer_calls))

    async def test_requires_exactly_one_valid_runtime_receipt_per_pass(self):
        async def missing(app, **kwargs):  # noqa: ANN001, ANN003
            yield {"type": "text", "text": "Result without proof."}
            yield {"type": "done"}

        async def duplicate(app, **kwargs):  # noqa: ANN001, ANN003
            yield {"type": "model_runtime", "runtime": _runtime()}
            yield {"type": "model_runtime", "runtime": _runtime()}

        async def mismatch(app, **kwargs):  # noqa: ANN001, ANN003
            yield {"type": "model_runtime", "runtime": _runtime("wrong-model")}

        for worker, expected in (
            (missing, "missing"),
            (duplicate, "duplicate"),
            (mismatch, "invalid"),
        ):
            with self.subTest(expected=expected), patch.object(er, "run_agent_worker_events", worker):
                with self.assertRaisesRegex(RuntimeError, expected):
                    await er.run_exhaustive_pipeline(
                        app={},
                        prompt="analyze",
                        instructions="analyze",
                        work_dir="",
                        profile="local",
                        model_id="gpt-test",
                        effort="exhaustive",
                        specialist_id="reasoning",
                    )

    async def test_receipt_callback_is_secret_safe(self):
        secret = "TOP_SECRET_VALUE"
        received: list[dict] = []

        async def worker(app, **kwargs):  # noqa: ANN001, ANN003
            yield {"type": "model_runtime", "runtime": _runtime(secret=secret)}
            text = (
                '{"score": 9, "veto": false, "reason": "verified"}'
                if str(kwargs.get("role") or "").startswith("reviewer-")
                else "A substantive verified result. " * 4
            )
            yield {"type": "text", "text": text}
            yield {"type": "done"}

        async def on_model_runtime(receipt: dict) -> None:
            received.append(receipt)

        with (
            patch.object(er, "run_agent_worker_events", worker),
            patch.object(er.verification, "verify_deliverable", _verified_result),
        ):
            await er.run_exhaustive_pipeline(
                app={},
                prompt="analyze",
                instructions="analyze",
                work_dir="",
                profile="local",
                model_id="gpt-test",
                effort="exhaustive",
                specialist_id="reasoning",
                on_model_runtime=on_model_runtime,
            )

        self.assertGreaterEqual(len(received), 4)
        self.assertNotIn(secret, repr(received))
        self.assertTrue(all(receipt.get("pass_kind") and receipt.get("role") for receipt in received))

    async def test_failed_quality_gate_is_not_delivered_after_remediation_cap(self):
        receipts: list[dict] = []
        quality_reviews: list[dict] = []

        async def worker(app, **kwargs):  # noqa: ANN001, ANN003
            yield {"type": "model_runtime", "runtime": _runtime()}
            text = (
                '{"score": 9, "veto": false, "reason": "verified"}'
                if str(kwargs.get("role") or "").startswith("reviewer-")
                else "A substantive but invalid result. " * 4
            )
            yield {"type": "text", "text": text}
            yield {"type": "done"}

        async def on_model_runtime(receipt: dict) -> None:
            receipts.append(receipt)

        async def on_quality_review(review: dict) -> None:
            quality_reviews.append(review)

        failed = SimpleNamespace(passed=False, checks=("ruff",))
        with (
            patch.object(er, "run_agent_worker_events", worker),
            patch.object(er.verification, "verify_deliverable", return_value=failed),
        ):
            with self.assertRaisesRegex(RuntimeError, "quality gates failed"):
                await er.run_exhaustive_pipeline(
                    app={},
                    prompt="build feature",
                    instructions="build",
                    work_dir="workspace",
                    profile="local",
                    model_id="gpt-test",
                    effort="exhaustive",
                    specialist_id="coding",
                    on_model_runtime=on_model_runtime,
                    on_quality_review=on_quality_review,
                )

        kinds = [receipt["pass_kind"] for receipt in receipts]
        self.assertEqual(kinds.count("adversarial_review"), 9)
        self.assertGreaterEqual(kinds.count("crew_work"), 1)
        self.assertGreaterEqual(kinds.count("remediation"), 2)
        self.assertEqual([review["cycle"] for review in quality_reviews], [0, 1, 2])
        self.assertTrue(all(review["passed"] for review in quality_reviews))


if __name__ == "__main__":
    unittest.main()
