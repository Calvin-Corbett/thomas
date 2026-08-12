"""Blue-owned changed-line coverage floor for evolve candidates."""

from __future__ import annotations

import ast
import difflib
import os
import subprocess  # nosec
import sys
import tempfile
from pathlib import Path
from typing import Any

MAX_BLAST_RADIUS_TEST_FILES = 8
MAX_DEPENDENT_SMOKE_TEST_FILES = 3
PYTHON_MODULE_ROOTS = ("thomas", "scripts")


def normalize_relpath(value: str | Path) -> str:
    return str(value or "").replace("\\", "/").lstrip("./")


def changed_module_refs(changed_py: list[str]) -> set[tuple[str, str, str, bool]]:
    refs: set[tuple[str, str, str, bool]] = set()
    for rel in changed_py:
        norm = normalize_relpath(rel)
        if not norm.endswith(".py") or not any(norm.startswith(f"{root}/") for root in PYTHON_MODULE_ROOTS):
            continue
        is_package = norm.endswith("/__init__.py")
        if is_package:
            dotted = norm[: -len("/__init__.py")].replace("/", ".")
        else:
            dotted = norm[:-3].replace("/", ".")
        parent, _, leaf = dotted.rpartition(".")
        refs.add((dotted, parent, leaf, is_package))
    return refs


def _module_name_for_relpath(rel: str) -> str:
    norm = normalize_relpath(rel)
    if not norm.endswith(".py") or not any(norm.startswith(f"{root}/") for root in PYTHON_MODULE_ROOTS):
        return ""
    if norm.endswith("/__init__.py"):
        return norm[: -len("/__init__.py")].replace("/", ".")
    return norm[:-3].replace("/", ".")


def _package_for_module(module_name: str, is_package: bool) -> str:
    if is_package:
        return module_name
    package, _sep, _leaf = module_name.rpartition(".")
    return package


def _resolve_import_from(module_name: str, is_package: bool, level: int, imported_from: str) -> str:
    if level <= 0:
        return imported_from
    parts = _package_for_module(module_name, is_package).split(".")
    if level > len(parts):
        return imported_from
    base = ".".join(parts[: len(parts) - level + 1])
    if imported_from:
        return f"{base}.{imported_from}" if base else imported_from
    return base


