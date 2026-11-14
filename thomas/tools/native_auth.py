"""Cross-platform native authorization helpers for high-risk Thomas actions."""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess

from thomas.core.owner_wait import awaiting_owner
from thomas.tools.windows_auth import get_auth_gate, verified_sign_in

log = logging.getLogger(__name__)


def _escape_applescript_string(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')


def _request_macos_authorization(action_description: str, reason: str) -> bool:
    if not shutil.which("osascript"):
        log.warning("Native auth unavailable on macOS: osascript not found.")
        return False
    prompt = (
        "Thomas needs your authorization:\\n\\n"
        f"{_escape_applescript_string(action_description)}\\n\\n"
        f"{_escape_applescript_string(reason)}"
    )
    script = f'do shell script "/usr/bin/true" with administrator privileges with prompt "{prompt}"'
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception as exc:
        log.warning("Native auth macOS dialog failed: %s", exc)
        return False
    return int(result.returncode or 0) == 0


def _request_linux_authorization() -> bool:
    pkexec = shutil.which("pkexec")
    if not pkexec:
        log.warning("Native auth unavailable on Linux: pkexec not found.")
        return False
    try:
        result = subprocess.run(
            [pkexec, "/usr/bin/true"],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception as exc:
        log.warning("Native auth Linux dialog failed: %s", exc)
        return False
    return int(result.returncode or 0) == 0


def request_native_authorization(
    action_description: str,
    reason: str,
    *,
    session_expiry_s: int = 0,
) -> bool:
    """Request native OS authorization for a sensitive action.

    Every call asks. Until 2026-09-22 the default reused a Windows approval for
    five minutes, so one tap for one protected file silently approved the next.
    Owner direction: "Every protected file needs to be its own thing." Wider
    approvals are a choice the owner makes on the card (this file, this task,
    or everything), never a side effect of timing. A caller can still opt into
    reuse with an explicit ``session_expiry_s``; none does.
    """
    system = platform.system()
    if system == "Windows":
        if session_expiry_s <= 0:
            return verified_sign_in(action_description, reason)
        gate = get_auth_gate(session_expiry_s=session_expiry_s)
        return gate.request_authorization(action_description=action_description, reason=reason)
    if system == "Darwin":
        with awaiting_owner():  # the asking worker is waiting on you, not stuck
            return _request_macos_authorization(action_description, reason)
    if system == "Linux":
        with awaiting_owner():
            return _request_linux_authorization()
    log.warning("Native auth is not implemented for platform: %s", system)
    return False
