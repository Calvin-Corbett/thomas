"""A stopped Thomas project's change can be retrieved without handing in or touching its green.

The route is the one ``thomas.server.rows.project_change`` registers; this builds its own app and calls the registrar.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from tests.green_support import git, make_blue
from thomas.server import green_checkout, green_handoff
from thomas.server.routes import self_project_routes


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    blue = make_blue(tmp_path)
    root = tmp_path / "greens"
    monkeypatch.setattr(green_checkout, "green_root", lambda: root)
    green = green_checkout.create_green(blue, "thomas-show-change")
    cid = "fc_show_change"
    folder = green.work / ".thomas" / "evolve" / "agent" / "conversations"
    folder.mkdir(parents=True)
    (folder / f"{cid}.json").write_text(
        json.dumps({"id": cid, "title": "Stopped repair", "thomas_project": {"execution_id": green.execution_id}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(self_project_routes.thomas_project, "_catalog_root", lambda: tmp_path / "catalog")
    monkeypatch.setattr(
        self_project_routes.thomas_project,
        "project_phase",
        lambda *_args: ("ended", "three repair rounds are spent"),
    )
    monkeypatch.setattr(green_handoff, "sibling_changes", lambda _eid: {})
    return green, cid, blue


def _get(cid: str, guard=None) -> tuple[int, dict]:
    from thomas.server.routes.self_project_change_routes import register_self_project_change_routes

    app = web.Application()
    register_self_project_change_routes(app, require_loopback=guard or (lambda _request: None))
    path = f"/api/self/projects/{cid}/change"
    handler = next(
        r.handler
        for r in app.router.routes()
        if r.method == "GET" and r.resource.canonical == path.replace(cid, "{conversation_id}")
    )
    response = asyncio.run(handler(make_mocked_request("GET", path, app=app, match_info={"conversation_id": cid})))
    return response.status, json.loads(response.body)


def _index(green: green_checkout.Green) -> bytes:
    return (green.git_dir / "index").read_bytes()


def test_stopped_project_excludes_nested_coordination_files_from_its_patch(project) -> None:
    green, cid, _blue = project
    folder = green.work / "plans" / "thomas" / "problems"
    folder.mkdir(parents=True)
    (folder / "not-team-work.md").write_text("local coordination\n", encoding="utf-8")
    (green.work / "thomas" / "fix_me.py").write_text("VALUE = 2\n", encoding="utf-8")

    status, body = _get(cid)

    assert status == 200
    assert body["patch"] == green_checkout.green_patch(green)
    assert "plans/thomas/problems/not-team-work.md" not in body["changed_files"]


@pytest.mark.parametrize("ignore_source", ["gitignore", "blue_exclude"])
def test_stopped_project_omits_ignored_new_files_already_staged_in_green(project, ignore_source) -> None:
    green, cid, blue = project
    ignored = "thomas_search.db-wal"
    if ignore_source == "gitignore":
        (green.work / ".gitignore").write_text(f"{ignored}\n", encoding="utf-8")
    else:
        exclude = blue / ".git" / "info" / "exclude"
        exclude.write_text(f"{ignored}\n", encoding="utf-8")
    (green.work / ignored).write_text("not a team change\n", encoding="utf-8")
    git(green.work, "add", "-f", ignored)
    (green.work / "thomas" / "fix_me.py").write_text("VALUE = 2\n", encoding="utf-8")

    status, body = _get(cid)

    assert status == 200
    assert body["patch"] == green_checkout.green_patch(green)
    assert ignored not in body["changed_files"]
    assert f"diff --git a/{ignored} b/{ignored}" not in body["patch"]


def test_stopped_project_exposes_the_exact_applicable_patch_without_changing_its_green(project, tmp_path) -> None:
    green, cid, blue = project
    (green.work / "thomas" / "fix_me.py").write_text("VALUE = 2\n", encoding="utf-8")
    (green.work / "new file.txt").write_text("new content\n", encoding="utf-8")
    # A staged edit should not be disturbed either.
    git(green.work, "add", "thomas/fix_me.py")
    before = (
        git(green.work, "rev-parse", "HEAD"),
        git(green.work, "status", "--porcelain=v1", "--untracked-files=all"),
        _index(green),
    )
    listed = self_project_routes.read_projects(tmp_path / "catalog")["projects"][0]
    # Force a stale index stat without changing content; do not run git between this touch and the route.
    unchanged = green.work / "README.md"
    stamp = unchanged.stat()
    os.utime(unchanged, ns=(stamp.st_atime_ns, stamp.st_mtime_ns + 5_000_000_000))

    status, body = _get(cid)

    index_after_route = _index(green)  # status itself can refresh the index; check bytes first.
    after = (
        git(green.work, "rev-parse", "HEAD"),
        git(green.work, "status", "--porcelain=v1", "--untracked-files=all"),
        index_after_route,
    )
    assert status == 200 and body["ok"] is True
    assert before == after
    assert body["conversation_id"] == cid
    assert body["execution_id"] == green.execution_id
    assert (body["state"], body["detail"]) == (listed["state"], listed["detail"])
    assert body["changed_files"] == [
        ".thomas/evolve/agent/conversations/fc_show_change.json",
        "new file.txt",
        "thomas/fix_me.py",
    ]
    assert body["patch"] == green_checkout.green_patch(green)
    fresh = tmp_path / "fresh"
    subprocess.run(["git", "clone", "-q", str(blue), str(fresh)], check=True)
    applied = subprocess.run(
        ["git", "apply", "--check", "-"],
        cwd=fresh,
        input=body["patch"].encode("utf-8", "surrogateescape"),
        capture_output=True,
    )
    assert applied.returncode == 0, applied.stderr
    subprocess.run(["git", "apply", "-"], cwd=fresh, input=body["patch"].encode("utf-8", "surrogateescape"), check=True)
    assert (fresh / "thomas" / "fix_me.py").read_text(encoding="utf-8") == "VALUE = 2\n"
    assert (fresh / "new file.txt").read_text(encoding="utf-8") == "new content\n"


def test_reading_change_does_not_rewrite_the_green_base_after_dev_was_merged(project) -> None:
    green, cid, blue = project
    (blue / "README.md").write_text("new blue commit\n", encoding="utf-8")
    git(blue, "add", "README.md")
    git(blue, "commit", "-qm", "new blue commit")
    git(green.work, "fetch", str(blue), "HEAD")
    git(green.work, "merge", "--no-edit", "FETCH_HEAD")
    (green.work / "thomas" / "fix_me.py").write_text("VALUE = 3\n", encoding="utf-8")
    record = green.git_dir / green_checkout.METADATA_NAME
    before = (
        record.read_bytes(),
        git(green.work, "rev-parse", "HEAD"),
        git(green.work, "status", "--porcelain=v1", "--untracked-files=all"),
        _index(green),
    )

    status, body = _get(cid)

    after = (
        record.read_bytes(),
        git(green.work, "rev-parse", "HEAD"),
        git(green.work, "status", "--porcelain=v1", "--untracked-files=all"),
        _index(green),
    )
    assert status == 200 and body["ok"] is True
    assert before == after
    assert body["patch"]  # The merged dev commit is not a change this project built.
    assert "new blue commit" not in body["patch"]


def test_an_unrelated_index_entry_does_not_join_the_change(project) -> None:
    green, cid, _blue = project
    (green.work / "index-only.txt").write_text("staged but not in the working tree\n", encoding="utf-8")
    git(green.work, "add", "index-only.txt")
    (green.work / "index-only.txt").unlink()
    before = _index(green)
    status, body = _get(cid)
    assert status == 200
    assert "index-only.txt" not in body["changed_files"]
    assert "index-only.txt" not in body["patch"]
    assert _index(green) == before


def test_unreadable_neighbor_does_not_hide_a_readable_projects_change(project, monkeypatch) -> None:
    green, cid, _blue = project
    (green.work / "thomas" / "fix_me.py").write_text("VALUE = 2\n", encoding="utf-8")
    conversation = json.loads(
        (green.work / ".thomas" / "evolve" / "agent" / "conversations" / f"{cid}.json").read_text(encoding="utf-8")
    )
    found = [(green.work, conversation)]

    def unreadable_neighbor(warnings=None):
        raise self_project_routes.GreensUnreadable(found, ["another green's conversations could not be read"])

    monkeypatch.setattr(self_project_routes, "_in_greens", unreadable_neighbor)
    status, body = _get(cid)

    assert status == 200 and body["ok"] is True
    assert body["conversation_id"] == cid
    assert body["patch"] == green_checkout.green_patch(green)
    assert body["changed_files"] == [
        ".thomas/evolve/agent/conversations/fc_show_change.json",
        "thomas/fix_me.py",
    ]


def test_unknown_project_is_not_a_green(project) -> None:
    status, body = _get("fc_unknown")
    assert status == 404 and body["ok"] is False


def test_catalog_only_project_is_not_a_green(project) -> None:
    green, cid, _blue = project
    catalog_record = green.work / ".thomas" / "evolve" / "agent" / "conversations" / f"{cid}.json"
    catalog_record_in_catalog = (
        green.blue.parent / "catalog" / ".thomas" / "evolve" / "agent" / "conversations" / f"{cid}.json"
    )
    catalog_record_in_catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog_record_in_catalog.write_bytes(catalog_record.read_bytes())
    status, body = _get(cid)
    assert status == 404 and body["ok"] is False


def test_invalid_conversation_id_is_rejected(project) -> None:
    status, body = _get("bad!id")
    assert status == 400 and body["ok"] is False


def test_project_with_missing_green_explains_why_it_cannot_show_a_change(project) -> None:
    green, cid, _blue = project
    shutil.rmtree(green.git_dir)
    status, body = _get(cid)
    assert status == 409 and body["ok"] is False
    assert "green" in body["error"].lower()


def test_unreadable_patch_explains_why_it_cannot_be_shown(project, monkeypatch: pytest.MonkeyPatch) -> None:
    _green, cid, _blue = project

    def unreadable(*_args):
        raise green_checkout.GreenUnavailable("git could not read the change")

    monkeypatch.setattr("thomas.server.routes.self_project_change_routes._git_bytes", unreadable)
    status, body = _get(cid)
    assert status == 409 and "git could not read the change" in body["error"]


def test_non_loopback_caller_is_refused_by_the_same_guard(project) -> None:
    _green, cid, _blue = project

    def deny(_request):
        raise web.HTTPForbidden(text="loopback only")

    with pytest.raises(web.HTTPForbidden) as refusal:
        _get(cid, guard=deny)
    assert refusal.value.text == "loopback only"
