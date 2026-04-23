"""Run a Thomas-vs-raw-Codex comparison for manual review."""

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

from thomas.demo.project_swarm_runner import (
    run_codex_prompt_only,
    run_thomas_compare_swarm,
    run_thomas_prompt_only,
)

WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=f"prompt_compare_{time.strftime('%Y%m%d_%H%M%S')}")
    parser.add_argument(
        "--project-prompt",
        default="Build a useful project from the requested task.",
        help="Exact task prompt to give both Thomas and raw Codex.",
    )
    parser.add_argument("--lanes", type=int, default=25)
    parser.add_argument("--max-concurrency", type=int, default=8)
    parser.add_argument("--profile", default="")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--workboard", type=Path, default=WORKBOARD)
    parser.add_argument("--agent", default="thomas-project-swarm-coordinator")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--keep-claims", action="store_true")
    parser.add_argument("--integrator-repair-rounds", type=int, default=2)
    parser.add_argument("--integrator-max-targets", type=int, default=4)
    parser.add_argument(
        "--prompt-only-transport",
        choices=("auto", "chat", "codex_exec"),
        default="auto",
        help="Transport for the legacy prompt-only Thomas runner.",
    )
    parser.add_argument(
        "--thomas-runner",
        choices=("production", "prompt_only"),
        default="production",
        help="Thomas comparison path. 'production' uses the project swarm path; 'prompt_only' keeps the legacy runner.",
    )
    parser.add_argument("--raw-timeout", type=int, default=900)
    parser.add_argument("--thomas-only", action="store_true")
    parser.add_argument("--raw-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def _manual_review_summary(kind: str, metrics: dict[str, Any], *, thomas_runner: str = "") -> dict[str, Any]:
    metrics_kind = str(metrics.get("kind") or "").strip()
    summary_kind = kind
    if kind == "thomas":
        if metrics_kind:
            summary_kind = metrics_kind
        elif str(thomas_runner or "").strip().lower() == "prompt_only":
            summary_kind = "thomas_swarm_prompt_only"
        else:
            summary_kind = "thomas_project_swarm"
    summary = {
        "kind": summary_kind,
        "root": metrics.get("root"),
        "seconds": metrics.get("seconds"),
        "lines": metrics.get("lines"),
        "workspace": metrics.get("workspace"),
    }
    if kind == "thomas":
        worker_results = list(metrics.get("worker_results") or metrics.get("lane_results") or [])
        summary["worker_failures"] = [row for row in worker_results if row.get("status") != "passed"]
        summary["repair_rounds"] = len(list(metrics.get("integrator_repairs") or []))
        summary["runner"] = str(thomas_runner or "").strip().lower() or "production"
        detail_name = "thomas_prompt_only_metrics.json" if summary_kind == "thomas_swarm_prompt_only" else "project_swarm_metrics.json"
        summary["detail_metrics_path"] = str(Path(str(metrics.get("root") or "")) / detail_name)
    else:
        summary["returncode"] = metrics.get("returncode")
        summary["timed_out"] = metrics.get("timed_out")
        summary["stdout_tail"] = metrics.get("stdout_tail")
        summary["stderr_tail"] = metrics.get("stderr_tail")
        summary["detail_metrics_path"] = str(Path(str(metrics.get("root") or "")) / "codex_raw_prompt_metrics.json")
    return summary


def _run_thomas_compare(args: Any) -> tuple[str, dict[str, Any]]:
    runner = str(getattr(args, "thomas_runner", "production") or "production").strip().lower()
    if runner == "prompt_only":
        return runner, asyncio.run(run_thomas_prompt_only(args))
    return "production", asyncio.run(run_thomas_compare_swarm(args))


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.profile = str(args.profile or "").strip() or None
    if args.lanes < 1 or args.lanes > 25:
        raise SystemExit("--lanes must be between 1 and 25")
    if args.thomas_only and args.raw_only:
        raise SystemExit("--thomas-only and --raw-only cannot be used together")

    output_root = args.repo_root / "output" / "prompt_comparisons" / args.run_id
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "PROMPT.txt").write_text(str(args.project_prompt).strip() + "\n", encoding="utf-8")
    thomas_runner = str(args.thomas_runner or "production").strip().lower()

    payload: dict[str, Any] = {
        "run_id": args.run_id,
        "mode": "manual_review",
        "manual_review_required": True,
        "thomas_runner": thomas_runner,
        "prompt": str(args.project_prompt).strip(),
    }

    if not args.raw_only:
        thomas_runner, thomas_metrics = _run_thomas_compare(args)
        payload["thomas"] = _manual_review_summary("thomas", thomas_metrics, thomas_runner=thomas_runner)
    if not args.thomas_only:
        raw_metrics = run_codex_prompt_only(args)
        payload["codex_raw"] = _manual_review_summary("codex_raw_prompt", raw_metrics)

    summary_path = output_root / "comparison.json"
    legacy_summary_path = output_root / "prompt_only_comparison.json"
    serialized = json.dumps(payload, indent=2)
    summary_path.write_text(serialized, encoding="utf-8")
    legacy_summary_path.write_text(serialized, encoding="utf-8")

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Comparison: {summary_path}")
        if "thomas" in payload:
            print(
                f"Thomas runner={payload.get('thomas_runner')} "
                f"seconds={float(payload['thomas'].get('seconds') or 0):.2f} "
                f"root={payload['thomas'].get('root')}"
            )
        if "codex_raw" in payload:
            print(
                f"Raw Codex seconds={float(payload['codex_raw'].get('seconds') or 0):.2f} "
                f"root={payload['codex_raw'].get('root')}"
            )
        print("Manual review required.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
