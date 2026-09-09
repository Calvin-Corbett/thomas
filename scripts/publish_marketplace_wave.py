#!/usr/bin/env python3
"""Promote selected extension packs into the hosted Thomas marketplace store."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from thomas.marketplace.publisher import (
    DEFAULT_EXTENSIONS_ROOT,
    DEFAULT_HOSTED_STORE_ROOT,
    publish_marketplace_wave,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publish curated extension packs into the hosted marketplace store.")
    parser.add_argument("--extensions-root", default=str(DEFAULT_EXTENSIONS_ROOT), help="Extensions catalog root.")
    parser.add_argument("--hosted-store-root", default=str(DEFAULT_HOSTED_STORE_ROOT), help="Hosted store output root.")
    parser.add_argument("--plugin-id", action="append", default=[], help="Explicit plugin id to publish (repeatable).")
    parser.add_argument("--family", action="append", default=[], help="Selector token for future promotion waves.")
    parser.add_argument(
        "--write", action="store_true", help="Write bundle.zip and manifest.json into the hosted store."
    )
    parser.add_argument("--json", dest="as_json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    report = publish_marketplace_wave(
        extensions_root=Path(args.extensions_root).expanduser().resolve(),
        hosted_store_root=Path(args.hosted_store_root).expanduser().resolve(),
        plugin_ids=list(args.plugin_id or []),
        families=list(args.family or []),
        dry_run=not bool(args.write),
    )

    if bool(args.as_json):
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            json.dumps(
                {
                    "published": len(report.get("published") or []),
                    "skipped": len(report.get("skipped") or []),
                    "errors": len(report.get("errors") or []),
                    "dry_run": bool(report.get("dry_run")),
                },
                ensure_ascii=False,
            )
        )

    return 0 if not report.get("errors") else 1


if __name__ == "__main__":
    raise SystemExit(main())
