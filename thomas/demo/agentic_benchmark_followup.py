from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from thomas.demo.agentic_benchmark_helpers import _merge_usage_rows


def _missing_artifact_contract_items(checks: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    check_rows = dict(checks.get("checks") or {})
    missing_response_mentions: list[str] = []
    missing_files: list[str] = []
    for key, passed in check_rows.items():
        if bool(passed):
            continue
        name = str(key or "")
        if name.startswith("response_contains:"):
            missing_response_mentions.append(name.split(":", 1)[1])
            continue
        if name.startswith("required_file:"):
            missing_files.append(name.split(":", 1)[1])
    return missing_files, missing_response_mentions


def _build_artifact_follow_up_prompt(
    *,
    original_prompt: str,
    missing_files: Sequence[str],
    missing_response_mentions: Sequence[str],
) -> str:
    lines = [str(original_prompt or "").rstrip(), "", "Follow-up: the previous attempt is incomplete."]
    if missing_files:
        lines.append("Required files still missing:")
        lines.extend(f"- {item}" for item in missing_files)
    if missing_response_mentions:
        lines.append("Required final-response mentions still missing:")
        lines.extend(f"- {item}" for item in missing_response_mentions)
    lines.extend(
        [
            "Continue in the same workspace.",
            "Do not re-plan or summarize.",
            "Produce only the missing required artifacts and the required final confirmation now.",
        ]
    )
    return "\n".join(lines).strip()


def _merge_run_attempts(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(current)
    merged["elapsed_seconds"] = round(
        float(previous.get("elapsed_seconds") or 0.0) + float(current.get("elapsed_seconds") or 0.0),
        3,
    )
    merged["tool_calls"] = int(previous.get("tool_calls") or 0) + int(current.get("tool_calls") or 0)
    merged["usage"] = _merge_usage_rows(
        [
            dict(previous.get("usage") or {}),
            dict(current.get("usage") or {}),
        ]
    )
    previous_error = str(previous.get("error") or "").strip()
    current_error = str(current.get("error") or "").strip()
    merged["error"] = "; ".join(part for part in (previous_error, current_error) if part)
    for key in (
        "first_token_seconds",
        "first_text_delta_seconds",
        "first_stream_event_seconds",
        "reported_first_token_ms",
    ):
        merged[key] = previous.get(key) if previous.get(key) is not None else current.get(key)
    merged["setup_elapsed_seconds"] = round(
        float(previous.get("setup_elapsed_seconds") or 0.0) + float(current.get("setup_elapsed_seconds") or 0.0),
        3,
    )
    merged["stream_event_count"] = int(previous.get("stream_event_count") or 0) + int(
        current.get("stream_event_count") or 0
    )
    merged["text_event_count"] = int(previous.get("text_event_count") or 0) + int(current.get("text_event_count") or 0)
    if not str(merged.get("text") or "").strip():
        merged["text"] = str(previous.get("text") or "")
    if not merged.get("token_report"):
        merged["token_report"] = dict(previous.get("token_report") or {})
    return merged
