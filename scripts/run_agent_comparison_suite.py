from __future__ import annotations

import argparse
import glob
import json
import math
import shutil
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from thomas.demo import agent_comparison_suite as _suite

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SUITE_CONFIG = ROOT / "demo" / "baselines" / "agent_comparison_suite.current.json"
DEFAULT_ARTIFACT_PATHS_REL = {
    "latest_json": "docs/reference_cli_gap_runs/latest_full_suite_compare.json",
    "latest_markdown": "docs/reference_cli_gap_runs/latest_full_suite_compare.md",
    "latest_legacy_json": "docs/reference_cli_gap_runs/latest_compare.json",
    "registry_json": "docs/reference_cli_gap_runs/competitor_registry.json",
    "registry_markdown": "docs/reference_cli_gap_runs/competitor_registry.md",
}
BENCHMARK_GLOB_KEYS: dict[str, tuple[str, ...]] = {
    "benchmark_scorecard_globs": (
        "benchmark_scorecard_globs",
        "benchmark_scorecard_glob",
        "scorecard_globs",
        "scorecard_glob",
    ),
    "benchmark_raw_globs": (
        "benchmark_raw_globs",
        "benchmark_raw_glob",
        "raw_globs",
        "benchmark_results_raw_globs",
        "benchmark_results_globs",
    ),
    "benchmark_evidence_globs": (
        "benchmark_evidence_globs",
        "benchmark_evidence_glob",
        "evidence_globs",
        "benchmark_checks_globs",
    ),
}
BENCHMARK_ALIAS_KEYS = (
    "benchmark_aliases",
    "benchmark_alias",
    "benchmark_tracks",
    "track_aliases",
)
BENCHMARK_EVIDENCE_CONTAINER_KEYS = (
    "rows",
    "results",
    "records",
    "items",
    "data",
    "evaluations",
    "tasks",
    "entries",
)
EVIDENCE_TRUE_STRINGS = {
    "1",
    "true",
    "yes",
    "y",
    "ok",
    "pass",
    "passed",
    "success",
    "succeeded",
}
EVIDENCE_FALSE_STRINGS = {
    "0",
    "false",
    "no",
    "n",
    "fail",
    "failed",
    "error",
}


def _resolve_repo_path(repo_root: Path, raw_path: str | None, *, fallback_rel: str) -> Path:
    value = str(raw_path or "").strip() or fallback_rel
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = (repo_root / path).resolve()
    return path


