"""Contributors in Settings, with its row on and off, in a real browser.

The row is ``thomas.server.rows.contributors``, its route is ``thomas.server.routes.contributors`` and the counting is
``thomas.core.contributors``. The route, a server started with the row off and a caller with no token are in
``tests/test_turning_contributors_off_touches_only_its_routes.py``. The section is drawn by
``thomas/server/web/settings.contributors-panel.js``.

Every sentence of the row's words is in ``SENTENCES`` with the tests that show it, and the last test fails when a sentence
is added, changed or dropped without this list.
"""

from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.row_page_fixture import serving
from tests.row_proof_fixture import ROOT, ROWS
from tests.web_fixtures.thomas_chat_fixture import browser_ok

pytestmark = pytest.mark.skipif(not browser_ok(), reason="playwright chromium unavailable")

WORDS = next(row for row in ROWS if row.id == "contributors").config["words"]
WINDOW = {"width": 1400, "height": 900}
PROOFS = (
    "test_the_contributors_section_with_its_row_on_and_off.py",
    "test_turning_contributors_off_touches_only_its_routes.py",
)
SENTENCES = {
    "Shows how many of the changes to this copy of Thomas were made by Thomas, by Claude, by Codex and by you, over "
    "all time and over the last 30 days, in Settings under Contributors.": (
        "test_the_section_shows_the_counts_for_all_time_and_the_last_thirty_days",
    ),
    "It only reads the record of changes and changes nothing.": ("test_reading_the_counts_changes_nothing",),
    "While this is off, Contributors in Settings says the counts are not available, and nothing else changes.": (
        "test_with_the_row_off_the_section_says_the_counts_are_not_available",
        "test_with_the_row_off_the_server_starts_and_every_other_row_is_up",
    ),
    "The page asks once each time you open it, so nothing repeats.": (
        "test_the_section_asks_once_each_time_you_open_it",
        "test_with_the_row_off_the_section_asks_once_and_the_page_stays_quick",
    ),
    "A Contributors page you already have open keeps its numbers until you leave it and come back.": (
        "test_a_section_already_open_keeps_its_numbers_until_you_come_back",
    ),
}
ASKED = "/api/contributors"
# Lag of the page's own timer over three seconds, which a page spinning on a failed fetch would blow through.
LAG = """() => new Promise((done) => {
    let worst = 0, last = performance.now(), n = 0;
    const timer = setInterval(() => {
        const now = performance.now();
        worst = Math.max(worst, now - last - 100);
        last = now;
        if (++n >= 30) { clearInterval(timer); done(Math.round(worst)); }
    }, 100);
})"""


def _get(base: str, path: str) -> Any:
    with urllib.request.urlopen(base + path, timeout=120) as answer:  # noqa: S310 - a server of this test
        return json.loads(answer.read())


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


def _in_words(count: int) -> str:
    return f"{count:,} {'change' if count == 1 else 'changes'}"


class _Settings:
    """The Settings page in a browser tab, counting what it asks the server for."""

    def __init__(self, browser: Any, base: str) -> None:
        self.base = base
        self.page = browser.new_page(viewport=WINDOW)
        self.asked: list[str] = []
        self.page.on("request", lambda request: self.asked.append(request.url.replace(base, "").partition("?")[0]))
        self.page.goto(base + "/settings", wait_until="domcontentloaded")
        self.page.wait_for_selector("button[data-section='contributors']")

    def count(self) -> int:
        return self.asked.count(ASKED)

    def open(self, wait_for: str) -> None:
        self.page.click("button[data-section='contributors']")
        self.page.wait_for_function(
            "(text) => document.getElementById('contributorsHost').innerText.toLowerCase().includes(text)",
            arg=wait_for,
            timeout=60000,
        )

    def leave(self) -> None:
        self.page.click("button[data-section='autonomy']")

    def text(self) -> str:
        return self.page.inner_text("#contributorsHost")

    def close(self) -> None:
        self.page.close()


