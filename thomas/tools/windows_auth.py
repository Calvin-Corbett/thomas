"""Windows native authorization gate for high-risk Thomas actions.

Uses the Windows CredUIPromptForCredentials dialog (same native PIN/password
popup used by Chrome/Edge autofill). Zero disk persistence — auth state lives
only in process memory and is cleared on process exit or explicit revocation.

Usage:
    from thomas.tools.windows_auth import WindowsAuthGate, get_auth_gate

    gate = get_auth_gate()
    authorized = gate.request_authorization("Delete all files in /output", "Destructive action")
    if not authorized:
        raise PermissionError("User denied authorization")
"""

from __future__ import annotations

import logging
import platform
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory session state (no disk, no files, cleared on process exit)
# ---------------------------------------------------------------------------


@dataclass
class _AuthSession:
    """Single in-memory auth session. No persistence."""

    granted_at: float
    expiry_s: float
    actions_approved: list[str] = field(default_factory=list)

    def is_valid(self) -> bool:
        return time.monotonic() < (self.granted_at + self.expiry_s)

    def log_action(self, action: str) -> None:
        self.actions_approved.append(action)


class WindowsAuthGate:
    """In-process Windows PIN/password authorization gate.

    - Zero disk writes. Auth state is process-local only.
    - Configurable session expiry (default 5 minutes).
    - Tracks all actions approved in the current session.
    - Falls back gracefully on non-Windows platforms (returns False, logs warning).
    """

    def __init__(self, session_expiry_s: int = 300) -> None:
        self._session_expiry_s = session_expiry_s
        self._session: _AuthSession | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def request_authorization(
        self,
        action_description: str,
        reason: str = "This action requires your explicit approval.",
    ) -> bool:
        """Show native Windows PIN/password dialog if no valid session exists.

        Returns True only if the user successfully authenticates.
        On non-Windows platforms, always returns False.
        """
        if platform.system() != "Windows":
            log.warning(
                "WindowsAuthGate: not on Windows — authorization denied for: %s",
                action_description,
            )
            return False

        # Valid session already exists — no re-prompt needed
        if self._session and self._session.is_valid():
            self._session.log_action(action_description)
            log.info("WindowsAuthGate: session still valid, approved: %s", action_description)
            return True

        # Prompt fresh
        success = self._show_windows_dialog(action_description, reason)
        if success:
            self._session = _AuthSession(
                granted_at=time.monotonic(),
                expiry_s=self._session_expiry_s,
            )
            self._session.log_action(action_description)
            log.info(
                "WindowsAuthGate: authorized for %ds. Action: %s",
                self._session_expiry_s,
                action_description,
            )
        else:
            self._session = None
            log.warning("WindowsAuthGate: authorization denied for: %s", action_description)

        return success

    def revoke(self) -> None:
        """Immediately invalidate the current session."""
        self._session = None
        log.info("WindowsAuthGate: session revoked.")

    def session_summary(self) -> dict:
        """Return current session state for display/audit."""
        if not self._session or not self._session.is_valid():
            return {"active": False, "actions_approved": []}
        remaining = int((self._session.granted_at + self._session.expiry_s) - time.monotonic())
        return {
            "active": True,
            "expires_in_s": max(0, remaining),
            "actions_approved": list(self._session.actions_approved),
        }

    # ------------------------------------------------------------------
    # Internal: native Windows dialog
    # ------------------------------------------------------------------

    def _show_windows_dialog(self, action_description: str, reason: str) -> bool:
        try:
            import pywintypes
            import win32api
            import win32cred
        except ImportError:
            log.error("WindowsAuthGate: pywin32 not installed. Run: pip install pywin32")
            return False

        target = f"THOMAS-AUTH:{action_description[:60]}"
        message = (
            f"Thomas needs your authorization:\n\n"
            f"{action_description}\n\n"
            f"{reason}\n\n"
            f"Enter your Windows PIN or password to proceed."
        )

        flags = (
            win32cred.CREDUI_FLAGS_GENERIC_CREDENTIALS
            | win32cred.CREDUI_FLAGS_EXPECT_CONFIRMATION
            | win32cred.CREDUI_FLAGS_COMPLETE_USERNAME
        )

        try:
            username = win32api.GetUserName()
        except (OSError, pywintypes.error):
            username = ""

        try:
            result, _username, _password, _saved = win32cred.CredUIPromptForCredentials(
                target,  # TargetName
                0,  # AuthError (0 = no prior error)
                username,  # UserName
                "",  # Password
                False,  # Save
                flags,  # Flags
                message,  # MessageText
            )
            # result == 0 means ERROR_SUCCESS (user confirmed)
            return result == 0
        except (OSError, pywintypes.error) as e:
            log.error("WindowsAuthGate: dialog error: %s", e)
            return False


# Prompt content is never regex-scanned or pre-rejected here. Provider policy
# handles model safety, while this module authorizes concrete structured
# high-risk actions after Thomas has chosen them.


# ---------------------------------------------------------------------------
# Process-level singleton
# ---------------------------------------------------------------------------

_gate: WindowsAuthGate | None = None


def get_auth_gate(session_expiry_s: int = 300) -> WindowsAuthGate:
    """Return the process-level singleton auth gate."""
    global _gate
    if _gate is None:
        _gate = WindowsAuthGate(session_expiry_s=session_expiry_s)
    return _gate
