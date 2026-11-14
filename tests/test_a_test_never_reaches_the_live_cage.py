"""A test never writes into the live cage, however it was set up.

On 2026-10-24 a copy of a shared-card test run from .thomas/scratch (outside tests/, where conftest points the cage at a
temp folder) and a fixture shared across tests wrote fake hand-ins into C:\\ProgramData\\ThomasCage\\inbox; the live
promoter refused some and made a card of one. cage_root() now refuses the live folder under pytest.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.tools import cage_shell


def test_under_pytest_the_live_cage_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cage_shell.CAGE_ROOT_ENV, raising=False)
    monkeypatch.setattr(cage_shell, "DEFAULT_CAGE_ROOT", cage_shell._LIVE_CAGE_ROOT)
    with pytest.raises(RuntimeError, match="a test reached the live cage"):
        cage_shell.cage_root()


def test_a_cage_root_the_test_set_is_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(cage_shell.CAGE_ROOT_ENV, str(tmp_path))
    assert cage_shell.cage_root() == tmp_path


def test_a_redirected_default_is_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cage_shell.CAGE_ROOT_ENV, raising=False)
    monkeypatch.setattr(cage_shell, "DEFAULT_CAGE_ROOT", tmp_path)
    assert cage_shell.cage_root() == tmp_path


def test_work_that_outlives_its_test_still_lands_in_the_runs_own_cage() -> None:
    """2026-10-25 19:59: a hand-in a test had started finished after it, once the per-test cage folder was undone,
    and wrote into the live inbox. The run's own cage folder is what is left between and after tests."""
    from tests import conftest

    between_tests = Path(conftest._RUN_FOLDERS[cage_shell.CAGE_ROOT_ENV])
    assert between_tests != cage_shell._LIVE_CAGE_ROOT and conftest.TEST_DATA_ROOT in between_tests.parents


def test_outside_pytest_the_live_cage_is_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cage_shell.CAGE_ROOT_ENV, raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(cage_shell, "DEFAULT_CAGE_ROOT", cage_shell._LIVE_CAGE_ROOT)
    assert cage_shell.cage_root() == Path(r"C:\ProgramData\ThomasCage")
