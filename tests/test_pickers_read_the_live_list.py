"""The Chat picker reads the live list; it keeps no list of models of its own."""

from __future__ import annotations

import re
from pathlib import Path

PICKER = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "js" / "chat_model_picker.js"
BOOT = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "js" / "chat_boot.js"


def _function_body(text: str, name: str) -> str:
    start = re.search(rf"function {re.escape(name)}\(", text)
    assert start, f"{name} not found"
    rest = text[start.start() :]
    end = re.search(r"\n    function ", rest)
    return rest[: end.start()] if end else rest


def test_the_picker_reads_the_catalog_and_can_ask_for_a_fresh_one() -> None:
    text = PICKER.read_text(encoding="utf-8")
    assert "fetch('/api/models/catalog')" in text
    assert "'/api/models/catalog/refresh'" in text
    assert "Check for new models" in text


def test_the_picker_holds_no_hand_typed_model_ids() -> None:
    text = PICKER.read_text(encoding="utf-8")
    assert "/api/openai-codex/models" not in text
    assert not re.search(r"['\"](gpt-\d|claude-\w)", text)


def test_apply_catalog_only_fills_usable_profiles() -> None:
    body = _function_body(PICKER.read_text(encoding="utf-8"), "applyCatalog")
    assert "profileIsUsable(p)" in body


def test_checked_label_uses_only_usable_profiles_and_reads_the_error() -> None:
    body = _function_body(PICKER.read_text(encoding="utf-8"), "checkedLabel")
    assert "profileIsUsable" in body
    assert ".error" in body


def test_profile_is_usable_reads_keyless_ok() -> None:
    body = _function_body(PICKER.read_text(encoding="utf-8"), "profileIsUsable")
    assert "keyless_ok" in body


def test_boot_and_the_menu_agree_about_which_profiles_can_answer() -> None:
    """A profile the menu offers has to survive a reload as well.

    Boot kept a rule of its own, and it knew only about a stored key: a Claude
    plan chosen in the menu was silently swapped for another profile the next
    time the page loaded, which reads as the choice never having been made.
    """
    menu = _function_body(PICKER.read_text(encoding="utf-8"), "profileIsUsable")
    boot = BOOT.read_text(encoding="utf-8")
    for flag in ("has_api_key", "keyless_ok", "claude_plan", "openai_codex"):
        assert flag in menu, f"the model menu no longer reads {flag}"
        assert flag in boot, f"boot no longer reads {flag}, so its rule has drifted from the menu's"


def test_set_profile_handles_keep_id_and_still_notifies_change() -> None:
    body = _function_body(PICKER.read_text(encoding="utf-8"), "setProfile")
    assert "keepId" in body
    assert "ThomasChatModelSelection.changed" in body


def test_a_saved_model_the_connection_stopped_offering_is_not_switched_on_load() -> None:
    text = BOOT.read_text(encoding="utf-8")
    assert re.search(r"savedId\s*&&\s*!saved", text)
    assert "keepId: savedId" in text
    assert "state.modelId = savedId" not in text
