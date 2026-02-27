from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import re
import sys
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import httpx
except ImportError:
    from thomas._vendor import httpx_shim as httpx  # type: ignore[assignment]

from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, load_config
from thomas.core.llm import LLMClient
from thomas.demo.agentic_benchmark_core import (
    _ensure_usage_telemetry,
    _estimate_text_tokens,
    _extract_reported_first_token_ms,
    _extract_usage_from_token_report,
    _harness_pack,
    _normalize_usage,
    _safe_float,
    _select_elapsed_seconds,
    _select_optional_elapsed_seconds,
    apply_template_context,
    compute_before_after_delta,
    evaluate_task_success,
    load_agentic_task_pack,
    render_task,
)
from thomas.demo.harness import (
    build_execution_plan,
    compute_summary,
    write_run_artifacts,
)
from thomas.tools.code_search import register_code_search_tools
from thomas.tools.diff import register_diff_tools
from thomas.tools.filesystem import register_filesystem_tools
from thomas.tools.git import register_git_tools
from thomas.tools.registry import ToolRegistry
from thomas.tools.shell import register_shell_tools
from thomas.tools.ssh import register_ssh_tools

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TASK_PACK = ROOT / "demo" / "task_pack.agentic.local.json"
DEFAULT_RUNS_DIR = ROOT / "demo" / "agentic-runs"
DEFAULT_SYSTEM_PROMPT = (
    "You are a baseline assistant. Do not claim to have executed tools unless you actually can. "
    "Respond concisely and truthfully."
)
__all__ = [
    "apply_template_context",
    "compute_before_after_delta",
    "evaluate_task_success",
    "load_agentic_task_pack",
    "main",
    "parse_args",
    "render_task",
    "run_agentic_benchmark",
    "_ensure_usage_telemetry",
    "_estimate_text_tokens",
    "_extract_reported_first_token_ms",
    "_extract_usage_from_token_report",
    "_resolve_config_path",
    "_run_thomas_api_task",
    "_safe_float",
    "_select_elapsed_seconds",
    "_select_optional_elapsed_seconds",
]


def _watch_line(enabled: bool, message: str) -> None:
    if enabled:
        print(message, flush=True)


def _watch_text(enabled: bool, text: str) -> None:
    if enabled and text:
        sys.stdout.write(text)
        sys.stdout.flush()


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_config_path(config_arg: str) -> Path | None:
    text = str(config_arg or "").strip()
    if text:
        return Path(text).resolve()
    env_path = str(os.environ.get("THOMAS_CONFIG", "")).strip()
    if env_path:
        return None
    repo_default = ROOT / "thomas.toml"
    if repo_default.exists():
        return repo_default.resolve()
    return None


def _build_tools(config: AppConfig) -> ToolRegistry:
    registry = ToolRegistry()
    sandbox = config.tools.sandbox_path
    register_filesystem_tools(registry, sandbox, config.tools.max_file_size)
    if config.tools.allow_shell:
        register_shell_tools(
            registry,
            sandbox,
            config_timeout=config.tools.shell_timeout,
            allowed=True,
        )
    register_git_tools(registry, sandbox)
    register_code_search_tools(registry, sandbox)
    register_diff_tools(registry, sandbox)
    register_ssh_tools(registry)
    return registry


@dataclass
class TrackSpec:
    name: str
    kind: str  # raw | thomas
    profile: str
    mode: str = "auto"
    token_economy: str = "optimal"
    max_iterations: int | None = None


