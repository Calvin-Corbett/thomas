from __future__ import annotations

import argparse
import json
import sys

from .tasks import format_task, sample_tasks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simple todo fixture CLI.")
    parser.add_argument("--list", action="store_true", help="Print all tasks.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    tasks = sample_tasks()
    if args.list:
        sys.stdout.write("\n".join(format_task(task) for task in tasks) + "\n")
        return 0
    sys.stdout.write(json.dumps({"count": len(tasks)}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
