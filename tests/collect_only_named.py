"""Collect only the test files a run names (2026-10-29).

Handed files by name, pytest collects their folder again for every file and skips its own cache for it ("files
given directly multiple times on the command line should not be deduplicated", _pytest/main.py), so each named file
built a node for every one of the ~1,900 files in tests/, and on Windows compared each with samefile(), two stats
apiece. Collecting 5 named files took 8.8 s of a 10.9 s run (1.8 s for one file); passing over the files the run did
not name before pytest builds them takes it to 2.3 s (0.35 s for one), with the same tests collected.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_NAMED = pytest.StashKey[frozenset[str]]()


def named_files(config: pytest.Config) -> frozenset[str]:
    """Every file the run names, or none when one argument is not an existing file (a folder, a module name)."""
    if _NAMED not in config.stash:
        base = str(config.invocation_params.dir)
        named: set[str] = set()
        for arg in config.args:
            path = os.path.normcase(os.path.abspath(os.path.join(base, str(arg).split("::", 1)[0])))
            if not os.path.isfile(path):
                named = set()
                break
            named.add(path)
        config.stash[_NAMED] = frozenset(named)
    return config.stash[_NAMED]


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    """Pass over a Python file the run did not name, when it named only files; decide nothing otherwise."""
    if collection_path.suffix != ".py" or collection_path.name in ("conftest.py", "__init__.py"):
        return None
    named = named_files(config)
    return True if named and os.path.normcase(str(collection_path)) not in named else None
