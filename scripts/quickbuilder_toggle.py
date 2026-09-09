#!/usr/bin/env python3
"""Turn Thomas QuickBuilder mode on/off with Windows credential verification.

QuickBuilder mode relaxes the *workflow / coordination / location* gates
(worktree-branch-guard, worktree-rules, workboard claim/changed-files/task-
problems/inbox gates, active-folder-guard, plan-structure, merge-readiness) and
disables the breakglass cooldown -- so a human can build fast from any worktree
without fighting the "wrong worktree / unclaimed path / dirty tree" gates.

It does NOT relax any code-engineering or security gate: tests, ruff,
enforcement-integrity, the secret-scan (publish preflight), exception-handler,
type-safety, architecture, monolith, protected-files and protected-deletions all
still run. Protected-file edits still require a breakglass tap -- QuickBuilder
only removes the *cooldown* between them, not the human authorization.

Usage (from the Thomas repo root):
    python scripts/quickbuilder_toggle.py on      # Activate (requires Windows auth)
    python scripts/quickbuilder_toggle.py off     # Deactivate
    python scripts/quickbuilder_toggle.py status  # Check current state

Files this script manages (both gitignored, both integrity/path-protected):
    - runtime/.quickbuilder_mode   the signed JSON flag
    - runtime/.quickbuilder_key    the per-install HMAC key

The flag is a JSON document signed with HMAC-SHA256 using the key. The validator
``scripts/forge/gates/_quickbuilder_guard.py`` recomputes the signature and
rejects flags it can't verify, so a forged or empty flag is harmless. Activation
requires an interactive Windows credential prompt, which a headless agent cannot
produce -- so an agent cannot self-activate QuickBuilder.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import sys
import time
from hashlib import sha256
from pathlib import Path

# Ensure the repo root is importable so `from scripts.breakglass_auth import ...`
# resolves when this script is invoked directly (sys.path[0] is scripts/, not the
# repo root, so breakglass_auth's own `scripts.*` imports would otherwise fail).
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _find_repo_root() -> Path:
    """Walk up from CWD to find the repo root (has agent_safety.toml)."""
    p = Path.cwd().resolve()
    for parent in [p, *p.parents]:
        if (parent / "agent_safety.toml").exists():
            return parent
    script_dir = Path(__file__).resolve().parent.parent
    if (script_dir / "agent_safety.toml").exists():
        return script_dir
    print("ERROR: Cannot find agent_safety.toml in any parent directory.")
    raise SystemExit(1)


FLAG_FILENAME = ".quickbuilder_mode"
KEY_FILENAME = ".quickbuilder_key"
FLAG_VERSION = 1


def _flag_path(repo: Path) -> Path:
    return repo / "runtime" / FLAG_FILENAME


def _key_path(repo: Path) -> Path:
    return repo / "runtime" / KEY_FILENAME


def _signing_payload(version: int, issued_at: str, issued_by: str, repo_str: str) -> bytes:
    """Must match _quickbuilder_guard._signing_payload byte-for-byte."""
    return f"{int(version)}|{issued_at}|{issued_by}|{repo_str}".encode()


def _mint_fresh_key(repo: Path) -> bytes:
    """Generate a brand-new HMAC key, overwriting any prior key file.

    Minting fresh on every activation means any attacker-planted key is
    overwritten the next time the owner legitimately activates, and any flag
    signed against an old key becomes invalid the moment the new key lands.
    """
    key_file = _key_path(repo)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    new_key = secrets.token_bytes(32)
    key_file.write_text(new_key.hex() + "\n", encoding="utf-8")
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return new_key


def _is_active(repo: Path) -> bool:
    """Quick presence check (does NOT validate signature; used by status/on)."""
    return _flag_path(repo).exists()


def _authenticate_windows() -> bool:
    """Prompt for Windows credentials and verify them."""
    if os.name != "nt":
        print("ERROR: QuickBuilder toggle requires a Windows interactive session.")
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

    caption = "Thomas QuickBuilder Toggle"
    message = (
        "Confirm your identity to activate Thomas QuickBuilder mode.\n"
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


def cmd_on(repo: Path) -> int:
    """Activate QuickBuilder mode (requires authentication)."""
    if _is_active(repo):
        print("  QuickBuilder mode is already ON.")
        return 0

    print("  Activating QuickBuilder mode...")
    print("  Workflow/coordination/location gates + the breakglass cooldown relax.")
    print("  Code-engineering and security gates (tests, ruff, integrity, secret-scan) stay ON.")

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
        "note": "Deactivate with: python scripts/quickbuilder_toggle.py off",
    }

    flag = _flag_path(repo)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

    print("\n  QuickBuilder mode is now ON.")
    print(f"  Issued at: {issued_at}  by: {issued_by}")
    print("  Friction gates relax + no breakglass cooldown; the engineering spine still enforces.")
    print("  Deactivate with: python scripts/quickbuilder_toggle.py off")
    return 0


def cmd_off(repo: Path) -> int:
    """Deactivate QuickBuilder mode (removes flag + signing key)."""
    flag = _flag_path(repo)
    key = _key_path(repo)

    if not flag.exists() and not key.exists():
        print("  QuickBuilder mode is already OFF.")
        return 0

    for path, label in ((flag, "flag file"), (key, "signing key")):
        if not path.exists():
            continue
        try:
            path.unlink()
        except OSError as e:
            print(f"  ERROR: Could not remove {label} at {path}: {e}")
            return 1

    print("  QuickBuilder mode is now OFF.")
    print("  All workflow gates and the breakglass cooldown are back in force.")
    print("  (Signing key removed; next 'on' will mint a fresh one.)")
    return 0


def cmd_status(repo: Path) -> int:
    """Show current QuickBuilder state."""
    if _is_active(repo):
        flag = _flag_path(repo)
        mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(flag.stat().st_mtime))
        print(f"  QuickBuilder mode: ON (since {mtime})")
        print(f"  Flag file: {flag}")
        print("  Deactivate with: python scripts/quickbuilder_toggle.py off")
        return 1
    print("  QuickBuilder mode: OFF")
    print("  All workflow gates and the breakglass cooldown are in force.")
    return 0


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Toggle Thomas QuickBuilder mode on/off",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Commands:\n"
            "  on       Activate QuickBuilder (requires Windows auth)\n"
            "  off      Deactivate QuickBuilder\n"
            "  status   Show current state\n"
        ),
    )
    parser.add_argument("command", choices=["on", "off", "status"])
    args = parser.parse_args()

    repo = _find_repo_root()

    if args.command == "on":
        return cmd_on(repo)
    if args.command == "off":
        return cmd_off(repo)
    if args.command == "status":
        return cmd_status(repo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
