#!/usr/bin/env python3
"""Open/close a time-boxed approval *window* for the breakglass Windows-Hello tap.

This is a switch for ONE gate: the human-presence (Windows sign-in / Windows
Hello) check in ``scripts/breakglass_auth.py``. Turn it ON (one real tap) and
for the next few hours protected actions won't re-prompt you. It does NOT relax
any other guardrail -- secret scan, integrity, tests, worktree rules, etc. all
still run. For machine owners who accept a short no-re-tap window in exchange
for not approving every single action.

Usage (from the Thomas repo root):
    python scripts/breakglass_window.py on            # 3h window (default), taps once
    python scripts/breakglass_window.py on --hours 1  # custom length (capped)
    python scripts/breakglass_window.py off           # revoke the window now
    python scripts/breakglass_window.py status        # time left, if any

Activation requires an interactive Windows sign-in -- no tap, no window. The
token + key live under runtime/ (gitignored) and are HMAC-signed, bound to your
Windows account, and hard-expire at the deadline.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_FALLBACK = _SCRIPTS_DIR.parent
if str(_REPO_FALLBACK) not in sys.path:
    sys.path.insert(0, str(_REPO_FALLBACK))

try:
    from scripts.breakglass_auth import (
        _REPO_ROOT,
        _current_windows_sam_name,
        _run_windows_credential_prompt,
    )
    from scripts.breakglass_window_core import (
        DEFAULT_WINDOW_HOURS,
        MAX_WINDOW_HOURS,
        clamp_hours,
        clear_window,
        mint_window,
        window_status,
    )
except ImportError:  # pragma: no cover - direct-run fallback
    from breakglass_auth import (  # type: ignore[no-redef]
        _REPO_ROOT,
        _current_windows_sam_name,
        _run_windows_credential_prompt,
    )
    from breakglass_window_core import (  # type: ignore[no-redef]
        DEFAULT_WINDOW_HOURS,
        MAX_WINDOW_HOURS,
        clamp_hours,
        clear_window,
        mint_window,
        window_status,
    )


def _fmt_remaining(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes = rem // 60
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def cmd_on(hours: float) -> int:
    requested = clamp_hours(hours)
    print("\n  Opening a breakglass approval window for THIS gate only.")
    print("  (Other guardrails -- secret scan, tests, integrity -- still run.)")
    current_user = _current_windows_sam_name()
    if not current_user:
        print("  ERROR: could not determine the current Windows user.")
        return 1
    print(f"  Account: {current_user}")
    print(f"  Requested length: {requested:g}h (max {MAX_WINDOW_HOURS:g}h)")
    print("  A Windows sign-in prompt will appear -- approve it once.\n")

    result = _run_windows_credential_prompt(
        prompt_caption="Thomas Breakglass Approval Window",
        prompt_message=(
            "Confirm your identity to open a breakglass approval window.\n"
            f"Account: {current_user}\n"
            f"For the next {requested:g} hour(s), protected actions won't re-prompt.\n"
            "Windows may offer PIN, password, or Windows Hello."
        ),
    )
    if not result.ok:
        if result.cancelled:
            print("  Cancelled -- no window opened.")
        else:
            print(f"  Sign-in failed -- no window opened: {result.message}")
        return 1

    actor = result.actor or current_user
    doc = mint_window(_REPO_ROOT, actor, requested)
    print("\n  Approval window is now OPEN.")
    print(f"  Actor:   {actor}")
    print(f"  Expires: {doc['expires_at']}  ({_fmt_remaining(int(doc['hours'] * 3600))} from now)")
    print("  Revoke any time with: python scripts/breakglass_window.py off")
    print("  Note: this only takes effect if Protected Override Approval (breakglass)")
    print("        is enabled in Thomas Settings; it never relaxes other gates.")
    return 0


def cmd_off() -> int:
    removed = clear_window(_REPO_ROOT)
    if removed:
        print("  Approval window CLOSED. Protected actions will prompt for Windows sign-in again.")
    else:
        print("  No approval window was open.")
    return 0


def cmd_status() -> int:
    current_user = _current_windows_sam_name()
    status = window_status(_REPO_ROOT, current_user or "")
    if status.get("active"):
        print("  Breakglass approval window: OPEN")
        print(f"  Actor:   {status.get('actor')}")
        print(f"  Expires: {status.get('expires_at')}  ({_fmt_remaining(int(status.get('remaining_seconds', 0)))} left)")
        return 0
    if status.get("token_present"):
        print("  Breakglass approval window: NOT ACTIVE (expired, wrong account, or invalid).")
        print("  Re-open with: python scripts/breakglass_window.py on")
    else:
        print("  Breakglass approval window: CLOSED.")
        print("  Open one with: python scripts/breakglass_window.py on")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Open/close a time-boxed approval window for the breakglass Windows-Hello tap.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    on = sub.add_parser("on", help="Open a window (requires one Windows sign-in)")
    on.add_argument(
        "--hours",
        type=float,
        default=DEFAULT_WINDOW_HOURS,
        help=f"Window length in hours (default {DEFAULT_WINDOW_HOURS:g}, capped at {MAX_WINDOW_HOURS:g}).",
    )
    sub.add_parser("off", help="Revoke the window now")
    sub.add_parser("status", help="Show remaining time, if any")
    args = parser.parse_args(argv)

    if args.command == "on":
        return cmd_on(args.hours)
    if args.command == "off":
        return cmd_off()
    if args.command == "status":
        return cmd_status()
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
