"""Off hides your saved interface changes from every page and deletes none of them, on a real server.

These are the proofs of ``thomas.server.rows.overlay`` for what the file of saved changes does through off and on. The file
is in the data folder of a server of its own, and the pages are read over HTTP, five of them. The routes and the fresh
process are in ``tests/test_turning_overlay_off_touches_only_its_routes.py``, and what a window shows is in
``tests/test_the_overlay_row_says_what_a_window_shows.py``.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.row_page_fixture import serving

# "/mission" was in this list while it was Mission Control, a page that carried your changes. Its address now leads to
# System, which does not (the row's words: "System and Library do not show them"), so it is not a page to walk here.
PAGES = ("/", "/classic", "/settings", "/companion")
ANCHOR = {
    "exact": True,
    "fragile": False,
    "component": "aside",
    "label": "Chat sidebar",
    "policy": "move resize",
    "path": "",
}
SAVED = [
    {"op": "set", "kind": "token", "address": "token:nebula:--c-accent", "value": "#2ecc71"},
    {"op": "set", "kind": "identity", "address": "identity:name", "value": "Otto"},
    {
        "op": "set",
        "kind": "element",
        "address": "element:chat:desktop:chat.sidebar",
        "value": {"x": 0, "y": 0, "width": 320, "style": {"backgroundColor": "#101a2e"}},
        "anchor": ANCHOR,
    },
]
ACTION = {"actor": "test", "instruction": "seed", "targets": []}
THE_SPLICE = re.compile(
    r'(?:<style id="thomas-overlay-css">\n.*?</style>\n)?<script id="thomas-overlay-view" .*?</script>\n'
    r'<script src="/static/js/overlay_runtime.js\?v=[^"]*" defer></script>\n',
    re.S,
)
THE_MARKS = ("thomas-overlay-css", "thomas-overlay-view", "overlay_runtime.js")


def _ask(base: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, str]:
    request = urllib.request.Request(
        base + path,
        method="GET" if body is None else "POST",
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as answer:
            return answer.status, answer.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as refused:
        return refused.code, refused.read().decode("utf-8", "replace")


def _pages(base: str) -> dict[str, str]:
    found = {}
    for path in PAGES:
        status, html = _ask(base, path)
        assert status == 200, path
        found[path] = html
    return found


@pytest.fixture(scope="module")
def walked(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    """One server: your changes saved, then the pages with the row on, off, and on again, and the file at each."""
    folder = tmp_path_factory.mktemp("overlay-keeps")
    saved_file = folder / "data" / "overlay" / "manifest.json"
    with serving(folder) as base:
        status, body = _ask(base, "/api/ui/overlay/records", {"overlay_id": None, "action": ACTION, "records": SAVED})
        assert status == 200, body
        seen: dict[str, Any] = {"before": saved_file.read_bytes(), "on": _pages(base)}
        seen["off_pressed"] = _ask(base, "/api/plugins/thomas/overlay/off", {})[0]
        seen["off"] = _pages(base)
        seen["off_file"] = saved_file.read_bytes()
        seen["off_routes"] = [_ask(base, "/api/ui/overlay")[0], _ask(base, "/api/ui/overlay/manifest")[0]]
        seen["on_pressed"] = _ask(base, "/api/plugins/thomas/overlay/on", {})[0]
        seen["on_again"] = _pages(base)
        seen["on_again_file"] = saved_file.read_bytes()
        seen["on_again_routes"] = [_ask(base, "/api/ui/overlay")[0], _ask(base, "/api/ui/overlay/manifest")[0]]
        yield seen


def test_with_the_row_on_every_page_carries_your_saved_changes(walked: dict[str, Any]) -> None:
    for path, html in walked["on"].items():
        assert ":root{--c-accent:#2ecc71;}" in html, path
        assert '"name":"Otto"' in html, path
        assert "/static/js/overlay_runtime.js" in html, path


def test_with_the_row_off_no_page_carries_any_of_them(walked: dict[str, Any]) -> None:
    assert walked["off_pressed"] == 200
    assert set(walked["off"]) == set(PAGES)
    for path, html in walked["off"].items():
        assert [mark for mark in THE_MARKS if mark in html] == [], path
        assert "#2ecc71" not in html and "Otto" not in html, path


def test_off_changes_nothing_in_the_page_but_the_splice(walked: dict[str, Any]) -> None:
    """Whatever else a page carries, such as its build stamp, is the same with the row on and off."""
    for path, html in walked["off"].items():
        assert THE_SPLICE.search(walked["on"][path]), path
        assert THE_SPLICE.sub("", walked["on"][path]) == html, path


def test_off_deletes_nothing_the_saved_file_is_the_same_bytes(walked: dict[str, Any]) -> None:
    assert walked["before"]
    assert walked["off_file"] == walked["before"]
    assert walked["on_again_file"] == walked["before"]


def test_turned_back_on_every_page_carries_them_exactly_as_before(walked: dict[str, Any]) -> None:
    assert walked["on_pressed"] == 200
    assert walked["on_again"] == walked["on"]


def test_the_routes_answer_404_while_off_and_the_saved_changes_again_when_on(walked: dict[str, Any]) -> None:
    assert walked["off_routes"] == [404, 404]
    assert walked["on_again_routes"] == [200, 200]
