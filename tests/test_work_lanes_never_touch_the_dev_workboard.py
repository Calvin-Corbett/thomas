"""Separation, storage, and the property that a stored gate cannot rot.

The dev workboard under `plans/thomas/` records repo engineering. A user's Work
job lanes are their business, and putting job runs into that board would mix two
unrelated things. The separation is asserted here rather than intended.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thomas.work.lanes.model import Gate, Lane, Step
from thomas.work.lanes.onboarding_lane import onboarding_lane
from thomas.work.lanes.proving import GateCannotFail
from thomas.work.lanes.store import LaneStore, default_store_path


def test_the_default_store_lives_with_work_data_not_in_the_repo():
    text = str(default_store_path()).replace("\\", "/")
    assert "/plans/" not in text
    assert text.endswith("/freedom_transit/work_lanes.json")


def test_a_store_rooted_in_the_dev_workboard_is_refused():
    with pytest.raises(ValueError, match="plans/"):
        LaneStore(path="plans/thomas/work_lanes.json")


def test_saving_a_lane_writes_only_the_file_it_was_given(tmp_path):
    store = LaneStore(path=tmp_path / "nested" / "work_lanes.json")
    store.save_lane(onboarding_lane(), approved_by="calvin")
    written = sorted(p.name for p in (tmp_path / "nested").iterdir())
    assert written == ["work_lanes.json"]


def test_a_lane_survives_a_round_trip(tmp_path):
    store = LaneStore(path=tmp_path / "work_lanes.json")
    store.save_lane(onboarding_lane())
    loaded = store.load_lane("work-onboarding")
    assert loaded is not None
    assert [s.id for s in loaded.steps] == ["goal_discovery", "workflow_mapping", "workflow_configuration"]
    assert all(gate.proven for step in loaded.steps for gate in step.gates)


def test_a_second_save_keeps_the_first_for_rollback(tmp_path):
    store = LaneStore(path=tmp_path / "work_lanes.json")
    store.save_lane(onboarding_lane())
    trimmed = onboarding_lane()
    trimmed.steps[1].gates = trimmed.steps[1].gates[:1]
    saved = store.save_lane(trimmed)
    assert saved.version == 2
    assert len(store.history("work-onboarding")) == 1

    restored = store.rollback("work-onboarding")
    assert restored is not None
    assert len(restored.steps[1].gates) == 2, "the fuller previous version is back"


def test_a_stored_gate_edited_into_one_that_always_passes_is_refused_on_load(tmp_path):
    """Proof is re-earned on load, so a gate cannot quietly rot into a green light."""
    path = tmp_path / "work_lanes.json"
    store = LaneStore(path=path)
    store.save_lane(onboarding_lane())

    data = json.loads(path.read_text(encoding="utf-8"))
    gates = data["lanes"]["work-onboarding"]["steps"][0]["gates"]
    # Loosen the check until the counterexample it declares would sail through.
    gates[0]["params"]["min_chars"] = 0
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(GateCannotFail, match="passed its own counterexample"):
        store.load_lane("work-onboarding")


def test_a_corrupt_store_raises_rather_than_reading_as_no_gates(tmp_path):
    """An empty store means 'no gates', which would wave every run through."""
    path = tmp_path / "work_lanes.json"
    path.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        LaneStore(path=path).load_lane("work-onboarding")


def test_a_lane_whose_gate_declares_no_counterexample_cannot_be_saved(tmp_path):
    store = LaneStore(path=tmp_path / "work_lanes.json")
    lane = Lane(
        id="lazy",
        job_kind="lazy",
        version=1,
        steps=[
            Step(
                id="s",
                name="S",
                gates=[Gate(id="g", kind="mechanical", description="x", check="nonempty_text", params={"field": "f"})],
            )
        ],
    )
    with pytest.raises(GateCannotFail, match="declares no counterexample"):
        store.save_lane(lane)


def test_lane_data_follows_the_work_store_it_describes(tmp_path):
    """A default that resolves to $HOME turns every job-creating test into a
    write against the owner's live Work data. Measured 2026-09-08: a suite run
    created `~/.thomas/freedom_transit/work_lane_stats.json` with 21 checks
    logged inside one second. Lane data is derived from the work store's own
    root instead, which is `.thomas/` (gitignored) and is a temp dir in tests.
    """
    from thomas.work.lanes.store import lane_data_dir

    derived = lane_data_dir(tmp_path)
    assert derived == (tmp_path / ".thomas" / "work").resolve()
    # Not `Path.home() not in derived`: on Windows tmp_path itself lives under
    # the user profile. The live Work directory is what must never be touched.
    assert Path.home() / ".thomas" / "freedom_transit" not in derived.parents
    assert "/plans/" not in str(derived).replace("\\", "/")


def test_registering_work_routes_writes_no_lane_data_into_the_home_directory(tmp_path):
    import asyncio

    from aiohttp import web

    from thomas.server.routes.work import register_work_routes
    from thomas.work import WorkStore

    home = Path.home() / ".thomas" / "freedom_transit"
    before = {p.name for p in home.iterdir()} if home.exists() else set()

    async def drive() -> None:
        app = web.Application()
        register_work_routes(
            app, require_api_access=lambda request: None, store=WorkStore(tmp_path / "work"), mission_canceller=None
        )
        from aiohttp.test_utils import TestClient, TestServer

        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            await client.post("/api/work/apps", json={"id": "ops", "name": "Ops", "goal": "Operate"})
            await client.post("/api/work/apps/ops/jobs", json={"name": "A job"})
        finally:
            await client.close()

    asyncio.run(drive())
    after = {p.name for p in home.iterdir()} if home.exists() else set()
    assert after == before, f"creating a job wrote into live Work data: {sorted(after - before)}"
    assert (tmp_path / "work" / ".thomas" / "work").exists(), "lane data landed with its work store"
