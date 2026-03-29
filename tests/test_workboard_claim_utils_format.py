from __future__ import annotations

import scripts.workboard_claim_utils as mod


def test_resolve_display_name_uses_virtual_office_default() -> None:
    assert mod._resolve_display_name(None, "thomas") == "Thomas"
    assert mod._resolve_display_name(None, "Codex 3-Worker-9").startswith("Codex ")


def test_format_claim_always_emits_identity_fields() -> None:
    claim = mod._format_claim(
        "Codex 3",
        "thomas/cli/main.py",
        "runtime lane",
        name=mod._resolve_display_name(None, "Codex 3"),
        role="solo",
        parent="",
    )

    assert claim.startswith("- agent=Codex 3;")
    assert "name=Codex 3;" in claim
    assert "role=solo;" in claim
    assert "parent=none;" in claim
    assert "scope=thomas/cli/main.py;" in claim
    assert "task=runtime lane" in claim
