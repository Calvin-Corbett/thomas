"""Every minute of a Thomas self-change project is put in exactly one phase (spec 2026-10-12 Step 0).

Pure functions on in-memory records: the timeline's runs, card times, phases, totals and the check clocks.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from scripts.praxis import timeline_load as load
from scripts.praxis import timeline_phases as phases
from scripts.praxis import timeline_runs as runs
from scripts.praxis import timeline_totals as totals

T0 = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc).timestamp()


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _conversation(cid: str, execution: str, launch: float, turns: list[dict]) -> dict:
    return {
        "id": cid,
        "title": "t",
        "created_at": _iso(launch),
        "updated_at": _iso(launch),
        "turns": turns,
        "thomas_project": {"execution_id": execution, "repairs": []},
    }


def _finished(cid: str, execution: str, launch: float) -> dict:
    turns = [
        {"role": "user", "text": "Make it", "ts": _iso(launch + 1)},
        {"role": "agent", "ts": _iso(launch + 2), "ok": True, "outcome": "completed", "changed_files": ["a.py"]},
    ]
    return _conversation(cid, execution, launch, turns)


def _hand_in(execution: str, submitted: float) -> dict:
    sid = f"self-{execution}"
    return {sid: {"sid": sid, "where": "processed", "execution_id": execution, "submitted_at": submitted}}


def _verdict(execution: str, ts: float, *, code: str = "", pending: tuple[float, float] | None = None) -> dict:
    entry: dict = {"verdict": {"status": "landed", "ts": ts, "card": {"pairing_code": code} if code else {}}}
    if pending is not None:
        entry["pending_times"] = {"created": pending[0], "modified": pending[1], "size": 1.0}
    return {f"self-{execution}": entry}


def _rows(conversations: list[dict], hand_ins: dict, outbox: dict, looks: dict, tmp: Path, now: float) -> list[dict]:
    rows = [runs.build_project(c, hand_ins, outbox, looks, tmp, now, None, lambda _sha: None) for c in conversations]
    phases.infer_cards(rows, outbox, now)
    for row in rows:
        phases.attribute(row, now)
        row["totals"] = totals.totals(row)
    return rows


@pytest.mark.parametrize(
    ("text", "first", "expected"),
    [
        ("Autopilot: continuing: done check -- look again", False, ("done_check", "autopilot")),
        ("Autopilot: continuing: repair round 1", False, ("repair_round", "autopilot")),
        ("Autopilot: continuing: resuming after the usage limit", False, ("resume", "autopilot")),
        ("Autopilot: continuing: resuming after provider trouble", False, ("resume", "autopilot")),
        ("Autopilot: continuing: resuming after a restart", False, ("restart", "autopilot")),
        ("Autopilot: continuing with your steering update", False, ("steer", "autopilot")),
        ("Autopilot: continuing", False, ("continuation", "autopilot")),
        ("Make the button blue", True, ("first_build", "launch")),
        ("Carry on with the task above. Thomas's server restarted while it ran.", False, ("restart", "manual")),
        ("Finish this change and hand it in", False, ("manual_message", "manual")),
    ],
)
def test_run_kind_is_read_from_the_autopilot_prefix(text: str, first: bool, expected: tuple[str, str]) -> None:
    assert runs.classify(text, first) == expected


def test_a_run_without_an_agent_turn_ends_at_its_transcripts_last_write(tmp_path: Path) -> None:
    turns = [{"role": "user", "text": "Make it", "ts": _iso(T0)}]
    index = [(T0 + 1.0, T0 + 500.0, 10.0, "transcript-0123456789abcdef.txt")]

    [run] = runs.build_runs(turns, tmp_path, T0 + 10_000.0, index)

    assert run["end"] == T0 + 500.0 and run["duration_s"] == 500.0
    assert run["outcome"].startswith("cut without") and run["failure_class"] == "cut_without_a_turn"


@pytest.mark.parametrize(("quiet_s", "running"), [(901.0, False), (60.0, True)])
def test_a_quiet_last_run_is_not_still_running(tmp_path: Path, quiet_s: float, running: bool) -> None:
    now = T0 + 5_000.0
    turns = [{"role": "user", "text": "Make it", "ts": _iso(T0)}]

    [run] = runs.build_runs(turns, tmp_path, now, [(T0 + 0.5, now - quiet_s, 10.0, "transcript-x.txt")])

    assert (run["outcome"] == "running") is running
    assert (run["end"] is None) is running


def test_repair_causes_tell_server_rounds_from_send_backs() -> None:
    assert (
        runs.repair_cause({"detail": "A second model read your change against the request"}) == "second_look_not_safe"
    )
    assert runs.repair_cause({"detail": "The check before your card applied this change"}) == "precard_check_failed"
    assert runs.repair_cause({"why": "dev_moved", "detail": "x"}) == "dev_moved"
    by_hand = {"why": "sent_back", "detail": "Please also fix the label"}
    assert runs.repair_cause({**by_hand, "sid": "self-x"}) == "manual_send_back_after_hand_in"
    assert runs.repair_cause(by_hand) == "manual_send_back"


def test_a_project_is_landed_ended_or_open() -> None:
    def hand_in(status: str) -> list[dict]:
        return [{"submitted_at": 1.0, "verdict_status": status, "verdict_ts": 2.0}]

    assert runs.project_state({"thomas_project": {}}, hand_in("landed")) == "landed"
    assert runs.project_state({"thomas_project": {}}, hand_in("declined")) == "ended"
    repaired = {"thomas_project": {"repairs": [{"at": _iso(T0)}]}}
    assert runs.project_state(repaired, hand_in("refused")) == "open", "a repair round followed the refusal"
    assert runs.project_state({"thomas_project": {"retirement": {"outcome": "reported"}}}, []) == "ended"
    assert runs.project_state({"thomas_project": {}}, []) == "open"


def test_every_second_from_launch_to_landing_is_in_exactly_one_phase(tmp_path: Path) -> None:
    turns = [
        {"role": "user", "text": "Make the button blue", "ts": _iso(T0 + 30)},
        {"role": "agent", "ts": _iso(T0 + 600), "ok": True, "outcome": "completed", "changed_files": ["a.py"]},
        {"role": "user", "text": "Autopilot: continuing: done check", "ts": _iso(T0 + 605)},
        {"role": "agent", "ts": _iso(T0 + 700), "ok": True, "outcome": "completed", "changed_files": []},
    ]
    looks = {"thomas-a": [{"session": "s", "start": T0 + 800, "end": T0 + 840, "verdict_text": "SAFE"}]}
    outbox = _verdict("thomas-a", T0 + 1001, pending=(T0 + 870, T0 + 1000))
    conversation = _conversation("fc_20261009T120000_a", "thomas-a", T0, turns)

    [row] = _rows([conversation], _hand_in("thomas-a", T0 + 850), outbox, looks, tmp_path, T0 + 5000)

    spent = row["phases_s"]
    assert sum(spent.values()) == pytest.approx(1001, abs=0.5)
    assert spent == pytest.approx(
        {
            "launch_setup": 30,
            "run:first_build": 570,
            "autopilot_gap": 5,
            "run:done_check": 95,
            "precard_check": 100,
            "second_look": 40,
            "handover": 10,
            "promoter_precheck": 20,
            "owner_card": 130,
            "promoter_land": 1,
        },
        abs=0.5,
    )


def test_a_card_queued_behind_another_cards_answer_is_owner_wait(tmp_path: Path) -> None:
    conversations = [
        _finished("fc_20261009T120000_a", "thomas-a", T0 - 100),
        _finished("fc_20261009T120001_b", "thomas-b", T0 - 50),
    ]
    hand_ins = {**_hand_in("thomas-a", T0), **_hand_in("thomas-b", T0 + 100)}
    outbox = {**_verdict("thomas-a", T0 + 500), **_verdict("thomas-b", T0 + 900)}

    _a, b = _rows(conversations, hand_ins, outbox, {}, tmp_path, T0 + 5000)

    [queued] = b["hand_ins"]
    assert queued["pick"] == T0 + 500 and "queued" in queued["pick_basis"]
    assert b["phases_s"]["queue_behind_other_card"] == pytest.approx(400)
    assert b["totals"]["owner_wait_min"] >= 400 / 60


def test_changes_on_one_shared_card_are_one_promoter_outcome(tmp_path: Path) -> None:
    conversations = [
        _finished("fc_20261009T120000_a", "thomas-a", T0 - 100),
        _finished("fc_20261009T120001_b", "thomas-b", T0 - 50),
    ]
    hand_ins = {**_hand_in("thomas-a", T0 + 100), **_hand_in("thomas-b", T0 + 110)}
    outbox = {**_verdict("thomas-a", T0 + 600, code="1234"), **_verdict("thomas-b", T0 + 602, code="1234")}

    a, b = _rows(conversations, hand_ins, outbox, {}, tmp_path, T0 + 5000)

    [first], [second] = a["hand_ins"], b["hand_ins"]
    assert first["pick"] == second["pick"] == T0 + 110, "one card, picked once both had arrived"
    assert first["card_shown"] == second["card_shown"]
    assert "queued" not in second["pick_basis"], "a member's verdict is never the other member's previous finish"


def _record(start: float, seconds: float, *, files: int = 10) -> dict:
    stage = {"start": _iso(start), "end": _iso(start + seconds), "seconds": seconds}
    return {"started_at": _iso(start), "selected_files": files, "outcome": "handed_in", "check_state": "passed",
            "stages": {load.CHECK_STAGE: stage}}  # fmt: skip


def test_clock_stages_report_median_p90_and_max_for_any_stage_name() -> None:
    records = [_record(T0 + 10 * n, float(n)) for n in range(1, 11)]
    records[0]["stages"]["admission_wait"] = {"start": _iso(T0), "end": _iso(T0 + 2), "seconds": 2.0}

    summary = load.clocks_summary(records, since=T0, until=T0 + 1000)

    check = summary["stages"][load.CHECK_STAGE]
    assert (check["n"], check["p90_s"], check["max_s"]) == (10, 9.0, 10.0)
    assert summary["stages"]["admission_wait"]["n"] == 1, "a stage named after this tool was written still counts"
    assert summary["free_disk_min_bytes"] is None, "nothing recorded free disk"
    records[1]["free_disk_at_admission_bytes"] = 30 * 2**30
    records[2]["free_disk_after_run_bytes"] = 20 * 2**30
    assert load.clocks_summary(records, since=T0, until=T0 + 1000)["free_disk_min_bytes"] == 20 * 2**30


def test_p90_under_load_counts_only_checks_that_started_together() -> None:
    together = [_record(T0 + 10 * n, 100.0 + n) for n in range(6)]
    together[3]["selected_files"] = 200
    alone = _record(T0 + 3600, 50.0)

    summary = load.clocks_summary([*together, alone], since=T0, until=T0 + 7200)

    assert summary["check"]["under_load_n"] == 5, "the 200-file check is left out and the lone check never joins"
    assert summary["check"]["max_checks_at_once"] == 6
    assert summary["check"]["p90_under_load_s"] == 105.0


def test_build_stage_busy_share_counts_overlap_once() -> None:
    hour = 3600.0
    rows = [
        {"_launch_epoch": T0, "_end_epoch": T0 + 10 * hour, "hand_ins": [{"submitted_at": T0 + 10 * hour}], "runs": []},
        {"_launch_epoch": T0 + 5 * hour, "_end_epoch": T0 + 15 * hour,
         "hand_ins": [{"submitted_at": T0 + 15 * hour}], "runs": []},
    ]  # fmt: skip

    shares = load.window_shares(rows, start=T0, end=T0 + 24 * hour)

    assert shares["building_busy_share"] == pytest.approx(15 / 24, abs=1e-3)
    assert shares["in_flight_avg"] == pytest.approx(20 / 24, abs=1e-3)
    assert shares["in_flight_max"] == 2


def test_landings_per_day_use_the_verdict_time() -> None:
    midnight = datetime(2026, 10, 10, tzinfo=timezone.utc).timestamp()
    landed = [
        {"submitted_at": midnight - 600, "verdict_status": "landed", "verdict_ts": midnight - 60},
        {"submitted_at": midnight - 300, "verdict_status": "landed", "verdict_ts": midnight + 60},
    ]
    rows = [{"_launch_epoch": midnight - 7200, "_end_epoch": midnight + 60, "runs": [], "hand_ins": landed}]

    days = load.per_day(rows, tz=timezone.utc, start=midnight - 86400, end=midnight + 86400)

    assert [(day["day"], day["landed"]) for day in days] == [("2026-10-09", 1), ("2026-10-10", 1)]


def test_pass_lines_say_met_unmet_or_not_measured() -> None:
    clocks = {"check": {"p90_under_load_s": 230.0}, "free_disk_min_bytes": None}

    lines = load.pass_lines(clocks, {"building_busy_share": 0.5})

    assert lines["part1_check_p90_s"] == {"value": 230.0, "target": 240.0, "met": True}
    assert lines["part1_disk_floor"]["met"] is None
    assert lines["part3_build_busy_share"]["met"] is False
