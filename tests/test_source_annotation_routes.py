"""Route-layer tests for CAP-147 inline annotation editing.

Proves the exact L2 acceptance line through the HTTP layer -- "Add user-authored
anchored annotations that open agent conversations and create source diffs" --
against a hermetic runtime: a dict-backed file seam, an injected clock/id factory,
and a temp-dir JSON store. No network, no real repo files touched.

The route module is registered onto a bare ``web.Application`` (the orchestrator
wires it into the real app separately), so these tests exercise the endpoints
exactly as the browser panel calls them.
"""

from __future__ import annotations

import itertools
import tempfile
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from thomas.server.routes.source_annotation_routes import (
    SourceAnnotationRuntime,
    register_source_annotation_routes,
    reset_source_annotation_runtime,
    set_source_annotation_runtime,
)
from thomas.tools.source_annotations import AnnotationStore, apply_unified_diff

SAMPLE = "\n".join(
    [
        "def greet(name):",
        '    prefix = "Hello"',
        '    return prefix + ", " + name',
        "",
        "def farewell(name):",
        '    return "Bye, " + name',
    ]
)


class _FakeFiles:
    """Dict-backed file seam: normalize() validates, read() returns current text."""

    def __init__(self, files: dict[str, str]) -> None:
        self.files = dict(files)

    def normalize(self, file: str) -> str:
        key = str(file or "").strip()
        if not key:
            raise ValueError("file is required")
        if key not in self.files:
            raise ValueError(f"file not found: {key}")
        return key

    def read(self, file: str) -> str:
        return self.files[file]


