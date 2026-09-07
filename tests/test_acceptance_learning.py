"""A caught miss becomes a permanent check for the project."""

from __future__ import annotations

import json
from pathlib import Path

from thomas.core import acceptance_contract as ac
from thomas.core import acceptance_learning as al


def _repo(tmp_path: Path) -> Path:
    (tmp_path / ".git").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "aircraft.json").write_text(json.dumps({"turnaround_time_min": 25}), encoding="utf-8")
    return tmp_path


def test_misses_are_recorded_under_the_project_and_come_back_as_checks(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    field = ac.ContractItem(
        "field:aircraft.json:turnaround_time_min",
        ac.KIND_DATA_FIELD,
        "turnaround consumed",
        "aircraft.json",
        "turnaround_time_min",
        True,
        False,
        "missing",
    )
    launch = ac.ContractItem(
        "req:3", ac.KIND_REQUIREMENT, "The app opens without an error.", "prompt", "", True, False, "evaluator: unmet"
    )
    path = al.record_misses(repo, [field], caught=True, run_id="run-1")
    al.record_misses(repo, [launch, field], caught=False, run_id="run-2")
    assert path == repo / "runtime" / "coordination" / "verification" / "learned_checks.json"
    rows = {r["item_id"]: r for r in json.loads(path.read_text(encoding="utf-8"))}
    assert rows["field:aircraft.json:turnaround_time_min"]["count"] == 2
    assert (
        rows["field:aircraft.json:turnaround_time_min"]["caught"] == 1
        and rows["field:aircraft.json:turnaround_time_min"]["escaped"] == 1
    )
    assert rows["req:3"]["last_run_id"] == "run-2" and "T" in rows["req:3"]["first_seen"]

    learned = al.load_learned(repo)
    kinds = {row["item_id"]: row["kind"] for row in learned}
    assert kinds["field:aircraft.json:turnaround_time_min"] == ac.KIND_DATA_FIELD
    assert kinds["learned:req:3"] == ac.KIND_LEARNED
    items = ac.build_contract("do the thing", repo, learned=learned)
    assert any(
        it.item_id == "field:aircraft.json:turnaround_time_min" and it.kind == ac.KIND_DATA_FIELD for it in items
    )
    assert any(it.item_id == "learned:req:3" and not it.checked for it in items)


def test_a_learned_data_field_is_dropped_when_the_project_has_no_such_file(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    field = ac.ContractItem(
        "field:weather.json:mea_ft", ac.KIND_DATA_FIELD, "mea consumed", "weather.json", "mea_ft", True, False, ""
    )
    al.record_misses(repo, [field], caught=False)
    assert al.load_learned(repo) == []


def test_a_bare_folder_records_under_the_user_root_not_the_workspace(tmp_path: Path, monkeypatch) -> None:
    bare = tmp_path / "container-app"
    bare.mkdir()
    data_dir = tmp_path / "thomas-data"
    monkeypatch.delenv("THOMAS_PROJECT_ROOT", raising=False)
    root = al.learning_root(bare, env=dict(THOMAS_DATA_DIR=str(data_dir)))
    assert not str(root).startswith(str(bare))
    assert root.parent.name == "projects" and root.name.startswith("container-app-")


def test_nothing_to_record_writes_nothing(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert al.record_misses(repo, [], caught=True) is None
    assert not al.learned_path(repo).exists()
