"""Thomas-native project swarm runner."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from scripts.workboard_claim_ops import claim, release
from scripts.workboard_message import send_message

from thomas.core.benchmark_lane import audit_benchmark_event
from thomas.core.config import load_config
from thomas.core.llm_client import LLMClient
from thomas.core.llm_shared import LLMError
from thomas.demo.project_swarm_contracts import (
    ProjectLane,
    copy_tree,
    count_lines,
    evaluate_baseline_product,
    evaluate_project,
    mock_worker_payload,
    project_lanes,
    render_worker_module,
    write_architecture,
    write_integrated_game,
    write_worker_module,
)


def extract_json(text: str) -> dict[str, Any]:
    body = str(text or "").strip()
    if body.startswith("```"):
        body = body.strip("`")
        if body.lower().startswith("json"):
            body = body[4:].strip()
    start = body.find("{")
    end = body.rfind("}")
    if start < 0 or end < start:
        raise ValueError("response did not contain a JSON object")
    payload = json.loads(body[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("response JSON must be an object")
    return payload


async def worker_payload(args: Any, lane: ProjectLane, total: int) -> dict[str, Any]:
    if bool(args.mock):
        return mock_worker_payload(lane)
    config = load_config(args.config)
    profile = str(args.profile or config.default_model)
    client = LLMClient(
        config.get_model(profile),
        fallback_configs=config.failover_chain(profile),
        failover_enabled=config.failover.enabled,
        failover_cooldown_s=config.failover.cooldown_seconds,
        failover_on_auth_error=config.failover.fallback_on_auth_error,
    )
    prompt = (
        f"You are worker lane {lane.lane:02d} of {total:02d} building a Pac-Man browser game. "
        f"Your component is {lane.title}. Return only JSON with keys title, summary, settings, acceptance. "
        "Do not write files. Do not include markdown. acceptance must have at least 3 strings."
    )
    try:
        response = await client.chat(
            [
                {"role": "system", "content": "Return structured implementation intent only."},
                {"role": "user", "content": prompt},
            ]
        )
        return extract_json(str(response.get("text") or ""))
    finally:
        await client.close()


def workboard_message(workboard: Path, *, sender: str, recipient: str, task_id: str, summary: str) -> None:
    if not workboard.exists():
        return
    send_message(
        workboard,
        sender=sender,
        recipient=recipient,
        task_id=task_id,
        kind="status",
        priority="p1",
        summary=summary,
        require_claims_to_have_active_task=False,
    )


def claim_scope(workboard: Path, *, agent: str, scope: str, task: str, role: str, parent: str) -> None:
    ok, message = claim(
        workboard,
        agent=agent,
        name=agent,
        role=role,
        parent=parent,
        scope=scope,
        task=task,
        allow_presence_override=True,
        presence_override_reason="project swarm scoped benchmark lane",
    )
    if not ok:
        raise ValueError(str(message))


def release_scope(workboard: Path, *, agent: str) -> None:
    release(
        workboard,
        agent=agent,
        allow_dirty=True,
        dirty_reason="project swarm completed scoped benchmark output",
        allow_presence_override=True,
        presence_override_reason="project swarm scoped benchmark lane complete",
    )


async def run_lane(args: Any, root: Path, lane: ProjectLane, total: int, sem: asyncio.Semaphore) -> dict[str, Any]:
    task_id = f"{args.run_id}-lane-{lane.lane:02d}"
    started = time.perf_counter()
    claimed = False
    try:
        claim_scope(args.workboard, agent=lane.agent, scope=lane.scope, task=task_id, role="worker", parent=args.agent)
        claimed = True
        workboard_message(args.workboard, sender=lane.agent, recipient=args.agent, task_id=task_id, summary="started")
        async with sem:
            payload = await worker_payload(args, lane, total)
        write_worker_module(lane, render_worker_module(lane, payload))
        elapsed = time.perf_counter() - started
        workboard_message(args.workboard, sender=lane.agent, recipient=args.agent, task_id=task_id, summary="complete")
        return {"lane": lane.lane, "status": "passed", "seconds": elapsed}
    except (ValueError, OSError, json.JSONDecodeError, LLMError) as exc:
        return {"lane": lane.lane, "status": "failed", "seconds": time.perf_counter() - started, "error": str(exc)}
    finally:
        if claimed and not bool(args.keep_claims):
            release_scope(args.workboard, agent=lane.agent)


async def run_thomas_project_swarm(args: Any) -> dict[str, Any]:
    repo_root = args.repo_root.resolve()
    root = repo_root / "output" / "benchmarks" / args.run_id / "thomas_swarm"
    root.mkdir(parents=True, exist_ok=True)
    lanes = project_lanes(root, repo_root, int(args.lanes))
    write_architecture(root, lanes)
    context = {"run_id": args.run_id, "lane": "benchmark", "root": str(root), "audit_path": str(root / "audit.jsonl")}
    audit_benchmark_event(context, event="project_swarm_start", decision="allowed", payload={"lanes": len(lanes)})
    coordinator_scope = ",".join(str((root / name).relative_to(repo_root)) for name in ("ARCHITECTURE.md", "task_graph.json"))
    claim_scope(args.workboard, agent=args.agent, scope=coordinator_scope, task=args.run_id, role="parent", parent="none")
    started = time.perf_counter()
    sem = asyncio.Semaphore(max(1, int(args.max_concurrency)))
    lane_results = await asyncio.gather(*(run_lane(args, root, lane, len(lanes), sem) for lane in lanes))
    write_integrated_game(root, lanes)
    evaluator = evaluate_project(root)
    elapsed = time.perf_counter() - started
    metrics = {
        "run_id": args.run_id,
        "kind": "thomas_project_swarm",
        "root": str(root),
        "lanes": len(lanes),
        "max_concurrency": int(args.max_concurrency),
        "seconds": elapsed,
        "lane_results": lane_results,
        "evaluator": evaluator,
        "lines": count_lines(root / "product"),
    }
    metrics["passed"] = int(evaluator.get("failed") == 0 and all(row["status"] == "passed" for row in lane_results))
    metrics["lines_per_minute"] = round(metrics["lines"]["nonblank"] / max(elapsed / 60.0, 0.001), 2)
    (root / "project_swarm_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    audit_benchmark_event(context, event="project_swarm_finish", decision="allowed", payload=metrics)
    if not bool(args.keep_claims):
        release_scope(args.workboard, agent=args.agent)
    return metrics


def run_codex_baseline(args: Any) -> dict[str, Any]:
    run_root = args.repo_root / "output" / "benchmarks" / args.run_id
    reuse_raw = str(getattr(args, "baseline_reuse_dir", "") or "").strip()
    if reuse_raw:
        temp_root = Path(reuse_raw).expanduser().resolve()
        elapsed = float(getattr(args, "baseline_elapsed_seconds", 0.0) or 0.0)
        returncode = 124
        stdout = "reused timed-out baseline workspace"
        stderr = ""
        timed_out = True
    else:
        temp_root = Path(tempfile.gettempdir()) / f"codex_pacman_baseline_{args.run_id}_{int(time.time())}"
        temp_root.mkdir(parents=True)
        subprocess.run(["git", "init"], cwd=temp_root, capture_output=True, text=True, check=False)
        codex_cmd = shutil.which("codex.cmd") or shutil.which("codex.exe") or shutil.which("codex")
        if not codex_cmd:
            raise FileNotFoundError("codex CLI was not found on PATH")
        started = time.perf_counter()
        timed_out = False
        try:
            proc = subprocess.run(
                [codex_cmd, "exec", "--full-auto", "-C", str(temp_root), _baseline_prompt()],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                text=True,
                timeout=int(args.baseline_timeout),
                check=False,
            )
            elapsed = time.perf_counter() - started
            returncode = proc.returncode
            stdout = str(proc.stdout or "")
            stderr = str(proc.stderr or "")
        except subprocess.TimeoutExpired as exc:
            elapsed = time.perf_counter() - started
            returncode = 124
            stdout = str(exc.stdout or "")
            stderr = str(exc.stderr or "")
            timed_out = True
    dst = run_root / "codex_baseline"
    copy_tree(temp_root, dst)
    evaluation = evaluate_baseline_product(dst)
    metrics = {
        "kind": "codex_baseline",
        "root": str(dst),
        "seconds": elapsed,
        "returncode": returncode,
        "timed_out": timed_out,
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
        "evaluator": evaluation,
        "lines": count_lines(dst),
    }
    metrics["passed"] = int(returncode == 0 and evaluation["failed"] == 0)
    metrics["lines_per_minute"] = round(metrics["lines"]["nonblank"] / max(elapsed / 60.0, 0.001), 2)
    (dst / "codex_baseline_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics


def _baseline_prompt() -> str:
    return (
        "Build a playable Pac-Man style browser game in this folder. "
        "Create index.html, src/game.mjs, and src/styles.css. No external dependencies. "
        "Must include canvas rendering, keyboard controls, pellets, power pellets, ghosts, score, and lives."
    )
