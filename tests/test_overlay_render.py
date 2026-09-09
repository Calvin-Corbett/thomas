"""The overlay renders into three tags before </head>, and a bad value never escapes.

An absent overlay still carries the view JSON and the runtime script (so the
first write can reach documents that were open before it) but no stylesheet.
Token overrides use the exact tokens.css selector grammar so source order
wins; an overlay theme is a full block derived from its stock parent at
render time; identity text cannot close the view script.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thomas.server.overlay import cli, render, stock_tokens, store
from thomas.server.overlay import manifest as m

BASE = {"thomas_version": "0.19.27", "git": None, "web_build": None, "tokens_sha1": "0" * 40}
ACTION = {"actor": "test", "instruction": "render", "targets": []}
PAGE = "<!doctype html><html><head><title>x</title></head><body>__THOMAS_WEB_BUILD__</body></html>"


def _view(tmp_path: Path, records: list[dict]) -> dict:
    path = tmp_path / "overlay" / "manifest.json"
    m.append(records, ACTION, BASE, path=path, stock=stock_tokens.load_stock())
    return render.build_view(m.load(path))


def test_an_absent_overlay_injects_the_view_and_the_runtime_but_no_stylesheet(tmp_path: Path) -> None:
    view = render.empty_view(tmp_path / "overlay" / "manifest.json")
    html = render.inject(PAGE, "__THOMAS_WEB_BUILD__", view=view)
    head = html.split("</head>")[0]
    assert 'id="thomas-overlay-css"' not in head
    assert 'id="thomas-overlay-view"' in head and '"present":false' in head
    assert 'src="/static/js/overlay_runtime.js?v=__THOMAS_WEB_BUILD__" defer' in head
    assert html.count("</head>") == 1
    assert not (tmp_path / "overlay").exists()


def test_a_nebula_token_lands_on_root_and_a_dark_token_under_the_dark_selector(tmp_path: Path) -> None:
    view = _view(tmp_path, [
        {"op": "set", "kind": "token", "address": "token:nebula:--c-accent", "value": "#2ecc71"},
        {"op": "set", "kind": "token", "address": "token:dark:--c-accent", "value": "#111111"},
    ])
    css = render.render_css(view)
    assert ":root{--c-accent:#2ecc71;}" in css
    assert 'html[data-thomas-theme="dark"], html[data-theme="dark"]{--c-accent:#111111;}' in css
    assert view["overrides"] == ["token:nebula:--c-accent", "token:dark:--c-accent"]


def test_a_wildcard_token_reaches_every_theme_and_a_specific_token_wins(tmp_path: Path) -> None:
    view = _view(tmp_path, [
        {"op": "set", "kind": "token", "address": "token:*:--c-text", "value": "#010203"},
        {"op": "set", "kind": "token", "address": "token:dark:--c-text", "value": "#040506"},
        {"op": "set", "kind": "theme", "address": "theme:ember",
         "value": {"label": "Ember", "derives_from": "nebula", "color_scheme": "dark"}},
    ])
    css = render.render_css(view)
    assert ":root{--c-text:#010203;}" in css
    for theme in ("dark", "light", "aurora", "sandstone"):
        selector = f'html[data-thomas-theme="{theme}"], html[data-theme="{theme}"]'
        assert f"{selector}{{--c-text:#010203;}}" in css
    assert css.rfind('--c-text:#040506;') > css.find('--c-text:#010203;'), "the specific dark value must win by source order"
    ember = css.split('html[data-thomas-theme="ember"], html[data-theme="ember"]{', 1)[1].split("}", 1)[0]
    assert "--c-text:#010203;" in ember, "an overlay theme inherits the wildcard too"


def test_an_overlay_theme_is_a_full_block_derived_from_its_parent_at_render_time(tmp_path: Path) -> None:
    view = _view(tmp_path, [
        {"op": "set", "kind": "token", "address": "token:nebula:--c-accent", "value": "#2ecc71"},
        {"op": "set", "kind": "theme", "address": "theme:ember",
         "value": {"label": "Ember", "tagline": "Warm dark", "derives_from": "nebula", "color_scheme": "dark",
                   "swatches": ["#140a06", "#2a1408", "#ff7a1a"], "world": "nebula", "meta": {"menuBg": "#1c0f08"}}},
        {"op": "set", "kind": "token", "address": "token:ember:--c-bg", "value": "#140a06"},
    ])
    css = render.render_css(view)
    block = css.split('html[data-thomas-theme="ember"], html[data-theme="ember"]{', 1)[1].split("}", 1)[0]
    stock = stock_tokens.load_stock()["nebula"]
    assert all(f"{key}:" in block for key in stock), "every stock nebula token is present in the derived block"
    assert "--c-accent:#2ecc71;" in block, "the parent's token override flows into the derived theme"
    assert "--c-bg:#140a06;" in block and "color-scheme:dark;" in block
    assert view["themes"]["ember"]["label"] == "Ember"


def test_a_value_that_could_escape_its_declaration_is_dropped_into_the_notes() -> None:
    view = {"present": True, "tokens": {"nebula": {"--c-accent": "red}body{display:none"}}, "themes": {}, "notes": []}
    notes: list[str] = []
    css = render.render_css(view, notes)
    assert "display:none" not in css and css == ""
    assert any("--c-accent" in note for note in notes)
    assert view["notes"] == [], "the caller's view is never mutated"
    css2, published = render.rendered(view)
    css3, published_again = render.rendered(view)
    assert css2 == css3 == "" and len(published["notes"]) == 1 == len(published_again["notes"]), "rendering twice never duplicates a note"


def test_identity_text_cannot_close_or_reshape_the_view_script(tmp_path: Path) -> None:
    import json as json_lib

    view = _view(tmp_path, [{"op": "set", "kind": "identity", "address": "identity:name", "value": "</script><b>Otto<!--<script>"}])
    html = render.inject(PAGE, "__THOMAS_WEB_BUILD__", view=view)
    payload = html.split('type="application/json">', 1)[1].split("</script>", 1)[0]
    assert "<" not in payload, "no value can start a tag or an HTML comment inside the view element"
    assert json_lib.loads(payload)["identity"]["name"] == "</script><b>Otto<!--<script>", "and JSON.parse still restores it"
    assert html.count("</head>") == 1
    assert html.count("</script>") == 2, "the view script and the runtime script, nothing opened by the value"


def test_injecting_twice_injects_once(tmp_path: Path) -> None:
    view = render.empty_view(tmp_path / "overlay" / "manifest.json")
    once = render.inject(PAGE, "__THOMAS_WEB_BUILD__", view=view)
    assert render.inject(once, "__THOMAS_WEB_BUILD__", view=view) == once
    assert once.count('id="thomas-overlay-view"') == 1 and once.count("overlay_runtime.js") == 1


def test_a_hand_built_view_with_a_bad_theme_name_never_reaches_the_stylesheet() -> None:
    bad = 'x"]{} </style><script>alert(1)</script>/*'
    view = {"present": True, "tokens": {bad: {"--c-accent": "#000"}}, "themes": {bad: {"derives_from": "nebula", "color_scheme": "dark"}}, "notes": []}
    notes: list[str] = []
    css = render.render_css(view, notes)
    assert css == "" and "<script>" not in css
    assert notes and all("not a valid" in note for note in notes)


def test_a_page_without_a_head_is_left_alone(tmp_path: Path) -> None:
    view = render.empty_view(tmp_path / "overlay" / "manifest.json")
    assert render.inject("<p>fragment</p>", "__THOMAS_WEB_BUILD__", view=view) == "<p>fragment</p>"


def test_check_compares_a_token_with_its_addressed_theme_stock(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    stock = stock_tokens.load_stock()
    m.append([{"op": "set", "kind": "token", "address": "token:dark:--c-accent", "value": "#010203"}],
             ACTION, BASE, path=path, stock=stock)
    loaded = m.load(path)
    assert cli.problems(loaded, stock) == [], "unchanged dark stock must not be compared with nebula"
    moved = {name: dict(tokens) for name, tokens in stock.items()}
    moved["dark"]["--c-accent"] = "#aabbcc"
    problems = cli.problems(loaded, moved)
    assert len(problems) == 1 and "stock moved" in problems[0] and "#aabbcc" in problems[0]


def _many_themes(path: Path, count: int, same_action: bool) -> bytes:
    m.append([{"op": "set", "kind": "theme", "address": "theme:t0",
               "value": {"label": "T0", "derives_from": "nebula", "color_scheme": "dark"}}],
             ACTION, BASE, path=path, stock=stock_tokens.load_stock())
    data = json.loads(path.read_text(encoding="utf-8"))
    template = data["records"][0]
    data["records"] = []
    for index in range(count):
        record = json.loads(json.dumps(template))
        record.update(id=f"r{index + 1:04d}", address=f"theme:t{index}")
        if not same_action:
            record["by"]["action"] = f"act_a{index}_abcd"
        data["records"].append(record)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path.read_bytes()


@pytest.mark.parametrize(("count", "same_action", "constant", "limit", "reason"), [
    (501, False, "_MAX_ACTIVE_OVERRIDES", 500, "active"),
    (201, True, "_MAX_RECORDS_PER_APPEND", 200, "one action"),
    (3, False, "_MAX_TOTAL_RECORDS", 2, "total"),
])
def test_load_refuses_writer_limit_bypasses_without_rewriting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int, same_action: bool, constant: str, limit: int, reason: str,
) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    before = _many_themes(path, count, same_action)
    monkeypatch.setattr(store, constant, limit)
    with pytest.raises(m.ManifestBroken, match=reason):
        m.load(path)
    assert path.read_bytes() == before


def test_load_refuses_an_oversized_file_before_reading_or_rewriting(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    payload = _many_themes(path, 1, False)
    path.write_bytes(b" " * (store._MAX_MANIFEST_BYTES - len(payload) + 1) + payload)
    before = path.read_bytes()
    monkeypatch.setattr(Path, "read_text", lambda *_a, **_k: pytest.fail("oversized manifest was materialized"))
    with pytest.raises(m.ManifestBroken, match="bytes"):
        m.load(path)
    assert path.read_bytes() == before


def test_a_broken_manifest_renders_stock_with_a_note_and_the_cache_follows_the_file(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    render.invalidate()
    assert render.current_view(path)["present"] is False
    m.append([{"op": "set", "kind": "token", "address": "token:nebula:--c-accent", "value": "#2ecc71"}],
             ACTION, BASE, path=path, stock=stock_tokens.load_stock())
    render.invalidate()
    assert render.current_view(path)["present"] is True
    path.write_text("{broken", encoding="utf-8")
    render.invalidate()
    view = render.current_view(path)
    assert view["present"] is False and any("manifest.json" in note for note in view["notes"])
    assert render.render_css(view) == ""
