from __future__ import annotations

import scripts.check_release_update_gate as mod


def test_product_surface_excludes_architecture_manifest() -> None:
    assert mod._is_product_surface("thomas/_architecture.py") is False


def test_product_surface_includes_runtime_module_code() -> None:
    assert mod._is_product_surface("thomas/server/app.py") is True
