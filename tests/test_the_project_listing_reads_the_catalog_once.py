"""A self-project listing reuses its own snapshots, but never carries them into another listing."""

import json
import time
from collections import Counter
from pathlib import Path

import pytest

from thomas.forge.anvil import forge_code_projects
from thomas.server import green_checkout, green_handoff, hand_in_hold, thomas_project
from thomas.server.routes import self_project_routes as routes

CONVERSATIONS = Path(".thomas/evolve/agent/conversations")


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root, catalog = tmp_path / "green", tmp_path / "catalog"
    catalog.mkdir()
    (catalog / CONVERSATIONS).mkdir(parents=True)
    monkeypatch.setenv("THOMAS_CAPACITY_LEDGER_ROOT", str(tmp_path / "capacity"))
    monkeypatch.setattr(green_checkout, "green_root", lambda: root)
    monkeypatch.setattr(green_handoff, "sibling_changes", lambda _id: {"e1": ["changed.py"]})
    monkeypatch.setattr(thomas_project, "held_steers", lambda _cid: [])
    return root, catalog


def conversation(root: Path, number: int, *, agent: bool = False) -> tuple[str, Path, dict]:
    cid = f"fc_{number}"
    path = root / "work" / f"e{number}" / CONVERSATIONS / f"{cid}.json"
    path.parent.mkdir(parents=True)
    record = {
        "id": cid,
        "title": f"Green {number}",
        "updated_at": f"2026-10-19T10:0{number}:00+00:00",
        "thomas_project": {"execution_id": f"e{number}", "chat_session_id": f"chat{number}"},
        "turns": ([{"role": "agent", "reason": "done", "ts": "2026-10-19T10:00:00+00:00"}] if agent else []),
        "fixture_padding": "x" * (number * 101),
    }
    path.write_text(json.dumps(record), encoding="utf-8")
    return cid, path, record


def registry(catalog: Path, cids: list[str], *, large: bool = False) -> Path:
    path = catalog / ".thomas/evolve/agent/project_registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        cid: {"settings": {"requested": {"autonomy_level": 0}}, "padding": "x" * (110_000 if large else 0)}
        for cid in cids
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def hold(catalog: Path, cid: str, record: dict, *, state: str = "spent") -> Path:
    path = catalog / ".thomas/evolve/agent/hand_in_holds.json"
    rows = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    rows.append(
        {
            "cid": cid,
            "gen": hand_in_hold.generation(record),
            "state": state,
            "step": "check",
            "why": "offline",
            "tries": 1,
            "next_at": 0,
        }
    )
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def count_reads(monkeypatch: pytest.MonkeyPatch):
    counts = Counter()
    sizes = Counter()
    original_text, original_bytes, original_loads = Path.read_text, Path.read_bytes, json.loads
    original_open = Path.open

    def open_record(path, mode="r", *args, **kwargs):
        if mode == "rb":
            counts[Path(path)] += 1
        return original_open(path, mode, *args, **kwargs)

    def text(path, *args, **kwargs):
        counts[Path(path)] += 1
        return original_text(path, *args, **kwargs)

    def data(path, *args, **kwargs):
        return original_bytes(path, *args, **kwargs)

    def loads(value, *args, **kwargs):
        sizes[len(value)] += 1
        return original_loads(value, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_record)
    monkeypatch.setattr(Path, "read_text", text)
    monkeypatch.setattr(Path, "read_bytes", data)
    monkeypatch.setattr(json, "loads", loads)
    return counts, sizes


def test_large_catalog_and_each_green_and_hold_are_read_once_per_listing(scene, monkeypatch):
    root, catalog = scene
    greens = [conversation(root, i, agent=i in (2, 3)) for i in range(1, 6)]
    reg = registry(catalog, [cid for cid, _, _ in greens], large=True)
    assert reg.stat().st_size >= 500_000
    holds = hold(catalog, greens[1][0], greens[1][2])
    hold(catalog, greens[2][0], greens[2][2], state="checking")
    counts, sizes = count_reads(monkeypatch)
    paths = [reg, holds, *(path for _, path, _ in greens)]
    lengths = [len(path.read_bytes()) for path in paths]
    counts.clear()
    sizes.clear()

    routes.read_projects(catalog, changed_files=False)
    assert {str(path): counts[path] for path in paths} == {str(path): 1 for path in paths}
    # Only shared registry/hold records are decoded whole; conversations stream.
    assert all(sizes[length] == 1 for length in lengths[:2])
    assert all(sizes[length] == 0 for length in lengths[2:])

    routes.read_projects(catalog, changed_files=False)
    # The registry and the hold are read again; a conversation that has not changed is taken from memory.
    assert all(counts[path] == 2 for path in paths[:2])
    assert all(counts[path] == 1 for path in paths[2:])
    assert all(sizes[length] == 2 for length in lengths[:2])
    assert all(sizes[length] == 0 for length in lengths[2:])


def test_a_new_agent_turn_is_visible_in_the_next_listing(scene):
    root, catalog = scene
    cid, path, record = conversation(root, 1)
    registry(catalog, [cid])
    first = routes.read_projects(catalog, changed_files=False)["projects"][0]
    record["turns"].append({"role": "agent", "reason": "finished", "ts": "2026-10-19T10:01:00+00:00"})
    path.write_text(json.dumps(record), encoding="utf-8")
    second = routes.read_projects(catalog, changed_files=False)["projects"][0]
    assert (first["state"], first["detail"]) != (second["state"], second["detail"])


