#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from pathlib import Path

try:
    import tomllib
except Exception:  # pragma: no cover
    import tomli as tomllib  # type: ignore

from thomas.observability.onboarding_outcomes import build_onboarding_outcome_report
from thomas.observability.onboarding_outcomes_gate import evaluate_onboarding_outcomes_gate
from thomas.observability.run_db import resolve_runs_db_path
from thomas.security.security_audit import run_security_audit

ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _evaluate_onboarding_gate(
    *,
    days: int,
    db_path: str,
    min_events_for_quality_thresholds: int,
    min_completion_rate: float,
    min_recovery_success_rate: float,
    max_median_time_to_ready_seconds: float,
) -> dict:
    target_db = Path(db_path).resolve() if str(db_path or "").strip() else resolve_runs_db_path()
    report = build_onboarding_outcome_report(target_db, since_days=max(1, int(days)))
    gate = evaluate_onboarding_outcomes_gate(
        report,
        min_events_for_quality_thresholds=max(0, int(min_events_for_quality_thresholds)),
        min_completion_rate=max(0.0, min(1.0, float(min_completion_rate))),
        min_recovery_success_rate=max(0.0, min(1.0, float(min_recovery_success_rate))),
        max_median_time_to_ready_seconds=max(1.0, float(max_median_time_to_ready_seconds)),
    )
    return {
        "ok": bool(gate.get("ok", False)),
        "db_path": str(target_db),
        "errors": list(gate.get("errors") or []),
        "warnings": list(gate.get("warnings") or []),
        "summary": dict(gate.get("summary") or {}),
        "thresholds": dict(gate.get("thresholds") or {}),
    }


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Release hygiene checks for versioning, changelog, and onboarding KPI guardrails."
    )
    parser.add_argument(
        "--enforce-onboarding-gate",
        dest="enforce_onboarding_gate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enforce onboarding outcomes gate as part of release hygiene.",
    )
    parser.add_argument("--onboarding-days", type=int, default=7, help="Onboarding outcomes window in days.")
    parser.add_argument("--onboarding-db", default="", help="Optional onboarding outcomes DB path override.")
    parser.add_argument(
        "--onboarding-min-events-for-quality-thresholds",
        type=int,
        default=20,
        help="Minimum telemetry events before KPI threshold enforcement activates.",
    )
    parser.add_argument(
        "--onboarding-min-completion-rate",
        type=float,
        default=0.9,
        help="Minimum onboarding completion rate threshold.",
    )
    parser.add_argument(
        "--onboarding-min-recovery-success-rate",
        type=float,
        default=0.8,
        help="Minimum onboarding recovery success rate threshold.",
    )
    parser.add_argument(
        "--onboarding-max-median-time-to-ready-seconds",
        type=float,
        default=480.0,
        help="Maximum onboarding median time-to-ready threshold in seconds.",
    )
    parser.add_argument(
        "--enforce-security-audit",
        dest="enforce_security_audit",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Block release hygiene when security audit has failing checks (high-severity policy).",
    )
    parser.add_argument(
        "--security-threat-max-age-days",
        type=int,
        default=30,
        help="Maximum threat model age in days for security audit checks.",
    )
    parser.add_argument(
        "--security-min-extension-pass-rate",
        type=float,
        default=0.95,
        help="Minimum extension certification pass rate for security audit checks.",
    )
    parser.add_argument(
        "--security-include-incident-drill",
        action="store_true",
        help="Include incident drill checks in release-time security audit.",
    )
    parser.add_argument(
        "--strict-warnings",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Treat release-hygiene warnings as failures.",
    )
    args = parser.parse_args(argv)

    errors: list[str] = []
    warnings: list[str] = []

    pyproject_path = ROOT / "pyproject.toml"
    init_path = ROOT / "thomas" / "__init__.py"
    changelog_path = ROOT / "CHANGELOG.md"

    try:
        pyproject = tomllib.loads(_read(pyproject_path))
        project_version = str((pyproject.get("project") or {}).get("version") or "").strip()
    except Exception as exc:
        errors.append(f"failed to parse {pyproject_path}: {exc}")
        project_version = ""

    init_text = _read(init_path)
    m = re.search(r"__version__\s*=\s*\"([^\"]+)\"", init_text)
    init_version = m.group(1).strip() if m else ""
    if not init_version:
        errors.append(f"could not find __version__ in {init_path}")

    if project_version and init_version and project_version != init_version:
        errors.append(f"version mismatch: pyproject.toml={project_version} vs thomas/__init__.py={init_version}")

    changelog_text = _read(changelog_path)
    if "## [Unreleased]" not in changelog_text:
        errors.append('CHANGELOG.md is missing "## [Unreleased]" section')

    target_version = project_version or init_version
    if target_version:
        version_header = re.compile(
            rf"^## \[{re.escape(target_version)}\](?:\s*-\s*\d{{4}}-\d{{2}}-\d{{2}})?\s*$", re.M
        )
        if not version_header.search(changelog_text):
            errors.append(f"CHANGELOG.md is missing a section header for version [{target_version}]")

    onboarding_gate: dict | None = None
    security_audit: dict | None = None
    if bool(args.enforce_onboarding_gate):
        try:
            onboarding_gate = _evaluate_onboarding_gate(
                days=int(args.onboarding_days),
                db_path=str(args.onboarding_db or ""),
                min_events_for_quality_thresholds=int(args.onboarding_min_events_for_quality_thresholds),
                min_completion_rate=float(args.onboarding_min_completion_rate),
                min_recovery_success_rate=float(args.onboarding_min_recovery_success_rate),
                max_median_time_to_ready_seconds=float(args.onboarding_max_median_time_to_ready_seconds),
            )
        except Exception as exc:
            errors.append(f"onboarding outcomes gate evaluation failed: {type(exc).__name__}: {exc}")
        else:
            gate_errors = list(onboarding_gate.get("errors") or [])
            gate_warnings = list(onboarding_gate.get("warnings") or [])
            if gate_errors:
                lead = str(gate_errors[0]).strip()
                if len(gate_errors) > 1:
                    lead += f" (+{len(gate_errors) - 1} more)"
                errors.append(f"onboarding outcomes gate failed: {lead}")
            warnings.extend(
                f"onboarding outcomes gate warning: {str(msg).strip()}" for msg in gate_warnings if str(msg).strip()
            )

    if bool(args.enforce_security_audit):
        try:
            security_audit = run_security_audit(
                ROOT,
                max_threat_model_age_days=max(1, int(args.security_threat_max_age_days)),
                min_extension_pass_rate=max(0.0, min(1.0, float(args.security_min_extension_pass_rate))),
                include_incident_drill=bool(args.security_include_incident_drill),
            )
        except Exception as exc:
            errors.append(f"security audit evaluation failed: {type(exc).__name__}: {exc}")
        else:
            if not bool(security_audit.get("ok", False)):
                failing_checks = list((security_audit.get("summary") or {}).get("failing_checks") or [])
                joined = ", ".join(failing_checks) if failing_checks else "unknown"
                errors.append(f"security audit failed (high severity): {joined}")
            warning_count = int((security_audit.get("summary") or {}).get("warning_count") or 0)
            if warning_count > 0:
                warnings.append(f"security audit warnings present: {warning_count}")

    if warnings and bool(args.strict_warnings):
        print("release hygiene: FAIL")
        for warn in warnings:
            print(f"- WARN: {warn}")
        return 1

    if errors:
        print("release hygiene: FAIL")
        for err in errors:
            print(f"- {err}")
        for warn in warnings:
            print(f"- WARN: {warn}")
        return 1

    print("release hygiene: PASS")
    print(f"- version: {target_version}")
    print("- changelog sections present: Unreleased + current version")
    if bool(args.enforce_onboarding_gate):
        gate = onboarding_gate or {}
        summary = dict(gate.get("summary") or {})
        print(
            '- onboarding gate: '
            f"OK (events={int(summary.get('events', 0))}, "
            f"completion={float(summary.get('completion_rate', 0.0)):.4f}, "
            f"recovery={float(summary.get('recovery_success_rate', 0.0)):.4f}, "
            f"median_ready_s={float(summary.get('median_time_to_ready_seconds', 0.0)):.3f})"
        )
    if bool(args.enforce_security_audit):
        audit = security_audit or {}
        summary = dict(audit.get("summary") or {})
        failing = ", ".join(list(summary.get("failing_checks") or [])) or "none"
        print(
            '- security audit: '
            f"OK (checks={int(summary.get('check_count', 0))}, "
            f"failing={failing}, warnings={int(summary.get('warning_count', 0))})"
        )
    for warn in warnings:
        print(f"- WARN: {warn}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
