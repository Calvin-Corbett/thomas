"""The self-change project list names what it could not read, and Chat reads that list through a read-only tool.

You asked Chat "What are you working on on yourself right now? List each of your own projects that is running" and
it answered "No self-development projects are currently running", without a tool call, while three ran
(2026-09-29). The list behind it, GET /api/self/projects, caught the error from a green folder it could not read and
answered an empty list. Now it names what it could not read, in ``unreadable``, and still lists the rest; Chat's
read-only ``self.projects`` tool reads the same list. The route runs through its own handler in this process
(``make_mocked_request``, no socket).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from thomas.core.config import load_config
from thomas.server import green_checkout, green_handoff
from thomas.server.app_helpers import _build_tools
from thomas.server.chat_tool_policy import _is_classified_tool
from thomas.server.chat_tool_policy_model import _SAFE_READ_TOOLS
from thomas.server.routes import self_project_routes as routes

CONVERSATIONS = Path(".thomas") / "evolve" / "agent" / "conversations"
RUNNING = {"conversation_id": "thomas-aaa", "title": "Fix the voice button", "state": "running", "detail": "going"}
STOPPED = {"conversation_id": "thomas-bbb", "title": "Tidy the logs", "state": "stopped", "detail": "it ended"}


# --- the list names what it could not read -------------------------------------------------------------------


def _green(root: Path, eid: str, cid: str) -> Path:
    folder = root / "work" / eid / CONVERSATIONS
    folder.mkdir(parents=True)
    project = {"execution_id": eid}
    (folder / f"{cid}.json").write_text(json.dumps({"id": cid, "title": cid, "thomas_project": project}), "utf-8")
    return folder


def _deny(monkeypatch: pytest.MonkeyPatch, denied: Path) -> None:
    """Make one folder, or one file, unreadable the way a folder of another Windows account is."""

    def guard(original: Any) -> Any:
        def call(self: Path, *args: Any, **kwargs: Any) -> Any:
            if self == denied:
                raise PermissionError(13, "Access is denied", str(self))
            return original(self, *args, **kwargs)

        return call

    for name in ("iterdir", "glob", "read_bytes"):
        monkeypatch.setattr(Path, name, guard(getattr(Path, name)))


@pytest.fixture
def greens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "green"
    monkeypatch.setattr(green_checkout, "green_root", lambda: root)
    monkeypatch.setattr(green_handoff, "sibling_changes", lambda _id: {})
    monkeypatch.setattr(routes.thomas_project, "project_phase", lambda *_a: ("waiting", "a Build run is going"))
    monkeypatch.setattr(routes.thomas_project, "_catalog_root", lambda: tmp_path / "catalog")
    return root


def _listed() -> dict[str, Any]:
    """What GET /api/self/projects answers, from the route's own handler."""
    app = web.Application()
    routes.register_self_project_routes(app, require_loopback=lambda _request: None)
    [handler] = [r.handler for r in app.router.routes() if r.method == "GET" and r.resource.canonical == routes.PATH]
    response = asyncio.run(handler(make_mocked_request("GET", routes.PATH, app=app)))
    assert response.status == 200
    return json.loads(response.body)


def test_an_unreadable_green_folder_is_named_not_answered_as_an_empty_list(greens: Path, monkeypatch) -> None:
    _green(greens, "thomas-aaa", "fc_aaa")
    _deny(monkeypatch, greens / "work")

    body = _listed()

    assert body["ok"] is True and body["projects"] == []
    assert len(body["unreadable"]) == 1
    assert str(greens / "work") in body["unreadable"][0] and "Access is denied" in body["unreadable"][0]


def test_one_unreadable_green_is_named_and_the_others_are_still_listed(greens: Path, monkeypatch) -> None:
    _green(greens, "thomas-aaa", "fc_aaa")
    _green(greens, "thomas-bbb", "fc_bbb")
    _deny(monkeypatch, greens / "work" / "thomas-bbb" / CONVERSATIONS)

    body = _listed()

    assert [row["conversation_id"] for row in body["projects"] if row["state"] == "running"] == ["fc_aaa"]
    assert [row["execution_id"] for row in body["projects"] if row["state"] == "unreadable"] == ["thomas-bbb"]
    assert body["unreadable"] == []
    assert len(body["warnings"]) == 1 and "thomas-bbb" in body["warnings"][0]


def test_a_file_that_disappears_mid_read_is_skipped_without_dropping_every_project(greens, monkeypatch) -> None:
    _green(greens, "thomas-aaa", "fc_aaa")
    gone = _green(greens, "thomas-bbb", "fc_bbb") / "fc_bbb.json"
    open_file = Path.open

    def vanish(self: Path, *args, **kwargs):
        if self == gone:
            raise FileNotFoundError(2, "No such file", str(self))
        return open_file(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", vanish)

    body = _listed()

    assert [row["conversation_id"] for row in body["projects"]] == ["fc_aaa"]
    assert body["unreadable"] == []


def test_list_projects_still_answers_the_list_alone(greens: Path) -> None:
    _green(greens, "thomas-aaa", "fc_aaa")

    rows = routes.list_projects(routes.thomas_project._catalog_root())

    assert [row["conversation_id"] for row in rows] == ["fc_aaa"]


# --- the self.projects tool ----------------------------------------------------------------------------------


def _tool_text(report: dict[str, Any]) -> str:
    from thomas.tools.self_projects import SelfProjectsTool

    result = asyncio.run(SelfProjectsTool(lambda: report).execute({}))
    assert result.ok
    return str(result.data)


def test_chat_has_the_tool_and_may_always_read_it() -> None:
    assert "self.projects" in _build_tools(load_config())
    assert "self.projects" in _SAFE_READ_TOOLS and _is_classified_tool("self.projects")


def test_the_tool_lists_each_project_and_its_state() -> None:
    text = _tool_text({"ok": True, "projects": [RUNNING, STOPPED], "unreadable": []})

    assert "Fix the voice button" in text and "thomas-aaa" in text and "running" in text
    assert "Tidy the logs" in text and "stopped" in text
    assert "could not be read" not in text


def test_the_tool_says_first_what_it_could_not_read() -> None:
    text = _tool_text({"ok": True, "projects": [], "unreadable": ["green/work could not be read (Access is denied)"]})

    first = text.splitlines()[0]
    assert "could not be read" in first and "Access is denied" in text
    assert "No self-change project is going" not in text


def test_the_registered_tool_reads_the_listing_route(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes, "read_projects", lambda *a, **k: {"ok": True, "projects": [RUNNING], "unreadable": []})

    result = asyncio.run(_build_tools(load_config()).get("self.projects").execute({}))

    assert result.ok and "Fix the voice button" in str(result.data)
