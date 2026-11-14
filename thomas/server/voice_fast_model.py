"""Which model answers when you talk: the smallest and fastest one you have set up.

A spoken reply is only worth having if it comes back quickly, so by default the voice picks, from the models the model
list already holds as ready to use, the one whose name marks it as the smallest tier. The order below is the whole rule:
the first word that any ready model carries wins, and among models carrying that word the one listed first wins.
Nothing is asked of a provider, and a name carrying none of the words is never picked, so with no small model set up the
answer is ``None`` and the turn uses the model you chose. A model that does not answer in words is never picked either:
``google/nano-banana-2-lite`` carries "nano" but makes pictures, and once it was the voice's answer every spoken question
went to a picture model. The id is checked here as well as the catalog's ``chat`` mark, because a catalog saved before
that mark was right still says every model chats.
"""

from __future__ import annotations

from typing import Any

from thomas.models.catalog_rules import writes_text

# Smallest first. Matched against the lower-case model id as a whole word (split on - _ . : / and spaces).
SIZE_WORDS = ("nano", "tiny", "lite", "haiku", "mini", "flash", "spark", "small", "instant")
# Code runs only the GPT and Claude families, so that surface is held to them.
CODE_FAMILIES = ("openai", "anthropic", "claude")


def _words(model_id: str) -> set[str]:
    cleaned = "".join(" " if char in "-_.:/" else char for char in model_id.lower())
    return set(cleaned.split())


def _rank(model_id: str) -> int | None:
    found = _words(model_id)
    for index, word in enumerate(SIZE_WORDS):
        if word in found:
            return index
    return None


def pick(rows: list[dict[str, Any]], *, surface: str = "chat") -> dict[str, str] | None:
    """The best row as ``{"profile", "id", "label"}``, or None when no ready model is marked small."""
    best: tuple[int, int] | None = None
    chosen: dict[str, Any] | None = None
    for position, row in enumerate(rows):
        model_id = str(row.get("id") or "").strip()
        if not model_id or not row.get("profile") or row.get("available") is False or row.get("hidden"):
            continue
        if (row.get("capabilities") or {}).get("chat") is False or not writes_text(model_id):
            continue
        if surface == "code" and str(row.get("family") or "").lower() not in CODE_FAMILIES:
            continue
        rank = _rank(model_id)
        if rank is not None and (best is None or (rank, position) < best):
            best, chosen = (rank, position), row
    if chosen is None:
        return None
    model_id = str(chosen["id"])
    return {
        "profile": str(chosen["profile"]),
        "id": model_id,
        "label": str(chosen.get("display_name") or model_id),
    }


def chosen(setting: str, rows: list[dict[str, Any]], *, surface: str = "chat") -> dict[str, str] | None:
    """What the setting asks for: ``auto`` runs the rule, ``profile|id`` names a model that must still be ready."""
    if setting == "auto":
        return pick(rows, surface=surface)
    profile, _, model_id = setting.partition("|")
    for row in rows:
        if row.get("profile") == profile and row.get("id") == model_id and row.get("available") is not False:
            return {"profile": profile, "id": model_id, "label": str(row.get("display_name") or model_id)}
    return None
