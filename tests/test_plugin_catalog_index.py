from __future__ import annotations

from pathlib import Path

import thomas.plugins as plugins_pkg
from thomas.plugins.catalog_index import list_plugin_modules


def test_plugins_package_describes_runtime_catalog() -> None:
    doc = plugins_pkg.__doc__ or ""

    assert "Plugin runtime package" in doc
    assert "prompt-pack module catalog" in doc
    assert "accelerated catch-up" not in doc
    assert plugins_pkg.__all__ == ["list_plugin_modules"]


def test_list_plugin_modules_filters_prompt_pack_pattern(tmp_path: Path) -> None:
    (tmp_path / "p100_alpha.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "p101_bravo.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("ignore\n", encoding="utf-8")
    (tmp_path / "not_plugin.py").write_text("x = 1\n", encoding="utf-8")

    assert list_plugin_modules(tmp_path) == ["p100_alpha", "p101_bravo"]
