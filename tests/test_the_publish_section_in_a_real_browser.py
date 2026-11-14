"""The Publish to GitHub section of Settings, walked in a real browser against a real scratch server.

Proves thomas.server.rows.public_release, thomas.server.routes.public_release_routes and the page files
``settings.html`` and ``settings.publish-panel.js``. The server runs on a home, a data folder and a project catalog of
its own, and the release tool is replaced inside it by a stand-in that builds nothing and sends nothing, so the walk does
not depend on this checkout. It reads what the window shows: the words, the green ticks and red reasons, the button, the
answer after a sign-in, and what the section does with the row turned off, counting requests for ten seconds.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from tests.row_page_fixture import _SERVE, serving
from tests.web_fixtures.thomas_chat_fixture import browser_ok

WINDOW = {"width": 1280, "height": 900}
PAGE = "/settings"
OPEN = "button.sidebar-nav-item[data-section='publish']"
HOST = "#publishHost"

# The project catalog is the checkout the code runs from, so the server would list your real projects.
OWN_CATALOG = """\nimport sys
from pathlib import Path

from thomas.server import thomas_project

_catalog = Path(sys.argv[1]).parent / "catalog"
_catalog.mkdir(exist_ok=True)
thomas_project._catalog_root = lambda: _catalog
"""

# The release tool, as a stand-in. A file called mode.txt beside the memory folder chooses what the next preview is.
STAND_IN = """
import json
import time
from types import SimpleNamespace

from scripts.forge.publish import public_release as _release

_here = Path(sys.argv[1]).parent


class _Preview:
    def __init__(self, mode):
        bad = mode == "unsafe"
        self.facts = {
            "version": "9.9.9", "files": 5, "changed": 3, "branch": "release/9.9.9-2026-11-03",
            "remote_url": "https://example.invalid/org/thomas.git",
            "removed": {"a.py": "private security tooling", "b.py": "private security tooling",
                        "OWNER_STEPS.md": "steps for your own windows"},
            "checks": [
                {"name": "Private files are left out", "ok": True, "reason": "3 files left out"},
                {"name": "Publish safety checks", "ok": not bad, "reason": "1 unexpected file at the root" if bad else "every check passed"},
            ],
            "safe_to_publish": not bad, "digest": "digest-" + mode,
        }

    def to_dict(self):
        return self.facts

    def digest(self):
        return self.facts["digest"]

    def close(self):
        pass


def _build(repo, remote=None, **kw):
    time.sleep(4)
    return _Preview((_here / "mode.txt").read_text().strip())


def _confirm(preview):
    return None if (_here / "mode.txt").read_text().strip() == "decline" else object()


def _publish(preview, record, open_pr=False):
    (_here / "published.json").write_text(json.dumps({"digest": preview.digest()}))
    return SimpleNamespace(ok=True, dry_run=False, lines=["Sent version 9.9.9."], branch="release/9.9.9-2026-11-03",
                           branch_url="https://github.com/example/thomas/tree/release/9.9.9-2026-11-03", pr_url="", signed=False)


