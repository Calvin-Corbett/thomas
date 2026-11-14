"""The display kernel: a renderer plugs in through the registry, and a block always carries words.

Gate for step 1 of the display kernel. Two promises are held here:

1. A renderer can only arrive through ``ThomasDisplay.register`` -- no other file touches the registry, and every
   ``register`` call in the page's scripts is a name plus an object with a ``render`` function.
2. A block with no ``fallback_text`` cannot be built, and any block that cannot be drawn (no renderer, switched off,
   newer than its renderer, a renderer that throws or returns something that is not text) shows its words.

Driven through ``tests/web_node/display_kernel.mjs``.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
JS_DIR = REPO_ROOT / "thomas" / "server" / "web" / "js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "display_kernel.mjs"
KERNEL = "display_kernel.js"


def _drive() -> dict:
    result = subprocess.run(
        ["node", str(HARNESS), str(JS_DIR)],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_a_renderer_must_have_a_valid_type_and_a_render_function() -> None:
    report = _drive()
    assert report["registerNoRender"].startswith("threw:")
    assert report["registerBadType"].startswith("threw:")


def test_a_block_cannot_be_built_without_fallback_text() -> None:
    report = _drive()
    assert report["makeBlockNoWords"].startswith("threw:")
    assert report["rawBlockNoWords"] == ""


def test_a_block_that_cannot_draw_shows_its_words_escaped() -> None:
    report = _drive()
    assert report["unregistered"] == '<div class="tc-display-fallback">Q1 &lt;totals&gt;</div>'
    for key, words in (
        ("throws", "words survive"),
        ("notString", "still words"),
        ("badTableData", "A | B"),
        ("newerThanRenderer", "A"),
    ):
        assert report[key] == f'<div class="tc-display-fallback">{words}</div>', key
    assert "tc-display-table" not in report["switchedOff"]
    assert report["switchedOn"] is True


def test_the_built_ins_draw_what_they_drew_before() -> None:
    report = _drive()
    assert report["markdownSame"] is True
    assert "<table>" in report["table"] and "&lt;b&gt;a&lt;/b&gt;" in report["table"]
    assert report["tableFallbackText"] == "Name | State\na | ok"


def test_builds_reply_draws_the_same_through_the_kernel() -> None:
    report = _drive()
    assert report["buildReplyHasTable"] is True
    assert report["buildReplySame"] is True
    assert report["buildReplyOffShowsWords"] is True, "Build's reply must go through the registry"


def test_a_registered_renderer_can_be_swapped_and_the_server_list_is_read() -> None:
    report = _drive()
    assert report["swap"] == "<i>fixed</i>"
    assert report["loaded"] is True and report["loadedOff"] is False
    assert report["loadFails"] is False and report["stillOff"] is False, "a failed read keeps the last list"


def test_only_register_adds_a_renderer_and_every_call_passes_a_render_function() -> None:
    for path in sorted(JS_DIR.glob("*.js")):
        text = path.read_text(encoding="utf-8")
        if path.name != KERNEL:
            assert not re.search(r"\brenderers\.(set|get)\b", text), f"{path.name} reaches into the registry"
            assert not re.search(r"ThomasDisplay\s*=[^=]", text), f"{path.name} replaces ThomasDisplay"
        for call in re.finditer(r"\bkernel\.register\(\s*'([^']+)'\s*,\s*\{([^\n]*)\}\s*\)", text):
            assert "render" in call.group(2), f"{path.name} registers {call.group(1)} with no render"


def test_the_row_has_the_words_the_plugins_page_shows() -> None:
    text = (REPO_ROOT / "thomas" / "server" / "rows" / "default.toml").read_text(encoding="utf-8")
    block = text.split('id = "display"', 1)[1].split("[[row]]", 1)[0]
    for field in ("title", "about", "off_means", "stop_now"):
        assert re.search(rf'^{field} = ".+"', block, re.M), field
