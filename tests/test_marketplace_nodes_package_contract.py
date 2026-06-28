from __future__ import annotations

import thomas.marketplace.nodes as nodes_pkg


def test_marketplace_nodes_package_docstring_matches_live_surface() -> None:
    doc = nodes_pkg.__doc__ or ""

    assert "Node host models" in doc
    assert "registry support" in doc
    assert "Scaffold package" not in doc
