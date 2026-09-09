from thomas.marketplace.companion.contracts import allowed_permissions


def test_desktop_operator_permissions_are_allowed() -> None:
    perms = set(allowed_permissions())
    assert "device.screen.read" in perms
    assert "device.window.read" in perms
    assert "device.accessibility.read" in perms
    assert "device.input.write" in perms
    assert "device.vm.control" in perms
