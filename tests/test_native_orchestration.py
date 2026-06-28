"""Tests for native Thomas orchestration recipes and planning."""

from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner

from thomas.cli.commands.evolve import evolve
from thomas.forge.anvil.native_orchestration import (
    DEFAULT_RECIPE_ID,
    OrchestrationRecipe,
    OrchestrationRun,
    OrchestrationState,
    WorkerRecord,
    collect_repo_signals,
    get_recipe,
    load_state,
    plan_orchestration_run,
    save_state,
    status_payload,
    utc_now_iso,
)


def _scaffold_repo(root: Path) -> None:
    (root / "pyproject.toml").write_text("[project]\nname = 'test-thomas'\n", encoding="utf-8")
    package = root / "thomas"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")


def _worker(worker_id: str, lane_key: str, dedupe_key: str, status: str = "running") -> WorkerRecord:
    now = utc_now_iso()
    return WorkerRecord(
        worker_id=worker_id,
        recipe_id=DEFAULT_RECIPE_ID,
        run_id="existing-run",
        lane_key=lane_key,
        status=status,
        dedupe_key=dedupe_key,
        title=lane_key,
        goal_prompt=f"work on {lane_key}",
        claim_scope=["thomas"],
        runner_hint="evolve.dispatch",
        model_hint="codex:gpt",
        created_at=now,
        updated_at=now,
    )


def test_builtin_recipe_round_trips_and_state_persists(tmp_path: Path) -> None:
    recipe = get_recipe(DEFAULT_RECIPE_ID)
    restored = OrchestrationRecipe.from_dict(recipe.to_dict())

    assert restored.id == DEFAULT_RECIPE_ID
    assert restored.max_active_workers == 3
    assert [lane.key for lane in restored.lanes] == ["repo-council", "upgrade-worker", "integration-review"]
    assert all(lane.dedupe_key.startswith("native-orchestration:senior-council:") for lane in restored.lanes)

    run = OrchestrationRun(
        run_id="orch-test",
        recipe_id=DEFAULT_RECIPE_ID,
        status="running",
        workers=[_worker("worker-a", "repo-council", restored.lanes[0].dedupe_key)],
        blocked_lanes=[],
        merge_ready_lanes=[],
        recommended_actions=["reuse worker-a"],
        created_at=utc_now_iso(),
        updated_at=utc_now_iso(),
    )
    save_state(tmp_path, OrchestrationState(runs=[run]))
    reloaded = load_state(tmp_path)

    assert reloaded.runs[0].run_id == "orch-test"
    assert reloaded.runs[0].workers[0].worker_id == "worker-a"


def test_plan_dedupes_existing_worker_and_blocks_over_max_active(tmp_path: Path) -> None:
    recipe = get_recipe(DEFAULT_RECIPE_ID)
    state = OrchestrationState(
        runs=[
            OrchestrationRun(
                run_id="existing-run",
                recipe_id=DEFAULT_RECIPE_ID,
                status="running",
                workers=[
                    _worker("repo-council-live", "repo-council", recipe.lanes[0].dedupe_key),
                    _worker("other-a", "other-a", "native-orchestration:other-a"),
                    _worker("other-b", "other-b", "native-orchestration:other-b"),
                ],
                blocked_lanes=[],
                merge_ready_lanes=[],
                recommended_actions=[],
                created_at=utc_now_iso(),
                updated_at=utc_now_iso(),
            )
        ]
    )

    plan = plan_orchestration_run(
        tmp_path,
        state=state,
        signals={"dirty_paths": [], "broad_dirty_conflicts": [], "workboard_active": [], "merge_ready_lanes": []},
    )

    assert plan.workers[0].status == "deduped"
    assert plan.workers[0].worker_id == "repo-council-live"
    assert {lane["lane_key"] for lane in plan.blocked_lanes} == {"upgrade-worker", "integration-review"}
    assert all("max active workers" in lane["reason"] for lane in plan.blocked_lanes)


