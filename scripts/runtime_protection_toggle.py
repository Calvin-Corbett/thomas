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

Files this script manages (both gitignored, both in the hardcoded protected
file list — fs.write_file refuses to touch either):
    - runtime/.runtime_protection_disabled   the signed JSON flag
    - runtime/.runtime_protection_key        the per-install HMAC key

The flag is a JSON document signed with HMAC-SHA256 using the key.  The
validator in thomas/tools/filesystem.py recomputes the signature and rejects
flags it can't verify, so a forged or empty flag file is harmless.

Security model:
    - This script requires an interactive Windows session
    - It prompts for the PC's password via the Windows credential dialog
    - Agents running in background/headless mode cannot produce the dialog
    - Both managed files are protected paths: fs.write_file refuses agent
      writes, so an agent cannot mint a valid flag through Thomas's tool
      layer.  Even if a future write path slips past path protection, the
      signature check still rejects unsigned forgeries.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import time
from hashlib import sha256
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
KEY_FILENAME = ".runtime_protection_key"
FLAG_VERSION = 1


def _flag_path(repo: Path) -> Path:
    return repo / "runtime" / FLAG_FILENAME


def _key_path(repo: Path) -> Path:
    return repo / "runtime" / KEY_FILENAME


def _signing_payload(version: int, issued_at: str, issued_by: str, repo_str: str) -> bytes:
    """Must match thomas.tools.filesystem._runtime_signing_payload byte-for-byte."""
    return f"{int(version)}|{issued_at}|{issued_by}|{repo_str}".encode()


def _mint_fresh_key(repo: Path) -> bytes:
    """Generate a brand-new HMAC key, overwriting any prior key file.

    We deliberately do NOT re-use an existing key file across toggle
    sessions.  Persisting the key across sessions would mean that if an
    attacker ever planted a key (e.g. via some other write path before
    runtime/.runtime_protection_key was added to the protected list, or
    via shell.exec if Calvin ever enabled it), the planted key would
    silently keep working forever after.  Minting fresh on every ``off``
    means: any attacker-planted key is overwritten the next time Calvin
    legitimately toggles, and any flag signed against the old key
    becomes invalid the moment the new key lands.  (Codex hardening
    review, msg-20260527214458.)
    """
    key_file = _key_path(repo)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    new_key = secrets.token_bytes(32)
    key_file.write_text(new_key.hex() + "\n", encoding="utf-8")
    # Restrictive permissions where supported (no-op on Windows but
    # documents intent; Windows ACLs are inherited from runtime/).
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return new_key


def _is_disabled(repo: Path) -> bool:
    """Quick presence check (does NOT validate signature).

    This is intentionally lenient — used only by ``status`` and ``off``
    to short-circuit redundant work.  The real signature validation
    lives in ``thomas.tools.filesystem._is_runtime_protection_disabled``;
    that is what actually gates agent writes.
    """
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
        try:
            from breakglass_auth import (  # type: ignore[no-redef]
                BreakglassAuthorization,
                _current_windows_sam_name,
                _run_windows_credential_prompt,
            )
        except ImportError:
            # Last resort: add the scripts directory to sys.path
            import sys

            _scripts_dir = str(Path(__file__).resolve().parent)
            if _scripts_dir not in sys.path:
                sys.path.insert(0, _scripts_dir)
            try:
                from breakglass_auth import (  # type: ignore[no-redef]
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

    key = _mint_fresh_key(repo)

    issued_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    issued_by = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown"
    repo_str = str(repo.resolve())
    signature = hmac.new(
        key,
        _signing_payload(FLAG_VERSION, issued_at, issued_by, repo_str),
        sha256,
    ).hexdigest()

    document = {
        "version": FLAG_VERSION,
        "issued_at": issued_at,
        "issued_by": issued_by,
        "repo": repo_str,
        "signature": signature,
        "note": "Re-enable with: python scripts/runtime_protection_toggle.py on",
    }

    flag = _flag_path(repo)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    print("\n  Runtime protection is now DISABLED.")
    print(f"  Issued at: {issued_at}  by: {issued_by}")
    print("  Agent tools can write to thomas/tools/, thomas/agent/, etc.")
    print("  Re-enable with: python scripts/runtime_protection_toggle.py on")
    return 0


def cmd_on(repo: Path) -> int:
    """Re-enable runtime protection.

    Removes both the flag and the signing key.  The next ``off`` will
    mint a fresh key — this prevents any attacker-planted key from
    surviving an enable/disable cycle.
    """
    flag = _flag_path(repo)
    key = _key_path(repo)

    if not flag.exists() and not key.exists():
        print("  Runtime protection is already ENABLED.")
        return 0

    for path, label in ((flag, "flag file"), (key, "signing key")):
        if not path.exists():
            continue
        try:
            path.unlink()
        except OSError as e:
            print(f"  ERROR: Could not remove {label} at {path}: {e}")
            return 1

    print("  Runtime protection is now ENABLED.")
    print("  Agent tools are blocked from writing to Thomas's runtime code.")
    print("  (Signing key removed; next 'off' will mint a fresh one.)")
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