async def _run_raw_task(
    config: AppConfig,
    *,
    profile: str,
    prompt: str,
    watch: bool = False,
    watch_prefix: str = "",
) -> dict[str, Any]:
    model_cfg = config.get_model(profile)
    llm = LLMClient(model_cfg, fallback_configs=[], failover_enabled=False)
    started = time.monotonic()
    text = ""
    usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    error = ""
    try:
        _watch_line(watch, f"{watch_prefix} raw model request started")
        response = await llm.chat(
            [
                {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
                {"role": "user", "content": str(prompt or "")},
            ],
            tools=None,
        )
        text = str(response.get("text") or "")
        usage = _ensure_usage_telemetry(
            response.get("usage"),
            prompt_text=str(prompt or ""),
            response_text=text,
        )
        _watch_line(watch, f"{watch_prefix} raw model request completed")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        _watch_line(watch, f"{watch_prefix} raw model error: {error}")
    finally:
        await llm.close()
    elapsed = max(0.0, time.monotonic() - started)
    return {
        "ok": not bool(error),
        "text": text,
        "error": error,
        "usage": usage,
        "tool_calls": 0,
        "elapsed_seconds": round(elapsed, 3),
    }


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


def _pass_budget_for_mode(mode: str) -> int:
    run_mode = str(mode or "").strip().lower()
    if run_mode == "fast":
        return 1
    if run_mode == "thinking":
        return 3
    return 2


def _should_use_coding_pipeline(*, job_type: str, prompt: str) -> bool:
    kind = str(job_type or "").strip().lower()
    if kind in {"coding", "benchmark", "code", "debug", "debug_audit"}:
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
    if punctuation >= 6 and len(lines) >= 2:
        return True
    return False


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
        try:
            prompt_tokens += max(0, int(row.get("prompt_tokens", 0) or 0))
        except (ValueError, TypeError):
            pass
        try:
            completion_tokens += max(0, int(row.get("completion_tokens", 0) or 0))
        except (ValueError, TypeError):
            pass
        try:
            total_tokens += max(0, int(row.get("total_tokens", 0) or 0))
        except (ValueError, TypeError):
            pass
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


async def _run_single_agent_lane(
    config: AppConfig,
    *,
    profile: str,
    prompt: str,
    mode: str,
    token_economy: str,
    max_iterations: int | None,
    tools_policy: str,
    job_type: str,
    watch: bool,
    watch_prefix: str,
    text_delta_hook: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    model_cfg = config.get_model(profile)
    llm = LLMClient(model_cfg, fallback_configs=[], failover_enabled=False)
    tools = _build_tools(config)
    agent = AgentLoop(
        config,
        llm,
        tools,
        conversation=[],
        memory=None,
        thread_id=f"bench-{int(time.time() * 1000)}",
    )
    started = time.monotonic()
    text_parts: list[str] = []
    final_text = ""
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    tool_calls = 0
    token_report: dict[str, Any] = {}
    error = ""
    try:
        run_kwargs: dict[str, Any] = {
            "mode": str(mode),
            "tools_policy": str(tools_policy or "auto"),
            "token_economy": str(token_economy),
            "job_type": str(job_type or "coding"),
        }
        if max_iterations is not None:
            run_kwargs["max_iterations"] = int(max_iterations)

        async for event in agent.run(str(prompt or ""), **run_kwargs):
            et = str(getattr(event.type, "value", ""))
            if et == "text_delta":
                chunk = str(event.data.get("text") or "")
                text_parts.append(chunk)
                _watch_text(watch, chunk)
                if text_delta_hook is not None and chunk:
                    maybe = text_delta_hook(chunk)
                    if inspect.isawaitable(maybe):
                        await maybe  # type: ignore[arg-type]
            elif et == "tool_call_start":
                _watch_line(
                    watch,
                    f"\n{watch_prefix} tool_start: {event.data.get('tool_name', '')}",
                )
            elif et == "tool_result":
                _watch_line(
                    watch,
                    f"\n{watch_prefix} tool_result: {event.data.get('tool_name', '')} ok={bool(event.data.get('ok', False))}",
                )
            elif et == "agent_error":
                error = str(event.data.get("error") or "unknown error")
                _watch_line(watch, f"\n{watch_prefix} agent_error: {error}")
            elif et == "agent_done":
                final_text = str(event.data.get("text") or "")
                usage = _normalize_usage(event.data.get("usage"))
                tool_calls = int(event.data.get("tool_calls") or 0)
                token_report = dict(event.data.get("token_report") or {})
                _watch_line(
                    watch,
                    f"\n{watch_prefix} done: iterations={event.data.get('iterations')} tools={tool_calls}",
                )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        _watch_line(watch, f"\n{watch_prefix} runner_exception: {error}")
    finally:
        await llm.close()

    if not final_text:
        final_text = "".join(text_parts).strip("\n")
    usage = _ensure_usage_telemetry(
        usage,
        prompt_text=str(prompt or ""),
        response_text=final_text,
        token_report=token_report,
    )
    return {
        "ok": not bool(error),
        "text": final_text,
        "error": error,
        "usage": usage,
        "tool_calls": int(tool_calls),
        "token_report": token_report,
        "elapsed_seconds": round(max(0.0, time.monotonic() - started), 3),
    }


async def _run_thomas_embedded_task(
    config: AppConfig,
    *,
    profile: str,
    prompt: str,
    mode: str,
    token_economy: str,
    max_iterations: int | None,
    tools_policy: str = "auto",
    job_type: str = "coding",
    watch: bool = False,
    watch_prefix: str = "",
) -> dict[str, Any]:
    if mode == "swarm":
        raise ValueError("Embedded runner does not support mode=swarm. Use --thomas-runner api.")
    started = time.monotonic()
    topology = _pipeline_topology(token_economy)
    pass_budget = _pass_budget_for_mode(mode)
    coding_pipeline_enabled = _should_use_coding_pipeline(
        job_type=str(job_type or ""),
        prompt=str(prompt or ""),
    )
    if not coding_pipeline_enabled:
        coder_only = await _run_single_agent_lane(
            config,
            profile=profile,
            prompt=prompt,
            mode=mode,
            token_economy=token_economy,
            max_iterations=max_iterations,
            tools_policy=tools_policy,
            job_type=job_type,
            watch=watch,
            watch_prefix=watch_prefix,
        )
        token_report = dict(coder_only.get("token_report") or {})
        token_report["pipeline"] = {
            "enabled": False,
            "reason": "non_coding_task",
            "topology": "single_agent",
        }
        coder_only["token_report"] = token_report
        coder_only["elapsed_seconds"] = round(max(0.0, time.monotonic() - started), 3)
        return coder_only

    lane_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []
    lane_errors: list[str] = []
    stream_meta: dict[str, Any] = {
        "enabled": bool(topology == "coder_reviewer_parallel_conditional_fixer"),
        "chunks": 0,
        "chars": 0,
        "lines": 0,
    }
    streamed_text_parts: list[str] = []
    stream_queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def _stream_consumer() -> None:
        while True:
            item = await stream_queue.get()
            if item is None:
                break
            chunk = str(item or "")
            if not chunk:
                continue
            streamed_text_parts.append(chunk)
            stream_meta["chunks"] = int(stream_meta.get("chunks", 0) or 0) + 1
            stream_meta["chars"] = int(stream_meta.get("chars", 0) or 0) + len(chunk)
            stream_meta["lines"] = int(stream_meta.get("lines", 0) or 0) + chunk.count("\n")

    consumer_task: asyncio.Task | None = None
    text_hook: Callable[[str], Awaitable[None]] | None = None
    if topology == "coder_reviewer_parallel_conditional_fixer":
        consumer_task = asyncio.create_task(_stream_consumer())

        async def _enqueue_chunk(chunk: str) -> None:
            await stream_queue.put(str(chunk or ""))

        text_hook = _enqueue_chunk

    coder = await _run_single_agent_lane(
        config,
        profile=profile,
        prompt=prompt,
        mode=mode,
        token_economy=token_economy,
        max_iterations=max_iterations,
        tools_policy=tools_policy,
        job_type=job_type,
        watch=watch,
        watch_prefix=watch_prefix,
        text_delta_hook=text_hook,
    )
    lane_rows.append(
        {
            "lane": "coder",
            "ok": bool(coder.get("ok")),
            "elapsed_seconds": float(coder.get("elapsed_seconds") or 0.0),
            "tool_calls": int(coder.get("tool_calls") or 0),
        }
    )
    if str(coder.get("error") or "").strip():
        lane_errors.append(str(coder.get("error") or "").strip())

    if consumer_task is not None:
        await stream_queue.put(None)
        await consumer_task

    current_text = str(coder.get("text") or "")
    if streamed_text_parts:
        streamed_text = "".join(streamed_text_parts).strip("\n")
        if streamed_text:
            current_text = streamed_text
    usage_rows = [dict(coder.get("usage") or {})]
    tool_calls = int(coder.get("tool_calls") or 0)
    token_report: dict[str, Any] = dict(coder.get("token_report") or {})
    review_decision: dict[str, Any] = {
        "required": False,
        "reason": "topology_coder_only" if topology == "coder_only" else "review_not_requested",
    }
    if not bool(coder.get("ok")) or not str(current_text or "").strip():
        review_decision = {"required": False, "reason": "coder_failure_or_empty"}
        token_report["pipeline"] = {
            "enabled": True,
            "topology": topology,
            "pass_budget": int(pass_budget),
            "review_triggered": False,
            "review_trigger_reason": str(review_decision.get("reason") or ""),
            "review_rounds": review_rows,
            "lane_rows": lane_rows,
            "lane_errors": lane_errors,
            "stream": stream_meta,
            "early_exit": "coder_failure_or_empty",
        }
        usage = _ensure_usage_telemetry(
            _merge_usage_rows(usage_rows),
            prompt_text=str(prompt or ""),
            response_text=str(current_text or ""),
            token_report=token_report,
        )
        return {
            "ok": bool(coder.get("ok")) and bool(str(current_text or "").strip()),
            "text": str(current_text or ""),
            "error": str(coder.get("error") or ""),
            "usage": usage,
            "tool_calls": int(tool_calls),
            "token_report": token_report,
            "elapsed_seconds": round(max(0.0, time.monotonic() - started), 3),
        }

    if topology != "coder_only":
        review_decision = _review_decision_for_candidate(
            candidate_text=str(current_text or ""),
            prompt=str(prompt or ""),
            mode=str(mode or ""),
            token_economy=str(token_economy or ""),
        )
    if topology != "coder_only" and bool(review_decision.get("required")):
        for review_round in range(1, int(pass_budget) + 1):
            review_prompt = (
                "Review this candidate code for correctness relative to the task.\n"
                "Return JSON with keys: pass (bool), issues (array of short strings), summary (string).\n"
                "Be strict about edge cases and wrong complexity.\n\n"
                f"Task:\n{prompt}\n\nCandidate code:\n{current_text}\n"
            )
            reviewer_lane = await _chat_json_lane(
                config,
                profile=profile,
                system_prompt=(
                    "You are a strict code reviewer. Output only compact JSON: "
                    '{"pass": <bool>, "issues": [..], "summary": "..."}.'
                ),
                user_prompt=review_prompt,
                watch=watch,
                watch_prefix=f"{watch_prefix} reviewer[{review_round}]",
            )
            usage_rows.append(dict(reviewer_lane.get("usage") or {}))
            verdict = _parse_reviewer_verdict(str(reviewer_lane.get("text") or ""))
            reviewer_ok = bool(reviewer_lane.get("ok"))
            passed = bool(verdict.get("pass")) if reviewer_ok else True
            issues = list(verdict.get("issues") or [])
            summary = str(verdict.get("summary") or "")
            if str(reviewer_lane.get("error") or "").strip():
                lane_errors.append(str(reviewer_lane.get("error") or "").strip())
            review_row = {
                "round": int(review_round),
                "passed": bool(passed),
                "issues": issues,
                "summary": summary,
                "reviewer_ok": reviewer_ok,
                "reviewer_elapsed_seconds": float(reviewer_lane.get("elapsed_seconds") or 0.0),
            }
            review_rows.append(review_row)
            lane_rows.append(
                {
                    "lane": f"reviewer_{review_round}",
                    "ok": reviewer_ok,
                    "elapsed_seconds": float(reviewer_lane.get("elapsed_seconds") or 0.0),
                    "tool_calls": 0,
                }
            )
            if passed or review_round >= int(pass_budget):
                break

            fix_prompt = (
                "Revise the candidate code to resolve the reviewer issues.\n"
                "Return JSON with keys: revised_code (string), change_summary (string).\n\n"
                f"Task:\n{prompt}\n\nCurrent code:\n{current_text}\n\nIssues:\n{issues}\n"
            )
            fixer_lane = await _chat_json_lane(
                config,
                profile=profile,
                system_prompt=(
                    "You are a coding fixer. Output only compact JSON: "
                    '{"revised_code": "...", "change_summary": "..."}.'
                ),
                user_prompt=fix_prompt,
                watch=watch,
                watch_prefix=f"{watch_prefix} fixer[{review_round}]",
            )
            usage_rows.append(dict(fixer_lane.get("usage") or {}))
            lane_rows.append(
                {
                    "lane": f"fixer_{review_round}",
                    "ok": bool(fixer_lane.get("ok")),
                    "elapsed_seconds": float(fixer_lane.get("elapsed_seconds") or 0.0),
                    "tool_calls": 0,
                }
            )
            if str(fixer_lane.get("error") or "").strip():
                lane_errors.append(str(fixer_lane.get("error") or "").strip())
            revised_code = _extract_revised_code(str(fixer_lane.get("text") or ""))
            if revised_code.strip():
                current_text = revised_code
                review_row["fix_applied"] = True
            else:
                review_row["fix_applied"] = False

    token_report["pipeline"] = {
        "enabled": True,
        "topology": topology,
        "pass_budget": int(pass_budget),
        "review_triggered": bool(review_decision.get("required")),
        "review_trigger_reason": str(review_decision.get("reason") or ""),
        "review_rounds": review_rows,
        "lane_rows": lane_rows,
        "lane_errors": lane_errors,
        "stream": stream_meta,
        "final_text_chars": len(str(current_text or "")),
    }
    usage = _ensure_usage_telemetry(
        _merge_usage_rows(usage_rows),
        prompt_text=str(prompt or ""),
        response_text=str(current_text or ""),
        token_report=token_report,
    )
    return {
        "ok": bool(str(current_text or "").strip()),
        "text": str(current_text or ""),
        "error": "; ".join([e for e in lane_errors if e]).strip(),
        "usage": usage,
        "tool_calls": int(tool_calls),
        "token_report": token_report,
        "elapsed_seconds": round(max(0.0, time.monotonic() - started), 3),
    }


async def _run_thomas_api_task(
    *,
    api_base: str,
    api_token: str,
    profile: str,
    prompt: str,
    mode: str,
    token_economy: str,
    max_iterations: int | None,
    tools_policy: str = "auto",
    job_type: str = "coding",
    watch: bool = False,
    watch_prefix: str = "",
) -> dict[str, Any]:
    base = str(api_base or "").rstrip("/")
    if not base:
        raise ValueError("thomas api base URL is empty")
    headers: dict[str, str] = {}
    token = str(api_token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    started = time.monotonic()
    chat_started = started
    reported_elapsed_ms: float | None = None
    reported_first_token_ms: float | None = None
    first_stream_event_elapsed_seconds: float | None = None
    first_text_delta_elapsed_seconds: float | None = None
    stream_event_count = 0
    text_event_count = 0
    text_parts: list[str] = []
    final_text = ""
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    tool_calls = 0
    token_report: dict[str, Any] = {}
    error = ""

    timeout = httpx.Timeout(connect=10.0, read=1200.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        session_resp = await client.post(f"{base}/api/session/new", headers=headers)
        session_resp.raise_for_status()
        sid = str((session_resp.json() or {}).get("session_id") or "").strip()
        if not sid:
            raise ValueError("thomas api did not return session_id")
        chat_started = time.monotonic()

        payload: dict[str, Any] = {
            "session_id": sid,
            "profile": profile,
            "mode": mode,
            "text": str(prompt or ""),
            "token_economy": token_economy,
            "tools_policy": str(tools_policy or "auto"),
            "job_type": str(job_type or "coding"),
        }
        if max_iterations is not None:
            payload["max_iterations"] = int(max_iterations)
        _watch_line(watch, f"{watch_prefix} api session: {sid}")
        _watch_line(watch, f"{watch_prefix} started mode={mode} economy={token_economy}")

        async with client.stream("POST", f"{base}/api/chat", headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async for raw_line in resp.aiter_lines():
                line = str(raw_line or "").strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                stream_event_count += 1
                if first_stream_event_elapsed_seconds is None:
                    first_stream_event_elapsed_seconds = max(0.0, time.monotonic() - chat_started)
                et = str(evt.get("type") or "")
                if et == "text":
                    chunk = str(evt.get("text") or "")
                    text_parts.append(chunk)
                    text_event_count += 1
                    if chunk and first_text_delta_elapsed_seconds is None:
                        first_text_delta_elapsed_seconds = max(0.0, time.monotonic() - chat_started)
                    _watch_text(watch, chunk)
                elif et == "tool_start":
                    _watch_line(watch, f"\n{watch_prefix} tool_start: {evt.get('name', '')}")
                elif et == "tool_result":
                    _watch_line(
                        watch,
                        f"\n{watch_prefix} tool_result: {evt.get('name', '')} ok={bool(evt.get('ok', False))}",
                    )
                elif et == "iteration":
                    _watch_line(
                        watch,
                        f"\n{watch_prefix} iteration={evt.get('iteration')} token_estimate={evt.get('token_estimate')}",
                    )
                elif et == "error":
                    error = str(evt.get("error") or "unknown error")
                    _watch_line(watch, f"\n{watch_prefix} error: {error}")
                elif et == "done":
                    final_text = str(evt.get("response") or "")
                    usage = _normalize_usage(evt.get("run_usage") or evt.get("usage"))
                    tool_calls = int(evt.get("tool_calls") or 0)
                    token_report = dict(evt.get("token_report") or {})
                    elapsed_raw = _safe_float(evt.get("elapsed_ms"))
                    if elapsed_raw is not None and elapsed_raw >= 0:
                        reported_elapsed_ms = float(elapsed_raw)
                    first_token_raw = _extract_reported_first_token_ms(evt, token_report=token_report)
                    if first_token_raw is not None:
                        reported_first_token_ms = float(first_token_raw)
                    _watch_line(watch, f"\n{watch_prefix} done tools={tool_calls}")
                elif et == "swarm_done":
                    final_text = str(evt.get("final") or "")
                    usage = _normalize_usage(evt.get("run_usage") or evt.get("usage"))
                    tool_calls = int(evt.get("tool_calls") or 0)
                    token_report = dict(evt.get("token_report") or {})
                    elapsed_raw = _safe_float(evt.get("elapsed_ms"))
                    if elapsed_raw is not None and elapsed_raw >= 0:
                        reported_elapsed_ms = float(elapsed_raw)
                    first_token_raw = _extract_reported_first_token_ms(evt, token_report=token_report)
                    if first_token_raw is not None:
                        reported_first_token_ms = float(first_token_raw)
                    _watch_line(watch, f"\n{watch_prefix} swarm_done tools={tool_calls}")

    elapsed = _select_elapsed_seconds(
        reported_elapsed_ms=reported_elapsed_ms,
        fallback_elapsed_seconds=max(0.0, time.monotonic() - chat_started),
    )
    if not final_text:
        # Preserve leading indentation in generated code blocks.
        final_text = "".join(text_parts).strip("\n")
    usage = _ensure_usage_telemetry(
        usage,
        prompt_text=str(prompt or ""),
        response_text=final_text,
        token_report=token_report,
    )
    first_token_fallback = (
        first_text_delta_elapsed_seconds
        if first_text_delta_elapsed_seconds is not None
        else first_stream_event_elapsed_seconds
    )
    first_token_seconds = _select_optional_elapsed_seconds(
        reported_elapsed_ms=reported_first_token_ms,
        fallback_elapsed_seconds=first_token_fallback,
    )
    return {
        "ok": not bool(error),
        "text": final_text,
        "error": error,
        "usage": usage,
        "tool_calls": int(tool_calls),
        "token_report": token_report,
        "elapsed_seconds": float(elapsed),
        "setup_elapsed_seconds": round(max(0.0, chat_started - started), 3),
        "reported_elapsed_ms": (round(float(reported_elapsed_ms), 3) if reported_elapsed_ms is not None else None),
        "first_token_seconds": first_token_seconds,
        "first_text_delta_seconds": (
            round(float(first_text_delta_elapsed_seconds), 3) if first_text_delta_elapsed_seconds is not None else None
        ),
        "first_stream_event_seconds": (
            round(float(first_stream_event_elapsed_seconds), 3)
            if first_stream_event_elapsed_seconds is not None
            else None
        ),
        "reported_first_token_ms": (
            round(float(reported_first_token_ms), 3) if reported_first_token_ms is not None else None
        ),
        "stream_event_count": int(stream_event_count),
        "text_event_count": int(text_event_count),
    }


async def run_agentic_benchmark(args: argparse.Namespace) -> Path:
    config_path = _resolve_config_path(str(args.config or ""))
    config = load_config(config_path)

    task_pack = load_agentic_task_pack(Path(args.task_pack).resolve())
    quality_min = int((task_pack.get("quality_scale") or {}).get("min", 1))
    quality_max = int((task_pack.get("quality_scale") or {}).get("max", 5))

    run_id = str(args.run_id).strip() or datetime.now(timezone.utc).strftime("agentic-%Y%m%d-%H%M%S")
    workspace_root = Path(args.workspace).resolve()
    runs_dir = Path(args.runs_dir).resolve()
    artifact_root_rel = Path("runtime") / "agentic_bench" / run_id

    baseline_name = str(args.baseline_name).strip() or "baseline_raw"
    thomas_name = str(args.thomas_name).strip() or "thomas_os"
    tracks: list[TrackSpec] = []
    if not bool(args.skip_baseline):
        tracks.append(TrackSpec(name=baseline_name, kind="raw", profile=args.profile))
    if not bool(args.skip_thomas):
        tracks.append(
            TrackSpec(
                name=thomas_name,
                kind="thomas",
                profile=args.profile,
                mode=args.thomas_mode,
                token_economy=args.thomas_token_economy,
                max_iterations=args.max_iterations,
            )
        )
    if not tracks:
        raise ValueError("Nothing to run: both baseline and thomas tracks are disabled.")

    if bool(args.thomas_max_mode):
        for track in tracks:
            if track.kind != "thomas":
                continue
            track.token_economy = "max"
            if args.thomas_runner == "api":
                track.mode = "swarm"
            else:
                track.mode = "thinking"
            if track.max_iterations is None:
                track.max_iterations = 20

    if args.thomas_runner == "embedded":
        for track in tracks:
            if track.kind == "thomas" and track.mode == "swarm":
                raise ValueError("mode=swarm requires --thomas-runner api")

    records: list[dict[str, Any]] = []
    detailed_rows: list[dict[str, Any]] = []
    transcript_blobs: dict[str, str] = {}
    watch = bool(getattr(args, "watch", False))

    for task in list(task_pack.get("tasks") or []):
        task_id = str(task.get("id") or "").strip()
        for track in tracks:
            context = {
                "run_id": run_id,
                "track": track.name,
                "artifact_dir": str((artifact_root_rel / track.name).as_posix()),
                "workspace": str(workspace_root.as_posix()),
            }
            rendered = render_task(task, context)
            prompt = str(rendered.get("prompt") or "")
            (workspace_root / Path(context["artifact_dir"])).mkdir(parents=True, exist_ok=True)
            watch_prefix = f"[{task_id}/{track.name}]"

            if track.kind == "raw":
                run = await _run_raw_task(
                    config,
                    profile=track.profile,
                    prompt=prompt,
                    watch=watch,
                    watch_prefix=watch_prefix,
                )
            elif args.thomas_runner == "api":
                run = await _run_thomas_api_task(
                    api_base=args.thomas_api_base,
                    api_token=args.thomas_api_token,
                    profile=track.profile,
                    prompt=prompt,
                    mode=track.mode,
                    token_economy=track.token_economy,
                    max_iterations=track.max_iterations,
                    watch=watch,
                    watch_prefix=watch_prefix,
                )
            else:
                run = await _run_thomas_embedded_task(
                    config,
                    profile=track.profile,
                    prompt=prompt,
                    mode=track.mode,
                    token_economy=track.token_economy,
                    max_iterations=track.max_iterations,
                    watch=watch,
                    watch_prefix=watch_prefix,
                )

            checks = evaluate_task_success(
                rendered,
                response_text=str(run.get("text") or ""),
                workspace_root=workspace_root,
            )
            success = bool(run.get("ok")) and bool(checks.get("success"))
            notes = []
            err = str(run.get("error") or "").strip()
            if err:
                notes.append(f"runner_error={err}")
            notes.extend(list(checks.get("reasons") or []))
            notes_text = "; ".join(notes).strip()

            transcript_rel = str((Path("transcripts") / track.name / f"{task_id}.md").as_posix())
            transcript_blobs[transcript_rel] = "\n".join(
                [
                    f"# Task {task_id} - {track.name}",
                    "",
                    f"- run_id: {run_id}",
                    f"- track_kind: {track.kind}",
                    f"- profile: {track.profile}",
                    f"- mode: {track.mode if track.kind == 'thomas' else 'raw'}",
                    f"- token_economy: {track.token_economy if track.kind == 'thomas' else 'n/a'}",
                    f"- elapsed_seconds: {run.get('elapsed_seconds')}",
                    f"- first_token_seconds: {run.get('first_token_seconds')}",
                    f"- first_text_delta_seconds: {run.get('first_text_delta_seconds')}",
                    f"- first_stream_event_seconds: {run.get('first_stream_event_seconds')}",
                    f"- setup_elapsed_seconds: {run.get('setup_elapsed_seconds')}",
                    f"- stream_event_count: {run.get('stream_event_count')}",
                    f"- text_event_count: {run.get('text_event_count')}",
                    f"- success: {str(success).lower()}",
                    f"- tool_calls: {run.get('tool_calls')}",
                    f"- usage: {json.dumps(run.get('usage') or {}, ensure_ascii=False)}",
                    "",
                    "## Prompt",
                    "",
                    "```text",
                    prompt,
                    "```",
                    "",
                    "## Response",
                    "",
                    "```text",
                    str(run.get("text") or ""),
                    "```",
                    "",
                    "## Checks",
                    "",
                    "```json",
                    json.dumps(checks, ensure_ascii=False, indent=2),
                    "```",
                    "",
                ]
            )

            quality_score = quality_max if success else quality_min
            records.append(
                {
                    "task_id": task_id,
                    "competitor": track.name,
                    "success": bool(success),
                    "elapsed_seconds": float(run.get("elapsed_seconds") or 0.0),
                    "follow_up_prompts": 0,
                    "quality_score": int(quality_score),
                    "evidence": transcript_rel,
                    "notes": notes_text,
                    "captured_at": _now_iso(),
                }
            )
            detailed_rows.append(
                {
                    "task_id": task_id,
                    "track": track.name,
                    "track_kind": track.kind,
                    "mode": track.mode,
                    "token_economy": track.token_economy,
                    "max_iterations": track.max_iterations,
                    "run": run,
                    "checks": checks,
                    "success": bool(success),
                }
            )

    harness_pack = _harness_pack(task_pack)
    competitors = [t.name for t in tracks]
    execution_plan = build_execution_plan(
        task_pack=harness_pack,
        competitors=competitors,
        randomize=False,
        seed=None,
    )
    summary = compute_summary(harness_pack, records)

    run_dir = write_run_artifacts(
        runs_dir=runs_dir,
        run_id=run_id,
        task_pack=harness_pack,
        competitors=competitors,
        execution_plan=execution_plan,
        randomized_order=False,
        random_seed=None,
        require_evidence=False,
        records=records,
        summary=summary,
    )

    for rel, body in transcript_blobs.items():
        target = run_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")

    before_after = compute_before_after_delta(
        summary,
        baseline_name=baseline_name,
        thomas_name=thomas_name,
    )

    _write_json(run_dir / "benchmark_results.raw.json", detailed_rows)
    _write_json(run_dir / "task_pack.agentic.snapshot.json", task_pack)
    _write_json(
        run_dir / "agentic_benchmark.config.json",
        {
            "created_at": _now_iso(),
            "profile": args.profile,
            "workspace": str(workspace_root),
            "thomas_runner": args.thomas_runner,
            "thomas_api_base": str(args.thomas_api_base or ""),
            "thomas_mode": str(args.thomas_mode or ""),
            "thomas_token_economy": str(args.thomas_token_economy or ""),
            "thomas_max_mode": bool(args.thomas_max_mode),
            "max_iterations": args.max_iterations,
            "watch": watch,
            "baseline_enabled": not bool(args.skip_baseline),
            "thomas_enabled": not bool(args.skip_thomas),
            "artifact_root": str(artifact_root_rel.as_posix()),
            "config_path": str(config_path) if config_path else "",
        },
    )
    _write_json(run_dir / "before_after.delta.json", before_after)
    return run_dir


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run local-first agentic benchmark: raw model vs Thomas OS.")
    parser.add_argument("--task-pack", default=str(DEFAULT_TASK_PACK), help="Path to benchmark task pack JSON.")
    parser.add_argument("--runs-dir", default=str(DEFAULT_RUNS_DIR), help="Output directory for benchmark runs.")
    parser.add_argument("--run-id", default="", help="Optional run id (default: UTC timestamp).")
    parser.add_argument("--config", default="", help="Optional path to thomas.toml.")
    parser.add_argument("--workspace", default=".", help="Workspace root for file-based checks.")
    parser.add_argument("--profile", default="local", help="Model profile to benchmark (default: local).")
    parser.add_argument("--baseline-name", default="baseline_raw", help="Competitor label for raw baseline.")
    parser.add_argument("--thomas-name", default="thomas_os", help="Competitor label for Thomas track.")
    parser.add_argument("--skip-baseline", action="store_true", help="Skip raw baseline track.")
    parser.add_argument("--skip-thomas", action="store_true", help="Skip Thomas track.")
    parser.add_argument("--thomas-runner", choices=("embedded", "api"), default="embedded")
    parser.add_argument(
        "--thomas-api-base", default="http://127.0.0.1:8899", help="Thomas API base URL when --thomas-runner=api."
    )
    parser.add_argument("--thomas-api-token", default="", help="Thomas API bearer token for remote mode.")
    parser.add_argument("--thomas-mode", choices=("fast", "auto", "thinking", "swarm"), default="auto")
    parser.add_argument("--thomas-token-economy", choices=("cheap", "optimal", "max"), default="optimal")
    parser.add_argument(
        "--thomas-max-mode",
        action="store_true",
        help="Enable high-budget Thomas mode (max token economy; swarm via API runner).",
    )
    parser.add_argument("--max-iterations", type=int, default=None, help="Optional max iterations for Thomas track.")
    parser.add_argument("--watch", action="store_true", help="Stream live model/tool output while benchmark runs.")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not str(args.thomas_api_token or "").strip():
        env_token = str(__import__("os").environ.get("THOMAS_API_TOKEN", "")).strip()
        if env_token:
            args.thomas_api_token = env_token
    run_dir = asyncio.run(run_agentic_benchmark(args))
    print(f"Agentic benchmark completed: {run_dir}")
    print(f"  - {run_dir / 'scorecard.json'}")
    print(f"  - {run_dir / 'before_after.delta.json'}")
    print(f"  - {run_dir / 'benchmark_results.raw.json'}")
    print(f"  - {run_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