def _dedupe_keep_order(items: Sequence[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        text = str(raw or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _coerce_string_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    values: list[str] = []
    if isinstance(raw, str):
        values = [raw]
    elif isinstance(raw, Mapping):
        for key in ("glob", "path", "pattern", "value"):
            if key in raw:
                values = [str(raw.get(key) or "")]
                break
    elif isinstance(raw, Sequence) and not isinstance(raw, str | bytes | bytearray):
        for item in raw:
            if isinstance(item, Mapping):
                for key in ("glob", "path", "pattern", "value"):
                    if key in item:
                        values.append(str(item.get(key) or ""))
                        break
                else:
                    values.append(str(item))
            else:
                values.append(str(item))
    else:
        values = [str(raw)]
    return _dedupe_keep_order(values)


def _first_present_string_list(payload: Mapping[str, Any], keys: Sequence[str]) -> list[str]:
    for key in keys:
        values = _coerce_string_list(payload.get(key))
        if values:
            return values
    return []


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    parsed: float
    if isinstance(value, int | float):
        parsed = float(value)
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            parsed = float(text)
        except Exception:
            return None
    if not math.isfinite(parsed):
        return None
    return float(parsed)


def _coerce_bool(value: Any, *, allow_numeric: bool = True) -> bool | None:
    if isinstance(value, bool):
        return value
    if allow_numeric and isinstance(value, int | float) and value in {0, 1}:
        return bool(int(value))
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    if not allow_numeric and text in {"0", "1"}:
        return None
    if text in EVIDENCE_TRUE_STRINGS:
        return True
    if text in EVIDENCE_FALSE_STRINGS:
        return False
    return None


def _extract_evidence_pass(row: Mapping[str, Any]) -> bool | None:
    for key in ("pass", "success", "passed", "ok"):
        value = _coerce_bool(row.get(key), allow_numeric=True)
        if value is not None:
            return value
    checks = row.get("checks")
    if isinstance(checks, Mapping):
        for key in ("pass", "success", "passed", "ok"):
            value = _coerce_bool(checks.get(key), allow_numeric=True)
            if value is not None:
                return value
    for key in ("status", "outcome", "result"):
        value = _coerce_bool(row.get(key), allow_numeric=False)
        if value is not None:
            return value
    return None


def _extract_evidence_score(row: Mapping[str, Any]) -> float | None:
    for key in ("score", "quality_score"):
        value = _safe_float(row.get(key))
        if value is not None:
            return value
    checks = row.get("checks")
    if isinstance(checks, Mapping):
        for key in ("score", "quality_score"):
            value = _safe_float(checks.get(key))
            if value is not None:
                return value
    return None


def _extract_unambiguous_value_score(row: Mapping[str, Any]) -> float | None:
    if "value" not in row:
        return None
    value = row.get("value")
    numeric = _safe_float(value)
    if numeric is None:
        return None
    # Binary numeric values are ambiguous (bool-like vs score-like); keep them as raw `value`.
    if numeric in {0.0, 1.0}:
        return None
    return float(numeric)


def _extract_evidence_source(row: Mapping[str, Any]) -> str:
    for key in ("evidence", "source", "evidence_path", "artifact", "path", "transcript"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _extract_evidence_notes(row: Mapping[str, Any]) -> str:
    for key in ("notes", "note", "reason", "message", "summary"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _extract_evidence_updated_at(row: Mapping[str, Any]) -> str:
    for key in ("updated_at_utc", "updated_at", "timestamp", "created_at"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _extract_evidence_track(row: Mapping[str, Any]) -> str:
    for key in ("track", "benchmark_alias", "agent", "competitor", "profile"):
        value = str(row.get(key) or "").strip().lower()
        if value:
            return value
    return ""


def _extract_evidence_check_id(row: Mapping[str, Any], *, fallback: str = "") -> str:
    for key in ("evidence_id", "task_id", "check_id", "id", "key", "name", "probe_id"):
        raw_value = row.get(key)
        if raw_value is None:
            continue
        value = str(raw_value).strip()
        if value:
            return value
    return str(fallback or "").strip()


def _looks_like_evidence_row(row: Mapping[str, Any]) -> bool:
    direct_indicator_keys = {
        "evidence_id",
        "task_id",
        "check_id",
        "track",
        "pass",
        "success",
        "score",
        "quality_score",
    }
    if any(key in row for key in direct_indicator_keys):
        return True
    checks = row.get("checks")
    if not isinstance(checks, Mapping):
        return False
    if _extract_evidence_check_id(row):
        return True
    return any(key in checks for key in ("pass", "success", "passed", "ok", "score", "quality_score"))


def _looks_like_checks_mapping(payload: Mapping[str, Any]) -> bool:
    if not payload or "checks" in payload:
        return False
    meta_keys = {"id", "version", "meta", "metadata", "summary", "suite", "run", "config"}
    keys = [str(key or "").strip().lower() for key in payload.keys()]
    if any(key in meta_keys for key in keys):
        return False
    has_check_like_key = any(("." in key) or key.startswith("prog") for key in keys if key)
    if not has_check_like_key:
        return False
    for value in payload.values():
        if not isinstance(value, Mapping | str | int | float | bool):
            return False
    return True


def _coerce_checks_mapping_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_check_id, raw in payload.items():
        check_id = str(raw_check_id or "").strip()
        if not check_id:
            continue
        row = dict(raw) if isinstance(raw, Mapping) else {"value": raw}
        if not _extract_evidence_check_id(row):
            row["check_id"] = check_id
        rows.append(row)
    return rows


def _coerce_evidence_rows(raw: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if isinstance(raw, Mapping):
        if _looks_like_evidence_row(raw):
            rows.append(dict(raw))
            return rows
        if _looks_like_checks_mapping(raw):
            return _coerce_checks_mapping_rows(raw)
        for key, value in raw.items():
            key_name = str(key or "").strip().lower()
            if key_name in BENCHMARK_EVIDENCE_CONTAINER_KEYS:
                rows.extend(_coerce_evidence_rows(value))
                continue
            if key_name == "tracks" and isinstance(value, Mapping):
                for track_id, raw_rows in value.items():
                    for row in _coerce_evidence_rows(raw_rows):
                        if not row.get("track"):
                            row["track"] = str(track_id)
                        rows.append(row)
                continue
            if key_name == "checks" and isinstance(value, Mapping):
                rows.extend(_coerce_checks_mapping_rows(value))
                continue
            if not isinstance(value, Mapping):
                continue
            row = dict(value)
            if not _extract_evidence_check_id(row):
                row["check_id"] = str(key)
            rows.append(row)
        return rows
    if isinstance(raw, Sequence) and not isinstance(raw, str | bytes | bytearray):
        for item in raw:
            if isinstance(item, Mapping):
                rows.append(dict(item))
        return rows
    return rows


def _extract_evidence_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, Sequence) and not isinstance(payload, str | bytes | bytearray):
        return _coerce_evidence_rows(payload)
    if not isinstance(payload, Mapping):
        return []
    rows: list[dict[str, Any]] = []
    for key in BENCHMARK_EVIDENCE_CONTAINER_KEYS:
        if key in payload:
            rows.extend(_coerce_evidence_rows(payload.get(key)))
    tracks = payload.get("tracks")
    if isinstance(tracks, Mapping):
        for track_id, raw_rows in tracks.items():
            for row in _coerce_evidence_rows(raw_rows):
                if not row.get("track"):
                    row["track"] = str(track_id)
                rows.append(row)
    if rows:
        return rows
    if _looks_like_evidence_row(payload):
        return [dict(payload)]
    return []


def _normalize_evidence_row(
    row: Mapping[str, Any],
    *,
    fallback_check_id: str = "",
) -> tuple[str, dict[str, Any]] | None:
    check_id = _extract_evidence_check_id(row, fallback=fallback_check_id)
    if not check_id:
        return None
    normalized: dict[str, Any] = {}
    pass_value = _extract_evidence_pass(row)
    if pass_value is not None:
        normalized["pass"] = bool(pass_value)
    score_value = _extract_evidence_score(row)
    if score_value is None:
        score_value = _extract_unambiguous_value_score(row)
    if score_value is not None:
        normalized["score"] = float(score_value)
    if pass_value is None and score_value is None and "value" in row:
        normalized["value"] = row.get("value")
    if not normalized:
        return None
    source = _extract_evidence_source(row)
    if source:
        normalized["source"] = source
    notes = _extract_evidence_notes(row)
    if notes:
        normalized["notes"] = notes
    updated_at = _extract_evidence_updated_at(row)
    if updated_at:
        normalized["updated_at_utc"] = updated_at
    return check_id, normalized


def _normalize_checks_payload(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for raw_check_id, raw in payload.items():
        check_id = str(raw_check_id or "").strip()
        if not check_id:
            continue
        row = dict(raw) if isinstance(raw, Mapping) else {"value": raw}
        normalized_row = _normalize_evidence_row(row, fallback_check_id=check_id)
        if not normalized_row:
            continue
        out_check_id, out_row = normalized_row
        merged = dict(normalized.get(out_check_id) or {})
        merged.update(out_row)
        normalized[out_check_id] = merged
    return normalized


def _checks_payload_is_core_compatible(payload: Mapping[str, Any]) -> bool:
    for raw_check_id, raw in payload.items():
        check_id = str(raw_check_id or "").strip()
        if not check_id:
            return False
        if isinstance(raw, Mapping):
            pass_value = raw.get("pass")
            if pass_value is not None and not isinstance(pass_value, bool):
                return False
            score_value = raw.get("score")
            if score_value is not None and _safe_float(score_value) is None:
                return False
            value_field = raw.get("value")
            if value_field is not None and not isinstance(value_field, str | int | float | bool):
                return False
            continue
        if not isinstance(raw, str | int | float | bool):
            return False
    return True


def _rows_payload_is_core_compatible(rows: Sequence[Any], *, aliases: Sequence[str]) -> bool:
    normalized_rows = [row for row in rows if isinstance(row, Mapping)]
    if len(normalized_rows) != len(rows):
        return False
    alias_set = {str(item or "").strip().lower() for item in aliases if str(item or "").strip()}
    has_track_values = any(bool(_extract_evidence_track(dict(row))) for row in normalized_rows)
    for raw_row in normalized_rows:
        row = dict(raw_row)
        check_id = str(row.get("evidence_id") or row.get("task_id") or "").strip()
        if not check_id:
            return False

        pass_value = row.get("pass")
        success_value = row.get("success")
        if pass_value is not None and not isinstance(pass_value, bool):
            return False
        if success_value is not None and not isinstance(success_value, bool):
            return False

        checks = row.get("checks")
        if isinstance(checks, Mapping):
            nested_success = checks.get("success")
            if nested_success is not None and not isinstance(nested_success, bool):
                return False

        if row.get("score") is not None and _safe_float(row.get("score")) is None:
            return False
        if row.get("quality_score") is not None and _safe_float(row.get("quality_score")) is None:
            return False

        has_bool_signal = (
            isinstance(pass_value, bool)
            or isinstance(success_value, bool)
            or (isinstance(checks, Mapping) and isinstance(checks.get("success"), bool))
        )
        has_score_signal = (
            _safe_float(row.get("score")) is not None or _safe_float(row.get("quality_score")) is not None
        )
        if not has_bool_signal and not has_score_signal:
            return False

        track = _extract_evidence_track(row)
        if alias_set and track and track not in alias_set:
            continue
        if alias_set and not track and has_track_values:
            return False
    return True


def _evidence_payload_is_core_compatible(payload: Any, *, aliases: Sequence[str]) -> bool:
    if isinstance(payload, Mapping):
        checks_obj = payload.get("checks")
        if isinstance(checks_obj, Mapping):
            return _checks_payload_is_core_compatible(checks_obj)
        if _looks_like_checks_mapping(payload):
            return _checks_payload_is_core_compatible(payload)
        return False
    if isinstance(payload, Sequence) and not isinstance(payload, str | bytes | bytearray):
        return _rows_payload_is_core_compatible(payload, aliases=aliases)
    return False


def _normalize_evidence_payload_to_checks(
    payload: Any,
    *,
    aliases: Sequence[str],
) -> dict[str, dict[str, Any]]:
    alias_set = {str(item or "").strip().lower() for item in aliases if str(item or "").strip()}
    if isinstance(payload, Mapping):
        checks_obj = payload.get("checks")
        if isinstance(checks_obj, Mapping):
            return _normalize_checks_payload(checks_obj)
        if _looks_like_checks_mapping(payload):
            return _normalize_checks_payload(payload)

    rows = _extract_evidence_rows(payload)
    if not rows:
        return {}
    has_track_values = any(bool(_extract_evidence_track(row)) for row in rows)
    normalized: dict[str, dict[str, Any]] = {}
    for row in rows:
        track = _extract_evidence_track(row)
        if alias_set:
            if track and track not in alias_set:
                continue
            if not track and has_track_values:
                continue
        normalized_row = _normalize_evidence_row(row)
        if not normalized_row:
            continue
        check_id, values = normalized_row
        merged = dict(normalized.get(check_id) or {})
        merged.update(values)
        normalized[check_id] = merged
    return normalized


def _load_json_or_jsonl_payload(path: Path) -> tuple[Any | None, str | None, bool]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return None, f"{path}: {type(exc).__name__}: {exc}", False
    try:
        return json.loads(text), None, False
    except json.JSONDecodeError as json_exc:
        rows: list[Any] = []
        for line in text.splitlines():
            trimmed = line.strip()
            if not trimmed:
                continue
            try:
                rows.append(json.loads(trimmed))
            except Exception:
                return None, f"{path}: JSONDecodeError: {json_exc}", False
        if rows:
            return rows, None, True
        return None, f"{path}: JSONDecodeError: {json_exc}", False
    except Exception as exc:
        return None, f"{path}: {type(exc).__name__}: {exc}", False


def _expand_evidence_glob_variants(pattern: str) -> list[str]:
    text = str(pattern or "").strip()
    if not text:
        return []
    variants = [text]
    replacements = (
        ("benchmark_results.raw.json", "results.raw.json"),
        ("results.raw.json", "benchmark_results.raw.json"),
        ("benchmark_results.json", "results.json"),
        ("results.json", "benchmark_results.json"),
    )
    for source, target in replacements:
        if source in text:
            variants.append(text.replace(source, target))
    if text.endswith(".json"):
        variants.append(text[:-5] + ".jsonl")
        variants.append(text[:-5] + ".ndjson")
    elif text.endswith(".jsonl"):
        variants.append(text[:-6] + ".json")
        variants.append(text[:-6] + ".ndjson")
    elif text.endswith(".ndjson"):
        variants.append(text[:-7] + ".json")
        variants.append(text[:-7] + ".jsonl")
    return _dedupe_keep_order(variants)


def _resolve_glob_matches(patterns: Sequence[str], *, repo_root: Path) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for raw_pattern in patterns:
        pattern = str(raw_pattern or "").strip()
        if not pattern:
            continue
        path = Path(pattern)
        if not path.is_absolute():
            path = (repo_root / pattern).resolve()
        for match in sorted(glob.glob(str(path), recursive=True)):
            entry = Path(match)
            key = str(entry.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(entry)
    return out


def _sanitize_token_for_filename(value: str) -> str:
    token = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in str(value or "").strip())
    token = token.strip("_")
    return token or "agent"


def _normalize_agent_evidence_globs_for_runtime(
    agent: Mapping[str, Any],
    *,
    repo_root: Path,
    temp_dir: Path | None,
) -> tuple[dict[str, Any], bool, Path | None]:
    patterns = _coerce_string_list(agent.get("benchmark_evidence_globs"))
    if not patterns:
        return dict(agent), False, temp_dir

    expanded_patterns: list[str] = []
    for pattern in patterns:
        expanded_patterns.extend(_expand_evidence_glob_variants(pattern))
    expanded_patterns = _dedupe_keep_order(expanded_patterns)
    primary_matches = _resolve_glob_matches(patterns, repo_root=repo_root)
    matches = _resolve_glob_matches(expanded_patterns, repo_root=repo_root)
    if not matches and not primary_matches:
        return dict(agent), False, temp_dir

    aliases = _coerce_string_list(agent.get("benchmark_aliases"))
    aid = str(agent.get("id") or "").strip()
    if aid:
        aliases.append(aid)
    aliases = _dedupe_keep_order(aliases)

    normalization_required = (not primary_matches) and bool(matches)
    checks: dict[str, dict[str, Any]] = {}
    for match in matches:
        payload, _, used_jsonl_fallback = _load_json_or_jsonl_payload(match)
        if payload is None:
            continue
        if used_jsonl_fallback:
            normalization_required = True
        if not _evidence_payload_is_core_compatible(payload, aliases=aliases):
            normalization_required = True
        normalized_checks = _normalize_evidence_payload_to_checks(payload, aliases=aliases)
        for check_id, row in normalized_checks.items():
            merged = dict(checks.get(check_id) or {})
            merged.update(row)
            checks[check_id] = merged

    if not checks:
        return dict(agent), False, temp_dir
    if not normalization_required:
        return dict(agent), False, temp_dir

    target_dir = temp_dir
    if target_dir is None:
        target_dir = Path(tempfile.mkdtemp(prefix="agent-suite-normalized-"))
    normalized_path = target_dir / f"benchmark_evidence.{_sanitize_token_for_filename(aid)}.normalized.json"
    with normalized_path.open("w", encoding="utf-8") as handle:
        json.dump({"checks": checks}, handle, indent=2)
        handle.write("\n")

    normalized_agent = dict(agent)
    normalized_agent["benchmark_evidence_globs"] = [str(normalized_path)]
    changed = normalized_agent.get("benchmark_evidence_globs") != agent.get("benchmark_evidence_globs")
    return normalized_agent, changed, target_dir


def _normalize_suite_evidence_globs_for_runtime(
    payload: Mapping[str, Any],
    *,
    repo_root: Path,
) -> tuple[dict[str, Any], bool, Path | None]:
    normalized = dict(payload)
    agents = normalized.get("agents")
    if not isinstance(agents, list):
        return normalized, False, None

    changed = False
    out_agents: list[Any] = []
    temp_dir: Path | None = None
    for item in agents:
        if not isinstance(item, Mapping):
            out_agents.append(item)
            continue
        normalized_agent, agent_changed, temp_dir = _normalize_agent_evidence_globs_for_runtime(
            item,
            repo_root=repo_root,
            temp_dir=temp_dir,
        )
        out_agents.append(normalized_agent)
        changed = changed or agent_changed

    if changed:
        normalized["agents"] = out_agents
        return normalized, True, temp_dir
    if temp_dir is not None:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return normalized, False, None


def _normalize_agent_benchmark_config(agent: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    normalized = dict(agent)
    changed = False

    aid = str(normalized.get("id") or "").strip()
    aliases: list[str] = []
    for key in BENCHMARK_ALIAS_KEYS:
        aliases.extend(_coerce_string_list(normalized.get(key)))
    if aid:
        aliases.append(aid)
    aliases = _dedupe_keep_order(aliases)
    if normalized.get("benchmark_aliases") != aliases:
        normalized["benchmark_aliases"] = aliases
        changed = True

    for canonical, candidates in BENCHMARK_GLOB_KEYS.items():
        values = _first_present_string_list(normalized, candidates)
        if canonical == "benchmark_evidence_globs" and not values:
            values = _first_present_string_list(normalized, BENCHMARK_GLOB_KEYS["benchmark_raw_globs"])
        if normalized.get(canonical) != values:
            normalized[canonical] = values
            changed = True

    return normalized, changed


def _normalize_suite_config_payload(payload: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
    normalized = dict(payload)
    agents = normalized.get("agents")
    if not isinstance(agents, list):
        return normalized, False

    changed = False
    out_agents: list[Any] = []
    for item in agents:
        if not isinstance(item, Mapping):
            out_agents.append(item)
            continue
        normalized_agent, agent_changed = _normalize_agent_benchmark_config(item)
        out_agents.append(normalized_agent)
        changed = changed or agent_changed

    if changed:
        normalized["agents"] = out_agents
    return normalized, changed


def _prepare_suite_config_for_run(
    suite_config_path: str | Path | None,
    *,
    repo_root: Path = ROOT,
) -> tuple[Path, Path | None]:
    config_path = Path(suite_config_path or DEFAULT_SUITE_CONFIG).expanduser()
    if not config_path.is_absolute():
        config_path = (repo_root / config_path).resolve()

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return config_path, None
    if not isinstance(payload, Mapping):
        return config_path, None

    normalized_payload, config_changed = _normalize_suite_config_payload(payload)
    normalized_payload, evidence_changed, temp_dir = _normalize_suite_evidence_globs_for_runtime(
        normalized_payload,
        repo_root=repo_root,
    )
    changed = bool(config_changed or evidence_changed)
    if not changed:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)
        return config_path, None

    target_dir = temp_dir or Path(tempfile.mkdtemp(prefix="agent-suite-normalized-"))
    temp_path = target_dir / "suite_config.normalized.json"
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(normalized_payload, handle, indent=2)
        handle.write("\n")
    return temp_path, target_dir


def _inject_suite_config(argv: Sequence[str], *, suite_config_path: Path) -> list[str]:
    forwarded: list[str] = []
    skip_next = False
    for token in argv:
        if skip_next:
            skip_next = False
            continue
        text = str(token)
        if text == "--suite-config":
            skip_next = True
            continue
        if text.startswith("--suite-config="):
            continue
        forwarded.append(text)
    forwarded += ["--suite-config", str(suite_config_path)]
    return forwarded


def load_artifact_paths(
    suite_config_path: str | Path | None = None,
    *,
    repo_root: Path = ROOT,
) -> dict[str, Path]:
    config_path = Path(suite_config_path or DEFAULT_SUITE_CONFIG).expanduser()
    if not config_path.is_absolute():
        config_path = (repo_root / config_path).resolve()

    artifact_paths_cfg: dict[str, Any] = {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("artifact_paths"), dict):
            artifact_paths_cfg = dict(payload["artifact_paths"])
    except Exception:
        artifact_paths_cfg = {}

    resolved: dict[str, Path] = {}
    for key, rel_path in DEFAULT_ARTIFACT_PATHS_REL.items():
        resolved[key] = _resolve_repo_path(
            repo_root,
            str(artifact_paths_cfg.get(key) or ""),
            fallback_rel=rel_path,
        )
    return resolved


def _parse_wrapper_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--suite-config", default=None)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--write-path", default=None)
    parser.add_argument("--write-md", action="store_true")
    parser.add_argument("--write-md-path", default=None)
    parser.add_argument("--registry-path", default=None)
    parser.add_argument("--registry-md-path", default=None)
    parser.add_argument("--no-registry-write", action="store_true")
    args, _ = parser.parse_known_args(list(argv))
    return args


def _inject_default_paths(argv: Sequence[str], *, artifact_paths: dict[str, Path]) -> list[str]:
    parsed = _parse_wrapper_args(argv)
    forwarded = list(argv)

    if parsed.write and parsed.write_path is None:
        forwarded += ["--write-path", str(artifact_paths["latest_json"])]
    if parsed.write_md and parsed.write_md_path is None:
        forwarded += ["--write-md-path", str(artifact_paths["latest_markdown"])]
    if (not parsed.no_registry_write) and parsed.registry_path is None:
        forwarded += ["--registry-path", str(artifact_paths["registry_json"])]
    if (not parsed.no_registry_write) and parsed.registry_md_path is None:
        forwarded += ["--registry-md-path", str(artifact_paths["registry_markdown"])]

    return forwarded


def _effective_write_path(parsed: argparse.Namespace) -> Path | None:
    if not bool(parsed.write):
        return None
    return _resolve_repo_path(
        ROOT,
        str(parsed.write_path or ""),
        fallback_rel=DEFAULT_ARTIFACT_PATHS_REL["latest_json"],
    )


def _mirror_legacy_json(
    *,
    source_path: Path,
    canonical_path: Path,
    legacy_path: Path,
) -> None:
    if not source_path.exists():
        return

    source = source_path.resolve()
    canonical = canonical_path.resolve()
    legacy = legacy_path.resolve()
    if canonical == legacy:
        return

    destination: Path | None = None
    if source == canonical:
        destination = legacy_path
    elif source == legacy:
        destination = canonical_path
    if destination is None:
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, destination)


def run(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else list(sys.argv[1:])
    parsed = _parse_wrapper_args(raw_argv)
    suite_config_path, temp_cleanup_path = _prepare_suite_config_for_run(parsed.suite_config or DEFAULT_SUITE_CONFIG)
    artifact_paths = load_artifact_paths(suite_config_path)
    forwarded_argv = _inject_default_paths(raw_argv, artifact_paths=artifact_paths)
    forwarded_argv = _inject_suite_config(forwarded_argv, suite_config_path=suite_config_path)

    try:
        rc = _suite.main(forwarded_argv)
        rc = int(rc) if rc is not None else 0
        if rc != 0:
            return rc

        forwarded_parsed = _parse_wrapper_args(forwarded_argv)
        write_path = _effective_write_path(forwarded_parsed)
        if write_path is not None:
            _mirror_legacy_json(
                source_path=write_path,
                canonical_path=artifact_paths["latest_json"],
                legacy_path=artifact_paths["latest_legacy_json"],
            )
        return 0
    finally:
        if temp_cleanup_path is not None:
            if temp_cleanup_path.is_dir():
                shutil.rmtree(temp_cleanup_path, ignore_errors=True)
            else:
                temp_cleanup_path.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
