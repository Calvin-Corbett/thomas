"""The timeline reads the check clocks that ``thomas/server/precard/clocks.py`` writes (spec 2026-10-12 Step 0).

What the check wrote in its own file is summarized by stage name, and a line a Build team wrote wrongly is stepped over.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from scripts.praxis import timeline_load as load
from scripts.praxis import timeline_sources as sources

from thomas.server.precard import clocks

T0 = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc).timestamp()
CID = "fc_20261009T120000_aaaa1111"
EXEC = "thomas-tl1"


def test_the_clocks_summary_counts_the_span_the_check_wrote(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    with clocks.recording(catalog, CID):
        clocks.note("execution_id", EXEC)
        clocks.span(load.CHECK_STAGE, T0, T0 + 61.5)

    summary = load.clocks_summary(sources.load_clocks(catalog), since=0.0, until=time.time() + 60)

    assert summary["stages"][load.CHECK_STAGE]["max_s"] == 61.5 and summary["check"]["n"] == 1


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _record(start: float, seconds: object, **fields: object) -> dict:
    stage = {"start": _iso(start), "end": _iso(start + 1), "seconds": seconds}
    return {"started_at": _iso(start), "stages": {load.CHECK_STAGE: stage}, **fields}


def test_a_clocks_record_that_is_not_one_or_has_no_readable_time_is_skipped() -> None:
    odd = [None, "line", 5, ["a"], {"started_at": "no time", "stages": {load.CHECK_STAGE: {"seconds": 9.0}}}]
    odd += [{"started_at": _iso(T0), "stages": ["not", "a", "map"]}, {"started_at": _iso(T0), "stages": None}]

    summary = load.clocks_summary([*odd, _record(T0, 4.0)], since=0.0, until=T0 + 100)

    assert summary["records"] == 3, "a record with a readable start is in the window, stages or not"
    assert (summary["check"]["n"], summary["stages"][load.CHECK_STAGE]["n"]) == (1, 1)
    assert summary["check_states"] == {} and summary["check_causes"] == {}


def test_a_span_with_a_missing_or_wrong_time_is_not_a_measurement() -> None:
    bad = [None, "5", True, float("nan"), float("inf"), -3.0, [1], {"s": 1}]
    records = [_record(T0 + n, seconds) for n, seconds in enumerate(bad)]
    records.append({"started_at": _iso(T0), "stages": {load.CHECK_STAGE: {"seconds": 2.0}, "other": 7, "none": None}})
    records.append({"started_at": _iso(T0), "stages": {load.CHECK_STAGE: {"start": "soon", "seconds": 3.0}}})
    records.append(_record(T0 + 20, 6.0))

    summary = load.clocks_summary(records, since=T0 - 1, until=T0 + 100)

    assert summary["stages"][load.CHECK_STAGE]["n"] == 3, "the 2 s and 3 s spans and the 6 s one are the only numbers"
    assert set(summary["stages"]) == {load.CHECK_STAGE}, "a stage that is not a span is no stage"
    assert summary["check"]["n"] == 1, "a check with no readable start never joins the others"
    assert summary["check"]["p90_s"] == 6.0 and summary["check"]["max_checks_at_once"] == 1


def test_a_free_disk_note_that_is_not_a_number_is_ignored() -> None:
    wrong = {"free_disk_at_admission_bytes": "lots", "free_disk_after_run_bytes": True, "free_disk_x_bytes": None}
    wrong |= {"free_disk_nan_bytes": float("nan"), "free_disk_inf_bytes": float("-inf"), "free_disk_list_bytes": [3]}
    records = [_record(T0, 1.0, **wrong), _record(T0, 1.0, free_disk_at_admission_bytes=50 * 2**30)]

    assert load.clocks_summary(records[:1], since=0.0, until=T0 + 1)["free_disk_min_bytes"] is None
    assert load.clocks_summary(records, since=0.0, until=T0 + 1)["free_disk_min_bytes"] == 50 * 2**30


def test_a_check_whose_file_count_is_not_a_count_never_counts_as_under_load() -> None:
    together = [_record(T0 + n, 10.0, selected_files=10) for n in range(5)]
    together.append(_record(T0 + 5, 10.0, selected_files=True))
    together.append(_record(T0 + 6, 10.0, selected_files="ten"))

    summary = load.clocks_summary(together, since=0.0, until=T0 + 100)

    assert summary["check"]["n"] == 7, "a check with no file count is still a check, and it started with the others"
    assert summary["check"]["under_load_n"] == 5, "but its size is not known, so it is not one of the loaded checks"


def test_a_row_with_fields_of_the_wrong_type_is_stepped_over() -> None:
    window = {"start": T0, "end": T0 + 7200.0}
    unplaced = [None, "row", {"_launch_epoch": "yesterday", "_end_epoch": T0 + 60}, {"hand_ins": []}]
    hand_ins = [None, "h", {"submitted_at": "soon", "verdict_status": "landed", "verdict_ts": "now"}]
    crash = {"failure_class": "crash"}
    runs = [None, {}, {"start": "s", "duration_s": 5, **crash}, {"start": T0, "duration_s": "5", **crash}]
    runs += [{"start": T0, "duration_s": float("nan"), **crash}, {"start": float("inf"), "duration_s": 5, **crash}]
    open_rows = [
        {"_launch_epoch": T0, "_end_epoch": "later", "hand_ins": hand_ins, "runs": runs},
        {"_launch_epoch": T0, "hand_ins": "x", "runs": 5},
    ]

    nothing = load.window_shares(unplaced, **window)
    shares = load.window_shares([*unplaced, *open_rows], **window)

    assert (nothing["in_flight_max"], nothing["building_busy_share"]) == (0, 0.0), "no launch time, not in flight"
    assert (shares["in_flight_max"], shares["building_busy_share"]) == (2, 1.0), "no readable end: still open"
    assert shares["busy_runs_share"] == 0.0, "a run with no number for its start or length was not measured"
    [day] = load.per_day([*unplaced, *open_rows], tz=timezone.utc, **window)
    assert day["landed"] == 0 and day["failed_run_min"] == 0.0


def _slotted(record: dict, slot: object) -> dict:
    record["stages"]["in_slot"] = slot
    return record


def _in_slot(start: float, seconds: float) -> dict:
    return {"start": _iso(start), "end": _iso(start + seconds), "seconds": seconds}


def test_checks_waiting_for_their_turn_count_as_at_once_but_not_as_running() -> None:
    queue = [_slotted(_record(T0 + n, 100.0), _in_slot(T0 + 10 * n, 10.0)) for n in range(6)]

    check = load.clocks_summary(queue, since=0.0, until=T0 + 1000)["check"]

    assert (check["max_checks_at_once"], check["max_running_at_once"]) == (6, 1), "one place: one check at a time"
    queue[1] = _slotted(_record(T0 + 1, 100.0), _in_slot(T0 + 5, 10.0))  # its turn overlaps the first check's
    assert load.clocks_summary(queue, since=0.0, until=T0 + 1000)["check"]["max_running_at_once"] == 2


def test_a_turn_with_a_missing_or_wrong_time_is_not_a_measurement() -> None:
    wrong = [None, 5, {"seconds": 3.0}, {"start": "soon", "seconds": 3.0}, {"start": _iso(T0), "seconds": -1.0}]
    wrong.append({"start": _iso(T0), "seconds": float("nan")})
    records = [_slotted(_record(T0, 5.0), slot) for slot in wrong]

    check = load.clocks_summary(records, since=0.0, until=T0 + 100)["check"]

    assert check["max_running_at_once"] == 0 and check["max_checks_at_once"] == len(wrong)