class SourceAnnotationRoutesTest(AioHTTPTestCase):
    async def get_application(self) -> web.Application:
        self._tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmpdir.cleanup)
        self.addCleanup(reset_source_annotation_runtime)

        self.files = _FakeFiles({"demo.py": SAMPLE})
        clock = itertools.count(1)
        ids = itertools.count(1)
        store = AnnotationStore(
            Path(self._tmpdir.name) / "annotations.json",
            reader=self.files.read,
            clock=lambda: f"2026-07-22T00:00:{next(clock):02d}+00:00",
            id_factory=lambda: f"ann{next(ids)}",
        )
        set_source_annotation_runtime(
            SourceAnnotationRuntime(store=store, normalize=self.files.normalize, reader=self.files.read)
        )
        app = web.Application()
        register_source_annotation_routes(app, None)
        return app

    # -- helpers ----------------------------------------------------------

    async def _create(self, **overrides):
        payload = {
            "file": "demo.py",
            "line_start": 2,
            "line_end": 3,
            "body": "prefix should be configurable",
        }
        payload.update(overrides)
        return await self.client.post("/api/source-annotations", json=payload)

    # -- create + list (user-authored, anchored) ---------------------------

    async def test_create_anchors_annotation_to_line_range_and_lists_it(self):
        resp = await self._create()
        self.assertEqual(resp.status, 201)
        created = (await resp.json())["annotation"]
        self.assertEqual(created["file"], "demo.py")
        self.assertEqual(created["line_start"], 2)
        self.assertEqual(created["line_end"], 3)
        self.assertEqual(created["status"], "anchored")
        self.assertTrue(created["anchored"])
        self.assertEqual(created["body"], "prefix should be configurable")
        self.assertEqual(
            created["anchor"]["region_lines"],
            ['    prefix = "Hello"', '    return prefix + ", " + name'],
        )

        listing = await self.client.get("/api/source-annotations?file=demo.py")
        self.assertEqual(listing.status, 200)
        body = await listing.json()
        self.assertTrue(body["ok"])
        self.assertEqual([a["id"] for a in body["annotations"]], [created["id"]])

    async def test_source_endpoint_returns_lines_and_annotations(self):
        create = await self._create()
        self.assertEqual(create.status, 201)

        resp = await self.client.get("/api/source-annotations/source?file=demo.py")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertEqual(body["file"], "demo.py")
        self.assertEqual(body["line_count"], 6)
        self.assertEqual(body["lines"][0], {"number": 1, "text": "def greet(name):"})
        self.assertEqual(len(body["annotations"]), 1)
        self.assertEqual(body["annotations"][0]["status"], "anchored")

    async def test_unfiltered_list_returns_every_annotation(self):
        self.files.files["other.py"] = "alpha\nbeta\n"
        self.assertEqual((await self._create()).status, 201)
        second = await self._create(file="other.py", line_start=1, line_end=1, body="rename alpha")
        self.assertEqual(second.status, 201)

        resp = await self.client.get("/api/source-annotations")
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertIsNone(body["file"])
        self.assertEqual({a["file"] for a in body["annotations"]}, {"demo.py", "other.py"})

    # -- validation: user error is 4xx, never 500 --------------------------

    async def test_unknown_file_is_400(self):
        resp = await self._create(file="nope.py")
        self.assertEqual(resp.status, 400)
        body = await resp.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["code"], "invalid_request")

    async def test_line_range_beyond_end_of_file_is_400(self):
        resp = await self._create(line_start=5, line_end=99)
        self.assertEqual(resp.status, 400)
        self.assertEqual((await resp.json())["code"], "invalid_request")

    async def test_inverted_line_range_is_400(self):
        resp = await self._create(line_start=4, line_end=2)
        self.assertEqual(resp.status, 400)

    async def test_zero_line_start_is_400(self):
        resp = await self._create(line_start=0, line_end=1)
        self.assertEqual(resp.status, 400)

    async def test_missing_body_text_is_400(self):
        resp = await self._create(body="   ")
        self.assertEqual(resp.status, 400)

    async def test_malformed_json_body_is_400(self):
        resp = await self.client.post(
            "/api/source-annotations",
            data="{not json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.status, 400)

    async def test_source_endpoint_without_file_is_400(self):
        resp = await self.client.get("/api/source-annotations/source")
        self.assertEqual(resp.status, 400)
        self.assertEqual((await resp.json())["code"], "invalid_file")

    # -- open a conversation ----------------------------------------------

    async def test_open_conversation_returns_linked_ref(self):
        annotation_id = (await (await self._create()).json())["annotation"]["id"]

        resp = await self.client.post(f"/api/source-annotations/{annotation_id}/conversation", json={})
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["conversation_ref"], f"thread:annotation:{annotation_id}")
        self.assertEqual(body["annotation"]["conversation_ref"], f"thread:annotation:{annotation_id}")

        # The link is durable: it comes back on subsequent reads.
        listing = await self.client.get("/api/source-annotations?file=demo.py")
        stored = (await listing.json())["annotations"][0]
        self.assertEqual(stored["conversation_ref"], f"thread:annotation:{annotation_id}")

    async def test_open_conversation_accepts_explicit_ref(self):
        annotation_id = (await (await self._create()).json())["annotation"]["id"]
        resp = await self.client.post(
            f"/api/source-annotations/{annotation_id}/conversation",
            json={"conversation_ref": "session:abc-123"},
        )
        self.assertEqual(resp.status, 200)
        self.assertEqual((await resp.json())["conversation_ref"], "session:abc-123")

    async def test_open_conversation_rejects_blank_ref(self):
        annotation_id = (await (await self._create()).json())["annotation"]["id"]
        resp = await self.client.post(
            f"/api/source-annotations/{annotation_id}/conversation",
            json={"conversation_ref": "   "},
        )
        self.assertEqual(resp.status, 400)

    async def test_open_conversation_unknown_annotation_is_404(self):
        resp = await self.client.post("/api/source-annotations/missing/conversation", json={})
        self.assertEqual(resp.status, 404)
        self.assertEqual((await resp.json())["code"], "not_found")

    # -- emit a source diff -------------------------------------------------

    async def test_emit_diff_returns_appliable_unified_diff(self):
        created = await self._create(suggested_edit='    prefix = greeting\n    return prefix + ", " + name')
        annotation_id = (await created.json())["annotation"]["id"]

        resp = await self.client.post(f"/api/source-annotations/{annotation_id}/diff", json={})
        self.assertEqual(resp.status, 200)
        body = await resp.json()
        diff = body["diff"]
        self.assertIn("--- a/demo.py", diff)
        self.assertIn("+++ b/demo.py", diff)
        self.assertIn("@@", diff)
        self.assertIn('-    prefix = "Hello"', diff)
        self.assertIn("+    prefix = greeting", diff)

        # It is a real unified diff: applying it produces the suggested source.
        patched = apply_unified_diff(SAMPLE, diff)
        self.assertIn("    prefix = greeting", patched.split("\n"))
        self.assertNotIn('    prefix = "Hello"', patched.split("\n"))
        self.assertEqual(patched.split("\n")[0], "def greet(name):")

    async def test_emit_diff_honours_context_lines(self):
        created = await self._create(
            line_start=6,
            line_end=6,
            suggested_edit='    return "Goodbye, " + name',
        )
        annotation_id = (await created.json())["annotation"]["id"]
        resp = await self.client.post(f"/api/source-annotations/{annotation_id}/diff", json={"context_lines": 0})
        self.assertEqual(resp.status, 200)
        diff = (await resp.json())["diff"]
        self.assertNotIn("def greet(name):", diff)
        self.assertIn('+    return "Goodbye, " + name', diff)

    async def test_emit_diff_rejects_out_of_range_context_lines(self):
        created = await self._create(suggested_edit="    prefix = greeting\n    return prefix")
        annotation_id = (await created.json())["annotation"]["id"]
        resp = await self.client.post(
            f"/api/source-annotations/{annotation_id}/diff",
            json={"context_lines": 9999},
        )
        self.assertEqual(resp.status, 400)

    async def test_emit_diff_without_suggested_edit_is_409(self):
        annotation_id = (await (await self._create()).json())["annotation"]["id"]
        resp = await self.client.post(f"/api/source-annotations/{annotation_id}/diff", json={})
        self.assertEqual(resp.status, 409)
        self.assertEqual((await resp.json())["code"], "no_suggested_edit")

    async def test_emit_diff_unknown_annotation_is_404(self):
        resp = await self.client.post("/api/source-annotations/missing/diff", json={})
        self.assertEqual(resp.status, 404)

    # -- re-anchoring / orphan reporting -----------------------------------

    async def test_annotation_follows_its_lines_after_an_edit_above(self):
        annotation_id = (await (await self._create()).json())["annotation"]["id"]
        self.files.files["demo.py"] = "# new header\n# second header\n" + SAMPLE

        resp = await self.client.get("/api/source-annotations/source?file=demo.py")
        self.assertEqual(resp.status, 200)
        annotation = (await resp.json())["annotations"][0]
        self.assertEqual(annotation["id"], annotation_id)
        self.assertEqual(annotation["status"], "anchored")
        self.assertEqual(annotation["line_start"], 4)
        self.assertEqual(annotation["line_end"], 5)

    async def test_orphaned_anchor_is_reported_and_blocks_diff(self):
        created = await self._create(suggested_edit="    prefix = greeting")
        annotation_id = (await created.json())["annotation"]["id"]
        self.files.files["demo.py"] = "def unrelated():\n    return 0\n"

        resp = await self.client.get("/api/source-annotations/source?file=demo.py")
        self.assertEqual(resp.status, 200)
        annotation = (await resp.json())["annotations"][0]
        self.assertEqual(annotation["status"], "orphaned")
        self.assertFalse(annotation["anchored"])

        diff_resp = await self.client.post(f"/api/source-annotations/{annotation_id}/diff", json={})
        self.assertEqual(diff_resp.status, 409)
        self.assertEqual((await diff_resp.json())["code"], "orphaned_anchor")

    # -- acceptance line, end to end ---------------------------------------

    async def test_acceptance_author_then_converse_then_diff(self):
        create = await self._create(
            body="make the greeting configurable",
            suggested_edit='    prefix = greeting\n    return prefix + ", " + name',
        )
        self.assertEqual(create.status, 201)
        annotation_id = (await create.json())["annotation"]["id"]

        listed = await self.client.get("/api/source-annotations/source?file=demo.py")
        listing = await listed.json()
        self.assertEqual(listing["annotations"][0]["body"], "make the greeting configurable")

        conversation = await self.client.post(
            f"/api/source-annotations/{annotation_id}/conversation",
            json={},
        )
        self.assertEqual(conversation.status, 200)
        ref = (await conversation.json())["conversation_ref"]
        self.assertTrue(ref)

        diff_resp = await self.client.post(f"/api/source-annotations/{annotation_id}/diff", json={})
        self.assertEqual(diff_resp.status, 200)
        diff_body = await diff_resp.json()
        self.assertEqual(diff_body["annotation"]["conversation_ref"], ref)
        self.assertEqual(apply_unified_diff(SAMPLE, diff_body["diff"]).count("prefix = greeting"), 1)


if __name__ == "__main__":
    unittest.main()
