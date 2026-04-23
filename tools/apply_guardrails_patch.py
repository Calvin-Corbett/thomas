"""Best-effort patch applicator for Guardrails.

This script tries to apply the unified diffs in patches/*.patch using `git apply`.
If git isn't available or patches fail, it prints the manual merge instructions.

Usage (repo root):
  python tools/apply_guardrails_patch.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATCH_DIR = ROOT / "patches"

def main() -> int:
    if not PATCH_DIR.exists():
        print("patches/ not found; are you running from repo root?")
        return 2

    patches = sorted(PATCH_DIR.glob("*.patch"))
    if not patches:
        print("No patches found in patches/.")
        return 2

    # Prefer git apply if available
    try:
        subprocess.check_call(["git", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        cmd = ["git", "apply"] + [str(p.relative_to(ROOT)) for p in patches]
        print("Running:", " ".join(cmd))
        subprocess.check_call(cmd, cwd=str(ROOT))
        print("✅ Patches applied.")
        return 0
    except Exception as e:
        print("⚠️ git apply failed or git not available.")
        print("Reason:", e)
        print()
        print("Manual merge path:")
        print("- Open INTEGRATION_GUIDE.md")
        print("- Open each file in patches/ and transplant GUARDRAILS BEGIN/END blocks.")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
