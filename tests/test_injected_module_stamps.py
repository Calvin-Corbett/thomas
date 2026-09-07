"""Injected chat modules carry their own cache stamp (2026-09-05).

The page's build fingerprint hashes chat.html and workspace_shell.js only, so
a browser kept serving old copies of the injected modules after they changed
on disk: the verify server had the new ask_user_panel.js while the page ran
the old one. Each injected tag now stamps the module's own bytes.
"""

from __future__ import annotations

from pathlib import Path

from thomas.server.app_middleware_helpers import inject_ask_user_panel, inject_settings_parity

PAGE = "<html><body><p>hi</p></body></html>"


def _stamp(html: str, module: str) -> str:
    start = html.index(f"/static/js/{module}?v=") + len(f"/static/js/{module}?v=")
    return html[start : html.index('"', start)]


def test_each_tag_is_stamped_from_its_own_file_and_changes_with_it(tmp_path: Path) -> None:
    js = tmp_path / "js"
    js.mkdir()
    for name in (
        "chat_session_id",
        "rate_limit_banner",
        "ask_user_panel",
        "slash_palette",
        "message_feedback",
        "cost_readout",
        "fast_mode",
        "todo_panel",
    ):
        (js / f"{name}.js").write_text(f"// {name} v1\n", encoding="utf-8")

    first = inject_ask_user_panel(PAGE, web_dir=tmp_path)
    stamps = {name: _stamp(first, f"{name}.js") for name in ("ask_user_panel", "todo_panel")}
    assert all(s and s != "__THOMAS_WEB_BUILD__" for s in stamps.values()), stamps
    assert stamps["ask_user_panel"] != stamps["todo_panel"]

    (js / "todo_panel.js").write_text("// todo_panel v2\n", encoding="utf-8")
    second = inject_ask_user_panel(PAGE, web_dir=tmp_path)
    assert _stamp(second, "ask_user_panel.js") == stamps["ask_user_panel"]
    assert _stamp(second, "todo_panel.js") != stamps["todo_panel"]
    # a page that already carries the module is left alone, whatever its stamp
    assert inject_ask_user_panel(second, web_dir=tmp_path) == second


def test_a_missing_module_file_falls_back_to_the_page_build_stamp(tmp_path: Path) -> None:
    html = inject_ask_user_panel(PAGE, web_dir=tmp_path)
    assert html.count("__THOMAS_WEB_BUILD__") == 8


def test_settings_parity_is_stamped_the_same_way(tmp_path: Path) -> None:
    js = tmp_path / "js"
    js.mkdir()
    (js / "settings_parity.js").write_text("// v1\n", encoding="utf-8")
    first = _stamp(inject_settings_parity(PAGE, web_dir=tmp_path), "settings_parity.js")
    (js / "settings_parity.js").write_text("// v2\n", encoding="utf-8")
    second = _stamp(inject_settings_parity(PAGE, web_dir=tmp_path), "settings_parity.js")
    assert first != "__THOMAS_WEB_BUILD__" and first != second
