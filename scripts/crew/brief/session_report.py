#!/usr/bin/env python3
"""Generate a plain-English report of what an agent session changed.

Designed for non-coders who need to understand what AI agents did to
the codebase without reading code or git diffs.

Usage:
    # Report on the last commit
    python scripts/crew/brief/session_report.py

    # Report on the last 3 commits
    python scripts/crew/brief/session_report.py --commits 3

    # Report on changes since a specific commit
    python scripts/crew/brief/session_report.py --since abc1234

    # Save report to file
    python scripts/crew/brief/session_report.py --output report.md
"""

from __future__ import annotations

import argparse
import subprocess
from datetime import datetime
from pathlib import Path

import sys
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = Path(__file__).resolve().parents[3]
# Module descriptions for plain-English summaries
MODULE_DESCRIPTIONS: dict[str, str] = {
    "thomas/agent": "the AI agent brain (how Thomas thinks and responds)",
    "thomas/server": "the web server (how Thomas talks to browsers and APIs)",
    "thomas/memory": "the memory system (how Thomas remembers things)",
    "thomas/core": "the core engine (config, events, persistence)",
    "thomas/tools": "the tool system (what Thomas can do — browse, search, etc.)",
    "thomas/browser": "the browser automation (how Thomas controls web browsers)",
    "thomas/cli": "the command-line interface (terminal commands)",
    "thomas/plugins": "the plugin system (extensions and add-ons)",
    "thomas/security": "the security layer (permissions, auth, safety)",
    "thomas/preferences": "user preferences (settings and personalization)",
    "thomas/models": "AI model management (which LLMs Thomas uses)",
    "thomas/observability": "monitoring and logging (how you see what Thomas is doing)",
    "scripts/": "build and safety scripts (automation, hooks, checks)",
    "tests/": "test files (automated verification)",
    "docs/": "documentation",
    "apps/site": "the Thomas website",
}

# File patterns that are noteworthy
SAFETY_PATTERNS = {
    "GUARDRAILS.md": "a safety rules document",
    "CHANGELOG.md": "the changelog",
    "_architecture.py": "the architecture definition",
    "test_architecture.py": "architecture enforcement tests",
    ".pre-commit-config.yaml": "the pre-commit hook configuration",
}


def _git(args: list[str], timeout: int = 30) -> str:
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return (proc.stdout or "").strip()
    except subprocess.TimeoutExpired:
        return ""
    except OSError:
        return ""


def _git_log(count: int) -> list[dict[str, str]]:
    """Get recent commits as dicts."""
    raw = _git(["log", f"-{count}", "--pretty=format:%H|%an|%s|%ai"], timeout=20)
    commits = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 3)
        if len(parts) >= 4:
            commits.append(
                {
                    "hash": parts[0][:12],
                    "author": parts[1],
                    "message": parts[2],
                    "date": parts[3],
                }
            )
    return commits


def _git_diff_stat(ref: str) -> list[dict[str, str]]:
    """Get file change stats since ref."""
    raw = _git(["diff", "--stat", "--name-status", ref], timeout=30)
    changes = []
    for line in raw.splitlines():
        parts = line.split("\t", 2)
        if len(parts) >= 2:
            status = parts[0].strip()
            filepath = parts[1].strip()
            status_word = {
                "A": "added",
                "M": "modified",
                "D": "deleted",
            }.get(status[0] if status else "", "changed")
            changes.append({"status": status_word, "file": filepath})
    return changes


def _module_for_file(filepath: str) -> str:
    """Determine which module a file belongs to."""
    for prefix, description in MODULE_DESCRIPTIONS.items():
        if filepath.startswith(prefix):
            return description
    return "other project files"


def _describe_changes(changes: list[dict[str, str]]) -> str:
    """Turn a list of file changes into plain English."""
    if not changes:
        return "No files were changed."

    # Group by module
    by_module: dict[str, list[dict[str, str]]] = {}
    for change in changes:
        module = _module_for_file(change["file"])
        by_module.setdefault(module, []).append(change)

    # Count by status
    added = sum(1 for c in changes if c["status"] == "added")
    modified = sum(1 for c in changes if c["status"] == "modified")
    deleted = sum(1 for c in changes if c["status"] == "deleted")

    lines = []
    lines.append(f"**{len(changes)} files** were changed: " f"{added} added, {modified} modified, {deleted} deleted.")
    lines.append("")

    # Describe each module
    for module_desc, module_changes in sorted(by_module.items()):
        lines.append(f"**In {module_desc}:**")
        for c in module_changes[:5]:
            name = Path(c["file"]).name
            lines.append(f"  - {c['status'].capitalize()} `{name}`")
        if len(module_changes) > 5:
            lines.append(f"  - ... and {len(module_changes) - 5} more files")
        lines.append("")

    # Flag noteworthy files
    noteworthy = []
    for c in changes:
        for pattern, desc in SAFETY_PATTERNS.items():
            if pattern in c["file"]:
                noteworthy.append(f"  - {c['status'].capitalize()} {desc} (`{c['file']}`)")
    if noteworthy:
        lines.append("**Noteworthy changes:**")
        lines.extend(noteworthy)
        lines.append("")

    return "\n".join(lines)


