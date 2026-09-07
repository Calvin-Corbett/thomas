"""Does the state a write would leave hold together?

Records are the only story the overlay tells, so nothing may cascade
implicitly: clearing a theme that tokens or the default theme still point at
is refused as a whole action, not quietly patched up. The caller is told what
is dangling, so it can add those records and try again.

Checked under the lock, against the resolved state (what is on disk plus the
accepted records of this action, in order), before a single byte is written.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from thomas.server.overlay import stock_tokens


class OverlayIncoherent(RuntimeError):
    """The state this write would leave does not hold together; the whole action is refused."""


def themes_in(active: dict[str, dict[str, Any]]) -> set[str]:
    """Every theme name that exists in this state: the stock five plus the overlay's own."""
    return {*stock_tokens.STOCK_THEMES, *(a.split(":", 1)[1] for a in active if a.startswith("theme:"))}


def incoherent(active: dict[str, dict[str, Any]]) -> list[str]:
    """Every reason the resolved state would not hold together, or an empty list."""
    themes = themes_in(active)
    problems: list[str] = []
    for address, rec in active.items():
        if address.startswith("token:"):
            theme = address.split(":")[1]
            if theme != "*" and theme not in themes:
                problems.append(f"{address} would be left pointing at a theme this Thomas does not have")
        elif address == "setting:default_theme" and str(rec.get("value")) not in themes:
            problems.append(f"the default theme {rec.get('value')!r} would be left unresolvable")
    return problems


def same_effect(active: dict[str, Any] | None, candidate: dict[str, Any]) -> bool:
    """Whether a set would leave the exact effective payload already in force."""
    if active is None or active.get("op") != "set" or candidate.get("op") != "set":
        return False
    if candidate.get("kind") == "element":
        return active.get("value") == candidate.get("value") and active.get("anchor") == candidate.get("anchor")
    return active.get("value") == candidate.get("value")


def _apply(active: dict[str, dict[str, Any]], record: dict[str, Any]) -> None:
    address = record["address"]
    if record["op"] == "clear":
        active.pop(address, None)
    else:
        active[address] = record


def _default_is_handled(records: list[dict[str, Any]], theme: str) -> bool:
    return any(
        rec["address"] == "setting:default_theme"
        and (rec["op"] == "clear" or rec.get("value") != theme)
        for rec in records
    )


def action_problems(before: dict[str, dict[str, Any]], records: Iterable[dict[str, Any]]) -> list[str]:
    """Audit one atomic action in order, including explicit theme-dependency handling."""
    batch = list(records)
    active = dict(before)
    token_clears = {rec["address"] for rec in batch if rec["op"] == "clear" and rec["kind"] == "token"}
    problems: list[str] = []
    for rec in batch:
        address = rec["address"]
        if rec["op"] == "set":
            if same_effect(active.get(address), rec):
                problems.append(f"{address} is already in effect and makes no durable change")
            known = themes_in(active)
            if rec["kind"] == "token":
                theme = address.split(":", 2)[1]
                if theme != "*" and theme not in known:
                    problems.append(f"{address} points at a theme not known at that action point")
            elif address == "setting:default_theme" and rec["value"] not in known:
                problems.append(f"the default theme {rec['value']!r} is not known at that action point")
        elif address not in active:
            problems.append(f"{address} clears an override that is not in effect")
        if rec["op"] == "clear" and rec["kind"] == "theme" and address in active:
            theme = address.split(":", 1)[1]
            for dependent, current in active.items():
                if dependent.startswith(f"token:{theme}:") and dependent not in token_clears:
                    problems.append(f"{dependent} must be explicitly cleared before {address} is cleared")
                if (dependent == "setting:default_theme" and current.get("value") == theme
                        and not _default_is_handled(batch, theme)):
                    problems.append(f"the default theme must be explicitly cleared or repointed before {address} is cleared")
        _apply(active, rec)
    problems.extend(incoherent(active))
    return problems


def history_problems(records: Iterable[dict[str, Any]]) -> list[str]:
    """Audit every persisted action and the state it left, without repairing history."""
    active: dict[str, dict[str, Any]] = {}
    batch: list[dict[str, Any]] = []
    action = ""
    finished: set[str] = set()
    problems: list[str] = []
    for rec in records:
        record_action = rec["by"]["action"]
        if batch and record_action != action:
            problems.extend(action_problems(active, batch))
            for item in batch:
                _apply(active, item)
            finished.add(action)
            batch = []
        if not batch:
            if record_action in finished:
                problems.append(f"action {record_action} reappears after another action")
            action = record_action
        elif rec["by"] != batch[0]["by"] or rec["base"] != batch[0]["base"]:
            problems.append(f"action envelope or base contradicts another record in {record_action}")
        batch.append(rec)
    if batch:
        problems.extend(action_problems(active, batch))
    return problems
