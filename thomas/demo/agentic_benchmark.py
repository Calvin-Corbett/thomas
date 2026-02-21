from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

import httpx

from thomas.agent.loop import AgentLoop
from thomas.core.config import AppConfig, load_config
from thomas.core.llm import LLMClient
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

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TASK_PACK = ROOT / "demo" / "task_pack.agentic.local.json"
DEFAULT_RUNS_DIR = ROOT / "demo" / "agentic-runs"
DEFAULT_SYSTEM_PROMPT = (
    "You are a baseline assistant. Do not claim to have executed tools unless you actually can. "
    "Respond concisely and truthfully."
)
ALLOWED_SUCCESS_KEYS = {
    "response_contains",
    "response_regex",
    "required_files",
    "required_file_contains",
    "required_file_regex",
    "check_command",
    "check_timeout_seconds",
}


def _watch_line(enabled: bool, message: str) -> None:
    if enabled:
        print(message, flush=True)


def _watch_text(enabled: bool, text: str) -> None:
    if enabled and text:
        sys.stdout.write(text)
        sys.stdout.flush()


def _read_json(path: Path) -> Any:
    raw = path.read_text(encoding="utf-8-sig")
    return json.loads(raw)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_str_list(value: Any, *, field: str) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list of strings.")
    out: List[str] = []
    for idx, item in enumerate(value, start=1):
        text = str(item or "").strip()
        if not text:
            raise ValueError(f"{field}[{idx}] cannot be empty.")
        out.append(text)
    return out


def _coerce_str_map(value: Any, *, field: str) -> Dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object of string keys/values.")
    out: Dict[str, str] = {}
    for k, v in value.items():
        kk = str(k or "").strip()
        vv = str(v or "").strip()
        if not kk:
            raise ValueError(f"{field} has an empty key.")
        if not vv:
            raise ValueError(f"{field}['{kk}'] cannot be empty.")
        out[kk] = vv
    return out


