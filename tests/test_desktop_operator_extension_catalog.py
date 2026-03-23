from thomas.plugins.extension_catalog_runtime import validate_extension_catalog


def test_desktop_operator_extension_bundle_is_valid() -> None:
    payload = validate_extension_catalog()
    packs = {item["id"]: item for item in payload["packs"]}
    assert "desktop-operator" in packs
    assert packs["desktop-operator"]["valid"] is True
