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

from thomas.core.owner_wait import awaiting_owner

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
        return verified_sign_in(action_description, reason)


def sign_in_answer(action_description: str, reason: str) -> str:
    """Windows' own sign-in, answered as approved, cancelled (you pressed Cancel) or failed.

    "failed" is a prompt that could not be shown, or a sign-in Windows did not accept. Only "cancelled" is your
    answer: a caller must never take "failed" as a no from you.

    Until 2026-10-09 every one of these came back as False, and the self-change promoter declined a change on a
    mistyped PIN. The prompt sets ``cancelled`` only for Cancel (scripts/breakglass_auth.py)."""
    if platform.system() != "Windows":
        log.warning("sign_in_answer: not on Windows -- not asked: %s", action_description)
        return "failed"
    try:
        from scripts.breakglass_auth import _run_windows_credential_prompt
    except ImportError as exc:
        log.error("sign_in_answer: the Windows sign-in prompt is unavailable: %s", exc)
        return "failed"
    try:
        # While the prompt is open the asking worker is waiting on you, not stuck.
        with awaiting_owner():
            result = _run_windows_credential_prompt(
                prompt_caption="Thomas", prompt_message=f"{action_description}\n\n{reason}"
            )
    except (OSError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
        # A prompt that cannot be shown is never an approval, and never a crash in the tool that asked for it.
        log.error("sign_in_answer: the sign-in prompt failed: %s", exc)
        return "failed"
    if bool(getattr(result, "ok", False)):
        return "approved"
    if bool(getattr(result, "cancelled", False)):
        return "cancelled"
    log.warning("sign_in_answer: Windows did not accept the sign-in: %s", getattr(result, "message", ""))
    return "failed"


def verified_sign_in(action_description: str, reason: str) -> bool:
    """Thomas's one password prompt: Windows' own sign-in, and the answer is checked.

    Until 2026-09-22 this gate showed ``CredUIPromptForCredentials`` with
    GENERIC credentials and treated OK as approval without ever checking what
    was typed. Any password -- or none -- approved a protected write. The box
    looked like a password check and was not one.

    This is the sign-in the break-glass path already used:
    ``CredUIPromptForWindowsCredentialsW``, which takes your PIN, fingerprint,
    face or password, with the answer then checked by Windows (``LsaLogonUser``,
    falling back to ``LogonUserW``). It stays Windows' own box on purpose. It is
    the only one that accepts a PIN, and Thomas's code never sees what you type,
    so a misbehaving Thomas can neither capture it nor fake the answer. Every
    Thomas approval uses this one prompt, captioned "Thomas", so there is one
    thing to recognise.

    It answers True only for a sign-in Windows accepted (:func:`sign_in_answer` is "approved"); Cancel, a sign-in
    Windows did not accept, and a prompt that could not be shown are all False here.
    """
    return sign_in_answer(action_description, reason) == "approved"


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
