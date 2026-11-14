"""Build-side Praxis manager wiring over actual candidate files."""

from __future__ import annotations

import hashlib
from pathlib import Path

from thomas.core.praxis.formation_state import N1_RULES, Cycle
from thomas.server.praxis.coordinator import PraxisBuildCoordinator


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_combined_real_files_receive_durable_verdicts(tmp_path: Path) -> None:
    paths = {owner: tmp_path / f"{owner}.txt" for owner in ("builder_a", "builder_b")}
    paths["builder_a"].write_text("left", encoding="utf-8")
    paths["builder_b"].write_text("right", encoding="utf-8")
    calls = []

    def evaluate(key: tuple, _cycle: Cycle):
        calls.append(key)
        actual = " ".join(paths[owner].read_text(encoding="utf-8") for owner in paths)
        outcome = "accepted" if actual == "left right" else "repair"
        return {owner: outcome for owner in paths}

    coordinator = PraxisBuildCoordinator(
        run_id="build-1",
        owners=list(paths),
        cycles=[Cycle(1, "requirements-1", "acceptance-1")],
        log_path=tmp_path / "obligations.jsonl",
        evaluate=evaluate,
        manager_id="manager-1",
        rules=N1_RULES,
    )
    delivered: dict[str, list] = {owner: [] for owner in paths}
    coordinator.child_state("builder_a", "starting")
    coordinator.child_state("builder_a", "running")
    coordinator.child_state("builder_a", "completed")
    assert not coordinator.report()["obligations"]["obligations"]
    assert coordinator.report()["formation"]["accepted_cycles"] == []
    for owner, path in paths.items():
        coordinator.child_queued(owner)
        coordinator.child_admitted(owner)
        coordinator.submit_candidate(
            owner=owner,
            generation=1,
            candidate_hash=_hash(path),
            role="builder",
            owned_path=str(path),
            deliver=delivered[owner].append,
        )
    assert len(calls) == 1
    assert all(rows[0]["outcome"] == "accepted" for rows in delivered.values())
    report = coordinator.report()
    assert report["formation"]["finished"] == "all_cycles_accepted"
    assert not report["obligations"]["open"]
    assert len(report["obligations"]["obligations"]) == 2


def test_repair_feedback_and_manager_epoch_fence(tmp_path: Path) -> None:
    path = tmp_path / "builder.py"
    path.write_text("bad", encoding="utf-8")

    def evaluate(_key: tuple, _cycle: Cycle):
        return {
            "builder": {
                "outcome": "accepted" if path.read_text(encoding="utf-8") == "good" else "repair",
                "evidence": {"isolation_failed_checks": ["checks.py::valid [failed] expected good"]},
            }
        }

    coordinator = PraxisBuildCoordinator(
        run_id="build-2",
        owners=["builder"],
        cycles=[Cycle(1, "requirements-1", "acceptance-1")],
        log_path=tmp_path / "obligations.jsonl",
        evaluate=evaluate,
        manager_id="manager-1",
        rules=N1_RULES,
    )
    delivered = []
    old_handle = coordinator.proxy.manager.handle
    obligation = coordinator.submit_candidate(
        owner="builder",
        generation=1,
        candidate_hash=_hash(path),
        role="builder",
        owned_path=str(path),
        deliver=delivered.append,
    )
    assert delivered[0]["outcome"] == "repair"
    assert "expected good" in delivered[0]["feedback"]
    assert delivered[0]["repair_offer"]["event"] == "escalation_granted"
    replacement = coordinator.replace_manager("manager-2")
    assert replacement["new_epoch"] == 2
    assert not old_handle.issue_verdict(obligation, {"outcome": "accepted"})
    assert coordinator.report()["obligations"]["refusals"]
    path.write_text("good", encoding="utf-8")
    coordinator.submit_candidate(
        owner="builder",
        generation=2,
        candidate_hash=_hash(path),
        role="builder",
        owned_path=str(path),
        deliver=delivered.append,
    )
    assert delivered[-1]["outcome"] == "accepted"
    assert coordinator.report()["formation"]["finished"] == "all_cycles_accepted"
