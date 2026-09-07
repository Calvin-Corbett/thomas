"""python -m thomas.server.overlay path|list|show|check - the human surface of the overlay.

`list` and the GET /api/ui/overlay route show the same thing (the resolved
records grouped by kind) because both call the same resolve; there is no
second summary anywhere to drift. `check` is the seed of the phase-4 update
protocol: it exits non-zero when a record no longer resolves against the
current stock (a token key that left :root, a fragile element anchor, a
broken manifest) and says which.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from thomas.server.overlay import manifest as m
from thomas.server.overlay import paths, stock_tokens
from thomas.server.overlay.records import stock_value_for


def _load_or_exit() -> m.Manifest | None:
    try:
        return m.load()
    except m.ManifestBroken as exc:
        print(f"BROKEN: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def _grouped(loaded: m.Manifest) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for address, rec in m.resolve(loaded.records).items():
        grouped.setdefault(str(rec.get("kind")), {})[address] = rec.get("value")
    return grouped


def cmd_path(_: argparse.Namespace) -> int:
    print(paths.overlay_dir())
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    loaded = _load_or_exit()
    if loaded is None:
        print(f"no overlay at {paths.overlay_dir()} (stock Thomas)")
        return 0
    grouped = _grouped(loaded)
    if args.json:
        print(json.dumps({"overlay_id": loaded.overlay_id, "rev": loaded.rev, "overrides": grouped}, indent=1, ensure_ascii=False))
        return 0
    print(f"overlay {loaded.overlay_id} rev {loaded.rev} at {loaded.path.parent}")
    for kind, entries in grouped.items():
        print(f"  {kind}:")
        for address, value in entries.items():
            print(f"    {address} = {json.dumps(value, ensure_ascii=False)}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    loaded = _load_or_exit()
    matches = [r for r in (loaded.records if loaded else ()) if r.get("address") == args.address]
    if not matches:
        print(f"no record for {args.address}")
        return 1
    print(json.dumps(matches, indent=1, ensure_ascii=False))
    return 0


def problems(loaded: m.Manifest, stock: dict[str, dict[str, str]]) -> list[str]:
    """Records the current stock no longer resolves cleanly, one line each."""
    found: list[str] = []
    for address, rec in m.resolve(loaded.records).items():
        kind = rec.get("kind")
        if kind == "token":
            key = address.split(":")[-1]
            current = stock_value_for(address, stock)
            if not stock_tokens.is_stock_key(key, stock):
                found.append(f"{address}: {key} is no longer a stock token on :root")
            elif rec.get("stock_value") != current:
                found.append(f"{address}: stock moved under this override ({rec.get('stock_value')} -> {current})")
        elif kind == "element":
            anchor = rec.get("anchor") if isinstance(rec.get("anchor"), dict) else {}
            if anchor.get("fragile"):
                found.append(f"{address}: anchored to a minted path, may not resolve after a stock change")
        elif kind == "theme":
            value = rec.get("value") if isinstance(rec.get("value"), dict) else {}
            if value.get("derives_from") not in stock_tokens.STOCK_THEMES:
                found.append(f"{address}: derives from a theme stock no longer ships")
    return found


def cmd_check(_: argparse.Namespace) -> int:
    loaded = _load_or_exit()
    if loaded is None:
        print("no overlay (stock Thomas): nothing to check")
        return 0
    found = problems(loaded, stock_tokens.load_stock())
    for line in found:
        print(line)
    print(f"{len(found)} problem(s) in {loaded.rev} record(s)")
    return 2 if found else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m thomas.server.overlay")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("path").set_defaults(func=cmd_path)
    lst = sub.add_parser("list")
    lst.add_argument("--json", action="store_true")
    lst.set_defaults(func=cmd_list)
    show = sub.add_parser("show")
    show.add_argument("address")
    show.set_defaults(func=cmd_show)
    sub.add_parser("check").set_defaults(func=cmd_check)
    args = parser.parse_args(argv)
    return int(args.func(args))
