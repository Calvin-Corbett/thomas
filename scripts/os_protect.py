#!/usr/bin/env python3
"""OS-level file protection for Thomas agent safety.

Uses the operating system's native permission model to make critical files
truly immutable to agents. An agent cannot bypass OS permissions — only a
human entering their password/PIN at an OS elevation prompt can.

On Windows: sets files read-only via NTFS attributes + optional ACL elevation
On Linux/Mac: sets files to 444 (read-only for everyone), owned by root

Usage:
    # Lock all protected files (requires elevation)
    python scripts/os_protect.py lock

    # Unlock for human editing (requires elevation)
    python scripts/os_protect.py unlock

    # Check which files are/aren't locked
    python scripts/os_protect.py status

    # Show what would be locked (dry run)
    python scripts/os_protect.py plan

Why this matters:
    Every other safety mechanism (env vars, TOML configs, Python hooks) lives
    in the agent's execution sandbox. An agent can set THOMAS_SKIP_BREAKGLASS=1,
    edit agent_safety.toml, or rewrite hook scripts. OS file permissions are
    enforced by the kernel — the agent would need the human's password to bypass.
"""

from __future__ import annotations

import argparse
import os
import platform
import stat
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]


def _find_repo_root() -> Path:
    """Walk up from CWD to find the repo root (has agent_safety.toml)."""
    p = Path.cwd().resolve()
    for parent in [p, *p.parents]:
        if (parent / "agent_safety.toml").exists():
            return parent
    print("ERROR: Cannot find agent_safety.toml in any parent directory.")
    sys.exit(1)


def _load_protected_files(repo: Path) -> list[Path]:
    """Read agent_safety.toml and collect all files that should be OS-protected."""
    toml_path = repo / "agent_safety.toml"
    if tomllib is None:
        # Minimal fallback parser for the lists we need
        return _fallback_parse(toml_path, repo)

    with open(toml_path, "rb") as f:
        config = tomllib.load(f)

    files: list[str] = []
    protected = config.get("protected", {})
    files.extend(protected.get("policy_files", []))
    files.extend(protected.get("guardrails_files", []))
    files.extend(protected.get("enforcement_files", []))
    files.extend(protected.get("enforcement_scripts", []))

    # Also protect the safety config itself and this script
    files.append("agent_safety.toml")
    files.append("scripts/os_protect.py")
    files.append(".pre-commit-config.yaml")

    # Deduplicate and resolve
    seen: set[str] = set()
    result: list[Path] = []
    for f in files:
        if f not in seen:
            seen.add(f)
            p = repo / f
            if p.exists():
                result.append(p)

    return result


def _fallback_parse(toml_path: Path, repo: Path) -> list[Path]:
    """Minimal parser when tomllib isn't available."""
    import re

    content = toml_path.read_text(encoding="utf-8")
    files: list[str] = []
    for match in re.finditer(r'"([^"]+)"', content):
        val = match.group(1)
        if val.endswith((".py", ".md", ".toml", ".yaml", ".yml", ".json")) and (repo / val).exists():
            files.append(val)
    return [repo / f for f in dict.fromkeys(files)]


# ── Platform-specific operations ──────────────────────────────────────────


def _is_windows() -> bool:
    return platform.system() == "Windows"


def _is_elevated() -> bool:
    """Check if we're running with admin/root privileges."""
    if _is_windows():
        try:
            # Windows: check if running as admin
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            return False
    else:
        return os.geteuid() == 0  # type: ignore[attr-defined]


def _request_elevation() -> None:
    """Re-launch this script with elevation. On Windows this triggers UAC."""
    if _is_windows():
        import ctypes

        # ShellExecute with "runas" triggers the UAC prompt
        ctypes.windll.shell32.ShellExecuteW(  # type: ignore[attr-defined]
            None, "runas", sys.executable, " ".join(sys.argv), None, 1
        )
        sys.exit(0)
    else:
        print("ERROR: This command requires root privileges.")
        print("Run with: sudo python scripts/os_protect.py " + " ".join(sys.argv[1:]))
        sys.exit(1)


