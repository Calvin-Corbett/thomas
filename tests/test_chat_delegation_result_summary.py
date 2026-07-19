"""Tests for the verified deliverable manifest reported back to chat.

The result a user sees for a finished task must name the REAL files the worker
wrote (sourced from disk), not the worker's last sentence of reasoning, and must
never claim a file that isn't there.
"""

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from thomas.server.chat_delegation import (
    _build_result_summary,
    _claimed_filenames,
    _files_changed_since,
    _resolve_created,
    _snapshot_workspace_files,
    _WorkerRetry,
    _workspace_mtimes,
)
from thomas.server.chat_delegation_runner import _finalize_worker_completion, _worker_text_is_confirmed_answer


class TestWorkspaceSnapshot(unittest.TestCase):
    def test_lists_real_files_only(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "livecheck.txt").write_text("hi", encoding="utf-8")
            (base / "sub").mkdir()
            (base / "sub" / "index.html").write_text("<html>", encoding="utf-8")
            (base / ".hidden").write_text("x", encoding="utf-8")
            files = _snapshot_workspace_files(base)
            self.assertIn("livecheck.txt", files)
            self.assertIn("sub/index.html", files)
            self.assertNotIn(".hidden", files)  # dot/hidden files excluded

    def test_missing_or_none_dir_is_empty(self):
        self.assertEqual(_snapshot_workspace_files(None), [])
        self.assertEqual(_snapshot_workspace_files(Path(tempfile.gettempdir()) / "no_such_ws_xyz123"), [])

    def test_workspace_mtimes_prunes_ignored_live_repo_trees(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "thomas").mkdir()
            (base / "thomas" / "server.py").write_text("print('ok')", encoding="utf-8")
            (base / "node_modules" / "pkg").mkdir(parents=True)
            (base / "node_modules" / "pkg" / "index.js").write_text("heavy", encoding="utf-8")
            (base / "runtime" / "coordination").mkdir(parents=True)
            (base / "runtime" / "coordination" / "exec.json").write_text("{}", encoding="utf-8")
            (base / "output").mkdir()
            (base / "output" / "proof.png").write_text("generated", encoding="utf-8")

            mtimes = _workspace_mtimes(
                base,
                ignored_prefixes=("runtime/", "output/"),
                ignored_parts=frozenset({"node_modules"}),
            )

        self.assertIn("thomas/server.py", mtimes)
        self.assertNotIn("node_modules/pkg/index.js", mtimes)
        self.assertNotIn("runtime/coordination/exec.json", mtimes)
        self.assertNotIn("output/proof.png", mtimes)


