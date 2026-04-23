from __future__ import annotations

import ast
import json
import math
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

ALLOWED_SUCCESS_KEYS = {
    "response_contains",
    "response_regex",
    "response_python_compiles",
    "response_python_prefix",
    "response_entry_point",
    "required_files",
    "required_file_contains",
    "required_file_regex",
    "check_command",
    "check_timeout_seconds",
}

ALLOWED_COMPETITOR_REQUIREMENT_KEYS = {
    "required_capability_class",
}

ALLOWED_CAPABILITY_CLASSES = {
    "text_only",
    "tool_using_agent",
    "tool_using_multi_agent",
}


def _read_json(path: Path) -> Any:
    raw = path.read_text(encoding="utf-8-sig")
    return json.loads(raw)


def _coerce_str_list(value: Any, *, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list of strings.")
    out: list[str] = []
    for idx, item in enumerate(value, start=1):
        text = str(item or "").strip()
        if not text:
            raise ValueError(f"{field}[{idx}] cannot be empty.")
        out.append(text)
    return out


def _coerce_str_map(value: Any, *, field: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object of string keys/values.")
    out: dict[str, str] = {}
    for k, v in value.items():
        kk = str(k or "").strip()
        vv = str(v or "").strip()
        if not kk:
            raise ValueError(f"{field} has an empty key.")
        if not vv:
            raise ValueError(f"{field}['{kk}'] cannot be empty.")
        out[kk] = vv
    return out


def _normalize_competitor_requirements(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("competitor_requirements must be an object.")
    unknown = sorted(set(value.keys()) - ALLOWED_COMPETITOR_REQUIREMENT_KEYS)
    if unknown:
        raise ValueError("competitor_requirements has unknown keys: " + ", ".join(str(item) for item in unknown))
    required_capability = str(value.get("required_capability_class") or "").strip()
    if required_capability and required_capability not in ALLOWED_CAPABILITY_CLASSES:
        allowed = ", ".join(sorted(ALLOWED_CAPABILITY_CLASSES))
        raise ValueError(f"required_capability_class must be one of: {allowed}")
    out: dict[str, str] = {}
    if required_capability:
        out["required_capability_class"] = required_capability
    return out


def load_agentic_task_pack(path: Path) -> dict[str, Any]:
    data = _read_json(path)
    if not isinstance(data, dict):
        raise ValueError("Task pack must be a JSON object.")

    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Task pack must include a non-empty 'tasks' list.")

    pack_type = str(data.get("type") or "capability").strip() or "capability"
    family = str(data.get("family") or "").strip()
    competitor_requirements = _normalize_competitor_requirements(data.get("competitor_requirements"))
    report_metrics = _coerce_str_list(data.get("report_metrics"), field="report_metrics")

    seen_ids: set[str] = set()
    norm_tasks: list[dict[str, Any]] = []
    for idx, raw_task in enumerate(tasks, start=1):
        if not isinstance(raw_task, dict):
            raise ValueError(f"tasks[{idx}] must be an object.")
        task_id = str(raw_task.get("id") or "").strip()
        title = str(raw_task.get("title") or "").strip()
        prompt = str(raw_task.get("prompt") or "").strip()
        if not task_id:
            raise ValueError(f"tasks[{idx}] is missing id.")
        if task_id in seen_ids:
            raise ValueError(f"Duplicate task id: {task_id}")
        seen_ids.add(task_id)
        if not title:
            raise ValueError(f"Task '{task_id}' is missing title.")
        if not prompt:
            raise ValueError(f"Task '{task_id}' is missing prompt.")

        budget_raw = raw_task.get("time_budget_seconds")
        budget: int | None = None
        if budget_raw is not None:
            try:
                budget = int(budget_raw)
            except Exception as exc:
                raise ValueError(f"Task '{task_id}' has invalid time_budget_seconds.") from exc
            if budget <= 0:
                raise ValueError(f"Task '{task_id}' has non-positive time_budget_seconds.")

        success = raw_task.get("success") or {}
        if not isinstance(success, dict):
            raise ValueError(f"Task '{task_id}' success config must be an object.")
        unknown = sorted(set(success.keys()) - ALLOWED_SUCCESS_KEYS)
        if unknown:
            raise ValueError(f"Task '{task_id}' has unknown success keys: {', '.join(unknown)}")

        norm_tasks.append(
            {
                "id": task_id,
                "title": title,
                "prompt": prompt,
                "success_criteria": str(raw_task.get("success_criteria") or "").strip(),
                "time_budget_seconds": budget,
                "success": {
                    "response_contains": _coerce_str_list(
                        success.get("response_contains"),
                        field=f"tasks[{task_id}].success.response_contains",
                    ),
                    "response_regex": _coerce_str_list(
                        success.get("response_regex"),
                        field=f"tasks[{task_id}].success.response_regex",
                    ),
                    "response_python_compiles": bool(success.get("response_python_compiles", False)),
                    "response_python_prefix": str(success.get("response_python_prefix") or ""),
                    "response_entry_point": str(success.get("response_entry_point") or "").strip(),
                    "required_files": _coerce_str_list(
                        success.get("required_files"),
                        field=f"tasks[{task_id}].success.required_files",
                    ),
                    "required_file_contains": _coerce_str_map(
                        success.get("required_file_contains"),
                        field=f"tasks[{task_id}].success.required_file_contains",
                    ),
                    "required_file_regex": _coerce_str_map(
                        success.get("required_file_regex"),
                        field=f"tasks[{task_id}].success.required_file_regex",
                    ),
                    "check_command": str(success.get("check_command") or "").strip(),
                    "check_timeout_seconds": float(success.get("check_timeout_seconds") or 20.0),
                },
            }
        )

    weights_raw = data.get("weights") or {}
    if not isinstance(weights_raw, dict):
        raise ValueError("weights must be an object.")
    weights = {
        "success_rate": float(weights_raw.get("success_rate", 0.5)),
        "speed": float(weights_raw.get("speed", 0.2)),
        "follow_up": float(weights_raw.get("follow_up", 0.1)),
        "quality": float(weights_raw.get("quality", 0.2)),
    }
    if sum(weights.values()) <= 0:
        raise ValueError("weights must sum to a positive value.")

    scale_raw = data.get("quality_scale") or {}
    if not isinstance(scale_raw, dict):
        raise ValueError("quality_scale must be an object.")
    quality_scale = {
        "min": int(scale_raw.get("min", 1)),
        "max": int(scale_raw.get("max", 5)),
    }
    if quality_scale["min"] >= quality_scale["max"]:
        raise ValueError("quality_scale requires min < max.")

    return {
        "id": str(data.get("id") or path.stem),
        "name": str(data.get("name") or "Agentic Benchmark Pack"),
        "version": int(data.get("version") or 1),
        "type": pack_type,
        "family": family,
        "description": str(data.get("description") or "").strip(),
        "protocol": list(data.get("protocol") or []),
        "competitor_requirements": competitor_requirements,
        "report_metrics": report_metrics,
        "weights": weights,
        "quality_scale": quality_scale,
        "tasks": norm_tasks,
    }


def apply_template_context(value: Any, context: Mapping[str, str]) -> Any:
    if isinstance(value, str):
        out = value
        for key, replacement in context.items():
            out = out.replace("{{" + str(key) + "}}", str(replacement))
        return out
    if isinstance(value, list):
        return [apply_template_context(item, context) for item in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key_text = apply_template_context(str(k), context)
            out[str(key_text)] = apply_template_context(v, context)
        return out
    return value


def render_task(task: Mapping[str, Any], context: Mapping[str, str]) -> dict[str, Any]:
    return apply_template_context(dict(task), context)


def _resolve_path(path_text: str, workspace_root: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return workspace_root / path


def _normalize_usage(payload: Any) -> dict[str, int]:
    if not isinstance(payload, dict):
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    try:
        prompt_tokens = max(0, int(payload.get("prompt_tokens", 0) or 0))
    except (OSError, FileNotFoundError):
        prompt_tokens = 0
    try:
        completion_tokens = max(0, int(payload.get("completion_tokens", 0) or 0))
    except (OSError, FileNotFoundError):
        completion_tokens = 0
    try:
        total_tokens = max(0, int(payload.get("total_tokens", 0) or 0))
    except (OSError, FileNotFoundError):
        total_tokens = prompt_tokens + completion_tokens
    total_tokens = max(total_tokens, prompt_tokens + completion_tokens)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _coerce_positive_int(value: Any) -> int:
    try:
        num = int(value)
    except (ValueError, TypeError):
        return 0
    return max(0, int(num))


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return float(number)


def _extract_usage_from_token_report(token_report: Mapping[str, Any] | None) -> dict[str, int]:
    report = dict(token_report or {})
    usage_like = report.get("usage")
    if isinstance(usage_like, dict):
        report = {**dict(usage_like), **report}

    prompt = 0
    completion = 0
    total = 0
    for key in ("prompt_tokens", "input_tokens", "run_prompt_tokens"):
        prompt = max(prompt, _coerce_positive_int(report.get(key)))
    for key in ("completion_tokens", "output_tokens", "run_completion_tokens"):
        completion = max(completion, _coerce_positive_int(report.get(key)))
    for key in ("total_tokens", "run_total_tokens"):
        total = max(total, _coerce_positive_int(report.get(key)))
    total = max(total, prompt + completion)
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}


def _estimate_text_tokens(text: str) -> int:
    source = str(text or "").strip()
    if not source:
        return 0
    # Lightweight fallback estimate (~4 chars/token) when providers omit usage payloads.
    return max(1, int(math.ceil(len(source) / 4.0)))


def _ensure_usage_telemetry(
    usage_payload: Any,
    *,
    prompt_text: str = "",
    response_text: str = "",
    token_report: Mapping[str, Any] | None = None,
) -> dict[str, int]:
    usage = _normalize_usage(usage_payload)
    if int(usage.get("total_tokens") or 0) > 0:
        return usage

    report_usage = _extract_usage_from_token_report(token_report)
    usage["prompt_tokens"] = max(int(usage.get("prompt_tokens") or 0), int(report_usage["prompt_tokens"]))
    usage["completion_tokens"] = max(
        int(usage.get("completion_tokens") or 0),
        int(report_usage["completion_tokens"]),
    )
    usage["total_tokens"] = max(int(usage.get("total_tokens") or 0), int(report_usage["total_tokens"]))

    if int(usage["prompt_tokens"]) <= 0:
        usage["prompt_tokens"] = _estimate_text_tokens(prompt_text)
    if int(usage["completion_tokens"]) <= 0:
        usage["completion_tokens"] = _estimate_text_tokens(response_text)
    usage["total_tokens"] = max(
        int(usage["total_tokens"]),
        int(usage["prompt_tokens"]) + int(usage["completion_tokens"]),
    )
    return _normalize_usage(usage)


def _select_elapsed_seconds(*, reported_elapsed_ms: Any, fallback_elapsed_seconds: float) -> float:
    reported = _safe_float(reported_elapsed_ms)
    if reported is not None and reported >= 0:
        return round(max(0.0, float(reported) / 1000.0), 3)
    return round(max(0.0, float(fallback_elapsed_seconds)), 3)


def _select_optional_elapsed_seconds(
    *,
    reported_elapsed_ms: Any,
    fallback_elapsed_seconds: float | None,
) -> float | None:
    reported = _safe_float(reported_elapsed_ms)
    if reported is not None and reported >= 0:
        return round(max(0.0, float(reported) / 1000.0), 3)
    if fallback_elapsed_seconds is None:
        return None
    return round(max(0.0, float(fallback_elapsed_seconds)), 3)


def _extract_reported_first_token_ms(
    event_payload: Mapping[str, Any] | None,
    *,
    token_report: Mapping[str, Any] | None = None,
) -> float | None:
    event = dict(event_payload or {})
    report = dict(token_report or {})
    usage_like = report.get("usage")
    if isinstance(usage_like, dict):
        report = {**dict(usage_like), **report}
    keys = (
        "first_token_ms",
        "first_token_latency_ms",
        "ttft_ms",
        "time_to_first_token_ms",
    )
    for key in keys:
        value = _safe_float(event.get(key))
        if value is None:
            value = _safe_float(report.get(key))
        if value is not None and value >= 0:
            return float(value)
    return None


def evaluate_task_success(
    task: Mapping[str, Any],
    *,
    response_text: str,
    workspace_root: Path,
) -> dict[str, Any]:
    success_cfg = dict(task.get("success") or {})
    reasons: list[str] = []
    checks: dict[str, Any] = {}
    response = str(response_text or "")
    response_l = response.lower()

    for needle in success_cfg.get("response_contains", []) or []:
        ok = str(needle).lower() in response_l
        checks[f"response_contains:{needle}"] = bool(ok)
        if not ok:
            reasons.append(f"response missing expected text: {needle}")

    for pattern in success_cfg.get("response_regex", []) or []:
        ok = bool(re.search(str(pattern), response, re.IGNORECASE | re.MULTILINE))
        checks[f"response_regex:{pattern}"] = bool(ok)
        if not ok:
            reasons.append(f"response regex not matched: {pattern}")

    compile_requested = bool(success_cfg.get("response_python_compiles", False))
    compile_source = ""
    compile_ok = False
    if compile_requested:
        compile_prefix = str(success_cfg.get("response_python_prefix") or "")
        compile_source = f"{compile_prefix}{response}"
        try:
            compile(compile_source, "<agentic_benchmark_response>", "exec")
            compile_ok = True
        except Exception as exc:
            checks["response_python_compiles_error"] = f"{type(exc).__name__}: {exc}"
        checks["response_python_compiles"] = bool(compile_ok)
        if not compile_ok:
            reasons.append("response failed python compile check")

    entry_point = str(success_cfg.get("response_entry_point") or "").strip()
    if entry_point:
        entry_ok = False
        if compile_ok:
            try:
                module = ast.parse(compile_source)
                entry_ok = any(
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == entry_point
                    for node in ast.walk(module)
                )
            except (ValueError, TypeError):
                entry_ok = False
        else:
            entry_ok = bool(re.search(rf"(?m)^\s*def\s+{re.escape(entry_point)}\s*\(", response))
        checks[f"response_entry_point:{entry_point}"] = bool(entry_ok)
        if not entry_ok:
            reasons.append(f"response missing expected entry point: {entry_point}")

    for rel in success_cfg.get("required_files", []) or []:
        target = _resolve_path(str(rel), workspace_root)
        ok = target.exists()
        checks[f"required_file:{rel}"] = bool(ok)
        if not ok:
            reasons.append(f"required file not found: {rel}")

    for rel, needle in (success_cfg.get("required_file_contains", {}) or {}).items():
        target = _resolve_path(str(rel), workspace_root)
        ok = False
        if target.exists():
            try:
                body = target.read_text(encoding="utf-8", errors="ignore")
                ok = str(needle) in body
            except (OSError, FileNotFoundError):
                ok = False
        checks[f"required_file_contains:{rel}"] = bool(ok)
        if not ok:
            reasons.append(f"required file missing expected text: {rel}")

    for rel, pattern in (success_cfg.get("required_file_regex", {}) or {}).items():
        target = _resolve_path(str(rel), workspace_root)
        ok = False
        if target.exists():
            try:
                body = target.read_text(encoding="utf-8", errors="ignore")
                ok = bool(re.search(str(pattern), body, re.IGNORECASE | re.MULTILINE))
            except (OSError, FileNotFoundError):
                ok = False
        checks[f"required_file_regex:{rel}"] = bool(ok)
        if not ok:
            reasons.append(f"required file regex not matched: {rel}")

    check_command = str(success_cfg.get("check_command") or "").strip()
    if check_command:
        timeout_s = float(success_cfg.get("check_timeout_seconds") or 20.0)
        try:
            proc = subprocess.run(
                check_command,
                shell=True,
                cwd=str(workspace_root),
                capture_output=True,
                text=True,
                timeout=max(1.0, timeout_s),
            )
            ok = int(proc.returncode) == 0
            checks["check_command"] = bool(ok)
            checks["check_command_stdout"] = str(proc.stdout or "")[:1200]
            checks["check_command_stderr"] = str(proc.stderr or "")[:1200]
            if not ok:
                reasons.append(f"check command failed: {check_command}")
        except Exception as exc:
            checks["check_command"] = False
            checks["check_command_error"] = f"{type(exc).__name__}: {exc}"
            reasons.append(f"check command error: {type(exc).__name__}")

    return {
        "success": len(reasons) == 0,
        "reasons": reasons,
        "checks": checks,
    }


def _harness_pack(task_pack: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(task_pack.get("id") or "agentic-pack"),
        "name": str(task_pack.get("name") or "Agentic Benchmark Pack"),
        "version": int(task_pack.get("version") or 1),
        "description": str(task_pack.get("description") or ""),
        "protocol": list(task_pack.get("protocol") or []),
        "weights": dict(task_pack.get("weights") or {}),
        "quality_scale": dict(task_pack.get("quality_scale") or {"min": 1, "max": 5}),
        "tasks": [
            {
                "id": str(t.get("id") or ""),
                "title": str(t.get("title") or ""),
                "prompt": str(t.get("prompt") or ""),
                "success_criteria": str(t.get("success_criteria") or ""),
                "time_budget_seconds": t.get("time_budget_seconds"),
            }
            for t in (task_pack.get("tasks") or [])
        ],
    }


def compute_before_after_delta(
    summary: Mapping[str, Any],
    *,
    baseline_name: str,
    thomas_name: str,
) -> dict[str, Any]:
    competitors = dict(summary.get("competitors") or {})
    baseline = dict(competitors.get(baseline_name) or {})
    after = dict(competitors.get(thomas_name) or {})
    if not baseline or not after:
        return {}
    return {
        "baseline": baseline_name,
        "after": thomas_name,
        "metrics": {
            "weighted_score_delta": round(
                float(after.get("weighted_score", 0.0)) - float(baseline.get("weighted_score", 0.0)),
                3,
            ),
            "success_rate_delta": round(
                float(after.get("success_rate", 0.0)) - float(baseline.get("success_rate", 0.0)),
                6,
            ),
            "avg_elapsed_seconds_delta": round(
                float(after.get("avg_elapsed_seconds", 0.0)) - float(baseline.get("avg_elapsed_seconds", 0.0)),
                3,
            ),
            "evidence_coverage_delta": round(
                float(after.get("evidence_coverage", 0.0)) - float(baseline.get("evidence_coverage", 0.0)),
                6,
            ),
        },
    }


__all__ = [
    "apply_template_context",
    "compute_before_after_delta",
    "evaluate_task_success",
    "load_agentic_task_pack",
    "render_task",
    "_ensure_usage_telemetry",
    "_estimate_text_tokens",
    "_extract_reported_first_token_ms",
    "_extract_usage_from_token_report",
    "_harness_pack",
    "_normalize_usage",
    "_safe_float",
    "_select_elapsed_seconds",
    "_select_optional_elapsed_seconds",
]
