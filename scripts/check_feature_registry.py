#!/usr/bin/env python3
"""Validate feature registry entries point to existing domain paths."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "docs" / "ai" / "FEATURE_REGISTRY.md"
PATH_PATTERN = re.compile(r"`(thomas/[a-zA-Z0-9_./-]+)`")


def _extract_paths(markdown: str) -> list[str]:
    out: list[str] = []
    for line in markdown.splitlines():
        if "|" not in line:
            continue
        match = PATH_PATTERN.search(line)
        if match:
            out.append(match.group(1).strip())
    return sorted(set(out))


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY), help="Feature registry markdown path.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable output.")
    args = parser.parse_args(argv)

    registry_path = Path(args.registry).resolve()
    if not registry_path.exists():
        payload: dict[str, Any] = {"ok": False, "error": f"registry missing: {registry_path}"}
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"Feature registry check: FAIL ({payload['error']})")
        return 1

    text = registry_path.read_text(encoding="utf-8")
    paths = _extract_paths(text)
    missing = [p for p in paths if not (ROOT / p).exists()]

    payload = {
        "ok": not missing,
        "registry": str(registry_path),
        "entry_count": len(paths),
        "missing_paths": missing,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        if payload["ok"]:
            print(f"Feature registry check: PASS ({len(paths)} domain path entries)")
        else:
            print("Feature registry check: FAIL")
            for item in missing:
                print(f"- missing path from registry: {item}")

    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(run())
