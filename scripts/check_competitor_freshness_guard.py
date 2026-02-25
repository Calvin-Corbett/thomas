#!/usr/bin/env python3
"""Fail when competitor comparison artifacts are older than an age threshold."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RESULT_JSON = ROOT / "docs" / "openclaw_gap_runs" / "latest_full_suite_compare.json"
DEFAULT_REGISTRY_JSON = ROOT / "docs" / "openclaw_gap_runs" / "competitor_registry.json"


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
        description="Fail if latest competitor comparison run is older than threshold."
    )
    parser.add_argument(
        "--result-json",
        default=str(DEFAULT_RESULT_JSON),
        help="Path to latest suite result JSON (default: docs/openclaw_gap_runs/latest_full_suite_compare.json).",
    )
    parser.add_argument(
        "--registry-json",
        default=str(DEFAULT_REGISTRY_JSON),
        help="Path to competitor registry JSON (default: docs/openclaw_gap_runs/competitor_registry.json).",
    )
    parser.add_argument(
        "--max-age-days",
        type=float,
        default=7.0,
        help="Maximum allowed age in days for latest competitor run (default: 7).",
    )
    parser.add_argument(
        "--now",
        default="",
        help="Optional ISO-8601 current time override (for deterministic tests).",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON output.")
    args = parser.parse_args(argv)

    result_path = Path(args.result_json).expanduser()
    if not result_path.is_absolute():
        result_path = (ROOT / result_path).resolve()
    registry_path = Path(args.registry_json).expanduser()
    if not registry_path.is_absolute():
        registry_path = (ROOT / registry_path).resolve()

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

    warnings: list[str] = []
    candidates: list[dict[str, Any]] = []
    if not fatal_errors:
        candidates, warnings = _collect_candidates(
            result_payload=(result_payload or {}),
            registry_payload=(registry_payload or {}),
        )
        if not candidates:
            fatal_errors.append("no valid competitor run timestamps found in result/registry artifacts")

    latest: dict[str, Any] | None = None
    age_days: float | None = None
    stale = False
    if not fatal_errors and now is not None:
        latest = max(candidates, key=lambda row: row["timestamp_utc"])
        age_seconds = max(0.0, (now - latest["timestamp_utc"]).total_seconds())
        age_days = age_seconds / 86400.0
        stale = bool(age_days > float(args.max_age_days))

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
        "warnings": warnings,
        "errors": fatal_errors,
        "result_json": str(result_path),
        "registry_json": str(registry_path),
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
                print(
                    f"- latest run is stale: age={payload['latest_run_age_days']:.3f} days "
                    f"(max {float(args.max_age_days):.3f} days)"
                )
                print(f"- latest run at: {payload['latest_run_at_utc']}")
                print(f"- source: {payload['latest_run_source']}")
            if warnings:
                print(f"- warnings: {len(warnings)}")
                for item in warnings:
                    print(f"  - {item}")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