def _imported_module_names(path: Path, repo_root: Path) -> set[str]:
    rel = normalize_relpath(path.relative_to(repo_root).as_posix())
    module_name = _module_name_for_relpath(rel)
    if not module_name:
        return set()
    is_package = rel.endswith("/__init__.py")
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return set()

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(str(alias.name or "") for alias in node.names if alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_import_from(module_name, is_package, int(node.level or 0), str(node.module or ""))
            if base:
                imports.add(base)
    return imports


def _import_reaches_target(imported: str, target: str) -> bool:
    return imported == target or imported.startswith(target + ".")


def _dependent_module_refs(
    module_refs: set[tuple[str, str, str, bool]], repo_root: Path
) -> set[tuple[str, str, str, bool]]:
    targets = {dotted for dotted, _parent, _leaf, _is_package in module_refs}
    if not targets:
        return set()

    module_imports: dict[str, set[str]] = {}
    for root in PYTHON_MODULE_ROOTS:
        module_root = Path(repo_root) / root
        if not module_root.is_dir():
            continue
        for path in module_root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            rel = normalize_relpath(path.relative_to(repo_root).as_posix())
            module_name = _module_name_for_relpath(rel)
            if module_name:
                module_imports[module_name] = _imported_module_names(path, Path(repo_root))

    changed = True
    while changed:
        changed = False
        for module_name, imports in module_imports.items():
            if module_name in targets:
                continue
            if any(_import_reaches_target(imported, target) for imported in imports for target in targets):
                targets.add(module_name)
                changed = True

    dependents = targets - {dotted for dotted, _parent, _leaf, _is_package in module_refs}
    refs: set[tuple[str, str, str, bool]] = set()
    for dotted in dependents:
        parent, _sep, leaf = dotted.rpartition(".")
        refs.add((dotted, parent, leaf, False))
    return refs


def test_imports_changed_module(test_path: Path, module_refs: set[tuple[str, str, str, bool]]) -> bool:
    try:
        tree = ast.parse(test_path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return False

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported = str(alias.name or "")
                for dotted, _parent, _leaf, is_package in module_refs:
                    if imported == dotted or (is_package and imported.startswith(dotted + ".")):
                        return True
        elif isinstance(node, ast.ImportFrom):
            imported_from = str(node.module or "")
            for dotted, parent, leaf, _is_package in module_refs:
                if imported_from == dotted:
                    return True
                if parent and imported_from == parent and any(alias.name == leaf for alias in node.names):
                    return True
    return False


def select_blast_radius_tests(
    changed_py: list[str],
    repo_root: Path,
    *,
    max_files: int = MAX_BLAST_RADIUS_TEST_FILES,
) -> list[str]:
    module_refs = changed_module_refs(changed_py)
    if not module_refs:
        return []
    tests_dir = Path(repo_root) / "tests"
    if not tests_dir.is_dir():
        return []
    direct_refs = set(module_refs)
    hits: dict[str, tuple[int, int]] = {}
    for test_path in tests_dir.rglob("test_*.py"):
        if test_imports_changed_module(test_path, direct_refs):
            rel = test_path.relative_to(repo_root).as_posix()
            hits[rel] = (0, len(test_path.read_text(encoding="utf-8", errors="replace").splitlines()))
    if not hits:
        dependent_refs = _dependent_module_refs(direct_refs, Path(repo_root))
        if dependent_refs:
            for test_path in tests_dir.rglob("test_*.py"):
                if test_imports_changed_module(test_path, dependent_refs):
                    rel = test_path.relative_to(repo_root).as_posix()
                    hits[rel] = (1, len(test_path.read_text(encoding="utf-8", errors="replace").splitlines()))
    module_names = {leaf for _dotted, _parent, leaf, _is_package in direct_refs}

    def rank(rel: str) -> tuple[int, int, int, str]:
        test_stem = Path(rel).stem
        direct_name_match = any(name and name in test_stem for name in module_names)
        tier, line_count = hits.get(rel, (9, 100_000))
        return (tier, 0 if direct_name_match else 1, line_count, rel)

    return sorted(hits, key=rank)[:max_files]


def select_dependent_smoke_tests(
    changed_py: list[str],
    repo_root: Path,
    *,
    exclude: set[str] | None = None,
    max_files: int = MAX_DEPENDENT_SMOKE_TEST_FILES,
) -> list[str]:
    module_refs = changed_module_refs(changed_py)
    if not module_refs:
        return []
    tests_dir = Path(repo_root) / "tests"
    if not tests_dir.is_dir():
        return []
    direct_refs = set(module_refs)
    dependent_refs = _dependent_module_refs(direct_refs, Path(repo_root))
    if not dependent_refs:
        return []
    excluded = set(exclude or set())
    hits: dict[str, int] = {}
    for test_path in tests_dir.rglob("test_*.py"):
        rel = test_path.relative_to(repo_root).as_posix()
        if rel in excluded:
            continue
        if test_imports_changed_module(test_path, direct_refs):
            continue
        if test_imports_changed_module(test_path, dependent_refs):
            hits[rel] = len(test_path.read_text(encoding="utf-8", errors="replace").splitlines())
    return sorted(hits, key=lambda rel: (hits[rel], rel))[:max_files]


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def changed_candidate_lines(blue_root: Path, candidate_root: Path, rel: str) -> set[int]:
    norm = normalize_relpath(rel)
    candidate_path = Path(candidate_root) / norm
    if not candidate_path.exists():
        return set()
    old_lines = _read_lines(Path(blue_root) / norm)
    new_lines = _read_lines(candidate_path)
    changed: set[int] = set()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag in {"insert", "replace"}:
            changed.update(range(j1 + 1, j2 + 1))
    return changed


def _coverage_env(candidate_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    root = str(candidate_root)
    existing = str(env.get("PYTHONPATH") or "")
    env["PYTHONPATH"] = root if not existing else root + os.pathsep + existing
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run_coverage_probe(candidate_root: Path, tests: list[str], *, timeout_seconds: int) -> tuple[Path | None, str]:
    try:
        import coverage  # noqa: F401
    # Absence (or a broken install) of coverage.py must FAIL CLOSED: the caller
    # turns this string into a blast-radius failure, never a pass.
    except ImportError as exc:
        return None, f"coverage.py unavailable: {exc}"

    temp_dir = Path(tempfile.mkdtemp(prefix="thomas-evolve-coverage-"))
    data_file = temp_dir / ".coverage"
    command = [
        sys.executable,
        "-m",
        "coverage",
        "run",
        "--branch",
        f"--source={','.join(PYTHON_MODULE_ROOTS)}",
        "--data-file",
        str(data_file),
        "-m",
        "pytest",
        *tests,
        "-q",
        "-p",
        "no:cacheprovider",
    ]
    try:
        result = subprocess.run(  # nosec - fixed executable/args; tests are repo-relative paths.
            command,
            cwd=str(candidate_root),
            env=_coverage_env(candidate_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, int(timeout_seconds)),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, "blast-radius coverage probe timed out"
    except OSError as exc:
        return None, f"blast-radius coverage probe failed to start: {exc}"
    if not data_file.exists():
        return None, "blast-radius coverage probe produced no coverage data"
    if result.returncode != 0:
        tail = "\n".join((str(result.stdout or "") + "\n" + str(result.stderr or "")).splitlines()[-12:])
        detail = f": {tail}" if tail else ""
        return None, f"blast-radius tests failed with returncode {result.returncode}{detail}"
    return data_file, ""


def _run_pytest_probe(candidate_root: Path, tests: list[str], *, timeout_seconds: int, label: str) -> str:
    if not tests:
        return ""
    command = [
        sys.executable,
        "-m",
        "pytest",
        *tests,
        "-q",
        "-p",
        "no:cacheprovider",
    ]
    try:
        result = subprocess.run(  # nosec - fixed executable/args; tests are repo-relative paths.
            command,
            cwd=str(candidate_root),
            env=_coverage_env(candidate_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1, int(timeout_seconds)),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return f"{label} timed out"
    except OSError as exc:
        return f"{label} failed to start: {exc}"
    if result.returncode == 0:
        return ""
    tail = "\n".join((str(result.stdout or "") + "\n" + str(result.stderr or "")).splitlines()[-12:])
    detail = f": {tail}" if tail else ""
    return f"{label} failed with returncode {result.returncode}{detail}"


def _executed_statement_lines(candidate_root: Path, data_file: Path, rel: str) -> tuple[set[int], set[int], str]:
    try:
        import coverage
    except ImportError as exc:
        return set(), set(), f"blast-radius coverage analysis failed for {rel}: {exc}"
    try:
        cov = coverage.Coverage(data_file=str(data_file))
        cov.load()
        _filename, statements, _excluded, missing, _missing_text = cov.analysis2(str(Path(candidate_root) / rel))
    # Coverage analysis must FAIL CLOSED with a message, never propagate.
    # CoverageException is the base of coverage.py's own faults (NoSource,
    # NotPython, a corrupt or absent data file); OSError covers reading the
    # source/data files; ValueError/TypeError a malformed path or result tuple.
    except (coverage.CoverageException, OSError, ValueError, TypeError) as exc:
        return set(), set(), f"blast-radius coverage analysis failed for {rel}: {exc}"
    statement_lines = {int(line) for line in statements}
    missing_lines = {int(line) for line in missing}
    return statement_lines, statement_lines - missing_lines, ""


def execution_coverage_failures(
    changed_py: list[str],
    *,
    blue_root: Path,
    candidate_root: Path,
    timeout_seconds: int = 120,
) -> list[str]:
    normalized = [normalize_relpath(rel) for rel in changed_py if normalize_relpath(rel).endswith(".py")]
    if not normalized:
        return []

    tests_by_file = {rel: select_blast_radius_tests([rel], candidate_root) for rel in normalized}
    uncovered_by_tests = sorted(rel for rel, tests in tests_by_file.items() if not tests)
    if uncovered_by_tests:
        return ["no blast-radius tests selected for changed Python files: " + ", ".join(uncovered_by_tests[:8])]

    tests = sorted({test for rows in tests_by_file.values() for test in rows})
    data_file, probe_error = _run_coverage_probe(Path(candidate_root), tests, timeout_seconds=timeout_seconds)
    if probe_error or data_file is None:
        return [probe_error or "blast-radius coverage probe failed"]

    not_executed: list[str] = []
    analysis_errors: list[str] = []
    for rel in normalized:
        changed_lines = changed_candidate_lines(blue_root, candidate_root, rel)
        if not changed_lines:
            not_executed.append(f"{rel} (deleted or no candidate changed lines)")
            continue
        statement_lines, executed_lines, analysis_error = _executed_statement_lines(candidate_root, data_file, rel)
        if analysis_error:
            analysis_errors.append(analysis_error)
            continue
        changed_statements = changed_lines & statement_lines
        if changed_statements and not (changed_statements & executed_lines):
            sample = ",".join(str(line) for line in sorted(changed_statements)[:8])
            not_executed.append(f"{rel} lines {sample}")

    failures = []
    if analysis_errors:
        failures.extend(analysis_errors[:4])
    if not_executed:
        failures.append("no changed executable lines covered for changed Python files: " + "; ".join(not_executed[:8]))
    smoke_tests = sorted(
        {test for rel in normalized for test in select_dependent_smoke_tests([rel], candidate_root, exclude=set(tests))}
    )
    smoke_error = _run_pytest_probe(
        Path(candidate_root),
        smoke_tests,
        timeout_seconds=timeout_seconds,
        label="dependent blast-radius smoke tests",
    )
    if smoke_error:
        failures.append(smoke_error)
    return failures
