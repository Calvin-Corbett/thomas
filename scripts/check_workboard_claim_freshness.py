#!/usr/bin/env python3
"""Fail when active WORKBOARD claims have not been refreshed recently."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts import check_workboard_claims as claims_gate
except Exception:  # pragma: no cover
    import check_workboard_claims as claims_gate  # type: ignore


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"


def _parse_now(now_value: str | None) -> datetime:
    if not now_value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(str(now_value))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _line_commit_unix(workboard_path: Path, line_no: int) -> int | None:
    rel = workboard_path
    try:
        rel = workboard_path.resolve().relative_to(ROOT.resolve())
    except Exception:
        pass

    proc = subprocess.run(
        [
            "git",
            "blame",
            "--line-porcelain",
            "-L",
            f"{line_no},{line_no}",
            "--",
            str(rel),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    for line in (proc.stdout or "").splitlines():
        if line.startswith("author-time "):
            raw = line.split(" ", 1)[1].strip()
            try:
                return int(raw)
            except Exception:
                return None
    return None


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Require active WORKBOARD claims to be refreshed within a max age window."
    )
    parser.add_argument(
        "--workboard",
        default=str(DEFAULT_WORKBOARD),
        help="Path to workboard markdown file (default: plans/thomas/WORKBOARD.md)",
    )
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=72.0,
        help="Maximum allowed age for active claim lines in hours (default: 72).",
    )
    parser.add_argument(
        "--now",
        default="",
        help="Optional ISO-8601 current time override (for deterministic tests).",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    workboard_path = Path(args.workboard).expanduser()
    if not workboard_path.is_absolute():
        workboard_path = (ROOT / workboard_path).resolve()

    if args.max_age_hours <= 0:
        message = "--max-age-hours must be > 0"
        if args.json:
            print(
                json.dumps(
                    {
                        "gate": "workboard_claim_freshness",
                        "ok": False,
                        "error": message,
                        "workboard": str(workboard_path),
                    },
                    sort_keys=True,
                )
            )
        else:
            print("Workboard claim freshness gate: FAIL")
            print(f"- {message}")
        return 1

    try:
        now = _parse_now(args.now)
    except Exception as exc:
        message = f"invalid --now value: {exc}"
        if args.json:
            print(
                json.dumps(
                    {
                        "gate": "workboard_claim_freshness",
                        "ok": False,
                        "error": message,
                        "workboard": str(workboard_path),
                    },
                    sort_keys=True,
                )
            )
        else:
            print("Workboard claim freshness gate: FAIL")
            print(f"- {message}")
        return 1

    violations, claims = claims_gate.evaluate_claims(workboard_path)
    if violations:
        if args.json:
            print(
                json.dumps(
                    {
                        "gate": "workboard_claim_freshness",
                        "ok": False,
                        "error": "workboard claims invalid",
                        "violations": list(violations),
                        "workboard": str(workboard_path),
                    },
                    sort_keys=True,
                )
            )
        else:
            print("Workboard claim freshness gate: FAIL")
            for item in violations:
                print(f"- {item}")
        return 1

    stale_claims: list[dict[str, object]] = []
    max_age_seconds = float(args.max_age_hours) * 3600.0
    now_ts = now.timestamp()
    for claim in claims:
        claim_ts = _line_commit_unix(workboard_path, int(claim.line_no))
        if claim_ts is None:
            stale_claims.append(
                {
                    "agent": claim.agent,
                    "line_no": int(claim.line_no),
                    "issue": "missing_blame_timestamp",
                }
            )
            continue
        age_seconds = max(0.0, now_ts - float(claim_ts))
        if age_seconds > max_age_seconds:
            stale_claims.append(
                {
                    "agent": claim.agent,
                    "line_no": int(claim.line_no),
                    "age_hours": round(age_seconds / 3600.0, 2),
                    "last_update_utc": datetime.fromtimestamp(claim_ts, tz=timezone.utc).isoformat(),
                }
            )

    ok = not stale_claims
    if args.json:
        print(
            json.dumps(
                {
                    "gate": "workboard_claim_freshness",
                    "ok": ok,
                    "checked_claim_count": len(claims),
                    "stale_claim_count": len(stale_claims),
                    "max_age_hours": float(args.max_age_hours),
                    "stale_claims": stale_claims,
                    "workboard": str(workboard_path),
                },
                sort_keys=True,
            )
        )
        return 0 if ok else 1

    if not ok:
        print("Workboard claim freshness gate: FAIL")
        print(f"- stale active claims detected (max age {float(args.max_age_hours):.1f}h):")
        for item in stale_claims:
            if item.get("issue") == "missing_blame_timestamp":
                print(f"- agent `{item['agent']}` line {item['line_no']}: unable to resolve git blame timestamp")
            else:
                print(
                    f"- agent `{item['agent']}` line {item['line_no']}: "
                    f"age={item['age_hours']}h last_update={item['last_update_utc']}"
                )
        return 1

    print("Workboard claim freshness gate: PASS")
    print(f"- checked active claims: {len(claims)} (max age {float(args.max_age_hours):.1f}h)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
