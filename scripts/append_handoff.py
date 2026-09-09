"""Append a timestamped handoff entry for future agents.

Usage:
  python scripts/append_handoff.py --title "Checkpoint" --note "Did X" --note "Next: Y"
"""

from __future__ import annotations

import argparse
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG = ROOT / "docs" / "ops" / "agent_handoff_log.md"


def _git_info() -> tuple[str, str]:
    try:
        head = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:
        head = "unknown"
    try:
        branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip()
    except Exception:
        branch = "unknown"
    return head, branch


def main() -> int:
    parser = argparse.ArgumentParser(description="Append a timestamped handoff note.")
    parser.add_argument("--title", default="Handoff Update", help="Short section title.")
    parser.add_argument(
        "--note",
        action="append",
        default=[],
        help="Bullet note to include. Repeat for multiple bullets.",
    )
    parser.add_argument(
        "--log",
        default=str(DEFAULT_LOG),
        help="Path to handoff markdown file.",
    )
    args = parser.parse_args()

    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    head, branch = _git_info()
    notes = args.note or ["No notes provided."]

    lines = ["", f"## {timestamp}", "", f"### {args.title}", "", f"- Branch: `{branch}`", f"- HEAD: `{head}`"]
    lines.extend(f"- {note}" for note in notes)
    lines.append("")

    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Appended handoff entry to {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
