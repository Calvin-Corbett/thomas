#!/usr/bin/env python3
"""Extension catalog certification check."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from thomas.plugins.certification import certify_extension_catalog


def _render_text(payload: dict) -> str:
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    lines = [
        f"Catalog: {payload.get('catalog_path', '')}",
        f"Result: {'OK' if payload.get('ok') else 'FAILED'}",
        f"Total packs: {summary.get('total', 0)}",
        f"Certified: {summary.get('certified', 0)}",
        f"Uncertified: {summary.get('uncertified', 0)}",
        f"Pass rate: {summary.get('pass_rate', 0.0)}",
        f"Required capabilities: {', '.join(payload.get('required_capabilities') or [])}",
    ]
    uncertified = payload.get("uncertified") if isinstance(payload.get("uncertified"), list) else []
    if uncertified:
        lines.append("")
        lines.append("Uncertified packs:")
        for row in uncertified[:25]:
            lines.append(f"- {row.get('id', '')}: {'; '.join(str(r) for r in row.get('reasons') or [])}")
        if len(uncertified) > 25:
            lines.append(f"... {len(uncertified) - 25} more")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run extension certification checks.")
    parser.add_argument("--root", default="", help="Optional extension root path (contains catalog.json).")
    parser.add_argument(
        "--required-capability",
        action="append",
        default=[],
        help="Required capability for certification (repeatable).",
    )
    parser.add_argument("--min-pass-rate", type=float, default=0.95, help="Minimum required certification pass rate.")
    parser.add_argument("--json", dest="as_json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when certification fails.")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve() if str(args.root or "").strip() else None
    payload = certify_extension_catalog(
        root=root,
        required_capabilities=list(args.required_capability or []),
        min_pass_rate=float(args.min_pass_rate),
    )

    if bool(args.as_json):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(_render_text(payload))

    if bool(args.strict) and not bool(payload.get("ok")):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
