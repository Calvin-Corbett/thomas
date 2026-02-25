from __future__ import annotations

import json
from pathlib import Path

import scripts.generate_prog_evidence_payloads as mod


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_contract_evidence_ids_filters_target_families(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    _write_json(
        contract,
        {
            "catalog_checks": [
                {
                    "id": "prog.001",
                    "benchmark_family": "task_quality",
                    "implementation_mode": "evidence_required_v1",
                    "evidence_id": "prog.001",
                },
                {
                    "id": "prog.002",
                    "benchmark_family": "human_quality",
                    "implementation_mode": "evidence_required_v1",
                    "evidence_id": "prog.002",
                },
                {
                    "id": "core.quick",
                    "benchmark_family": "coverage_and_correctness",
                    "implementation_mode": "contract_rule_v1",
                },
            ]
        },
    )

    rows = mod.load_contract_evidence_ids(contract, target_families=("task_quality", "human_quality"))
    assert rows["task_quality"] == ["prog.001"]
    assert rows["human_quality"] == ["prog.002"]


def test_compute_track_family_scores_returns_target_family_keys() -> None:
    rows = [
        {
            "task_id": "x",
            "track": "thomas_os",
            "success": True,
            "quality_score": 90.0,
            "evidence": "transcripts/x.md",
            "run": {
                "elapsed_seconds": 4.0,
                "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
            },
        },
        {
            "task_id": "y",
            "track": "thomas_os",
            "success": False,
            "quality_score": 55.0,
            "run": {"elapsed_seconds": 12.0, "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}},
        },
    ]

    scores = mod.compute_track_family_scores(rows)
    assert set(scores.keys()) == set(mod.TARGET_FAMILIES)
    assert all(0.0 <= float(value) <= 100.0 for value in scores.values())


def test_build_prog_evidence_rows_emits_rows_per_contract_id() -> None:
    rows = mod.build_prog_evidence_rows(
        evidence_ids_by_family={"task_quality": ["prog.001", "prog.002"]},
        family_scores={"task_quality": 88.0},
        track="thomas_os",
        raw_source="demo/agentic-runs/run-x/benchmark_results.raw.json",
        generated_at_utc="2026-02-25T00:00:00Z",
        row_count=5,
    )
    assert len(rows) == 2
    assert rows[0]["track"] == "thomas_os"
    assert rows[0]["pass"] is True
    assert rows[0]["score"] == 88.0
    assert rows[0]["evidence_id"] == "prog.001"


def test_build_prog_evidence_rows_applies_manual_override_per_evidence_id() -> None:
    rows = mod.build_prog_evidence_rows(
        evidence_ids_by_family={"human_quality": ["prog.004"]},
        family_scores={"human_quality": 0.0},
        track="thomas_os",
        raw_source="demo/agentic-runs/run-x/benchmark_results.raw.json",
        generated_at_utc="2026-02-25T00:00:00Z",
        row_count=1,
        manual_overrides={
            "prog.004": {
                "score": 72.0,
                "pass": True,
                "notes": "manual review",
                "evidence": "manual://prog.004",
                "updated_at_utc": "2026-02-25T00:01:00Z",
            }
        },
    )
    assert len(rows) == 1
    assert rows[0]["evidence_id"] == "prog.004"
    assert rows[0]["pass"] is True
    assert rows[0]["score"] == 72.0
    assert rows[0]["notes"] == "manual review"
    assert rows[0]["evidence"] == "manual://prog.004"
    assert rows[0]["updated_at_utc"] == "2026-02-25T00:01:00Z"


def test_load_manual_overrides_reads_track_mappings(tmp_path: Path) -> None:
    overrides = tmp_path / "overrides.json"
    _write_json(
        overrides,
        {
            "tracks": {
                "thomas_os": {
                    "prog.004": {"score": 71.5, "pass": True, "notes": "ok"},
                }
            }
        },
    )
    loaded = mod.load_manual_overrides(overrides)
    assert loaded["thomas_os"]["prog.004"]["score"] == 71.5
    assert loaded["thomas_os"]["prog.004"]["pass"] is True
    assert loaded["thomas_os"]["prog.004"]["notes"] == "ok"


def test_run_writes_evidence_payloads_per_run_directory(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    runs = tmp_path / "runs"
    run_a = runs / "agentic-1"
    _write_json(
        contract,
        {
            "catalog_checks": [
                {
                    "id": "prog.001",
                    "benchmark_family": "task_quality",
                    "implementation_mode": "evidence_required_v1",
                    "evidence_id": "prog.001",
                },
                {
                    "id": "prog.040",
                    "benchmark_family": "safety_and_policy",
                    "implementation_mode": "evidence_required_v1",
                    "evidence_id": "prog.040",
                },
            ]
        },
    )
    _write_json(
        run_a / "benchmark_results.raw.json",
        [
            {
                "task_id": "artifact_probe",
                "track": "thomas_os",
                "success": True,
                "quality_score": 92.0,
                "run": {
                    "elapsed_seconds": 6.0,
                    "usage": {"prompt_tokens": 40, "completion_tokens": 20, "total_tokens": 60},
                },
                "evidence": "transcripts/thomas_os/probe.md",
            }
        ],
    )

    rc = mod.run(
        [
            "--contract",
            str(contract),
            "--runs-dir",
            str(runs),
            "--track",
            "thomas_os",
            "--output-filename",
            "benchmark_results.prog_evidence.json",
            "--json",
        ]
    )
    assert rc == 0

    output = run_a / "benchmark_results.prog_evidence.json"
    assert output.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert len(payload) == 2
    ids = {str(row.get("evidence_id")) for row in payload}
    assert ids == {"prog.001", "prog.040"}


def test_run_applies_manual_overrides_when_file_provided(tmp_path: Path) -> None:
    contract = tmp_path / "contract.json"
    runs = tmp_path / "runs"
    run_a = runs / "agentic-1"
    overrides = tmp_path / "overrides.json"
    _write_json(
        contract,
        {
            "catalog_checks": [
                {
                    "id": "prog.004",
                    "benchmark_family": "human_quality",
                    "implementation_mode": "evidence_required_v1",
                    "evidence_id": "prog.004",
                }
            ]
        },
    )
    _write_json(
        run_a / "benchmark_results.raw.json",
        [
            {
                "task_id": "artifact_probe",
                "track": "thomas_os",
                "success": False,
                "run": {"elapsed_seconds": 2.0, "usage": {"prompt_tokens": 10, "completion_tokens": 0, "total_tokens": 10}},
            }
        ],
    )
    _write_json(
        overrides,
        {
            "tracks": {
                "thomas_os": {
                    "prog.004": {
                        "score": 72.0,
                        "pass": True,
                        "notes": "manual human review",
                        "evidence": "manual://prog.004",
                    }
                }
            }
        },
    )

    rc = mod.run(
        [
            "--contract",
            str(contract),
            "--runs-dir",
            str(runs),
            "--track",
            "thomas_os",
            "--manual-overrides",
            str(overrides),
            "--output-filename",
            "benchmark_results.prog_evidence.json",
            "--json",
        ]
    )
    assert rc == 0

    output = run_a / "benchmark_results.prog_evidence.json"
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert len(payload) == 1
    row = dict(payload[0])
    assert row["evidence_id"] == "prog.004"
    assert row["pass"] is True
    assert row["score"] == 72.0
    assert row["notes"] == "manual human review"
    assert row["evidence"] == "manual://prog.004"
