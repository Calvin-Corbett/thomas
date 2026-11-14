"""Your window's three cards and its limits live in the pinned catalogue (spec section 8.4-8.7).

Changing a word or a limit takes your own commit and a re-pin (scripts/cage/pin_catalogue.ps1). The owner's desk,
which renders what the caged server names, never shows one of them. Tests use their own tmp pin and cage folders.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.cage import owner_desk

from thomas.tools import trusted_card

WINDOW_KINDS = ("open_window", "open_window_away", "undo_change", "revert_change")


def _longest(kind: str) -> dict[str, str]:
    spec = trusted_card.load_catalogue().KINDS[kind]
    return {name: "W" * spec.cap(name) for name in spec.fields}


def test_the_window_limits_are_pinned_at_the_spec_values() -> None:
    catalogue = trusted_card.load_catalogue()
    assert catalogue.WINDOW_CEILING_MINUTES == 525600, (
        "a window lasts until you turn it off, a year at most (2026-10-27)"
    )
    assert catalogue.WINDOW_DEFAULT_MINUTES == 120
    assert catalogue.WINDOW_MAX_LANDINGS == 25
    assert catalogue.WINDOW_IDLE_MINUTES == 15


def test_the_open_window_card_says_how_long_until_when_how_many_and_that_no_more_cards_come() -> None:
    catalogue = trusted_card.load_catalogue()
    title, body = catalogue.render(
        "open_window", {"minutes": "120", "ends": "Thu 16:05", "waiting": "3", "cap": catalogue.window_cap_words(25)}
    )
    assert title == "Let Thomas land checked changes while you are here"
    for words in ("120 minute(s)", "until Thu 16:05", "3 change(s) are waiting", "without another card", "at most 25"):
        assert words in body
    assert "the checker passed and a second look found safe" in body
    assert "operator" not in body and "reviewed" not in body, "no one outside Thomas looks at a change first"
    assert "Cancel opens nothing" in body


@pytest.mark.parametrize("kind", WINDOW_KINDS)
def test_every_window_card_fits_the_windows_prompt_at_its_longest(kind: str) -> None:
    catalogue = trusted_card.load_catalogue()
    details = _longest(kind)
    title, body = catalogue.render(kind, details)
    card = trusted_card.TrustedCard(kind, details, "0" * 64, "nonce", "ABC-DEF", title, body)
    action, reason = card.dialog()
    assert len(action) + 2 + len(catalogue.RETRY_NOTE) + 2 + len(reason) <= catalogue.DIALOG_LIMIT


@pytest.mark.parametrize("kind", WINDOW_KINDS)
def test_a_window_card_takes_exactly_its_own_fields(kind: str) -> None:
    catalogue = trusted_card.load_catalogue()
    with pytest.raises(ValueError):
        catalogue.render(kind, {**_longest(kind), "extra": "x"})


def test_the_catalogue_stays_ascii_for_its_pin() -> None:
    trusted_card.CATALOGUE_PATH.read_bytes().decode("ascii")


@pytest.mark.parametrize("kind", WINDOW_KINDS)
def test_the_owners_desk_never_shows_a_window_card(kind: str, tmp_path: Path) -> None:
    pins = tmp_path / "pins"
    pins.mkdir()
    (pins / trusted_card.PIN_NAME).write_text(trusted_card.catalogue_digest(trusted_card.CATALOGUE_PATH))
    requests = tmp_path / "cage" / "desk" / "requests"
    requests.mkdir(parents=True)
    rid = "a" * 32
    request = {"id": rid, "kind": kind, "details": _longest(kind), "content_hash": "0" * 64}
    (requests / f"{rid}.json").write_text(json.dumps(request), encoding="utf-8")
    asked: list[tuple[str, str]] = []

    owner_desk.serve_once(tmp_path / "cage", ask=lambda a, r: asked.append((a, r)) or True, pin_root=pins)

    answer = json.loads((tmp_path / "cage" / "desk" / "answers" / f"{rid}.json").read_text(encoding="utf-8"))
    assert asked == [] and answer["approved"] is False