def test_listing_preserves_the_complete_dev_report(scene):
    root, catalog = scene
    greens = [conversation(root, i, agent=i in (2, 3, 5, 6)) for i in range(1, 7)]
    registry(catalog, [cid for cid, _, _ in greens])
    for _, path, record in (greens[1], greens[2]):
        record["turns"][-1].update(ok=True, outcome="completed")
        path.write_text(json.dumps(record), encoding="utf-8")
    hold(catalog, greens[1][0], greens[1][2], state="held")
    retry_at = time.strftime("%Y-%m-%d %H:%M", time.localtime(0))
    hold(catalog, greens[2][0], greens[2][2], state="checking")
    hold(catalog, greens[5][0], greens[5][2], state="spent")
    greens[3][1].unlink()
    handed = {
        **greens[4][2],
        "thomas_project": {
            **greens[4][2]["thomas_project"],
            "summary": "ready",
            "submission": "",
        },
    }
    (catalog / CONVERSATIONS / "fc_5.json").write_text(json.dumps(handed), encoding="utf-8")
    expected = {
        "ok": True,
        "projects": [
            {
                "conversation_id": "fc_6",
                "execution_id": "e6",
                "title": "Green 6",
                "chat_session_id": "chat6",
                "state": "stopped",
                "detail": "Never handed in: check could not run (offline) after 1 tries. Send a message and Thomas carries on",
                "submission": "",
                "checked": "",
                "last_verdict": None,
                "changed_files": [],
                "updated_at": "2026-10-19T10:06:00+00:00",
            },
            {
                "conversation_id": "fc_3",
                "execution_id": "e3",
                "title": "Green 3",
                "chat_session_id": "chat3",
                "state": "running",
                "detail": "Your finished change is being checked before your approval card.",
                "submission": "",
                "checked": "",
                "last_verdict": None,
                "changed_files": [],
                "updated_at": "2026-10-19T10:03:00+00:00",
            },
            {
                "conversation_id": "fc_2",
                "execution_id": "e2",
                "title": "Green 2",
                "chat_session_id": "chat2",
                "state": "paused",
                "detail": f"Held before your approval card: check could not run (offline). Tries again by himself {retry_at} (try 1)",
                "submission": "",
                "checked": "",
                "last_verdict": None,
                "changed_files": [],
                "updated_at": "2026-10-19T10:02:00+00:00",
            },
            {
                "conversation_id": "fc_1",
                "execution_id": "e1",
                "title": "Green 1",
                "chat_session_id": "chat1",
                "state": "running",
                "detail": "its first Build run is starting",
                "submission": "",
                "checked": "",
                "last_verdict": None,
                "changed_files": ["changed.py"],
                "updated_at": "2026-10-19T10:01:00+00:00",
            },
            {
                "conversation_id": "fc_5",
                "execution_id": "e5",
                "title": "Green 5",
                "chat_session_id": "chat5",
                "state": "handing in",
                "detail": "being handed to your approval card",
                "submission": "",
                "checked": "",
                "last_verdict": None,
                "changed_files": [],
                "updated_at": "2026-10-19T10:05:00+00:00",
            },
        ],
        "unreadable": [],
        "skipped": [],
    }
    actual = routes.read_projects(catalog, changed_files=True)
    assert actual["slowest_today"] is None
    for project in actual["projects"]:
        assert project.pop("timings_seconds") == dict.fromkeys(
            ("building", "checks", "second_look", "repair_rounds", "card_wait")
        )
    actual.pop("slowest_today")
    board = actual.pop("speed_scoreboard")
    assert isinstance(board.pop("disk_free_gb"), (float, type(None)))
    for period in ("today", "last_week"):
        assert board[period].pop("cost")["hours_per_landing"] is None  # nothing landed, so no per-landing number
    assert board == {
        "today": {"median_seconds": None, "landed": 0, "steps": None, "peak_teams": 0},
        "last_week": {"median_seconds": None, "landed": 0, "steps": None, "peak_teams": 0},
        "faster_percent": None,
    }
    assert actual.pop("warnings") == []
    assert actual == expected


@pytest.mark.parametrize("handed_in", [False, True])
def test_corrupt_hold_file_does_not_block_projects_that_skip_phase(scene, handed_in):
    root, catalog = scene
    cid, _, record = conversation(root, 1)
    registry(catalog, [cid])
    if handed_in:
        record["thomas_project"]["settled_at"] = "2026-10-19T10:10:00+00:00"
        (catalog / CONVERSATIONS / f"{cid}.json").write_text(json.dumps(record), encoding="utf-8")
    holds_path = catalog / ".thomas" / "evolve" / "agent" / "hand_in_holds.json"
    holds_path.parent.mkdir(parents=True, exist_ok=True)
    holds_path.write_text("{broken", encoding="utf-8")
    report = routes.read_projects(catalog, running=set() if handed_in else {cid}, changed_files=False)
    assert report["ok"] is True
    assert [row["conversation_id"] for row in report["projects"]] == [cid]
    assert report["projects"][0]["state"] == ("no changes" if handed_in else "running")
    assert report["unreadable"] == []


def test_chat_task_card_phase_keeps_its_three_argument_answer(scene):
    root, catalog = scene
    greens = [conversation(root, i, agent=i == 2) for i in range(1, 4)]
    registry(catalog, [cid for cid, _, _ in greens])
    hold(catalog, greens[1][0], greens[1][2], state="spent")
    greens[2][1].unlink()
    assert [thomas_project.project_phase(root / "work" / f"e{i}", catalog, greens[i - 1][0]) for i in range(1, 4)] == [
        ("waiting", ""),
        ("ended", "Never handed in: check could not run (offline) after 1 tries. Send a message and Thomas carries on"),
        ("ended", "its Build conversation is gone"),
    ]