class TestResultSummary(unittest.TestCase):
    def test_acknowledgement_only_text_is_not_completion_evidence(self):
        for text in (
            "Got it.",
            "Okay",
            "Done",
            "Confirmed!",
            "On it",
            "Sure — I'll take care of that",
            "On it — I'll get started",
            "Got it, I'll handle this now",
            "Done — I will take care of that",
            "Done — I'll get started",
            "I'll handle it now.",
            "I will get started.",
            "I'll create the report.",
            "Let me start working on it.",
            "We're working on it now.",
            "I am working on it now.",
            "The answer will be 4 shortly.",
            "The completed analysis will be available shortly.",
            "Your summary is forthcoming.",
            "I have the explanation ready; I will provide it next.",
            "The answer is coming in the next message.",
            "Analysis complete. Details to follow.",
            "More to come.",
            "Continued in my next response.",
            "Please wait for the result.",
            "Stand byâ€”the answer follows.",
            "The result follows in a moment.",
            "I am almost done.",
            "Working on it now; answer soon.",
            "Answer pending.",
            "Still working.",
            "Processing the request.",
            "Hold on.",
            "One moment.",
            "To be continued.",
            "Drafting the answer now.",
            "The response is not ready yet.",
            "No final answer yet.",
            "Pending completion.",
            "Calculating\u2026",
            "Status: pending.",
            "Awaiting final response.",
            "Queued.",
            "In progress.",
            "Work in progress.",
            "Not yet complete.",
            "TBD.",
            "Coming up next.",
            "I\u2019ll be right back.",
            "Still processing.",
            "Response pending review.",
            "...",
            "\u2014",
            "No answer provided.",
            "Nothing to report yet.",
            "Waiting.",
            "Loading.",
            "Starting.",
            "Finishing up.",
            "Complete soon.",
            "[pending]",
            "(processing)",
            "Task complete.",
            "Ready.",
            "Finished.",
            "Success.",
            "STATUS: FINISHED!",
        ):
            self.assertFalse(_worker_text_is_confirmed_answer([text]), text)

    def test_substantive_answer_text_remains_completion_evidence(self):
        self.assertTrue(_worker_text_is_confirmed_answer(["The verified answer is 42."]))
        self.assertTrue(
            _worker_text_is_confirmed_answer(
                ["Analysis complete. Full details below: revenue rose 12 percent because volume increased."]
            )
        )
        self.assertTrue(
            _worker_text_is_confirmed_answer(
                ["The answer follows from the calculation: 4."], prompt="Analyze Q1 revenue."
            )
        )
        self.assertTrue(
            _worker_text_is_confirmed_answer(
                ["The analysis follows the requested framework: revenue rose 12 percent."],
                prompt="Analyze Q1 revenue.",
            )
        )
        self.assertTrue(_worker_text_is_confirmed_answer(["Done — the verified answer is 42."]))
        self.assertFalse(
            _worker_text_is_confirmed_answer(
                ["The playable game features arrow controls, scoring, and a restart button."],
                prompt="Create a playable game",
            )
        )

    def test_action_requests_require_matching_successful_tool_receipts(self):
        cases = (
            ("Deploy the site to production.", "Production is live now."),
            ("Email the signed report to Pat.", "The report is on its way to Pat."),
            ("Restart the API server.", "Restart complete; the API is healthy."),
            ("Purchase the standard plan.", "Your order is confirmed."),
            ("Install the analytics package.", "Installation complete."),
            ("Mail the signed contract to the client.", "Mailed the signed contract to the client."),
            ("Create a new customer account in the CRM.", "Created the new customer account in the CRM."),
        )
        for prompt, prose in cases:
            with self.subTest(prompt=prompt):
                self.assertFalse(_worker_text_is_confirmed_answer([prose], prompt=prompt))
                summary = _build_result_summary([prose], [], [], prompt=prompt)
                self.assertIn("not independently verified", summary.lower())

        self.assertTrue(
            _worker_text_is_confirmed_answer(
                ["The package installation completed."],
                prompt="Install the analytics package.",
                succeeded_tools=["package.install"],
                failed_tools=[],
            )
        )

    def test_action_explanations_and_negations_remain_informational(self):
        self.assertTrue(
            _worker_text_is_confirmed_answer(
                ["Use a staged rollout with a health check before promotion."],
                prompt="Explain how to deploy safely; do not deploy anything.",
            )
        )
        for prompt in (
            "Create a QA plan.",
            "Create a plan for testing file access.",
            "Create a message draft.",
            "Create an email draft.",
        ):
            with self.subTest(prompt=prompt):
                self.assertTrue(
                    _worker_text_is_confirmed_answer(
                        ["Here is the requested text with concrete steps and details."],
                        prompt=prompt,
                    )
                )

    def test_names_created_file(self):
        summary = _build_result_summary(["I made the file."], ["fs.write_file"], ["livecheck.txt"])
        self.assertIn("Created livecheck.txt", summary)

    def test_appends_worker_context_when_distinct(self):
        summary = _build_result_summary(["All set — it prints the date."], [], ["clock.py"])
        self.assertIn("Created clock.py", summary)
        self.assertIn("prints the date", summary)

    def test_suppresses_redundant_worker_line(self):
        summary = _build_result_summary(["Created livecheck.txt"], [], ["livecheck.txt"])
        self.assertEqual(summary, "Created livecheck.txt.")

    def test_no_files_falls_back_to_worker_line(self):
        summary = _build_result_summary(["Here is the answer: 42."], ["web.search"], [])
        self.assertEqual(summary, "Here is the answer: 42.")


