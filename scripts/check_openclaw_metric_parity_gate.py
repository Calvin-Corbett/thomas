"""Enforce metric-by-metric CLI parity against the pinned OpenClaw baseline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import compare_openclaw_baseline as compare


DEFAULT_BASELINE = compare.DEFAULT_BASELINE


def _evaluate_cli_parity(result: dict[str, Any]) -> dict[str, Any]:
    cli = dict(result.get("cli") or {})
    thomas_top = int(cli.get("thomas_top_level_commands") or 0)
    openclaw_top = int(cli.get("openclaw_top_level_commands") or 0)
    thomas_depth_total = int(cli.get("thomas_depth_total") or 0)
    openclaw_depth_total = int(cli.get("openclaw_depth_total") or 0)

    thomas_depth = dict(cli.get("thomas_subcommand_depth") or {})
    openclaw_depth = dict(cli.get("openclaw_subcommand_depth") or {})

    checks: list[dict[str, Any]] = []

    checks.append(
        {
            "metric": "cli.top_level_commands",
            "thomas": thomas_top,
            "openclaw": openclaw_top,
            "pass": thomas_top >= openclaw_top,
        }
    )
    checks.append(
        {
            "metric": "cli.depth_total",
            "thomas": thomas_depth_total,
            "openclaw": openclaw_depth_total,
            "pass": thomas_depth_total >= openclaw_depth_total,
        }
    )

    for command_name, openclaw_depth_value in sorted(openclaw_depth.items()):
        openclaw_val = int(openclaw_depth_value or 0)
        thomas_val = int(thomas_depth.get(command_name) or 0)
        checks.append(
            {
                "metric": f"cli.depth.{command_name}",
                "thomas": thomas_val,
                "openclaw": openclaw_val,
                "pass": thomas_val >= openclaw_val,
            }
        )

    failures = [row for row in checks if not bool(row.get("pass"))]
    return {
        "ok": not failures,
        "checks": checks,
        "failures": failures,
        "summary": {
            "total_checks": len(checks),
            "failed_checks": len(failures),
            "passed_checks": len(checks) - len(failures),
        },
    }


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check OpenClaw metric parity gate.")
    parser.add_argument(
        "--baseline",
        default=str(DEFAULT_BASELINE),
        help=f"Baseline artifact path (default: {DEFAULT_BASELINE})",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output.")
    args = parser.parse_args(argv)

    baseline_path = Path(args.baseline)
    if not baseline_path.is_absolute():
        baseline_path = (ROOT / baseline_path).resolve()

    spec = compare._load_baseline(baseline_path)
    result = compare._build_result(spec)
    parity = _evaluate_cli_parity(result)

    payload = {
        "ok": bool(parity.get("ok")),
        "baseline_file": str(baseline_path),
        "openclaw_commit": str(result.get("comparison_source", {}).get("openclaw_commit") or ""),
        "summary": dict(parity.get("summary") or {}),
        "failures": list(parity.get("failures") or []),
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if payload["ok"]:
            print("OpenClaw metric parity gate: OK")
            print(f"  baseline file: {payload['baseline_file']}")
            print(f"  openclaw commit: {payload['openclaw_commit']}")
            print(f"  checks: {payload['summary'].get('passed_checks')}/{payload['summary'].get('total_checks')}")
        else:
            print("OpenClaw metric parity gate: FAILED")
            print(f"  baseline file: {payload['baseline_file']}")
            print(f"  openclaw commit: {payload['openclaw_commit']}")
            print("  failing metrics:")
            for row in payload["failures"]:
                print(
                    f"    - {row.get('metric')}: "
                    f"Thomas={row.get('thomas')} OpenClaw={row.get('openclaw')}"
                )

    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(run())
