#!/usr/bin/env python3
"""Scan the repository for accidental PII, secrets, and sensitive data.

Usage:
    python scripts/audit_secrets.py [--strict]

Exit codes:
    0  No issues found
    1  Issues detected (prints details to stderr)
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Patterns that should NOT appear in committed source code.
PATTERNS: list[tuple[str, re.Pattern]] = [
    ("API key (OpenAI)", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("API key (Anthropic)", re.compile(r"sk-ant-[A-Za-z0-9\-]{20,}")),
    ("API key (xAI)", re.compile(r"xai-[A-Za-z0-9]{20,}")),
    ("API key (OpenRouter)", re.compile(r"sk-or-[A-Za-z0-9\-]{20,}")),
    ("Windows user path", re.compile(r"C:\\Users\\[A-Za-z0-9_]+\\")),
    ("Unix home path", re.compile(r"/home/[a-z][a-z0-9_]+/")),
    ("Email address", re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}")),
    ("Private key block", re.compile(r"-----BEGIN (RSA |EC |DSA )?PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"AKIA[A-Z0-9]{16}")),
    ("Generic secret assignment", re.compile(r"""(?i)(?:password|secret|token)\s*=\s*["'][^"']{8,}["']""")),
]

# Files and directories to skip.
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".eggs",
    "*.egg-info",
    ".tmp",
    ".tmp-cli-test",
    ".tmp-cli-test2",
    ".claude",
    "runtime",
    ".inbox_extract_cache",
}
SKIP_FILES = {
    "audit_secrets.py",  # This script itself
    "requirements-lock.txt",
    ".env.example",
}
SKIP_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".so",
    ".dll",
    ".exe",
    ".bin",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".svg",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".db",
    ".db-shm",
    ".db-wal",
    ".sqlite",
    ".zip",
    ".tar",
    ".gz",
    ".bz2",
}

# Known safe patterns (allowlist).
ALLOWLIST = [
    re.compile(r"sk-\.\.\."),  # Placeholder in docs
    re.compile(r"sk-ant-\.\.\."),  # Placeholder in docs
    re.compile(r"xai-\.\.\."),  # Placeholder in docs
    re.compile(r"sk-or-\.\.\."),  # Placeholder in docs
    re.compile(r'api_key\s*=\s*""'),  # Empty key in config templates
    re.compile(r"noreply@"),  # Bot email addresses
    re.compile(r"example\.com"),  # Example domains
    re.compile(r"your_key_here"),  # Placeholder text
    re.compile(r"@local\.invalid"),  # Internal placeholder emails
    re.compile(r"user@domain\.com"),  # Documentation examples
    re.compile(r"@acme\.com"),  # Test fixture data
    re.compile(r"@tech\.com"),  # Test fixture data
    re.compile(r"@abc\.com"),  # Test fixture data
    re.compile(r"@xyz\.com"),  # Test fixture data
    re.compile(r"@company\.com"),  # Documentation examples
    re.compile(r"boss@"),  # Documentation examples
    re.compile(r'ENV_\w+\s*=\s*"THOMAS_'),  # Env var name constants
    re.compile(r"RESET_PASSWORD"),  # Enum value, not a password
    re.compile(r"/home/node/"),  # Docker documentation paths
    re.compile(r"/home/user/"),  # Test fixture paths
    re.compile(r"placeholder"),  # Placeholder text
    re.compile(r'class="'),  # HTML template snippets
    re.compile(r"test_password"),  # Test fixture passwords
    re.compile(r"my_secure_password"),  # Test fixture passwords
    re.compile(r"123456:ABC"),  # Documentation example tokens
]


def should_skip_path(path: Path, root: Path) -> bool:
    """Check if a path should be skipped."""
    rel = path.relative_to(root)
    parts = rel.parts

    for part in parts:
        if part in SKIP_DIRS:
            return True
        if any(part.endswith(s) for s in (".egg-info",)):
            return True

    if path.name in SKIP_FILES:
        return True
    if path.suffix in SKIP_EXTENSIONS:
        return True

    return False


def is_allowlisted(line: str) -> bool:
    """Check if a line matches a known safe pattern."""
    return any(p.search(line) for p in ALLOWLIST)


def scan_file(path: Path, root: Path) -> list[tuple[int, str, str]]:
    """Scan a single file for sensitive patterns.

    Returns list of (line_number, pattern_name, matching_line).
    """
    findings: list[tuple[int, str, str]] = []

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, PermissionError):
        return findings

    for line_no, line in enumerate(text.splitlines(), start=1):
        if is_allowlisted(line):
            continue

        for pattern_name, pattern in PATTERNS:
            if pattern.search(line):
                findings.append((line_no, pattern_name, line.strip()[:120]))
                break  # One finding per line is enough

    return findings


def scan_repo(root: Path) -> list[tuple[Path, int, str, str]]:
    """Scan entire repository for sensitive data.

    Returns list of (file_path, line_number, pattern_name, matching_line).
    """
    all_findings: list[tuple[Path, int, str, str]] = []

    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if should_skip_path(path, root):
            continue

        findings = scan_file(path, root)
        for line_no, pattern_name, line in findings:
            all_findings.append((path.relative_to(root), line_no, pattern_name, line))

    return all_findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan for PII and secrets in the repo.")
    parser.add_argument("--strict", action="store_true", help="Treat warnings as errors")
    parser.add_argument("--root", type=Path, default=None, help="Repository root (default: auto-detect)")
    args = parser.parse_args()

    root = args.root
    if root is None:
        # Try to find repo root by walking up from script location
        candidate = Path(__file__).resolve().parent.parent
        if (candidate / "pyproject.toml").exists():
            root = candidate
        else:
            root = Path.cwd()

    if not root.exists():
        print(f"Error: root directory does not exist: {root}", file=sys.stderr)
        return 1

    print(f"Scanning {root} for sensitive data...")
    findings = scan_repo(root)

    if not findings:
        print("No sensitive data found.")
        return 0

    print(f"\nFound {len(findings)} potential issue(s):\n", file=sys.stderr)
    for file_path, line_no, pattern_name, line in findings:
        print(f"  {file_path}:{line_no}  [{pattern_name}]", file=sys.stderr)
        print(f"    {line}", file=sys.stderr)

    print(f"\nTotal: {len(findings)} finding(s)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
