"""The card's routes: Thomas asks, and a refused tap changes nothing.

A proposal that could apply itself would make the whole lane runtime decorative,
so the order matters here -- authorize, apply, and only then record the decision.
Recording first would leave an "approved" row in the ledger with nothing behind
it, which is the shape of every claim this system exists to stop.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.routes.work import _expected_errors, _ok
from thomas.server.routes.work_lane_proposals import register_lane_proposal_routes
from thomas.work.lanes.model import Gate, Lane, Step
from thomas.work.lanes.proposals import GateProposal, GateProposalStore
from thomas.work.lanes.store import LaneStore


def _gate(gate_id: str, field: str) -> Gate:
    return Gate(
        id=gate_id,
        kind="mechanical",
        description=f"{gate_id} holds",
        check="nonempty_text",
        params={"field": field, "min_chars": 5},
        counterexample={"fields": {field: ""}},
    )


def _fixture(tmp_path: Path):
    lanes = LaneStore(path=tmp_path / "work_lanes.json")
    lanes.save_lane(
        Lane(id="job", job_kind="job", version=1, steps=[Step(id="s", name="S", gates=[_gate("a", "goal"), _gate("b", "other")])])
    )
    proposals = GateProposalStore(path=tmp_path / "proposals.json")
    proposals.queue(
        [
            GateProposal(
                id="p1",
                job_kind="job",
                kind="retire",
                gate_id="b",
                rationale="Checked 24 times and never once stopped anything.",
                evidence={"checked_count": 24, "fired_count": 0, "waived_count": 0},
            )
        ]
    )
    return lanes, proposals


async def _client(tmp_path: Path, *, authorized: bool):
    lanes, proposals = _fixture(tmp_path)

    def authorize(*, purpose, reason):
        return (True, "authorized") if authorized else (False, "you did not approve this")

    app = web.Application()
    register_lane_proposal_routes(
        app,
        guard=lambda request: None,
        expected_errors=_expected_errors,
        ok=_ok,
        proposal_store=proposals,
        lane_store=lanes,
        authorize=authorize,
    )
    client = TestClient(TestServer(app))
    await client.start_server()
    return client, lanes, proposals


@pytest.mark.asyncio
async def test_the_card_shows_the_ask_with_its_evidence(tmp_path: Path):
    client, _, _ = await _client(tmp_path, authorized=True)
    try:
        body = await (await client.get("/api/work/lane-proposals")).json()
        row = body["proposals"][0]
        assert row["kind"] == "retire" and row["gate_id"] == "b"
        assert row["evidence"]["checked_count"] == 24, "the evidence travels with the ask"
        assert "never once stopped anything" in row["rationale"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_a_refused_tap_changes_nothing_at_all(tmp_path: Path):
    client, lanes, proposals = await _client(tmp_path, authorized=False)
    try:
        response = await client.post("/api/work/lane-proposals/p1/approve", json={})
        assert response.status == 403
        assert "did not approve" in (await response.json())["error"]
        assert [g.id for g in lanes.load_lane("job").steps[0].gates] == ["a", "b"], "the gate is still there"
        assert proposals.get("p1").status == "pending", "and it is still waiting, not filed as approved"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_an_approved_tap_changes_the_gate_and_versions_the_lane(tmp_path: Path):
    client, lanes, proposals = await _client(tmp_path, authorized=True)
    try:
        response = await client.post("/api/work/lane-proposals/p1/approve", json={"approved_by": "calvin"})
        assert response.status == 200
        assert (await response.json())["lane_version"] == 2
        assert [g.id for g in lanes.load_lane("job").steps[0].gates] == ["a"]
        assert proposals.get("p1").status == "approved"
        assert [g.id for g in lanes.rollback("job").steps[0].gates] == ["a", "b"], "still reversible"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_the_same_proposal_cannot_be_approved_twice(tmp_path: Path):
    client, _, _ = await _client(tmp_path, authorized=True)
    try:
        assert (await client.post("/api/work/lane-proposals/p1/approve", json={})).status == 200
        second = await client.post("/api/work/lane-proposals/p1/approve", json={})
        assert second.status == 409
        assert "already approved" in (await second.json())["error"]
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_rejecting_records_the_reason_and_clears_the_card(tmp_path: Path):
    client, lanes, proposals = await _client(tmp_path, authorized=True)
    try:
        response = await client.post("/api/work/lane-proposals/p1/reject", json={"reason": "I want that check"})
        assert response.status == 200
        assert proposals.pending("job") == []
        assert proposals.get("p1").decided_reason == "I want that check"
        assert [g.id for g in lanes.load_lane("job").steps[0].gates] == ["a", "b"], "rejecting touches no gate"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_an_unknown_proposal_is_a_404_not_a_silent_success(tmp_path: Path):
    client, _, _ = await _client(tmp_path, authorized=True)
    try:
        assert (await client.post("/api/work/lane-proposals/nope/approve", json={})).status == 404
        assert (await client.post("/api/work/lane-proposals/nope/reject", json={})).status == 404
    finally:
        await client.close()
