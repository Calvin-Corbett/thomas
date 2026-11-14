"""The System Map row, on and off, on a real server.

The System Map page is gone. The row ``thomas.server.rows.system_map`` keeps the old address, which sends you to System,
and the reading at ``GET /api/system-map`` that other programs ask for. Its routes are registered by
``thomas.server.system_map_routes``. The routes, a server started with the row off and a caller with no token are in
``tests/test_turning_system_map_off_touches_only_its_routes.py``.

Every sentence of the row's words is in ``SENTENCES`` with the tests that show it, and the last test fails when a
sentence is added, changed or dropped without this list.
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.row_page_fixture import serving
from tests.row_proof_fixture import ROOT, ROWS

WORDS = next(row for row in ROWS if row.id == "system_map").config["words"]
WEB = ROOT / "thomas" / "server" / "web"
PROOFS = (
    "test_the_system_map_with_its_row_off.py",
    "test_turning_system_map_off_touches_only_its_routes.py",
)
SENTENCES = {
    "The System Map page is gone: its old address now sends you to System, and so do saved links to it.": (
        "test_the_old_address_sends_you_to_agents_and_keeps_the_embed_flag",
        "test_no_page_of_thomas_is_left_at_the_old_address",
    ),
    "This keeps that redirect and the reading, which other programs can still ask for: the branches, "
    "separate working copies and set-aside piles in this project, and how long since each was touched.": (
        "test_the_reading_lists_branches_working_copies_and_piles_with_their_age",
        "test_the_old_address_sends_you_to_agents_and_keeps_the_embed_flag",
    ),
    "It only shows what is there and changes nothing.": ("test_reading_the_map_changes_nothing",),
    "While this is off, the old System Map address answers 404: Not Found instead of sending you to System, and other "
    "programs cannot ask for the reading.": (
        "test_with_the_row_off_the_old_address_and_the_reading_answer_404",
        "test_with_the_row_off_every_route_answers_404_and_none_is_listed",
    ),
    "Nothing you see in Thomas changes, because no page of Thomas asks for it.": (
        "test_no_page_of_thomas_is_left_at_the_old_address",
    ),
    "The reading is made when asked and kept nowhere, so turning this on again gives a fresh one and nothing is lost.": (
        "test_reading_the_map_changes_nothing",
        "test_turned_back_on_the_old_address_redirects_and_the_map_is_read_afresh",
    ),
}


class _Stay(urllib.request.HTTPRedirectHandler):
    """Hand a redirect back as the answer it is, so the test sees where it points instead of following it."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _get(base: str, path: str) -> Any:
    with urllib.request.urlopen(base + path, timeout=120) as answer:  # noqa: S310 - a server of this test
        return json.loads(answer.read())


def _first_answer(base: str, path: str) -> tuple[int, str | None]:
    """The status and Location of the first answer, a redirect not followed."""
    opener = urllib.request.build_opener(_Stay)
    try:
        with opener.open(base + path, timeout=60) as answer:
            return int(answer.status), answer.headers.get("Location")
    except urllib.error.HTTPError as error:
        return int(error.code), error.headers.get("Location")


def _post(base: str, path: str) -> int:
    request = urllib.request.Request(
        base + path, data=b"{}", method="POST", headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=60) as answer:  # noqa: S310 - the same
        return int(answer.status)


def _files(folder: Path) -> set[str]:
    return {str(path.relative_to(folder)) for path in folder.rglob("*") if path.is_file()}


def _git(*args: str) -> str:
    done = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=60, check=False)
    return done.stdout


@pytest.fixture(scope="module")
def walked(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    seen: dict[str, Any] = {}
    folder = tmp_path_factory.mktemp("system-map-window")
    with serving(folder) as base:
        before_files, before_head, before_status = (
            _files(folder),
            _git("rev-parse", "HEAD"),
            _git("status", "--porcelain"),
        )
        seen["reading"] = _get(base, "/api/system-map")
        seen["files_added"] = sorted(_files(folder) - before_files - {"server.log"})
        seen["git_unchanged"] = (_git("rev-parse", "HEAD"), _git("status", "--porcelain")) == (
            before_head,
            before_status,
        )
        seen["on"] = {
            path: _first_answer(base, path)
            for path in ("/system-map", "/system-map/", "/system-map?embed=1", "/system-map/?embed=1")
        }
        seen["pressed_off"] = _post(base, "/api/plugins/thomas/system_map/off")
        seen["off"] = {path: _first_answer(base, path) for path in ("/system-map", "/system-map/", "/api/system-map")}
        seen["pressed_on"] = _post(base, "/api/plugins/thomas/system_map/on")
        seen["again"] = _get(base, "/api/system-map")
        seen["on_again"] = _first_answer(base, "/system-map")
        yield seen


def test_the_reading_lists_branches_working_copies_and_piles_with_their_age(walked: dict[str, Any]) -> None:
    reading = walked["reading"]
    assert reading["ok"] is True
    assert {"branches", "worktrees", "stashes"} <= set(reading)
    assert reading["branches"] and all("days_since" in item for item in reading["branches"]), reading["branches"][:1]
    assert re.search(r"exists? in this project|things? exist", reading["headline"]), reading["headline"]


def test_the_old_address_sends_you_to_agents_and_keeps_the_embed_flag(walked: dict[str, Any]) -> None:
    assert walked["on"] == {
        "/system-map": (302, "/agents"),
        "/system-map/": (302, "/agents"),
        "/system-map?embed=1": (302, "/agents?embed=1"),
        "/system-map/?embed=1": (302, "/agents?embed=1"),
    }


def test_no_page_of_thomas_is_left_at_the_old_address() -> None:
    """The page, its stylesheet and its script are deleted, and nothing in the web folder asks for the reading."""
    gone = ("system_map.html", "css/system_map.css", "js/system_map_page.js")
    assert [name for name in gone if (WEB / name).exists()] == []
    asking = [
        str(path.relative_to(WEB))
        for path in WEB.rglob("*")
        if path.suffix in {".html", ".js", ".css"}
        and "api/system-map" in path.read_text(encoding="utf-8", errors="replace")
    ]
    assert asking == []


def test_reading_the_map_changes_nothing(walked: dict[str, Any]) -> None:
    """Nothing is written to the data or memory folders and git has the same head and the same changes after it."""
    assert walked["files_added"] == []
    assert walked["git_unchanged"] is True


def test_with_the_row_off_the_old_address_and_the_reading_answer_404(walked: dict[str, Any]) -> None:
    assert walked["pressed_off"] == 200
    assert walked["off"] == {"/system-map": (404, None), "/system-map/": (404, None), "/api/system-map": (404, None)}


def test_turned_back_on_the_old_address_redirects_and_the_map_is_read_afresh(walked: dict[str, Any]) -> None:
    assert walked["pressed_on"] == 200
    assert walked["again"]["checked_at"] > walked["reading"]["checked_at"]
    assert walked["on_again"] == (302, "/agents")


def test_every_sentence_of_the_words_names_the_test_that_shows_it() -> None:
    """The words are what you are told, so none lands on the strength of having been true once."""
    written = [*re.split(r"(?<=\.)\s+", WORDS["about"]), *re.split(r"(?<=\.)\s+", WORDS["off_means"])]
    assert written == list(SENTENCES)
    proofs = "".join((ROOT / "tests" / name).read_text(encoding="utf-8") for name in PROOFS)
    named = {name for names in SENTENCES.values() for name in names}
    assert {name for name in named if f"def {name}(" not in proofs} == set()
