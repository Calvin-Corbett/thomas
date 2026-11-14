"""The check in front of a plugin's deletion compares real folders, because a false yes here costs files."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from thomas.plugins import p103_plugin_uninstall_cleanup as uninstall


def test_uninstalling_a_plugin_cannot_reach_the_twin_of_its_folder(tmp_path: Path) -> None:
    root = tmp_path / "work"
    twin = tmp_path / "wor\u212a"
    root.mkdir()
    twin.mkdir()
    if os.path.samefile(root, twin):
        pytest.skip("This disk folds the Kelvin sign, so these are not two folders")

    uninstall._ensure_inside_root(root, root / "a-plugin")
    with pytest.raises(uninstall.PluginUninstallCleanupError):
        uninstall._ensure_inside_root(root, twin / "a-plugin")
