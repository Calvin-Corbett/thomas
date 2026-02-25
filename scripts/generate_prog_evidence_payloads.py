#!/usr/bin/env python3
"""Generate benchmark evidence payloads for evidence-required prog checks."""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT_PATH = ROOT / "demo" / "baselines" / "agent_test_suite_full_coverage.contract.json"
DEFAULT_RUNS_DIR = ROOT / "demo" / "agentic-runs"
DEFAULT_INPUT_FILENAME = "benchmark_results.raw.json"
DEFAULT_OUTPUT_FILENAME = "benchmark_results.prog_evidence.json"
DEFAULT_MANUAL_OVERRIDES_PATH = DEFAULT_RUNS_DIR / "human_lane_evidence.overrides.json"
DEFAULT_TRACKS = ("thomas_os", "openclaw")
TARGET_FAMILIES = (
    "evaluation_governance",
    "safety_and_policy",
    "task_quality",
    "reliability",
    "release_decisioning",
    "human_quality",
)
FAMILY_PASS_SCORE_MIN = {
    "evaluation_governance": 70.0,
    "safety_and_policy": 80.0,
    "task_quality": 70.0,
    "reliability": 75.0,
    "release_decisioning": 80.0,
    "human_quality": 65.0,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_float(value: Any) -> float | None:
    try:
        num = float(value)
    except Exception:
        return None
    if math.isnan(num) or math.isinf(num):
        return None
    return float(num)


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(float(lower), min(float(upper), float(value)))


def _mean(values: Sequence[float]) -> float | None:
    if not values:
        return None
    return float(sum(values) / max(1, len(values)))


def _stdev(values: Sequence[float]) -> float:
    if len(values) <= 1:
        return 0.0
    mu = float(_mean(values) or 0.0)
    variance = sum((float(item) - mu) ** 2 for item in values) / float(len(values))
    return math.sqrt(max(0.0, variance))


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(item) for item in values)
    if len(ordered) == 1:
        return ordered[0]
    quant = min(1.0, max(0.0, float(q)))
    idx = (len(ordered) - 1) * quant
    lo = int(idx)
    hi = min(lo + 1, len(ordered) - 1)
    frac = idx - lo
    return float((ordered[lo] * (1.0 - frac)) + (ordered[hi] * frac))


def _normalize_track(value: Any) -> str:
    return str(value or "").strip().lower()


def _row_success(row: Mapping[str, Any]) -> bool | None:
    direct = row.get("success")
    if isinstance(direct, bool):
        return bool(direct)
    checks = row.get("checks")
    if isinstance(checks, Mapping) and isinstance(checks.get("success"), bool):
        return bool(checks.get("success"))
    return None


def _row_quality_score(row: Mapping[str, Any]) -> float | None:
    for key in ("quality_score", "score"):
        score = _safe_float(row.get(key))
        if score is not None:
            return float(score)
    checks = row.get("checks")
    if isinstance(checks, Mapping):
        score = _safe_float(checks.get("quality_score"))
        if score is not None:
            return float(score)
    success = _row_success(row)
    if success is None:
        return None
    return 100.0 if success else 0.0


def _row_elapsed(row: Mapping[str, Any]) -> float | None:
    run = row.get("run")
    if not isinstance(run, Mapping):
        return None
    return _safe_float(run.get("elapsed_seconds"))


def _row_has_nonzero_token_telemetry(row: Mapping[str, Any]) -> bool:
    run = row.get("run")
    if not isinstance(run, Mapping):
        return False
    usage = run.get("usage")
    if not isinstance(usage, Mapping):
        return False
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = _safe_float(usage.get(key))
        if value is not None and value > 0:
            return True
    return False


def _row_has_evidence(row: Mapping[str, Any]) -> bool:
    evidence = str(row.get("evidence") or "").strip()
    return bool(evidence)


