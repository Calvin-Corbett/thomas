"""Executable frozen-corpus runner for Thomas evolve supervision."""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .decision import ACTION_PROMOTE, decide_for_session
from .supervisor import _corpus_lock_findings, evaluate_candidate
from .verifier_panel import run_verifier_panel


@dataclass(frozen=True)
class CorpusCaseResult:
    case_id: str
    ok: bool
    expected: str
    actual: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "ok": bool(self.ok),
            "expected": self.expected,
            "actual": self.actual,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class EvolveCorpusRunResult:
    ok: bool
    case_count: int
    cases: tuple[CorpusCaseResult, ...]
    lock_errors: tuple[dict[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": bool(self.ok),
            "case_count": int(self.case_count),
            "cases": [case.to_dict() for case in self.cases],
            "lock_errors": list(self.lock_errors),
        }


def _load_locked_case_payloads(repo_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    root = Path(repo_root)
    lock_errors = [item.to_dict() for item in _corpus_lock_findings(root)]
    if lock_errors:
        return [], lock_errors

    corpus_root = root / "evolve_corpus"
    lock_payload = json.loads((corpus_root / "LOCK.json").read_text(encoding="utf-8"))
    locked_files = lock_payload.get("files") if isinstance(lock_payload, dict) else {}
    cases: list[dict[str, Any]] = []
    for rel in sorted(locked_files):
        rel_text = str(rel)
        if not rel_text.startswith("cases/") or not rel_text.endswith(".json"):
            continue
        try:
            payload = json.loads((corpus_root / rel_text).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            cases.append(
                {
                    "case_id": rel_text,
                    "expected_supervisor_outcome": "invalid_case",
                    "load_error": str(exc),
                }
            )
            continue
        if isinstance(payload, dict):
            cases.append(payload)
    return cases, []


def _write_minimal_repo(root: Path) -> None:
    (root / "thomas" / "core").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "thomas" / "core" / "example.py").write_text("VALUE = 'blue'\n", encoding="utf-8")
    (root / "tests" / "test_architecture.py").write_text(
        "from thomas.core import example\n\n\ndef test_architecture():\n    assert example.VALUE\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text('[project]\nname = "thomas"\n', encoding="utf-8")
    (root / "agent_safety.toml").write_text(
        (
            "[project]\n"
            'test_dirs = ["tests/"]\n\n'
            "[protected]\n"
            'policy_files = ["evolve_governor.toml", "evolve_corpus/"]\n'
            "guardrails_files = []\n"
            'enforcement_files = ["tests/test_architecture.py"]\n'
            "enforcement_scripts = []\n"
        ),
        encoding="utf-8",
    )


def _copy_locked_corpus(repo_root: Path, blue_root: Path) -> None:
    shutil.copytree(Path(repo_root) / "evolve_corpus", blue_root / "evolve_corpus")


def _prepare_candidate_pair(repo_root: Path, case: dict[str, Any], workspace: Path) -> tuple[Path, Path]:
    blue = workspace / "blue"
    green = workspace / "green"
    _write_minimal_repo(blue)
    _copy_locked_corpus(repo_root, blue)
    shutil.copytree(blue, green)

    changed_files = case.get("changed_files")
    if not isinstance(changed_files, list) or not changed_files:
        changed_files = ["thomas/core/example.py"]
    for raw_rel in changed_files:
        rel = str(raw_rel or "").replace("\\", "/").lstrip("./")
        if not rel:
            continue
        blue_path = blue / rel
        green_path = green / rel
        blue_path.parent.mkdir(parents=True, exist_ok=True)
        green_path.parent.mkdir(parents=True, exist_ok=True)
        if not blue_path.exists():
            blue_path.write_text("VALUE = 'blue'\n", encoding="utf-8")
        green_path.write_text("VALUE = 'green'\n", encoding="utf-8")
    return blue, green


def _run_session_case(case: dict[str, Any]) -> CorpusCaseResult:
    case_id = str(case.get("case_id") or "unknown")
    expected = str(case.get("expected_supervisor_outcome") or "")
    session = dict(case.get("session") or {})
    risk = str(case.get("claimed_risk") or "low")
    decision = decide_for_session("auto_safe", session, risk)
    panel = run_verifier_panel(session)
    actual = decision.action
    if expected == "eligible_for_decision_gate":
        ok = decision.action == ACTION_PROMOTE
    elif expected == "hold_or_reject":
        ok = decision.action != ACTION_PROMOTE
    else:
        ok = False
    return CorpusCaseResult(
        case_id=case_id,
        ok=ok,
        expected=expected,
        actual=actual,
        details={"decision": decision.to_dict(), "verifier_panel": panel.to_dict()},
    )


def _run_candidate_case(repo_root: Path, case: dict[str, Any], workspace: Path) -> CorpusCaseResult:
    case_id = str(case.get("case_id") or "unknown")
    expected = str(case.get("expected_supervisor_outcome") or "")
    posture = str(case.get("posture") or "auto_safe")
    claimed_category = str(case.get("claimed_category") or "")
    claimed_risk = str(case.get("claimed_risk") or "low")
    blue, green = _prepare_candidate_pair(repo_root, case, workspace)
    verdict = evaluate_candidate(
        blue,
        green,
        claimed_category=claimed_category,
        claimed_risk=claimed_risk,
        session_payload=dict(case.get("session") or {}),
    )
    session = dict(case.get("session") or {"delta": {"changed_count": verdict.delta.changed_count}, "verification": []})
    session.setdefault("category", claimed_category)
    session.setdefault("risk_tier", claimed_risk)
    session["supervisor_verdict"] = verdict.to_dict()
    decision = decide_for_session(posture, session, claimed_risk)
    panel = run_verifier_panel(session, supervisor_verdict=verdict)
    finding_codes = {item.code for item in verdict.findings}
    expected_codes = {str(item) for item in case.get("expected_finding_codes") or []}

    if expected == "reject":
        ok = verdict.ok is False and expected_codes.issubset(finding_codes)
        actual = "reject" if verdict.ok is False else "not_reject"
    elif expected == "reject_or_hold_critical":
        ok = verdict.risk_floor == "critical" and (verdict.ok is False or decision.action != ACTION_PROMOTE)
        actual = f"{decision.action}_{verdict.risk_floor}"
    else:
        ok = False
        actual = "unsupported"

    return CorpusCaseResult(
        case_id=case_id,
        ok=ok,
        expected=expected,
        actual=actual,
        details={
            "decision": decision.to_dict(),
            "finding_codes": sorted(finding_codes),
            "verifier_panel": panel.to_dict(),
            "risk_floor": verdict.risk_floor,
            "verdict_ok": verdict.ok,
            "posture": posture,
        },
    )


def run_evolve_corpus(repo_root: Path) -> EvolveCorpusRunResult:
    """Execute the locked evolve corpus against blue-owned supervisor code."""
    root = Path(repo_root)
    cases, lock_errors = _load_locked_case_payloads(root)
    if lock_errors:
        return EvolveCorpusRunResult(ok=False, case_count=0, cases=(), lock_errors=tuple(lock_errors))

    results: list[CorpusCaseResult] = []
    with tempfile.TemporaryDirectory(prefix="thomas-evolve-corpus-") as tmp:
        tmp_root = Path(tmp)
        for index, case in enumerate(cases):
            if "load_error" in case:
                results.append(
                    CorpusCaseResult(
                        case_id=str(case.get("case_id") or f"case-{index}"),
                        ok=False,
                        expected=str(case.get("expected_supervisor_outcome") or "valid_case"),
                        actual="invalid_case",
                        details={"load_error": str(case.get("load_error") or "")},
                    )
                )
            elif (
                isinstance(case.get("session"), dict)
                and not case.get("changed_files")
                and not case.get("claimed_category")
            ):
                results.append(_run_session_case(case))
            else:
                results.append(_run_candidate_case(root, case, tmp_root / f"case-{index}"))

    return EvolveCorpusRunResult(
        ok=bool(results) and all(case.ok for case in results),
        case_count=len(results),
        cases=tuple(results),
    )
