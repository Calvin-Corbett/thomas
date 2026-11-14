"""The one-shot OS prompt that lets the owner past a protected path.

Split from ``thomas/tools/runtime_protection_paths.py`` so neither file grows past the
per-commit limit. Behaviour is unchanged; both re-export it.
"""

from __future__ import annotations

import logging
import threading
from pathlib import PurePosixPath

log = logging.getLogger("thomas.tools.filesystem")

__all__ = ["_maybe_apply_native_auth_override"]


def _maybe_apply_native_auth_override(
    *,
    reason: str,
    rel_posix: PurePosixPath,
    allow_native_auth_override: bool,
    action_description: str,
    card: object | None = None,
) -> str | None:
    """Per-operation native-auth gate: if approved, return None (allow).

    With a trusted card (thomas/tools/trusted_card.py) the chat card shows the
    real diff and a pairing code, the Windows dialog is worded only by the pinned
    catalogue, and a file that guards Thomas is asked every time (policy C). The
    model's own words -- ``action_description`` carries its ``reason`` -- never
    reach the Windows dialog, card or no card.
    """
    if not allow_native_auth_override:
        return reason

    # The approval cards must be the pinned ones before anything is asked.
    from thomas.tools import trusted_card

    try:
        trusted_card.require_trusted_catalogue()
    except trusted_card.CatalogueTampered as exc:
        log.error("Protected path '%s' REFUSED -- %s", rel_posix, exc)
        return f"{reason} Refused without asking: {exc}."

    # Import lazily so filesystem.py doesn't drag GUI/credential-dialog
    # dependencies into every import path.
    try:
        from thomas.tools.native_auth import request_native_authorization
    except (ImportError, OSError, RuntimeError) as exc:
        log.warning(
            "Protected path '%s': native-auth module unavailable (%s); honoring refusal",
            rel_posix,
            exc,
        )
        return reason

    action_text = action_description or f"Modify protected runtime path: {rel_posix}"

    # Owner direction 2026-09-22: every protected file is its own approval, and
    # the owner chooses how far an approval reaches -- this file, this task, or
    # everything -- on a card in the chat that asked, with one password.
    from thomas.core import protected_write_grants
    from thomas.core.session_scope import active_chat_id
    from thomas.tools.protected_write_card import ask_on_card, can_ask_on_a_card

    task = active_chat_id()
    log.info(
        "Protected path '%s': asking on a card=%s (task=%r, thread=%s)",
        rel_posix,
        can_ask_on_a_card(task),
        task,
        threading.current_thread().name,
    )
    # Policy C: a file that guards Thomas never rides a scope grant.
    dangerous = bool(card is not None and getattr(card, "danger", None))
    if not dangerous and protected_write_grants.allowed(task, str(rel_posix)):
        log.warning("Protected path '%s' APPROVED by an earlier approval on a card", rel_posix)
        return None
    if can_ask_on_a_card(task):
        why = str(getattr(card, "why", "") or "") if card is not None else action_text
        if ask_on_card(task=task, path=str(rel_posix), why=why, card=card):
            log.warning("Protected path '%s' APPROVED on the owner's card", rel_posix)
            return None
        log.info("Protected path '%s' REFUSED on the owner's card", rel_posix)
        return reason

    if card is not None:
        prompt_action, auth_reason = card.dialog()
    else:
        # Worded here, never from the caller: action_text carries the model's reason.
        prompt_action = f"Let Thomas change {rel_posix}"
        # `reason` is the path check's own refusal, written by code, so it may
        # appear; `action_text` is not, because it carries the model's words.
        auth_reason = (
            "An agent-spawned tool is attempting to modify a protected Thomas "
            "runtime path. Approve only if you initiated this operation.\n\n"
            f"{reason}"
        )

    try:
        approved = request_native_authorization(prompt_action, auth_reason)
    except (OSError, RuntimeError) as exc:
        log.warning(
            "Protected path '%s': native-auth raised (%s); honoring refusal",
            rel_posix,
            exc,
        )
        return reason

    if approved:
        log.warning(
            "Protected path '%s' APPROVED via native OS auth override (%s)",
            rel_posix,
            action_text,
        )
        return None

    log.info(
        "Protected path '%s' REFUSED — native OS auth not granted",
        rel_posix,
    )
    return reason
