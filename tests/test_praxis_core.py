"""Mechanical checks for the original Praxis manager records and formation."""

from __future__ import annotations

import json

import pytest

from thomas.core.praxis.formation import NOwnerCoordinator
from thomas.core.praxis.formation_state import ACCEPTED, REPAIR, STAGE2_RULES, Cycle, FormationState
from thomas.core.praxis.manager_proxy import CoordinatorProxy, ReplacementController
from thomas.core.praxis.obligations import CorruptRecords, ObligationLog, rebuild
from thomas.core.praxis.plan import plan_problems


def _candidate(owner: str, *, cycle: int = 1, generation: int = 1) -> dict:
    return {
        "owner": owner,
        "role": "builder",
        "generation": generation,
        "candidate_hash": f"{owner}-{cycle}-{generation}",
        "requirements_version": f"requirements-{cycle}",
        "acceptance_version": f"acceptance-{cycle}",
    }


def test_manager_replacement_fences_stale_verdict_and_delivers_once(tmp_path):
    log = ObligationLog(tmp_path / "run" / "obligations.jsonl")
    managers = []

    class Manager:
        def __init__(self, state, handle):
            self.state, self.handle = state, handle
            managers.append(self)

        def on_submission(self, _obligation_id, _candidate):
            pass

        def current_revision(self):
            return {}

    def factory(state, handle):
        return Manager(state, handle)

    proxy = CoordinatorProxy(coordinator_id="run-1", log=log, manager_id="first", factory=factory)
    received = []
    obligation_id = proxy.submit(_candidate("builder-a"), received.append)
    first = managers[-1]
    assert obligation_id in rebuild(log.path)["open"]

    report = ReplacementController(proxy).replace(manager_id="replacement", factory=factory)
    assert report["new_epoch"] == 2
    assert obligation_id in managers[-1].state["open"]
    assert not first.handle.issue_verdict(obligation_id, {"outcome": ACCEPTED})
    assert received == []
    assert managers[-1].handle.issue_verdict(obligation_id, {"outcome": ACCEPTED})
    assert received == [{"outcome": ACCEPTED}]
    state = rebuild(log.path)
    assert not state["open"] and state["refusals"][0]["refused_epoch"] == 1


def test_obligation_chain_rejects_changed_history(tmp_path):
    log = ObligationLog(tmp_path / "obligations.jsonl")
    epoch = log.open_epoch("manager")
    log.open_obligation(epoch=epoch, obligation_id="a", owed="verdict", **_candidate("a"))
    lines = log.path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["manager_id"] = "other"
    lines[0] = json.dumps(tampered)
    log.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(CorruptRecords):
        rebuild(log.path)


def test_n_owner_two_cycle_formation_rebuilds_after_repair(tmp_path):
    owners = [f"agent-{number}" for number in range(20)]
    cycles = [Cycle(index, f"requirements-{index}", f"acceptance-{index}") for index in (1, 2)]
    log = ObligationLog(tmp_path / "obligations.jsonl")
    received: dict[str, list[dict]] = {owner: [] for owner in owners}
    calls = 0

    def evaluate(key, cycle):
        nonlocal calls
        calls += 1
        return {owner: REPAIR if calls == 1 and owner == owners[0] else ACCEPTED for owner, _, _ in key}

    def factory(state, handle):
        return NOwnerCoordinator.from_records(
            state, handle, owners=owners, cycles=cycles, rules=STAGE2_RULES, evaluate=evaluate
        )

    proxy = CoordinatorProxy(coordinator_id="run-20", log=log, manager_id="lead", factory=factory)
    for owner in owners:
        proxy.submit(_candidate(owner), received[owner].append)
    assert len(proxy.manager.step()) == len(owners)
    assert received[owners[0]][0]["outcome"] == REPAIR
    assert proxy.manager.state.round_of(owners[0]) == 2
    proxy.submit(_candidate(owners[0], generation=2), received[owners[0]].append)
    assert proxy.manager.step()[0]["outcome"] == ACCEPTED
    assert proxy.manager.state.cycle.cycle_id == 2
    for owner in owners:
        proxy.submit(_candidate(owner, cycle=2), received[owner].append)
    assert len(proxy.manager.step()) == len(owners)
    assert proxy.manager.state.finished == "all_cycles_accepted"
    assert len(rebuild(log.path)["open"]) == 0


def test_plan_allows_100_justified_writers_without_arbitrary_ceiling():
    instructions = "Build a bootable kernel with shell and tests."
    units = [
        {
            "id": "contract",
            "kind": "interface",
            "owned_paths": [],
            "depends_on": [],
            "reason": "Define the kernel boundary",
            "brief": "Specify subsystem interfaces",
            "acceptance": [{"text": "Kernel boots", "cites": "bootable kernel"}],
        }
    ]
    units.extend(
        {
            "id": f"unit-{index}",
            "kind": "write",
            "owned_paths": [f"subsystems/part_{index}.c"],
            "depends_on": ["contract"],
            "reason": "Independent implementation",
            "brief": f"Implement subsystem {index}",
            "acceptance": [{"text": "Kernel boots", "cites": "bootable kernel"}],
        }
        for index in range(100)
    )
    plan = {"why_parallel": "disjoint_writes", "units": units}
    assert plan_problems(plan, instructions=instructions) == ()
    units[-1]["owned_paths"] = ["subsystems/part_0.c"]
    assert "overlapping_owners" in plan_problems(plan, instructions=instructions)
    units[-1]["owned_paths"] = ["subsystems/part_99.c"]
    units[-1]["acceptance"] = []
    assert "missing_acceptance" in plan_problems(plan, instructions=instructions)