class TestCompletionEvidenceGate(unittest.IsolatedAsyncioTestCase):
    async def test_artifact_completion_fails_closed_when_proof_cannot_persist(self) -> None:
        emitter = SimpleNamespace(completed=AsyncMock(), failed=AsyncMock())
        bot = SimpleNamespace(name="Nova")
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            (work / "index.html").write_text("<!doctype html><title>Proof</title>", encoding="utf-8")
            with (
                patch("thomas.server.chat_delegation_runner.render_report_pdfs", return_value=[]),
                patch("thomas.server.chat_delegation_runner.runtime_executability_warning", return_value=""),
                patch("thomas.server.chat_delegation_runner._hidden_completion_review_passes", return_value=True),
                patch(
                    "thomas.server.chat_delegation_runner.task_bot_runtime.attach_proof",
                    side_effect=OSError("secret ledger path"),
                ),
                patch("thomas.server.chat_delegation_runner.task_bot_runtime.complete_execution") as complete,
            ):
                with self.assertRaisesRegex(_WorkerRetry, "artifact proof persistence failed"):
                    await _finalize_worker_completion(
                        emitter,
                        "exec-proof-fail",
                        work,
                        "Create index.html.",
                        {},
                        ["Created index.html."],
                        ["fs.write_file"],
                        ["fs.write_file"],
                        [],
                        {},
                        bot,
                        "coding",
                        None,
                    )

        complete.assert_not_called()
        emitter.completed.assert_not_awaited()
        emitter.failed.assert_not_awaited()

    async def test_standard_worker_hidden_review_runs_before_terminal_presentation(self) -> None:
        order: list[str] = []
        emitter = SimpleNamespace(
            completed=AsyncMock(side_effect=lambda *_args, **_kwargs: order.append("present")),
            failed=AsyncMock(),
        )
        bot = SimpleNamespace(name="Nova")
        with tempfile.TemporaryDirectory() as d:
            with (
                patch(
                    "thomas.server.chat_delegation_runner._hidden_completion_review_passes",
                    side_effect=lambda *_args, **_kwargs: order.append("review") or True,
                ),
                patch(
                    "thomas.server.chat_delegation_runner.task_bot_runtime.complete_execution",
                    side_effect=lambda *_args, **_kwargs: {
                        "execution_id": "exec-answer",
                        "state": "completed",
                        "proof_status": "verified",
                    },
                ),
                patch("thomas.server.chat_delegation_runner.runtime_executability_warning", return_value=""),
            ):
                await _finalize_worker_completion(
                    emitter,
                    "exec-answer",
                    Path(d),
                    "Analyze the result.",
                    {},
                    ["Revenue increased 12 percent because volume grew."],
                    [],
                    [],
                    [],
                    {},
                    bot,
                    "reasoning",
                    None,
                )

        self.assertEqual(order, ["review", "present"])
        emitter.failed.assert_not_awaited()

    async def test_deliverable_prose_without_artifact_does_not_verify_task(self) -> None:
        emitter = SimpleNamespace(completed=AsyncMock(), failed=AsyncMock())
        bot = SimpleNamespace(name="Nova")
        with tempfile.TemporaryDirectory() as d:
            with (
                patch(
                    "thomas.server.chat_delegation_runner.task_bot_runtime.complete_execution",
                    return_value={"execution_id": "exec-game", "state": "failed", "proof_status": "missing"},
                ) as complete,
                patch("thomas.server.chat_delegation_runner.runtime_executability_warning", return_value=""),
            ):
                await _finalize_worker_completion(
                    emitter,
                    "exec-game",
                    Path(d),
                    "Create a playable game",
                    {},
                    ["The playable game features arrow controls, scoring, and a restart button."],
                    [],
                    [],
                    [],
                    {},
                    bot,
                    "coding",
                    None,
                )
        self.assertFalse(complete.call_args.kwargs["verified_success"])
        emitter.completed.assert_not_awaited()
        emitter.failed.assert_awaited_once()

    async def test_successful_read_tool_and_promise_do_not_verify_task(self) -> None:
        emitter = SimpleNamespace(completed=AsyncMock(), failed=AsyncMock())
        bot = SimpleNamespace(name="Nova")
        with tempfile.TemporaryDirectory() as d:
            with (
                patch(
                    "thomas.server.chat_delegation_runner.task_bot_runtime.complete_execution",
                    return_value={"execution_id": "exec-read", "state": "failed", "proof_status": "missing"},
                ) as complete,
                patch("thomas.server.chat_delegation_runner.runtime_executability_warning", return_value=""),
            ):
                await _finalize_worker_completion(
                    emitter,
                    "exec-read",
                    Path(d),
                    "Read the file and answer the question",
                    {},
                    ["Got it, I'll handle this now"],
                    ["fs.read_file"],
                    ["fs.read_file"],
                    [],
                    {},
                    bot,
                    "reasoning",
                    None,
                )
        self.assertFalse(complete.call_args.kwargs["verified_success"])
        emitter.completed.assert_not_awaited()
        emitter.failed.assert_awaited_once()

    async def test_action_prose_with_empty_workspace_and_no_receipt_fails_closed(self) -> None:
        emitter = SimpleNamespace(completed=AsyncMock(), failed=AsyncMock())
        bot = SimpleNamespace(name="Nova")
        with tempfile.TemporaryDirectory() as d:
            with (
                patch(
                    "thomas.server.chat_delegation_runner.task_bot_runtime.complete_execution",
                    return_value={"execution_id": "exec-deploy", "state": "failed", "proof_status": "missing"},
                ) as complete,
                patch("thomas.server.chat_delegation_runner.runtime_executability_warning", return_value=""),
            ):
                await _finalize_worker_completion(
                    emitter,
                    "exec-deploy",
                    Path(d),
                    "Deploy the site to production.",
                    {},
                    ["Production is live now."],
                    [],
                    [],
                    [],
                    {},
                    bot,
                    "tools",
                    None,
                )

        self.assertFalse(complete.call_args.kwargs["verified_success"])
        self.assertIn("not independently verified", complete.call_args.kwargs["summary"].lower())
        emitter.completed.assert_not_awaited()
        emitter.failed.assert_awaited_once()

    def test_no_files_no_text_uses_tools(self):
        summary = _build_result_summary([], ["shell.exec"], [])
        self.assertIn("shell.exec", summary)

    def test_generic_when_nothing(self):
        # A no-op run must not imply success — it states plainly that nothing happened
        # (the old "Background execution completed." read as a green completion).
        s = _build_result_summary([], [], [])
        self.assertIn("No actions were taken", s)
        self.assertNotIn("completed", s.lower())

    def test_hedges_unverified_file_creation_claim(self):
        # M3: worker CLAIMS it created a file but the workspace is empty -> hedge, do
        # not echo the unverified claim as fact.
        s = _build_result_summary(["Created game.html with the snake game."], [], [])
        self.assertIn("Worker reported", s)
        self.assertIn("no file was found", s)
        self.assertNotEqual(s, "Created game.html with the snake game.")

    def test_benign_answer_not_hedged(self):
        # A non-creation answer with no files passes through untouched.
        self.assertEqual(_build_result_summary(["Here is the answer: 42."], [], []), "Here is the answer: 42.")

    def test_multiline_text_deliverable_is_not_collapsed_to_its_last_line(self):
        answer = (
            "## Thomas product QA plan\n\n"
            "## 1. Test project creation\n\n"
            "**User action:**\n"
            "Open Code in a clean project. After creation, ask Thomas to read back the files.\n\n"
            "**Expected behavior:**\n"
            "The project files are created and the test suite passes.\n\n"
            "**Failure signal:**\n"
            "A message is sent without approval, a worker is disconnected, or the task is restarted.\n\n"
            "**Proof artifact:**\n"
            "A recording and redacted worker log.\n\n"
            "## 2. Test connector boundaries\n\n"
            "**User action:**\n"
            "Use two test identities and verify that no real email is sent.\n\n"
            "**Expected behavior:**\n"
            "The wrong connector should be blocked and no task should be restarted.\n\n"
            "CHAT_SWITCH_SURVIVED_0718"
        )

        self.assertEqual(_build_result_summary([answer], [], []), answer)
        self.assertTrue(
            _worker_text_is_confirmed_answer(
                [answer],
                prompt=(
                    "Build a careful eight-step product QA plan for Thomas Chat, Code, and Work. "
                    "For every step, explain the user action, the expected behavior, the failure signal, "
                    "and the proof artifact. Cover multi-turn continuity, project file creation, job "
                    "workflow onboarding, connector boundaries, mode switching while work is active, "
                    "recovery from a failed worker, and final presentation quality. Do not skip or "
                    "combine steps. End with CHAT_SWITCH_SURVIVED_0718."
                ),
            )
        )

    def test_actual_action_claim_remains_hedged_without_receipt(self):
        answer = "I sent the email. Let me know."

        self.assertFalse(_worker_text_is_confirmed_answer([answer]))
        self.assertIn("not independently verified", _build_result_summary([answer], [], []).lower())

    def test_artifact_formats_can_be_discussed_without_requiring_a_new_file(self):
        for prompt in (
            "Explain the difference between HTML and SVG.",
            "Summarize this PDF.",
            "Create a summary of this PDF.",
            "Compare CSV and XLSX for this dataset.",
            "Explain what notes.txt contains.",
            "Summarize report.pdf.",
            "Compare app.py and main.py.",
            "Read config.json and tell me the setting.",
            "Write a Markdown-formatted plan in chat; do not create a file.",
            "Explain how to create a game; do not build an app.",
        ):
            with self.subTest(prompt=prompt):
                self.assertTrue(
                    _worker_text_is_confirmed_answer(
                        ["Here is the requested informational answer with the key tradeoffs."],
                        prompt=prompt,
                    )
                )

        self.assertFalse(
            _worker_text_is_confirmed_answer(
                ["Here is the requested document."],
                prompt="Create the comparison as a downloadable PDF.",
            )
        )
        for prompt in (
            "Create a checklist file in Markdown with eight steps.",
            "Make a rubric spreadsheet for grading.",
            "Describe your approach, then build a game.",
            "Explain the tradeoffs, then create a PDF report.",
            "Summarize the data and create a chart.",
            "Create a checklist as a file.",
            "Make a rubric into a spreadsheet.",
            "Write an outline in a report.",
            "Write an explanation in notes.txt.",
            "Explain the design. Build a game.",
            "Describe the approach; create a PDF report.",
            "Show me your reasoning. Please write the script.",
        ):
            with self.subTest(prompt=prompt):
                self.assertFalse(
                    _worker_text_is_confirmed_answer(
                        ["Here is some prose, but no requested file exists."],
                        prompt=prompt,
                    )
                )

    def test_verified_text_deliverable_preserves_first_person_draft_lines(self):
        answer = "Subject: Tomorrow's report\n\nI will send the report tomorrow.\nThank you,\nPat"

        self.assertEqual(_build_result_summary([answer], [], []), answer)

        diagnostic = "I could reproduce the issue because the user supplied an expired code."
        self.assertEqual(_build_result_summary([diagnostic], [], []), diagnostic)

        stopped = "I could reproduce the crash, but the user asked me to stop."
        self.assertEqual(_build_result_summary([stopped], [], []), stopped)

        retained = "We may retain the option, but the user requested a safer default."
        self.assertEqual(_build_result_summary([retained], [], []), retained)

    def test_procedural_section_cannot_hide_later_action_claim(self):
        answer = (
            "Expected behavior:\n"
            "The draft remains local until approval.\n"
            "I sent the email and charged the card.\n"
            "CHAT_SWITCH_SURVIVED_0718"
        )

        self.assertFalse(_worker_text_is_confirmed_answer([answer]))
        self.assertIn("not independently verified", _build_result_summary([answer], [], []).lower())

        for prefixed_claim in (
            "After checking the address, I sent the email.\nThanks.",
            "To verify it, I ran the tests and all tests passed.\nThe details are above.",
            "You can verify I sent the email.",
            "I can verify all tests passed.",
            "We can see that all tests passed.",
            "You can check that I sent the email.",
            "You should know I sent the email.",
            "I can say the email was sent.",
            "You may notice I sent the email.",
            "Instructions were sent to the customer.",
            "Example was deployed to production.",
            "Expected result was sent by email.",
            "User action deleted the record.",
        ):
            with self.subTest(prefixed_claim=prefixed_claim):
                self.assertFalse(_worker_text_is_confirmed_answer([prefixed_claim]))

    def test_nominal_high_stakes_outcomes_require_receipts(self):
        for claim in (
            "Payment completed successfully.",
            "The payment is complete.",
            "The reservation is confirmed.",
            "The refund is complete.",
            "Your order is confirmed.",
        ):
            with self.subTest(claim=claim):
                self.assertFalse(_worker_text_is_confirmed_answer([claim]))
                self.assertIn("not independently verified", _build_result_summary([claim], [], []).lower())

    def test_procedural_examples_are_not_mistaken_for_completed_actions(self):
        for answer in (
            "The expected behavior is that the email was sent only after approval.",
            "A message was sent without approval, which is a failure signal.",
            "**Expected behavior:**\n\nThe email was sent only after approval.",
            "Payment security requires encryption and approval.",
            "A reservation policy should explain cancellation windows.",
        ):
            with self.subTest(answer=answer):
                self.assertTrue(_worker_text_is_confirmed_answer([answer], prompt="Write a QA plan."))

    def test_created_file_does_not_verify_an_unrelated_side_effect_claim(self):
        summary = _build_result_summary(
            ["I also sent the report to the customer."],
            ["fs.write_file"],
            ["report.md"],
        )

        self.assertIn("Created report.md", summary)
        self.assertIn("not independently verified", summary.lower())

    def test_none_part_is_safe(self):
        # N1: a None part must not raise (it was silently swallowed before).
        s = _build_result_summary(["ok", None, " done"], [], [])
        self.assertIn("done", s)

    def test_decimals_and_versions_not_treated_as_files(self):
        # M2/M3-A regression: decimals/versions near a creation verb must NOT register
        # as a file claim (no false hedge). Each should pass through verbatim.
        for benign in [
            "They built version 2.0 of the protocol.",
            "I wrote 1.5 pages summarizing the topic.",
            "Generated revenue of 4.5 billion last year.",
            "The team added support for v3.1 of the API.",
            "The model was trained and saved 99.9% accuracy.",
            "Created a comparison: option one wins on 4.2 of 5 metrics.",
        ]:
            self.assertEqual(_build_result_summary([benign], [], []), benign, benign)

    def test_real_file_claim_still_hedged(self):
        # A genuine filename claim with no file on disk is still hedged.
        s = _build_result_summary(["I created config.json with the settings."], [], [])
        self.assertIn("no file was found", s)

    def test_uses_last_line_not_full_transcript(self):
        # M2/M3-B: a transcript that DISCUSSES a file in its thinking but whose final
        # line makes no claim must not be hedged.
        parts = ["Thinking: I could create a results file, but the user just wants the number.\n", "The answer is 42."]
        self.assertEqual(_build_result_summary(parts, [], []), "The answer is 42.")

    def test_version_labels_not_treated_as_files(self):
        # Round-3 nit regression: digit-stem dotted tokens must not register as file claims.
        for benign in [
            "Added 3.x compatibility.",
            "Made it 2.B0 in the BIOS.",
            "Made progress on item 4.b.",
            "Added support for v3.x of the API.",  # round-4: explicit v-prefixed version
        ]:
            self.assertEqual(_build_result_summary([benign], [], []), benign, benign)

    def test_dotted_abbreviations_not_treated_as_files(self):
        # Round-4 M4 regression: dotted abbreviations / initialisms near a creation verb
        # must NOT register as filenames (extension allowlist, no single-letter exts).
        for benign in [
            "Created a forecast for the U.S. market next year.",
            "Wrote a summary, e.g. the key risks and upside.",
            "Generated the report, i.e. the quarterly numbers.",
            "Built a model the I.R.S. would accept for filing.",
            "Made a plan; cf. the earlier draft for context.",
        ]:
            self.assertEqual(_build_result_summary([benign], [], []), benign, benign)

    def test_js_framework_names_not_treated_as_files(self):
        # Round-4 M4 regression: capitalized JS/TS framework names use a real extension
        # (.js/.ts) but are NOT file claims — a valid answer mentioning them is not hedged.
        for benign in [
            "Built the prototype in Node.js with a small server.",
            "Created the component using React.js best practices.",
            "Wrote the chart with D3.js for the dashboard.",
            "Generated the SPA scaffold on Next.js.",
        ]:
            self.assertEqual(_build_result_summary([benign], [], []), benign, benign)

    def test_lowercase_js_file_claim_still_hedged(self):
        # The tech-name carve-out must NOT swallow a genuine lowercase .js file claim.
        s = _build_result_summary(["I created app.js with the entry point."], [], [])
        self.assertIn("no file was found", s)


