"""A Thomas with its own data folder looks for legacy Work files there, never in the machine user's home."""

import json

from thomas.core.owned_root import freedom_transit_dir, global_skills_dir, thomas_owned_tree
from thomas.work.lanes.proposals import GateProposalStore
from thomas.work.lanes.stats import GateStatsStore
from thomas.work.lanes.store import LaneStore
from thomas.work.store import WorkStore

MARKER = "marker-legacy-app-7f3a"


def _fake_home(tmp_path):
    home = tmp_path / "home"
    folder = home / ".thomas" / "freedom_transit"
    folder.mkdir(parents=True)
    (folder / "work_apps.json").write_text(
        json.dumps({"apps": [{"id": MARKER, "name": "Marker", "jobs": []}]}), encoding="utf-8"
    )
    return home


def _config(root):
    class _Memory:
        root_path = str(root)

    class _Config:
        memory = _Memory()

    return _Config()


def _clean_env(monkeypatch):
    for name in ("THOMAS_DATA_DIR", "THOMAS_OWNED_ROOT", "THOMAS_PROFILE"):
        monkeypatch.delenv(name, raising=False)


def test_a_moved_data_dir_ignores_the_real_home(tmp_path, monkeypatch):
    home = _fake_home(tmp_path)
    _clean_env(monkeypatch)
    for name in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(name, str(home))
    data = tmp_path / "data"
    monkeypatch.setenv("THOMAS_DATA_DIR", str(data))
    store = WorkStore.from_config(_config(tmp_path / "memory"))
    assert MARKER not in json.dumps(store._state)
    assert home not in thomas_owned_tree().parents
    assert thomas_owned_tree() == data.resolve() / ".thomas"


def test_an_owned_root_names_the_tree_outright(tmp_path):
    env = {"THOMAS_OWNED_ROOT": str(tmp_path / "owned"), "THOMAS_DATA_DIR": str(tmp_path / "d")}
    assert freedom_transit_dir(env=env) == tmp_path / "owned" / "freedom_transit"
    assert global_skills_dir(env=env) == tmp_path / "owned" / "skills"


def test_the_default_setup_still_migrates_the_legacy_file(tmp_path):
    home = _fake_home(tmp_path)
    source = freedom_transit_dir(env={}, home=home) / "work_apps.json"
    assert source == home / ".thomas" / "freedom_transit" / "work_apps.json"
    store = WorkStore(tmp_path / "memory", user_work_apps_path=source)
    assert MARKER in json.dumps(store._state)
    assert global_skills_dir(env={}, home=home) == home / ".thomas" / "skills"


def test_the_lane_stores_follow_the_moved_data_dir(tmp_path, monkeypatch):
    _clean_env(monkeypatch)
    data = tmp_path / "data"
    monkeypatch.setenv("THOMAS_DATA_DIR", str(data))
    folder = data.resolve() / ".thomas" / "freedom_transit"
    assert LaneStore().path == folder / "work_lanes.json"
    assert GateProposalStore().path == folder / "work_lane_proposals.json"
    assert GateStatsStore().path == folder / "work_lane_stats.json"


def test_the_lane_stores_default_to_the_home_tree(tmp_path, monkeypatch):
    _clean_env(monkeypatch)
    home = tmp_path / "h"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    assert LaneStore().path == home / ".thomas" / "freedom_transit" / "work_lanes.json"