@pytest.fixture(scope="module")
def walked(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, Any]]:
    from playwright.sync_api import sync_playwright

    seen: dict[str, Any] = {}
    folder = tmp_path_factory.mktemp("contributors-window")
    with serving(folder) as base, sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        before_files, before_head, before_status = (
            _files(folder),
            _git("rev-parse", "HEAD"),
            _git("status", "--porcelain"),
        )
        seen["reading"] = _get(base, ASKED)
        seen["files_added"] = sorted(_files(folder) - before_files - {"server.log"})
        seen["git_unchanged"] = (_git("rev-parse", "HEAD"), _git("status", "--porcelain")) == (
            before_head,
            before_status,
        )
        settings = _Settings(browser, base)
        settings.open("all time")
        seen["on_text"] = settings.text()
        settings.page.wait_for_timeout(5000)
        seen["on_asked_after_wait"] = settings.count()
        settings.leave()
        settings.open("all time")
        settings.page.wait_for_timeout(3000)
        seen["on_asked_after_reopen"] = settings.count()
        seen["pressed_off"] = _post(base, "/api/plugins/thomas/contributors/off")
        settings.page.wait_for_timeout(3000)
        seen["open_after_off"] = settings.text()
        seen["asked_while_open_after_off"] = settings.count()
        settings.leave()
        settings.open("not available")
        seen["back_after_off"] = settings.text()
        settings.page.wait_for_timeout(1000)
        seen["asked_after_coming_back"] = settings.count()
        settings.close()
        fresh = _Settings(browser, base)
        fresh.open("not available")
        fresh.page.wait_for_timeout(7000)
        seen["off_text"] = fresh.text()
        seen["off_asked"] = fresh.count()
        seen["off_total"] = len(fresh.asked)
        seen["off_lag"] = fresh.page.evaluate(LAG)
        fresh.close()
        seen["pressed_on"] = _post(base, "/api/plugins/thomas/contributors/on")
        again = _Settings(browser, base)
        again.open("all time")
        seen["on_again_text"] = again.text()
        again.close()
        browser.close()
    return seen


def test_the_section_shows_the_counts_for_all_time_and_the_last_thirty_days(walked: dict[str, Any]) -> None:
    reading, text = walked["reading"], walked["on_text"]
    assert reading["error"] == ""
    assert reading["commits"] == sum(reading["total"].values()) > 0
    assert "all time" in text.lower() and "last 30 days" in text.lower()
    for actor, name in (("thomas", "Thomas"), ("claude", "Claude"), ("codex", "Codex"), ("you", "You")):
        assert re.search(rf"{name}\s+{re.escape(_in_words(reading['total'][actor]))}", text), (name, text)
    assert _in_words(reading["recent"]["you"]) in text.lower().split("last 30 days")[1]


def test_reading_the_counts_changes_nothing(walked: dict[str, Any]) -> None:
    """Nothing is written to the data or memory folders and git has the same head and the same changes after it."""
    assert walked["files_added"] == []
    assert walked["git_unchanged"] is True
    script = (ROOT / "thomas" / "server" / "web" / "settings.contributors-panel.js").read_text(encoding="utf-8")
    assert "POST" not in script and "PUT" not in script and "DELETE" not in script


def test_the_section_asks_once_each_time_you_open_it(walked: dict[str, Any]) -> None:
    assert walked["on_asked_after_wait"] == 1
    assert walked["on_asked_after_reopen"] == 2


def test_a_section_already_open_keeps_its_numbers_until_you_come_back(walked: dict[str, Any]) -> None:
    assert walked["pressed_off"] == 200
    assert walked["open_after_off"] == walked["on_text"]
    assert walked["asked_while_open_after_off"] == 2  # nothing asked for it, so nothing replaced the numbers
    assert "not available" in walked["back_after_off"]
    assert walked["asked_after_coming_back"] == 3


def test_with_the_row_off_the_section_says_the_counts_are_not_available(walked: dict[str, Any]) -> None:
    assert walked["off_text"] == (
        "The counts are not available because Contributors is turned off. You can turn it back on under Plugins."
    )
    assert walked["pressed_on"] == 200
    assert "all time" in walked["on_again_text"].lower()


def test_with_the_row_off_the_section_asks_once_and_the_page_stays_quick(walked: dict[str, Any]) -> None:
    """Over seven seconds the section asked once, and the page's own timer ran on time."""
    assert walked["off_asked"] == 1, walked["off_asked"]
    assert walked["off_total"] < 40, walked["off_total"]
    assert walked["off_lag"] < 500, walked["off_lag"]


def test_every_sentence_of_the_words_names_the_test_that_shows_it() -> None:
    """The words are what you are told, so none lands on the strength of having been true once."""
    written = [*re.split(r"(?<=\.)\s+", WORDS["about"]), *re.split(r"(?<=\.)\s+", WORDS["off_means"])]
    assert written == list(SENTENCES)
    proofs = "".join((ROOT / "tests" / name).read_text(encoding="utf-8") for name in PROOFS)
    named = {name for names in SENTENCES.values() for name in names}
    assert {name for name in named if f"def {name}(" not in proofs} == set()
