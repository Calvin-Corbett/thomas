"""A benchmark run stays under its own folder, compared folder by folder."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from thomas.core import benchmark_lane


def test_a_benchmark_root_cannot_be_the_twin_of_its_parent(tmp_path: Path) -> None:
    root = tmp_path / "work"
    twin = tmp_path / "wor\u212a"
    root.mkdir()
    twin.mkdir()
    if os.path.samefile(root, twin):
        pytest.skip("This disk folds the Kelvin sign, so these are not two folders")

    assert benchmark_lane._commonpath_startswith(root, root / "run")
    assert not benchmark_lane._commonpath_startswith(root, twin / "run")
