"""An overlay is a directory the base never writes and a manifest that is loud when broken.

The manifest copies the accepted-risks registry contract (scripts/forge/accepted_risks.py):
a MISSING manifest is stock Thomas and says so once; a manifest that EXISTS but is
malformed is broken, not empty, and never falls back. Records are append-only under a
lock; resolve is newest-wins per address and `clear` retracts.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from thomas.server.overlay import manifest as m
from thomas.server.overlay import stock_tokens, store

STOCK = {"nebula": {"--c-accent": "#8b8cff", "--c-bg": "#070912"}, "dark": {"--c-accent": "#6e9bff"},
         "light": {}, "aurora": {}, "sandstone": {}}
BASE = {"thomas_version": "0.19.27", "git": "abc1234", "web_build": "0123456789ab", "tokens_sha1": "f" * 40}
ACTION = {"actor": "redesign", "instruction": "make the sidebar darker", "targets": ["chat.sidebar"]}


def element(address: str = "element:chat:desktop:chat.sidebar", **value):
    return {
        "op": "set", "kind": "element", "address": address,
        "value": value or {"x": 0, "y": 0, "style": {"backgroundColor": "#101a2e"}},
        "anchor": {"exact": True, "fragile": False, "component": "aside", "label": "Chat sidebar",
                   "policy": "move resize", "path": ""},
    }


def test_a_missing_manifest_is_stock_thomas_not_an_error(tmp_path: Path) -> None:
    assert m.load(tmp_path / "overlay" / "manifest.json") is None
    assert not (tmp_path / "overlay").exists()


def test_a_broken_manifest_names_its_file_and_never_reads_as_empty(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    path.parent.mkdir()
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(m.ManifestBroken) as info:
        m.load(path)
    assert "manifest.json" in str(info.value)
    path.write_text(json.dumps({"version": 1, "overlay": {"id": "ovl_x"}, "records": [{"id": "r0001"}]}), encoding="utf-8")
    with pytest.raises(m.ManifestBroken):
        m.load(path)
    with pytest.raises(m.ManifestBroken):
        m.append([element()], ACTION, BASE, path=path, stock=STOCK)
    assert "r0001" in path.read_text(encoding="utf-8")


def test_the_first_append_gives_birth_and_writes_nothing_outside_the_overlay_dir(tmp_path: Path) -> None:
    path = tmp_path / "home" / "overlay" / "manifest.json"
    result = m.append([element()], ACTION, BASE, path=path, stock=STOCK)
    assert result.created is True and result.rev == 1 and result.overlay_id.startswith("ovl_")
    loaded = m.load(path)
    assert loaded is not None and loaded.rev == 1 and loaded.header["created_from"] == BASE
    assert sorted(p.name for p in path.parent.iterdir()) == [".gitattributes", ".gitignore", "README.md", "manifest.json"]
    assert sorted(p.name for p in (tmp_path / "home").iterdir()) == ["overlay"]
    record = loaded.records[0]
    assert record["id"] == "r0001" and record["at"].endswith("Z") and record["by"]["action"].startswith("act_")
    assert record["value"]["style"] == {"backgroundColor": "#101a2e"}


def test_resolve_is_newest_wins_and_clear_retracts(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    m.append([element(style={"backgroundColor": "#111"})], ACTION, BASE, path=path, stock=STOCK)
    m.append([element(style={"backgroundColor": "#222"})], ACTION, BASE, path=path, stock=STOCK)
    live = m.resolve(m.load(path).records)
    assert live["element:chat:desktop:chat.sidebar"]["value"]["style"]["backgroundColor"] == "#222"
    m.append([{"op": "clear", "kind": "element", "address": "element:chat:desktop:chat.sidebar"}], ACTION, BASE, path=path, stock=STOCK)
    assert "element:chat:desktop:chat.sidebar" not in m.resolve(m.load(path).records)
    assert m.load(path).rev == 3


def test_a_token_record_carries_the_stock_value_it_overrides(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    result = m.append([{"op": "set", "kind": "token", "address": "token:nebula:--c-accent", "value": "#2ecc71"}],
                      ACTION, BASE, path=path, stock=STOCK)
    assert result.accepted == ["token:nebula:--c-accent"]
    rec = m.load(path).records[0]
    assert rec["stock_value"] == "#8b8cff" and rec["base"] == BASE and rec["by"]["actor"] == "redesign"


def test_a_foreign_overlay_id_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    first = m.append([element()], ACTION, BASE, path=path, stock=STOCK)
    with pytest.raises(m.OverlayMismatch):
        m.append([element()], ACTION, BASE, path=path, stock=STOCK, expected_overlay_id="ovl_000000000000")
    loaded = m.load(path)
    assert loaded.overlay_id == first.overlay_id and loaded.rev == 1
    again = m.append([element(x=1)], ACTION, BASE, path=path, stock=STOCK, expected_overlay_id=first.overlay_id)
    assert again.created is False and again.rev == 2


def test_two_writers_both_land_and_the_file_is_never_half_written(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    m.append([element()], ACTION, BASE, path=path, stock=STOCK)

    def writer(n: int) -> None:
        m.append([element(address=f"element:chat:desktop:row{n}", x=n)], ACTION, BASE, path=path, stock=STOCK)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    loaded = m.load(path)
    assert loaded.rev == 9
    assert [r["id"] for r in loaded.records] == [f"r{i:04d}" for i in range(1, 10)]
    assert not store.lock_path_for(path).exists() and not list(path.parent.glob("*.tmp"))


def test_a_record_on_disk_that_fails_full_validation_is_broken_and_never_rendered(tmp_path: Path) -> None:
    from thomas.server.overlay import render

    path = tmp_path / "overlay" / "manifest.json"
    m.append([element()], ACTION, BASE, path=path, stock=STOCK)
    data = json.loads(path.read_text(encoding="utf-8"))
    crafted = dict(data["records"][0], id="r0002", kind="theme", address='theme:x"]{} </style><script>alert(1)</script>/*',
                   value={"label": "x", "derives_from": "nebula", "color_scheme": "dark"}, anchor=None, stock_value=None)
    data["records"].append(crafted)
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(m.ManifestBroken, match="record 1"):
        m.load(path)
    render.invalidate()
    view = render.current_view(path)
    assert view["present"] is False and render.render_css(view) == "" and "<script>" not in render.render_view(view)
    with pytest.raises(m.ManifestBroken):
        m.append([element(address="element:chat:desktop:other")], ACTION, BASE, path=path, stock=STOCK)


def test_header_and_record_shapes_are_fully_checked_on_load(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    m.append([element()], ACTION, BASE, path=path, stock=STOCK)
    good = json.loads(path.read_text(encoding="utf-8"))
    for mutate in (
        lambda d: d.update(version=True),
        lambda d: d["overlay"].update(schema=True),
        lambda d: d["overlay"].update(id="ovl_nothex"),
        lambda d: d["overlay"].update(created_at="yesterday"),
        lambda d: d["overlay"].update(created_at="9999-99-99T99:99:99Z"),
        lambda d: d["overlay"].update(created_from={"thomas_version": "1", "git": None, "web_build": None, "tokens_sha1": "x", "extra": 1}),
        lambda d: d["records"][0].update(id="r0009"),
        lambda d: d["records"][0].update(at="2026-09-02"),
        lambda d: d["records"][0].update(at="2026-02-30T00:00:00Z"),
        lambda d: d["records"][0].update(by="me"),
        lambda d: d["records"][0]["by"].update(targets="chat.sidebar"),
        lambda d: d["records"][0]["by"].update(instruction={"text": "x"}),
        lambda d: d["records"][0]["by"].update(action="not-an-action"),
        lambda d: d["records"][0].update(base={"thomas_version": 1}),
        lambda d: d["records"][0]["base"].update(git=float("nan")),
        lambda d: d["records"][0].update(anchor="aside"),
        lambda d: d["records"][0].update(value={"x": True}),
        lambda d: d["records"][0].update(address="element:chat:desktop:\x01"),
    ):
        data = json.loads(json.dumps(good))
        mutate(data)
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(m.ManifestBroken):
            m.load(path)
    path.write_text('{"version": 1, "version": 1, ' + json.dumps(good)[1:], encoding="utf-8")
    with pytest.raises(m.ManifestBroken, match="duplicate key"):
        m.load(path)
    path.write_text(json.dumps(good).replace('"git": "abc1234"', '"git": NaN', 1), encoding="utf-8")
    with pytest.raises(m.ManifestBroken, match="non-finite"):
        m.load(path)
    path.write_text(json.dumps(good), encoding="utf-8")
    assert m.load(path).rev == 1


def test_persisted_set_provenance_must_be_something_the_writer_can_emit(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    m.append([
        element(),
        {"op": "set", "kind": "token", "address": "token:nebula:--c-accent", "value": "#2ecc71"},
        {"op": "set", "kind": "identity", "address": "identity:name", "value": "Otto"},
    ], ACTION, BASE, path=path, stock=STOCK)
    good = json.loads(path.read_text(encoding="utf-8"))
    mutations = (
        lambda d: d["records"][0].update(stock_value="fabricated"),
        lambda d: d["records"][1].update(anchor={"exact": True}),
        lambda d: d["records"][1].update(stock_value=None),
        lambda d: d["records"][1].update(stock_value={"value": "#8b8cff"}),
        lambda d: d["records"][1].update(stock_value=" #8b8cff "),
        lambda d: d["records"][2].update(anchor={"exact": True}),
        lambda d: d["records"][2].update(stock_value="fabricated"),
    )
    for mutate in mutations:
        data = json.loads(json.dumps(good))
        mutate(data)
        path.write_text(json.dumps(data), encoding="utf-8")
        before = path.read_bytes()
        with pytest.raises(m.ManifestBroken, match="provenance"):
            m.load(path)
        assert path.read_bytes() == before, "load must reject impossible provenance without rewriting it"


def test_a_theme_value_cannot_carry_markup_into_the_theme_menu(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    good = {"label": "Ember", "tagline": "Warm", "derives_from": "nebula", "color_scheme": "dark",
            "swatches": ["#140a06", "rgb(42, 20, 8)", "orange"], "world": "nebula",
            "meta": {"menuBg": "#1c0f08", "msgRule": "1px solid #333", "bot": ["#fff", "#eee", "rgba(0,0,0,0.5)"], "welcome": ["Hello", "there"]}}
    breakout = '#000;"><img src=x onerror="fetch(1)">'
    bad = [
        dict(good, swatches=["#000", "#000", breakout]),
        dict(good, meta={"msgRule": breakout}),
        dict(good, meta={"bot": ["#000", "#000", breakout]}),
        dict(good, meta={"welcome": ["Hello", "<b>x</b>"]}),
        dict(good, meta={"onload": "x"}),
        dict(good, label="<script>"),
        dict(good, world="../x"),
        dict(good, extra="x"),
    ]
    result = m.append([{"op": "set", "kind": "theme", "address": f"theme:t{i}", "value": value} for i, value in enumerate([good, *bad])],
                      ACTION, BASE, path=path, stock=STOCK)
    assert result.accepted == ["theme:t0"], result.rejected
    assert len(result.rejected) == len(bad)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["records"][0]["value"]["swatches"][2] = breakout
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(m.ManifestBroken):
        m.load(path)


def test_the_overlay_id_precondition_is_strict_when_given(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    with pytest.raises(m.OverlayMismatch):
        m.append([element()], ACTION, BASE, path=path, stock=STOCK, expected_overlay_id="ovl_000000000000")
    assert not (tmp_path / "overlay").exists()
    born = m.append([element()], ACTION, BASE, path=path, stock=STOCK, expected_overlay_id=None)
    assert born.created is True
    with pytest.raises(m.OverlayMismatch, match="does not match"):
        m.append([element()], ACTION, BASE, path=path, stock=STOCK, expected_overlay_id=None)
    assert m.load(path).rev == 1
    assert m.append([element(x=1)], ACTION, BASE, path=path, stock=STOCK, expected_overlay_id=born.overlay_id).rev == 2
    # A write that records nothing still keeps the precondition: a stale id
    # cannot learn the current one from the reply.
    rejected_only = [{"op": "set", "kind": "asset", "address": "asset:x", "value": {}}]
    with pytest.raises(m.OverlayMismatch):
        m.append(rejected_only, ACTION, BASE, path=path, stock=STOCK, expected_overlay_id="ovl_000000000000")
    with pytest.raises(m.OverlayMismatch):
        m.append(rejected_only, ACTION, BASE, path=path, stock=STOCK, expected_overlay_id=None)
    assert m.append(rejected_only, ACTION, BASE, path=path, stock=STOCK, expected_overlay_id=born.overlay_id).overlay_id == born.overlay_id
    with pytest.raises(m.OverlayMismatch):
        m.append([{"op": "clear", "kind": "element", "address": "element:chat:desktop:x"}], ACTION, BASE,
                 path=tmp_path / "none" / "manifest.json", stock=STOCK, expected_overlay_id="ovl_000000000000")


def test_nothing_accepted_means_nothing_is_born(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    empty = m.append([], ACTION, BASE, path=path, stock=STOCK)
    assert empty.created is False and empty.rev == 0 and empty.overlay_id == ""
    rejected_only = m.append([{"op": "set", "kind": "asset", "address": "asset:x", "value": {}}], ACTION, BASE, path=path, stock=STOCK)
    assert rejected_only.rejected and rejected_only.created is False
    clear_only = m.append([{"op": "clear", "kind": "element", "address": "element:chat:desktop:x"}], ACTION, BASE, path=path, stock=STOCK)
    assert "not in effect" in clear_only.rejected[0]["reason"]
    assert not (tmp_path / "overlay").exists(), "no birth files, no directory, for a write that recorded nothing"


def test_stock_tokens_parse_the_root_and_every_theme_block() -> None:
    stock = stock_tokens.load_stock()
    assert set(stock) == set(stock_tokens.STOCK_THEMES)
    assert stock["nebula"]["--c-accent"].startswith("#")
    assert all(stock[name] for name in stock_tokens.STOCK_THEMES), "every stock theme block has tokens"
    assert stock_tokens.is_stock_key("--c-accent", stock) and not stock_tokens.is_stock_key("--c-nope", stock)
