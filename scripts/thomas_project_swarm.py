"""Run the Thomas-native Pac-Man project swarm benchmark."""

# ruff: noqa: E402 - script execution needs repo root on sys.path before local imports.

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from thomas.demo.project_swarm_runner import run_codex_baseline, run_thomas_project_swarm

WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=f"project_swarm_pacman_{time.strftime('%Y%m%d_%H%M%S')}")
    parser.add_argument("--lanes", type=int, default=25)
    parser.add_argument("--max-concurrency", type=int, default=8)
    parser.add_argument("--profile", default="")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--workboard", type=Path, default=WORKBOARD)
    parser.add_argument("--agent", default="thomas-project-swarm-coordinator")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--keep-claims", action="store_true")
    parser.add_argument("--codex-baseline", action="store_true")
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument("--baseline-timeout", type=int, default=900)
    parser.add_argument("--baseline-reuse-dir", default="")
    parser.add_argument("--baseline-elapsed-seconds", type=float, default=0.0)
    parser.add_argument("--json", action="store_true")
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.profile = str(args.profile or "").strip() or None
    if args.lanes < 1 or args.lanes > 25:
        raise SystemExit("--lanes must be between 1 and 25")
    payload = {"run_id": args.run_id}
    summary_path = args.repo_root / "output" / "benchmarks" / args.run_id / "project_swarm_comparison.json"
    metrics_path = args.repo_root / "output" / "benchmarks" / args.run_id / "thomas_swarm" / "project_swarm_metrics.json"
    if args.baseline_only:
        if metrics_path.exists():
            payload["thomas"] = json.loads(metrics_path.read_text(encoding="utf-8"))
    else:
        payload["thomas"] = asyncio.run(run_thomas_project_swarm(args))
    if args.codex_baseline or args.baseline_only:
        payload["codex_baseline"] = run_codex_baseline(args)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        thomas_metrics = dict(payload.get("thomas") or {})
        print(
            "Thomas project swarm: "
            f"passed={thomas_metrics.get('passed', 0)} seconds={float(thomas_metrics.get('seconds') or 0):.2f}"
        )
        if "codex_baseline" in payload:
            baseline = payload["codex_baseline"]
            print(f"Codex baseline: passed={baseline['passed']} seconds={baseline['seconds']:.2f}")
        print(f"Summary: {summary_path}")
    thomas_ok = int(dict(payload.get("thomas") or {}).get("passed") or 0) == 1
    baseline_ok = "codex_baseline" not in payload or int(payload["codex_baseline"]["passed"]) == 1
    return 0 if thomas_ok and baseline_ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
