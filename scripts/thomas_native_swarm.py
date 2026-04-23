"""Run a Thomas-native, workboard-scoped product swarm benchmark."""

# ruff: noqa: E402 - script execution needs repo root on sys.path before local imports.

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.workboard_claim_ops import claim, release
from scripts.workboard_message import send_message
from thomas.core.benchmark_lane import audit_benchmark_event
from thomas.core.config import load_config
from thomas.core.llm_client import LLMClient
from thomas.core.llm_shared import LLMError
from thomas.demo.native_swarm_product import (
    count_product_lines,
    lane_specs,
    mock_payload,
    render_module,
    run_evaluator,
    write_feature,
    write_scaffold,
)

WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"


def _extract_json(text: str) -> dict[str, Any]:
    body = str(text or "").strip()
    if body.startswith("```"):
        body = body.strip("`")
        if body.lower().startswith("json"):
            body = body[4:].strip()
    start = body.find("{")
    end = body.rfind("}")
    if start < 0 or end < start:
        raise ValueError("model response did not contain a JSON object")
    parsed = json.loads(body[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("model response JSON must be an object")
    return parsed


def _prompt(lane: int, total: int) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a Thomas worker inside a scoped benchmark lane. Return only JSON. "
                "Do not request tools and do not write files."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Create feature intent for lane {lane:02d} of {total:02d}. "
                "Return a JSON object with keys: title, category, metric, accent, problem, "
                "workflow, acceptanceChecks, implementationNotes. "
                "Category must be one of intake, planning, execution, review, governance. "
                "Workflow and acceptanceChecks must be arrays of at least 3 strings."
            ),
        },
    ]


async def _llm_payload(*, profile: str | None, config_path: Path | None, lane: int, total: int) -> dict[str, Any]:
    config = load_config(config_path)
    profile_name = profile or config.default_model
    client = LLMClient(
        config.get_model(profile_name),
        fallback_configs=config.failover_chain(profile_name),
        failover_enabled=config.failover.enabled,
        failover_cooldown_s=config.failover.cooldown_seconds,
        failover_on_auth_error=config.failover.fallback_on_auth_error,
    )
    try:
        response = await client.chat(_prompt(lane, total))
        return _extract_json(str(response.get("text") or ""))
    finally:
        await client.close()


def _message(
    workboard: Path,
    *,
    sender: str,
    recipient: str,
    task_id: str,
    summary: str,
    kind: str = "status",
) -> None:
    if not workboard.exists():
        return
    send_message(
        workboard,
        sender=sender,
        recipient=recipient,
        task_id=task_id,
        summary=summary,
        kind=kind,
        priority="p1",
        requested_action="none",
        decision="pending",
        require_claims_to_have_active_task=False,
    )


def _claim(workboard: Path, *, agent: str, scope: str, task: str, role: str, parent: str) -> None:
    ok, message = claim(
        workboard,
        agent=agent,
        name=agent,
        role=role,
        parent=parent,
        scope=scope,
        task=task,
    )
    if not ok:
        raise ValueError(str(message))


def _release(workboard: Path, *, agent: str) -> None:
    release(
        workboard,
        agent=agent,
    )


async def _run_lane(args: argparse.Namespace, root: Path, spec, sem: asyncio.Semaphore) -> dict[str, Any]:
    task_id = f"{args.run_id}-lane-{spec.lane:02d}"
    start = time.perf_counter()
    claimed = False
    try:
        _claim(args.workboard, agent=spec.agent, scope=spec.scope, task=task_id, role="worker", parent=args.agent)
        claimed = True
        _message(
            args.workboard,
            sender=spec.agent,
            recipient=args.agent,
            task_id=task_id,
            summary="lane claimed and starting",
        )
        async with sem:
            payload = mock_payload(spec.lane) if args.mock else await _llm_payload(
                profile=args.profile,
                config_path=args.config,
                lane=spec.lane,
                total=args.lanes,
            )
        module_text = render_module(spec.lane, payload)
        write_feature(root, spec, module_text)
        elapsed = time.perf_counter() - start
        _message(
            args.workboard,
            sender=spec.agent,
            recipient=args.agent,
            task_id=task_id,
            summary=f"lane complete in {elapsed:.2f}s",
        )
        return {"lane": spec.lane, "agent": spec.agent, "status": "passed", "seconds": elapsed}
    except (ValueError, OSError, json.JSONDecodeError, LLMError) as exc:
        elapsed = time.perf_counter() - start
        _message(
            args.workboard,
            sender=spec.agent,
            recipient=args.agent,
            task_id=task_id,
            summary=f"lane failed: {exc}",
            kind="blocker",
        )
        return {"lane": spec.lane, "agent": spec.agent, "status": "failed", "seconds": elapsed, "error": str(exc)}
    finally:
        if claimed and not args.keep_claims:
            _release(args.workboard, agent=spec.agent)


