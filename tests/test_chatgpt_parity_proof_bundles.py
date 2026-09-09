from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
STRESS = ROOT / "tests" / "stress"
if str(STRESS) not in sys.path:
    sys.path.insert(0, str(STRESS))

from chatgpt_parity_harness import (
    EvidenceRow,
    score_families,
    validate_evidence_provenance,
)
from chatgpt_parity_probes import ProbeContext


def _load_loop() -> ModuleType:
    spec = importlib.util.spec_from_file_location("chatgpt_parity_bundle_loop", STRESS / "chatgpt_parity_loop.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _family(family_id: str, weight: float) -> dict:
    return {
        "id": family_id,
        "name": family_id.title(),
        "weight": weight,
        "critical": True,
        "behaviors": ["behaves"],
        "tiers": {str(tier): [{"kind": "manual", "severity": "critical"}] for tier in range(1, 5)},
    }


def _rubric() -> dict:
    return {
        "schema_version": "thomas-chatgpt-parity-v1",
        "target": "test",
        "as_of": "2026-07-12",
        "source_urls": ["https://example.test"],
        "scoring": {str(tier): f"tier {tier}" for tier in range(5)},
        "families": [_family("core", 0.25), _family("work", 0.75)],
    }


def _run_args(tmp_path: Path, *, run_id: str, family: list[str]) -> SimpleNamespace:
    rubric_path = tmp_path / "rubric.json"
    rubric_path.write_text(json.dumps(_rubric()), encoding="utf-8")
    return SimpleNamespace(
        rubric=str(rubric_path),
        output_dir=str(tmp_path / "proof"),
        base_url="http://127.0.0.1:8908",
        profile="local",
        model_id="test-model",
        run_tests=True,
        timeout_seconds=5.0,
        family=family,
        run_id=run_id,
    )


def _passing_evidence(rubric_data: dict, context: ProbeContext) -> list[EvidenceRow]:
    context.runtime_cache["model_runtime_receipts"] = [
        {
            "requested": {"profile": "local", "provider": "fixture", "model": "test-model"},
            "active": {"profile": "local", "provider": "fixture", "model": "test-model"},
            "failover_enabled": False,
            "failover_used": False,
            "attempts": [{"profile": "local", "provider": "fixture", "model": "test-model", "status": "success"}],
        }
    ]
    return [
        EvidenceRow(family["id"], tier, f"{family['id']}-{tier}", "pass", "pass", True, "critical")
        for family in rubric_data["families"]
        for tier in range(1, 5)
    ]


def _read_evidence(path: Path) -> list[EvidenceRow]:
    return [EvidenceRow(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()]


def test_targeted_run_isolates_selected_family_and_preserves_canonical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = _load_loop()
    args = _run_args(tmp_path, run_id="targeted-core", family=["core"])
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True)
    canonical = {
        "latest_evidence.jsonl": "canonical evidence\n",
        "latest_scorecard.json": "canonical scorecard\n",
        "RUBRIC.md": "canonical rubric\n",
        "GAP_LEDGER.md": "canonical gaps\n",
    }
    for name, payload in canonical.items():
        (output_dir / name).write_text(payload, encoding="utf-8")
    captured: list[tuple[str, float]] = []

    def collect(rubric_data: dict, context: ProbeContext) -> list[EvidenceRow]:
        captured.extend((family["id"], family["weight"]) for family in rubric_data["families"])
        return _passing_evidence(rubric_data, context)

    monkeypatch.setattr(loop, "collect_evidence", collect)
    scorecard = loop.run(args)

    assert captured == [("core", 1.0)]
    assert scorecard["coverage"] == "targeted"
    assert scorecard["selected_scope_achieved"] is True
    assert scorecard["parity_achieved"] is False
    assert scorecard["parity_claimable"] is False
    assert scorecard["totals"]["families"] == 1
    for name, payload in canonical.items():
        assert (output_dir / name).read_text(encoding="utf-8") == payload
    bundle = output_dir / "runs" / args.run_id
    evidence = _read_evidence(bundle / "evidence.jsonl")
    assert {row.family for row in evidence} == {"core"}
    assert "No gaps remain in the selected scope." in (bundle / "GAP_LEDGER.md").read_text(encoding="utf-8")


def test_full_run_publishes_verified_bundle_and_independently_checkable_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = _load_loop()
    args = _run_args(tmp_path, run_id="full-proof", family=[])
    monkeypatch.setattr(loop, "collect_evidence", _passing_evidence)

    scorecard = loop.run(args)

    output_dir = Path(args.output_dir)
    bundle = output_dir / "runs" / args.run_id
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    evidence = _read_evidence(bundle / "evidence.jsonl")
    assert scorecard["parity_achieved"] is True
    assert scorecard["parity_claimable"] is True
    assert scorecard["runtime_attribution"]["status"] == "verified"
    assert manifest["run_id"] == args.run_id
    assert manifest["profile"] == args.profile
    assert manifest["model_id"] == args.model_id
    assert manifest["base_url"] == args.base_url
    assert manifest["git_sha"]
    assert manifest["rubric_sha256"]
    assert manifest["evaluator_sha256"]
    digest_payload = {key: value for key, value in manifest.items() if key not in {"provenance_id", "artifacts"}}
    expected_id = hashlib.sha256(
        json.dumps(digest_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert manifest["provenance_id"] == expected_id
    assert validate_evidence_provenance(evidence, required=True) == expected_id
    bundle_scorecard = json.loads((bundle / "scorecard.json").read_text(encoding="utf-8"))
    assert bundle_scorecard["provenance_id"] == expected_id
    for name, digest in manifest["artifacts"].items():
        assert hashlib.sha256((bundle / name).read_bytes()).hexdigest() == digest
    pointer = json.loads((output_dir / "latest_run.json").read_text(encoding="utf-8"))
    assert pointer["provenance_id"] == expected_id
    assert pointer["artifacts"] == manifest["artifacts"]


def test_canonical_pointer_and_scorecard_do_not_advance_when_projection_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = _load_loop()
    args = _run_args(tmp_path, run_id="publish-failure", family=[])
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True)
    (output_dir / "latest_scorecard.json").write_text("old scorecard\n", encoding="utf-8")
    (output_dir / "latest_run.json").write_text("old pointer\n", encoding="utf-8")
    monkeypatch.setattr(loop, "collect_evidence", _passing_evidence)
    original_replace = Path.replace

    def fail_gap_projection(path: Path, target: Path) -> Path:
        if path.name == "GAP_LEDGER.md" and path.parent.name.startswith(".canonical-stage."):
            raise OSError("injected projection failure")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_gap_projection)

    with pytest.raises(OSError, match="injected projection failure"):
        loop.run(args)

    assert (output_dir / "latest_scorecard.json").read_text(encoding="utf-8") == "old scorecard\n"
    assert (output_dir / "latest_run.json").read_text(encoding="utf-8") == "old pointer\n"
    assert not (output_dir / ".canonical-publish.lock").exists()
    assert (output_dir / "runs" / args.run_id / "manifest.json").is_file()


def test_duplicate_or_unsafe_run_id_fails_before_collecting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = _load_loop()
    args = _run_args(tmp_path, run_id="existing", family=[])
    (Path(args.output_dir) / "runs" / args.run_id).mkdir(parents=True)
    called = False

    def collect(_rubric_data: dict, _context: ProbeContext) -> list[EvidenceRow]:
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(loop, "collect_evidence", collect)
    with pytest.raises(FileExistsError, match="already exists"):
        loop.run(args)
    assert called is False
    with pytest.raises(ValueError, match="run id"):
        loop.run(_run_args(tmp_path, run_id="../escape", family=[]))


def test_scoring_rejects_mixed_provenance() -> None:
    rows = [
        EvidenceRow("core", 1, "one", "pass", "pass", True, "critical", provenance_id="run-a"),
        EvidenceRow("core", 2, "two", "pass", "pass", True, "critical", provenance_id="run-b"),
    ]

    with pytest.raises(ValueError, match="mixed evidence provenance"):
        score_families(_rubric(), rows, require_provenance=True)


def test_require_parity_never_accepts_a_targeted_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    loop = _load_loop()
    targeted = {
        "coverage": "targeted",
        "parity_index": 100.0,
        "totals": {"families_at_4": 1, "families": 1, "critical_failures": 0},
        "parity_achieved": False,
        "parity_claimable": False,
    }
    monkeypatch.setattr(loop, "run", lambda _args: targeted)

    assert loop.main(["--family", "core"]) == 0
    assert loop.main(["--family", "core", "--require-parity"]) == 1
