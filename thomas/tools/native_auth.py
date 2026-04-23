"""Cross-platform native authorization helpers for high-risk Thomas actions."""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess

from thomas.tools.windows_auth import get_auth_gate

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
    session_expiry_s: int = 300,
) -> bool:
    """Request native OS authorization for a sensitive action."""
    system = platform.system()
    if system == "Windows":
        gate = get_auth_gate(session_expiry_s=session_expiry_s)
        return gate.request_authorization(action_description=action_description, reason=reason)
    if system == "Darwin":
        return _request_macos_authorization(action_description, reason)
    if system == "Linux":
        return _request_linux_authorization()
    log.warning("Native auth is not implemented for platform: %s", system)
    return False
