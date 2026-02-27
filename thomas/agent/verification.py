"""Post-action verification hooks for Thomas agent loop.

Inspired by Claude Code's verification-first architecture:
after every tool execution that modifies files, run lightweight
checks to catch errors before they compound.

Hooks:
  - Python syntax check (py_compile) on .py files
  - Import smoke test on modified Python modules
  - File size guard (GUARDRAILS.md limits)
  - Optional lint check via ruff
"""

from __future__ import annotations

import asyncio
import logging
import py_compile
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# File size limits from GUARDRAILS.md
_SIZE_LIMITS = {
    ".py": {"soft": 800, "hard": 1200},
    ".js": {"soft": 800, "hard": 2000},
    ".mjs": {"soft": 800, "hard": 2000},
    ".css": {"soft": 600, "hard": 1200},
    ".html": {"soft": 2000, "hard": 3000},
}


def _is_write_tool(tool_name: str) -> bool:
    """Check if a tool modifies files."""
    write_patterns = {
        "fs.write",
        "fs.create",
        "fs.edit",
        "fs.append",
        "fs.replace",
        "fs.rename",
        "fs.move",
        "fs.delete",
        "fs.mkdir",
        "shell.exec",
        "shell.run",  # may create files
        "git.commit",
        "git.apply",
    }
    name_lower = tool_name.lower()
    return any(p in name_lower for p in write_patterns)


def _extract_file_path(tool_name: str, args: dict[str, Any]) -> str | None:
    """Extract the file path from tool arguments."""
    for key in ("path", "file", "filename", "filepath", "file_path", "target"):
        val = args.get(key)
        if val and isinstance(val, str):
            return val
    return None


async def verify_after_tool(
    tool_name: str,
    args: dict[str, Any],
    result_ok: bool,
    sandbox_root: str | None = None,
    *,
    enable_lint: bool = False,
) -> list[dict[str, Any]]:
    """Run post-tool verification checks.

    Returns a list of warning/error dicts, empty if all checks pass.
    Each dict has: {"level": "warning"|"error", "check": str, "message": str}
    """
    if not result_ok:
        return []  # Don't verify failed tool calls

    if not _is_write_tool(tool_name):
        return []

    file_path = _extract_file_path(tool_name, args)
    if not file_path:
        return []

    issues: list[dict[str, Any]] = []
    path = Path(file_path)

    # Resolve relative paths against sandbox
    if sandbox_root and not path.is_absolute():
        path = Path(sandbox_root) / path

    if not path.exists():
        return []  # File was deleted or doesn't exist

    # --- Check 1: File size limits ---
    try:
        line_count = len(path.read_bytes().split(b"\n"))
        suffix = path.suffix.lower()
        limits = _SIZE_LIMITS.get(suffix)
        if limits:
            if line_count > limits["hard"]:
                issues.append(
                    {
                        "level": "error",
                        "check": "file_size",
                        "message": (
                            f"{path.name}: {line_count} lines exceeds hard limit "
                            f"of {limits['hard']} for {suffix} files. "
                            f"Split this file before proceeding."
                        ),
                    }
                )
            elif line_count > limits["soft"]:
                issues.append(
                    {
                        "level": "warning",
                        "check": "file_size",
                        "message": (
                            f"{path.name}: {line_count} lines exceeds soft limit "
                            f"of {limits['soft']} for {suffix} files. "
                            f"Consider splitting."
                        ),
                    }
                )
    except OSError as oe:
        log.debug("File size check failed for %s: %s", path, oe)

    # --- Check 2: Python syntax validation ---
    if path.suffix.lower() == ".py":
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as pce:
            issues.append(
                {
                    "level": "error",
                    "check": "syntax",
                    "message": f"{path.name}: Syntax error — {pce}",
                }
            )

    # --- Check 3: Python import smoke test ---
    if path.suffix.lower() == ".py" and not any(i["check"] == "syntax" for i in issues):
        # Only try import if syntax is valid
        module_parts = []
        for parent in reversed(path.parents):
            init = parent / "__init__.py"
            if init.exists():
                module_parts.insert(0, parent.name)
            else:
                break
        if module_parts:
            module_name = ".".join(module_parts + [path.stem])
            try:
                proc = await asyncio.create_subprocess_exec(
                    "python",
                    "-c",
                    f"import {module_name}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=sandbox_root or ".",
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
                if proc.returncode != 0:
                    err_text = stderr.decode("utf-8", errors="replace").strip()
                    # Only report if it's a real import error, not a missing dependency
                    if "ModuleNotFoundError" not in err_text:
                        issues.append(
                            {
                                "level": "warning",
                                "check": "import",
                                "message": f"{path.name}: Import check failed — {err_text[:200]}",
                            }
                        )
            except (asyncio.TimeoutError, OSError) as exc:
                log.debug("Import check timed out for %s: %s", path, exc)

    # --- Check 4: Optional lint ---
    if enable_lint and path.suffix.lower() == ".py":
        try:
            proc = await asyncio.create_subprocess_exec(
                "python",
                "-m",
                "ruff",
                "check",
                "--select=E,F",
                str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode != 0:
                lint_out = stdout.decode("utf-8", errors="replace").strip()
                error_count = lint_out.count("\n") + 1 if lint_out else 0
                if error_count > 0:
                    issues.append(
                        {
                            "level": "warning",
                            "check": "lint",
                            "message": f"{path.name}: {error_count} lint issues found",
                        }
                    )
        except (asyncio.TimeoutError, FileNotFoundError, OSError):
            pass  # Lint is optional

    return issues


def format_verification_feedback(issues: list[dict[str, Any]]) -> str | None:
    """Format verification issues into a message for the agent.

    Returns None if no issues, or a formatted string to inject
    as system feedback into the conversation.
    """
    if not issues:
        return None

    errors = [i for i in issues if i["level"] == "error"]
    warnings = [i for i in issues if i["level"] == "warning"]

    parts = ["[VERIFICATION]"]
    if errors:
        parts.append(f"ERRORS ({len(errors)}):")
        for e in errors:
            parts.append(f"  - {e['message']}")
    if warnings:
        parts.append(f"WARNINGS ({len(warnings)}):")
        for w in warnings:
            parts.append(f"  - {w['message']}")

    if errors:
        parts.append("Fix the errors above before proceeding.")

    return "\n".join(parts)
