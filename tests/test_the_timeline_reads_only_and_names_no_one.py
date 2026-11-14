"""The Praxis timeline reads what Thomas and the promoter write, never asks a server, and names no one.

Spec 2026-10-12 Step 0: the operator's scratch timeline lands as scripts/praxis_timeline.py. It reads every Thomas
project from disk (the project listing shows only the newest 20 handed in and took up to 90 s), writes only into its
own folder, and its baseline holds aggregates only, because the repo is published.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from scripts.praxis import timeline_cage
from scripts.praxis import timeline_sources as sources

from thomas.tools import cage_shell

# tests/conftest.py redirects cage_shell.DEFAULT_CAGE_ROOT for every test, so the real one is read at import.
_REAL_CAGE_ROOT = cage_shell.DEFAULT_CAGE_ROOT

T0 = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc).timestamp()
CID = "fc_20261009T120000_aaaa1111"
EXEC = "thomas-tl1"
TITLE = "Make the timeline fixture title secret"


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _conversation(cid: str, execution: str, *, updated: float, turns: list | None = None, **project: object) -> dict:
    return {
        "id": cid,
        "title": TITLE,
        "created_at": _iso(T0),
        "updated_at": _iso(updated),
        "turns": turns if turns is not None else [],
        "thomas_project": {"execution_id": execution, **project},
    }


def _write(folder: Path, conversation: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{conversation['id']}.json"
    path.write_text(json.dumps(conversation), encoding="utf-8")
    return path


def test_every_project_is_read_from_the_catalog_and_the_greens(tmp_path: Path) -> None:
    catalog, greens = tmp_path / "catalog", tmp_path / "green"
    _write(catalog / sources.CONVERSATIONS, _conversation(CID, EXEC, updated=T0 + 10))
    newer = _conversation(CID, EXEC, updated=T0 + 20, repairs=[{"round": 1}])
    _write(greens / "work" / EXEC / sources.CONVERSATIONS, newer)
    building = "fc_20261009T130000_bbbb2222"
    _write(greens / "work" / "thomas-tl2" / sources.CONVERSATIONS, _conversation(building, "thomas-tl2", updated=T0))
    before = "fc_20261001T130000_cccc3333"
    _write(catalog / sources.CONVERSATIONS, _conversation(before, "thomas-old", updated=T0))
    for n in range(25):  # more handed-in projects than the listing's newest 20
        cid = f"fc_20261010T0000{n:02d}_d{n:07d}"
        _write(catalog / sources.CONVERSATIONS, _conversation(cid, f"thomas-n{n}", updated=T0 + 100 + n))
    plain = {"id": "fc_20261009T150000_eeee5555", "title": "ordinary Build work", "turns": []}
    _write(catalog / sources.CONVERSATIONS, plain)

    found = sources.load_conversations(sources.Paths(catalog, tmp_path / "cage", greens), since=T0 - 1)

    assert CID in found and building in found and before not in found
    assert found[CID]["thomas_project"].get("repairs") == [{"round": 1}], "the copy written last says where it stands"
    assert len(found) == 27, "every Thomas project since the start, and nothing that is not one"


def test_the_timeline_reads_the_clocks_the_check_writes(tmp_path: Path) -> None:
    from thomas.server.precard import clocks

    catalog = tmp_path / "catalog"
    with clocks.recording(catalog, CID):
        clocks.note("execution_id", EXEC)
        clocks.note("selected_files", 12)
        clocks.span("check_for_hand_in", T0, T0 + 61.5)
    path = clocks.clocks_path(catalog)
    path.write_text(path.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")

    [record] = sources.load_clocks(catalog)

    assert record["execution_id"] == EXEC and record["selected_files"] == 12
    assert record["stages"]["check_for_hand_in"]["seconds"] == 61.5


def test_promoter_restarts_carry_the_time_and_the_event_and_never_the_line(tmp_path: Path) -> None:
    log = tmp_path / "cage" / "promoter" / "promoter.log"
    log.parent.mkdir(parents=True)
    log.write_text(
        "2026-10-09 13:00:00,250 pid=7 promoter started for C:\\Users\\someone\\Thomas\n"
        "2026-10-09 13:05:00,000 pid=7 self-x: landed\n"
        "2026-10-09 14:00:00,000 pid=7 promoter process exiting\n",
        encoding="utf-8",
    )

    events = timeline_cage.promoter_restarts(tmp_path / "cage", since=0.0)

    assert [event["event"] for event in events] == ["started", "exiting"]
    assert all(set(event) == {"at", "event"} for event in events)


def test_the_paths_match_what_thomas_writes(tmp_path: Path) -> None:
    from thomas.forge.anvil import forge_code_store
    from thomas.server.precard import clocks
    from thomas.server.routes import evolve_agent_runtime

    assert sources.DEFAULT_CAGE_ROOT == _REAL_CAGE_ROOT
    assert sources.CAGE_ROOT_ENV == cage_shell.CAGE_ROOT_ENV
    assert sources.CLOCKS_FILE == clocks.CLOCKS_FILE
    assert tmp_path / sources.CONVERSATIONS == forge_code_store.conversations_dir(tmp_path)
    assert sources.transcript_name("run-x") == evolve_agent_runtime._transcript_path(tmp_path, "run-x").name


RUN = "run-x"
PROMOTER_LOG = (
    "2026-10-09 13:00:00,250 pid=7 promoter started for C:\\Users\\someone\\Thomas\n"
    "2026-10-09 13:05:00,000 pid=7 self-x: landed\n"
    "2026-10-09 14:00:00,000 pid=7 promoter process exiting\n"
    "2026-10-09 15:00:00,500 pid=8 promoter stopped by an error it did not catch\n"
    "2026-13-45 99:99:99,000 pid=8 promoter started for nowhere\n"
    "0001-01-01 00:00:00,000 pid=8 promoter started for nowhere\n"
)


def _put(path: Path, content: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


def _said(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _row(offset: float, message: object, kind: str = "assistant") -> str:
    return json.dumps({"timestamp": _iso(T0 + offset), "type": kind, "message": message})


def _tree(root: Path) -> sources.Paths:
    """One fixture tree of everything the readers read: conversations, clocks, a transcript, the cage folder."""
    catalog, greens, cage = root / "catalog", root / "green", root / "cage"
    _write(catalog / sources.CONVERSATIONS, _conversation(CID, EXEC, updated=T0 + 10))
    _write(greens / "work" / EXEC / sources.CONVERSATIONS, _conversation(CID, EXEC, updated=T0 + 20))
    _put(catalog / sources.AGENT_DIR / sources.CLOCKS_FILE, json.dumps({"execution_id": EXEC}) + "\n")
    _put(catalog / sources.AGENT_DIR / sources.transcript_name(RUN), "transcript")
    for where, sid, body in (
        ("inbox", "self-a", {"execution_id": EXEC, "submitted_at": _iso(T0 + 5)}),
        ("processed", "self-b", {"execution_id": "thomas-tl2"}),
        ("withdrawn", "self-c", {"execution_id": "thomas-tl3"}),
        ("inbox", "self-d", ["a", "submission.json", "that", "is", "not", "an", "object"]),
    ):
        _put(cage / where / sid / "submission.json", body)
    _put(cage / "outbox" / "self-a.pending.json", {"id": "self-a", "execution_id": EXEC})
    _put(cage / "outbox" / "self-b.verdict.json", {"submission_id": "self-b", "status": "landed", "ts": T0})
    _put(cage / "outbox" / "self-e.pending.json", ["not", "an", "object"])
    looks = cage / "claude" / "projects" / f"C--r-green-work-{EXEC}"
    _put(looks / "s1.jsonl", "\n".join([_row(30, "look", "user"), _row(40, _said("SAFE")), _row(50, "a string")]))
    _put(looks / "s2.jsonl", _row(100, _said("NOT SAFE")))
    _put(cage / "promoter" / "promoter.log", PROMOTER_LOG)
    return sources.Paths(catalog, cage, greens)


def _git(repo: Path, *args: str) -> str:
    config = ["-c", "user.name=t", "-c", "user.email=t@t.invalid", "-c", "commit.gpgsign=false"]
    done = subprocess.run(["git", "-C", str(repo), *config, *args], capture_output=True, text=True, check=True)
    return done.stdout.strip()


def _repo(root: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, str, str]:
    """A repo whose ``main`` holds a commit (the second) that branch ``side`` (the first) does not."""
    for key in [key for key in os.environ if key.startswith("GIT_")]:
        monkeypatch.delenv(key)
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    tree = _git(root, "write-tree")
    first = _git(root, "commit-tree", tree, "-m", "first")
    second = _git(root, "commit-tree", tree, "-p", first, "-m", "second")
    _git(root, "update-ref", "refs/heads/main", second)
    _git(root, "update-ref", "refs/heads/side", first)
    _git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    return root, first, second


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    return {p.relative_to(root).as_posix(): (p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*")}


def test_no_reader_writes_makes_a_folder_or_touches_a_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _tree(tmp_path)
    repo, _first, second = _repo(tmp_path / "repo", monkeypatch)
    before = _snapshot(tmp_path)

    found = [
        sources.load_conversations(paths, since=T0 - 1),
        sources.load_clocks(paths.catalog),
        sources.transcript_index(paths.agent_dir, since=T0),
        sources.transcript_times(paths.agent_dir, RUN),
        sources.git_commit(repo, second, "main"),
        timeline_cage.load_hand_ins(paths.cage),
        timeline_cage.load_outbox(paths.cage),
        timeline_cage.load_second_looks(paths.cage),
        timeline_cage.promoter_restarts(paths.cage, since=0.0),
    ]

    assert all(found), "every reader found something, so an unchanged tree is not an empty one"
    assert _snapshot(tmp_path) == before, "same paths, same sizes, same write times, no new folder"


def test_the_cage_readers_find_what_the_promoter_and_the_second_look_wrote(tmp_path: Path) -> None:
    cage = _tree(tmp_path).cage

    hand_ins = timeline_cage.load_hand_ins(cage)
    assert {sid: (h["where"], h["execution_id"]) for sid, h in hand_ins.items()} == {
        "self-a": ("inbox", EXEC),
        "self-b": ("processed", "thomas-tl2"),
        "self-c": ("withdrawn", "thomas-tl3"),
        "self-d": ("inbox", ""),  # a submission.json that is not an object reads as empty, never raises
    }
    assert hand_ins["self-a"]["submitted_at"] == _iso(T0 + 5)

    outbox = timeline_cage.load_outbox(cage)
    assert set(outbox) == {"self-a", "self-b", "self-e"}
    assert outbox["self-a"]["pending"]["execution_id"] == EXEC and "verdict" not in outbox["self-a"]
    assert outbox["self-b"]["verdict"]["status"] == "landed" and outbox["self-b"]["verdict_times"]["size"] > 0
    assert outbox["self-e"]["pending"] == {}, "an outbox record that is not an object reads as empty"

    looks = timeline_cage.load_second_looks(cage)
    assert list(looks) == [EXEC]
    assert [(s["session"], s["start"], s["end"], s["verdict_text"]) for s in looks[EXEC]] == [
        ("s1", T0 + 30, T0 + 50, "SAFE"),  # the row whose message is a string is skipped, its time still counts
        ("s2", T0 + 100, T0 + 100, "NOT SAFE"),
    ]


def test_promoter_restarts_carry_the_log_time_and_skip_a_line_with_no_real_date(tmp_path: Path) -> None:
    cage = _tree(tmp_path).cage

    def local(hour: int, second: float) -> float:
        return time.mktime((2026, 10, 9, hour, 0, 0, 0, 0, -1)) + second

    assert timeline_cage.promoter_restarts(cage, since=0.0) == [
        {"at": pytest.approx(local(13, 0.25), abs=1e-3), "event": "started"},
        {"at": pytest.approx(local(14, 0.0), abs=1e-3), "event": "exiting"},
        {"at": pytest.approx(local(15, 0.5), abs=1e-3), "event": "crashed"},
    ]
    later = timeline_cage.promoter_restarts(cage, since=local(13, 1800.0))
    assert [event["event"] for event in later] == ["exiting", "crashed"]


def test_a_name_or_a_time_that_is_not_real_is_skipped_and_never_aborts_the_read(tmp_path: Path) -> None:
    assert sources.cid_epoch("fc_20261399T250000_x") is None and sources.cid_epoch("fc_00000101T000000_x") is None
    assert sources.iso_to_epoch("0001-01-01T00:00:00") is None
    folder = tmp_path / "catalog" / sources.CONVERSATIONS
    stray = "fc_20261399T250000_zzzz9999"
    odd = _conversation("fc_20261009T130000_bbbb2222", "thomas-tl2", updated=T0) | {"updated_at": "0001-01-01T00:00:00"}
    for conversation in (_conversation(CID, EXEC, updated=T0), _conversation(stray, "thomas-bad", updated=T0), odd):
        _write(folder, conversation)

    found = sources.load_conversations(sources.Paths(tmp_path / "catalog", tmp_path / "cage", None), since=T0 - 1)

    assert set(found) == {CID, odd["id"]}, "the stray name has no real date and is left out; the others are read"


def test_git_commit_takes_only_a_sha_and_says_exactly_where_it_stands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _first, second = _repo(tmp_path / "repo", monkeypatch)
    victim = tmp_path / "victim.txt"

    for not_a_sha in (f"--output={victim}", f"{second[:8]} --stat", "main", "abc", "", f"{second}\n"):
        assert sources.git_commit(repo, not_a_sha) is None, not_a_sha  # git show would honour --output=<file>
    held = sources.git_commit(repo, second[:10], "main")
    assert held is not None and (held["sha"], held["on_dev"], held["found"]) == (second, True, True)
    assert held["committed_epoch"] > T0
    assert sources.git_commit(repo, second, "side")["on_dev"] is False, "git answered no"
    assert sources.git_commit(repo, second, "no-such-branch")["on_dev"] is None, "git failed: neither yes nor no"
    assert sources.git_commit(repo, second, f"--output={victim}")["on_dev"] is None
    assert sources.git_commit(repo, "ab" * 20, "main") == {"sha": "ab" * 20, "found": False}
    assert not victim.exists(), "no input made the reader write a file"