def load_agentic_task_pack(path: Path) -> Dict[str, Any]:
    data = _read_json(path)
    if not isinstance(data, dict):
        raise ValueError("Task pack must be a JSON object.")

    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Task pack must include a non-empty 'tasks' list.")

    seen_ids: set[str] = set()
    norm_tasks: List[Dict[str, Any]] = []
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
        budget: Optional[int] = None
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
            raise ValueError(
                f"Task '{task_id}' has unknown success keys: {', '.join(unknown)}"
            )

        norm_tasks.append(
            {
                "id": task_id,
                "title": title,
                "prompt": prompt,
                "success_criteria": str(raw_task.get("success_criteria") or "").strip(),
                "time_budget_seconds": budget,
                "success": {
                    "response_contains": _coerce_str_list(
                        success.get("response_contains"), field=f"tasks[{task_id}].success.response_contains"
                    ),
                    "response_regex": _coerce_str_list(
                        success.get("response_regex"), field=f"tasks[{task_id}].success.response_regex"
                    ),
                    "required_files": _coerce_str_list(
                        success.get("required_files"), field=f"tasks[{task_id}].success.required_files"
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
        "description": str(data.get("description") or "").strip(),
        "protocol": list(data.get("protocol") or []),
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
        out: Dict[str, Any] = {}
        for k, v in value.items():
            key_text = apply_template_context(str(k), context)
            out[str(key_text)] = apply_template_context(v, context)
        return out
    return value


def render_task(task: Mapping[str, Any], context: Mapping[str, str]) -> Dict[str, Any]:
    return apply_template_context(dict(task), context)


def _resolve_path(path_text: str, workspace_root: Path) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return workspace_root / path


def _normalize_usage(payload: Any) -> Dict[str, int]:
    if not isinstance(payload, dict):
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    try:
        p = max(0, int(payload.get("prompt_tokens", 0) or 0))
    except Exception:
        p = 0
    try:
        c = max(0, int(payload.get("completion_tokens", 0) or 0))
    except Exception:
        c = 0
    try:
        t = max(0, int(payload.get("total_tokens", 0) or 0))
    except Exception:
        t = p + c
    t = max(t, p + c)
    return {"prompt_tokens": p, "completion_tokens": c, "total_tokens": t}


def evaluate_task_success(
    task: Mapping[str, Any],
    *,
    response_text: str,
    workspace_root: Path,
) -> Dict[str, Any]:
    success_cfg = dict(task.get("success") or {})
    reasons: List[str] = []
    checks: Dict[str, Any] = {}
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
            except Exception:
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
            except Exception:
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
    return registry


@dataclass
class TrackSpec:
    name: str
    kind: str  # raw | thomas
    profile: str
    mode: str = "auto"
    token_economy: str = "optimal"
    max_iterations: Optional[int] = None


async def _run_raw_task(
    config: AppConfig,
    *,
    profile: str,
    prompt: str,
    watch: bool = False,
    watch_prefix: str = "",
) -> Dict[str, Any]:
    model_cfg = config.get_model(profile)
    llm = LLMClient(model_cfg, fallback_configs=[], failover_enabled=False)
    started = time.monotonic()
    text = ""
    usage: Dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
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
        usage = _normalize_usage(response.get("usage"))
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


async def _run_thomas_embedded_task(
    config: AppConfig,
    *,
    profile: str,
    prompt: str,
    mode: str,
    token_economy: str,
    max_iterations: Optional[int],
    watch: bool = False,
    watch_prefix: str = "",
) -> Dict[str, Any]:
    if mode == "swarm":
        raise ValueError("Embedded runner does not support mode=swarm. Use --thomas-runner api.")
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
    text_parts: List[str] = []
    final_text = ""
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    tool_calls = 0
    error = ""
    try:
        run_kwargs: Dict[str, Any] = {
            "mode": str(mode),
            "tools_policy": "auto",
            "token_economy": str(token_economy),
            "job_type": "coding",
        }
        if max_iterations is not None:
            run_kwargs["max_iterations"] = int(max_iterations)

        async for event in agent.run(str(prompt or ""), **run_kwargs):
            et = str(getattr(event.type, "value", ""))
            if et == "text_delta":
                chunk = str(event.data.get("text") or "")
                text_parts.append(chunk)
                _watch_text(watch, chunk)
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
                _watch_line(watch, f"\n{watch_prefix} done: iterations={event.data.get('iterations')} tools={tool_calls}")
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        _watch_line(watch, f"\n{watch_prefix} runner_exception: {error}")
    finally:
        await llm.close()

    elapsed = max(0.0, time.monotonic() - started)
    if not final_text:
        final_text = "".join(text_parts).strip()
    return {
        "ok": not bool(error),
        "text": final_text,
        "error": error,
        "usage": usage,
        "tool_calls": int(tool_calls),
        "elapsed_seconds": round(elapsed, 3),
    }


async def _run_thomas_api_task(
    *,
    api_base: str,
    api_token: str,
    profile: str,
    prompt: str,
    mode: str,
    token_economy: str,
    max_iterations: Optional[int],
    watch: bool = False,
    watch_prefix: str = "",
) -> Dict[str, Any]:
    base = str(api_base or "").rstrip("/")
    if not base:
        raise ValueError("thomas api base URL is empty")
    headers: Dict[str, str] = {}
    token = str(api_token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    started = time.monotonic()
    text_parts: List[str] = []
    final_text = ""
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    tool_calls = 0
    error = ""

    timeout = httpx.Timeout(connect=10.0, read=1200.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        session_resp = await client.post(f"{base}/api/session/new", headers=headers)
        session_resp.raise_for_status()
        sid = str((session_resp.json() or {}).get("session_id") or "").strip()
        if not sid:
            raise ValueError("thomas api did not return session_id")

        payload: Dict[str, Any] = {
            "session_id": sid,
            "profile": profile,
            "mode": mode,
            "text": str(prompt or ""),
            "token_economy": token_economy,
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
                except Exception:
                    continue
                et = str(evt.get("type") or "")
                if et == "text":
                    chunk = str(evt.get("text") or "")
                    text_parts.append(chunk)
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
                    _watch_line(watch, f"\n{watch_prefix} done tools={tool_calls}")
                elif et == "swarm_done":
                    final_text = str(evt.get("final") or "")
                    usage = _normalize_usage(evt.get("run_usage") or evt.get("usage"))
                    tool_calls = int(evt.get("tool_calls") or 0)
                    _watch_line(watch, f"\n{watch_prefix} swarm_done tools={tool_calls}")

    elapsed = max(0.0, time.monotonic() - started)
    if not final_text:
        final_text = "".join(text_parts).strip()
    return {
        "ok": not bool(error),
        "text": final_text,
        "error": error,
        "usage": usage,
        "tool_calls": int(tool_calls),
        "elapsed_seconds": round(elapsed, 3),
    }


def _harness_pack(task_pack: Mapping[str, Any]) -> Dict[str, Any]:
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
) -> Dict[str, Any]:
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
                float(after.get("weighted_score", 0.0)) - float(baseline.get("weighted_score", 0.0)), 3
            ),
            "success_rate_delta": round(
                float(after.get("success_rate", 0.0)) - float(baseline.get("success_rate", 0.0)), 6
            ),
            "avg_elapsed_seconds_delta": round(
                float(after.get("avg_elapsed_seconds", 0.0))
                - float(baseline.get("avg_elapsed_seconds", 0.0)),
                3,
            ),
            "evidence_coverage_delta": round(
                float(after.get("evidence_coverage", 0.0))
                - float(baseline.get("evidence_coverage", 0.0)),
                6,
            ),
        },
    }


async def run_agentic_benchmark(args: argparse.Namespace) -> Path:
    config_path = Path(args.config).resolve() if str(args.config or "").strip() else None
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
    tracks: List[TrackSpec] = []
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

    records: List[Dict[str, Any]] = []
    detailed_rows: List[Dict[str, Any]] = []
    transcript_blobs: Dict[str, str] = {}
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
        },
    )
    _write_json(run_dir / "before_after.delta.json", before_after)
    return run_dir


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run local-first agentic benchmark: raw model vs Thomas OS."
    )
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
    parser.add_argument("--thomas-api-base", default="http://127.0.0.1:8899", help="Thomas API base URL when --thomas-runner=api.")
    parser.add_argument("--thomas-api-token", default="", help="Thomas API bearer token for remote mode.")
    parser.add_argument("--thomas-mode", choices=("fast", "auto", "thinking", "swarm"), default="auto")
    parser.add_argument("--thomas-token-economy", choices=("cheap", "optimal", "max"), default="optimal")
    parser.add_argument("--thomas-max-mode", action="store_true", help="Enable high-budget Thomas mode (max token economy; swarm via API runner).")
    parser.add_argument("--max-iterations", type=int, default=None, help="Optional max iterations for Thomas track.")
    parser.add_argument("--watch", action="store_true", help="Stream live model/tool output while benchmark runs.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
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
