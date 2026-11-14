"""The two things BootDoctor needs from outside thomas.core.

thomas.core sits at the bottom of the dependency tree and may not import thomas.tools or
thomas.server, so ``run_boot_doctor`` takes them as arguments and its entry points pass these.
Both import lazily: a broken install is exactly when BootDoctor runs, and it must still report.
"""

from __future__ import annotations

from pathlib import Path

from thomas.core.boot_ai_summary import LOOKUP_ERRORS


def windows_authorize(action: str, reason: str) -> bool:
    """Ask for the Windows PIN or password. No answer means no.

    This is the question in front of any file access outside the Thomas root, so a tools package that will not import,
    or a prompt that cannot be shown, is a denial and never an approval.
    """
    try:
        from thomas.tools.windows_auth import get_auth_gate

        return bool(get_auth_gate().request_authorization(action_description=action, reason=reason))
    except LOOKUP_ERRORS:
        return False


def stored_api_key(state_dir: Path, profile: str) -> str | None:
    """The API key saved for a model profile in Settings, if there is one."""
    try:
        from thomas.server.secrets import SecretStore
    except LOOKUP_ERRORS:
        return None
    return SecretStore(state_dir).get(profile)
