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
import json
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiohttp import CookieJar, web
from aiohttp.test_utils import TestClient, TestServer

from thomas.forge.anvil import forge_code_git, forge_code_projects, forge_code_store
from thomas.forge.anvil.forge_code_git import _run_git
from thomas.server.app_keys import APP_SECRETS
from thomas.server.routes import evolve_agent_http_support, evolve_agent_routes, evolve_agent_runtime
from thomas.server.routes.deliverable_aiohttp import register_deliverable_routes
from thomas.server.routes.evolve_agent_routes import (
    APP_EVOLVE_AGENT_APPROVALS,
    APP_EVOLVE_AGENT_DRAIN,
    APP_EVOLVE_AGENT_SESSION,
    APP_EVOLVE_AGENT_TASK,
    register_evolve_agent_routes,
)


class _GateInput:
    def __init__(self) -> None:
        self.data = b""
        self.closed = False

    def write(self, data: bytes) -> None:
        self.data += data

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


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


def _drive(
    repo: Path,
    body: Callable[[TestClient], Awaitable[Any]],
    *,
    configure: Callable[[web.Application], None] | None = None,
) -> Any:
    """Build an app with only the evolve-agent routes and run ``body`` against it.

    Wrapped in :func:`asyncio.run` so each test is an ordinary sync function --
    no pytest-asyncio dependency, and ``tmp_path`` composes cleanly.
    """

    async def _runner() -> Any:
        app = web.Application()
        preview_service = register_deliverable_routes(app, require_api_access=lambda _request: None)
        register_evolve_agent_routes(
            app,
            require_api_access=lambda _request: None,  # auth stubbed out
            root_resolver=lambda: repo,
        )
        if configure is not None:
            configure(app)
        client = TestClient(TestServer(app), cookie_jar=CookieJar(unsafe=True))
        await client.start_server()
        preview_service.configure(main_origin=str(client.make_url("/")).rstrip("/"))
        try:
            return await body(client)
        finally:
            await client.close()
            await preview_service.stop()

    prior_data_dir = os.environ.get("THOMAS_DATA_DIR")
    os.environ["THOMAS_DATA_DIR"] = str(repo.parent / "thomas-test-data")
    try:
        return asyncio.run(_runner())
    finally:
        if prior_data_dir is None:
            os.environ.pop("THOMAS_DATA_DIR", None)
        else:
            os.environ["THOMAS_DATA_DIR"] = prior_data_dir


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


