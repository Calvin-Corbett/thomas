#!/usr/bin/env python3
"""Generate a task-specific briefing for AI agents before they start work.

Instead of hoping agents read every GUARDRAILS.md file, this script
reads them and produces a focused, compact briefing tailored to the
specific files and modules the agent will touch.

Usage:
    # Briefing for working on memory module
    python scripts/agent_briefing.py --modules memory

    # Briefing for working on server routes
    python scripts/agent_briefing.py --modules server

    # Briefing for a specific task (auto-detects modules)
    python scripts/agent_briefing.py --task "fix the memory curator cleanup logic"

    # Briefing for multiple modules
    python scripts/agent_briefing.py --modules memory,server,agent

    # Full briefing (all modules)
    python scripts/agent_briefing.py --full
"""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Module keywords for auto-detection from task descriptions
MODULE_KEYWORDS: dict[str, list[str]] = {
    "agent": ["agent", "loop", "response", "tone", "swarm", "guidance", "tool execution"],
    "server": ["server", "route", "api", "endpoint", "http", "web", "aiohttp", "middleware"],
    "memory": ["memory", "curator", "episodic", "fabric", "recall", "store", "rememb"],
    "core": ["core", "config", "event", "persistence", "scheduler", "rag"],
    "tools": ["tool", "browser", "search", "capability"],
    "cli": ["cli", "command", "terminal", "repl"],
    "plugins": ["plugin", "extension", "pack"],
    "security": ["security", "auth", "permission", "token"],
    "browser": ["browser", "selenium", "playwright", "automat"],
}

# Guardrails paths per module
GUARDRAILS_PATHS: dict[str, str] = {
    "agent": "thomas/agent/GUARDRAILS.md",
    "server": "thomas/server/GUARDRAILS.md",
    "memory": "thomas/memory/GUARDRAILS.md",
    "core": "thomas/core/GUARDRAILS.md",
    "tools": "thomas/tools/GUARDRAILS.md",
    "cli": "thomas/cli/GUARDRAILS.md",
    "browser": "thomas/browser/GUARDRAILS.md",
}


def _read_file(path: str) -> str:
    full = ROOT / path
    if full.exists():
        try:
            return full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""
    return ""


def _detect_modules(task: str) -> list[str]:
    """Auto-detect which modules a task description relates to."""
    task_lower = task.lower()
    matches = []
    for module, keywords in MODULE_KEYWORDS.items():
        if any(kw in task_lower for kw in keywords):
            matches.append(module)
    return matches if matches else ["general"]


def _extract_key_rules(guardrails_content: str) -> list[str]:
    """Extract the most important rules from a GUARDRAILS.md file."""
    rules = []
    current_rule = ""
    in_rule = False

    for line in guardrails_content.splitlines():
        if line.startswith("## Rule") or line.startswith("## Known Debt"):
            if current_rule:
                rules.append(current_rule.strip())
            current_rule = line + "\n"
            in_rule = True
        elif in_rule and line.startswith("## "):
            if current_rule:
                rules.append(current_rule.strip())
            current_rule = ""
            in_rule = False
        elif in_rule:
            current_rule += line + "\n"

    if current_rule:
        rules.append(current_rule.strip())

    return rules