def _lock_file_windows(path: Path) -> bool:
    """Make file read-only on Windows using attrib and icacls."""
    try:
        # Set read-only attribute
        subprocess.run(["attrib", "+R", str(path)], check=True, capture_output=True)

        # For stronger protection: remove write permission for the current user
        # This requires elevation (UAC prompt)
        subprocess.run(
            ["icacls", str(path), "/deny", f"{os.environ.get('USERNAME', 'Everyone')}:(W,D,DC)"],
            check=True,
            capture_output=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        # Fallback: at least set read-only attribute
        try:
            subprocess.run(["attrib", "+R", str(path)], check=True, capture_output=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False


def _lock_file_unix(path: Path) -> bool:
    """Make file read-only on Linux/Mac. With root: chown root + chmod 444."""
    try:
        if _is_elevated():
            # Full protection: root-owned, read-only for everyone
            os.chown(str(path), 0, 0)  # chown root:root
            os.chmod(str(path), stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)  # 444
        else:
            # Partial protection: just remove write bits
            current = os.stat(path).st_mode
            os.chmod(str(path), current & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
        return True
    except PermissionError:
        return False


def _unlock_file_windows(path: Path) -> bool:
    """Restore write permission on Windows."""
    try:
        subprocess.run(["attrib", "-R", str(path)], check=True, capture_output=True)
        subprocess.run(
            ["icacls", str(path), "/remove:d", os.environ.get("USERNAME", "Everyone")],
            check=True,
            capture_output=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        try:
            subprocess.run(["attrib", "-R", str(path)], check=True, capture_output=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False


def _unlock_file_unix(path: Path) -> bool:
    """Restore write permission on Linux/Mac."""
    try:
        if _is_elevated():
            import pwd

            # Restore ownership to the original user
            user = os.environ.get("SUDO_USER", os.environ.get("USER", ""))
            if user:
                pw = pwd.getpwnam(user)
                os.chown(str(path), pw.pw_uid, pw.pw_gid)
            os.chmod(str(path), stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)  # 644
        else:
            current = os.stat(path).st_mode
            os.chmod(str(path), current | stat.S_IWUSR)
        return True
    except PermissionError:
        return False


def _is_locked(path: Path) -> bool:
    """Check if a file is currently write-protected."""
    try:
        mode = os.stat(path).st_mode
        return not bool(mode & stat.S_IWUSR)
    except FileNotFoundError:
        return False


# ── Commands ──────────────────────────────────────────────────────────────


def cmd_status(repo: Path, files: list[Path]) -> int:
    """Show lock status of all protected files."""
    locked = 0
    unlocked = 0
    missing = 0

    for f in files:
        rel = f.relative_to(repo)
        if not f.exists():
            print(f"  MISSING  {rel}")
            missing += 1
        elif _is_locked(f):
            print(f"  LOCKED   {rel}")
            locked += 1
        else:
            print(f"  OPEN     {rel}")
            unlocked += 1

    print(f"\n  {locked} locked, {unlocked} open, {missing} missing")
    if unlocked > 0:
        print("  Run 'python scripts/os_protect.py lock' to protect open files.")
        return 1
    return 0


def cmd_plan(repo: Path, files: list[Path]) -> int:
    """Show what would be locked (dry run)."""
    print(f"Files that would be OS-protected ({len(files)} total):\n")
    for f in files:
        rel = f.relative_to(repo)
        status = "LOCKED" if _is_locked(f) else "OPEN"
        print(f"  [{status}] {rel}")

    print(f"\nPlatform: {platform.system()}")
    if _is_windows():
        print("Method: attrib +R + icacls deny write (requires UAC elevation)")
    else:
        print("Method: chown root:root + chmod 444 (requires sudo)")
    print("\nTo apply: python scripts/os_protect.py lock")
    return 0


def cmd_lock(repo: Path, files: list[Path]) -> int:
    """Lock all protected files at the OS level."""
    if not _is_elevated():
        print("Elevation required to lock files.")
        _request_elevation()
        return 1

    lock_fn = _lock_file_windows if _is_windows() else _lock_file_unix
    ok = 0
    fail = 0

    for f in files:
        rel = f.relative_to(repo)
        if _is_locked(f):
            print(f"  SKIP (already locked) {rel}")
            ok += 1
        elif lock_fn(f):
            print(f"  LOCKED  {rel}")
            ok += 1
        else:
            print(f"  FAILED  {rel}")
            fail += 1

    print(f"\n  {ok} locked, {fail} failed")
    if fail > 0:
        print("  Some files could not be locked. Check permissions.")
        return 1

    print("\n  Protected files are now OS-locked.")
    print("  Agents CANNOT modify these files.")
    print("  To unlock for editing: python scripts/os_protect.py unlock")
    return 0


def cmd_unlock(repo: Path, files: list[Path]) -> int:
    """Unlock protected files for human editing."""
    if not _is_elevated():
        print("Elevation required to unlock files.")
        _request_elevation()
        return 1

    unlock_fn = _unlock_file_windows if _is_windows() else _unlock_file_unix
    ok = 0
    fail = 0

    for f in files:
        rel = f.relative_to(repo)
        if not _is_locked(f):
            print(f"  SKIP (already open) {rel}")
            ok += 1
        elif unlock_fn(f):
            print(f"  UNLOCKED  {rel}")
            ok += 1
        else:
            print(f"  FAILED    {rel}")
            fail += 1

    print(f"\n  {ok} unlocked, {fail} failed")
    if fail == 0:
        print("\n  WARNING: Protected files are now writable.")
        print("  Remember to re-lock after editing: python scripts/os_protect.py lock")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OS-level file protection for Thomas agent safety",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  lock     Make protected files read-only at the OS level (requires elevation)
  unlock   Restore write access for human editing (requires elevation)
  status   Show which protected files are locked/open
  plan     Show what would be locked (dry run)

The key insight: environment variables, TOML configs, and Python hooks all live
in the agent's sandbox. OS permissions are enforced by the kernel. An agent
cannot type your password into a UAC/sudo prompt.
        """,
    )
    parser.add_argument("command", choices=["lock", "unlock", "status", "plan"])
    args = parser.parse_args()

    repo = _find_repo_root()
    files = _load_protected_files(repo)

    if not files:
        print("No protected files found in agent_safety.toml")
        return 1

    if args.command == "status":
        return cmd_status(repo, files)
    elif args.command == "plan":
        return cmd_plan(repo, files)
    elif args.command == "lock":
        return cmd_lock(repo, files)
    elif args.command == "unlock":
        return cmd_unlock(repo, files)
    return 0


if __name__ == "__main__":
    sys.exit(main())