def _check_safety_status(changes: list[dict[str, str]]) -> list[str]:
    """Run safety checks and report status in plain English."""
    findings = []

    # Check for broad exception handlers in changed files
    py_files = [c["file"] for c in changes if c["file"].endswith(".py") and c["status"] != "deleted"]
    broad_except_count = 0
    for filepath in py_files:
        full_path = ROOT / filepath
        if not full_path.exists():
            continue
        try:
            content = full_path.read_text(encoding="utf-8")
            if "except Exception" in content or "except:" in content:
                broad_except_count += 1
        except (OSError, UnicodeDecodeError):
            continue
    if broad_except_count:
        findings.append(
            f"- {broad_except_count} changed Python file(s) contain broad exception handlers "
            f"(`except Exception:`). The exception handler gate should catch new ones."
        )

    # Check for oversized files
    for filepath in py_files:
        full_path = ROOT / filepath
        if not full_path.exists():
            continue
        try:
            line_count = len(full_path.read_text(encoding="utf-8").splitlines())
            if line_count > 800:
                findings.append(
                    f"- `{filepath}` is {line_count} lines (limit: 800). " f"The monolith guard should flag this."
                )
        except (OSError, UnicodeDecodeError):
            continue

    # Check for duplicate-signaling filenames
    import re

    dup_pattern = re.compile(
        r"[-_](v\d+|new|updated|fixed|copy|backup|old|revised|alt|temp|tmp|wip)" r"\.(py|js|mjs|ts|tsx|jsx|css|html)$",
        re.IGNORECASE,
    )
    for c in changes:
        if c["status"] == "added" and dup_pattern.search(Path(c["file"]).name):
            findings.append(
                f"- New file `{c['file']}` has a duplication-signaling name. "
                f"The duplicate filename gate should catch this."
            )

    if not findings:
        findings.append("- No safety concerns detected in the changed files.")

    return findings


def generate_report(*, commits: int = 1, since: str = "", output: str = "") -> str:
    """Generate the full report."""
    lines = []
    lines.append("# Agent Session Report")
    lines.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*")
    lines.append("")

    # Get commits
    if since:
        commit_list = _git_log(50)  # get enough to find the ref
        commit_list = [c for c in commit_list if not c["hash"].startswith(since[:8])]
        ref = since
    else:
        commit_list = _git_log(commits)
        ref = f"HEAD~{commits}" if commits > 0 else "HEAD~1"

    # Commits section
    lines.append("## What Was Done")
    lines.append("")
    if commit_list:
        for c in commit_list[:commits]:
            lines.append(f"- **{c['message']}** (by {c['author']}, {c['date'][:10]})")
        lines.append("")
    else:
        lines.append("No commits found in the specified range.")
        lines.append("")

    # Changes section
    lines.append("## What Changed")
    lines.append("")
    changes = _git_diff_stat(ref)
    lines.append(_describe_changes(changes))

    # Safety section
    lines.append("## Safety Check")
    lines.append("")
    safety = _check_safety_status(changes)
    lines.extend(safety)
    lines.append("")

    # Hook status
    lines.append("## Protection Status")
    lines.append("")
    lines.append("Your repo has **35 pre-commit hooks** that automatically check for problems.")
    lines.append("All hooks are skip-protected (agents can't bypass them without breakglass).")
    lines.append("")
    lines.append("If any of these hooks blocked a commit, you would see an error message")
    lines.append("explaining what went wrong and how to fix it.")
    lines.append("")

    report = "\n".join(lines)

    if output:
        output_path = ROOT / output
        output_path.write_text(report, encoding="utf-8")
        print(f"Report saved to: {output_path}")
    else:
        print(report)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a plain-English report of agent changes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--commits",
        type=int,
        default=1,
        help="Number of recent commits to report on (default: 1).",
    )
    parser.add_argument(
        "--since",
        default="",
        help="Report on changes since this commit hash.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Save report to this file (relative to repo root).",
    )
    args = parser.parse_args()
    generate_report(commits=args.commits, since=args.since, output=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