def generate_briefing(*, modules: list[str], task: str = "") -> str:
    """Generate a focused briefing for the specified modules."""
    lines = []
    lines.append("# Agent Briefing")
    lines.append("")

    if task:
        lines.append(f"**Task:** {task}")
        lines.append(f"**Detected modules:** {', '.join(modules)}")
        lines.append("")

    # Universal rules (always include)
    lines.append("## Universal Rules (ALWAYS follow these)")
    lines.append("")
    lines.append("1. **File size limit:** No Python file over 800 lines. No exceptions.")
    lines.append("2. **No broad exceptions:** Use specific types (`except ValueError:`), not `except Exception:`.")
    lines.append("   If you MUST use broad catch, include BOTH `logger.exception()` AND `raise`.")
    lines.append("3. **No duplicate files:** Never create `_v2.py`, `_new.py`, `_fixed.py`. Fix the original.")
    lines.append("4. **Update CHANGELOG:** If you change 3+ files under thomas/, update CHANGELOG.md.")
    lines.append("5. **Don't modify guards:** Never edit GUARDRAILS.md, test_architecture.py, or _architecture.py.")
    lines.append("6. **Search before creating:** Before writing a new file, search for existing implementations.")
    lines.append("7. **Verify your work:**")
    lines.append("   ```")
    lines.append("   python -m py_compile thomas/your_file.py")
    lines.append("   python -m pytest tests/test_architecture.py -x --tb=short -q")
    lines.append("   ```")
    lines.append("")

    # Module-specific rules
    for module in modules:
        if module == "general":
            continue

        guardrails_path = GUARDRAILS_PATHS.get(module)
        if not guardrails_path:
            continue

        content = _read_file(guardrails_path)
        if not content:
            continue

        lines.append(f"## {module.title()} Module — Key Constraints")
        lines.append("")

        key_rules = _extract_key_rules(content)
        if key_rules:
            for rule in key_rules[:6]:
                # Extract just the rule header and first meaningful line
                rule_lines = rule.splitlines()
                header = rule_lines[0] if rule_lines else ""
                lines.append(f"**{header}**")
                # Get the first non-empty content line
                for rl in rule_lines[1:]:
                    stripped = rl.strip()
                    if stripped and not stripped.startswith("##") and not stripped.startswith("```"):
                        lines.append(f"  {stripped}")
                        break
                lines.append("")
        else:
            lines.append(f"  Read: {guardrails_path}")
            lines.append("")

    # Placeholder file warnings
    if "memory" in modules:
        lines.append("## CRITICAL: Memory Placeholder Files")
        lines.append("")
        lines.append("**DO NOT EDIT these files — they are stubs, not real implementations:**")
        lines.append("- `thomas/memory/episodic.py`")
        lines.append("- `thomas/memory/episodic_store.py`")
        lines.append("- `thomas/memory/summarization.py`")
        lines.append("")
        lines.append("If you need this functionality, create a NEW file with a descriptive name.")
        lines.append("")

    # Monolith warnings for specific modules
    monolith_warnings: dict[str, list[str]] = {
        "agent": [
            "loop.py is 2500+ lines — DO NOT add to it. Plan a split first.",
            "swarm.py is 930+ lines — DO NOT add to it.",
            "response_tone.py is 827+ lines — DO NOT add to it.",
        ],
        "server": [
            "mission.py is 2500+ lines — DO NOT add to it. Plan a split first.",
            "app.py is 1500+ lines — DO NOT add to it.",
        ],
        "memory": [
            "curator.py is 1130+ lines — DO NOT add to it. Plan a split first.",
            "v2/fabric.py is 1170+ lines — DO NOT add to it.",
        ],
    }
    for module in modules:
        warnings = monolith_warnings.get(module)
        if warnings:
            lines.append(f"## {module.title()} — Monolith Files (DO NOT GROW)")
            lines.append("")
            for w in warnings:
                lines.append(f"- {w}")
            lines.append("")

    # Pre-commit reminder
    lines.append("## Before You Commit")
    lines.append("")
    lines.append("Your commit will be checked by 35 pre-commit hooks. If any fail:")
    lines.append("1. Read the error message — it tells you exactly what's wrong.")
    lines.append("2. Fix your code, not the test or the hook.")
    lines.append("3. If you're stuck, ask the user.")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a task-specific briefing for AI agents.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--modules",
        default="",
        help="Comma-separated module names (e.g., memory,server,agent).",
    )
    parser.add_argument(
        "--task",
        default="",
        help="Task description (auto-detects relevant modules).",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Generate briefing for ALL modules.",
    )
    args = parser.parse_args()

    if args.full:
        modules = list(GUARDRAILS_PATHS.keys())
    elif args.modules:
        modules = [m.strip() for m in args.modules.split(",")]
    elif args.task:
        modules = _detect_modules(args.task)
    else:
        modules = ["general"]

    briefing = generate_briefing(modules=modules, task=args.task)
    print(briefing)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
