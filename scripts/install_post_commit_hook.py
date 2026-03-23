#!/usr/bin/env python3
"""Install the post-commit audit hook into .git/hooks/.

Unlike pre-commit hooks (managed by .pre-commit-config.yaml), post-commit
hooks need to be installed directly. This script creates or appends to
.git/hooks/post-commit.

Run once after cloning:
    python scripts/install_post_commit_hook.py

Audit reference: Adversarial Audit Finding 7 (2026-03-19)
"""

from __future__ import annotations

import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK_PATH = ROOT / ".git" / "hooks" / "post-commit"
HOOK_MARKER = "# thomas-post-commit-audit"
HOOK_CONTENT = f"""\
{HOOK_MARKER}
python scripts/post_commit_audit.py 2>/dev/null || true
"""


def main() -> int:
    if HOOK_PATH.exists():
        existing = HOOK_PATH.read_text(encoding="utf-8")
        if HOOK_MARKER in existing:
            print(f"Post-commit audit hook already installed in {HOOK_PATH}")
            return 0
        # Append to existing hook
        with HOOK_PATH.open("a", encoding="utf-8") as f:
            f.write("\n" + HOOK_CONTENT)
        print(f"Appended post-commit audit to existing hook: {HOOK_PATH}")
    else:
        HOOK_PATH.parent.mkdir(parents=True, exist_ok=True)
        HOOK_PATH.write_text("#!/bin/sh\n" + HOOK_CONTENT, encoding="utf-8")
        # Make executable
        HOOK_PATH.chmod(HOOK_PATH.stat().st_mode | stat.S_IEXEC)
        print(f"Created post-commit audit hook: {HOOK_PATH}")

    print("The hook will detect --no-verify bypasses and log them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
