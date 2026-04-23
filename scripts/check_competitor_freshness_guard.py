#!/usr/bin/env python3
"""Fail when canonical competitor artifacts are older than an age threshold."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SUITE_CONFIG = ROOT / "demo" / "baselines" / "agent_comparison_suite.current.json"
DEFAULT_ARTIFACT_PATHS_REL = {
    "latest_json": "docs/openclaw_gap_runs/latest_full_suite_compare.json",
    "latest_markdown": "docs/openclaw_gap_runs/latest_full_suite_compare.md",
    "latest_legacy_json": "docs/openclaw_gap_runs/latest_compare.json",
    "registry_json": "docs/openclaw_gap_runs/competitor_registry.json",
    "registry_markdown": "docs/openclaw_gap_runs/competitor_registry.md",
}
DEFAULT_RESULT_JSON = ROOT / DEFAULT_ARTIFACT_PATHS_REL["latest_json"]
DEFAULT_LEGACY_RESULT_JSON = ROOT / DEFAULT_ARTIFACT_PATHS_REL["latest_legacy_json"]
DEFAULT_REGISTRY_JSON = ROOT / DEFAULT_ARTIFACT_PATHS_REL["registry_json"]


def _parse_iso(raw: str) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_now(raw: str | None) -> datetime:
    if not str(raw or "").strip():
        return datetime.now(timezone.utc)
    parsed = _parse_iso(str(raw))
    if parsed is None:
        raise ValueError(f"invalid --now value: {raw!r}")
    return parsed


def _resolve_repo_path(raw_path: str | None, *, fallback_rel: str) -> Path:
    value = str(raw_path or "").strip() or fallback_rel
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    return path


def _load_artifact_paths(suite_config: Path) -> tuple[dict[str, Path], list[str]]:
    warnings: list[str] = []
    artifact_cfg: dict[str, Any] = {}
    if suite_config.exists():
        try:
            payload = json.loads(suite_config.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("artifact_paths"), dict):
                artifact_cfg = dict(payload["artifact_paths"])
        except Exception as exc:
            warnings.append(
                f"unable to parse suite config for artifact paths: {suite_config} ({type(exc).__name__}: {exc})"
            )
    else:
        warnings.append(f"suite config not found for artifact path defaults: {suite_config}")

    resolved: dict[str, Path] = {}
    for key, fallback_rel in DEFAULT_ARTIFACT_PATHS_REL.items():
        resolved[key] = _resolve_repo_path(
            str(artifact_cfg.get(key) or ""),
            fallback_rel=fallback_rel,
        )
    return resolved, warnings


def _load_json_object(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.exists():
        return None, f"missing JSON file: {path}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return None, f"invalid JSON file {path}: {type(exc).__name__}: {exc}"
    if not isinstance(payload, dict):
        return None, f"JSON root must be an object: {path}"
    return payload, None


def _add_candidate(
    candidates: list[dict[str, Any]],
    warnings: list[str],
    *,
    source: str,
    raw_timestamp: Any,
) -> None:
    value = str(raw_timestamp or "").strip()
    if not value:
        return
    parsed = _parse_iso(value)
    if parsed is None:
        warnings.append(f"invalid timestamp for {source}: {value}")
        return
    candidates.append(
        {
            "source": source,
            "timestamp_raw": value,
            "timestamp_utc": parsed,
        }
    )


def _collect_candidates(
    *,
    result_payload: dict[str, Any],
    registry_payload: dict[str, Any],
    legacy_result_payload: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    candidates: list[dict[str, Any]] = []

    _add_candidate(
        candidates,
        warnings,
        source="result.computed_at_utc",
        raw_timestamp=result_payload.get("computed_at_utc"),
    )
    _add_candidate(
        candidates,
        warnings,
        source="registry.updated_at_utc",
        raw_timestamp=registry_payload.get("updated_at_utc"),
    )
    if isinstance(legacy_result_payload, dict):
        _add_candidate(
            candidates,
            warnings,
            source="legacy_result.computed_at_utc",
            raw_timestamp=legacy_result_payload.get("computed_at_utc"),
        )

    runs = registry_payload.get("runs")
    if isinstance(runs, list):
        for idx, item in enumerate(runs):
            if not isinstance(item, dict):
                continue
            _add_candidate(
                candidates,
                warnings,
                source=f"registry.runs[{idx}].computed_at_utc",
                raw_timestamp=item.get("computed_at_utc"),
            )

    return candidates, warnings


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Fail if required competitor comparison artifacts are older than threshold.")
    )
    parser.add_argument(
        "--result-json",
        default="",
        help=(
            "Path to latest suite result JSON. If omitted, resolved from "
            "--suite-config artifact_paths.latest_json (fallback: docs/openclaw_gap_runs/latest_full_suite_compare.json)."
        ),
    )
    parser.add_argument(
        "--legacy-result-json",
        default="",
        help=(
            "Optional legacy result JSON path. If omitted and --result-json is omitted, "
            "uses --suite-config artifact_paths.latest_legacy_json when present."
        ),
    )
    parser.add_argument(
        "--registry-json",
        default="",
        help=(
            "Path to competitor registry JSON. If omitted, resolved from "
            "--suite-config artifact_paths.registry_json (fallback: docs/openclaw_gap_runs/competitor_registry.json)."
        ),
    )
    parser.add_argument(
        "--suite-config",
        default=str(DEFAULT_SUITE_CONFIG),
        help=(
            "Suite config path used for artifact path defaults "
            "(default: demo/baselines/agent_comparison_suite.current.json)."
        ),
    )
    parser.add_argument(
        "--max-age-days",
        type=float,
        default=7.0,
        help=(
            "Maximum allowed age in days for required timestamps "
            "(result.computed_at_utc and registry.updated_at_utc)."
        ),
    )
    parser.add_argument(
        "--now",
        default="",
        help="Optional ISO-8601 current time override (for deterministic tests).",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    args = parser.parse_args(argv)

    warnings: list[str] = []
    explicit_result = bool(str(args.result_json or "").strip())
    explicit_registry = bool(str(args.registry_json or "").strip())
    explicit_legacy = bool(str(args.legacy_result_json or "").strip())
    suite_config_path = Path(str(args.suite_config or "")).expanduser()
    if not suite_config_path.is_absolute():
        suite_config_path = (ROOT / suite_config_path).resolve()

    artifact_paths: dict[str, Path] = {}
    if (not explicit_result) or (not explicit_registry):
        artifact_paths, artifact_warnings = _load_artifact_paths(suite_config_path)
        warnings.extend(artifact_warnings)
    else:
        artifact_paths = {
            "latest_json": DEFAULT_RESULT_JSON,
            "latest_legacy_json": DEFAULT_LEGACY_RESULT_JSON,
            "registry_json": DEFAULT_REGISTRY_JSON,
        }

    result_path = (
        _resolve_repo_path(str(args.result_json), fallback_rel=DEFAULT_ARTIFACT_PATHS_REL["latest_json"])
        if explicit_result
        else artifact_paths["latest_json"]
    )
    registry_path = (
        _resolve_repo_path(str(args.registry_json), fallback_rel=DEFAULT_ARTIFACT_PATHS_REL["registry_json"])
        if explicit_registry
        else artifact_paths["registry_json"]
    )
    if explicit_legacy:
        legacy_result_path: Path | None = _resolve_repo_path(
            str(args.legacy_result_json),
            fallback_rel=DEFAULT_ARTIFACT_PATHS_REL["latest_legacy_json"],
        )
    elif explicit_result:
        legacy_result_path = None
    else:
        legacy_result_path = artifact_paths.get("latest_legacy_json", DEFAULT_LEGACY_RESULT_JSON)

    fatal_errors: list[str] = []
    if args.max_age_days <= 0:
        fatal_errors.append("--max-age-days must be > 0")

    now: datetime | None = None
    if not fatal_errors:
        try:
            now = _parse_now(args.now)
        except Exception as exc:
            fatal_errors.append(str(exc))

    result_payload: dict[str, Any] = {}
    registry_payload: dict[str, Any] = {}
    if not fatal_errors:
        result_payload, result_error = _load_json_object(result_path)
        if result_error:
            fatal_errors.append(result_error)
        registry_payload, registry_error = _load_json_object(registry_path)
        if registry_error:
            fatal_errors.append(registry_error)

    legacy_result_payload: dict[str, Any] | None = None
    if not fatal_errors and legacy_result_path is not None:
        legacy_result_payload, legacy_error = _load_json_object(legacy_result_path)
        if legacy_error:
            warnings.append(f"optional legacy result artifact unavailable: {legacy_error}")
            legacy_result_payload = None

    required_timestamps: dict[str, datetime] = {}
    if not fatal_errors:
        result_timestamp = _parse_iso(str(result_payload.get("computed_at_utc") or ""))
        if result_timestamp is None:
            fatal_errors.append("missing or invalid required timestamp: result.computed_at_utc")
        else:
            required_timestamps["result.computed_at_utc"] = result_timestamp

        registry_timestamp = _parse_iso(str(registry_payload.get("updated_at_utc") or ""))
        if registry_timestamp is None:
            fatal_errors.append("missing or invalid required timestamp: registry.updated_at_utc")
        else:
            required_timestamps["registry.updated_at_utc"] = registry_timestamp

    candidates: list[dict[str, Any]] = []
    if not fatal_errors:
        candidates, candidate_warnings = _collect_candidates(
            result_payload=(result_payload or {}),
            registry_payload=(registry_payload or {}),
            legacy_result_payload=legacy_result_payload,
        )
        warnings.extend(candidate_warnings)
        if not candidates:
            fatal_errors.append("no valid competitor run timestamps found in result/registry artifacts")

    latest: dict[str, Any] | None = None
    age_days: float | None = None
    required_age_days: dict[str, float] = {}
    required_stale_sources: list[str] = []
    stale = False
    if not fatal_errors and now is not None:
        latest = max(candidates, key=lambda row: row["timestamp_utc"])
        age_seconds = max(0.0, (now - latest["timestamp_utc"]).total_seconds())
        age_days = age_seconds / 86400.0
        for source, timestamp in required_timestamps.items():
            source_age_seconds = max(0.0, (now - timestamp).total_seconds())
            source_age_days = source_age_seconds / 86400.0
            required_age_days[source] = round(float(source_age_days), 4)
            if source_age_days > float(args.max_age_days):
                required_stale_sources.append(source)
        stale = bool(required_stale_sources)

    ok = (not fatal_errors) and (not stale)
    payload: dict[str, Any] = {
        "gate": "competitor_freshness_guard",
        "ok": ok,
        "stale": bool(stale),
        "max_age_days": float(args.max_age_days),
        "now_utc": (now.isoformat() if now is not None else ""),
        "candidate_count": len(candidates),
        "latest_run_at_utc": (latest["timestamp_utc"].isoformat() if latest else ""),
        "latest_run_source": (str(latest.get("source")) if latest else ""),
        "latest_run_age_days": (round(float(age_days), 4) if age_days is not None else None),
        "required_timestamp_sources": sorted(required_timestamps.keys()),
        "required_age_days": required_age_days,
        "required_stale_sources": required_stale_sources,
        "warnings": warnings,
        "errors": fatal_errors,
        "result_json": str(result_path),
        "legacy_result_json": (str(legacy_result_path) if legacy_result_path is not None else ""),
        "registry_json": str(registry_path),
        "suite_config": str(suite_config_path),
    }

    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        if ok:
            print("Competitor freshness guard: PASS")
            print(
                f"- latest run age: {payload['latest_run_age_days']:.3f} days "
                f"(max {float(args.max_age_days):.3f} days)"
            )
            print(f"- latest run at: {payload['latest_run_at_utc']}")
            print(f"- source: {payload['latest_run_source']}")
            print(f"- candidates checked: {payload['candidate_count']}")
            if warnings:
                print(f"- warnings: {len(warnings)}")
                for item in warnings:
                    print(f"  - {item}")
        else:
            print("Competitor freshness guard: FAIL")
            if fatal_errors:
                for item in fatal_errors:
                    print(f"- {item}")
            elif stale:
                print("- required freshness sources are stale:")
                for source in required_stale_sources:
                    source_age_days = float(required_age_days.get(source, 0.0))
                    print(f"  - {source}: age={source_age_days:.3f} days " f"(max {float(args.max_age_days):.3f} days)")
            if warnings:
                print(f"- warnings: {len(warnings)}")
                for item in warnings:
                    print(f"  - {item}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
