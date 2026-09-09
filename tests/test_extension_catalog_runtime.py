from __future__ import annotations

from thomas.plugins.extension_catalog_runtime import validate_extension_catalog


def test_extension_catalog_runtime_reports_valid_packs() -> None:
    payload = validate_extension_catalog()
    assert int(payload.get("total") or 0) >= 480
    assert int(payload.get("invalid") or 0) == 0
    packs = payload.get("packs")
    assert isinstance(packs, list) and packs
    first = packs[0]
    assert "id" in first
    assert "capabilities" in first