_release.build, _release.confirm, _release.publish = _build, _confirm, _publish
"""
SCRIPT = OWN_CATALOG + STAND_IN + _SERVE


def _mode(folder: Path, mode: str) -> None:
    (folder / "mode.txt").write_text(mode, encoding="utf-8")


def _open_the_section(page: Any, base: str) -> None:
    page.goto(base + PAGE)
    page.locator(OPEN).click()
    page.locator(f"{HOST} button").first.wait_for(state="visible", timeout=60000)


def _turn_off(base: str) -> None:
    request = urllib.request.Request(  # noqa: S310 - the scratch server on this machine
        base + "/api/plugins/thomas/public_release/off", data=b"{}", method="POST"
    )
    request.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(request, timeout=60) as answer:  # noqa: S310
        assert answer.status == 200


@pytest.fixture
def browser_page() -> Any:
    if not browser_ok():
        pytest.skip("playwright chromium unavailable")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        yield browser
        browser.close()


def test_the_section_asks_nothing_until_a_button_is_pressed_and_shows_what_would_go_public(
    browser_page: Any, tmp_path_factory: pytest.TempPathFactory
) -> None:
    folder = tmp_path_factory.mktemp("publish-page")
    _mode(folder, "safe")
    with serving(folder, script=SCRIPT) as base:
        page = browser_page.new_page(viewport=WINDOW)
        asked: list[str] = []
        page.on("request", lambda request: asked.append(request.url) if "/api/public-release" in request.url else None)
        _open_the_section(page, base)
        page.wait_for_timeout(3000)
        assert asked == []
        assert "Publish to GitHub" in page.locator("#publish .panel-title").inner_text()

        page.get_by_role("button", name="Look at what would go public").click()
        page.get_by_text("Working on it. This takes a few minutes, and nothing is being sent.").wait_for(timeout=15000)
        page.locator(".publish-heading").wait_for(timeout=60000)
        text = page.locator(HOST).inner_text()
        assert "Version 9.9.9: 5 files would go public." in text
        assert "3 private files are left out:" in text
        assert "2 × private security tooling" in text
        assert "3 files differ from the public copy now." in text
        assert "Where it goes: https://example.invalid/org/thomas.git, as the branch release/9.9.9-2026-11-03." in text
        assert "✓ Private files are left out: 3 files left out" in text
        assert page.locator(".publish-check.is-bad").count() == 0
        assert len(asked) <= 6, asked  # one to start, then one every three seconds while it worked

        before = len(asked)
        page.wait_for_timeout(4000)
        assert len(asked) == before  # it stopped asking once it had the answer

        page.get_by_role("button", name="Publish a review copy to GitHub").click()
        page.get_by_text("Sent to the branch release/9.9.9-2026-11-03.").wait_for(timeout=30000)
        link = page.get_by_role("link", name="Open the branch on GitHub")
        assert link.get_attribute("href").endswith("/tree/release/9.9.9-2026-11-03")
        assert json.loads((folder / "published.json").read_text(encoding="utf-8")) == {"digest": "digest-safe"}
        page.close()


def test_a_red_check_shows_its_reason_and_the_button_stays_off(
    browser_page: Any, tmp_path_factory: pytest.TempPathFactory
) -> None:
    folder = tmp_path_factory.mktemp("publish-unsafe")
    _mode(folder, "unsafe")
    with serving(folder, script=SCRIPT) as base:
        page = browser_page.new_page(viewport=WINDOW)
        _open_the_section(page, base)
        page.get_by_role("button", name="Look at what would go public").click()
        page.locator(".publish-heading").wait_for(timeout=60000)

        bad = page.locator(".publish-check.is-bad")
        assert bad.count() == 1 and "✗ Publish safety checks: 1 unexpected file at the root" in bad.inner_text()
        assert page.get_by_role("button", name="Publish a review copy to GitHub").is_disabled()
        assert "Not safe to publish yet. Fix the red items first." in page.locator(HOST).inner_text()
        assert not (folder / "published.json").exists()
        page.close()


def test_a_sign_in_you_decline_sends_nothing_and_says_so(
    browser_page: Any, tmp_path_factory: pytest.TempPathFactory
) -> None:
    folder = tmp_path_factory.mktemp("publish-decline")
    _mode(folder, "decline")
    with serving(folder, script=SCRIPT) as base:
        page = browser_page.new_page(viewport=WINDOW)
        _open_the_section(page, base)
        page.get_by_role("button", name="Look at what would go public").click()
        page.locator(".publish-heading").wait_for(timeout=60000)
        page.get_by_role("button", name="Publish a review copy to GitHub").click()

        page.get_by_text("You did not sign in with Windows, so nothing was published.").wait_for(timeout=30000)
        assert not (folder / "published.json").exists()
        page.close()


def test_with_the_row_off_the_section_says_so_once_and_does_not_loop(
    browser_page: Any, tmp_path_factory: pytest.TempPathFactory
) -> None:
    folder = tmp_path_factory.mktemp("publish-off")
    _mode(folder, "safe")
    with serving(folder, script=SCRIPT) as base:
        page = browser_page.new_page(viewport=WINDOW)
        _open_the_section(page, base)
        page.get_by_role("button", name="Look at what would go public").click()
        page.locator(".publish-heading").wait_for(timeout=60000)
        _turn_off(base)
        asked: list[str] = []
        page.on("request", lambda request: asked.append(request.url) if "/api/public-release" in request.url else None)

        page.get_by_role("button", name="Publish a review copy to GitHub").click()
        page.get_by_text("Publishing is turned off.").wait_for(timeout=30000)
        assert "Turn Publish to GitHub back on in Plugins to use this page." in page.locator(HOST).inner_text()
        page.wait_for_timeout(10000)
        assert len(asked) <= 2, asked
        assert not (folder / "published.json").exists()
        page.close()


def test_a_page_opened_with_the_row_off_asks_once_when_pressed_and_never_again(
    browser_page: Any, tmp_path_factory: pytest.TempPathFactory
) -> None:
    folder = tmp_path_factory.mktemp("publish-off-first")
    _mode(folder, "safe")
    with serving(folder, script=SCRIPT) as base:
        _turn_off(base)
        page = browser_page.new_page(viewport=WINDOW)
        asked: list[str] = []
        page.on("request", lambda request: asked.append(request.url) if "/api/public-release" in request.url else None)
        _open_the_section(page, base)

        page.get_by_role("button", name="Look at what would go public").click()
        page.get_by_text("Publishing is turned off.").wait_for(timeout=30000)
        page.wait_for_timeout(10000)

        assert len(asked) == 1, asked
        page.close()
