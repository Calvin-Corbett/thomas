"""The artifact-intent floor: does the deliverable relate to the request at all?

These cases are drawn from real incidents on this machine. The graph/arcade-game
pair is the one Calvin reported twice; the Teal Tapper pair is the false
rejection the first version of this gate produced, kept here because a verifier
that rejects good work is not an improvement on one that accepts bad work.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from thomas.server.chat_delegation_artifact_intent import (
    artifact_intent_issues,
    intent_evidence,
)

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


if __name__ == "__main__":
    unittest.main()
