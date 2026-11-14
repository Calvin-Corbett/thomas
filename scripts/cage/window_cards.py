"""Asking one of the window's pinned cards at your Windows sign-in, through the promoter's own asker (spec 8.4-8.6).

The words come only from the pinned catalogue (open_window, open_window_away, undo_change, revert_change); the
pairing code is derived from exactly what is asked. The prompt is the promoter's: never the owner's desk, never Thomas's
page. While the cards do not match their pin, or after three sign-ins Windows did not accept, nothing is asked and the
answer is "failed", which is never a yes and never a no.
"""

from __future__ import annotations

from pathlib import Path

from scripts.cage import self_change_promoter as sp

from thomas.tools import trusted_card


def ask_card(p: sp.Promoter, kind: str, details: dict[str, object], digest: str, nonce: str) -> tuple[str, str]:
    """("approved" | "cancelled" | "failed", the pairing code shown) for one window card."""
    if p._hold_reason():
        return "failed", ""
    catalogue = trusted_card.load_catalogue()
    shown = {name: str(value) for name, value in details.items()}
    title, body = catalogue.render(kind, shown)
    code = catalogue.pairing_code(kind, shown, digest, nonce)
    card = trusted_card.TrustedCard(
        kind=kind, details=shown, content_hash=digest, nonce=nonce, code=code, title=title, body=body
    )
    action, reason = card.dialog()
    if len(action) + 2 + len(catalogue.RETRY_NOTE) + 2 + len(reason) > catalogue.DIALOG_LIMIT:
        raise ValueError(f"the {kind} card would not fit the Windows prompt, so it is not shown")
    p._meta, p._sub_dir = {"id": nonce}, Path(nonce)
    return p._sign_in(action, reason, catalogue.RETRY_NOTE, still=lambda: None), code


__all__ = ["ask_card"]
