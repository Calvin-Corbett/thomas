#!/usr/bin/env python3
"""Watch for the fleet shipping nothing.

Every guard Thomas owns looks for too much. `bulk_commit_guard` refuses a
commit that touches too many files; `commit_growth_guard` refuses a file that
grows too many lines; `monolith_guard` refuses a module that gets too long.
Nothing looked for too little. On 2026-09-02 five agents held claims and landed
zero commits for twelve hours, and every one of those guards read clean the
whole time - a jammed fleet scores better against them than a working one.

These three detectors point the other way. They answer, from git and the board
alone with no new plumbing:

* ``STALL`` - agents are holding scope and nothing is landing.
* ``UNVERSIONED TOOLING`` - the commit path is gated by files that are
  themselves uncommitted, so an unreviewed edit can brick every agent.
* ``UNTRACKED PLANS`` - an active task's PLAN.md is untracked, which the plan
  gate reads from the git index and can therefore never accept. That is a
  bootstrap paradox: the commit that would track the plan is the commit the
  gate refuses.

`manager.py --sweep-inactive` is the nearest existing thing and answers a
different question - it notices an agent whose heartbeat stopped, and releases
its claims. These notice work not landing while agents are perfectly alive.

Read-only, and it always exits zero. This reports; a detector that could block
a commit would join the problem it exists to find.

Usage:
    python scripts/forge/fleet_stall.py
    python scripts/forge/fleet_stall.py --json
    python scripts/forge/fleet_stall.py --stall-hours 6
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORKBOARD = ROOT / "plans" / "thomas" / "WORKBOARD.md"
GATE_DIR = ROOT / "scripts" / "forge" / "gates"
COMMIT_TOOLS = (
    "scripts/crew/brief/commit.py",
    "scripts/forge/commit_master.py",
)
DEFAULT_STALL_HOURS = 8
NO_FINDING = "none"
MAX_DETAIL_LINES = 3


def _git(*args: str, repo: Path | None = None) -> str:
    """Run git and decode as UTF-8.

    Not the platform default: a single 0x9d byte in the workboard - half a
    curly quote inside one message row - crashed a gate that captured git
    output as cp1252 text, and the failure surfaced as the workboard appearing
    absent from the index. Ask for the encoding the repo actually uses.
    """
    proc = subprocess.run(
        ("git", *args),
        cwd=str(repo or ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return proc.stdout if proc.returncode == 0 else ""


@dataclass
class Report:
    stall: list[str] = field(default_factory=list)
    unversioned: list[str] = field(default_factory=list)
    untracked_plans: list[str] = field(default_factory=list)
    hours: int = DEFAULT_STALL_HOURS

    @property
    def quiet(self) -> bool:
        return not (self.stall or self.unversioned or self.untracked_plans)


def claim_agents(board_text: str) -> list[str]:
    """Agents holding a claim row, in board order, deduplicated."""
    agents: list[str] = []
    for line in board_text.splitlines():
        match = re.match(r"- agent=([^;]+);", line.strip())
        if not match:
            continue
        agent = match.group(1).strip()
        if agent and agent not in agents:
            agents.append(agent)
    return agents


def task_plan_rows(board_text: str) -> list[tuple[str, str]]:
    """(task_id, plan path) for every board row that names a plan file."""
    rows: list[tuple[str, str]] = []
    for line in board_text.splitlines():
        text = line.strip()
        if not text.startswith("- task_id=") or "plan=" not in text:
            continue
        task = re.search(r"task_id=(.+?); ", text)
        plan = re.search(r"plan=(.+?)(?:; |$)", text)
        if task and plan:
            rows.append((task.group(1).strip(), plan.group(1).strip()))
    return rows


def _commits_since(hours: int, repo: Path | None = None) -> list[str]:
    since = (datetime.now(timezone.utc) - timedelta(hours=max(1, hours))).isoformat()
    out = _git("log", f"--since={since}", "--format=%H", repo=repo)
    return [line for line in out.splitlines() if line.strip()]


def _tracked(path: str, repo: Path | None = None) -> bool:
    return bool(_git("ls-files", "--", path, repo=repo).strip())


def _dirty(path: str, repo: Path | None = None) -> bool:
    return bool(_git("status", "--porcelain", "--", path, repo=repo).strip())


def find_stall(board_text: str, hours: int, repo: Path | None = None) -> list[str]:
    """Agents holding scope while nothing lands."""
    agents = claim_agents(board_text)
    if not agents:
        return []
    if _commits_since(hours, repo=repo):
        return []
    return [
        f"{len(agents)} agent(s) hold claims and 0 commits landed in {hours}h: "
        + ", ".join(f"`{agent}`" for agent in agents)
    ]


def find_unversioned_tooling(repo: Path | None = None, gate_dir: Path | None = None) -> list[str]:
    """Gates and commit tools that are not themselves committed.

    A gate file nobody has reviewed can refuse every agent in the repo, and the
    only trace is that commits stop. That happened: an untracked gate wired
    into an uncommitted commit.py blocked the whole fleet, its own author
    included.
    """
    findings: list[str] = []
    base = repo or ROOT
    for gate in sorted((gate_dir or GATE_DIR).glob("*.py")):
        rel = gate.relative_to(base).as_posix()
        if not _tracked(rel, repo=repo):
            findings.append(f"gate is untracked and still gating: `{rel}`")
    for tool in COMMIT_TOOLS:
        if not (base / tool).exists():
            continue
        if not _tracked(tool, repo=repo):
            findings.append(f"commit tool is untracked: `{tool}`")
        elif _dirty(tool, repo=repo):
            findings.append(f"commit tool is uncommitted-modified: `{tool}`")
    return findings


def find_untracked_plans(board_text: str, repo: Path | None = None) -> list[str]:
    """Active tasks whose PLAN.md the plan gate can never accept.

    The plan gate reads each PLAN.md from the git index. An untracked plan does
    not exist there, so the gate refuses - including the very commit that would
    track it.
    """
    findings: list[str] = []
    for task_id, plan in task_plan_rows(board_text):
        if not plan.endswith(".md"):
            continue
        if not _tracked(plan, repo=repo):
            findings.append(f"`{task_id}` PLAN is untracked so the plan gate cannot pass: `{plan}`")
    return findings


def build_report(
    workboard: Path = DEFAULT_WORKBOARD,
    hours: int = DEFAULT_STALL_HOURS,
    repo: Path | None = None,
    gate_dir: Path | None = None,
) -> Report:
    try:
        board_text = workboard.read_text(encoding="utf-8")
    except OSError as exc:
        # Say why rather than printing a clean zero from an instrument that
        # never read anything.
        return Report(stall=[f"unavailable ({exc})"], hours=hours)
    return Report(
        stall=find_stall(board_text, hours, repo=repo),
        unversioned=find_unversioned_tooling(repo=repo, gate_dir=gate_dir),
        untracked_plans=find_untracked_plans(board_text, repo=repo),
        hours=hours,
    )


def render(report: Report) -> str:
    lines: list[str] = []
    for label, findings in (
        ("STALL", report.stall),
        ("UNVERSIONED TOOLING", report.unversioned),
        ("UNTRACKED PLANS", report.untracked_plans),
    ):
        if not findings:
            lines.append(f"{label}: {NO_FINDING}")
            continue
        lines.append(f"{label}: {len(findings)}")
        for finding in findings[:MAX_DETAIL_LINES]:
            lines.append(f"  - {finding}")
        if len(findings) > MAX_DETAIL_LINES:
            lines.append(f"  - ... and {len(findings) - MAX_DETAIL_LINES} more")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workboard", default=str(DEFAULT_WORKBOARD))
    parser.add_argument("--stall-hours", type=int, default=DEFAULT_STALL_HOURS)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = build_report(Path(args.workboard), args.stall_hours)
    if args.json:
        print(json.dumps({
            "stall": report.stall,
            "unversioned_tooling": report.unversioned,
            "untracked_plans": report.untracked_plans,
            "stall_hours": report.hours,
            "quiet": report.quiet,
        }, indent=2))
    else:
        print(render(report))
    # Always zero. This reports; refusing would make it part of the problem.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