async def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = args.repo_root.resolve()
    root = (repo_root / "output" / "benchmarks" / args.run_id).resolve()
    root.mkdir(parents=True, exist_ok=True)
    write_scaffold(root, args.lanes)
    context = {
        "run_id": args.run_id,
        "lane": "benchmark",
        "reason": "Thomas-native scoped swarm benchmark",
        "root": str(root),
        "audit_path": str(root / "benchmark_audit.jsonl"),
    }
    audit_benchmark_event(context, event="native_swarm_start", decision="allowed", payload={"lanes": args.lanes})
    coordinator_scope = ",".join(
        str((root / rel).relative_to(repo_root))
        for rel in ("SPEC.md", "scopes.txt", "native_swarm_metrics.json")
    )
    _claim(args.workboard, agent=args.agent, scope=coordinator_scope, task=args.run_id, role="parent", parent="none")
    started = time.perf_counter()
    sem = asyncio.Semaphore(max(1, int(args.max_concurrency)))
    lane_rows = await asyncio.gather(*[_run_lane(args, root, spec, sem) for spec in lane_specs(root, args.lanes)])
    evaluator = run_evaluator(root)
    elapsed = time.perf_counter() - started
    line_counts = count_product_lines(root)
    passed = evaluator.get("passed")
    failed = evaluator.get("failed")
    metrics = {
        "run_id": args.run_id,
        "root": str(root),
        "lanes": args.lanes,
        "max_concurrency": args.max_concurrency,
        "mock": bool(args.mock),
        "seconds": elapsed,
        "lines": line_counts,
        "lines_per_minute": round(line_counts["nonblank"] / max(elapsed / 60.0, 0.001), 2),
        "lane_results": lane_rows,
        "evaluator": evaluator,
        "passed": int(passed) if passed is not None else 0,
        "failed": int(failed) if failed is not None else args.lanes,
    }
    (root / "native_swarm_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    audit_benchmark_event(context, event="native_swarm_finish", decision="allowed", payload=metrics)
    if not args.keep_claims:
        _release(args.workboard, agent=args.agent)
    return metrics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-product-benchmark", action="store_true", help="Run the product swarm benchmark.")
    parser.add_argument("--run-id", default=f"thomas_native_swarm_{time.strftime('%Y%m%d_%H%M%S')}")
    parser.add_argument("--lanes", type=int, default=25)
    parser.add_argument("--max-concurrency", type=int, default=8)
    parser.add_argument("--profile", default="")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--workboard", type=Path, default=WORKBOARD)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--agent", default="thomas-native-swarm-coordinator")
    parser.add_argument("--mock", action="store_true", help="Use deterministic local payloads instead of model calls.")
    parser.add_argument("--keep-claims", action="store_true", help="Leave benchmark claims active for inspection.")
    parser.add_argument("--json", action="store_true")
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.profile = str(args.profile or "").strip() or None
    if not args.run_product_benchmark:
        raise SystemExit("--run-product-benchmark is required")
    if args.lanes < 1 or args.lanes > 100:
        raise SystemExit("--lanes must be between 1 and 100")
    metrics = asyncio.run(run_benchmark(args))
    if args.json:
        print(json.dumps(metrics, indent=2))
    else:
        print(f"Native swarm: {metrics['passed']}/{args.lanes} passed in {metrics['seconds']:.2f}s")
        print(f"Metrics: {Path(metrics['root']) / 'native_swarm_metrics.json'}")
    return 0 if metrics["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(run())
