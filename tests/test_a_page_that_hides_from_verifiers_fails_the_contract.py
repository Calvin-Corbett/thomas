"""A page that behaves differently for an automated browser cannot be verified (2026-09-05).

The Minecraft build (project "Code task 2026-08-14 1413", main.js line 136) read
``navigator.webdriver`` and the user agent for Headless, Playwright and Puppeteer
and never activated its renderer under automation; its own comment said this
"used to make smoke checks fail". You entered a world that was a HUD over a
void, and every playtest that could have caught it saw the same void and
called it fine. Such a page is unverifiable by construction, so the contract
carries a machine item that fails while any changed source detects automation.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from thomas.core import acceptance_contract as ac

DETECTING = """const isAutomatedBrowser = navigator.webdriver === true
  || /HeadlessChrome|Playwright|Puppeteer/i.test(navigator.userAgent);
function activateRenderer() { if (isAutomatedBrowser) return; start(); }
"""
HONEST = "function activateRenderer() { start(); }\n"


def _contract(ws: Path, started: float) -> ac.ContractItem:
    items = ac.build_contract("Make the world render.", ws)
    item = next(it for it in items if it.item_id == "honest_page")
    assert item.kind == ac.KIND_HONEST_PAGE and item.machine
    evaluated = ac.evaluate_contract(items, workspace=ws, started_at=started)
    return next(it for it in evaluated if it.item_id == "honest_page")


def test_a_changed_source_that_detects_automation_fails_the_item(tmp_path: Path) -> None:
    started = time.time() - 5
    (tmp_path / "main.js").write_text(DETECTING, encoding="utf-8")
    item = _contract(tmp_path, started)
    assert item.checked and not item.satisfied
    assert "main.js" in item.detail and "navigator.webdriver" in item.detail, item.detail


def test_an_honest_source_passes_and_the_text_says_why_it_matters(tmp_path: Path) -> None:
    started = time.time() - 5
    (tmp_path / "main.js").write_text(HONEST, encoding="utf-8")
    item = _contract(tmp_path, started)
    assert item.checked and item.satisfied, item.detail
    assert "automated" in item.description.lower() and "verif" in item.description.lower()


def test_an_untouched_old_file_is_not_the_work_under_review(tmp_path: Path) -> None:
    (tmp_path / "vendor.js").write_text(DETECTING, encoding="utf-8")
    old = time.time() - 3600
    os.utime(tmp_path / "vendor.js", (old, old))
    item = _contract(tmp_path, time.time() - 5)
    assert item.satisfied, item.detail


def test_the_default_machine_items_alone_are_still_a_trivial_contract(tmp_path: Path) -> None:
    items = ac.build_contract("hi there, how are you", tmp_path)
    assert {it.item_id for it in items} == {"compiles", "honest_page"}, [it.item_id for it in items]
    assert ac.is_trivial(items)


def test_a_comment_that_names_the_words_is_not_detection(tmp_path: Path) -> None:
    started = time.time() - 5
    (tmp_path / "main.js").write_text(
        "// The renderer used to skip navigator.webdriver and HeadlessChrome sessions; it no longer does.\n"
        "/* Playwright and Puppeteer see the same world as a person. */\n"
        "function activateRenderer() { start(); }\n",
        encoding="utf-8",
    )
    item = _contract(tmp_path, started)
    assert item.satisfied, item.detail
