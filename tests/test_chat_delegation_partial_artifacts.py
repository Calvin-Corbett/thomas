"""Failed output remains downloadable without becoming verified evidence."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.core import task_bot_runtime
from thomas.server.chat_delegation_session import _normalize_record
from thomas.server.routes import deliverable_aiohttp as deliverables
from thomas.server.routes import deliverable_listing
from thomas.server.routes.chat_v2_session_routes import guard_chat_v2_read, handle_session_delegations


def _record() -> dict:
    return {
        "execution_id": "exec-partial",
        "conversation_id": "own-chat",
        "state": "failed",
        "proof_status": "failed",
        "proof": {},
        "blocker": "strict_receipt_unverified",
        "salvaged_artifacts": ["partial report.txt", "draft.html"],
    }


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(deliverable_listing, "_WORKSPACES_BASE", tmp_path / "workspaces")
    work = tmp_path / "workspaces" / "exec-partial"
    work.mkdir(parents=True)
    (work / "partial report.txt").write_text("Unreviewed text result", encoding="utf-8")
    (work / "draft.html").write_text("<html><script>window.bad = true</script></html>", encoding="utf-8")
    return work


@pytest.mark.asyncio
async def test_partial_files_reach_the_api_and_require_existing_download_authorization(workspace, monkeypatch):
    record = _record()
    monkeypatch.setattr(task_bot_runtime, "list_user_executions", lambda *_args, **_kwargs: [record])
    monkeypatch.setattr(task_bot_runtime, "get_execution", lambda *_args, **_kwargs: record)

    def require_access(request: web.Request) -> None:
        if request.headers.get("Authorization") != "Bearer fixture":
            raise web.HTTPUnauthorized()

    app = web.Application()
    app.router.add_get(
        "/api/v2/chat/session/{session_id}/delegations",
        guard_chat_v2_read(handle_session_delegations, require_access),
    )
    service = deliverables.register_deliverable_routes(app, require_api_access=require_access)
    client = TestClient(TestServer(app))
    await client.start_server()
    headers = {"Authorization": "Bearer fixture"}
    try:
        denied = await client.get("/api/v2/chat/session/own-chat/delegations")
        assert denied.status == 401
        response = await client.get("/api/v2/chat/session/own-chat/delegations", headers=headers)
        row = (await response.json())["delegations"][0]
        assert row["state"] == "failed" and row["receipt"]["ok"] is False
        assert row["proof_status"] == "failed" and row["proof"] == {}
        assert row["artifacts"] == [] and row["artifact_url"] == ""
        assert row["verification_label"] == ""
        assert len(row["partial_artifacts"]) == 2
        for artifact in row["partial_artifacts"]:
            assert artifact["status"] == "unverified"
            assert artifact["kind"] == "file"
            assert artifact["url"].endswith("?download=1")
            denied = await client.get(artifact["url"], allow_redirects=False)
            assert denied.status == 401
            download = await client.get(artifact["url"], headers=headers, allow_redirects=False)
            assert download.status == 200 and "Location" not in download.headers
            assert "attachment" in download.headers["Content-Disposition"]
            assert await download.read() == (workspace / artifact["path"]).read_bytes()
        other = await client.get("/api/v2/chat/session/other-chat/delegations", headers=headers)
        assert (await other.json())["delegations"] == []
        outside = await client.get("/deliverable/exec-partial/..%2f..%2foutside.txt?download=1", headers=headers)
        assert outside.status == 404
    finally:
        await client.close()
        await service.stop()


def test_partial_files_reject_missing_outside_absolute_and_hidden_paths(workspace):
    outside = workspace.parent.parent / "outside.txt"
    outside.write_text("not a deliverable")
    (workspace / ".secret").write_text("not a deliverable")
    record = _record()
    record["salvaged_artifacts"] += [
        "partial report.txt",
        "missing.txt",
        "../../outside.txt",
        "..\\..\\outside.txt",
        str(outside),
        "C:/outside.txt",
        "C:outside.txt",
        "/outside.txt",
        ".secret",
        {"path": "draft.html"},
    ]
    row = _normalize_record(record)
    assert [item["path"] for item in row["partial_artifacts"]] == ["partial report.txt", "draft.html"]
    assert _normalize_record({**record, "execution_id": "../exec-partial"})["partial_artifacts"] == []


def test_partial_files_reject_symlink_escape(workspace):
    outside = workspace.parent.parent / "outside.txt"
    outside.write_text("not a deliverable")
    try:
        (workspace / "escape.txt").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"File symlinks unavailable: {exc}")
    assert _normalize_record({**_record(), "salvaged_artifacts": ["escape.txt"]})["partial_artifacts"] == []


@pytest.mark.parametrize("state", ["executing", "completed", "verified", "cancelled", "abandoned"])
def test_only_unsuccessful_terminal_records_expose_partial_files(workspace, state):
    row = _normalize_record({**_record(), "state": state})
    assert bool(row["partial_artifacts"]) is (state in {"cancelled", "abandoned"})
    assert row["artifacts"] == []


def test_partial_files_reject_hardlinked_external_content(workspace):
    import os

    outside = workspace.parent.parent / "outside.txt"
    outside.write_text("external content")
    os.link(outside, workspace / "linked.txt")
    row = _normalize_record({**_record(), "salvaged_artifacts": ["linked.txt"]})
    assert row["partial_artifacts"] == []


def _directory_link(target: Path, alias: Path) -> None:
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(alias))
    else:
        alias.symlink_to(target, target_is_directory=True)


def _remove_directory_link(alias: Path) -> None:
    if os.name == "nt":
        alias.rmdir()
    else:
        alias.unlink()


@asynccontextmanager
async def _downloads():
    app = web.Application()
    service = deliverables.register_deliverable_routes(app, require_api_access=lambda _request: None)
    client = TestClient(TestServer(app))
    await client.start_server()
    try:
        yield client
    finally:
        await client.close()
        await service.stop()


@pytest.mark.asyncio
async def test_execution_directory_alias_cannot_list_or_download_sibling_output(workspace):
    offered = _normalize_record(_record())["partial_artifacts"][0]["url"]
    other = workspace.with_name("exec-other")
    workspace.rename(other)
    _directory_link(other, workspace)
    try:
        assert deliverable_listing._workspace_dir("exec-partial") is None
        assert _normalize_record(_record())["partial_artifacts"] == []
        async with _downloads() as client:
            stale = await client.get(offered, allow_redirects=False)
            assert stale.status == 404
            own = await client.get("/deliverable/exec-other/partial%20report.txt?download=1")
            assert own.status == 200
            assert await own.read() == (other / "partial report.txt").read_bytes()
    finally:
        _remove_directory_link(workspace)


@pytest.mark.asyncio
async def test_directory_alias_to_hidden_metadata_is_rechecked_at_download(workspace):
    visible = workspace / "visible"
    visible.mkdir()
    (visible / "config").write_text("ordinary output")
    record = {**_record(), "salvaged_artifacts": ["visible/config"]}
    offered = _normalize_record(record)["partial_artifacts"][0]["url"]
    (visible / "config").unlink()
    visible.rmdir()
    hidden = workspace / ".git"
    hidden.mkdir()
    (hidden / "config").write_text("private repository settings")
    _directory_link(hidden, visible)
    try:
        assert _normalize_record(record)["partial_artifacts"] == []
        async with _downloads() as client:
            stale = await client.get(offered, allow_redirects=False)
            assert stale.status == 404
    finally:
        _remove_directory_link(visible)


@pytest.mark.asyncio
async def test_previously_offered_file_cannot_download_replacement_hardlink(workspace):
    artifact = _normalize_record(_record())["partial_artifacts"][0]
    outside = workspace.parent.parent / "private.txt"
    outside.write_text("unrelated external content")
    target = workspace / artifact["path"]
    target.unlink()
    os.link(outside, target)
    assert artifact["path"] not in [item["path"] for item in _normalize_record(_record())["partial_artifacts"]]
    async with _downloads() as client:
        stale = await client.get(artifact["url"], allow_redirects=False)
        assert stale.status == 404
