"""The artifact-intent floor: does the deliverable relate to the request at all?

These cases are drawn from real incidents on this machine. The graph/arcade-game
pair is the one Calvin reported twice; the Teal Tapper pair is the false
rejection the first version of this gate produced, kept here because a verifier
that rejects good work is not an improvement on one that accepts bad work.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from thomas.server.chat_delegation_artifact_intent import (
    artifact_intent_issues,
    intent_evidence,
)
from thomas.server.chat_delegation_artifact_verification import _hidden_completion_review_passes

REPO_ROOT = Path(__file__).resolve().parents[1]

# The same request, answered twice: once with the wrong thing, once with the
# right thing. Any verifier worth the name has to separate these two.
TRENDS_REQUEST = "make me a graph of current technology adoption trends"

TRENDS_GRAPH = """<!doctype html><html><head><title>Technology trends</title></head>
<body><h1>Technology adoption trends over time</h1>
<p>Chart of adoption for each technology, plotted by year.</p>
<canvas id="chart"></canvas></body></html>"""

ARCADE_GAME = """<!doctype html><html><head><title>Orbit</title>
<style>body { display: grid; background: #000; }</style></head>
<body><h1>ORBIT</h1><p>Reverse direction at the right moment.</p>
<p>One button. No excuses.</p><p>Hit the pink pulse to score.</p>
<script>const player = {x: 0};</script></body></html>"""

SNAKE_GAME = """<!doctype html><html><head><title>Snake</title></head>
<body><h1>Snake</h1><p>Use the arrow keys to play. Eat to grow.</p>
<p>Score: 0</p></body></html>"""

# The real clicker deliverable calls itself Teal Tapper and never says
# "clicker" or "game" anywhere in its visible text.
TEAL_TAPPER = """<!doctype html><html><head><title>Teal Tapper</title></head>
<body><main><h1>Teal Tapper</h1><p>Tap to increase your total.</p>
<button>Tap me</button></main></body></html>"""


class ArtifactIntentTests(unittest.TestCase):
    def _write(self, tmp: str, name: str, body: str) -> Path:
        root = Path(tmp)
        (root / name).write_text(body, encoding="utf-8")
        return root

    def test_rejects_the_arcade_game_delivered_for_a_graph_request(self):
        """The reported incident: 'make me a graph of current trends' -> a game."""
        with TemporaryDirectory() as tmp:
            root = self._write(tmp, "index.html", ARCADE_GAME)
            issues = artifact_intent_issues(
                "make me a graph of current technology trends", root, ["index.html"]
            )
        self.assertTrue(issues)
        self.assertIn("index.html", issues[0])

    def test_accepts_an_artifact_that_matches_the_request(self):
        with TemporaryDirectory() as tmp:
            root = self._write(tmp, "snake.html", SNAKE_GAME)
            issues = artifact_intent_issues(
                "Make a small snake game i can play with arrow keys", root, ["snake.html"]
            )
        self.assertEqual(issues, [])

    def test_accepts_a_synonym_when_the_requested_filename_was_delivered(self):
        """clicker.html was asked for by name and produced, so the app inside
        being called Teal Tapper is a naming choice, not a wrong deliverable."""
        with TemporaryDirectory() as tmp:
            root = self._write(tmp, "clicker.html", TEAL_TAPPER)
            issues = artifact_intent_issues(
                "Make a tiny html clicker game, single file called clicker.html",
                root,
                ["clicker.html"],
            )
        self.assertEqual(issues, [])

    def test_one_incidental_word_is_not_agreement(self):
        """The arcade game says 'right'; a snake request must not pass on that."""
        with TemporaryDirectory() as tmp:
            root = self._write(tmp, "index.html", ARCADE_GAME)
            issues = artifact_intent_issues(
                "Make a small snake game i can play right now with arrow keys",
                root,
                ["index.html"],
            )
        self.assertTrue(issues)

    def test_stylesheet_and_script_bodies_do_not_count_as_subject(self):
        """CSS words like 'grid' must not satisfy a request for a grid."""
        page = "<!doctype html><html><head><style>.a{display:grid;filter:blur(1px)}</style>"
        page += "</head><body><p>Nothing here.</p></body></html>"
        with TemporaryDirectory() as tmp:
            root = self._write(tmp, "out.html", page)
            issues = artifact_intent_issues(
                "build a grid showing quarterly revenue figures", root, ["out.html"]
            )
        self.assertTrue(issues)

    def test_silent_when_the_request_is_too_vague_to_judge(self):
        with TemporaryDirectory() as tmp:
            root = self._write(tmp, "index.html", ARCADE_GAME)
            self.assertEqual(artifact_intent_issues("fix it", root, ["index.html"]), [])

    def test_silent_when_there_are_no_artifacts(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(
                artifact_intent_issues("make me a graph of current trends", Path(tmp), []), []
            )

    def test_silent_for_files_it_cannot_read(self):
        """A PDF cannot be token-checked; guessing about one is worse than
        admitting the check does not apply."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "report.pdf").write_bytes(b"%PDF-1.4 binary")
            self.assertEqual(
                artifact_intent_issues("make me a graph of current trends", root, ["report.pdf"]),
                [],
            )

    def test_evidence_reports_checkability_rather_than_a_bare_verdict(self):
        with TemporaryDirectory() as tmp:
            root = self._write(tmp, "index.html", ARCADE_GAME)
            vague = intent_evidence("fix it", root, ["index.html"])
            real = intent_evidence("make me a graph of technology trends", root, ["index.html"])
        self.assertFalse(vague["checkable"])
        self.assertTrue(real["checkable"])
        self.assertFalse(real["matches_request"])

    def test_an_absolute_path_cannot_escape_the_workspace(self):
        """On Windows an absolute path WINS the join, so work_dir / "C:/x.html"
        is simply C:\\x.html -- it survives the ".." test and then reads a file
        outside the workspace, naming its full path in a user-visible message.
        Containment is verified after resolving, not inferred from the string."""
        with TemporaryDirectory() as tmp:
            outside = Path(tmp) / "outside.html"
            outside.write_text("<p>unrelated content</p>", encoding="utf-8")
            work = Path(tmp) / "workspace"
            work.mkdir()

            for escape in (str(outside), "C:/Windows/system.html", "../outside.html"):
                with self.subTest(escape=escape):
                    self.assertEqual(
                        artifact_intent_issues("make a graph of current technology trends", work, [escape]),
                        [],
                    )

    def test_path_traversal_in_a_recorded_artifact_is_ignored(self):
        with TemporaryDirectory() as tmp:
            root = self._write(tmp, "index.html", ARCADE_GAME)
            self.assertEqual(
                artifact_intent_issues(
                    "make me a graph of technology trends", root, ["../../etc/passwd"]
                ),
                [],
            )


class ArtifactIntentIsNotOnTheCompletionPath(unittest.TestCase):
    """This check works and nothing in production calls it. Both halves, measured.

    Measured on dev 043d737c, 2026-07-31, with one request answered twice --
    ``make me a graph of current technology adoption trends`` delivered as an
    arcade game, and the same request delivered as a trend graph:

      * ``_hidden_completion_review_passes`` -> True for BOTH. The gate that
        decides whether a run is reported as verified cannot separate them.
      * ``artifact_intent_issues``           -> flags the game, passes the graph.
        So the difference is detectable; it is just not consulted.
      * Importers of ``chat_delegation_artifact_intent`` under ``thomas/``: 0.
        Control, same scanner: ``chat_delegation_artifact_verification`` has 1
        (``chat_delegation_runner``), so the scan can find a wired-up module --
        it found none for this one.

    Before/after for this change: no runtime behaviour moved. What changed is the
    module docstring, which used to say the Canvas path "already refuses this"
    (``review_canvas_html`` now opens with ``del prompt``) and read as though the
    generalised check were in force. Restoring the original 6cc89af2 call site
    was measured too: the arcade game flips True -> False, the genuine graph stays
    True, and ``test_hidden_review_accepts_verified_nonempty_artifact`` turns red,
    because the same merge landed the opposite contract. These tests hold the line
    so that whichever way that is settled, it is settled on purpose.
    """

    def _workspace(self, tmp: str, body: str) -> Path:
        root = Path(tmp)
        (root / "index.html").write_text(body, encoding="utf-8")
        return root

    def _completion_gate(self, root: Path) -> bool:
        return _hidden_completion_review_passes(
            TRENDS_REQUEST,
            root,
            ["index.html"],
            "Created index.html",
            True,
            [],
            succeeded_tools=["fs.write_file"],
        )

    def test_the_completion_gate_cannot_tell_the_wrong_deliverable_from_the_right_one(self):
        """Both answers to one request are reported verified. This is the defect."""
        with TemporaryDirectory() as tmp:
            wrong = self._completion_gate(self._workspace(tmp, ARCADE_GAME))
        with TemporaryDirectory() as tmp:
            right = self._completion_gate(self._workspace(tmp, TRENDS_GRAPH))

        self.assertTrue(right, "a genuine trend graph must still pass; otherwise this measures nothing")
        self.assertTrue(
            wrong,
            "the completion gate now separates a wrong deliverable from a right one -- "
            "if that was wired on purpose, update the 'NOT WIRED' note in "
            "thomas/server/chat_delegation_artifact_intent.py",
        )

    def test_this_module_can_tell_them_apart_which_is_why_it_is_kept(self):
        """The control: the gap is detectable, so the code is worth keeping wired-out."""
        with TemporaryDirectory() as tmp:
            wrong = artifact_intent_issues(TRENDS_REQUEST, self._workspace(tmp, ARCADE_GAME), ["index.html"])
        with TemporaryDirectory() as tmp:
            right = artifact_intent_issues(TRENDS_REQUEST, self._workspace(tmp, TRENDS_GRAPH), ["index.html"])

        self.assertTrue(wrong)
        self.assertEqual(right, [])

    def test_the_only_importer_is_the_reporting_path_not_the_verdict(self):
        """This module IS wired up now, and where it is wired matters.

        This test previously asserted that nothing under ``thomas/`` imported the
        module at all, and it fired the moment that changed -- which is exactly
        what it was for. The reconnection was deliberate: the promise the
        changelog made ("Thomas no longer calls a deliverable verified when it
        has nothing to do with what you asked") is now kept by TELLING the owner
        rather than by failing the run.

        So the claim worth pinning is no longer "nothing imports it" but "only
        the reporting path imports it". A token overlap must never decide
        pass/fail: restoring the original 2026-07-24 wiring, where a mismatch
        scored the completion review 0.0, flips a real recorded case from pass to
        fail. ``chat_delegation_deliverable_postprocess`` reaches it, that module
        returns a warning string, and the runner appends it to the summary
        alongside the executability warning.
        """
        target = "chat_delegation_artifact_intent"
        control = "chat_delegation_artifact_verification"
        importers: dict[str, set[str]] = {target: set(), control: set()}

        for path in (REPO_ROOT / "thomas").rglob("*.py"):
            if path.name == f"{target}.py":
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""] + [alias.name for alias in node.names]
                for module in names:
                    for name in (target, control):
                        if module.rsplit(".", 1)[-1] == name:
                            importers[name].add(path.relative_to(REPO_ROOT).as_posix())

        self.assertTrue(
            importers[control],
            "control failed: the scanner found no importer of a module that has one, "
            "so a zero for the target below would prove nothing",
        )
        self.assertEqual(
            importers[target],
            {"thomas/server/chat_delegation_deliverable_postprocess.py"},
            "chat_delegation_artifact_intent is reachable from somewhere other than the "
            "reporting path. It returns a token overlap, which must never decide a "
            "verdict -- restoring its original completion-review wiring flips a real "
            "recorded case from pass to fail. If a new importer is legitimate, say here "
            "which one and why it does not gate.",
        )

        # And the reporting path must not feed the verdict.
        runner = (REPO_ROOT / "thomas" / "server" / "chat_delegation_runner.py").read_text(encoding="utf-8")
        call = next(
            (
                line
                for line in runner.splitlines()
                if "subject_mismatch_warning" in line and "(" in line and "import" not in line
            ),
            "",
        )
        self.assertTrue(call, "the reporting call is gone, so the owner is no longer told")
        self.assertNotIn(
            "verified_success",
            call,
            f"the subject warning now feeds the verdict: {call.strip()!r}",
        )


if __name__ == "__main__":
    unittest.main()