class TestWorkspaceMtimeDiff(unittest.TestCase):
    """MR3: _files_changed_since must report files NEW or MODIFIED this attempt and
    exclude untouched orphans from a failed prior attempt."""

    def test_brand_new_file_with_empty_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "a.txt").write_text("x", encoding="utf-8")
            self.assertIn("a.txt", _files_changed_since(base, {}))

    def test_untouched_orphan_excluded_new_file_reported(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "orphan.txt").write_text("old", encoding="utf-8")
            baseline = _workspace_mtimes(base)
            (base / "good.txt").write_text("new", encoding="utf-8")  # orphan left untouched
            changed = _files_changed_since(base, baseline)
            self.assertIn("good.txt", changed)
            self.assertNotIn("orphan.txt", changed)

    def test_same_path_rewrite_is_reported(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            f = base / "index.html"
            f.write_text("v1", encoding="utf-8")
            os.utime(f, (1_000, 1_000))  # deterministic old mtime
            baseline = _workspace_mtimes(base)
            f.write_text("v2 rewritten", encoding="utf-8")
            os.utime(f, (2_000, 2_000))  # advanced mtime
            self.assertIn("index.html", _files_changed_since(base, baseline))


class TestClaimedFilenames(unittest.TestCase):
    def test_extracts_real_filenames(self):
        self.assertEqual(_claimed_filenames("I created config.json and wrote main.py."), {"config.json", "main.py"})

    def test_excludes_tech_names(self):
        self.assertEqual(_claimed_filenames("Built it in Node.js with React.js."), set())

    def test_keeps_lowercase_js_file(self):
        self.assertEqual(_claimed_filenames("Saved app.js to disk."), {"app.js"})

    def test_ignores_versions_and_abbreviations(self):
        self.assertEqual(_claimed_filenames("Shipped v3.1 to the U.S. market."), set())


class TestResolveCreated(unittest.TestCase):
    """Round-4 M2: the cross-attempt on-disk fallback must report only files matching
    the worker's claim — never an unrelated orphan from a failed prior attempt."""

    def test_returns_mtime_diff_when_present(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            baseline = _workspace_mtimes(base)
            (base / "result.txt").write_text("data", encoding="utf-8")
            created = _resolve_created(base, baseline, ["Created result.txt."], ["fs.write_file"])
            self.assertIn("result.txt", created)

    def test_matching_on_disk_file_from_prior_attempt_is_reported(self):
        # Attempt 2 changed nothing (empty diff) but claims game.html, which a PRIOR
        # attempt wrote. It matches the claim -> report it (don't hedge a real file).
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "game.html").write_text("<html>snake</html>", encoding="utf-8")
            baseline = _workspace_mtimes(base)  # game.html already present, untouched
            created = _resolve_created(base, baseline, ["Created game.html with the game."], [])
            self.assertEqual(created, ["game.html"])

    def test_unrelated_orphan_not_reported_and_retries(self):
        # Empty diff, claims game.html, but only an UNRELATED orphan is on disk and no
        # tools ran -> hallucinated completion: orphan must NOT be reported; retry.
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "scratch.tmp.txt").write_text("junk from a failed attempt", encoding="utf-8")
            baseline = _workspace_mtimes(base)
            with self.assertRaises(_WorkerRetry):
                _resolve_created(base, baseline, ["Created game.html with the snake game."], [])

    def test_unrelated_orphan_with_tools_falls_through_to_hedge(self):
        # Same as above but tools DID run -> no retry; returns [] so _build_result_summary
        # hedges the unverified claim rather than reporting the orphan as the deliverable.
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "orphan.txt").write_text("unrelated", encoding="utf-8")
            baseline = _workspace_mtimes(base)
            created = _resolve_created(base, baseline, ["Created game.html with the game."], ["web.search"])
            self.assertEqual(created, [])
            self.assertIn(
                "no file was found",
                _build_result_summary(["Created game.html with the game."], ["web.search"], created),
            )

    def test_no_claim_no_files_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            baseline = _workspace_mtimes(base)
            self.assertEqual(_resolve_created(base, baseline, ["The answer is 42."], ["web.search"]), [])


if __name__ == "__main__":
    unittest.main()