def test_dry_run_plan_fails_closed_on_dirty_conflicts_but_keeps_council_scan(tmp_path: Path) -> None:
    plan = plan_orchestration_run(
        tmp_path,
        signals={
            "dirty_paths": ["README.md"],
            "broad_dirty_conflicts": ["README.md"],
            "workboard_active": [],
            "stale_active_folder_claims": [],
            "merge_ready_lanes": [{"session_id": "ready-1", "status": "ready", "promotable": True}],
        },
    )

    assert plan.dry_run is True
    assert plan.merge_ready_lanes[0]["session_id"] == "ready-1"
    assert any(worker.lane_key == "repo-council" and worker.status == "planned" for worker in plan.workers)
    assert {lane["lane_key"] for lane in plan.blocked_lanes} == {"upgrade-worker", "integration-review"}
    assert any("dirty" in action for action in plan.recommended_actions)
    assert any("merge-ready" in action for action in plan.recommended_actions)


def test_collect_repo_signals_surfaces_active_folder_roster_and_stale_leases(tmp_path: Path) -> None:
    active_root = tmp_path / "runtime" / "coordination"
    active_root.mkdir(parents=True)
    (active_root / "active_folders.json").write_text(
        json.dumps(
            {
                "claims": [
                    {
                        "agent_id": "fresh-worker",
                        "claim_id": "claim-fresh",
                        "paths": ["thomas/fresh.py"],
                        "note": "still active",
                        "pid": os.getpid(),
                        "started_at": "2026-06-26T16:00:00+00:00",
                        "last_heartbeat_at": "2026-06-26T16:05:00+00:00",
                        "expires_at": "2030-01-01T00:00:00+00:00",
                    },
                    {
                        "agent_id": "stale-worker",
                        "claim_id": "claim-stale",
                        "paths": ["thomas/stale.py"],
                        "note": "expired",
                        "pid": 999999999,
                        "started_at": "2026-06-26T15:00:00+00:00",
                        "last_heartbeat_at": "2026-06-26T15:05:00+00:00",
                        "expires_at": "2020-01-01T00:00:00+00:00",
                    },
                ]
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    signals = collect_repo_signals(tmp_path, get_recipe(DEFAULT_RECIPE_ID))
    payload = status_payload(tmp_path)

    assert {claim["agent_id"] for claim in signals["active_folder_claims"]} == {"fresh-worker", "stale-worker"}
    assert [claim["agent_id"] for claim in signals["stale_active_folder_claims"]] == ["stale-worker"]
    assert [claim["agent_id"] for claim in signals["dead_owner_active_folder_claims"]] == ["stale-worker"]
    assert payload["active_folder_claim_count"] == 2
    assert payload["stale_active_folder_claim_count"] == 1
    assert payload["dead_owner_active_folder_claim_count"] == 1
    assert payload["cleanup_needed_active_folder_claim_count"] == 1


def test_plan_recommends_clearing_stale_or_dead_owner_active_folder_leases(tmp_path: Path) -> None:
    plan = plan_orchestration_run(
        tmp_path,
        signals={
            "dirty_paths": [],
            "broad_dirty_conflicts": [],
            "workboard_active": [],
            "stale_active_folder_claims": [{"agent_id": "stale-worker", "stale": True}],
            "dead_owner_active_folder_claims": [{"agent_id": "dead-worker", "dead_owner": True}],
            "merge_ready_lanes": [],
        },
    )

    assert any("stale active-folder leases" in action for action in plan.recommended_actions)
    assert any("dead-owner active-folder leases" in action for action in plan.recommended_actions)


def test_evolve_orchestration_plan_cli_returns_json(tmp_path: Path) -> None:
    _scaffold_repo(tmp_path)

    result = CliRunner().invoke(evolve, ["orchestration", "plan", "--repo-root", str(tmp_path), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["recipe"]["id"] == DEFAULT_RECIPE_ID
    assert payload["run"]["dry_run"] is True
    assert payload["run"]["workers"]
