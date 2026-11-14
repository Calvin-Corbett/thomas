"""The timeline's run and project readers skip a record a Build team wrote wrongly and never raise on it.

Conversations, submissions and verdicts are files a Build team can write, so a turn, a transcript row or a hand-in
field of the wrong type is data to step over (spec 2026-10-12 Step 0), the way ``timeline_cage`` steps over a line.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from scripts.praxis import timeline_runs as runs

T0 = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc).timestamp()
ISO = datetime.fromtimestamp(T0, timezone.utc).isoformat()


def _project(conversation: dict, hand_ins: dict, outbox: dict, looks: dict, tmp: Path) -> dict:
    return runs.build_project(conversation, hand_ins, outbox, looks, tmp, T0, None, lambda _sha: None)


def test_a_turn_that_is_not_one_or_has_no_readable_time_is_skipped(tmp_path: Path) -> None:
    agent = {"role": "agent", "ts": ISO, "ok": "yes", "outcome": "completed", "changed_files": 7}
    turns = [None, "text", 5, {"role": "user", "ts": "no time"}, {"role": "agent", "ts": None, "ok": True}, agent]

    [run] = runs.build_runs(turns, tmp_path, T0 + 9_000.0)

    assert run["turn_index"] == 3 and run["start"] is None and run["duration_s"] is None
    assert run["end"] == T0, "the agent turn with no readable time did not end the run; the next did"
    assert run["ok"] is None and run["changed_files"] == 0, "a field of the wrong type is read as not recorded"
    assert runs.build_runs(5, tmp_path, T0) == [], "turns that are not a list are no runs"


def test_runs_with_no_start_and_no_turn_are_not_recorded_and_never_running(tmp_path: Path) -> None:
    [first, last] = runs.build_runs([{"role": "user", "text": "a"}, {"role": "user", "text": "b"}], tmp_path, T0)

    assert first["end"] is None and last["end"] is None
    assert {first["outcome"], last["outcome"]} == {"no agent turn recorded"} and last["end_source"] == "not recorded"


def test_a_project_with_fields_of_the_wrong_type_still_reads(tmp_path: Path) -> None:
    project = {"execution_id": "thomas-a", "repairs": [None, "x", {"at": ISO}], "settled_at": "soon"}
    hand_ins = {
        "self-thomas-a": {"sid": "self-thomas-a", "where": "inbox", "execution_id": "thomas-a", "submitted_at": "?"},
        "self-orphan": {"sid": "self-orphan", "where": "inbox", "execution_id": ""},
        "junk": "not a hand-in",
    }
    verdict = {"status": ["landed"], "ts": "later", "card": "x", "commit_sha": ["a"]}

    row = _project(
        {"id": "fc_20261009T120000_a", "turns": 5, "thomas_project": project},
        hand_ins,
        {"self-thomas-a": {"verdict": verdict, "pending_times": 4}},
        {"thomas-a": [None, {"session": "s"}]},
        tmp_path,
    )

    [hand_in] = row["hand_ins"]
    assert row["runs"] == [] and row["settled_at"] is None and len(row["repairs"]) == 1
    assert hand_in["submitted_at"] is None and hand_in["verdict_status"] is None and hand_in["card_code"] == ""
    assert row["state"] == "open" and row["second_looks"] == [{"session": "s"}]
    assert _project({"id": "x", "thomas_project": ["no"]}, hand_ins, {}, {}, tmp_path)["hand_ins"] == []
    assert runs.project_state({"thomas_project": 3}, [None, {"verdict_status": ["declined"]}]) == "open"
