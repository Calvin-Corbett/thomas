"""Shared pytest fixtures used by cross-suite tests.

This module must stay import-side-effect free so test collection is reliable.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def runtime_root() -> Path:
    """Repository root path for tests that resolve project-relative files."""

    return Path(__file__).resolve().parents[1]


@pytest.fixture()
def thomas_tmp_dir(tmp_path: Path) -> Path:
    """Per-test temp directory for Thomas runtime artifacts."""

    return tmp_path
