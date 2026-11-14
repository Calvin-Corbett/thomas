"""The Praxis timeline command writes only into its own folder, and the baseline it can write names no one.

Spec 2026-10-12 Step 0. The baseline goes into the repo, which is published, so it holds aggregates only: no project
title, conversation id, green name, request words or path. ``timeline.md`` is the operator's own report, in a folder git
ignores, and does name each project, so the "names no one" checks here are on the baseline and not on that report.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import praxis_timeline
from scripts.praxis import timeline_report
from scripts.praxis import timeline_sources as sources

T0 = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc).timestamp()
CID = "fc_20261009T120000_aaaa1111"
EXEC = "thomas-tl1"
TITLE = "Make the timeline fixture title secret"
OPEN_CID = "fc_20261009T140000_open0001"
NEW_FILES = (
    "scripts/praxis_timeline.py",
    "scripts/praxis/timeline_sources.py",
    "scripts/praxis/timeline_cage.py",
    "scripts/praxis/timeline_runs.py",
    "scripts/praxis/timeline_state.py",
    "scripts/praxis/timeline_phases.py",
    "scripts/praxis/timeline_totals.py",
    "scripts/praxis/timeline_load.py",
    "scripts/praxis/timeline_report.py",
    "scripts/praxis/check_load.py",
    "scripts/praxis/check_load_record.py",
    "scripts/praxis/check_load_machine.py",
    "scripts/praxis/check_load_job.py",
)


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


@pytest.fixture
def tree(tmp_path: Path) -> SimpleNamespace:
    """A landed project in the catalog, an open one only in a green, and the cage files the promoter wrote."""
    catalog, cage, greens, out = (tmp_path / name for name in ("catalog", "cage", "green", "out"))
    turns = [
        {"role": "user", "text": "Make the button blue", "ts": _iso(T0 + 30)},
        {"role": "agent", "ts": _iso(T0 + 600), "ok": True, "outcome": "completed", "changed_files": ["a.py"],
         "run_id": "run-1"},
    ]  # fmt: skip
    _write(catalog / sources.CONVERSATIONS, _conversation(CID, EXEC, updated=T0 + 1001, turns=turns, repairs=[]))
    open_turns = [
        {"role": "user", "text": "Make it green", "ts": _iso(T0 + 7200)},
        {"role": "agent", "ts": _iso(T0 + 7300), "ok": True, "outcome": "completed", "changed_files": ["b.py"]},
    ]
    building = _conversation(OPEN_CID, "thomas-tl2", updated=T0 + 7300, turns=open_turns)
    _write(greens / "work" / "thomas-tl2" / sources.CONVERSATIONS, {**building, "created_at": _iso(T0 + 7200)})
    sid = f"self-{EXEC}"
    (cage / "processed" / sid).mkdir(parents=True)
    submission = {"execution_id": EXEC, "submitted_at": T0 + 850}
    (cage / "processed" / sid / "submission.json").write_text(json.dumps(submission), encoding="utf-8")
    (cage / "outbox").mkdir()
    verdict = {"status": "landed", "ts": T0 + 1001, "commit_sha": "abc123"}
    (cage / "outbox" / f"{sid}.verdict.json").write_text(json.dumps(verdict), encoding="utf-8")
    (cage / "promoter").mkdir()
    (cage / "promoter" / "promoter.log").write_text(
        "2026-10-09 13:00:00,000 pid=1 promoter started for C:\\Users\\someone\\Thomas\n", encoding="utf-8"
    )
    looks = cage / "claude" / "projects" / f"C--g-green-work-{EXEC}"
    looks.mkdir(parents=True)
    said = {
        "type": "assistant",
        "timestamp": _iso(T0 + 840),
        "message": {"content": [{"type": "text", "text": "SAFE"}]},
    }
    (looks / "s1.jsonl").write_text(
        json.dumps({"type": "user", "timestamp": _iso(T0 + 800)}) + "\n" + json.dumps(said) + "\n", encoding="utf-8"
    )
    agent = catalog / sources.AGENT_DIR
    (agent / sources.transcript_name("run-1")).write_text("x", encoding="utf-8")
    stage = {"start": _iso(T0 + 700), "end": _iso(T0 + 790), "seconds": 90.0}
    record = {"conversation_id": CID, "started_at": _iso(T0 + 700), "execution_id": EXEC, "selected_files": 10,
              "outcome": "handed_in", "check_state": "passed", "stages": {"check_for_hand_in": stage}}  # fmt: skip
    (agent / sources.CLOCKS_FILE).write_text(json.dumps(record) + "\n", encoding="utf-8")
    return SimpleNamespace(tmp=tmp_path, catalog=catalog, cage=cage, greens=greens, out=out,
                           paths=sources.Paths(catalog, cage, greens))  # fmt: skip


def _argv(tree: SimpleNamespace) -> list[str]:
    return [
        "--since", "2026-10-09T00:00", "--until", "2026-10-10T00:00",
        "--catalog-root", str(tree.catalog), "--cage-root", str(tree.cage), "--green-root", str(tree.greens),
        "--no-git", "--out-dir", str(tree.out),
    ]  # fmt: skip


def _snapshot(*roots: Path) -> dict[str, tuple[bool, int, int]]:
    seen = {}
    for root in roots:
        for path in sorted(root.rglob("*")):
            status = path.stat()
            seen[str(path)] = (path.is_dir(), status.st_size if path.is_file() else 0, status.st_mtime_ns)
    return seen


def _baseline(tree: SimpleNamespace, *more: str) -> dict:
    target = tree.out / "baseline.json"
    assert praxis_timeline.main([*_argv(tree), "--baseline-out", str(target), *more], tz=timezone.utc) == 0
    return json.loads(target.read_text(encoding="utf-8"))


def test_it_writes_only_into_its_out_dir(tree: SimpleNamespace) -> None:
    before = _snapshot(tree.catalog, tree.cage, tree.greens)

    assert praxis_timeline.main(_argv(tree), tz=timezone.utc) == 0

    assert _snapshot(tree.catalog, tree.cage, tree.greens) == before
    assert sorted(path.name for path in tree.out.iterdir()) == ["timeline.json", "timeline.md"]


def test_the_baseline_names_no_project_path_or_title(tree: SimpleNamespace) -> None:
    data = _baseline(tree)

    assert set(data) == {"schema", "extracted_at", "since", "until", "aggregate", "cohorts", "clocks", "window",
                         "per_day", "pass_lines"}  # fmt: skip
    assert data["aggregate"]["projects"] == 2 and data["aggregate"]["projects_landed"] == 1
    text = (tree.out / "baseline.json").read_text(encoding="utf-8")
    secrets = (str(tree.tmp), json.dumps(str(tree.tmp))[1:-1], TITLE, "fc_", "self-thomas-", "text_head", "someone")
    for secret in (*secrets, CID, OPEN_CID, EXEC, "thomas-tl", "Make the button blue", "Make it green", "abc123"):
        assert secret not in text, secret


def test_the_operators_report_names_each_project_and_the_baseline_does_not(tree: SimpleNamespace) -> None:
    data = _baseline(tree)

    report = (tree.out / "timeline.md").read_text(encoding="utf-8")
    assert TITLE in report and EXEC in report, "timeline.md is for the operator and sits in a folder git ignores"
    for private in (CID, OPEN_CID, "fc_", str(tree.tmp), "someone"):
        assert private not in report, private
    assert TITLE not in json.dumps(data) and EXEC not in json.dumps(data)


def test_a_project_in_a_green_is_found_without_the_server(tree: SimpleNamespace) -> None:
    since = datetime(2026, 10, 9, tzinfo=timezone.utc).timestamp()

    # The green's conversation was written at T0+7300: two minutes before, so it is being built and not quiet for an hour.
    payload = praxis_timeline.collect(tree.paths, since=since, now=T0 + 7420, tz=timezone.utc)

    rows = {row["conversation_id"]: row for row in payload["projects"]}
    assert rows[OPEN_CID]["state"] == "open" and "open_now" in rows[OPEN_CID]["phases_s"]
    assert rows[CID]["state"] == "landed" and "second_look" in rows[CID]["phases_s"]
    assert payload["clocks"]["check"]["n"] == 1


def test_a_project_launched_at_or_after_until_is_not_counted(tree: SimpleNamespace) -> None:
    at_until, later = "fc_20261010T000000_edge0001", "fc_20261011T090000_late0002"
    for cid in (at_until, later):
        _write(tree.catalog / sources.CONVERSATIONS, _conversation(cid, f"thomas-{cid[-8:]}", updated=T0 + 90000))

    data = _baseline(tree)

    assert data["aggregate"]["projects"] == 2, "the window is [since, until): only the two launched before it ends"
    payload = json.loads((tree.out / "timeline.json").read_text(encoding="utf-8"))
    assert sorted(row["conversation_id"] for row in payload["projects"]) == [CID, OPEN_CID]


def test_a_cohort_is_counted_by_when_its_projects_launched(tree: SimpleNamespace) -> None:
    data = _baseline(tree, "--recent-since", "2026-10-09T13:00")

    assert set(data["cohorts"]) == {"launched_since_recent", "launched_before_recent"}
    assert data["cohorts"]["launched_since_recent"]["projects"] == 1
    assert data["cohorts"]["launched_before_recent"]["projects"] == 1
    assert _baseline(tree)["cohorts"] == {}, "no --recent-since, no cohorts"


def test_a_window_with_no_project_measured_no_busy_share_and_still_renders(tmp_path: Path) -> None:
    paths = sources.Paths(tmp_path / "catalog", tmp_path / "cage", None)
    since = datetime(2026, 10, 9, tzinfo=timezone.utc).timestamp()

    empty = praxis_timeline.collect(paths, since=since, now=since + 86400, tz=timezone.utc)

    assert empty["projects"] == [] and empty["aggregate"]["projects"] == 0
    line = empty["pass_lines"]["part3_build_busy_share"]
    assert line["value"] is None and line["met"] is None, "nothing was building, so the share was not measured"
    assert "no projects" in timeline_report.markdown(empty)


def test_a_project_in_the_window_measures_the_busy_share(tree: SimpleNamespace) -> None:
    since = datetime(2026, 10, 9, tzinfo=timezone.utc).timestamp()

    payload = praxis_timeline.collect(tree.paths, since=since, now=since + 86400, tz=timezone.utc)

    line = payload["pass_lines"]["part3_build_busy_share"]
    assert line["value"] == payload["window"]["building_busy_share"] and isinstance(line["met"], bool)


def test_a_time_that_is_not_a_time_or_an_empty_window_is_refused_before_anything_is_written(
    tree: SimpleNamespace, capsys: pytest.CaptureFixture[str]
) -> None:
    for bad in (["--since", "last tuesday"], ["--since", "2026-10-11T00:00"], ["--recent-since", "0000-00-00"]):
        assert praxis_timeline.main([*_argv(tree), *bad], tz=timezone.utc) == 2, bad

    assert not tree.out.exists(), "nothing is written for a window that was not understood"
    assert "--since must be before --until" in capsys.readouterr().err


def test_a_project_file_of_the_wrong_shape_is_skipped_and_never_aborts_the_run(tree: SimpleNamespace) -> None:
    odd = "fc_20261009T150000_odd00001"
    broken = {"id": odd, "title": 7, "created_at": "not a time", "turns": "no turns", "updated_at": 5,
              "thomas_project": {"execution_id": "thomas-odd", "repairs": "none", "settled_at": []}}  # fmt: skip
    _write(tree.catalog / sources.CONVERSATIONS, broken)
    cut = tree.catalog / sources.CONVERSATIONS / "fc_20261009T160000_junk0001.json"
    cut.write_text('{"id": "fc_20261009T160000_junk0001", "thomas_project": {"execution', encoding="utf-8")

    data = _baseline(tree)

    assert data["aggregate"]["projects"] == 3
    assert not any(secret in json.dumps(data) for secret in (odd, "thomas-odd"))


def test_the_new_files_reach_no_network_and_name_no_one() -> None:
    from scripts.cage import card_catalogue

    root = Path(__file__).resolve().parents[1]
    protected = card_catalogue.load_enforcement_paths(root)
    for rel in NEW_FILES:
        text = (root / rel).read_text(encoding="utf-8")
        added = "".join(f"+{line}\n" for line in text.splitlines())
        diff = f"--- /dev/null\n+++ b/{rel}\n -0,0 +1,{len(text.splitlines())} \n{added}"
        assert card_catalogue.danger_class(rel, added_diff=diff, enforcement_paths=protected) is None, rel
        assert "C:\\Users" not in text, rel
