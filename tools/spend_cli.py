#!/usr/bin/env python3
"""Feature 14 v3 CLI: quick spend check.

Usage:
  python tools/spend_cli.py today
  python tools/spend_cli.py session
  python tools/spend_cli.py history 30
  python tools/spend_cli.py tail 20
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from thomas.core.cost_tracker import get_cost_tracker


def die(msg: str) -> None:
    print(msg)
    sys.exit(1)


def cmd_today():
    ct = get_cost_tracker()
    print(f"today_usd={ct.today_usd():.6f} calls={ct.today_call_count()} tokens={ct.today_tokens()}")
    for m, row in ct.today_by_model_detail().items():
        print(f"  {m:28} usd={row['usd']:.6f} tok={row['total_tokens']} calls={row['calls']}")


def cmd_session():
    ct = get_cost_tracker()
    print(f"session_usd={ct.session_usd():.6f} calls={ct.session_call_count()} tokens={ct.session_tokens()}")
    for m, row in ct.session_by_model_detail().items():
        print(f"  {m:28} usd={row['usd']:.6f} tok={row['total_tokens']} calls={row['calls']}")


def cmd_history(days: int):
    ct = get_cost_tracker()
    rows = ct.by_day(days=days)
    for r in rows:
        print(f"{r['date']}\t{float(r['usd']):.6f}")


def cmd_tail(n: int):
    path = Path.cwd() / "thomas_spend.jsonl"
    if not path.exists():
        die("thomas_spend.jsonl not found in current directory (run from repo root).")
    lines = path.read_text(encoding="utf-8").splitlines()
    for line in lines[-n:]:
        try:
            obj = json.loads(line)
            print(f"{obj.get('ts','')} {obj.get('provider','')} {obj.get('model','')} usd={obj.get('usd_total',0)} pt={obj.get('prompt_tokens',0)} ct={obj.get('completion_tokens',0)}")
        except Exception:
            print(line)


def main():
    if len(sys.argv) < 2:
        die("usage: spend_cli.py today|session|history <days>|tail <n>")
    cmd = sys.argv[1]
    if cmd == "today":
        cmd_today()
    elif cmd == "session":
        cmd_session()
    elif cmd == "history":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        cmd_history(days)
    elif cmd == "tail":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        cmd_tail(n)
    else:
        die("unknown command")


if __name__ == "__main__":
    main()
