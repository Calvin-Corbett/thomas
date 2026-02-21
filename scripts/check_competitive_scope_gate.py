"""Enforce the competitive scope contract in docs/PROJECT_SCOPE.md.

This gate ensures the scope remains explicitly benchmarked against OpenClaw and
retains hard, measurable win conditions while keeping consumer value as the
primary product mission.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List


ROOT = Path(__file__).resolve().parent.parent
SCOPE_DOC = ROOT / "docs" / "PROJECT_SCOPE.md"
BASELINE_DOC = ROOT / "demo" / "baselines" / "openclaw.current.json"


REQUIRED_SECTIONS: List[str] = [
    "## Consumer Mission (Permanent)",
    "## Competitive Program (Release-Bound)",
    "## OpenClaw Baseline Lock",
    "## Capability Contract (Must Exist)",
    "## Hard Win Gates (Must All Pass)",
    "## Evidence Policy",
]

REQUIRED_PATTERNS: Dict[str, str] = {
    "Consumer value first": r"consumer value first",
    "Competitive is not sole purpose": r"not the sole product purpose",
    "Release-bound baseline wording": r"currently released OpenClaw baseline",
    "Pinned baseline artifact reference": r"demo/baselines/openclaw\.current\.json",
    "OpenClaw baseline mention": r"\bOpenClaw\b",
    "Task success uplift (+10pp)": r"Task Success Rate:.*\+10",
    "TTFU speed target (20%)": r"p95 Time-to-First-Useful-Output:.*20%",
    "Crash-free rate (99.5%)": r"Crash-Free Run Rate:.*99\.5%",
    "Recovery target (95% <=30s)": r"Autonomous Recovery Success.*95%.*<=30s",
    "Unsafe block target (99%)": r"Unsafe Action Block Rate:.*99%",
    "False-block cap (<=5%)": r"False Block Rate.*<=5%",
    "Cross-provider gate (>=3)": r"Cross-Provider Pass Rate:.*at least `3`",
    "Cost-per-success cap (<=5%)": r"Cost-per-Success:.*5%",
}


def _read_scope() -> str:
    try:
        return SCOPE_DOC.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"Scope gate failed: missing file: {SCOPE_DOC}")
        raise SystemExit(1)


def _validate_baseline_doc() -> str | None:
    if not BASELINE_DOC.exists():
        return f"missing baseline artifact: {BASELINE_DOC}"
    try:
        payload = json.loads(BASELINE_DOC.read_text(encoding="utf-8"))
    except Exception as e:
        return f"invalid baseline artifact JSON: {type(e).__name__}: {e}"

    if not isinstance(payload, dict):
        return "baseline artifact must be a JSON object"

    system = str(payload.get("system") or "").strip().lower()
    if system != "openclaw":
        return "baseline artifact must declare system=openclaw"

    commit = str(payload.get("commit") or "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{7,40}", commit) is None:
        return "baseline artifact must include a valid commit hash (7-40 hex chars)"

    baseline_type = str(payload.get("baseline_type") or "").strip().lower()
    if baseline_type not in {"released_snapshot", "release_tag"}:
        return "baseline artifact baseline_type must be released_snapshot or release_tag"
    return None


def run() -> int:
    text = _read_scope()
    missing_sections = [section for section in REQUIRED_SECTIONS if section not in text]
    missing_patterns = [
        label
        for label, pattern in REQUIRED_PATTERNS.items()
        if re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL) is None
    ]
    baseline_error = _validate_baseline_doc()

    if not missing_sections and not missing_patterns and baseline_error is None:
        baseline = json.loads(BASELINE_DOC.read_text(encoding="utf-8"))
        commit = str(baseline.get("commit") or "").strip()
        print("Competitive scope gate: OK")
        print(f"  file: {SCOPE_DOC}")
        print(f"  baseline artifact: {BASELINE_DOC}")
        print(f"  baseline commit: {commit}")
        print(f"  required sections: {len(REQUIRED_SECTIONS)}")
        print(f"  required metric patterns: {len(REQUIRED_PATTERNS)}")
        return 0

    print("Competitive scope gate: FAILED")
    print(f"  file: {SCOPE_DOC}")
    print(f"  baseline artifact: {BASELINE_DOC}")
    if missing_sections:
        print("  missing sections:")
        for section in missing_sections:
            print(f"    - {section}")
    if missing_patterns:
        print("  missing metric clauses:")
        for label in missing_patterns:
            print(f"    - {label}")
    if baseline_error is not None:
        print("  baseline artifact error:")
        print(f"    - {baseline_error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(run())
