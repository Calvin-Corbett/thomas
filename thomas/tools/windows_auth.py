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
        except Exception:
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
        except Exception as e:
            log.error("WindowsAuthGate: dialog error: %s", e)
            return False


# ---------------------------------------------------------------------------
# Suspicious prompt detection
# ---------------------------------------------------------------------------

# NOTE: The dialog below uses CredUIPromptForCredentials (username+password).
# For a proper Windows Hello PIN prompt, use CredUIPromptForWindowsCredentials
# with CREDUIWIN_AUTHPACKAGE_ONLY. That requires pywin32 >= 228 and is a
# future improvement.

# Patterns that indicate a prompt may be attempting to manipulate Thomas into
# bypassing guardrails, extracting system internals, or impersonating an
# authorized upgrade process.
#
# Design rules for patterns:
#   - Must be specific enough to not fire on normal developer instructions.
#   - "respond only in valid json" is NORMAL — do NOT flag it.
#   - "level 5 autonomy" is in SOUL.md — do NOT flag it.
#   - Require at least two suspicious signals in proximity, or very specific phrasing.
_SUSPICIOUS_PATTERNS = (
    # Fake authority / impersonation — requires specific impersonation phrasing
    r"(?:openai|anthropic|grok|deepmind)\s+(?:has\s+)?authoriz(?:ed|es)\s+you",
    r"i\s+am\s+(?:your\s+)?(?:developer|creator|owner)\s+.*override",
    r"maintenance\s+mode\s+.*disable\s+(?:all\s+)?(?:safety|guardrail|filter)",
    # System prompt extraction — must ask to reveal/paste the actual prompt
    r"(?:paste|print|output|reveal|show)\s+(?:me\s+)?(?:your\s+)?(?:full\s+)?system\s+prompt",
    r"(?:repeat|output)\s+(?:everything|all)\s+(?:above|before)\s+(?:this|verbatim)",
    r"what\s+(?:are\s+)?your\s+(?:exact\s+)?(?:hidden\s+)?instructions",
    # Guardrail bypass — explicit bypass language only
    r"(?:ignore|bypass|override|disable)\s+(?:all\s+)?(?:your\s+)?(?:safety|guardrail|filter|restriction)s?",
    r"(?:ignore|disregard)\s+(?:all\s+)?(?:previous|prior)\s+instructions?\s+and",
    r"pretend\s+(?:you\s+have\s+)?no\s+(?:restrictions?|rules?|guidelines?)",
    # Self-rewrite attacks — must target rules/identity specifically
    r"rewrite\s+(?:your\s+)?(?:core\s+)?(?:rules?|identity|soul|instructions?)",
    r"add\s+(?:a\s+)?(?:permanent|ironclad|unbreakable)\s+rule\s+(?:that\s+)?(?:you\s+)?(?:must|will|shall)",
)

import re as _re

_SUSPICIOUS_RE = _re.compile(
    "|".join(_SUSPICIOUS_PATTERNS),
    _re.IGNORECASE | _re.DOTALL,
)

_NO_HUMAN_MODES = {"human", "allow", "deny"}


def _normalize_no_human_mode(value: str | None) -> str:
    mode = str(value or "human").strip().lower()
    if mode in _NO_HUMAN_MODES:
        return mode
    return "human"


def check_prompt_suspicious(text: str) -> tuple[bool, str]:
    """Return (is_suspicious, matched_pattern) for a given prompt text."""
    m = _SUSPICIOUS_RE.search(str(text or ""))
    if m:
        return True, m.group(0)[:80]
    return False, ""


def gate_suspicious_prompt(
    text: str,
    action_description: str = "Proceed with flagged request",
    precomputed: tuple | None = None,
    no_human_mode: str | None = None,
) -> bool:
    """If the prompt looks suspicious, require Windows PIN before continuing.

    Args:
        text: The prompt text to check.
        action_description: Label shown in the Windows auth dialog.
        precomputed: Optional (is_suspicious, matched) tuple from a prior
            check_prompt_suspicious() call. If provided, skips the regex scan.

    Returns True if the user authorized (or prompt is clean).
    Returns False if suspicious AND user cancelled/failed PIN.
    """
    if precomputed is not None:
        suspicious, matched = precomputed
    else:
        suspicious, matched = check_prompt_suspicious(text)

    if not suspicious:
        return True

    mode = _normalize_no_human_mode(no_human_mode)
    if mode == "allow":
        log.warning(
            "Suspicious prompt detected (matched: %r). no-human mode allow: bypassing PIN gate.",
            matched,
        )
        return True
    if mode == "deny":
        log.warning(
            "Suspicious prompt detected (matched: %r). no-human mode deny: blocking request.",
            matched,
        )
        return False

    log.warning("Suspicious prompt detected (matched: %r). Requiring Windows PIN.", matched)
    gate = get_auth_gate()
    return gate.request_authorization(
        action_description,
        reason=(
            f"This request matched a suspicious pattern: '{matched}'\n\n"
            "If this is really you, enter your Windows PIN to proceed.\n"
            "Cancel to abort."
        ),
    )


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