def test_unregistered_conversation_opens_from_the_project_the_list_found_it_in(tmp_path: Path) -> None:
    """A conversation with no registry row still opens, in its own project.

    The registry only knows conversations whose creator wrote a row. Plenty do
    not: measured on a live workspace, 65 of the 108 tasks the Code sidebar
    displayed had no row at all. Listing found them anyway -- it walks the known
    roots and reads what is there -- while every other endpoint resolved through
    the registry and fell back to the catalog root, where those files are not.
    So the sidebar offered 65 tasks that answered 404 when clicked, could not be
    renamed or deleted, and left the project chip naming whatever was open
    before. This pins list and open to the same answer.
    """

    repo = _new_repo(tmp_path)
    project = tmp_path / "own-project"
    project.mkdir()
    _init_repo(project)

    # One bound conversation is what puts `project` on the map of known roots;
    # the conversation under test is written beside it with no row of its own.
    forge_code_projects.bind_conversation(repo, "conv-bound", project)
    orphan = forge_code_store.new_conversation(project, title="Written straight into the project")
    cid = orphan["id"]
    assert forge_code_projects.conversation_metadata(repo, cid) is None

    async def _body(client: TestClient) -> None:
        listing = await (await client.get("/api/evolve/agent/conversations")).json()
        row = next(c for c in listing["conversations"] if c["id"] == cid)
        assert row["project_root"] == str(project)

        # Opening it agrees with the listing instead of 404ing.
        resp = await client.get(f"/api/evolve/agent/conversations/{cid}")
        assert resp.status == 200
        fetched = await resp.json()
        assert fetched["conversation"]["project_root"] == str(project)

        # And so does every other id-addressed operation, which used to act on
        # the catalog root and therefore on nothing.
        resp = await client.post(f"/api/evolve/agent/conversations/{cid}/rename", json={"title": "Renamed"})
        assert resp.status == 200
        assert forge_code_store.load_conversation(project, cid)["title"] == "Renamed"

        resp = await client.delete(f"/api/evolve/agent/conversations/{cid}")
        assert resp.status == 200
        assert forge_code_store.load_conversation(project, cid) is None

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
        created = await (await client.post("/api/evolve/agent/conversations/new", json={})).json()
        cid = created["conversation"]["id"]
        forge_code_store.append_agent_turn(
            repo,
            cid,
            model="test",
            transcript="",
            changed_files=["reverted.txt", "kept.txt"],
            returncode=0,
            ok=True,
            noop=False,
            reason="two files changed",
        )
        # /changes reports both dirty files with a real, non-empty diff.
        resp = await client.get("/api/evolve/agent/changes", params={"cid": cid})
        assert resp.status == 200
        payload = await resp.json()
        assert payload["ok"] is True
        by_file = {entry["file"]: entry for entry in payload["changed"]}
        assert "reverted.txt" in by_file
        assert "kept.txt" in by_file
        assert "+local edit" in by_file["reverted.txt"]["diff"]
        assert by_file["reverted.txt"]["untracked"] is False

        # Revert is destructive, so the first exact request pauses for approval.
        resp = await client.post(
            "/api/evolve/agent/revert",
            json={"file": "reverted.txt", "conversation_id": cid},
        )
        assert resp.status == 409
        approval_id = (await resp.json())["approval"]["id"]
        assert (await client.post("/api/evolve/agent/approve", json={"approval_id": approval_id})).status == 200

        # The one-time approval restores only this conversation-owned file.
        resp = await client.post(
            "/api/evolve/agent/revert",
            json={"file": "reverted.txt", "conversation_id": cid, "approval_id": approval_id},
        )
        assert resp.status == 200
        result = await resp.json()
        assert result["ok"] is True
        assert result["clean"] is True
        assert "reverted.txt" not in forge_code_git.changed_files(repo)

        # Keep is a no-op on disk: the file stays changed.
        resp = await client.post(
            "/api/evolve/agent/keep",
            json={"file": "kept.txt", "conversation_id": cid},
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


def test_send_and_changes_fail_closed_when_git_evidence_is_unavailable(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo = _new_repo(tmp_path)
    original_snapshot = forge_code_git.snapshot

    def _snapshot_failure(_root: Path) -> dict[str, str]:
        raise forge_code_git.ForgeCodeGitError("snapshot unavailable")

    def _evidence_failure(_root: Path, _files: list[str]) -> list[dict[str, Any]]:
        raise forge_code_git.ForgeCodeGitError("diff evidence unavailable")

    async def _body(client: TestClient) -> None:
        monkeypatch.setattr(forge_code_git, "snapshot", _snapshot_failure)
        send = await client.post("/api/evolve/agent/send", json={"message": "Build a local page"})
        assert send.status == 503
        assert (await send.json())["code"] == "git_status_unavailable"
        assert forge_code_store.list_conversations(repo) == []

        monkeypatch.setattr(forge_code_git, "snapshot", original_snapshot)
        created = await (await client.post("/api/evolve/agent/conversations/new", json={})).json()
        cid = created["conversation"]["id"]
        (repo / "index.html").write_text("<h1>Proof</h1>", encoding="utf-8")
        forge_code_store.append_agent_turn(
            repo,
            cid,
            model="test",
            transcript="",
            changed_files=["index.html"],
            returncode=0,
            ok=True,
            noop=False,
            reason="built page",
        )
        monkeypatch.setattr(forge_code_git, "change_evidence", _evidence_failure)
        changes = await client.get("/api/evolve/agent/changes", params={"cid": cid})
        assert changes.status == 503
        assert (await changes.json())["code"] == "git_status_unavailable"

    _drive(repo, _body)


def test_empty_chatgpt_oauth_token_is_an_explicit_auth_failure(monkeypatch: Any) -> None:
    app = web.Application()
    app[APP_SECRETS] = object()

    async def _empty_token(*_args: Any, **_kwargs: Any) -> str:
        return ""

    monkeypatch.setattr(evolve_agent_http_support, "ensure_openai_codex_access_token", _empty_token)
    token, response = asyncio.run(evolve_agent_http_support.prepare_code_oauth_credential(app, "gpt"))

    assert token == ""
    assert response is not None
    assert response.status == 503
    assert json.loads(response.text)["code"] == "chatgpt_auth_unavailable"


def test_artifact_serves_built_html_sandboxed_and_refuses_non_artifacts(tmp_path: Path) -> None:
    """The artifact route serves the REAL bytes of a file this build wrote, from
    an isolated preview origin, and refuses anything that is not a build artifact
    or that escapes the repo root."""
    repo = _new_repo(tmp_path)
    # A clean, committed file is NOT an artifact (not dirty, not recorded).
    (repo / "committed.txt").write_text("secret\n", encoding="utf-8")
    _commit_all(repo)
    # The build's real output: an HTML page now dirty in the working tree.
    page = (
        '<!doctype html><title>Hi</title><link rel="stylesheet" href="/assets/styles.css">'
        '<h1>Built by Forge</h1><script type="module" src="/src/main.js"></script>'
    )
    (repo / "index.html").write_text(page, encoding="utf-8")
    (repo / "assets").mkdir()
    (repo / "assets" / "styles.css").write_text("h1 { color: gold; }\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "main.js").write_text(
        "fetch('/data.json'); new Worker('/worker.js', {type: 'module'});\n",
        encoding="utf-8",
    )
    (repo / "data.json").write_text('{"ready": true}\n', encoding="utf-8")
    (repo / "worker.js").write_text("self.postMessage('ready');\n", encoding="utf-8")
    (repo / "internal.py").write_text("SECRET = 'not a preview artifact'\n", encoding="utf-8")

    async def _body(client: TestClient) -> None:
        created = await (await client.post("/api/evolve/agent/conversations/new", json={})).json()
        cid = created["conversation"]["id"]
        forge_code_store.append_agent_turn(
            repo,
            cid,
            model="test",
            transcript="",
            changed_files=[
                "index.html",
                "assets/styles.css",
                "src/main.js",
                "data.json",
                "worker.js",
                "internal.py",
            ],
            returncode=0,
            ok=True,
            noop=False,
            reason="built page",
        )
        # The dirty HTML page moves to a separate capability-gated origin so its
        # root-relative assets and workers run without sharing Thomas's origin.
        redirect = await client.get(f"/api/evolve/agent/artifact/{cid}/index.html", allow_redirects=False)
        assert redirect.status == 302
        assert "no-store" in redirect.headers["Cache-Control"]
        resp = await client.get(f"/api/evolve/agent/artifact/{cid}/index.html")
        assert resp.status == 200
        assert resp.url.host == "127.0.0.1"
        assert resp.url.port != client.server.port
        assert resp.url.path == "/index.html"
        assert "Built by Forge" in await resp.text()
        csp = resp.headers["Content-Security-Policy"]
        assert "sandbox allow-scripts allow-forms allow-same-origin" in csp
        assert "style-src 'self' 'unsafe-inline' data:" in csp
        assert "connect-src 'self'" in csp
        assert "worker-src 'self' blob:" in csp
        assert "form-action 'self'" in csp
        assert resp.headers["Referrer-Policy"] == "no-referrer"
        assert "no-store" in resp.headers["Cache-Control"]
        preview_origin = f"{resp.url.scheme}://{resp.url.host}:{resp.url.port}"
        for path in ("/assets/styles.css", "/src/main.js", "/data.json", "/worker.js"):
            assert (await client.session.get(preview_origin + path)).status == 200
        assert (await client.session.get(preview_origin + "/api/models")).status == 404
        assert (await client.get(f"/api/evolve/agent/artifact/{cid}/assets/styles.css")).status == 200
        assert (await client.get(f"/api/evolve/agent/artifact/{cid}/src/main.js")).status == 200
        assert (await client.get(f"/api/evolve/agent/artifact/{cid}/internal.py")).status == 404
        invalid = await client.get(f"/api/evolve/agent/artifact-content/{'0' * 64}/{cid}/index.html")
        assert invalid.status == 404

        # Artifact access is scoped to the conversation that produced the file.
        other = await (await client.post("/api/evolve/agent/conversations/new", json={})).json()
        other_cid = other["conversation"]["id"]
        assert (await client.get(f"/api/evolve/agent/artifact/{other_cid}/index.html")).status == 404

        # A committed (clean) file is not an artifact of any build -> 404.
        assert (await client.get(f"/api/evolve/agent/artifact/{cid}/committed.txt")).status == 404

        # A path that escapes the repo root is refused even if dirty-looking.
        escaped = await client.get(f"/api/evolve/agent/artifact/{cid}/../../etc/passwd")
        assert escaped.status == 404

    _drive(repo, _body)


def test_done_frame_carries_artifacts_for_renderable_run() -> None:
    """The detector wired into the done frame produces an artifact descriptor for a
    run that wrote an .html file, and none for a .py-only run."""
    from thomas.forge.anvil.forge_code_store import detect_artifacts

    assert detect_artifacts(["index.html"]) == [{"file": "index.html", "kind": "html", "ext": "html"}]
    assert detect_artifacts(["thomas/server/foo.py"]) == []


def test_done_sse_frame_requires_process_success_and_a_real_delta(tmp_path: Path) -> None:
    """A clean process exit without a file delta is a no-op, never completion."""
    repo = _new_repo(tmp_path)

    class _FinishedProcess:
        def __init__(self, returncode: int) -> None:
            self.returncode = returncode

    async def _assert_done(client: TestClient, expected_ok: bool, expected_rc: int, expected_noop: bool) -> None:
        response = await client.get("/api/evolve/agent/stream")
        assert response.status == 200
        frames = [
            json.loads(line.removeprefix("data: "))
            for line in (await response.text()).splitlines()
            if line.startswith("data: ")
        ]
        done = next(frame for frame in frames if frame.get("type") == "done")
        assert done["returncode"] == expected_rc
        assert done["ok"] is expected_ok
        assert done["noop"] is expected_noop
        assert done["outcome"] == ("noop" if expected_noop else "failed")

    def _configure(app: web.Application, returncode: int) -> None:
        result = {
            "persistence_confirmed": True,
            "returncode": returncode,
            "ok": False,
            "noop": returncode == 0,
            "outcome": "noop" if returncode == 0 else "failed",
            "changed_files": [],
            "artifacts": [],
        }
        recording = asyncio.get_running_loop().create_future()
        recording.set_result(result)
        app[APP_EVOLVE_AGENT_TASK] = _FinishedProcess(returncode)
        app[APP_EVOLVE_AGENT_DRAIN] = recording

    _drive(repo, lambda client: _assert_done(client, False, 7, False), configure=lambda app: _configure(app, 7))
    _drive(repo, lambda client: _assert_done(client, False, 0, True), configure=lambda app: _configure(app, 0))


def test_sse_reconnect_cursor_replays_only_unseen_events_for_the_exact_run(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)
    transcript = repo / "run-cursor.txt"
    transcript.write_text(
        '{"fc":"say","text":"first"}\n{"fc":"say","text":"second"}\n',
        encoding="utf-8",
    )

    class _FinishedProcess:
        returncode = 0

    def _configure(app: web.Application) -> None:
        result = {
            "persistence_confirmed": True,
            "returncode": 0,
            "ok": True,
            "noop": False,
            "outcome": "completed",
            "changed_files": ["result.txt"],
            "artifacts": [],
        }
        recording = asyncio.get_running_loop().create_future()
        recording.set_result(result)
        proc = _FinishedProcess()
        app[APP_EVOLVE_AGENT_TASK] = proc
        app[APP_EVOLVE_AGENT_DRAIN] = {"generation": 2, "run_id": "run-cursor", "task": recording}
        app[APP_EVOLVE_AGENT_SESSION] = {
            "generation": 2,
            "run_id": "run-cursor",
            "conversation_id": "conversation-cursor",
            "transcript": str(transcript),
            "proc": proc,
        }

    async def _body(client: TestClient) -> None:
        response = await client.get("/api/evolve/agent/stream?run_id=run-cursor&cursor=1")
        assert response.status == 200
        lines = (await response.text()).splitlines()
        frames = [json.loads(line.removeprefix("data: ")) for line in lines if line.startswith("data: ")]
        assert [frame["event_seq"] for frame in frames] == [2, 3]
        assert [frame["event_id"] for frame in frames] == ["run-cursor:2", "run-cursor:3"]
        assert [line.removeprefix("id: ") for line in lines if line.startswith("id: ")] == [
            "run-cursor:2",
            "run-cursor:3",
        ]
        assert frames[0]["text"] == "second"
        assert frames[1]["type"] == "done"

    _drive(repo, _body, configure=_configure)


def test_revert_is_conversation_owned_read_only_aware_and_state_bound(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)
    (repo / "owned.txt").write_text("original\n", encoding="utf-8")
    (repo / "outsider.txt").write_text("original\n", encoding="utf-8")
    (repo / "readonly.txt").write_text("original\n", encoding="utf-8")
    _commit_all(repo)
    (repo / "owned.txt").write_text("original\nagent edit\n", encoding="utf-8")
    (repo / "outsider.txt").write_text("original\nuser edit\n", encoding="utf-8")
    (repo / "readonly.txt").write_text("original\nagent edit\n", encoding="utf-8")

    async def _body(client: TestClient) -> None:
        writable = await (await client.post("/api/evolve/agent/conversations/new", json={})).json()
        cid = writable["conversation"]["id"]
        forge_code_store.append_agent_turn(
            repo,
            cid,
            model="test",
            transcript="",
            changed_files=["owned.txt"],
            returncode=0,
            ok=True,
            noop=False,
            reason="owned file changed",
        )

        # No conversation context can never fall back to arbitrary working-tree dirt.
        missing_context = await client.post("/api/evolve/agent/revert", json={"file": "outsider.txt"})
        assert missing_context.status == 400
        assert (await missing_context.json())["code"] == "conversation_required"

        # A real conversation cannot discard a dirty file it did not create/change.
        outsider = await client.post(
            "/api/evolve/agent/revert",
            json={"file": "outsider.txt", "conversation_id": cid},
        )
        assert outsider.status == 403
        assert (await outsider.json())["code"] == "file_not_owned_by_conversation"
        assert "user edit" in (repo / "outsider.txt").read_text(encoding="utf-8")

        # Approval is bound to current state. Editing after approval invalidates it.
        pending = await client.post(
            "/api/evolve/agent/revert",
            json={"file": "owned.txt", "conversation_id": cid},
        )
        first_id = (await pending.json())["approval"]["id"]
        assert pending.status == 409
        assert (await client.post("/api/evolve/agent/approve", json={"approval_id": first_id})).status == 200
        (repo / "owned.txt").write_text("original\nagent edit changed after approval\n", encoding="utf-8")
        stale = await client.post(
            "/api/evolve/agent/revert",
            json={"file": "owned.txt", "conversation_id": cid, "approval_id": first_id},
        )
        stale_payload = await stale.json()
        assert stale.status == 409
        assert stale_payload["code"] == "approval_required"
        second_id = stale_payload["approval"]["id"]
        assert second_id != first_id
        assert (await client.post("/api/evolve/agent/approve", json={"approval_id": second_id})).status == 200
        reverted = await client.post(
            "/api/evolve/agent/revert",
            json={"file": "owned.txt", "conversation_id": cid, "approval_id": second_id},
        )
        assert reverted.status == 200
        assert (await reverted.json())["clean"] is True

        # Read-only mode refuses mutation before offering any destructive approval.
        read_only = await (
            await client.post(
                "/api/evolve/agent/conversations/new",
                json={"file_access": "read_only"},
            )
        ).json()
        read_only_cid = read_only["conversation"]["id"]
        forge_code_store.append_agent_turn(
            repo,
            read_only_cid,
            model="test",
            transcript="",
            changed_files=["readonly.txt"],
            returncode=0,
            ok=True,
            noop=False,
            reason="read-only fixture",
        )
        blocked = await client.post(
            "/api/evolve/agent/revert",
            json={"file": "readonly.txt", "conversation_id": read_only_cid},
        )
        assert blocked.status == 403
        assert (await blocked.json())["code"] == "read_only_mode"
        assert "agent edit" in (repo / "readonly.txt").read_text(encoding="utf-8")

    _drive(repo, _body)


def test_revert_untracked_file_requires_exact_approval_before_delete(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)
    generated = repo / "generated.tmp"
    generated.write_text("build output\n", encoding="utf-8")

    async def _body(client: TestClient) -> None:
        created = await (await client.post("/api/evolve/agent/conversations/new", json={})).json()
        cid = created["conversation"]["id"]
        forge_code_store.append_agent_turn(
            repo,
            cid,
            model="test",
            transcript="",
            changed_files=["generated.tmp"],
            returncode=0,
            ok=True,
            noop=False,
            reason="generated file",
        )
        pending = await client.post(
            "/api/evolve/agent/revert",
            json={"file": "generated.tmp", "conversation_id": cid},
        )
        payload = await pending.json()
        assert pending.status == 409
        assert generated.exists()
        approval_id = payload["approval"]["id"]
        assert (await client.post("/api/evolve/agent/approve", json={"approval_id": approval_id})).status == 200
        deleted = await client.post(
            "/api/evolve/agent/revert",
            json={
                "file": "generated.tmp",
                "conversation_id": cid,
                "approval_id": approval_id,
                "request_id": "revert-generated-once",
            },
        )
        assert deleted.status == 200
        result = await deleted.json()
        assert result["reason"] == "deleted untracked file"
        assert not generated.exists()
        replayed = await client.post(
            "/api/evolve/agent/revert",
            json={
                "file": "generated.tmp",
                "conversation_id": cid,
                "approval_id": approval_id,
                "request_id": "revert-generated-once",
            },
        )
        replayed_result = await replayed.json()
        assert replayed.status == 200
        assert replayed_result == {**result, "replayed": True}

    _drive(repo, _body)


def test_code_file_preview_is_bounded_to_selected_repository(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "src" / "main.js").write_text("const ready = true;\n", encoding="utf-8")

    async def _body(client: TestClient) -> None:
        created = await (
            await client.post("/api/evolve/agent/conversations/new", json={"project_root": str(repo)})
        ).json()
        cid = created["conversation"]["id"]
        preview = await client.get(f"/api/evolve/agent/conversations/{cid}/file", params={"path": "src/main.js"})
        body = await preview.json()
        assert preview.status == 200
        assert body["content"].splitlines() == ["const ready = true;"]
        escaped = await client.get(f"/api/evolve/agent/conversations/{cid}/file", params={"path": "../secret.txt"})
        assert escaped.status == 400

    _drive(repo, _body)


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
        resp = await client.post("/api/evolve/agent/stop", json={"run_id": "run-stop"})
        assert resp.status == 409
        body = await resp.json()
        assert body["ok"] is False
        assert body["stopped"] is False
        assert body["termination_confirmed"] is False
        assert body["code"] == "no_active_run"

    _drive(repo, _body)


def test_stop_claims_stopped_only_after_process_wait_confirms_exit(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo = _new_repo(tmp_path)

    class _RunningProcess:
        pid = 417
        returncode: int | None = None

        async def wait(self) -> int:
            self.returncode = -15
            return self.returncode

    proc = _RunningProcess()
    monkeypatch.setattr(evolve_agent_runtime, "_kill_tree", lambda target: setattr(target, "kill_requested", True))

    async def _body(client: TestClient) -> None:
        resp = await client.post("/api/evolve/agent/stop", json={"run_id": "run-stop"})
        payload = await resp.json()
        assert resp.status == 200
        assert payload["ok"] is True
        assert payload["stopped"] is True
        assert payload["termination_confirmed"] is True
        assert payload["state"] == "terminated"
        assert payload["returncode"] == -15
        assert proc.kill_requested is True

    def _configure(app: web.Application) -> None:
        app[APP_EVOLVE_AGENT_TASK] = proc
        app[APP_EVOLVE_AGENT_SESSION] = {"run_id": "run-stop"}

    _drive(repo, _body, configure=_configure)


def test_status_reports_recording_and_stop_waits_for_persistence(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo = _new_repo(tmp_path)
    captured: dict[str, Any] = {}

    class _RunningProcess:
        pid = 419
        returncode: int | None = None

        async def wait(self) -> int:
            self.returncode = -15
            return self.returncode

    proc = _RunningProcess()
    monkeypatch.setattr(evolve_agent_runtime, "_kill_tree", lambda _target: None)

    def _configure(app: web.Application) -> None:
        app[APP_EVOLVE_AGENT_TASK] = proc
        app[APP_EVOLVE_AGENT_SESSION] = {"run_id": "run-recording"}
        app[APP_EVOLVE_AGENT_DRAIN] = asyncio.get_running_loop().create_future()
        captured["app"] = app

    async def _body(client: TestClient) -> None:
        status = await (await client.get("/api/evolve/agent/status")).json()
        assert status["running"] is True
        assert status["recording"] is True

        stop_request = asyncio.create_task(client.post("/api/evolve/agent/stop", json={"run_id": "run-recording"}))
        await asyncio.sleep(0.02)
        assert stop_request.done() is False
        captured["app"][APP_EVOLVE_AGENT_DRAIN].set_result(
            {
                "persistence_confirmed": True,
                "returncode": -15,
                "ok": False,
                "noop": False,
                "outcome": "failed",
                "changed_files": [],
                "artifacts": [],
            }
        )
        response = await stop_request
        receipt = await response.json()
        assert response.status == 200
        assert receipt["termination_confirmed"] is True
        assert receipt["persistence_confirmed"] is True

        finished = await (await client.get("/api/evolve/agent/status")).json()
        assert finished["running"] is False
        assert finished["recording"] is False

    _drive(repo, _body, configure=_configure)


def test_send_rejects_a_new_run_while_the_prior_result_is_recording(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path)
    captured: dict[str, Any] = {}

    class _FinishedProcess:
        returncode = 0

    def _configure(app: web.Application) -> None:
        recording = asyncio.get_running_loop().create_future()
        app[APP_EVOLVE_AGENT_TASK] = _FinishedProcess()
        app[APP_EVOLVE_AGENT_DRAIN] = {"generation": 4, "run_id": "run-prior", "task": recording}
        captured["recording"] = recording

    async def _body(client: TestClient) -> None:
        response = await client.post(
            "/api/evolve/agent/send",
            json={"message": "Start the next build", "request_id": "request-next"},
        )
        payload = await response.json()
        assert response.status == 409
        assert payload["code"] == "agent_result_recording"
        assert captured["recording"].done() is False
        captured["recording"].cancel()

    _drive(repo, _body, configure=_configure)


def test_unconfirmed_process_stop_returns_pending_receipt(monkeypatch: Any) -> None:
    class _StuckProcess:
        pid = 418
        returncode = None

        async def wait(self) -> int:
            await asyncio.sleep(1)
            return 0

    monkeypatch.setattr(evolve_agent_runtime, "_kill_tree", lambda _target: None)
    receipt = asyncio.run(evolve_agent_runtime._terminate_process(_StuckProcess(), timeout_s=0.01))

    assert receipt == {
        "ok": False,
        "stopped": False,
        "termination_confirmed": False,
        "state": "termination_pending",
        "code": "termination_pending",
        "returncode": None,
    }


def test_steering_requires_a_live_run_and_returns_restart_receipt(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    repo = _new_repo(tmp_path)

    class _RunningProcess:
        returncode = None

    process = _RunningProcess()
    killed: list[Any] = []
    monkeypatch.setattr(evolve_agent_routes, "_kill_tree", killed.append)

    async def _body(client: TestClient) -> None:
        empty = await client.post("/api/evolve/agent/steer", json={"message": "  "})
        assert empty.status == 400

        response = await client.post(
            "/api/evolve/agent/steer",
            json={"message": "Keep the API, simplify the interface", "run_id": "run-steer"},
        )
        payload = await response.json()
        assert response.status == 202
        assert payload == {
            "ok": True,
            "stop_requested": True,
            "restart_required": True,
            "message": "Keep the API, simplify the interface",
        }
        for _attempt in range(20):
            if killed:
                break
            await asyncio.sleep(0.01)
        assert killed == [process]

        stale = await client.post(
            "/api/evolve/agent/steer",
            json={"message": "stale request", "run_id": "run-old"},
        )
        assert stale.status == 409
        assert (await stale.json())["code"] == "run_not_active"
        assert killed == [process]

    def _configure(app: web.Application) -> None:
        app[APP_EVOLVE_AGENT_TASK] = process
        app[APP_EVOLVE_AGENT_SESSION] = {"run_id": "run-steer"}

    _drive(repo, _body, configure=_configure)


def test_external_project_conversation_persists_settings_and_scopes_tree(tmp_path: Path) -> None:
    catalog = _new_repo(tmp_path)
    project = tmp_path / "selected-project"
    project.mkdir()
    _init_repo(project)
    (project / "src").mkdir()
    (project / "src" / "main.py").write_text("print('selected')\n", encoding="utf-8")
    (project / ".thomas").mkdir()

    async def _body(client: TestClient) -> None:
        response = await client.post(
            "/api/evolve/agent/conversations/new",
            json={
                "title": "Selected project",
                "project_root": str(project),
                "model": "codex:gpt",
                "model_id": "gpt-5.6-codex",
                "reasoning_effort": "high",
                "autonomy_level": 4,
                "file_access": "pc",
                "memory": False,
                "guardrails": "open",
                "token_economy": "cheap",
            },
        )
        assert response.status == 200
        created = (await response.json())["conversation"]
        cid = created["id"]
        assert created["project_root"] == str(project.resolve())
        assert created["settings"]["effective"]["model"] == "gpt-5.6-codex"
        assert created["settings"]["support"]["file_access"]["effective"] == "pc"

        fetched = (await (await client.get(f"/api/evolve/agent/conversations/{cid}")).json())["conversation"]
        assert fetched["project_root"] == str(project.resolve())
        assert fetched["settings"] == created["settings"]
        listing = (await (await client.get("/api/evolve/agent/conversations")).json())["conversations"]
        assert next(item for item in listing if item["id"] == cid)["project_root"] == str(project.resolve())

        tree_response = await client.get(f"/api/evolve/agent/conversations/{cid}/tree")
        assert tree_response.status == 200
        tree = await tree_response.json()
        assert tree["project_root"] == str(project.resolve())
        assert {entry["name"] for entry in tree["entries"]} == {"src"}
        nested = await (await client.get(f"/api/evolve/agent/conversations/{cid}/tree?path=src")).json()
        assert [entry["path"] for entry in nested["entries"]] == ["src/main.py"]
        assert (await client.get(f"/api/evolve/agent/conversations/{cid}/tree?path=..")).status == 400

    _drive(catalog, _body)


def test_send_passes_raw_prompt_to_gpt_without_local_semantic_approval(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    catalog = _new_repo(tmp_path)
    project = tmp_path / "selected-project"
    project.mkdir()
    _init_repo(project)
    spawned: dict[str, Any] = {}

    class _EmptyStdout:
        async def readline(self) -> bytes:
            return b""

    class _FinishedProcess:
        pid = 1234
        returncode = 0
        stdout = _EmptyStdout()

        def __init__(self) -> None:
            self.stdin = _GateInput()

        async def wait(self) -> int:
            return 0

    async def _spawn(executable: str, *args: str, **kwargs: Any) -> _FinishedProcess:
        spawned.update({"executable": executable, "args": args, **kwargs})
        proc = _FinishedProcess()
        proc.start_token = kwargs["env"]["THOMAS_CODE_START_TOKEN"]
        spawned["proc"] = proc
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn)

    async def _access_token(_profile: str, *, secret_store: object) -> str:
        assert secret_store is not None
        return "live-oauth-token"

    monkeypatch.setattr(evolve_agent_http_support, "ensure_openai_codex_access_token", _access_token)

    async def _body(client: TestClient) -> None:
        raw_prompt = "Review this build, then deploy it to production"
        created = await (
            await client.post(
                "/api/evolve/agent/conversations/new",
                json={"title": "GPT build", "project_root": str(project)},
            )
        ).json()
        cid = created["conversation"]["id"]
        response = await client.post(
            "/api/evolve/agent/send",
            json={
                "conversation_id": cid,
                "project_root": str(project),
                "message": raw_prompt,
                "model": "codex:gpt",
                "model_id": "gpt-5.6-codex",
                "reasoning_effort": "xhigh",
                "autonomy_level": 4,
                "file_access": "full",
                "memory": True,
                "guardrails": "fortress",
                "token_economy": "max",
            },
        )
        assert response.status == 200
        payload = await response.json()
        assert payload["conversation_id"] == cid
        assert payload["project_root"] == str(project.resolve())
        assert payload["settings"]["support"]["reasoning_effort"]["status"] == "applied"
        assert payload["settings"]["support"]["autonomy_level"]["status"] == "applied"
        assert payload["settings"]["support"]["file_access"]["status"] == "applied"
        assert payload["settings"]["support"]["file_access"]["effective"] == "full"
        assert payload["settings"]["support"]["guardrails"]["effective"] == "fortress"
        assert payload["settings"]["support"]["memory"]["effective"] == "conversation_history"
        assert spawned["stdin"] is asyncio.subprocess.PIPE
        assert spawned["env"]["THOMAS_CODE_START_GATE"] == "pipe"
        assert spawned["env"]["THOMAS_CODE_RUN_ID"] == payload["run_id"]
        assert spawned["env"]["THOMAS_CODE_REQUEST_ID"] == payload["request_id"]
        # The runaway ceiling, not a per-tier budget: cd0203a7 removed pass
        # limits (abandoning nearly-working code saves nothing), so every
        # economy reports the same generous cap.
        assert payload["settings"]["support"]["token_economy"]["max_fix_iters"] == 20

        assert spawned["cwd"] == str(project.resolve())
        args = list(spawned["args"])
        assert args[:3] == ["-m", "thomas.forge.anvil.forge_code_runner", "--project-root"]
        assert raw_prompt not in args
        assert args[args.index("--profile") + 1] == "forgecode"
        assert "--chatgpt-connected" not in args
        assert args[args.index("--autonomy") + 1] == "4"
        assert args[args.index("--file-access") + 1] == "full"
        assert args[args.index("--memory") + 1] == "on"
        assert args[args.index("--guardrails") + 1] == "fortress"
        assert args[args.index("--token-economy") + 1] == "max"
        env = spawned["env"]
        assert env["THOMAS_MODELS_FORGECODE_MODEL"] == "gpt-5.6-codex"
        assert env["THOMAS_MODELS_FORGECODE_REASONING_EFFORT"] == "xhigh"
        assert str(Path(evolve_agent_routes.__file__).resolve().parents[3]) in env["PYTHONPATH"].split(os.pathsep)
        gate_payload = json.loads(spawned["proc"].stdin.data.decode())
        assert gate_payload["gate_token"] == spawned["proc"].start_token
        assert gate_payload["oauth_access_token"] == "live-oauth-token"
        assert gate_payload["goal"] == raw_prompt
        assert "live-oauth-token" not in " ".join(args)
        assert "live-oauth-token" not in json.dumps(env)
        assert spawned["proc"].stdin.closed is True

        # A completed turn can be followed by another turn in the same Code
        # conversation, preserving its project and durable history identity.
        for _ in range(100):
            status = await (await client.get("/api/evolve/agent/status")).json()
            if status.get("running") is False:
                break
            await asyncio.sleep(0.01)
        assert status["running"] is False
        follow_up = await client.post(
            "/api/evolve/agent/send",
            json={"conversation_id": cid, "project_root": str(project), "message": "improve it"},
        )
        assert follow_up.status == 200
        follow_up_payload = await follow_up.json()
        assert follow_up_payload["conversation_id"] == cid
        assert follow_up_payload["run_id"] != payload["run_id"]
        assert json.loads(spawned["proc"].stdin.data.decode())["goal"] == "improve it"
        for _ in range(100):
            status = await (await client.get("/api/evolve/agent/status")).json()
            if status.get("running") is False:
                break
            await asyncio.sleep(0.01)
        assert status["running"] is False

        other = tmp_path / "other-project"
        other.mkdir()
        _init_repo(other)
        changed = await client.post(
            "/api/evolve/agent/send",
            json={"conversation_id": cid, "project_root": str(other), "message": "move it"},
        )
        assert changed.status == 409
        assert (await changed.json())["code"] == "project_change_requires_new_conversation"

    def _configure(app: web.Application) -> None:
        app[APP_SECRETS] = object()  # type: ignore[assignment]

    _drive(catalog, _body, configure=_configure)


def test_chatgpt_transport_failure_is_structured_and_never_launches(
    tmp_path: Path,
    monkeypatch: Any,
    caplog: Any,
) -> None:
    catalog = _new_repo(tmp_path)
    project = tmp_path / "selected-project"
    project.mkdir()
    _init_repo(project)

    async def _access_token(_profile: str, *, secret_store: object) -> str:
        assert secret_store is not None
        raise evolve_agent_http_support.OpenAICodexOAuthError("refresh_token=TOP_SECRET_REFRESH")

    async def _must_not_spawn(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("Code must not spawn after OAuth preparation fails")

    monkeypatch.setattr(evolve_agent_http_support, "ensure_openai_codex_access_token", _access_token)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _must_not_spawn)

    async def _body(client: TestClient) -> None:
        response = await client.post(
            "/api/evolve/agent/send",
            json={
                "message": "build it",
                "project_root": str(project),
                "model": "codex:gpt",
                "request_id": "oauth-transport-failure",
            },
        )
        assert response.status == 503
        payload = await response.json()
        assert payload == {
            "ok": False,
            "error": "ChatGPT authentication is temporarily unavailable. Retry or reconnect in Easy Setup.",
            "code": "chatgpt_auth_unavailable",
            "retryable": True,
        }
        assert evolve_agent_runtime._action_receipt(catalog, "run", "oauth-transport-failure") is None
        assert forge_code_store.list_conversations(project) == []
        assert "TOP_SECRET_REFRESH" not in caplog.text

    def _configure(app: web.Application) -> None:
        app[APP_SECRETS] = object()  # type: ignore[assignment]

    _drive(catalog, _body, configure=_configure)
