"""Frozen regression selection and runner integrity for private source candidates."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .forge_code_self_edit import SourceCandidate


def plan_candidate_checks(
    candidate: SourceCandidate, changed: list[str]
) -> tuple[tuple[tuple[str, ...], ...], list[str]]:
    """Select existing regression checks from live source, never worker prose.

    A reference selects a check; it does not prove behavioral coverage. Files
    without a selected regression check remain explicitly uncovered.
    """
    from evolve_supervisor.coverage_floor import select_blast_radius_tests

    from .forge_code_self_edit import (
        SelfEditSnapshotError,
        _source_path,
        assert_source_unchanged,
        candidate_snapshot,
    )

    assert_source_unchanged(candidate)
    tests = {
        path: _source_path(candidate.source_root, path).read_text(encoding="utf-8")
        for path in candidate.baseline
        if path.startswith("tests/") and Path(path).name.startswith("test_") and path.endswith(".py")
    }
    names: dict[str, int] = {}
    for path in candidate.baseline:
        names[Path(path).name] = names.get(Path(path).name, 0) + 1
    selected: set[str] = set()
    uncovered = []
    for path in changed:
        direct = {
            test
            for test, content in tests.items()
            if path in content or (names.get(Path(path).name, 0) == 1 and Path(path).name in content)
        }
        if path.endswith(".py"):
            direct.update(select_blast_radius_tests([path], candidate.source_root, max_files=len(tests) + 1))
        if direct:
            selected.update(direct)
        else:
            uncovered.append(path)
    current = candidate_snapshot(candidate.candidate_root)
    runner_modules = {"pytest", "_pytest", "pluggy", "py_compile", "coverage", "sitecustomize", "usercustomize"}
    for path in current:
        root_name = PurePosixPath(path).parts[0].casefold()
        stem = root_name.split(".", 1)[0]
        # A source-owned startup hook is part of the frozen check configuration.
        # Only its exact baseline bytes are allowed, never a new/changed hook or
        # an existing replacement for the actual test runner.
        if path == "sitecustomize.py" and current[path] == candidate.baseline.get(path):
            continue
        if stem in runner_modules and (root_name == stem or root_name.endswith((".py", ".pyc", ".pyo", ".pyd", ".so"))):
            raise SelfEditSnapshotError("Candidate shadows the independent test plan runner")
    protected_checks = selected | {
        path
        for path in candidate.baseline.keys() | current.keys()
        if path.casefold().startswith(("tests/", "pytest/", "_pytest/", "pluggy/"))
        or Path(path).name.casefold() in {"conftest.py", "sitecustomize.py", "usercustomize.py"}
        or path.casefold()
        in {"pytest.ini", ".pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini", "pytest.py", "py_compile.py"}
    }
    if any(current.get(path) != candidate.baseline.get(path) for path in protected_checks):
        raise SelfEditSnapshotError("Candidate changed the independent test plan or its configuration")
    commands = []
    python_files = [path for path in changed if path.endswith(".py") and path in current]
    if python_files:
        commands.append(("python", "-m", "py_compile", *sorted(python_files)))
    if selected:
        commands.append(("python", "-m", "pytest", "-p", "no:cacheprovider", "-q", *sorted(selected)))
    return tuple(commands), sorted(uncovered)
