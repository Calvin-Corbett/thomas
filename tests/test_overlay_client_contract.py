"""Every document reads the user overlay the same way, and the two whitelists cannot drift.

The node harness runs chat_themes.js and workspace_shell.js against a stub
document carrying an overlay view and reports what came out; the source pins
keep the parts other tests and other documents rely on exactly where they are.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from thomas.server.overlay.style_whitelist import STYLE_PROPS

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "thomas" / "server" / "web"
HARNESS = ROOT / "tests" / "web_node" / "overlay_client.mjs"


def _read(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def report() -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    out = subprocess.run(
        [node, str(HARNESS), str(WEB / "js" / "chat_themes.js"), str(WEB / "js" / "workspace_shell.js"),
         str(WEB / "js" / "overlay_runtime.js")],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_overlay_themes_are_appended_in_manifest_order_after_the_stock_five(report: dict) -> None:
    assert report["theme_order"] == ["nebula", "dark", "light", "aurora", "sandstone", "ember", "paper", "rogue"]
    assert report["merge_is_idempotent"] is True


def test_a_cleared_record_restores_stock_live_and_quoted_font_tokens_land(report: dict) -> None:
    assert report["cleared_token_restores_stock"] is True
    assert report["quoted_font_token_reaches_meta"] is True


def test_a_cleared_then_readded_overlay_theme_uses_its_new_welcome(report: dict) -> None:
    assert report["cleared_readded_theme_uses_new_welcome"] is True


def test_every_identity_field_the_server_accepts_has_a_consumer_in_the_runtime() -> None:
    from thomas.server.overlay.records import IDENTITY_FIELDS, RESERVED_IDENTITY_FIELDS

    runtime = _read("js/overlay_runtime.js")
    for field in IDENTITY_FIELDS:
        assert f'"{field}"' in runtime or f"identityOf()[{field!r}]" in runtime or f"id.{field}" in runtime, field
    assert "tagline" in RESERVED_IDENTITY_FIELDS and "mark" in RESERVED_IDENTITY_FIELDS
    select = _read("js/ui_redesign_select.js")
    assert "Not applied - " in select and "The theme changes were not applied." in select


def test_a_theme_string_that_could_open_a_tag_never_reaches_the_payload(report: dict) -> None:
    assert report["rogue_label_falls_back_to_name"] is True
    assert report["rogue_swatches_fall_back_to_parent"] is True
    assert report["rogue_msg_rule_stays_parent"] is True
    assert report["rogue_welcome_stays_parent"] is True


def test_token_records_patch_the_stock_payloads_and_only_their_theme(report: dict) -> None:
    assert report["nebula_accent"] == "#2ecc71"
    assert report["dark_accent_untouched"] != "#2ecc71"
    assert report["star_text_everywhere"] is True
    assert report["nebula_font_head_from_token"] == "'Inter', sans-serif", "a META field that is a token follows its record"


def test_an_overlay_theme_derives_from_its_parent_at_load(report: dict) -> None:
    assert report["ember_bg"] == "#140a06" and report["ember_inherits_parent_accent"] is True
    assert report["ember_label"] == "Ember" and report["ember_swatches"] == ["#140a06", "#2a1408", "#ff7a1a"]
    assert report["ember_meta_menu_bg"] == "#1c0f08" and report["ember_meta_rcard"] == "12px"
    assert report["ember_meta_bot_inherited"] is True
    assert report["paper_is_light_copy"] is True


def test_the_shell_knows_overlay_themes_and_their_colour_scheme(report: dict) -> None:
    assert report["known_themes"] == ["nebula", "dark", "light", "aurora", "sandstone", "ember", "paper", "rogue"]
    assert report["safe_ember"] == "ember" and report["safe_unknown"] == "nebula"
    assert report["stored_theme"] == "ember", "a stored overlay theme is never reset to nebula"
    assert report["paper_color_scheme"] == "light" and report["ember_color_scheme"] == "dark"
    assert report["default_theme_when_nothing_stored"] == "ember", "setting:default_theme seeds an empty browser"


def test_the_browser_and_server_style_whitelists_are_the_same_set() -> None:
    layout = _read("js/ui_edit_layout.js")
    block = layout.split("const STYLE_PROPS = new Set([", 1)[1].split("]);", 1)[0]
    assert set(re.findall(r'"([A-Za-z]+)"', block)) == set(STYLE_PROPS)
    runtime = (ROOT / "thomas" / "server" / "routes" / "ui_redesign_runtime.py").read_text(encoding="utf-8")
    assert "_STYLE_PROPS = {" not in runtime and "from thomas.server.overlay.style_whitelist import clean_style" in runtime


def test_the_pins_other_tests_rely_on_are_untouched() -> None:
    shell = _read("js/workspace_shell.js")
    assert 'const THEMES = ["nebula", "dark", "light", "aurora", "sandstone"]' in shell
    assert 'root.style.colorScheme = LIGHT_THEMES.includes(name) ? "light" : "dark"' in shell
    themes = _read("js/chat_themes.js")
    assert "/css/tokens.css" in themes and "mergeOverlay: mergeOverlay" in themes
    layout = _read("js/ui_edit_layout.js")
    assert 'const KEY = "thomas_ui_layout_v2"' in layout and "localStorage.setItem(KEY" in layout
    assert "orphans, overlaidKeys, refreshOverlay" in layout
    assert "return Object.assign(overlayMap(), clone(editing ? slot.draft : slot.saved));" in layout


def test_the_runtime_never_writes_overlay_text_through_innerhtml() -> None:
    runtime = _read("js/overlay_runtime.js")
    assert "innerHTML" not in runtime
    assert 'const CHANNEL = "thomas-overlay"' in runtime and "new BroadcastChannel(CHANNEL)" in runtime
    assert "node.textContent = to" in runtime and "function applySurface(key)" in runtime
    assert "function renameHeaders(root, from, to)" in runtime and 'classList.contains("tc-activity")' in runtime, "only the assistant header is renamed inside the thread"
    assert ".replace(WORD, () => name)" in runtime, "a name containing $ sequences is inserted literally"
    assert 'if (res.status === 404) return { ok: false, unavailable: true' in runtime
    assert 'data.code === "overlay_mismatch"' in runtime, "a stale overlay id refreshes and retries once"


def test_no_python_outside_the_overlay_package_builds_an_overlay_path() -> None:
    allowed = {
        ROOT / "thomas" / "server" / "overlay",
        ROOT / "thomas" / "server" / "routes" / "ui_overlay_routes.py",
    }
    offenders = []
    for path in (ROOT / "thomas").rglob("*.py"):
        if any(path == a or a in path.parents for a in allowed):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "THOMAS_OVERLAY_DIR" in text or re.search(r'["\']overlay["\']\s*\)?\s*/|/ "overlay"', text):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], offenders


def test_settings_stays_at_or_under_its_line_cap() -> None:
    assert len(_read("settings.script01.js").splitlines()) <= 800
