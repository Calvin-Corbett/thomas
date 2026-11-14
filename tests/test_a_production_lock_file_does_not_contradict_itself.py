"""The Docker production lock file does not contradict itself (2026-09-30).

The Dockerfile's production branch (the default for `docker build .` and
`docker compose up`) runs `pip install -r requirements-lock.txt` on
python:3.12-slim. The Dependabot pass of 2026-05-28 raised Twisted to 26.4.0 and
pypdf to 6.10.2 but left the pins those releases depend on at the versions the
file was first frozen from, so pip's resolver stopped with ResolutionImpossible
("The user requested attrs==21.2.0 / twisted 26.4.0 depends on attrs>=22.2.0")
and the image could not be built.

Each row below is one requirement copied from a release's own PyPI metadata
(Requires-Dist, read for CPython 3.12 on Linux on 2026-09-30). The rows are
hermetic on purpose: a full check is `pip install --dry-run --ignore-installed -r
requirements-lock.txt` in a Python 3.12 venv, which needs the network. When you
bump a pin in the lock, run that command and add the row for whatever it reports.

A row applies to the release its owner names. `>=` owners are floors (a newer
Twisted or pipx has kept or raised these needs, so the row still guards it);
`==` owners are one exact release whose range a later release may loosen. A row
whose owner the lock no longer holds is skipped with a message, never passed, so a
bump that outruns a row shows up in the test summary.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

LOCK = Path(__file__).resolve().parents[1] / "requirements-lock.txt"

# (locked release that has the need, package it needs, version range it needs)
NEEDS = [
    ("Twisted>=26.4.0", "attrs", ">=22.2.0"),
    ("Twisted>=26.4.0", "automat", ">=24.8.0"),
    ("Twisted>=26.4.0", "incremental", ">=24.7.0"),
    ("pipx>=1.0.0", "argcomplete", ">=1.9.4"),
    ("pyasn1-modules==0.4.2", "pyasn1", ">=0.6.1,<0.7"),
    # The old pin: pyasn1-modules 0.2.1 caps pyasn1 below the 0.6.3 the lock carries.
    ("pyasn1-modules==0.2.1", "pyasn1", "<0.5"),
]


def _pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in LOCK.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9._-]+)==(\S+)$", line.strip())
        if match:
            pins[canonicalize_name(match.group(1))] = match.group(2)
    return pins


@pytest.mark.parametrize(("owner", "package", "needed"), NEEDS, ids=[f"{o}->{p}" for o, p, _ in NEEDS])
def test_each_pin_meets_the_version_its_neighbour_needs(owner: str, package: str, needed: str) -> None:
    pins = _pins()
    requirement = Requirement(owner)
    held = pins.get(canonicalize_name(requirement.name))
    if held is None or not requirement.specifier.contains(held):
        pytest.skip(
            f"row recorded for {owner}; requirements-lock.txt pins {requirement.name}=={held}. "
            "If the lock moved on, re-check that release's Requires-Dist on PyPI and refresh or drop this row"
        )
    locked = pins[canonicalize_name(package)]
    assert Version(locked) in SpecifierSet(needed), (
        f"requirements-lock.txt pins {requirement.name}=={held} and {package}=={locked}, but {owner} needs "
        f"{package}{needed}; pip cannot resolve the file, so the production Docker image cannot be built"
    )


def test_pypdf_6_is_not_locked_beside_camelot_py_1() -> None:
    # camelot-py 1.0.9 requires pypdf<6.0 on Python 3.12. Nothing in thomas/ imports it, and the
    # project itself asks for pypdf>=6.0,<7 (pyproject.toml, the server extra), so the lock drops
    # camelot-py rather than going back to a pypdf with open security advisories.
    pins = _pins()
    assert Version(pins["pypdf"]) >= Version("6.0"), "the pypdf 6 security bump must stay"
    assert pins.get("camelot-py") != "1.0.9", "camelot-py 1.0.9 cannot be installed with pypdf 6"
