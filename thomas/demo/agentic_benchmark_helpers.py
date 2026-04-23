"""Helper functions for agentic benchmark pipeline."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from contextlib import suppress
from typing import Any

from thomas.core.benchmark_lane import BENCHMARK_RUN_ID_ENV
from thomas.core.config import AppConfig
from thomas.core.llm import LLMClient
from thomas.demo.agentic_benchmark_core import _ensure_usage_telemetry

_CODING_HINT_RE = re.compile(
    r"\b(code|coding|bug|fix|refactor|function|class|module|repo|commit|"
    r"tests?|api|endpoint|traceback|stack trace|python|javascript|typescript)\b",
    re.I,
)
_CODE_SHAPE_RE = re.compile(
    r"(^|\n)\s*(def\s+\w+\s*\(|class\s+\w+\s*[\(:]|import\s+\w+|from\s+\w+\s+import\s+|"
    r"function\s+\w+\s*\(|const\s+\w+\s*=|let\s+\w+\s*=|var\s+\w+\s*=|#include\s+<)",
    re.I,
)
_LOW_CONFIDENCE_RE = re.compile(
    r"\b("
    r"not sure|unsure|uncertain|might be wrong|could be wrong|probably wrong|"
    r"i think|maybe|guess|not confident|can't guarantee|cannot guarantee|"
    r"as an ai|might fail|might not work"
    r")\b",
    re.I,
)
_ERROR_SIGNAL_RE = re.compile(
    r"\b(traceback|exception|error:|failed|failure|cannot|can't)\b",
    re.I,
)
BENCHMARK_ALLOW_CODING_PIPELINE_ENV = "THOMAS_BENCHMARK_ALLOW_CODING_PIPELINE"


def _watch_line(enabled: bool, message: str) -> None:
    if enabled:
        print(message, flush=True)


def _watch_text(enabled: bool, text: str) -> None:
    if enabled and text:
        sys.stdout.write(text)
        sys.stdout.flush()


async def _chat_json_lane(
    config: AppConfig,
    *,
    profile: str,
    system_prompt: str,
    user_prompt: str,
    watch: bool = False,
    watch_prefix: str = "",
) -> dict[str, Any]:
    model_cfg = config.get_model(profile)
    llm = LLMClient(model_cfg, fallback_configs=[], failover_enabled=False)
    started = time.monotonic()
    text = ""
    error = ""
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    try:
        _watch_line(watch, f"{watch_prefix} lane request started")
        resp = await llm.chat(
            [
                {"role": "system", "content": str(system_prompt or "")},
                {"role": "user", "content": str(user_prompt or "")},
            ],
            tools=None,
        )
        text = str(resp.get("text") or "")
        usage = _ensure_usage_telemetry(
            resp.get("usage"),
            prompt_text=f"{system_prompt}\n\n{user_prompt}",
            response_text=text,
        )
        _watch_line(watch, f"{watch_prefix} lane request completed")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        _watch_line(watch, f"{watch_prefix} lane error: {error}")
    finally:
        await llm.close()
    return {
        "ok": not bool(error),
        "text": text,
        "error": error,
        "usage": usage,
        "elapsed_seconds": round(max(0.0, time.monotonic() - started), 3),
    }


def _pass_budget_for_mode(mode: str) -> int:
    run_mode = str(mode or "").strip().lower()
    if run_mode == "fast":
        return 1
    if run_mode == "thinking":
        return 3
    return 2


def _should_use_coding_pipeline(*, job_type: str, prompt: str) -> bool:
    benchmark_run_id = str(os.environ.get(BENCHMARK_RUN_ID_ENV, "")).strip()
    allow_benchmark_pipeline = str(os.environ.get(BENCHMARK_ALLOW_CODING_PIPELINE_ENV, "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if benchmark_run_id and not allow_benchmark_pipeline:
        return False
    kind = str(job_type or "").strip().lower()
    if kind == "benchmark":
        return False
    if kind in {"coding", "code", "debug", "debug_audit"}:
        return True
    return bool(_CODING_HINT_RE.search(str(prompt or "")))


def _pipeline_topology(token_economy: str) -> str:
    economy = str(token_economy or "").strip().lower()
    if economy == "cheap":
        return "coder_only"
    if economy == "max":
        return "coder_reviewer_parallel_conditional_fixer"
    return "coder_reviewer_conditional_fixer"


def _extract_primary_code_text(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    fence_match = re.search(r"```(?:[a-zA-Z0-9_+-]+)?\s*\n(?P<body>[\s\S]*?)```", raw)
    if fence_match:
        body = str(fence_match.group("body") or "").strip()
        if body:
            return body
    return raw


def _looks_like_code(text: str) -> bool:
    candidate = _extract_primary_code_text(text)
    if not candidate:
        return False
    if bool(_CODE_SHAPE_RE.search(candidate)):
        return True
    lines = [str(line).strip() for line in candidate.splitlines() if str(line).strip()]
    if not lines:
        return False
    starts = (
        "def ",
        "class ",
        "import ",
        "from ",
        "return ",
        "for ",
        "while ",
        "if ",
        "elif ",
        "else:",
        "try:",
        "except ",
        "with ",
        "const ",
        "let ",
        "var ",
        "function ",
        "public ",
        "private ",
        "protected ",
        "#include ",
    )
    if any(line.startswith(starts) for line in lines[:20]):
        return True
    punctuation = sum(candidate.count(ch) for ch in "{}();[]=<>:")
    return bool(punctuation >= 6 and len(lines) >= 2)


def _review_decision_for_candidate(
    *,
    candidate_text: str,
    prompt: str,
    mode: str,
    token_economy: str,
) -> dict[str, Any]:
    economy = str(token_economy or "").strip().lower()
    run_mode = str(mode or "").strip().lower()
    raw = str(candidate_text or "")
    normalized = raw.strip()
    if economy == "cheap":
        return {"required": False, "reason": "cheap_topology"}
    if run_mode == "fast":
        return {"required": False, "reason": "fast_mode"}
    if not normalized:
        return {"required": True, "reason": "empty_candidate"}
    if raw.count("```") % 2 == 1:
        return {"required": True, "reason": "unbalanced_code_fence"}
    if bool(_LOW_CONFIDENCE_RE.search(normalized)):
        return {"required": True, "reason": "low_confidence_language"}
    if bool(_ERROR_SIGNAL_RE.search(normalized)):
        return {"required": True, "reason": "error_signal_in_candidate"}
    if not _looks_like_code(normalized) and bool(_CODING_HINT_RE.search(str(prompt or ""))):
        return {"required": True, "reason": "candidate_not_code_like"}
    return {"required": False, "reason": "coder_output_looks_healthy"}


def _merge_usage_rows(rows: list[dict[str, int]]) -> dict[str, int]:
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        with suppress(ValueError, TypeError):
            prompt_tokens += max(0, int(row.get("prompt_tokens", 0) or 0))
        with suppress(ValueError, TypeError):
            completion_tokens += max(0, int(row.get("completion_tokens", 0) or 0))
        with suppress(ValueError, TypeError):
            total_tokens += max(0, int(row.get("total_tokens", 0) or 0))
    if total_tokens <= 0:
        total_tokens = max(0, int(prompt_tokens + completion_tokens))
    return {
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
        "total_tokens": int(total_tokens),
    }


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    snippet = raw[start : end + 1]
    try:
        parsed = json.loads(snippet)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None


def _parse_reviewer_verdict(text: str) -> dict[str, Any]:
    obj = _extract_json_object(text)
    issues: list[str] = []
    summary = ""
    passed = True
    if isinstance(obj, dict):
        summary = str(obj.get("summary") or obj.get("rationale") or "").strip()
        raw_issues = obj.get("issues")
        if isinstance(raw_issues, list):
            issues = [str(x).strip() for x in raw_issues if str(x).strip()]
        elif isinstance(raw_issues, str) and raw_issues.strip():
            issues = [raw_issues.strip()]
        if "pass" in obj:
            try:
                passed = bool(obj.get("pass"))
            except (ValueError, TypeError):
                passed = len(issues) == 0
        elif "passed" in obj:
            try:
                passed = bool(obj.get("passed"))
            except (ValueError, TypeError):
                passed = len(issues) == 0
        elif "status" in obj:
            status = str(obj.get("status") or "").strip().lower()
            if status in {"pass", "ok", "good", "approved"}:
                passed = True
            elif status in {"fail", "failed", "bad", "reject"}:
                passed = False
    if not summary:
        summary = str(text or "").strip()[:240]
    if not issues:
        low = str(text or "").lower()
        if any(k in low for k in ("incorrect", "bug", "edge case", "fails", "failure", "wrong")):
            passed = False
            issues = ["reviewer flagged potential correctness issues"]
    if not issues and not passed:
        issues = ["reviewer did not approve the candidate code"]
    if issues and passed:
        passed = False
    return {"pass": bool(passed), "issues": issues, "summary": summary}


def _extract_revised_code(text: str) -> str:
    obj = _extract_json_object(text)
    if isinstance(obj, dict):
        for key in ("revised_code", "code", "output", "draft"):
            value = str(obj.get(key) or "").strip()
            if value:
                return value
    raw = str(text or "").strip()
    if not raw:
        return ""
    fence_match = re.search(r"```(?:[a-zA-Z0-9_+-]+)?\s*\n(?P<body>[\s\S]*?)```", raw)
    if fence_match:
        return str(fence_match.group("body") or "").strip()
    return raw


__all__ = [
    "_chat_json_lane",
    "_extract_json_object",
    "_extract_primary_code_text",
    "_extract_revised_code",
    "_looks_like_code",
    "_merge_usage_rows",
    "_parse_reviewer_verdict",
    "_pass_budget_for_mode",
    "_pipeline_topology",
    "_review_decision_for_candidate",
    "_should_use_coding_pipeline",
    "_watch_line",
    "_watch_text",
]
