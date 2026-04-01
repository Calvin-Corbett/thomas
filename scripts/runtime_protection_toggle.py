#!/usr/bin/env python3
"""Toggle Thomas runtime protection on/off with Windows credential verification.

Runtime protection prevents agent-spawned tools (fs.write_file, diff.create,
diff.apply_patch) from modifying Thomas's own runtime code.  This script lets
a human — authenticated via their Windows password/PIN — temporarily disable
that protection for maintenance, then re-enable it.

Usage (from the Thomas repo root):
    python scripts/runtime_protection_toggle.py off   # Disable protection
    python scripts/runtime_protection_toggle.py on    # Re-enable protection
    python scripts/runtime_protection_toggle.py status # Check current state

The toggle writes/removes a flag file at runtime/.runtime_protection_disabled.
The guard in thomas/tools/filesystem.py checks for this file.

Security model:
    - This script requires an interactive Windows session
    - It prompts for the PC's password via the Windows credential dialog
    - Agents running in background/headless mode cannot produce the dialog
    - The flag file location (runtime/) is outside the protected directories
      so it CAN be written, but only this script creates it after auth
"""

from __future__ import annotations

import os
import time
from pathlib import Path


def _find_repo_root() -> Path:
    """Walk up from CWD to find the repo root (has agent_safety.toml)."""
    p = Path.cwd().resolve()
    for parent in [p, *p.parents]:
        if (parent / "agent_safety.toml").exists():
            return parent
    # Try script location as fallback
    script_dir = Path(__file__).resolve().parent.parent
    if (script_dir / "agent_safety.toml").exists():
        return script_dir
    print("ERROR: Cannot find agent_safety.toml in any parent directory.")
    raise SystemExit(1)


FLAG_FILENAME = ".runtime_protection_disabled"


def _flag_path(repo: Path) -> Path:
    return repo / "runtime" / FLAG_FILENAME


def _is_disabled(repo: Path) -> bool:
    return _flag_path(repo).exists()


def _authenticate_windows() -> bool:
    """Prompt for Windows credentials and verify them.

    Returns True if the user authenticated successfully, False otherwise.
    """
    if os.name != "nt":
        print("ERROR: Runtime protection toggle requires a Windows interactive session.")
        print("       On Linux/Mac, edit the flag file manually with sudo.")
        return False

    try:
        from scripts.breakglass_auth import (
            BreakglassAuthorization,
            _current_windows_sam_name,
            _run_windows_credential_prompt,
        )
    except ImportError:
        print("ERROR: Could not import breakglass_auth. Run from the Thomas repo root.")
        return False

    current_user = _current_windows_sam_name()
    if not current_user:
        print("ERROR: Could not determine current Windows user.")
        return False

    print(f"\n  Account: {current_user}")
    print("  A Windows sign-in prompt will appear. Enter your password/PIN.\n")

    caption = "Thomas Runtime Protection Toggle"
    message = (
        "Confirm your identity to toggle Thomas runtime protection.\n"
        f"Account: {current_user}\n"
        "Windows may offer PIN, password, or Windows Hello."
    )

    result: BreakglassAuthorization = _run_windows_credential_prompt(
        prompt_caption=caption,
        prompt_message=message,
    )

    if result.ok:
        print(f"  Authenticated as: {result.actor}")
        return True

    if result.cancelled:
        print("  Authentication cancelled.")
    else:
        print(f"  Authentication failed: {result.message}")
    return False


def cmd_off(repo: Path) -> int:
    """Disable runtime protection (requires authentication)."""
    if _is_disabled(repo):
        print("  Runtime protection is already DISABLED.")
        return 0

    print("  Disabling runtime protection...")
    print("  This allows agent tools to write to Thomas's runtime directories.")

    if not _authenticate_windows():
        return 1

    flag = _flag_path(repo)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text(
        f"# Runtime protection disabled at {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"# by {os.environ.get('USERNAME', 'unknown')}\n"
        f"# Re-enable with: python scripts/runtime_protection_toggle.py on\n",
        encoding="utf-8",
    )

    print("\n  Runtime protection is now DISABLED.")
    print("  Agent tools can write to thomas/tools/, thomas/agent/, etc.")
    print("  Re-enable with: python scripts/runtime_protection_toggle.py on")
    return 0


def cmd_on(repo: Path) -> int:
    """Re-enable runtime protection."""
    flag = _flag_path(repo)
    if not flag.exists():
        print("  Runtime protection is already ENABLED.")
        return 0

    try:
        flag.unlink()
    except OSError as e:
        print(f"  ERROR: Could not remove flag file: {e}")
        return 1

    print("  Runtime protection is now ENABLED.")
    print("  Agent tools are blocked from writing to Thomas's runtime code.")
    return 0


def cmd_status(repo: Path) -> int:
    """Show current protection state."""
    if _is_disabled(repo):
        flag = _flag_path(repo)
        mtime = time.strftime(
            "%Y-%m-%d %H:%M:%S",
            time.localtime(flag.stat().st_mtime),
        )
        print(f"  Runtime protection: DISABLED (since {mtime})")
        print(f"  Flag file: {flag}")
        print("  Re-enable with: python scripts/runtime_protection_toggle.py on")
        return 1
    else:
        print("  Runtime protection: ENABLED")
        print("  Agent tools are blocked from writing to Thomas's runtime code.")
        return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Toggle Thomas runtime protection on/off",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Commands:\n"
            "  off      Disable protection (requires Windows auth)\n"
            "  on       Re-enable protection\n"
            "  status   Show current state\n"
        ),
    )
    parser.add_argument("command", choices=["on", "off", "status"])
    args = parser.parse_args()

    repo = _find_repo_root()

    if args.command == "off":
        return cmd_off(repo)
    elif args.command == "on":
        return cmd_on(repo)
    elif args.command == "status":
        return cmd_status(repo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
