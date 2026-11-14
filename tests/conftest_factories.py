"""Shared pytest fixtures used by cross-suite tests.

This module must stay import-side-effect free so test collection is reliable.
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _each_test_has_its_own_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep implicit home-relative discovery in a per-test folder outside tmp_path."""
    home = tmp_path_factory.mktemp("home")
    gitconfig = home / ".gitconfig"
    gitconfig.write_text("[user]\n\tname = Thomas Test\n\temail = thomas-test@example.invalid\n", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("CODEX_HOME", raising=False)
    assert Path.home() == home


@pytest.fixture(scope="session")
def runtime_root() -> Path:
    """Repository root path for tests that resolve project-relative files."""

    return Path(__file__).resolve().parents[1]


@pytest.fixture()
def thomas_tmp_dir(tmp_path: Path) -> Path:
    """Per-test temp directory for Thomas runtime artifacts."""

    return tmp_path
