"""Run dependency policy checks against pyproject dependencies."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from thomas.security.dependency_policy import evaluate_dependency_policy


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check dependency policy constraints.")
    parser.add_argument("--pyproject", default="pyproject.toml", help="Path to pyproject.toml.")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Emit machine-readable JSON output.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero on policy errors.")
    args = parser.parse_args(argv)

    path = Path(args.pyproject).resolve()
    report = evaluate_dependency_policy(path)

    if bool(args.as_json):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        summary = dict(report.get("summary") or {})
        print("Dependency policy check")
        print(f"- file: {report.get('pyproject_path', '')}")
        print(f"- dependencies: {summary.get('dependency_count', 0)}")
        print(f"- errors: {summary.get('error_count', 0)}")
        print(f"- warnings: {summary.get('warning_count', 0)}")

    if bool(args.strict) and not bool(report.get("ok")):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
