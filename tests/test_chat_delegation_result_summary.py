"""Tests for the verified deliverable manifest reported back to chat.

The result a user sees for a finished task must name the REAL files the worker
wrote (sourced from disk), not the worker's last sentence of reasoning, and must
never claim a file that isn't there.
"""

import os
import tempfile
import unittest
from pathlib import Path

from thomas.server.chat_delegation import (
    _build_result_summary,
    _claimed_filenames,
    _files_changed_since,
    _resolve_created,
    _snapshot_workspace_files,
    _WorkerRetry,
    _workspace_mtimes,
)


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
        parts = ["I could create a results file, but the user just wants the number.\n", "The answer is 42."]
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
