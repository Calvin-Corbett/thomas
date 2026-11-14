"""What a chat shows for a self-fix's approval card, and for the card a landed change was approved on.

Your decision, 2026-10-08: "Yes, batch cards". One Windows sign-in can now list several waiting self-fixes, one line
each (scripts/cage/shared_card.py). Each of their chats mirrors that shared card: which line is its own, every line of
the card, every file in its own change, and its own diff. The question panel shows a field's value on one line
(thomas/server/web/js/ask_user_panel.js), so each line of the card is a field of its own.

The mirror is never the approval: it says so, and that the list is a copy. A record that is not a well-formed shared
card shows as one change, as every card did before; a bad record never stops the chat following the rest.
"""

from __future__ import annotations

from typing import Any

SINGLE_NOTE = (
    "Approve at the Windows prompt only if its pairing code matches this one. This card cannot approve anything."
)
SHARED_NOTE = (
    "Approve at the Windows prompt only if its pairing code matches this one and its lines are the ones you expect: "
    "this list is a copy. Signing in there puts all {n} changes in; Cancel there puts none in and asks about each on "
    "its own. This card cannot approve anything."
)
EVERY_FILE = 200  # files named under "Every file in this change"; the rest are counted


def _place(place: Any) -> tuple[int, int]:
    """(position, of) of a change on a shared card: whole numbers, 1 <= position <= of. Raises on anything else."""
    k, n = place["position"], place["of"]
    if type(k) is not int or type(n) is not int or not 1 <= k <= n:
        raise ValueError(f"not a place on a card: {k!r} of {n!r}")
    return k, n


def _shared(card: dict[str, Any]) -> tuple[list[dict[str, str]], str]:
    k, n = _place(card["card"])
    lines = str(card.get("body") or "").splitlines()
    if len(lines) != n + 1:
        raise ValueError(f"a card for {n} changes has a head and {n} lines, not {len(lines)} lines")
    fields = [{"label": "This chat's change", "value": f"Number {k} of the {n} on this card"}]
    for i, line in enumerate(lines[1:], 1):
        number, dot, text = line.partition(". ")
        if number != str(i) or not dot:
            raise ValueError(f"line {i} of the card does not start with its number")
        fields.append({"label": f"{i} (this chat's)" if i == k else str(i), "value": text})
    files = card["files"]
    if not isinstance(files, list):
        raise TypeError("a change's files are a list")
    every = [str(name) for name in files]
    more = f" and {len(every) - EVERY_FILE} more" if len(every) > EVERY_FILE else ""
    fields.append({"label": "Every file in this change", "value": ", ".join(every[:EVERY_FILE]) + more})
    return fields, SHARED_NOTE.format(n=n)


def card_fields(card: dict[str, Any]) -> tuple[list[dict[str, str]], str]:
    """(fields, note) for the chat's copy of one approval card. A change on a shared card gets which line is its own,
    one field per line of the card, and every file in its change; any other record, or a shared one this cannot read,
    gets one "Change" field with the card's body, as before. Never raises: a card that cannot be read must not end the
    chat's following of the rest."""
    if isinstance(card.get("card"), dict) and card["card"]:
        try:
            return _shared(card)
        except (TypeError, KeyError, ValueError):
            pass
    return [{"label": "Change", "value": str(card.get("body") or "")}], SINGLE_NOTE


def landed_on(verdict: dict[str, Any]) -> dict[str, str] | None:
    """The "Approved on" field of a change that landed on a shared card, or the "Landed in" field of one that landed
    inside your window (Part 4); None for a single card or anything else."""
    window = verdict.get("window")
    if verdict.get("status") == "landed" and isinstance(window, dict) and window.get("pairing_code"):
        opened, code = str(window.get("opened_at") or "?"), str(window["pairing_code"])
        return {"label": "Landed in", "value": f"your window opened at {opened} (pairing code {code}), with no card"}
    place = verdict.get("card")
    if verdict.get("status") != "landed" or not isinstance(place, dict) or not place.get("pairing_code"):
        return None
    try:
        k, n = _place(place)
    except (TypeError, KeyError, ValueError):
        return None
    code = str(place["pairing_code"])
    return {"label": "Approved on", "value": f"one card for {n} changes (pairing code {code}), number {k}"}


__all__ = ["EVERY_FILE", "SHARED_NOTE", "SINGLE_NOTE", "card_fields", "landed_on"]
