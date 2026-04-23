#!/usr/bin/env python3
"""Alert when competitor pressure worsens week-over-week."""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUITE_CONFIG = ROOT / "demo" / "baselines" / "agent_comparison_suite.current.json"
DEFAULT_ARTIFACT_PATHS_REL = {
    "registry_json": "docs/openclaw_gap_runs/competitor_registry.json",
}
DEFAULT_REGISTRY_JSON = ROOT / DEFAULT_ARTIFACT_PATHS_REL["registry_json"]


def _parse_iso(raw: Any) -> datetime | None:
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


def _resolve_repo_path(raw_path: str | None, *, fallback_rel: str) -> Path:
    value = str(raw_path or "").strip() or fallback_rel
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    return path


def _load_registry_path_from_suite_config(suite_config: Path) -> tuple[Path, list[str]]:
    warnings: list[str] = []
    artifact_cfg: dict[str, Any] = {}
    if suite_config.exists():
        try:
            payload = json.loads(suite_config.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and isinstance(payload.get("artifact_paths"), dict):
                artifact_cfg = dict(payload["artifact_paths"])
        except Exception as exc:
            warnings.append(
                f"unable to parse suite config for artifact paths: {suite_config} " f"({type(exc).__name__}: {exc})"
            )
    else:
        warnings.append(f"suite config not found for artifact path defaults: {suite_config}")

    return (
        _resolve_repo_path(
            str(artifact_cfg.get("registry_json") or ""),
            fallback_rel=DEFAULT_ARTIFACT_PATHS_REL["registry_json"],
        ),
        warnings,
    )


def _coerce_number(raw: Any) -> float | None:
    if raw is None:
        return None
    try:
        value = float(raw)
    except Exception:
        return None
    if not math.isfinite(value):
        return None
    return value


def _extract_pressure_snapshot(
    *,
    run: dict[str, Any],
    run_index: int,
    warnings: list[str],
) -> dict[str, Any] | None:
    focus = run.get("focus")
    if not isinstance(focus, dict):
        warnings.append(f"missing focus payload for registry.runs[{run_index}]")
        return None

    pressure = focus.get("competitor_pressure")
    if not isinstance(pressure, dict):
        warnings.append(f"missing focus.competitor_pressure for registry.runs[{run_index}]")
        return None

    ranked = pressure.get("ranked_competitors")
    if not isinstance(ranked, list) or not ranked:
        warnings.append(f"no ranked competitors for registry.runs[{run_index}]")
        return None

    beat_values: list[int] = []
    threat_values: list[float] = []
    top_competitor = ""
    top_threat_score: float | None = None
    for row_index, row in enumerate(ranked):
        if not isinstance(row, dict):
            warnings.append(f"invalid ranked competitor row for registry.runs[{run_index}] row[{row_index}]")
            continue

        beat_metric_source = row.get("metrics_beating_focus")
        beat_metric_raw = _coerce_number(beat_metric_source)
        if beat_metric_source is not None and beat_metric_raw is None:
            warnings.append(
                "non-finite competitor metric 'metrics_beating_focus' "
                f"for registry.runs[{run_index}] row[{row_index}]"
            )
        if beat_metric_raw is not None:
            beat_values.append(int(round(beat_metric_raw)))

        threat_score_source = row.get("composite_score")
        threat_score_raw = _coerce_number(threat_score_source)
        if threat_score_source is not None and threat_score_raw is None:
            warnings.append(
                "non-finite competitor metric 'composite_score' " f"for registry.runs[{run_index}] row[{row_index}]"
            )
        if threat_score_raw is not None:
            threat_values.append(float(threat_score_raw))
            if (top_threat_score is None) or (threat_score_raw > top_threat_score):
                top_threat_score = threat_score_raw
                top_competitor = str(row.get("competitor") or "")

    beat_metric_count: int | None = max(beat_values) if beat_values else None
    threat_score: float | None = max(threat_values) if threat_values else None
    if beat_metric_count is None and threat_score is None:
        warnings.append(
            "no numeric competitor pressure metrics in "
            f"registry.runs[{run_index}].focus.competitor_pressure.ranked_competitors"
        )
        return None

    return {
        "beat_metric_count": beat_metric_count,
        "threat_score": (round(float(threat_score), 3) if threat_score is not None else None),
        "top_competitor": top_competitor,
        "ranked_competitor_count": len(ranked),
    }


def _collect_run_snapshots(
    registry_payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []
    snapshots: list[dict[str, Any]] = []

    runs = registry_payload.get("runs")
    if not isinstance(runs, list):
        return [], warnings, ["registry.runs must be a list"]

    for run_index, run in enumerate(runs):
        if not isinstance(run, dict):
            warnings.append(f"invalid run payload at registry.runs[{run_index}]")
            continue

        raw_timestamp = str(run.get("computed_at_utc") or "").strip()
        timestamp_utc = _parse_iso(raw_timestamp)
        if timestamp_utc is None:
            warnings.append(f"invalid timestamp for registry.runs[{run_index}].computed_at_utc: {raw_timestamp}")
            continue

        snapshot = _extract_pressure_snapshot(run=run, run_index=run_index, warnings=warnings)
        if snapshot is None:
            continue

        snapshots.append(
            {
                "source": f"registry.runs[{run_index}]",
                "timestamp_raw": raw_timestamp,
                "timestamp_utc": timestamp_utc,
                "snapshot": snapshot,
            }
        )

    if not snapshots:
        errors.append("no valid competitor pressure snapshots found in registry.runs")
    return snapshots, warnings, errors


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=("Alert when weekly competitor pressure worsens based on beat-metric count " "or threat score.")
    )
    parser.add_argument(
        "--registry-json",
        default="",
        help=(
            "Path to competitor registry JSON. If omitted, resolved from --suite-config "
            "artifact_paths.registry_json (fallback: docs/openclaw_gap_runs/competitor_registry.json)."
        ),
    )
    parser.add_argument(
        "--suite-config",
        default=str(DEFAULT_SUITE_CONFIG),
        help=(
            "Suite config path used for registry artifact defaults "
            "(default: demo/baselines/agent_comparison_suite.current.json)."
        ),
    )
    parser.add_argument(
        "--lookback-days",
        type=float,
        default=7.0,
        help="Week-over-week lookback window in days (default: 7).",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when worsening alerts are detected.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    args = parser.parse_args(argv)

    fatal_errors: list[str] = []
    warnings: list[str] = []
    lookback_days = float(args.lookback_days)
    lookback_days_payload: float | None = lookback_days if math.isfinite(lookback_days) else None
    if lookback_days_payload is None:
        fatal_errors.append("--lookback-days must be finite")
    elif lookback_days_payload <= 0:
        fatal_errors.append("--lookback-days must be > 0")

    suite_config_path = Path(str(args.suite_config or "")).expanduser()
    if not suite_config_path.is_absolute():
        suite_config_path = (ROOT / suite_config_path).resolve()

    explicit_registry = bool(str(args.registry_json or "").strip())
    if explicit_registry:
        registry_path = _resolve_repo_path(
            str(args.registry_json),
            fallback_rel=DEFAULT_ARTIFACT_PATHS_REL["registry_json"],
        )
    else:
        registry_path, path_warnings = _load_registry_path_from_suite_config(suite_config_path)
        warnings.extend(path_warnings)

    registry_payload: dict[str, Any] = {}
    if not fatal_errors:
        registry_payload, load_error = _load_json_object(registry_path)
        if load_error:
            fatal_errors.append(load_error)

    snapshots: list[dict[str, Any]] = []
    if not fatal_errors:
        snapshots, snapshot_warnings, snapshot_errors = _collect_run_snapshots(registry_payload or {})
        warnings.extend(snapshot_warnings)
        fatal_errors.extend(snapshot_errors)

    latest: dict[str, Any] | None = None
    baseline: dict[str, Any] | None = None
    status = "error"
    metric_deltas: dict[str, dict[str, Any]] = {}
    alerts: list[dict[str, Any]] = []
    if not fatal_errors and snapshots:
        latest = max(snapshots, key=lambda row: row["timestamp_utc"])
        cutoff = latest["timestamp_utc"] - timedelta(days=float(lookback_days_payload))
        baseline_candidates = [row for row in snapshots if row["timestamp_utc"] <= cutoff]

        if not baseline_candidates:
            status = "insufficient_history"
        else:
            baseline = max(baseline_candidates, key=lambda row: row["timestamp_utc"])
            status = "ok"

            for metric in ("beat_metric_count", "threat_score"):
                latest_value = latest["snapshot"].get(metric)
                baseline_value = baseline["snapshot"].get(metric)
                if latest_value is None or baseline_value is None:
                    warnings.append(f"missing comparable metric '{metric}' between latest and baseline runs")
                    continue
                delta = round(float(latest_value) - float(baseline_value), 3)
                worsened = bool(delta > 0)
                metric_deltas[metric] = {
                    "latest": latest_value,
                    "baseline": baseline_value,
                    "delta": delta,
                    "worsened": worsened,
                }
                if worsened:
                    status = "alert"
                    alerts.append(
                        {
                            "metric": metric,
                            "latest": latest_value,
                            "baseline": baseline_value,
                            "delta": delta,
                            "message": (
                                f"{metric} worsened from {baseline_value} to {latest_value} " f"(delta {delta:+.3f})"
                            ),
                        }
                    )

            if not metric_deltas:
                fatal_errors.append("no comparable competitor pressure metrics found between latest and baseline runs")
                status = "error"

    ok = not fatal_errors and status in {"ok", "insufficient_history"}
    would_fail_strict = bool(fatal_errors) or bool(alerts)
    should_fail = bool(fatal_errors) or (bool(args.strict) and bool(alerts))
    payload: dict[str, Any] = {
        "gate": "competitor_weekly_delta_alert",
        "ok": ok,
        "status": status,
        "strict": bool(args.strict),
        "would_fail_strict": bool(would_fail_strict),
        "lookback_days": lookback_days_payload,
        "registry_json": str(registry_path),
        "suite_config": str(suite_config_path),
        "snapshot_count": len(snapshots),
        "latest_run_at_utc": (latest["timestamp_utc"].isoformat() if latest is not None else ""),
        "latest_run_source": (latest["source"] if latest is not None else ""),
        "latest_top_competitor": (
            (latest.get("snapshot") or {}).get("top_competitor", "") if latest is not None else ""
        ),
        "baseline_run_at_utc": (baseline["timestamp_utc"].isoformat() if baseline is not None else ""),
        "baseline_run_source": (baseline["source"] if baseline is not None else ""),
        "baseline_top_competitor": (
            (baseline.get("snapshot") or {}).get("top_competitor", "") if baseline is not None else ""
        ),
        "metrics": metric_deltas,
        "alert_count": len(alerts),
        "alerts": alerts,
        "warnings": warnings,
        "errors": fatal_errors,
    }

    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        if fatal_errors:
            print("Competitor weekly delta alerting: FAIL")
            for item in fatal_errors:
                print(f"- {item}")
        elif status == "insufficient_history":
            print("Competitor weekly delta alerting: PASS (insufficient week-over-week history)")
            print(f"- snapshots analyzed: {len(snapshots)}")
            print(f"- latest run at: {payload['latest_run_at_utc']}")
        elif alerts:
            print("Competitor weekly delta alerting: ALERT")
            print(f"- latest run at: {payload['latest_run_at_utc']}")
            print(f"- baseline run at: {payload['baseline_run_at_utc']}")
            for alert in alerts:
                print(f"- {alert['message']}")
        else:
            print("Competitor weekly delta alerting: PASS")
            print(f"- latest run at: {payload['latest_run_at_utc']}")
            print(f"- baseline run at: {payload['baseline_run_at_utc']}")
            for metric_name, metric_payload in sorted(metric_deltas.items()):
                print(
                    f"- {metric_name}: latest={metric_payload['latest']} "
                    f"baseline={metric_payload['baseline']} delta={metric_payload['delta']:+.3f}"
                )

        if warnings:
            print(f"- warnings: {len(warnings)}")
            for item in warnings:
                print(f"  - {item}")

    return 1 if should_fail else 0


if __name__ == "__main__":
    raise SystemExit(run())
