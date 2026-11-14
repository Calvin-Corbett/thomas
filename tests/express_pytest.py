"""pytest glue shared by the Express lab tests: the ``lab`` fixture, ``make`` and ``skip_or_fail``.

A test module brings the fixture in with ``from tests.express_pytest import lab  # noqa: F401``. Importing this
module also imports ``tests.express_support``, so every lab fixture is registered whichever module a test starts
from.

Skips are for what this machine cannot do: no git, not Windows, no symlink privilege, 8.3 names off, no sparse
files. They are never for a broken or misspelled fixture: ``FixtureBroken`` fails the test and an unknown name
raises ``KeyError``. Set ``EXPRESS_LAB_STRICT=1`` (the run to make on your own machine before the referee is
installed) and every skip that goes through ``skip_or_fail`` fails instead, so a green run means every trick was
really built. Tests that skip on a plain platform check (``skipif(not IS_WINDOWS)``) do not go through it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import tests.express_support  # noqa: F401  (registers every lab fixture)
from tests.express_lab import ExpressLab, LabCase, build_fixture
from tests.express_winfs import EnvironmentUnavailable


def strict() -> bool:
    return os.environ.get("EXPRESS_LAB_STRICT") == "1"


def skip_or_fail(reason: str) -> None:
    """Skip with ``reason`` - or, in strict mode, fail naming it."""
    if strict():
        pytest.fail(f"EXPRESS_LAB_STRICT is set and this could not be built: {reason}")
    pytest.skip(reason)


@pytest.fixture
def lab(tmp_path: Path):
    try:
        built = ExpressLab(tmp_path / "lab")
    except EnvironmentUnavailable as exc:
        skip_or_fail(str(exc))
    yield built
    built.close()


def make(name: str, built: ExpressLab) -> LabCase:
    """Build the named trick, or skip the calling test with the reason it cannot exist on this machine."""
    try:
        return build_fixture(name, built)
    except EnvironmentUnavailable as exc:
        skip_or_fail(str(exc))
