"""An unplugged drive must not delete your projects."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thomas.server.routes import local_projects_helpers_aiohttp as helpers


class _App(dict):
    pass


@pytest.fixture()
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _App:
    registry = tmp_path / "projects.json"
    monkeypatch.setattr(helpers, "_registry_path", lambda _app: registry)
    return _App()


def _seed(app: _App, projects: list[dict[str, Any]]) -> None:
    helpers._write_registry(app, projects)


def test_a_project_on_an_offline_drive_is_kept(app: _App, tmp_path: Path) -> None:
    """The data-loss path. _refresh_projects used to drop unreachable projects,
    and its callers write the result straight back over the registry -- so one
    ordinary action on one project erased every project that was offline at that
    moment. Both of this user's real projects live on a second physical drive."""
    here = tmp_path / "OnDisk"
    here.mkdir()
    _seed(app, [
        {"id": "p-here", "name": "OnDisk", "root_path": str(here)},
        {"id": "p-gone", "name": "FreedomFlappy", "root_path": r"F:\DevHub\projects\FreedomFlappy"},
    ])

    refreshed = helpers._refresh_projects(app)

    ids = {p["id"] for p in refreshed}
    assert ids == {"p-here", "p-gone"}, "an unreachable project was dropped"


def test_the_unreachable_one_is_marked_offline(app: _App, tmp_path: Path) -> None:
    here = tmp_path / "OnDisk"
    here.mkdir()
    _seed(app, [
        {"id": "p-here", "name": "OnDisk", "root_path": str(here)},
        {"id": "p-gone", "name": "Gone", "root_path": str(tmp_path / "nope")},
    ])

    by_id = {p["id"]: p for p in helpers._refresh_projects(app)}

    assert by_id["p-gone"]["offline"] is True
    assert by_id["p-here"]["offline"] is False


def test_saving_after_a_refresh_does_not_shrink_the_registry(app: _App, tmp_path: Path) -> None:
    """The actual sequence that loses data: refresh, then persist."""
    here = tmp_path / "OnDisk"
    here.mkdir()
    _seed(app, [
        {"id": "p-here", "name": "OnDisk", "root_path": str(here)},
        {"id": "p-gone", "name": "Gone", "root_path": str(tmp_path / "unplugged")},
    ])

    helpers._write_registry(app, helpers._refresh_projects(app))
    stored = json.loads(helpers._registry_path(app).read_text(encoding="utf-8"))

    assert len(stored["projects"]) == 2, "persisting a refresh deleted an offline project"


def test_remembered_detail_is_not_overwritten_while_offline(app: _App, tmp_path: Path) -> None:
    """A dossier rebuilt from a folder that is not there would replace real
    remembered detail with empty defaults."""
    _seed(app, [{
        "id": "p-gone", "name": "FreedomTMS", "root_path": str(tmp_path / "unplugged"),
        "framework": "Workspace", "summary": "Transit management system",
    }])

    project = helpers._refresh_projects(app)[0]

    assert project["name"] == "FreedomTMS"
    assert project["summary"] == "Transit management system"
