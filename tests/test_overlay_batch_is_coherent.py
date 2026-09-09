"""A write leaves a state that holds together, or it does not happen at all.

Records are the whole story the overlay tells, so nothing cascades quietly:
clearing a theme that tokens or the default still point at refuses the entire
action with the manifest untouched, and the caller has to say what happens to
the dependants. These are the exact sequences that used to slip through.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from thomas.server.overlay import manifest as m

STOCK = {"nebula": {"--c-accent": "#8b8cff", "--c-bg": "#070912"}, "dark": {"--c-accent": "#6e9bff"},
         "light": {}, "aurora": {}, "sandstone": {}}
BASE = {"thomas_version": "0.19.27", "git": "abc1234", "web_build": "0123456789ab", "tokens_sha1": "f" * 40}
ACTION = {"actor": "test", "instruction": "themes", "targets": []}


def theme(name: str = "ember", parent: str = "nebula") -> dict:
    return {"op": "set", "kind": "theme", "address": f"theme:{name}",
            "value": {"label": name.title(), "derives_from": parent, "color_scheme": "dark"}}


def token(name: str = "ember", key: str = "--c-accent", value: str = "#2ecc71") -> dict:
    return {"op": "set", "kind": "token", "address": f"token:{name}:{key}", "value": value}


def default(name: str = "ember") -> dict:
    return {"op": "set", "kind": "setting", "address": "setting:default_theme", "value": name}


def clear(address: str) -> dict:
    return {"op": "clear", "kind": address.split(":", 1)[0], "address": address}


def write(path: Path, records: list[dict]):
    return m.append(records, ACTION, BASE, path=path, stock=STOCK)


def test_a_token_must_name_a_theme_that_exists_at_that_point(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    result = write(path, [token("ghost"), theme(), token()])
    assert result.accepted == ["theme:ember", "token:ember:--c-accent"], result.rejected
    assert "not a theme this Thomas has" in result.rejected[0]["reason"]
    assert write(path, [token("nebula", value="#111111")]).accepted == ["token:nebula:--c-accent"]
    assert write(path, [{"op": "set", "kind": "token", "address": "token:*:--c-bg", "value": "#000000"}]).accepted


def test_clearing_a_theme_its_tokens_still_point_at_refuses_the_whole_action(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    write(path, [theme(), token()])
    before, rev = path.read_bytes(), m.load(path).rev
    with pytest.raises(m.OverlayIncoherent, match="token:ember:--c-accent"):
        write(path, [clear("theme:ember")])
    assert path.read_bytes() == before and m.load(path).rev == rev, "nothing was written and rev did not move"
    # The same action may say what happens to the dependant, either way.
    assert write(path, [clear("token:ember:--c-accent"), clear("theme:ember")]).accepted == [
        "token:ember:--c-accent", "theme:ember"]
    assert "theme:ember" not in m.resolve(m.load(path).records)


def test_clear_then_re_add_cannot_resurrect_an_untouched_token(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    write(path, [theme(), token()])
    before, rev = path.read_bytes(), m.load(path).rev
    with pytest.raises(m.OverlayIncoherent, match="explicitly"):
        write(path, [clear("theme:ember"), theme("ember", parent="dark")])
    assert path.read_bytes() == before and m.load(path).rev == rev
    revived = write(path, [clear("token:ember:--c-accent"), clear("theme:ember"),
                           theme("ember", parent="dark"), token()])
    assert revived.accepted == ["token:ember:--c-accent", "theme:ember", "theme:ember",
                                "token:ember:--c-accent"], revived.rejected
    live = m.resolve(m.load(path).records)
    assert live["theme:ember"]["value"]["derives_from"] == "dark"
    assert live["token:ember:--c-accent"]["value"] == "#2ecc71"


def test_a_default_theme_may_not_be_left_pointing_at_nothing(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    with pytest.raises(m.OverlayIncoherent, match="default theme"):
        write(path, [theme(), default(), clear("theme:ember")])
    assert not (tmp_path / "overlay").exists(), "a refused first action creates nothing"
    write(path, [theme(), default()])
    before = path.read_bytes()
    with pytest.raises(m.OverlayIncoherent, match="default theme"):
        write(path, [clear("theme:ember")])
    assert path.read_bytes() == before
    # Repointing the default in the same action is what makes the clear legal.
    assert write(path, [default("dark"), clear("theme:ember")]).accepted == ["setting:default_theme", "theme:ember"]
    assert m.resolve(m.load(path).records)["setting:default_theme"]["value"] == "dark"


def test_a_refused_action_leaves_no_lock_and_no_directory(tmp_path: Path) -> None:
    from thomas.server.overlay import store

    path = tmp_path / "overlay" / "manifest.json"
    with pytest.raises(m.OverlayIncoherent):
        write(path, [theme(), default(), clear("theme:ember")])
    assert not (tmp_path / "overlay").exists()
    assert not store.lock_path_for(path).exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == []


def _stored_clear(source: dict, number: int, action: str) -> dict:
    return {
        "id": f"r{number:04d}", "at": source["at"], "op": "clear", "kind": source["kind"],
        "address": source["address"], "by": dict(source["by"], action=action), "base": source["base"],
    }


@pytest.mark.parametrize("dependent", ["token", "default"])
def test_a_loaded_manifest_cannot_end_with_an_orphan_dependency(tmp_path: Path, dependent: str) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    dependency = token() if dependent == "token" else default()
    write(path, [theme(), dependency])
    data = json.loads(path.read_text(encoding="utf-8"))
    data["records"].append(_stored_clear(data["records"][0], 3, "act_20260902T180000Z_dead"))
    path.write_text(json.dumps(data), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(m.ManifestBroken, match="resolv|pointing"):
        m.load(path)
    assert path.read_bytes() == before, "load reports the broken history and never rewrites it"


def test_a_loaded_history_cannot_resurrect_an_untouched_dependency(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    write(path, [theme(), token()])
    data = json.loads(path.read_text(encoding="utf-8"))
    original = data["records"][0]
    action = "act_20260902T180001Z_beef"
    data["records"].append(_stored_clear(original, 3, action))
    revived = copy.deepcopy(original)
    revived.update(id="r0004", by=dict(original["by"], action=action),
                   value={"label": "Ember", "derives_from": "dark", "color_scheme": "dark"})
    data["records"].append(revived)
    path.write_text(json.dumps(data), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(m.ManifestBroken, match="explicitly"):
        m.load(path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("record", [
    token("nebula"),
    theme(),
    {"op": "set", "kind": "element", "address": "element:chat:desktop:chat.sidebar", "value": {"x": 1},
     "anchor": {"exact": True, "fragile": False, "component": "aside", "label": "Sidebar", "policy": "move", "path": ""}},
    {"op": "set", "kind": "identity", "address": "identity:name", "value": "Otto"},
    default("dark"),
])
def test_an_identical_set_is_not_a_durable_change(tmp_path: Path, record: dict) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    same_action = write(path, [copy.deepcopy(record), copy.deepcopy(record)])
    assert same_action.accepted == [record["address"]]
    assert len(same_action.rejected) == 1 and "already in effect" in same_action.rejected[0]["reason"]
    before, rev = path.read_bytes(), m.load(path).rev
    later = write(path, [copy.deepcopy(record)])
    assert later.accepted == [] and "already in effect" in later.rejected[0]["reason"]
    assert path.read_bytes() == before and m.load(path).rev == rev


@pytest.mark.parametrize("record", [
    token("nebula", value="  #2ecc71  "),
    {"op": "set", "kind": "identity", "address": "identity:name", "value": " Otto "},
    {"op": "set", "kind": "theme", "address": "theme:t1",
     "value": {"label": " Ember ", "derives_from": "nebula", "color_scheme": "dark"}},
    {"op": "set", "kind": "theme", "address": "theme:t2",
     "value": {"label": "Ember", "derives_from": "nebula", "color_scheme": "dark", "swatches": [" #000", "#111", "#222"]}},
    {"op": "set", "kind": "theme", "address": "theme:t3",
     "value": {"label": "Ember", "derives_from": "nebula", "color_scheme": "dark", "meta": {"menuBg": " #000 "}}},
    {"op": "set", "kind": "theme", "address": "theme:t4",
     "value": {"label": "Ember", "derives_from": "nebula", "color_scheme": "dark", "meta": {"welcome": [" Hello", "there"]}}},
])
def test_client_trimmed_strings_must_arrive_canonical_and_write_nothing(tmp_path: Path, record: dict) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    result = write(path, [record])
    assert result.accepted == [] and "canonical" in result.rejected[0]["reason"]
    assert not path.parent.exists()


@pytest.mark.parametrize("value", [
    {"label": 'Em"ber', "derives_from": "nebula", "color_scheme": "dark"},
    {"label": "Ember", "tagline": "Warm`", "derives_from": "nebula", "color_scheme": "dark"},
    {"label": "Ember", "derives_from": "nebula", "color_scheme": "dark", "meta": {"msgRule": '1px solid "red"'}},
    {"label": "Ember", "derives_from": "nebula", "color_scheme": "dark", "meta": {"composerAccent": "bad`value"}},
    {"label": "Ember", "derives_from": "nebula", "color_scheme": "dark", "meta": {"welcome": ["Hello\\there", "again"]}},
])
def test_theme_markup_sink_strings_are_refused_instead_of_silently_dropped(tmp_path: Path, value: dict) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    result = write(path, [{"op": "set", "kind": "theme", "address": "theme:ember", "value": value}])
    assert result.accepted == [] and "markup-safe" in result.rejected[0]["reason"]
    assert not path.parent.exists()


def test_a_quoted_font_stack_remains_valid_for_its_css_only_sink(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    spec = {"label": "Ember", "derives_from": "nebula", "color_scheme": "dark", "meta": {"fontHead": '"Inter", sans-serif'}}
    assert write(path, [{"op": "set", "kind": "theme", "address": "theme:ember", "value": spec}]).accepted == ["theme:ember"]


@pytest.mark.parametrize(("section", "field", "value"), [
    ("by", "actor", "mallory"),
    ("by", "instruction", "a different instruction"),
    ("by", "targets", ["other"]),
    ("base", "git", "different"),
])
def test_one_action_cannot_contradict_its_own_envelope(
    tmp_path: Path, section: str, field: str, value: object,
) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    write(path, [theme("t1"), theme("t2")])
    data = json.loads(path.read_text(encoding="utf-8"))
    data["records"][1][section][field] = value
    path.write_text(json.dumps(data), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(m.ManifestBroken, match="action envelope"):
        m.load(path)
    assert path.read_bytes() == before


def test_an_action_id_cannot_reappear_after_another_action(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    for name in ("t1", "t2", "t3"):
        write(path, [theme(name)])
    data = json.loads(path.read_text(encoding="utf-8"))
    data["records"][2]["by"] = copy.deepcopy(data["records"][0]["by"])
    path.write_text(json.dumps(data), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(m.ManifestBroken, match="reappears"):
        m.load(path)
    assert path.read_bytes() == before
