"""Adversarial contracts for honest, isolated Chat background completion."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, patch

from thomas.server import chat_delegation_exhaustive_runner, exhaustive_runtime
from thomas.server.chat_delegation_deliverable import _WorkerRetry
from thomas.server.chat_delegation_result_policy import worker_text_is_confirmed_answer
from thomas.server.chat_delegation_runner import _finalize_live_repo_completion


class TestStructuredWorkerTerminalGuard(unittest.TestCase):
    def test_terminal_answer_status_does_not_classify_claim_wording(self) -> None:
        prompt = "Mail the signed contract to the client."
        claim = ["Mailed the signed contract to the client."]
        self.assertTrue(worker_text_is_confirmed_answer(claim, prompt=prompt))
        self.assertTrue(
            worker_text_is_confirmed_answer(
                claim,
                prompt=prompt,
                succeeded_tools=["fs.read_file"],
                failed_tools=[],
            )
        )
        self.assertTrue(
            worker_text_is_confirmed_answer(
                claim,
                prompt=prompt,
                succeeded_tools=["email.send"],
                failed_tools=[],
            )
        )
        self.assertFalse(
            worker_text_is_confirmed_answer(
                claim,
                prompt=prompt,
                failed_tools=["email.send"],
            )
        )


class TestHiddenReviewAndRuntimeSettings(unittest.IsolatedAsyncioTestCase):
    async def test_live_repo_completion_fails_closed_when_proof_cannot_persist(self) -> None:
        emitter = SimpleNamespace(completed=AsyncMock(), failed=AsyncMock())
        bot = SimpleNamespace(name="Nova")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch(
                    "thomas.server.chat_delegation_runner._live_repo_files_changed_since",
                    return_value=["implementation.py"],
                ),
                patch(
                    "thomas.server.chat_delegation_runner._hidden_completion_review_passes",
                    return_value=True,
                ),
                patch(
                    "thomas.server.chat_delegation_runner.task_bot_runtime.attach_proof",
                    side_effect=OSError("secret ledger path"),
                ),
                patch("thomas.server.chat_delegation_runner.task_bot_runtime.complete_execution") as complete,
            ):
                with self.assertRaisesRegex(_WorkerRetry, "live-repo proof persistence failed"):
                    await _finalize_live_repo_completion(
                        emitter,
                        "exec-live-proof-fail",
                        root,
                        "Implement and test the fix.",
                        {},
                        ["Implemented the fix and verified it."],
                        ["fs.write_file", "shell.exec"],
                        ["fs.write_file", "shell.exec"],
                        [],
                        bot,
                        "coding",
                    )

        complete.assert_not_called()
        emitter.completed.assert_not_awaited()
        emitter.failed.assert_not_awaited()

    async def test_live_repo_worker_fails_closed_before_presentation_when_review_vetoes(self) -> None:
        emitter = SimpleNamespace(completed=AsyncMock(), failed=AsyncMock())
        bot = SimpleNamespace(name="Nova")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch(
                    "thomas.server.chat_delegation_runner._live_repo_files_changed_since",
                    return_value=["implementation.py"],
                ),
                patch(
                    "thomas.server.chat_delegation_runner._hidden_completion_review_passes",
                    return_value=False,
                ) as review,
                patch("thomas.server.chat_delegation_runner.task_bot_runtime.attach_proof") as attach,
                patch("thomas.server.chat_delegation_runner.task_bot_runtime.complete_execution") as complete,
            ):
                with self.assertRaisesRegex(_WorkerRetry, "hidden completion review failed"):
                    await _finalize_live_repo_completion(
                        emitter,
                        "exec-live",
                        root,
                        "Implement and test the fix.",
                        {},
                        ["Implemented the fix and verified it."],
                        ["fs.write_file", "shell.exec"],
                        ["fs.write_file", "shell.exec"],
                        [],
                        bot,
                        "coding",
                    )

        review.assert_called_once_with(
            "Implement and test the fix.",
            root,
            ["implementation.py"],
            ANY,
            True,
            [],
            succeeded_tools=["fs.write_file", "shell.exec"],
        )
        attach.assert_not_called()
        complete.assert_not_called()
        emitter.completed.assert_not_awaited()
        emitter.failed.assert_not_awaited()

    async def test_exhaustive_worker_preserves_memory_reasoning_and_economy_dials(self) -> None:
        captured: dict[str, object] = {}

        async def fake_worker_events(_app, **kwargs):  # noqa: ANN001, ANN003
            captured.update(kwargs)
            yield {
                "type": "model_runtime",
                "runtime": {
                    "requested": {"profile": "chatgpt", "provider": "fixture", "model": "gpt-5.6-sol"},
                    "active": {"profile": "chatgpt", "provider": "fixture", "model": "gpt-5.6-sol"},
                    "failover_enabled": False,
                    "failover_used": False,
                    "attempts": [
                        {
                            "profile": "chatgpt",
                            "provider": "fixture",
                            "model": "gpt-5.6-sol",
                            "status": "success",
                        }
                    ],
                },
            }
            text = (
                '{"score": 9, "veto": false, "reason": "verified"}'
                if str(kwargs.get("role") or "").startswith("reviewer-")
                else "Revenue rose 12 percent because volume increased. " * 4
            )
            yield {"type": "text", "text": text}
            yield {"type": "done"}

        with patch.object(exhaustive_runtime, "run_agent_worker_events", fake_worker_events):
            await exhaustive_runtime.run_exhaustive_pipeline(
                app={},
                prompt="Analyze revenue.",
                instructions="Return a verified analysis.",
                work_dir="",
                profile="chatgpt",
                model_id="gpt-5.6-sol",
                reasoning_effort="xhigh",
                effort="cheap",
                specialist_id="reasoning",
                memory_enabled=False,
            )

        self.assertEqual(captured["reasoning_effort"], "xhigh")
        self.assertEqual(captured["effort"], "cheap")
        self.assertIs(captured["memory_enabled"], False)

    async def test_max_runner_persists_every_pass_receipt_before_completion(self) -> None:
        record = {"state": "running", "runtime_profile": {}}
        emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())
        bot = SimpleNamespace(name="Nova")

        def runtime() -> dict:
            return {
                "requested": {"profile": "chatgpt", "provider": "fixture", "model": "gpt-5.6-sol"},
                "active": {"profile": "chatgpt", "provider": "fixture", "model": "gpt-5.6-sol"},
                "attempts": [
                    {
                        "profile": "chatgpt",
                        "provider": "fixture",
                        "model": "gpt-5.6-sol",
                        "status": "success",
                    }
                ],
                "api_key": "must-not-persist",
            }

        async def pipeline(_app, **kwargs):  # noqa: ANN001, ANN003
            for index, role in enumerate(("coding", "reviewer-correctness"), start=1):
                receipt = runtime()
                receipt.update(
                    {
                        "pass_id": f"max-pass-{index}",
                        "pass_kind": "crew_work" if index == 1 else "adversarial_review",
                        "role": role,
                        "agent_name": "Nova" if index == 1 else "Fresh correctness grader",
                    }
                )
                await kwargs["on_model_runtime"](receipt)
            return SimpleNamespace(
                aborted="",
                verified=True,
                review_passed=True,
                result="A complete, evidence-backed analysis with a direct answer.",
                rubric={"tools_required": False},
            )

        def update(_execution_id, **kwargs):  # noqa: ANN001, ANN003
            if "runtime_profile" in kwargs:
                record["runtime_profile"] = kwargs["runtime_profile"]
            if "progress_summary" in kwargs:
                record["progress_summary"] = kwargs["progress_summary"]
            return record

        def complete(_execution_id, **_kwargs):  # noqa: ANN001, ANN003
            record["state"] = "completed"
            return record

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(exhaustive_runtime, "run_exhaustive_pipeline", pipeline),
            patch.object(chat_delegation_exhaustive_runner.task_bot_runtime, "get_execution", return_value=record),
            patch.object(chat_delegation_exhaustive_runner.task_bot_runtime, "update_execution", side_effect=update),
            patch.object(
                chat_delegation_exhaustive_runner.task_bot_runtime, "complete_execution", side_effect=complete
            ),
            patch.object(chat_delegation_exhaustive_runner, "_snapshot_workspace_files", return_value=[]),
            patch.object(chat_delegation_exhaustive_runner, "worker_text_is_confirmed_answer", return_value=True),
        ):
            await chat_delegation_exhaustive_runner._run_exhaustive_worker(
                {},
                execution_id="exec-max",
                prompt="Analyze revenue.",
                specialist_id="reasoning",
                bot=bot,
                emitter=emitter,
                instructions="Analyze.",
                repo_root=Path(directory),
                profile="chatgpt",
                model_id="gpt-5.6-sol",
            )

        profile = record["runtime_profile"]
        self.assertEqual(profile["model_runtime_pass_count"], 2)
        self.assertEqual(len(profile["model_runtime_receipts"]), 2)
        self.assertEqual(
            [receipt["pass_id"] for receipt in profile["model_runtime_receipts"]],
            ["max-pass-1", "max-pass-2"],
        )
        self.assertIs(profile["max_answer_only"], True)
        self.assertEqual(
            profile["max_verified_answer_text"],
            "A complete, evidence-backed analysis with a direct answer.",
        )
        self.assertNotIn("must-not-persist", repr(profile))
        emitter.completed.assert_awaited_once()
        emitter.failed.assert_not_awaited()

    async def test_max_runner_never_overwrites_an_external_terminal_failure(self) -> None:
        record = {"state": "executing", "runtime_profile": {}}
        emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())
        bot = SimpleNamespace(name="Nova")

        async def pipeline(_app, **kwargs):  # noqa: ANN001, ANN003
            record["state"] = "failed"
            self.assertTrue(kwargs["should_cancel"]())
            raise asyncio.CancelledError

        fail_execution = AsyncMock()
        complete_execution = AsyncMock()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(exhaustive_runtime, "run_exhaustive_pipeline", pipeline),
            patch.object(chat_delegation_exhaustive_runner.task_bot_runtime, "get_execution", return_value=record),
            patch.object(
                chat_delegation_exhaustive_runner.task_bot_runtime,
                "is_cancel_requested",
                return_value=False,
            ),
            patch.object(
                chat_delegation_exhaustive_runner.task_bot_runtime,
                "fail_execution",
                fail_execution,
            ),
            patch.object(
                chat_delegation_exhaustive_runner.task_bot_runtime,
                "complete_execution",
                complete_execution,
            ),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await chat_delegation_exhaustive_runner._run_exhaustive_worker(
                    {},
                    execution_id="exec-max-terminal-race",
                    prompt="Analyze revenue.",
                    specialist_id="reasoning",
                    bot=bot,
                    emitter=emitter,
                    instructions="Analyze.",
                    repo_root=Path(directory),
                    profile="chatgpt",
                    model_id="gpt-5.6-sol",
                )

        fail_execution.assert_not_awaited()
        complete_execution.assert_not_awaited()
        emitter.completed.assert_not_awaited()
        emitter.failed.assert_not_awaited()

    async def test_max_runner_never_marks_artifacts_verified_when_proof_persistence_fails(self) -> None:
        record = {"state": "executing", "runtime_profile": {}}
        emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())
        bot = SimpleNamespace(name="Nova")

        async def pipeline(_app, **kwargs):  # noqa: ANN001, ANN003
            receipt = {
                "requested": {"profile": "chatgpt", "provider": "openai", "model": "gpt-5.6-sol"},
                "active": {"profile": "chatgpt", "provider": "openai", "model": "gpt-5.6-sol"},
                "attempts": [{"profile": "chatgpt", "provider": "openai", "model": "gpt-5.6-sol", "status": "success"}],
                "pass_id": "max-pass-1",
                "pass_kind": "crew_work",
                "role": "coding",
                "agent_name": "Nova",
            }
            await kwargs["on_model_runtime"](receipt)
            Path(kwargs["work_dir"]).joinpath("report.md").write_text("verified body", encoding="utf-8")
            return SimpleNamespace(
                aborted="",
                verified=True,
                review_passed=True,
                result="Created report.md.",
                rubric={"tools_required": True},
            )

        def update(_execution_id, **kwargs):  # noqa: ANN001, ANN003
            record.update(
                {key: value for key, value in kwargs.items() if key in {"runtime_profile", "progress_summary"}}
            )
            return record

        fallback = AsyncMock()
        complete = AsyncMock()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(exhaustive_runtime, "run_exhaustive_pipeline", pipeline),
            patch.object(chat_delegation_exhaustive_runner.task_bot_runtime, "get_execution", return_value=record),
            patch.object(chat_delegation_exhaustive_runner.task_bot_runtime, "update_execution", side_effect=update),
            patch.object(
                chat_delegation_exhaustive_runner.task_bot_runtime,
                "attach_proof",
                side_effect=OSError("proof ledger unavailable"),
            ),
            patch.object(chat_delegation_exhaustive_runner.task_bot_runtime, "complete_execution", complete),
            patch("thomas.server.chat_delegation_runner._run_agent_worker", fallback),
        ):
            await chat_delegation_exhaustive_runner._run_exhaustive_worker(
                {},
                execution_id="exec-proof-fail",
                prompt="Create report.md.",
                specialist_id="coding",
                bot=bot,
                emitter=emitter,
                instructions="Create and verify the report.",
                repo_root=Path(directory),
                work_dir=Path(directory),
                profile="chatgpt",
                model_id="gpt-5.6-sol",
            )

        complete.assert_not_awaited()
        emitter.completed.assert_not_awaited()
        fallback.assert_awaited_once()
        self.assertIs(record["runtime_profile"]["exhaustive_fallback"], True)

    async def test_max_fallback_is_recorded_and_announced(self) -> None:
        record = {"state": "running", "runtime_profile": {}}
        emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())
        bot = SimpleNamespace(name="Nova")

        async def pipeline(_app, **_kwargs):  # noqa: ANN001, ANN003
            try:
                raise RuntimeError("provider-secret-must-not-surface")
            except RuntimeError as cause:
                raise exhaustive_runtime.ExhaustivePassFailure(
                    "worker_reported_error",
                    pass_id="max-pass-2",
                    role="synthesis",
                ) from cause

        def update(_execution_id, **kwargs):  # noqa: ANN001, ANN003
            record.update(
                {key: value for key, value in kwargs.items() if key in {"runtime_profile", "progress_summary"}}
            )
            return record

        fallback = AsyncMock()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(exhaustive_runtime, "run_exhaustive_pipeline", pipeline),
            patch.object(chat_delegation_exhaustive_runner.task_bot_runtime, "get_execution", return_value=record),
            patch.object(chat_delegation_exhaustive_runner.task_bot_runtime, "update_execution", side_effect=update),
            patch("thomas.server.chat_delegation_runner._run_agent_worker", fallback),
        ):
            await chat_delegation_exhaustive_runner._run_exhaustive_worker(
                {},
                execution_id="exec-max-fallback",
                prompt="Analyze revenue.",
                specialist_id="reasoning",
                bot=bot,
                emitter=emitter,
                instructions="Analyze.",
                repo_root=Path(directory),
                profile="chatgpt",
                model_id="gpt-5.6-sol",
            )

        self.assertIs(record["runtime_profile"]["exhaustive_fallback"], True)
        self.assertEqual(record["runtime_profile"]["exhaustive_fallback_reason"], "worker_reported_error")
        self.assertEqual(
            record["runtime_profile"]["exhaustive_failed_pass"],
            {"pass_id": "max-pass-2", "role": "synthesis", "code": "worker_reported_error"},
        )
        self.assertNotIn("provider-secret", repr(record))
        emitter.progress.assert_awaited_once()
        fallback.assert_awaited_once()
        self.assertIn("not a Max-certified result", fallback.await_args.kwargs["instructions"])

    async def test_max_quality_veto_fails_instead_of_faking_a_downgraded_success(self) -> None:
        record = {"state": "running", "runtime_profile": {}}
        emitter = SimpleNamespace(progress=AsyncMock(), completed=AsyncMock(), failed=AsyncMock())
        bot = SimpleNamespace(name="Nova")

        async def pipeline(_app, **kwargs):  # noqa: ANN001, ANN003
            await kwargs["on_quality_review"](
                {
                    "cycle": 2,
                    "median_score": 5.0,
                    "passed": False,
                    "reviews": [{"lens": "correctness", "score": 4.0, "veto": False, "reason": "missing evidence"}],
                }
            )
            raise exhaustive_runtime.ExhaustiveQualityGateFailure("bounded review failed")

        def update(_execution_id, **kwargs):  # noqa: ANN001, ANN003
            if "runtime_profile" in kwargs:
                record["runtime_profile"] = kwargs["runtime_profile"]
            return record

        def fail(_execution_id, **kwargs):  # noqa: ANN001, ANN003
            record.update(
                {
                    "state": "failed",
                    "blocker": kwargs["blocker"],
                    "progress_summary": kwargs["summary"],
                }
            )
            return record

        fallback = AsyncMock()
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(exhaustive_runtime, "run_exhaustive_pipeline", pipeline),
            patch.object(chat_delegation_exhaustive_runner.task_bot_runtime, "get_execution", return_value=record),
            patch.object(chat_delegation_exhaustive_runner.task_bot_runtime, "update_execution", side_effect=update),
            patch.object(chat_delegation_exhaustive_runner.task_bot_runtime, "fail_execution", side_effect=fail),
            patch("thomas.server.chat_delegation_runner._run_agent_worker", fallback),
        ):
            await chat_delegation_exhaustive_runner._run_exhaustive_worker(
                {},
                execution_id="exec-max-veto",
                prompt="Analyze revenue.",
                specialist_id="reasoning",
                bot=bot,
                emitter=emitter,
                instructions="Analyze.",
                repo_root=Path(directory),
                profile="chatgpt",
                model_id="gpt-5.6-sol",
            )

        self.assertEqual(record["state"], "failed")
        self.assertEqual(record["blocker"], "max_quality_gates_failed")
        self.assertEqual(len(record["runtime_profile"]["exhaustive_quality_reviews"]), 1)
        fallback.assert_not_awaited()
        emitter.failed.assert_awaited_once()
        emitter.completed.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
