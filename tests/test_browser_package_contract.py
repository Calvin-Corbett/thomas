from __future__ import annotations

import thomas.browser as browser_pkg


def test_browser_package_describes_live_runtime_contract() -> None:
    doc = browser_pkg.__doc__ or ""

    assert "live ``thomas.tools.browser`` runtime" in doc
    assert "Scaffold" not in doc


def test_browser_package_exports_runtime_bridge_contract() -> None:
    assert browser_pkg.CANONICAL_BROWSER_RUNTIME == "thomas.tools.browser"
    assert browser_pkg.CONTRACT_PACKAGE == "thomas.browser"
    assert browser_pkg.__all__ == [
        "CANONICAL_BROWSER_RUNTIME",
        "CONTRACT_PACKAGE",
        "browser_runtime_status",
        "import_browser_runtime",
    ]
