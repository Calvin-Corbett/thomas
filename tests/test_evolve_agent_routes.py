"""Route tests for the directed Evolve-agent (Forge Code) HTTP API.

These drive the real aiohttp handlers in
``thomas.server.routes.evolve_agent_routes`` through an in-process
:class:`~aiohttp.test_utils.TestClient`, with:

* a no-op ``require_api_access`` stub (auth is exercised elsewhere), and
* a ``root_resolver`` pointing at a throwaway git repo created in ``tmp_path``.

The conversation-store and git-truth helpers are NOT mocked -- the tests assert
against real persisted JSON and real ``git`` output, so they verify the wiring
end to end. The test process is allowed to run git (it bootstraps the fixture);
the build subprocess itself is never spawned here -- we exercise the
store/git/route layer directly.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.forge.anvil import forge_code_git
from thomas.forge.anvil.forge_code_git import _run_git
from thomas.server.routes.evolve_agent_routes import register_evolve_agent_routes


def _init_repo(root: Path) -> None:
    """Create a throwaway git repo with deterministic identity/signing."""
    _run_git(root, ["init"])
    _run_git(root, ["config", "user.email", "test@example.com"])
    _run_git(root, ["config", "user.name", "Forge Test"])
    # A developer's global config may force GPG signing; disable it so a commit
    # in a bare tmp repo cannot hang or fail for unrelated reasons.
    _run_git(root, ["config", "commit.gpgsign", "false"])


def _commit_all(root: Path, message: str = "commit") -> None:
    _run_git(root, ["add", "-A"])
    _run_git(root, ["commit", "-m", message])


def _new_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)
    return repo


def _drive(repo: Path, body: Callable[[TestClient], Awaitable[Any]]) -> Any:
    """Build an app with only the evolve-agent routes and run ``body`` against it.

    Wrapped in :func:`asyncio.run` so each test is an ordinary sync function --
    no pytest-asyncio dependency, and ``tmp_path`` composes cleanly.
    """

    async def _runner() -> Any:
        app = web.Application()
        register_evolve_agent_routes(
            app,
            require_api_access=lambda _request: None,  # auth stubbed out
            root_resolver=lambda: repo,
        )
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            return await body(client)
        finally:
            await client.close()

    return asyncio.run(_runner())


def test_conversation_new_list_get_and_missing_404(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)

    async def _body(client: TestClient) -> None:
        # Open a fresh conversation.
        resp = await client.post(
            "/api/evolve/agent/conversations/new",
            json={"title": "My build"},
        )
        assert resp.status == 200
        created = await resp.json()
        assert created["ok"] is True
        cid = created["conversation"]["id"]
        assert cid
        assert created["conversation"]["title"] == "My build"

        # It shows up in the list, with a day-grouped view.
        resp = await client.get("/api/evolve/agent/conversations")
        assert resp.status == 200
        listing = await resp.json()
        assert listing["ok"] is True
        assert any(c["id"] == cid for c in listing["conversations"])
        assert isinstance(listing["days"], list)
        assert any(item["id"] == cid for group in listing["days"] for item in group["items"])

        # It is fetchable by id.
        resp = await client.get(f"/api/evolve/agent/conversations/{cid}")
        assert resp.status == 200
        fetched = await resp.json()
        assert fetched["ok"] is True
        assert fetched["conversation"]["id"] == cid

        # A missing id 404s with a structured error.
        resp = await client.get("/api/evolve/agent/conversations/does-not-exist")
        assert resp.status == 404
        missing = await resp.json()
        assert missing["ok"] is False
        assert missing["error"] == "not found"

    _drive(repo, _body)


def test_conversation_rename_and_delete(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)

    async def _body(client: TestClient) -> None:
        created = await (await client.post("/api/evolve/agent/conversations/new", json={"title": "Original"})).json()
        cid = created["conversation"]["id"]

        # Rename returns the updated conversation and persists the new title.
        resp = await client.post(
            f"/api/evolve/agent/conversations/{cid}/rename",
            json={"title": "Renamed build"},
        )
        assert resp.status == 200
        renamed = await resp.json()
        assert renamed["ok"] is True
        assert renamed["conversation"]["title"] == "Renamed build"

        # The rename is reflected when the conversation is fetched back.
        fetched = await (await client.get(f"/api/evolve/agent/conversations/{cid}")).json()
        assert fetched["conversation"]["title"] == "Renamed build"

        # A blank title is rejected (the store never persists an empty label here).
        resp = await client.post(
            f"/api/evolve/agent/conversations/{cid}/rename",
            json={"title": "   "},
        )
        assert resp.status == 400

        # Renaming a missing conversation 404s.
        resp = await client.post(
            "/api/evolve/agent/conversations/does-not-exist/rename",
            json={"title": "nope"},
        )
        assert resp.status == 404

        # Delete removes it; a second delete 404s (idempotent at the store layer).
        resp = await client.delete(f"/api/evolve/agent/conversations/{cid}")
        assert resp.status == 200
        deleted = await resp.json()
        assert deleted["ok"] is True
        assert deleted["deleted"] is True
        assert deleted["id"] == cid

        assert (await client.get(f"/api/evolve/agent/conversations/{cid}")).status == 404
        assert (await client.delete(f"/api/evolve/agent/conversations/{cid}")).status == 404

    _drive(repo, _body)


def test_changes_revert_and_keep_against_real_git(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)
    # Commit two files, then dirty both: one we will revert, one we will keep.
    (repo / "reverted.txt").write_text("original\n", encoding="utf-8")
    (repo / "kept.txt").write_text("original\n", encoding="utf-8")
    _commit_all(repo)
    (repo / "reverted.txt").write_text("original\nlocal edit\n", encoding="utf-8")
    (repo / "kept.txt").write_text("original\nlocal edit\n", encoding="utf-8")

    async def _body(client: TestClient) -> None:
        # /changes reports both dirty files with a real, non-empty diff.
        resp = await client.get("/api/evolve/agent/changes")
        assert resp.status == 200
        payload = await resp.json()
        assert payload["ok"] is True
        by_file = {entry["file"]: entry for entry in payload["changed"]}
        assert "reverted.txt" in by_file
        assert "kept.txt" in by_file
        assert "+local edit" in by_file["reverted.txt"]["diff"]
        assert by_file["reverted.txt"]["untracked"] is False

        # Revert restores the file: git no longer reports it dirty.
        resp = await client.post(
            "/api/evolve/agent/revert",
            json={"file": "reverted.txt"},
        )
        assert resp.status == 200
        result = await resp.json()
        assert result["ok"] is True
        assert result["clean"] is True
        assert "reverted.txt" not in forge_code_git.changed_files(repo)

        # Keep is a no-op on disk: the file stays changed.
        resp = await client.post(
            "/api/evolve/agent/keep",
            json={"file": "kept.txt"},
        )
        assert resp.status == 200
        kept = await resp.json()
        assert kept["ok"] is True
        assert kept["kept"] is True
        assert kept["file"] == "kept.txt"
        assert "kept.txt" in forge_code_git.changed_files(repo)

        # Revert with no file is a 400.
        resp = await client.post("/api/evolve/agent/revert", json={})
        assert resp.status == 400

    _drive(repo, _body)


def test_artifact_serves_built_html_sandboxed_and_refuses_non_artifacts(tmp_path: Path) -> None:
    """The artifact route serves the REAL bytes of a file this build wrote, from
    the app's own origin, sandboxed at the response layer -- and refuses anything
    that is not a build artifact or that escapes the repo root."""
    repo = _new_repo(tmp_path)
    # A clean, committed file is NOT an artifact (not dirty, not recorded).
    (repo / "committed.txt").write_text("secret\n", encoding="utf-8")
    _commit_all(repo)
    # The build's real output: an HTML page now dirty in the working tree.
    page = "<!doctype html><title>Hi</title><h1>Built by Forge</h1>"
    (repo / "index.html").write_text(page, encoding="utf-8")

    async def _body(client: TestClient) -> None:
        # The dirty HTML page is served with the real bytes + sandbox CSP so it can
        # render in the preview iframe but never reach the host app.
        resp = await client.get("/api/evolve/agent/artifact/anycid/index.html")
        assert resp.status == 200
        assert "Built by Forge" in await resp.text()
        assert resp.headers["Content-Security-Policy"] == "sandbox allow-scripts allow-forms"

        # A committed (clean) file is not an artifact of any build -> 404.
        assert (await client.get("/api/evolve/agent/artifact/anycid/committed.txt")).status == 404

        # A path that escapes the repo root is refused even if dirty-looking.
        escaped = await client.get("/api/evolve/agent/artifact/anycid/../../etc/passwd")
        assert escaped.status == 404

    _drive(repo, _body)


def test_done_frame_carries_artifacts_for_renderable_run() -> None:
    """The detector wired into the done frame produces an artifact descriptor for a
    run that wrote an .html file, and none for a .py-only run."""
    from thomas.forge.anvil.forge_code_store import detect_artifacts

    assert detect_artifacts(["index.html"]) == [{"file": "index.html", "kind": "html", "ext": "html"}]
    assert detect_artifacts(["thomas/server/foo.py"]) == []


def test_line_to_sse_payload_maps_forge_events_to_typed_frames() -> None:
    """A forge-event transcript line becomes a typed SSE frame (kept under
    type:'output' so progressive frames still count, plus a 'kind' the UI styles);
    plain text stays untyped; garbage degrades to plain text, never raising."""
    import json

    from thomas.server.routes.evolve_agent_routes import _line_to_sse_payload

    tool = _line_to_sse_payload(json.dumps({"fc": "tool", "name": "Edit", "text": "a.py"}))
    assert tool == {"type": "output", "kind": "tool", "text": "a.py", "name": "Edit"}

    tres = _line_to_sse_payload(json.dumps({"fc": "tool_result", "text": "boom", "is_error": True}))
    assert tres["kind"] == "tool_result" and tres["is_error"] is True

    say = _line_to_sse_payload(json.dumps({"fc": "say", "text": "thinking"}))
    assert say == {"type": "output", "kind": "say", "text": "thinking"}

    plain = _line_to_sse_payload("DISPATCHED via claude CLI (2 file(s) changed)")
    assert plain == {"type": "output", "text": "DISPATCHED via claude CLI (2 file(s) changed)"}
    assert "kind" not in plain  # untyped -> heuristic-rendered on the client

    # Defensive: a line that merely looks like JSON must not raise.
    assert _line_to_sse_payload("{not valid json") == {"type": "output", "text": "{not valid json"}
    assert _line_to_sse_payload("   ") == {}


def test_incremental_line_decoder_survives_multibyte_split_across_chunks() -> None:
    """Perf-45 regression: a multibyte UTF-8 char split across two read chunks must
    decode INTACT — never as the U+FFFD replacement char.

    The SSE tail reads the transcript in arbitrary byte chunks, so an emoji (4
    bytes) or em-dash (3 bytes) can straddle a boundary. A per-chunk decode would
    mangle each half; the incremental decoder must hold the partial sequence until
    the completing bytes arrive.
    """
    import json

    from thomas.server.routes.evolve_agent_routes import _IncrementalLineDecoder

    # A full forge-event narration line carrying an emoji AND an em-dash.
    line = '{"fc": "say", "text": "Creating the file \U0001f6e0 and flagging — done"}\n'
    raw = line.encode("utf-8")

    # Split the byte stream in the MIDDLE of the 4-byte emoji so chunk 1 ends with
    # an incomplete multibyte sequence that only chunk 2 completes.
    emoji_start = raw.index(b"\xf0\x9f\x9b\xa0")  # U+1F6E0 hammer-and-wrench in UTF-8
    split = emoji_start + 2  # 2 of the emoji's 4 bytes land in the first chunk
    chunk1, chunk2 = raw[:split], raw[split:]
    assert chunk1.decode("utf-8", errors="replace").endswith("�")  # the naive bug, proven

    dec = _IncrementalLineDecoder()
    out = dec.feed(chunk1) + dec.feed(chunk2) + dec.flush()

    assert len(out) == 1
    decoded = out[0]
    assert "�" not in decoded  # no U+FFFD replacement char survived the boundary
    assert "\U0001f6e0" in decoded  # the emoji is intact
    assert "—" in decoded  # the em-dash is intact
    # And the reassembled line is still parseable as the original forge event.
    assert json.loads(decoded)["text"] == "Creating the file \U0001f6e0 and flagging — done"


def test_incremental_line_decoder_holds_partial_line_until_newline() -> None:
    """Only COMPLETE lines (terminated by ``\\n``) are emitted as they arrive; a
    partial trailing line is buffered until its newline, then flushed at end."""
    from thomas.server.routes.evolve_agent_routes import _IncrementalLineDecoder

    dec = _IncrementalLineDecoder()
    assert dec.feed(b"first line\nsecond ") == ["first line"]  # partial held back
    assert dec.feed(b"half\n") == ["second half"]  # newline completes it
    assert dec.feed(b"no newline yet") == []  # still buffered
    assert dec.flush() == ["no newline yet"]  # final remainder surfaced once


def test_stop_when_nothing_running_is_a_safe_noop(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)

    async def _body(client: TestClient) -> None:
        resp = await client.post("/api/evolve/agent/stop")
        assert resp.status == 200
        body = await resp.json()
        assert body["ok"] is True
        assert body["stopped"] is True

    _drive(repo, _body)
