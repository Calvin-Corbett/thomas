"""What the overlay refuses to write, and what it leaves behind when it does.

Every case here was a write that landed, or half-landed, when it should not
have: a crossed limit, a held lock, a disk that gave out mid-write, a link
redirecting the boundary, an element value out of bounds, an envelope that
could poison the manifest. A refusal writes nothing and says why.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from thomas.server.overlay import manifest as m
from thomas.server.overlay import store

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


def test_records_that_lie_about_their_shape_are_rejected_with_a_reason(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    bad = [
        {"op": "set", "kind": "token", "address": "token:nebula:--c-nope", "value": "#000"},
        {"op": "set", "kind": "token", "address": "token:nebula:--c-accent", "value": "url(x)"},
        {"op": "set", "kind": "theme", "address": "theme:nebula", "value": {"label": "x", "derives_from": "nebula", "color_scheme": "dark"}},
        {"op": "set", "kind": "element", "address": "element:chat:desktop:chat.shell", "value": {"style": {"backgroundColor": "#000"}},
         "anchor": {"exact": True, "fragile": False, "policy": "root protected"}},
        {"op": "set", "kind": "asset", "address": "asset:fonts/x.woff2", "value": {}},
        {"op": "set", "kind": "identity", "address": "identity:name", "value": "<script>"},
        {"op": "set", "kind": "identity", "address": "identity:mark", "value": "O"},
        {"op": "set", "kind": "token", "address": "token:x:--c-accent", "value": "#000"},
    ]
    result = m.append(bad, ACTION, BASE, path=path, stock=STOCK)
    assert result.accepted == ["identity:name"]  # escaped at render, allowed as text
    reasons = {r["address"]: r["reason"] for r in result.rejected}
    assert "not a stock token" in reasons["token:nebula:--c-nope"]
    assert "value" in reasons["token:nebula:--c-accent"]
    assert "stock" in reasons["theme:nebula"]
    assert "protected" in reasons["element:chat:desktop:chat.shell"]
    assert "phase 3" in reasons["asset:fonts/x.woff2"]
    assert "reserved" in reasons["identity:mark"], "a field no surface applies is refused, not stored as if it did something"
    assert "token:<theme>" in reasons["token:x:--c-accent"], "the write grammar and the render grammar agree on theme names"
    assert m.load(path).rev == 1


def test_a_caller_cannot_forge_an_editable_policy_for_a_protected_stock_element(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    result = m.append([element("element:chat:desktop:chat.shell")], ACTION, BASE, path=path, stock=STOCK)
    assert result.accepted == []
    assert result.rejected == [{"address": "element:chat:desktop:chat.shell", "reason": "this region is protected"}]
    assert not path.exists()


def test_a_held_lock_is_a_loud_failure_that_leaves_nothing_behind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    store.lock_path_for(path).write_text("", encoding="utf-8")
    monkeypatch.setattr(store, "_LOCK_MAX_RETRIES", 2)
    monkeypatch.setattr(store, "_LOCK_RETRY_INTERVAL", 0.01)
    with pytest.raises(m.OverlayLocked, match="lock is held"):
        m.append([element()], ACTION, BASE, path=path, stock=STOCK)
    assert not (tmp_path / "overlay").exists(), "a refused first write creates no directory and no birth files"

def test_a_first_write_refused_by_a_limit_leaves_nothing_behind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    monkeypatch.setattr(store, "_MAX_ACTIVE_OVERRIDES", 0)
    with pytest.raises(m.OverlayLimit):
        m.append([element()], ACTION, BASE, path=path, stock=STOCK)
    assert not (tmp_path / "overlay").exists() and not store.lock_path_for(path).exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == [], "not even a lock file stays"

def test_a_disk_failure_after_birth_rolls_back_only_what_this_write_created(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "overlay" / "manifest.json"

    def refuse(src, dst):
        raise OSError(28, "disk full")

    monkeypatch.setattr(store.os, "replace", refuse)
    with pytest.raises(m.OverlayWriteFailed, match="rolled back"):
        m.append([element()], ACTION, BASE, path=path, stock=STOCK)
    assert not (tmp_path / "overlay").exists(), "the directory and its birth files are gone"
    assert not store.lock_path_for(path).exists()
    monkeypatch.undo()
    born = m.append([element()], ACTION, BASE, path=path, stock=STOCK)
    (path.parent / "README.md").write_text("mine", encoding="utf-8")
    before = path.read_bytes()
    monkeypatch.setattr(store.os, "replace", refuse)
    with pytest.raises(m.OverlayWriteFailed):
        m.append([element(address="element:chat:desktop:b")], ACTION, BASE, path=path, stock=STOCK)
    assert path.read_bytes() == before and not list(path.parent.glob("*.tmp"))
    assert (path.parent / "README.md").read_text(encoding="utf-8") == "mine", "a preexisting user file is never touched"
    monkeypatch.undo()
    assert m.load(path).overlay_id == born.overlay_id

def test_an_element_value_must_stay_within_bounds(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    bad = [
        element(address="element:chat:desktop:a", x=10**9),
        element(address="element:chat:desktop:b", width=float("nan")),
        element(address="element:chat:desktop:c", y=True),
        element(address="element:chat:desktop:d", hidden="yes"),
        element(address="element:chat:desktop:e", icon="javascript:alert(1)"),
        element(address="element:chat:desktop:f", x=12.5, width=320, hidden=False, icon="ph-gear-six"),
    ]
    result = m.append(bad, ACTION, BASE, path=path, stock=STOCK)
    assert result.accepted == ["element:chat:desktop:f"]
    reasons = {r["address"].rsplit(":", 1)[1]: r["reason"] for r in result.rejected}
    assert "x must be a finite number" in reasons["a"] and "width must be" in reasons["b"] and "y must be" in reasons["c"]
    assert "hidden" in reasons["d"] and "icon" in reasons["e"]

def test_the_active_override_cap_refuses_the_next_set_without_writing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    monkeypatch.setattr(store, "_MAX_ACTIVE_OVERRIDES", 3)
    for n in range(3):
        m.append([element(address=f"element:chat:desktop:row{n}", x=n)], ACTION, BASE, path=path, stock=STOCK)
    before = path.read_bytes()
    with pytest.raises(m.OverlayLimit, match="cap of 3"):
        m.append([element(address="element:chat:desktop:row3", x=3)], ACTION, BASE, path=path, stock=STOCK)
    assert path.read_bytes() == before, "a refused write changes nothing"
    with pytest.raises(m.OverlayLimit):
        m.append([
            {"op": "clear", "kind": "element", "address": "element:chat:desktop:row0"},
            element(address="element:chat:desktop:row3", x=3),
            element(address="element:chat:desktop:row4", x=4),
        ], ACTION, BASE, path=path, stock=STOCK)
    assert path.read_bytes() == before, "clear plus set cannot slip past the resolved cap"
    swapped = m.append([
        {"op": "clear", "kind": "element", "address": "element:chat:desktop:row0"},
        element(address="element:chat:desktop:row3", x=3),
    ], ACTION, BASE, path=path, stock=STOCK)
    assert swapped.rev == 5 and len(m.resolve(m.load(path).records)) == 3
    monkeypatch.setattr(store, "_MAX_RECORDS_PER_APPEND", 2)
    with pytest.raises(m.OverlayLimit, match="per write"):
        m.append([element(address="element:chat:desktop:a"), element(address="element:chat:desktop:b"), element(address="element:chat:desktop:c")], ACTION, BASE, path=path, stock=STOCK)
    monkeypatch.setattr(store, "_MAX_RECORDS_PER_APPEND", 200)
    monkeypatch.setattr(store, "_MAX_MANIFEST_BYTES", len(path.read_bytes()) + 1)
    with pytest.raises(m.OverlayLimit, match="bytes"):
        m.append([{"op": "clear", "kind": "element", "address": "element:chat:desktop:row1"}], ACTION, BASE, path=path, stock=STOCK)
    assert m.load(path).rev == 5

def test_a_clear_must_name_a_valid_address_and_the_action_envelope_is_checked_first(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    m.append([element()], ACTION, BASE, path=path, stock=STOCK)
    clears = [
        {"op": "clear", "kind": "theme", "address": 'theme:x"]{} </style><script>alert(1)</script>/*'},
        {"op": "clear", "kind": "asset", "address": "asset:../../etc/passwd"},
        {"op": "clear", "kind": "identity", "address": "identity:mark"},
        {"op": "clear", "kind": "identity", "address": "identity:onload"},
        {"op": "clear", "kind": "setting", "address": "setting:evil"},
        {"op": "clear", "kind": "token", "address": "token:x:--c-accent"},
        {"op": "clear", "kind": "element", "address": "element:chat:desktop:chat.sidebar"},
    ]
    result = m.append(clears, ACTION, BASE, path=path, stock=STOCK)
    assert result.accepted == ["element:chat:desktop:chat.sidebar"], result.rejected
    assert len(result.rejected) == 6 and m.load(path).rev == 2
    before = path.read_bytes()
    for bad_action in (
        {"actor": "x", "targets": []},
        {"actor": "x", "instruction": "hi"},
        {"actor": "x" * 81, "instruction": "hi", "targets": []},
        {"actor": "", "instruction": "hi", "targets": []},
        {"actor": {"name": "x"}, "instruction": "hi", "targets": []},
        {"actor": "x", "instruction": {"text": "hi"}, "targets": []},
        {"actor": "x", "instruction": "hi", "targets": "chat.sidebar"},
        {"actor": "x", "instruction": "hi", "targets": [1, 2]},
        {"actor": "x", "instruction": "x" * 2001, "targets": []},
    ):
        with pytest.raises(m.ActionInvalid):
            m.append([element(address="element:chat:desktop:again")], bad_action, BASE, path=path, stock=STOCK)
    with pytest.raises(m.ActionInvalid):
        m.append([element(address="element:chat:desktop:again")], ACTION, {"thomas_version": 1}, path=path, stock=STOCK)
    assert path.read_bytes() == before, "an invalid envelope writes nothing"
    assert m.load(path).rev == 2, "and what was written before still loads"

def test_a_lock_path_that_is_a_link_is_refused_and_never_unlinked(tmp_path: Path) -> None:
    path = tmp_path / "overlay" / "manifest.json"
    target = tmp_path / "elsewhere"
    target.mkdir()
    lock = store.lock_path_for(path)
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(lock))
    else:
        os.symlink(target, lock, target_is_directory=True)
    with pytest.raises(m.OverlayUnsafe):
        m.append([element()], ACTION, BASE, path=path, stock=STOCK)
    assert os.path.lexists(lock) and target.exists(), "the link stays exactly as it was"
    assert not (tmp_path / "overlay").exists()

def test_a_junction_at_the_overlay_directory_is_refused_and_nothing_leaks(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir()
    link = tmp_path / "overlay"
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)
    with pytest.raises(m.OverlayUnsafe):
        m.append([element()], ACTION, BASE, path=link / "manifest.json", stock=STOCK)
    assert list(target.iterdir()) == [], "nothing was written through the junction"
    inner = tmp_path / "real"
    inner.mkdir()
    (inner / "elsewhere.json").write_text("{}", encoding="utf-8")
    if sys.platform == "win32":
        _winapi.CreateJunction(str(target), str(inner / "manifest.json"))
    else:
        os.symlink(inner / "elsewhere.json", inner / "manifest.json")
    with pytest.raises(m.OverlayUnsafe):
        m.append([element()], ACTION, BASE, path=inner / "manifest.json", stock=STOCK)


def test_a_live_lock_owner_is_never_stolen_when_its_marker_is_old(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = tmp_path / "overlay.lock"
    monkeypatch.setattr(store, "_LOCK_STALE_SECONDS", -1.0)
    monkeypatch.setattr(store, "_LOCK_MAX_RETRIES", 100)
    monkeypatch.setattr(store, "_LOCK_RETRY_INTERVAL", 0.005)
    first_entered, release_first, second_entered = threading.Event(), threading.Event(), threading.Event()
    inside = 0
    maximum = 0
    guard = threading.Lock()

    def contender(entered: threading.Event, release: threading.Event | None = None) -> None:
        nonlocal inside, maximum
        with store.locked(lock):
            with guard:
                inside += 1
                maximum = max(maximum, inside)
            entered.set()
            if release is not None:
                assert release.wait(2)
            with guard:
                inside -= 1

    first = threading.Thread(target=contender, args=(first_entered, release_first))
    second = threading.Thread(target=contender, args=(second_entered,))
    first.start()
    assert first_entered.wait(1)
    second.start()
    try:
        time.sleep(0.05)
        assert not second_entered.is_set(), "mtime alone must not steal a live owner's lock"
    finally:
        release_first.set()
        first.join(2)
        second.join(2)
    assert second_entered.is_set() and maximum == 1 and not lock.exists()


def test_only_a_positively_dead_owner_is_reaped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock = tmp_path / "overlay.lock"
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait(timeout=5)
    lock.write_text(json.dumps({"pid": dead.pid, "token": "d" * 32}), encoding="utf-8")
    os.utime(lock, (0, 0))
    with store.locked(lock):
        assert lock.exists()
    assert not lock.exists()

    lock.write_text("not an owned marker", encoding="utf-8")
    os.utime(lock, (0, 0))
    monkeypatch.setattr(store, "_LOCK_MAX_RETRIES", 2)
    monkeypatch.setattr(store, "_LOCK_RETRY_INTERVAL", 0.001)
    with pytest.raises(m.OverlayLocked):
        with store.locked(lock):
            pass
    assert lock.read_text(encoding="utf-8") == "not an owned marker"


def test_a_predecessor_never_unlinks_a_successor_marker(tmp_path: Path) -> None:
    lock = tmp_path / "overlay.lock"
    successor = {"pid": os.getpid(), "token": "b" * 32}
    lock.write_text(json.dumps(successor), encoding="utf-8")
    store._release_owned(lock, "a" * 32)
    assert json.loads(lock.read_text(encoding="utf-8")) == successor
