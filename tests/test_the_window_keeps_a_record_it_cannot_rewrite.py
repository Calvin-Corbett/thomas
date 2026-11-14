"""The window's record: write-once events that each name the one before, and a summary read from dev (spec 8.4).

Its own tmp folder and git repo; never C:\\ProgramData\\ThomasWindow. The folder's create-only permissions are set by
scripts/cage/enable_window.ps1 and are not tested here.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.cage import self_change_checks as checks
from scripts.cage import window_record as wrec

from tests.green_support import git, make_blue

WINDOW = "0123456789abcdef"


def _record(tmp_path: Path, **kwargs: object) -> wrec.Record:
    (tmp_path / "record").mkdir(exist_ok=True)
    return wrec.Record(tmp_path / "record", **kwargs)  # type: ignore[arg-type]


def test_events_are_numbered_and_each_names_the_one_before(tmp_path: Path) -> None:
    record = _record(tmp_path, clock=lambda: 5.0)

    first = record.event("window_opened", window_id=WINDOW)
    second = record.event("landing_intent", window_id=WINDOW, sid="self-x", commit="c" * 40)

    assert (first["seq"], second["seq"]) == (1, 2) and second["prev"] == first["hash"]
    assert [event["name"] for event in record.events()] == ["window_opened", "landing_intent"]
    with pytest.raises(FileExistsError):
        open(tmp_path / "record" / "00000001-window_opened.json", "xb").close()


def test_an_event_that_was_changed_reads_as_torn_and_refuses_further_writes(tmp_path: Path) -> None:
    record = _record(tmp_path)
    record.event("window_opened", window_id=WINDOW)
    path = tmp_path / "record" / "00000001-window_opened.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["window_id"] = "forged"
    path.write_text(json.dumps(data), encoding="utf-8")

    before = path.read_bytes()
    with pytest.raises(OSError, match="record chain"):
        record.event("window_closed", window_id=WINDOW, reason="you closed it")
    assert record.events()[0]["torn"] is True
    assert path.read_bytes() == before and len(list(path.parent.glob("*.json"))) == 1


def test_only_window_events_are_written(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _record(tmp_path).event("anything_else")


def test_a_landing_the_promoter_stopped_inside_is_listed_until_it_is_settled(tmp_path: Path) -> None:
    record = _record(tmp_path)
    record.event("landing_intent", sid="self-a", commit="a" * 40)
    record.event("landing_intent", sid="self-b", commit="b" * 40)
    record.event("landed", sid="self-a", commit="a" * 40)

    assert [event["sid"] for event in record.unfinished()] == ["self-b"]
    record.event("recovered", sid="self-b", commit="b" * 40, on_dev=False)
    assert record.unfinished() == []


def test_no_record_folder_means_no_window_and_the_record_never_makes_one(tmp_path: Path) -> None:
    assert "missing" in wrec.Record(tmp_path / "nowhere").usable()
    with pytest.raises(OSError):
        wrec.Record(tmp_path / "nowhere").event("window_opened")
    assert not (tmp_path / "nowhere").exists()
    (tmp_path / "here").mkdir()
    assert wrec.Record(tmp_path / "here").usable() == ""


def _land(repo: Path, files: dict[str, str], body: str, sid: str) -> str:
    parent = git(repo, "rev-parse", "dev")
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    tree = git(repo, "write-tree")
    trailers = [("Thomas-Committed-By", "self-change-promoter"), ("Thomas-Submission-Id", sid)]
    commit = checks.make_commit(repo, tree, parent, body, trailers)
    git(repo, "update-ref", "refs/heads/dev", commit, parent)
    git(repo, "reset", "-q", "--hard", "dev")
    return commit


def test_the_summary_is_read_from_dev_and_says_what_was_undone(tmp_path: Path) -> None:
    repo = make_blue(tmp_path)
    git(repo, "checkout", "-q", "-b", "dev")
    landed = _land(
        repo,
        {"thomas/fix_me.py": "VALUE = 2\n", "thomas/new.py": "A = 1\nB = 2\n"},
        f"self-fix: x\n\nLanded inside the window you opened (window {WINDOW}, pairing code ABC-DEF).",
        "self-thomas-aaa",
    )
    _land(repo, {"README.md": "other\n"}, "self-fix: not in the window", "self-thomas-bbb")
    _land(repo, {"thomas/fix_me.py": "VALUE = 1\n"}, "undo: self-thomas-aaa", "undo-self-thomas-aaa")

    rows = wrec.window_summary(repo, "dev", WINDOW)

    assert len(rows) == 1 and rows[0]["sid"] == "self-thomas-aaa" and rows[0]["commit"] == landed
    assert sorted(rows[0]["files"]) == ["thomas/fix_me.py", "thomas/new.py"]
    assert (rows[0]["added"], rows[0]["deleted"]) == (3, 1) and rows[0]["undone"]
    assert wrec.landed_on(repo, "dev", landed)
