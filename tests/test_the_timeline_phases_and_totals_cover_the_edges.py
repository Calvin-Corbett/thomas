"""Card times, phases and totals at their edges: a resume, a card with no pending time, ranks, names, bad records.

The first three cases live in ``test_the_timeline_puts_every_minute_in_one_phase.py``. Conversations, submissions and
verdicts are files a Build team can write, so a time or field that cannot be read is data to step over (spec
2026-10-12 Step 0): the phases and totals still come out, and nothing here raises.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from scripts.praxis import timeline_phases as phases
from scripts.praxis import timeline_runs as runs
from scripts.praxis import timeline_totals as totals

T0 = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc).timestamp()
FINISHED = [
    {"role": "user", "text": "Make it", "ts": T0 + 1},
    {"role": "agent", "ts": T0 + 2, "ok": True, "outcome": "completed", "changed_files": ["a.py"]},
]


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _conversation(execution: str, turns: list[dict], repairs: list[dict] | None = None) -> dict:
    stamped = [{**turn, "ts": _iso(turn["ts"])} for turn in turns]
    project = {"execution_id": execution, "repairs": repairs or []}
    return {"id": "fc_20261009T120000_a", "title": "Secret title", "created_at": _iso(T0), "turns": stamped,
            "thomas_project": project}  # fmt: skip


def _built(conversation: dict, submitted: object, outbox: dict, looks: dict, tmp: Path, now: float) -> dict:
    execution = conversation["thomas_project"]["execution_id"]
    sid = f"self-{execution}"
    hand_ins = {sid: {"sid": sid, "where": "processed", "execution_id": execution, "submitted_at": submitted}}
    return runs.build_project(conversation, hand_ins, outbox, looks, tmp, now, None, lambda _sha: None)


def _pipeline(conversation: dict, submitted: object, outbox: dict, looks: dict, tmp: Path, now: float) -> dict:
    row = _built(conversation, submitted, outbox, looks, tmp, now)
    phases.infer_cards([row], outbox, now)
    phases.attribute(row, now)
    row["totals"] = totals.totals(row)
    return row


def _landed(ts: object, *, pending: dict | None = None, **verdict: object) -> dict:
    entry: dict = {"verdict": {"status": "landed", "ts": ts, **verdict}}
    if pending is not None:
        entry["pending_times"] = pending
    return {"self-thomas-a": entry}


def test_a_resume_after_provider_trouble_is_a_resume_phase(tmp_path: Path) -> None:
    turns = [
        {"role": "user", "text": "Make it", "ts": T0 + 10},
        {"role": "agent", "ts": T0 + 100, "ok": True, "outcome": "completed", "changed_files": []},
        {"role": "user", "text": "Autopilot: continuing: resuming after provider trouble", "ts": T0 + 160},
        {"role": "agent", "ts": T0 + 400, "ok": True, "outcome": "completed", "changed_files": []},
    ]

    row = _pipeline(_conversation("thomas-a", turns), None, {}, {}, tmp_path, T0 + 500)

    assert [run["kind"] for run in row["runs"]] == ["first_build", "resume"]
    assert row["phases_s"] == pytest.approx(
        {"launch_setup": 10, "run:first_build": 90, "autopilot_gap": 60, "run:resume": 240, "open_now": 100}
    )


@pytest.mark.parametrize(
    ("pending", "exact", "basis"),
    [
        (None, [], "inferred: pick time + 14 s"),
        ({"created": T0 + 70, "modified": T0 + 300, "size": 1.0}, [20.0], "exact: pending.json creation time"),
    ],
)
def test_a_card_is_put_up_at_its_pending_time_or_after_the_median_precheck(
    tmp_path: Path, pending: dict | None, exact: list[float], basis: str
) -> None:
    outbox = _landed(T0 + 301, pending=pending)
    row = _built(_conversation("thomas-a", FINISHED), T0 + 50, outbox, {}, tmp_path, T0 + 5000)

    assert phases.infer_cards([row], outbox, T0 + 5000) == exact

    [hand_in] = row["hand_ins"]
    assert hand_in["card_basis"] == basis
    assert hand_in["card_shown"] == T0 + 50 + (exact[0] if exact else phases.PROMOTER_PRECHECK_FALLBACK_S)


def test_percentiles_are_nearest_rank_and_ignore_what_is_not_there() -> None:
    values = [4.0, None, 1.0, 3.0, 2.0]

    assert [totals.percentile(values, q) for q in (0.0, 0.5, 0.51, 0.9, 1.0)] == [1.0, 2.0, 3.0, 4.0, 4.0]
    assert totals.percentile([None], 0.5) is None and totals.percentile([], 0.5) is None
    assert totals.med([1.0, None, 2.0]) == 1.5 and totals.med([None]) is None
    assert totals.minutes(90.0) == 1.5 and totals.minutes(None) is None


def test_the_aggregate_names_no_project(tmp_path: Path) -> None:
    repairs = [{"at": _iso(T0 + 20), "why": "dev_moved", "detail": "x"}]
    row = _pipeline(_conversation("thomas-a", FINISHED, repairs), T0 + 50, _landed(T0 + 90), {}, tmp_path, T0 + 500)

    found = totals.aggregate([row, {**row, "pipeline": "ratchet"}])

    assert found["projects"] == 1 and found["projects_landed"] == 1 and found["repair_causes"] == {"dev_moved": 1}
    text = json.dumps(found)
    assert not any(name in text for name in ("thomas-a", "Secret title", "fc_20261009", "self-"))
    assert totals.aggregate([]) == {"projects": 0, "projects_landed": 0}


@pytest.mark.parametrize(
    ("submitted", "outbox", "looks"),
    [
        pytest.param(None, _landed(T0 + 100), {}, id="a hand-in with no submit time"),
        pytest.param(0, _landed(T0 + 100), {}, id="a hand-in submitted at the epoch"),
        pytest.param(T0 + 50, _landed("later"), {}, id="landed, verdict time not a time"),
        pytest.param(T0 + 50, {"self-thomas-a": {"verdict": {"status": "landed"}}}, {}, id="landed, no verdict time"),
        pytest.param(T0 + 50, _landed(T0 + 100, card="1234"), {}, id="a card that is a string"),
        pytest.param(T0 + 50, {"self-thomas-a": {"verdict": ["landed"]}}, {}, id="a verdict that is a list"),
        pytest.param(T0 + 50, {"self-thomas-a": "x"}, {}, id="an outbox entry that is a string"),
        pytest.param(T0 + 50, _landed(T0 + 100, pending={"created": "a", "modified": "b"}), {}, id="pending text"),
        pytest.param(T0 + 50, _landed(T0 + 100), {"thomas-a": [{"session": "s"}]}, id="a second look with no times"),
        pytest.param(
            T0 + 50,
            _landed(T0 + 100),
            {"thomas-a": [{"session": "s", "start": T0 + 10}]},
            id="a second look with no end",
        ),
    ],
)
def test_a_record_with_a_time_that_cannot_be_read_is_stepped_over(
    tmp_path: Path, submitted: object, outbox: dict, looks: dict
) -> None:
    row = _pipeline(_conversation("thomas-a", FINISHED), submitted, outbox, looks, tmp_path, T0 + 5000)

    assert isinstance(row["phases_s"], dict) and sum(row["phases_s"].values()) >= 0
    assert totals.aggregate([row])["projects"] == 1


def test_a_verdict_time_written_as_text_is_read_as_a_time(tmp_path: Path) -> None:
    row = _pipeline(_conversation("thomas-a", FINISHED), T0 + 50, _landed(_iso(T0 + 100)), {}, tmp_path, T0 + 5000)

    assert row["totals"]["launch_to_landed_min"] == pytest.approx(100 / 60, abs=0.01)
    assert sum(row["phases_s"].values()) == pytest.approx(100, abs=0.5)
