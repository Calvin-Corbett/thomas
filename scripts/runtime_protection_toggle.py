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

The toggle writes/removes a flag file at runtime/.runtime_protection_disabled
and an authenticated receipt in app-state. Runtime guards only honor the
disable when both are present.

Security model:
    - This script requires an interactive Windows session
    - It prompts for the PC's password via the Windows credential dialog
    - Agents running in background/headless mode cannot produce the dialog
    - The repo flag alone is not trusted; guards also require the app-state receipt
"""

from __future__ import annotations

import json
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
STATE_DIRNAME = "runtime_protection"
DISABLED_RECEIPT_FILENAME = "disabled_receipt.json"
DEFAULT_DISABLE_MINUTES = 5
MAX_DISABLE_MINUTES = 60


def _flag_path(repo: Path) -> Path:
    return repo / "runtime" / FLAG_FILENAME


def _state_root() -> Path:
    if os.name == "nt":
        local_app_data = str(os.getenv("LOCALAPPDATA", "") or "").strip()
        if local_app_data:
            return Path(local_app_data).expanduser().resolve() / "Thomas"
    xdg_state_home = str(os.getenv("XDG_STATE_HOME", "") or "").strip()
    if xdg_state_home:
        return Path(xdg_state_home).expanduser().resolve() / "thomas"
    return Path.home().expanduser().resolve() / ".local" / "state" / "thomas"


def _receipt_path() -> Path:
    return _state_root() / STATE_DIRNAME / DISABLED_RECEIPT_FILENAME


def _read_disabled_receipt() -> dict[str, object] | None:
    receipt_path = _receipt_path()
    if not receipt_path.exists():
        return None
    try:
        payload = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _load_disabled_receipt(*, now: float | None = None) -> dict[str, object] | None:
    payload = _read_disabled_receipt()
    if payload is None:
        return None
    actor = str(payload.get("actor") or "").strip()
    method = str(payload.get("method") or "").strip()
    disabled_at = str(payload.get("disabled_at") or "").strip()
    expires_at_raw = payload.get("expires_at")
    if not actor or not method or not disabled_at:
        return None
    try:
        expires_at = float(expires_at_raw)
    except (TypeError, ValueError):
        return None
    current = time.time() if now is None else float(now)
    if expires_at <= current:
        return None
    payload["expires_at"] = expires_at
    return payload


def runtime_protection_is_disabled(repo: Path) -> bool:
    """Return True only when both the repo flag and an authenticated receipt exist."""
    flag = _flag_path(repo)
    if not flag.exists():
        return False
    return _load_disabled_receipt() is not None


def _clear_disabled_state(repo: Path) -> None:
    _flag_path(repo).unlink(missing_ok=True)
    _receipt_path().unlink(missing_ok=True)


def _is_disabled(repo: Path) -> bool:
    return runtime_protection_is_disabled(repo)


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


def cmd_off(repo: Path, *, minutes: int = DEFAULT_DISABLE_MINUTES) -> int:
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
    duration_minutes = max(1, min(int(minutes or DEFAULT_DISABLE_MINUTES), MAX_DISABLE_MINUTES))
    expires_at = time.time() + (duration_minutes * 60)
    receipt = {
        "actor": str(os.environ.get("USERNAME", "unknown")).strip() or "unknown",
        "method": "windows-credential-dialog",
        "disabled_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "expires_at": expires_at,
        "expires_at_local": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(expires_at)),
        "duration_minutes": duration_minutes,
        "flag_path": str(flag),
    }
    receipt_path = _receipt_path()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, sort_keys=True, indent=2), encoding="utf-8")

    print(f"\n  Runtime protection is now DISABLED for {duration_minutes} minute(s).")
    print(f"  It will auto-expire at {receipt['expires_at_local']}.")
    print("  Agent tools can write to thomas/tools/, thomas/agent/, etc.")
    print("  Re-enable with: python scripts/runtime_protection_toggle.py on")
    return 0


def cmd_on(repo: Path) -> int:
    """Re-enable runtime protection."""
    if not _flag_path(repo).exists() and not _receipt_path().exists():
        print("  Runtime protection is already ENABLED.")
        return 0

    try:
        _clear_disabled_state(repo)
    except OSError as e:
        print(f"  ERROR: Could not remove runtime protection state: {e}")
        return 1

    print("  Runtime protection is now ENABLED.")
    print("  Agent tools are blocked from writing to Thomas's runtime code.")
    return 0


def cmd_status(repo: Path) -> int:
    """Show current protection state."""
    if _is_disabled(repo):
        flag = _flag_path(repo)
        receipt_path = _receipt_path()
        receipt = _load_disabled_receipt()
        mtime = time.strftime(
            "%Y-%m-%d %H:%M:%S",
            time.localtime(flag.stat().st_mtime),
        )
        print(f"  Runtime protection: DISABLED (since {mtime})")
        print(f"  Flag file: {flag}")
        print(f"  Receipt file: {receipt_path}")
        if receipt is not None:
            expires_at = float(receipt.get("expires_at") or 0.0)
            print(f"  Auto-expires: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expires_at))}")
        print("  Re-enable with: python scripts/runtime_protection_toggle.py on")
        return 1
    else:
        print("  Runtime protection: ENABLED")
        if _flag_path(repo).exists():
            raw_receipt = _read_disabled_receipt()
            if raw_receipt is None:
                print("  Warning: runtime flag exists without an authenticated receipt; bypass ignored.")
            else:
                expires_at = raw_receipt.get("expires_at")
                try:
                    expired = float(expires_at) <= time.time()
                except (TypeError, ValueError):
                    expired = False
                if expired:
                    print("  Warning: runtime disable receipt expired; protection has auto-re-enabled.")
                elif _load_disabled_receipt() is None:
                    print("  Warning: runtime disable receipt is invalid; bypass ignored.")
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
    parser.add_argument(
        "--minutes",
        type=int,
        default=DEFAULT_DISABLE_MINUTES,
        help=f"Disable duration in minutes for `off` (default: {DEFAULT_DISABLE_MINUTES}, max: {MAX_DISABLE_MINUTES}).",
    )
    args = parser.parse_args()

    repo = _find_repo_root()

    if args.command == "off":
        return cmd_off(repo, minutes=args.minutes)
    elif args.command == "on":
        return cmd_on(repo)
    elif args.command == "status":
        return cmd_status(repo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