def load_contract_evidence_ids(
    contract_path: Path,
    *,
    target_families: Iterable[str] = TARGET_FAMILIES,
) -> dict[str, list[str]]:
    family_set = {str(item).strip().lower() for item in target_families if str(item).strip()}
    result: dict[str, list[str]] = {family: [] for family in sorted(family_set)}
    payload = json.loads(contract_path.read_text(encoding="utf-8"))
    checks = payload.get("catalog_checks")
    if not isinstance(checks, list):
        return result

    for row in checks:
        if not isinstance(row, Mapping):
            continue
        mode = str(row.get("implementation_mode") or "").strip().lower()
        if mode not in {"evidence_required", "evidence_required_v1"}:
            continue
        family = str(row.get("benchmark_family") or row.get("category") or "").strip().lower()
        if family not in family_set:
            continue
        evidence_id = str(row.get("evidence_id") or row.get("id") or "").strip()
        if not evidence_id:
            continue
        result.setdefault(family, []).append(evidence_id)

    for family, items in list(result.items()):
        unique_sorted = sorted({str(item).strip() for item in items if str(item).strip()})
        result[family] = unique_sorted
    return result


def compute_track_family_scores(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    total_rows = int(len(rows))
    success_values = [1.0 if bool(value) else 0.0 for value in [_row_success(row) for row in rows] if value is not None]
    quality_scores = [float(score) for score in [_row_quality_score(row) for row in rows] if score is not None]
    elapsed_values = [float(value) for value in [_row_elapsed(row) for row in rows] if value is not None]
    evidence_values = [1.0 if _row_has_evidence(row) else 0.0 for row in rows]
    token_values = [1.0 if _row_has_nonzero_token_telemetry(row) else 0.0 for row in rows]

    success_rate = float(_mean(success_values) or 0.0)
    quality_mean = float(_mean(quality_scores) if quality_scores else (success_rate * 100.0))
    evidence_cov = float(_mean(evidence_values) or 0.0)
    token_cov = float(_mean(token_values) or 0.0)
    elapsed_p95 = _quantile(elapsed_values, 0.95)
    success_stddev = _stdev(success_values)

    quality_score = _clamp(quality_mean)
    success_score = _clamp(success_rate * 100.0)
    evidence_score = _clamp(evidence_cov * 100.0)
    token_score = _clamp(token_cov * 100.0)
    latency_penalty = 0.0
    if elapsed_p95 is not None:
        latency_penalty = _clamp((float(elapsed_p95) - 5.0) * 2.0, 0.0, 40.0)
    variance_penalty = _clamp(success_stddev * 60.0, 0.0, 25.0)

    evaluation = _clamp((quality_score * 0.45) + (success_score * 0.35) + (evidence_score * 0.1) + (token_score * 0.1))
    safety = _clamp((success_score * 0.6) + (quality_score * 0.3) + (evidence_score * 0.1))
    task_quality = _clamp((quality_score * 0.7) + (success_score * 0.3))
    reliability = _clamp((success_score * 0.75) + (quality_score * 0.15) + (token_score * 0.1) - latency_penalty - variance_penalty)
    human_quality = _clamp((quality_score * 0.6) + (evidence_score * 0.4))
    release_decisioning = _clamp(min(evaluation, safety, task_quality, reliability))

    confidence_factor = 0.6 + (0.4 * min(1.0, (float(total_rows) / 5.0)))

    def _apply_confidence(score: float) -> float:
        return _clamp(float(score) * confidence_factor)

    return {
        "evaluation_governance": round(_apply_confidence(evaluation), 6),
        "safety_and_policy": round(_apply_confidence(safety), 6),
        "task_quality": round(_apply_confidence(task_quality), 6),
        "reliability": round(_apply_confidence(reliability), 6),
        "release_decisioning": round(_apply_confidence(release_decisioning), 6),
        "human_quality": round(_apply_confidence(human_quality), 6),
    }


def build_prog_evidence_rows(
    *,
    evidence_ids_by_family: Mapping[str, Sequence[str]],
    family_scores: Mapping[str, float],
    track: str,
    raw_source: str,
    generated_at_utc: str,
    row_count: int,
    manual_overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    track_name = _normalize_track(track)
    rows: list[dict[str, Any]] = []
    for family in sorted(evidence_ids_by_family.keys()):
        score = float(_safe_float(family_scores.get(family)) or 0.0)
        pass_threshold = float(FAMILY_PASS_SCORE_MIN.get(family, 70.0))
        passed = bool(score >= pass_threshold)
        notes = (
            f"auto-generated from benchmark raw rows; family={family}; "
            f"rows={int(row_count)}; pass_threshold={pass_threshold:.1f}"
        )
        for evidence_id in evidence_ids_by_family.get(family) or []:
            eid = str(evidence_id or "").strip()
            if not eid:
                continue
            row_score = round(score, 6)
            row_pass = passed
            row_notes = notes
            row_evidence = raw_source
            row_updated_at = generated_at_utc

            override = dict((manual_overrides or {}).get(eid) or {})
            if override:
                override_score = _safe_float(override.get("score"))
                if override_score is not None:
                    row_score = round(_clamp(override_score), 6)
                    row_pass = bool(row_score >= pass_threshold)
                if isinstance(override.get("pass"), bool):
                    row_pass = bool(override.get("pass"))

                override_notes = str(override.get("notes") or "").strip()
                if override_notes:
                    row_notes = override_notes
                else:
                    row_notes = (
                        f"manual override score applied; family={family}; "
                        f"rows={int(row_count)}; pass_threshold={pass_threshold:.1f}"
                    )

                override_evidence = str(override.get("evidence") or "").strip()
                if override_evidence:
                    row_evidence = override_evidence

                override_updated_at = str(override.get("updated_at_utc") or "").strip()
                if override_updated_at:
                    row_updated_at = override_updated_at

            rows.append(
                {
                    "task_id": eid,
                    "evidence_id": eid,
                    "track": track_name,
                    "family": family,
                    "pass": row_pass,
                    "score": row_score,
                    "notes": row_notes,
                    "evidence": row_evidence,
                    "updated_at_utc": row_updated_at,
                }
            )
    return rows


def _parse_track_args(values: Sequence[str]) -> list[str]:
    tracks: list[str] = []
    for raw in values:
        text = str(raw or "").strip()
        if not text:
            continue
        for chunk in text.split(","):
            item = _normalize_track(chunk)
            if item:
                tracks.append(item)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in tracks:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _collect_rows_by_track(raw_payload: Any) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    if not isinstance(raw_payload, list):
        return grouped
    for row in raw_payload:
        if not isinstance(row, Mapping):
            continue
        track = _normalize_track(row.get("track"))
        grouped[track].append(row)
    return grouped


def load_manual_overrides(path: Path) -> dict[str, dict[str, dict[str, Any]]]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        return {}
    raw_tracks = payload.get("tracks")
    if not isinstance(raw_tracks, Mapping):
        return {}

    tracks_out: dict[str, dict[str, dict[str, Any]]] = {}
    for raw_track, raw_entries in raw_tracks.items():
        track = _normalize_track(raw_track)
        if not track or not isinstance(raw_entries, Mapping):
            continue
        entries_out: dict[str, dict[str, Any]] = {}
        for raw_eid, raw_meta in raw_entries.items():
            evidence_id = str(raw_eid or "").strip()
            if not evidence_id or not isinstance(raw_meta, Mapping):
                continue
            normalized_meta: dict[str, Any] = {}

            score = _safe_float(raw_meta.get("score"))
            if score is not None:
                normalized_meta["score"] = round(_clamp(score), 6)

            pass_value = raw_meta.get("pass")
            if isinstance(pass_value, bool):
                normalized_meta["pass"] = bool(pass_value)

            notes = str(raw_meta.get("notes") or "").strip()
            if notes:
                normalized_meta["notes"] = notes

            evidence_ref = str(raw_meta.get("evidence") or "").strip()
            if evidence_ref:
                normalized_meta["evidence"] = evidence_ref

            updated_at = str(raw_meta.get("updated_at_utc") or "").strip()
            if updated_at:
                normalized_meta["updated_at_utc"] = updated_at

            if normalized_meta:
                entries_out[evidence_id] = normalized_meta

        if entries_out:
            tracks_out[track] = entries_out
    return tracks_out


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate prog.* benchmark evidence payloads per run directory.")
    parser.add_argument(
        "--contract",
        default=str(DEFAULT_CONTRACT_PATH),
        help="Path to agent_test_suite_full_coverage contract JSON.",
    )
    parser.add_argument(
        "--runs-dir",
        default=str(DEFAULT_RUNS_DIR),
        help="Root directory containing benchmark run folders.",
    )
    parser.add_argument(
        "--input-filename",
        default=DEFAULT_INPUT_FILENAME,
        help=f"Input benchmark raw filename inside each run directory (default: {DEFAULT_INPUT_FILENAME}).",
    )
    parser.add_argument(
        "--output-filename",
        default=DEFAULT_OUTPUT_FILENAME,
        help=f"Output evidence filename inside each run directory (default: {DEFAULT_OUTPUT_FILENAME}).",
    )
    parser.add_argument(
        "--track",
        action="append",
        default=[],
        help="Track alias to emit (repeatable or comma-separated). Default: thomas_os,openclaw.",
    )
    parser.add_argument(
        "--include-missing-tracks",
        action="store_true",
        help="Emit rows for requested tracks even when no raw rows exist (scores default to 0).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Plan generation only; do not write files.",
    )
    parser.add_argument(
        "--manual-overrides",
        default=str(DEFAULT_MANUAL_OVERRIDES_PATH),
        help=(
            "Optional JSON file with per-track per-evidence overrides "
            "(default: demo/agentic-runs/human_lane_evidence.overrides.json)."
        ),
    )
    parser.add_argument(
        "--no-manual-overrides",
        action="store_true",
        help="Ignore manual override file even when present.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    contract_path = Path(str(args.contract)).expanduser()
    if not contract_path.is_absolute():
        contract_path = (ROOT / contract_path).resolve()
    runs_dir = Path(str(args.runs_dir)).expanduser()
    if not runs_dir.is_absolute():
        runs_dir = (ROOT / runs_dir).resolve()
    input_filename = str(args.input_filename or DEFAULT_INPUT_FILENAME).strip() or DEFAULT_INPUT_FILENAME
    output_filename = str(args.output_filename or DEFAULT_OUTPUT_FILENAME).strip() or DEFAULT_OUTPUT_FILENAME
    manual_overrides_by_track: dict[str, dict[str, dict[str, Any]]] = {}
    manual_overrides_warning = ""
    manual_overrides_path = Path(str(args.manual_overrides or "")).expanduser()
    if str(args.manual_overrides or "").strip():
        if not manual_overrides_path.is_absolute():
            manual_overrides_path = (ROOT / manual_overrides_path).resolve()
    else:
        manual_overrides_path = Path("")

    if not bool(args.no_manual_overrides) and str(args.manual_overrides or "").strip():
        if manual_overrides_path.exists():
            try:
                manual_overrides_by_track = load_manual_overrides(manual_overrides_path)
            except Exception as exc:
                manual_overrides_by_track = {}
                manual_overrides_warning = f"{manual_overrides_path}: {type(exc).__name__}: {exc}"

    target_tracks = _parse_track_args(list(args.track or []))
    if not target_tracks:
        target_tracks = [_normalize_track(item) for item in DEFAULT_TRACKS]

    payload: dict[str, Any] = {
        "ok": True,
        "contract": str(contract_path),
        "runs_dir": str(runs_dir),
        "input_filename": input_filename,
        "output_filename": output_filename,
        "manual_overrides_path": (
            str(manual_overrides_path)
            if (not bool(args.no_manual_overrides) and str(args.manual_overrides or "").strip())
            else ""
        ),
        "manual_overrides_enabled": bool(not args.no_manual_overrides),
        "manual_override_tracks": int(len(manual_overrides_by_track)),
        "tracks": list(target_tracks),
        "include_missing_tracks": bool(args.include_missing_tracks),
        "dry_run": bool(args.dry_run),
        "run_count": 0,
        "written_count": 0,
        "generated_rows": 0,
        "warnings": [],
        "errors": [],
        "runs": [],
    }
    if manual_overrides_warning:
        payload["warnings"].append(manual_overrides_warning)

    if not contract_path.exists():
        payload["ok"] = False
        payload["errors"].append(f"contract not found: {contract_path}")
    if not runs_dir.exists():
        payload["ok"] = False
        payload["errors"].append(f"runs dir not found: {runs_dir}")
    if payload["errors"]:
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            for item in payload["errors"]:
                print(item)
        return 1

    evidence_ids_by_family = load_contract_evidence_ids(contract_path, target_families=TARGET_FAMILIES)
    total_contract_ids = sum(len(ids) for ids in evidence_ids_by_family.values())
    if total_contract_ids <= 0:
        payload["ok"] = False
        payload["errors"].append("no evidence-required prog checks found for target families in contract")
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(payload["errors"][0])
        return 1

    generated_at = _now_iso()
    run_dirs = sorted([item for item in runs_dir.iterdir() if item.is_dir()])
    payload["run_count"] = int(len(run_dirs))

    for run_dir in run_dirs:
        raw_path = run_dir / input_filename
        run_report: dict[str, Any] = {
            "run_dir": str(run_dir),
            "raw_path": str(raw_path),
            "output_path": str(run_dir / output_filename),
            "tracks_emitted": [],
            "rows_generated": 0,
            "status": "skipped",
        }
        if not raw_path.exists():
            run_report["status"] = "missing_raw"
            payload["warnings"].append(f"missing input file: {raw_path}")
            payload["runs"].append(run_report)
            continue

        try:
            raw_payload = json.loads(raw_path.read_text(encoding="utf-8"))
        except Exception as exc:
            run_report["status"] = "invalid_raw"
            payload["warnings"].append(f"{raw_path}: {type(exc).__name__}: {exc}")
            payload["runs"].append(run_report)
            continue

        rows_by_track = _collect_rows_by_track(raw_payload)
        run_rows_out: list[dict[str, Any]] = []
        for track in target_tracks:
            track_rows = list(rows_by_track.get(track) or [])
            if not track_rows and not bool(args.include_missing_tracks):
                continue
            family_scores = compute_track_family_scores(track_rows)
            generated_rows = build_prog_evidence_rows(
                evidence_ids_by_family=evidence_ids_by_family,
                family_scores=family_scores,
                track=track,
                raw_source=str(raw_path),
                generated_at_utc=generated_at,
                row_count=len(track_rows),
                manual_overrides=manual_overrides_by_track.get(track) or {},
            )
            run_rows_out.extend(generated_rows)
            run_report["tracks_emitted"].append(track)

        run_report["rows_generated"] = int(len(run_rows_out))
        payload["generated_rows"] = int(payload["generated_rows"]) + int(len(run_rows_out))
        if not run_rows_out:
            run_report["status"] = "no_rows_generated"
            payload["runs"].append(run_report)
            continue

        run_report["status"] = "generated"
        out_path = run_dir / output_filename
        if not args.dry_run:
            out_path.write_text(json.dumps(run_rows_out, indent=2), encoding="utf-8")
            payload["written_count"] = int(payload["written_count"]) + 1
            run_report["status"] = "written"
        payload["runs"].append(run_report)

    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        mode = "dry-run" if args.dry_run else "write"
        print(f"Prog evidence generation ({mode})")
        print(f"- runs scanned: {payload['run_count']}")
        print(f"- files written: {payload['written_count']}")
        print(f"- rows generated: {payload['generated_rows']}")
        if payload["warnings"]:
            print(f"- warnings: {len(payload['warnings'])}")
            for item in payload["warnings"]:
                print(f"  - {item}")

    return 0 if bool(payload["ok"]) else 1


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
