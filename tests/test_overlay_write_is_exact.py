"""Accepted means effective: a record the overlay stores is one it would apply.

Every case here is a write that used to come back accepted while changing
nothing on screen, or a path that let a write land outside the boundary the
contract describes. A caller that sends a field nothing reads is told so
rather than having it silently dropped or silently kept.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from thomas.server.overlay import manifest as m
from thomas.server.overlay import store

STOCK = {"nebula": {"--c-accent": "#8b8cff", "--c-bg": "#070912"}, "dark": {"--c-accent": "#6e9bff"},
         "light": {}, "aurora": {}, "sandstone": {}}
BASE = {"thomas_version": "0.19.27", "git": "abc1234", "web_build": "0123456789ab", "tokens_sha1": "f" * 40}
ACTION = {"actor": "redesign", "instruction": "make it mine", "targets": ["chat.sidebar"]}
ANCHOR = {"exact": True, "fragile": False, "component": "aside", "label": "Chat sidebar", "policy": "move resize", "path": ""}
MINTED_ANCHOR = {"exact": False, "fragile": True, "component": "span", "label": "Brand", "policy": "move resize", "path": "span"}
SIDEBAR = "element:chat:desktop:chat.sidebar"


def element(address: str = SIDEBAR, value: dict | None = None, anchor: object = None) -> dict:
    return {"op": "set", "kind": "element", "address": address,
            "value": {"x": 0, "y": 0, "style": {"backgroundColor": "#101a2e"}} if value is None else value,
            "anchor": ANCHOR if anchor is None else anchor}


def reasons(result) -> dict[str, str]:
    return {row["address"]: row["reason"] for row in result.rejected}


def test_an_element_record_that_would_change_nothing_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    result = m.append([
        element("element:chat:desktop:a", value={}),
        element("element:chat:desktop:b", value={"style": {}}),
        element("element:chat:desktop:c", value={"style": {"nonsense": "1px"}}),
        element("element:chat:desktop:d", value={"notAField": "ignored"}),
        element("element:chat:desktop:e", value={"x": 0, "locked": "false"}),
        element("element:chat:desktop:f", value={"x": 0, "hidden": "yes"}),
        element("element:chat:desktop:g", value={"x": 12, "locked": True}),
    ], ACTION, BASE, path=path, stock=STOCK)
    assert result.accepted == ["element:chat:desktop:g"], result.rejected
    said = reasons(result)
    assert "records nothing" in said["element:chat:desktop:a"]
    assert "no whitelisted property" in said["element:chat:desktop:b"]
    assert "canonical or whitelisted" in said["element:chat:desktop:c"]
    assert "does not apply" in said["element:chat:desktop:d"]
    assert "locked must be true or false" in said["element:chat:desktop:e"]
    assert "hidden must be true or false" in said["element:chat:desktop:f"]


def test_an_element_record_must_say_how_its_target_was_found(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    minted = "element:chat:desktop:chat.sidebar~~span"
    empty_minted = "element:chat:desktop:chat.sidebar~~"
    result = m.append([
        element("element:chat:desktop:a", anchor="aside"),
        element("element:chat:desktop:b", anchor=False),
        element("element:chat:desktop:c", anchor=dict(ANCHOR, unknown=1)),
        element("element:chat:desktop:d", anchor=dict(ANCHOR, exact="yes")),
        element("element:chat:desktop:h", anchor={"exact": True, "fragile": False}),
        element(minted, anchor=dict(MINTED_ANCHOR, path="")),
        element(minted, anchor=dict(MINTED_ANCHOR, path="div")),
        element(empty_minted, anchor=dict(MINTED_ANCHOR, path="")),
        element("element:chat:desktop:e", anchor=MINTED_ANCHOR),
        element(minted, anchor=MINTED_ANCHOR),
    ], ACTION, BASE, path=path, stock=STOCK)
    assert result.accepted == [minted], result.rejected
    said = reasons(result)
    assert "how the target was found" in said["element:chat:desktop:a"]
    assert "how the target was found" in said["element:chat:desktop:b"]
    assert "does not read" in said["element:chat:desktop:c"]
    assert "anchor.exact must be true or false" in said["element:chat:desktop:d"]
    assert "anchor is missing: component, label, path, policy" in said["element:chat:desktop:h"]
    assert "the path it was minted from" in said[minted], "an anchor whose path is not the minted suffix is refused"
    assert "nonempty" in said[empty_minted], "an empty suffix cannot identify a node"
    assert "exact true and fragile false" in said["element:chat:desktop:e"]


def test_a_minted_address_needs_a_nonempty_owner_before_it_writes(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    address = "element:chat:desktop:~~span"
    result = m.append([element(address, anchor=MINTED_ANCHOR)], ACTION, BASE, path=path, stock=STOCK)
    assert result.accepted == []
    assert "nonempty owner" in result.rejected[0]["reason"]
    assert not path.parent.exists(), "a target the browser can never resolve must not create an overlay"


@pytest.mark.parametrize("partial_name", ["README.md", ".tmp"])
def test_a_partial_owned_write_is_removed_without_a_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, partial_name: str,
) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    original = Path.write_text

    def fail_after_partial(target: Path, text: str, *args, **kwargs) -> int:
        chosen = target.name == partial_name or (partial_name == ".tmp" and target.suffix == ".tmp")
        if chosen:
            original(target, "PARTIAL", encoding="utf-8")
            raise OSError(28, "disk full after a partial write")
        return original(target, text, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_after_partial)
    with pytest.raises(m.OverlayWriteFailed, match="rolled back"):
        m.append([element()], ACTION, BASE, path=path, stock=STOCK)
    assert not path.parent.exists(), "every partially-created owned path and its new directory are removed"


def test_a_preexisting_temp_collision_is_never_overwritten_or_unlinked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    path.parent.mkdir()
    collision = path.with_name(f"{path.name}.{os.getpid()}.cafe.tmp")
    collision.write_bytes(b"mine")
    monkeypatch.setattr(store.secrets, "token_hex", lambda _n: "cafe")
    with pytest.raises(m.OverlayWriteFailed):
        store.write_transaction(path, "new\n", birth=False)
    assert collision.read_bytes() == b"mine" and not path.exists()


def test_element_style_is_already_canonical_or_the_whole_record_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    result = m.append([
        element("element:chat:desktop:a", value={"style": {"color": "#fff", "nonsense": "1px"}}),
        element("element:chat:desktop:b", value={"style": {"opacity": 0.5}}),
        element("element:chat:desktop:c", value={"style": {"color": ["#fff"]}}),
        element("element:chat:desktop:d", value={"style": {"color": {"value": "#fff"}}}),
        element("element:chat:desktop:e", value={"style": {"color": " #fff "}}),
        element("element:chat:desktop:f", value={"style": {"background-color": "#000"}}),
        element("element:chat:desktop:g", value={"style": {"backgroundColor": "#000", "opacity": "0.5"}}),
    ], ACTION, BASE, path=path, stock=STOCK)
    assert result.accepted == ["element:chat:desktop:g"], result.rejected
    assert len(result.rejected) == 6
    assert all("style" in row["reason"] for row in result.rejected)
    stored = m.load(path).records[0]
    assert stored["value"] == {"style": {"backgroundColor": "#000", "opacity": "0.5"}}


def test_a_token_value_must_be_text_and_a_default_theme_must_exist(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    ember = {"op": "set", "kind": "theme", "address": "theme:ember",
             "value": {"label": "Ember", "derives_from": "nebula", "color_scheme": "dark"}}
    result = m.append([
        {"op": "set", "kind": "token", "address": "token:nebula:--c-accent", "value": 1},
        {"op": "set", "kind": "token", "address": "token:nebula:--c-bg", "value": ["#000"]},
        {"op": "set", "kind": "setting", "address": "setting:default_theme", "value": "does-not-exist"},
        {"op": "set", "kind": "setting", "address": "setting:default_theme", "value": "dark"},
    ], ACTION, BASE, path=path, stock=STOCK)
    assert result.accepted == ["setting:default_theme"], result.rejected
    said = reasons(result)
    assert "token value must be text" in said["token:nebula:--c-accent"]
    assert "token value must be text" in said["token:nebula:--c-bg"]
    assert "not a theme this Thomas has" in said["setting:default_theme"]
    # A theme defined earlier in the SAME action is a theme this Thomas has.
    same_action = m.append([ember, {"op": "set", "kind": "setting", "address": "setting:default_theme", "value": "ember"}],
                           ACTION, BASE, path=path, stock=STOCK)
    assert same_action.accepted == ["theme:ember", "setting:default_theme"], same_action.rejected


def test_a_clear_only_retracts_what_is_in_effect_at_that_point(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    m.append([element()], ACTION, BASE, path=path, stock=STOCK)
    clear = {"op": "clear", "kind": "element", "address": SIDEBAR}
    twice = m.append([clear, dict(clear)], ACTION, BASE, path=path, stock=STOCK)
    assert twice.accepted == [SIDEBAR], "the first retracts it; the second has nothing to retract"
    assert "not in effect" in twice.rejected[0]["reason"]
    assert m.load(path).rev == 2
    never = m.append([{"op": "clear", "kind": "identity", "address": "identity:title"}], ACTION, BASE, path=path, stock=STOCK)
    assert never.accepted == [] and "not in effect" in never.rejected[0]["reason"]
    assert m.load(path).rev == 2, "a clear that retracts nothing appends nothing"
    again = m.append([element(), dict(clear)], ACTION, BASE, path=path, stock=STOCK)
    assert again.accepted == [SIDEBAR, SIDEBAR], "set then clear in one action is both effective"
    assert SIDEBAR not in m.resolve(m.load(path).records)


def test_a_field_nothing_reads_is_refused_rather_than_dropped_or_kept(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    result = m.append([dict(element(), note="keep me")], ACTION, BASE, path=path, stock=STOCK)
    assert result.accepted == [] and "does not read" in result.rejected[0]["reason"]
    assert not (tmp_path / "overlay").exists()
    with pytest.raises(m.ActionInvalid, match="does not read"):
        m.append([element()], dict(ACTION, mood="brisk"), BASE, path=path, stock=STOCK)
    with pytest.raises(m.ActionInvalid, match="base has keys the overlay does not read: extra"):
        m.append([element()], ACTION, dict(BASE, extra=1), path=path, stock=STOCK)
    with pytest.raises(m.ActionInvalid, match="base is missing: git"):
        m.append([element()], ACTION, {k: v for k, v in BASE.items() if k != "git"}, path=path, stock=STOCK)
    m.append([element()], ACTION, BASE, path=path, stock=STOCK)
    good = json.loads(path.read_text(encoding="utf-8"))
    for mutate in (
        lambda d: d["overlay"].update(extra=1),
        lambda d: d["records"][0].update(extra=1),
        lambda d: d["records"][0]["by"].update(extra=1),
        lambda d: d.update(extra=1),
    ):
        data = json.loads(json.dumps(good))
        mutate(data)
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(m.ManifestBroken, match="does not read"):
            m.load(path)


def test_a_locked_only_record_is_a_real_record_both_ways(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    result = m.append([
        element("element:chat:desktop:a", value={"locked": True}),
        element("element:chat:desktop:b", value={"locked": False}),
        element("element:chat:desktop:c", value={"locked": "false"}),
    ], ACTION, BASE, path=path, stock=STOCK)
    assert result.accepted == ["element:chat:desktop:a", "element:chat:desktop:b"], result.rejected
    assert "locked must be true or false" in reasons(result)["element:chat:desktop:c"]
    live = m.resolve(m.load(path).records)
    assert live["element:chat:desktop:a"]["value"] == {"locked": True}
    assert live["element:chat:desktop:b"]["value"] == {"locked": False}


def test_each_operation_and_kind_takes_exactly_its_own_keys(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    result = m.append([
        {"kind": "element", "address": SIDEBAR, "value": {"x": 1}, "anchor": ANCHOR},
        {"op": "clear", "kind": "element", "address": SIDEBAR, "value": {"x": 1}},
        {"op": "clear", "kind": "element", "address": SIDEBAR, "anchor": ANCHOR},
        {"op": "set", "kind": "element", "address": SIDEBAR, "value": {"x": 1}},
        {"op": "set", "kind": "identity", "address": "identity:name", "value": "Otto", "anchor": ANCHOR},
        {"op": "set", "kind": "identity", "address": "identity:name", "value": "Otto"},
    ], ACTION, BASE, path=path, stock=STOCK)
    assert result.accepted == ["identity:name"], result.rejected
    said = [row["reason"] for row in result.rejected]
    assert "op must be stated as set or clear" in said[0]
    assert "does not read: value" in said[1] and "does not read: anchor" in said[2]
    assert "missing: anchor" in said[3], "an element set must say how its target was found"
    assert "does not read: anchor" in said[4], "nothing else has an anchor to read"


def test_a_persisted_record_carries_exactly_what_its_operation_stores(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    m.append([element(), {"op": "clear", "kind": "element", "address": SIDEBAR}], ACTION, BASE, path=path, stock=STOCK)
    good = json.loads(path.read_text(encoding="utf-8"))
    stored_set, stored_clear = good["records"][0], good["records"][1]
    assert set(stored_set) == {"id", "at", "op", "kind", "address", "by", "base", "value", "stock_value", "anchor"}
    assert set(stored_clear) == {"id", "at", "op", "kind", "address", "by", "base"}
    assert set(stored_set["by"]) == {"actor", "action", "instruction", "targets"}
    assert set(stored_set["base"]) == {"thomas_version", "git", "web_build", "tokens_sha1"}
    for mutate in (
        lambda d: d["records"][1].update(value={"x": 1}),
        lambda d: d["records"][0].pop("stock_value"),
        lambda d: d["records"][0].pop("anchor"),
        lambda d: d["records"][0]["by"].pop("targets"),
        lambda d: d["records"][0]["base"].pop("git"),
    ):
        data = json.loads(json.dumps(good))
        mutate(data)
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(m.ManifestBroken):
            m.load(path)


def test_a_junction_anywhere_above_the_overlay_sends_no_bytes_outside_it(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("mine", encoding="utf-8")
    before = sorted((p.name, p.read_bytes()) for p in outside.iterdir())
    linked_home = tmp_path / "linked-home"
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(outside), str(linked_home))
    else:
        os.symlink(outside, linked_home, target_is_directory=True)
    path = linked_home / "overlay" / "manifest.json"
    with pytest.raises(m.OverlayUnsafe, match="link or junction"):
        m.append([element()], ACTION, BASE, path=path, stock=STOCK)
    assert sorted((p.name, p.read_bytes()) for p in outside.iterdir()) == before, "the redirected tree is byte for byte what it was"
    assert not (outside / "overlay").exists() and not store.lock_path_for(path).exists()
