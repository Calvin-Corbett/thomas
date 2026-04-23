from __future__ import annotations

from pathlib import Path

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


def test_atomic_write_uses_unique_temp_path_per_call(tmp_path, monkeypatch) -> None:
    target = tmp_path / "WORKBOARD.md"
    target.write_text("initial", encoding="utf-8")
    seen_tmp_names: list[str] = []
    real_replace = Path.replace

    def _record_replace(self: Path, destination: Path) -> Path:
        seen_tmp_names.append(self.name)
        return real_replace(self, destination)

    monkeypatch.setattr(Path, "replace", _record_replace)

    mod._atomic_write(target, "first")
    mod._atomic_write(target, "second")

    assert target.read_text(encoding="utf-8") == "second"
    assert len(seen_tmp_names) == 2
    assert len(set(seen_tmp_names)) == 2


def test_atomic_write_retries_transient_permission_error(tmp_path, monkeypatch) -> None:
    target = tmp_path / "WORKBOARD.md"
    target.write_text("initial", encoding="utf-8")
    replace_calls = {"count": 0}
    real_replace = Path.replace

    def _flaky_replace(self: Path, destination: Path) -> Path:
        replace_calls["count"] += 1
        if replace_calls["count"] == 1:
            raise PermissionError("workboard busy")
        return real_replace(self, destination)

    monkeypatch.setattr(Path, "replace", _flaky_replace)

    mod._atomic_write(target, "updated")

    assert target.read_text(encoding="utf-8") == "updated"
    assert replace_calls["count"] == 2
