"""Bible Status — one-line and detailed snapshot of bible health.

Designed for agent session-start: run this when you boot in the
Thomas repo and you immediately know whether the bible is healthy,
stale, or broken. Replaces five separate `bible_*.py` invocations
with a single rollup.

Output (default, human-readable):

    Bible: HEALTHY  |  80 sections  |  100% covered  |  10 drifted, 2 stubs

    Top drifted (oldest first):
      - 16d  Pattern 16 — Test patches need re-export reachability
      - 14d  Pattern 8 — Misleading package docstring on real code
      ...

    Auto-stubs awaiting fill (2):
      - Auto-stub: thomas/newthing/
      - Auto-stub: thomas/otherthing/

Output (with --json): structured payload for tooling.

Exit codes:
    0 = healthy (bible exists, lint passes, no truly-uncovered paths)
    1 = bible structure broken (lint errors)
    2 = uncovered paths exist (you should add bible coverage)
    3 = severe drift (more than --max-drifted sections drifted)
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BIBLE = ROOT / "docs" / "THOMAS_BIBLE.md"
SCRIPTS = ROOT / "scripts"


def _utf8_stdout() -> None:
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def _find_repo(start: Path):
    cur = start.resolve()
    for parent in [cur, *cur.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def _run_json(script: str, *args: str) -> dict | None:
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args, "--json"],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if out.returncode > 1:
        return None  # script error
    try:
        return json.loads(out.stdout)
    except (ValueError, Exception):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bible", type=Path, default=DEFAULT_BIBLE)
    parser.add_argument("--repo", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--max-drifted", type=int, default=50, help="Sections drifted before status is degraded.")
    parser.add_argument("--detail", action="store_true", help="Print top drifted sections + auto-stub list.")
    args = parser.parse_args()

    _utf8_stdout()

    if not args.bible.exists():
        if args.json:
            print(json.dumps({"status": "missing", "bible": str(args.bible)}))
        else:
            print(f"Bible: MISSING ({args.bible})")
        return 0  # not present = no enforcement

    repo = args.repo or _find_repo(args.bible.parent)
    if repo is None:
        if args.json:
            print(json.dumps({"status": "no-repo"}))
        else:
            print("Bible: NO REPO (cannot run freshness/coverage)")
        return 0

    # Run all three subscripts
    lint = _run_json("bible_lint.py", "--bible", str(args.bible), "--repo", str(repo))
    freshness = _run_json("bible_freshness.py", "--bible", str(args.bible), "--repo", str(repo))
    coverage = _run_json("bible_coverage.py", "--bible", str(args.bible), "--repo", str(repo))

    # Aggregate
    sections = freshness["sections"] if freshness else []
    drifted = [s for s in sections if s.get("status") == "drifted"]
    stubs = [s for s in sections if s.get("title", "").lower().startswith("auto-stub:")]
    in_sync = [s for s in sections if s.get("status") == "in-sync"]
    level_counts: dict[str, int] = {"L1": 0, "L2": 0, "L3": 0, "L4": 0, "L5": 0}
    for s in sections:
        eff = s.get("effective_level", "L3")
        level_counts[eff] = level_counts.get(eff, 0) + 1

    lint_ok = bool(lint and lint.get("ok"))
    lint_warns = len(lint.get("warnings", [])) if lint else 0

    uncovered_count = len(coverage.get("uncovered", [])) if coverage else 0
    transitive_count = len(coverage.get("transitive_only", [])) if coverage else 0
    total_units = coverage.get("total_units", 0) if coverage else 0
    covered_count = total_units - uncovered_count
    cov_pct = (100.0 * covered_count / total_units) if total_units else 0.0

    # Determine status
    rc = 0
    status = "HEALTHY"
    if not lint_ok:
        status = "LINT_BROKEN"
        rc = 1
    elif uncovered_count:
        status = "UNCOVERED"
        rc = 2
    elif len(drifted) > args.max_drifted:
        status = "STALE"
        rc = 3

    if args.json:
        print(
            json.dumps(
                {
                    "status": status,
                    "sections": len(sections),
                    "in_sync": len(in_sync),
                    "drifted": len(drifted),
                    "stubs": len(stubs),
                    "lint_ok": lint_ok,
                    "lint_warnings": lint_warns,
                    "uncovered_units": uncovered_count,
                    "transitive_units": transitive_count,
                    "coverage_pct": round(cov_pct, 1),
                    "top_drifted": [
                        {"title": s["title"], "drift_days": s["drift_days"]}
                        for s in sorted(drifted, key=lambda x: -(x.get("drift_days") or 0))[:10]
                    ],
                    "auto_stubs": [s["title"] for s in stubs],
                },
                indent=2,
            )
        )
        return rc

    # Human-readable
    marker = {
        "HEALTHY": "OK",
        "LINT_BROKEN": "FAIL",
        "UNCOVERED": "GAP",
        "STALE": "STALE",
        "missing": "MISSING",
        "no-repo": "NO-REPO",
    }.get(status, status)
    level_str = "  ".join(f"{lvl}:{n}" for lvl, n in level_counts.items() if n)
    print(
        f"Bible: {marker} {status}  |  "
        f"{len(sections)} sections  |  "
        f"{cov_pct:.0f}% covered ({covered_count}/{total_units}, {uncovered_count} uncovered)  |  "
        f"{len(drifted)} drifted, {len(stubs)} stubs"
    )
    print(f"  Trust levels (effective): {level_str}")
    # xfail debt accounting (P0-1 from 2026-05-27 senior review).
    # Best-effort: silent if the inventory tool isn't importable for any
    # reason — bible_status should always be runnable.
    try:
        # Add repo root to sys.path so `scripts.xfail_inventory` resolves
        # regardless of how this script was invoked.
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from scripts.xfail_inventory import find_xfails

        _xfails = find_xfails()
        if _xfails:
            _files = len({e.file for e in _xfails})
            print(f"  xfail debt: {len(_xfails)} across {_files} test files (see docs/XFAIL_POLICY.md)")
    except Exception:
        # Stay silent; bible_status must always succeed.
        pass
    if not lint_ok:
        print(f"  lint errors: {len(lint.get('errors', []))}")
        for e in lint.get("errors", [])[:5]:
            print(f"    - {e}")

    if args.detail or rc != 0:
        if drifted:
            top = sorted(drifted, key=lambda x: -(x.get("drift_days") or 0))[:10]
            print("\nTop drifted (oldest first):")
            for s in top:
                print(f"  {s['drift_days']:4d}d  {s['title']}")
            if len(drifted) > 10:
                print(f"  ... and {len(drifted) - 10} more (run: python scripts/bible_query.py --drifted)")

        if stubs:
            print(f"\nAuto-stubs awaiting fill ({len(stubs)}):")
            for s in stubs[:10]:
                print(f"  - {s['title']}")
            if len(stubs) > 10:
                print(f"  ... and {len(stubs) - 10} more")

        if uncovered_count and coverage:
            print(f"\nUncovered units ({uncovered_count}):")
            for u in coverage.get("uncovered", [])[:10]:
                print(f"  + {u}")
            if uncovered_count > 10:
                print(f"  ... and {uncovered_count - 10} more")

    return rc


if __name__ == "__main__":
    sys.exit(main())
