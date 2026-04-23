"""Architecture fitness tests — enforce thomas/_architecture.py via compute.

Every test prints a self-healing fix message on failure so agents auto-correct.
Zero token cost. Runs in pre-commit hooks and CI.
"""

from __future__ import annotations

import ast
import pathlib
import re
from collections import defaultdict

import pytest

# Import the architecture definition
from thomas._architecture import MODULES, RULES, get_all_by_tier, resolve_module

THOMAS_ROOT = pathlib.Path(__file__).resolve().parent.parent / "thomas"
REPO_ROOT = THOMAS_ROOT.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_py_files(directory: pathlib.Path) -> list[pathlib.Path]:
    """Collect all .py files under a directory, excluding __pycache__."""
    return [p for p in directory.rglob("*.py") if "__pycache__" not in str(p)]


def _matches_forbidden_pattern(filepath: pathlib.Path) -> bool:
    """Check if a file matches any forbidden pattern (skip these in dep checks)."""
    import fnmatch

    name = filepath.name
    for pattern in RULES["forbidden_patterns"]:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def _matches_legacy_pattern(filepath: pathlib.Path) -> bool:
    """Check if a file matches any legacy pattern (grandfathered, exempt from size limits)."""
    import fnmatch

    name = filepath.name
    for pattern in RULES.get("legacy_patterns", []):
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def _parse_thomas_imports(filepath: pathlib.Path) -> list[str]:
    """Parse a .py file and return all thomas.X module names it imports from."""
    try:
        source = filepath.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("thomas."):
                parts = node.module.split(".")
                if len(parts) >= 2:
                    imported_modules.add(parts[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("thomas."):
                    parts = alias.name.split(".")
                    if len(parts) >= 2:
                        imported_modules.add(parts[1])
    return sorted(imported_modules)


def _known_debt_files() -> set[str]:
    """Collect files mentioned in debt annotations (they're exempt from size limits)."""
    debt_files = set()
    for name, mod in MODULES.items():
        debt_note = mod.get("debt", "")
        # Extract paths like "app.py", "routes/mission.py", "v2/fabric.py"
        for match in re.findall(r"([\w\-/]+\.py)", debt_note):
            debt_files.add(f"thomas/{name}/{match}")
    return debt_files


# ---------------------------------------------------------------------------
# Test 1: Dependency direction
# ---------------------------------------------------------------------------


def test_dependency_direction():
    """No module imports outside its declared depends_on list."""
    violations = []
    for py_file in _collect_py_files(THOMAS_ROOT):
        # Skip files matching forbidden patterns (caught by test_forbidden_patterns)
        if _matches_forbidden_pattern(py_file):
            continue

        source_module = resolve_module(str(py_file))
        if source_module is None or source_module not in MODULES:
            continue

        allowed = set(MODULES[source_module]["depends_on"])
        allowed.add(source_module)  # modules can import from themselves
        # _architecture is always allowed
        allowed.add("_architecture")

        for imported in _parse_thomas_imports(py_file):
            if imported.startswith("_"):
                continue  # skip private/internal
            if imported not in MODULES:
                continue  # skip non-module imports
            if imported not in allowed:
                rel = py_file.relative_to(REPO_ROOT)
                deps = MODULES[source_module]["depends_on"]
                violations.append(
                    f"  {rel} imports thomas.{imported}\n"
                    f"  FIX: {source_module}'s allowed deps are: {deps}. "
                    f"Move shared logic to a common dependency or update "
                    f"_architecture.py if this dependency is intentional."
                )

    if violations:
        msg = "Dependency direction violations:\n" + "\n".join(violations)
        pytest.fail(msg)


# ---------------------------------------------------------------------------
# Test 2: Extension isolation
# ---------------------------------------------------------------------------


def test_extension_isolation():
    """Extension-tier modules cannot import from other extension-tier modules."""
    if not RULES.get("extension_isolation"):
        pytest.skip("extension_isolation rule is disabled")

    ext_modules = set(get_all_by_tier("ext").keys())
    exceptions = {(a, b) for a, b in RULES.get("ext_isolation_exceptions", [])}
    violations = []

    for ext_name in ext_modules:
        ext_dir = THOMAS_ROOT / ext_name
        if not ext_dir.is_dir():
            continue
        for py_file in _collect_py_files(ext_dir):
            if _matches_forbidden_pattern(py_file):
                continue
            for imported in _parse_thomas_imports(py_file):
                if imported in ext_modules and imported != ext_name:
                    if (ext_name, imported) in exceptions:
                        continue  # known tech debt
                    rel = py_file.relative_to(REPO_ROOT)
                    violations.append(
                        f"  {rel} imports thomas.{imported}\n"
                        f"  FIX: Extensions are isolated from each other. "
                        f"Extract shared code to thomas/core/ and import from there."
                    )

    if violations:
        msg = "Extension isolation violations:\n" + "\n".join(violations)
        pytest.fail(msg)


# ---------------------------------------------------------------------------
# Test 3: File sizes
# ---------------------------------------------------------------------------


def test_file_sizes():
    """Files must not exceed hard limits. Debt annotations get 1.5x multiplier
    (1200 lines) but NOT unlimited. MONOLITH_CEILING is absolute.
    """
    from thomas._architecture import MONOLITH_CEILING

    hard_limit = RULES["max_file_lines_hard"]
    debt_ceiling = int(hard_limit * 1.5)  # 1200 lines for debt-annotated files
    debt_files = _known_debt_files()
    violations = []

    for py_file in _collect_py_files(THOMAS_ROOT):
        if _matches_forbidden_pattern(py_file):
            continue  # caught by test_forbidden_patterns
        if _matches_legacy_pattern(py_file):
            continue  # legacy files are grandfathered

        try:
            line_count = len(py_file.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue

        rel = str(py_file.relative_to(REPO_ROOT)).replace("\\", "/")
        is_debt_file = rel in debt_files

        # Determine which limit applies
        if is_debt_file:
            applicable_limit = debt_ceiling
        else:
            applicable_limit = hard_limit

        # Check against applicable limit and MONOLITH_CEILING (absolute max)
        if line_count > applicable_limit or line_count > MONOLITH_CEILING:
            effective_limit = min(applicable_limit, MONOLITH_CEILING)
            if is_debt_file:
                msg = (
                    f"  MONOLITH ALERT: {rel} has {line_count} lines (limit: {effective_limit}). "
                    f"Debt annotation does NOT exempt from hard ceiling. Split this file.\n"
                    f"  FIX: Break into smaller modules. Even documented debt cannot exceed {MONOLITH_CEILING} lines."
                )
            else:
                msg = (
                    f"  {rel} is {line_count} lines (limit: {effective_limit})\n"
                    f"  FIX: Split into smaller files. Max for new files is {hard_limit} lines.\n"
                    f"  If this is intentional tech debt, add a debt annotation in _architecture.py."
                )
            violations.append(msg)

    if violations:
        msg = "File size violations:\n" + "\n".join(violations)
        pytest.fail(msg)


# ---------------------------------------------------------------------------
# Test 3b: Debt trending (monitor file growth)
# ---------------------------------------------------------------------------


def test_debt_trending():
    """For each debt-annotated file, verify it hasn't grown beyond its documented size.

    Warns (not fails) if documented debt files have grown. Fails if NEW files
    (not in debt annotations) exceed 500 lines.
    """
    soft_limit = RULES["max_new_file_lines"]  # 500 lines
    debt_files_dict = {}  # { "thomas/module/file.py": "documented size info" }

    # Build map of debt-annotated files and their documented sizes
    for name, mod in MODULES.items():
        debt = mod.get("debt", "")
        if not debt:
            continue
        # Extract file references and their documented sizes (e.g. "exceeds 1000 lines")
        for match in re.finditer(r"([\w\-/]+\.py)\s+exceeds?\s+(\d+)\s+lines", debt):
            filename = match.group(1)
            documented_size = int(match.group(2))
            full_path = THOMAS_ROOT / name / filename
            debt_files_dict[str(full_path.relative_to(REPO_ROOT)).replace("\\", "/")] = documented_size

    warnings = []
    failures = []

    for py_file in _collect_py_files(THOMAS_ROOT):
        if _matches_forbidden_pattern(py_file):
            continue
        if _matches_legacy_pattern(py_file):
            continue

        try:
            line_count = len(py_file.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue

        rel = str(py_file.relative_to(REPO_ROOT)).replace("\\", "/")

        # Check if this is a debt-annotated file
        if rel in debt_files_dict:
            documented_size = debt_files_dict[rel]
            # If file has grown beyond documented size, warn
            if line_count > documented_size:
                warnings.append(
                    f"  {rel} has grown to {line_count} lines "
                    f"(documented as exceeding {documented_size} lines)\n"
                    f"  WARN: File is growing. Consider splitting or updating debt annotation."
                )
        else:
            # This is a NEW file (not in debt annotations)
            # It should not exceed soft limit
            if line_count > soft_limit:
                failures.append(
                    f"  {rel} is {line_count} lines (limit for new files: {soft_limit})\n"
                    f"  FIX: Add debt annotation in _architecture.py or split the file."
                )

    # Print warnings (informational, do not fail)
    if warnings:
        print("\nDEBT TRENDING WARNINGS:")
        for w in warnings:
            print(w)

    # Fail on new files exceeding soft limit
    if failures:
        msg = "New files exceeding soft limit:\n" + "\n".join(failures)
        pytest.fail(msg)


# ---------------------------------------------------------------------------
# Test 3c: Monolith alert (informational summary)
# ---------------------------------------------------------------------------


def test_monolith_alert():
    """Print a clear summary of all large files (800+ lines) grouped by module.

    This is purely informational — provides agents a quick view of what needs splitting.
    Does not fail the test.
    """
    large_files = defaultdict(list)  # { "module": [(filename, line_count), ...] }

    for py_file in _collect_py_files(THOMAS_ROOT):
        if _matches_forbidden_pattern(py_file):
            continue
        if _matches_legacy_pattern(py_file):
            continue

        try:
            line_count = len(py_file.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue

        # Only report files over 800 lines
        if line_count >= 800:
            rel = str(py_file.relative_to(REPO_ROOT)).replace("\\", "/")
            module = resolve_module(rel)
            if module:
                filename = py_file.name
                large_files[module].append((filename, line_count))

    # Sort and print
    if large_files:
        print("\n" + "=" * 70)
        print("MONOLITH ALERT: Files exceeding 800 lines (grouped by module)")
        print("=" * 70)
        for module in sorted(large_files.keys()):
            files = sorted(large_files[module], key=lambda x: -x[1])  # sort by size, descending
            print(f"\n{module}/")
            for filename, line_count in files:
                print(f"  {filename:40s} {line_count:6d} lines")
        print("\n" + "=" * 70)
        print("Consider breaking these into smaller, focused modules.")
        print("=" * 70 + "\n")


# ---------------------------------------------------------------------------
# Test 4: Forbidden patterns
# ---------------------------------------------------------------------------


def test_forbidden_patterns():
    """No files matching forbidden patterns in thomas/ or repo root."""
    import fnmatch

    violations = []

    for pattern in RULES["forbidden_patterns"]:
        # Check repo root (non-recursive)
        for match in REPO_ROOT.glob(pattern):
            if match.is_file():
                violations.append(
                    f"  {match.name} matches forbidden pattern '{pattern}'\n"
                    f"  FIX: Remove debug/temp files before committing."
                )
        # Check thomas/ (recursive)
        for py_file in _collect_py_files(THOMAS_ROOT):
            if fnmatch.fnmatch(py_file.name, pattern):
                rel = py_file.relative_to(REPO_ROOT)
                violations.append(
                    f"  {rel} matches forbidden pattern '{pattern}'\n"
                    f"  FIX: Remove debug/temp files before committing."
                )

    if violations:
        msg = "Forbidden file pattern violations:\n" + "\n".join(violations)
        pytest.fail(msg)


# ---------------------------------------------------------------------------
# Test 4b: No NEW legacy-pattern files
# ---------------------------------------------------------------------------


def test_no_new_legacy_files():
    """No NEW files matching legacy patterns (existing ones are grandfathered)."""
    import fnmatch
    import subprocess

    legacy_patterns = RULES.get("legacy_patterns", [])
    if not legacy_patterns:
        pytest.skip("No legacy patterns defined")

    # Get list of files tracked by git (these are grandfathered)
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=10,
        )
        tracked = set(result.stdout.strip().splitlines())
    except Exception:
        pytest.skip("git not available")

    violations = []
    for pattern in legacy_patterns:
        for py_file in _collect_py_files(THOMAS_ROOT):
            if fnmatch.fnmatch(py_file.name, pattern):
                rel = str(py_file.relative_to(REPO_ROOT)).replace("\\", "/")
                if rel not in tracked:
                    violations.append(
                        f"  {rel} is a NEW file matching legacy pattern '{pattern}'\n"
                        f"  FIX: Don't create new numbered stubs. Use 'thomas scaffold' instead."
                    )

    if violations:
        msg = "New legacy-pattern files (not allowed):\n" + "\n".join(violations)
        pytest.fail(msg)


# ---------------------------------------------------------------------------
# Test 5: Module coverage
# ---------------------------------------------------------------------------


def test_module_coverage():
    """Every thomas/ subdirectory with .py files should be in MODULES."""
    violations = []
    skip = {"__pycache__"}

    for entry in THOMAS_ROOT.iterdir():
        if not entry.is_dir():
            continue
        if entry.name in skip or entry.name.startswith("_"):
            continue
        # Check if it has any .py files
        if not any(entry.rglob("*.py")):
            continue
        if entry.name not in MODULES:
            violations.append(
                f"  thomas/{entry.name}/ exists but is not in _architecture.py MODULES\n"
                f"  FIX: Add '{entry.name}' to MODULES in thomas/_architecture.py\n"
                f"  with tier, depends_on, health, and description."
            )

    if violations:
        msg = "Unregistered module directories:\n" + "\n".join(violations)
        pytest.fail(msg)


# ---------------------------------------------------------------------------
# Test 6: Test coverage for required dirs
# ---------------------------------------------------------------------------


def test_required_test_coverage():
    """Every directory listed in test_required_dirs has corresponding test files."""
    tests_dir = REPO_ROOT / "tests"
    violations = []

    for req_dir in RULES["test_required_dirs"]:
        # e.g. "thomas/server/routes/" -> look for test files matching "test_server_*" or "test_*routes*"
        parts = req_dir.strip("/").split("/")
        module_name = parts[1] if len(parts) > 1 else parts[0]

        # Check if any test file references this module
        matching_tests = list(tests_dir.glob(f"test_{module_name}*.py"))
        if not matching_tests:
            matching_tests = list(tests_dir.glob(f"test_*{module_name}*.py"))

        if not matching_tests:
            violations.append(
                f"  {req_dir} has no matching test files in tests/\n"
                f"  FIX: Create tests/test_{module_name}.py (or similar)."
            )

    if violations:
        msg = "Missing required test coverage:\n" + "\n".join(violations)
        pytest.fail(msg)


# ---------------------------------------------------------------------------
# Test 7: Health annotations accuracy
# ---------------------------------------------------------------------------


def test_health_annotations():
    """Debt annotations should reference real issues (files that actually exist
    and actually exceed limits)."""
    violations = []
    soft_limit = RULES["max_new_file_lines"]

    for name, mod in MODULES.items():
        debt = mod.get("debt", "")
        if not debt:
            continue

        # Extract referenced .py files (including nested paths like routes/mission.py)
        referenced_files = re.findall(r"([\w\-/]+\.py)", debt)
        for filename in referenced_files:
            full_path = THOMAS_ROOT / name / filename
            if not full_path.exists():
                violations.append(
                    f"  Module '{name}' debt references {filename} but it doesn't exist\n"
                    f"  FIX: Update or remove the debt annotation in _architecture.py."
                )
                continue

            # If debt mentions "exceeds" or "over", verify the file is actually large
            if "exceed" in debt.lower() or "over" in debt.lower():
                try:
                    lines = len(full_path.read_text(encoding="utf-8", errors="replace").splitlines())
                except OSError:
                    continue
                if lines <= soft_limit:
                    violations.append(
                        f"  Module '{name}' debt says {filename} is oversized "
                        f"but it's only {lines} lines\n"
                        f"  FIX: Remove the debt annotation — the issue is resolved."
                    )

    if violations:
        msg = "Stale health annotations:\n" + "\n".join(violations)
        pytest.fail(msg)


# ---------------------------------------------------------------------------
# Test 8: depends_on entries reference valid modules
# ---------------------------------------------------------------------------


def test_depends_on_valid():
    """Every depends_on entry must reference a module that exists in MODULES."""
    violations = []
    for name, mod in MODULES.items():
        for dep in mod["depends_on"]:
            if dep not in MODULES:
                violations.append(
                    f"  Module '{name}' depends on '{dep}' which is not in MODULES\n"
                    f"  FIX: Add '{dep}' to MODULES in _architecture.py, or remove it from "
                    f"'{name}' depends_on."
                )

    if violations:
        msg = "Invalid depends_on references:\n" + "\n".join(violations)
        pytest.fail(msg)


# ---------------------------------------------------------------------------
# Test 9: No circular dependencies
# ---------------------------------------------------------------------------


def test_no_circular_deps():
    """The declared dependency graph must have no NEW circular dependencies.

    Known cycles (documented as tech debt in _architecture.py) are skipped.
    Only NEW cycles cause a failure.
    """
    known_cycles = {frozenset(pair) for pair in RULES.get("known_cycles", [])}

    # Build adjacency list, excluding known cycle edges
    graph: dict[str, list[str]] = {}
    for name, mod in MODULES.items():
        deps = []
        for d in mod["depends_on"]:
            if d not in MODULES:
                continue
            if frozenset((name, d)) in known_cycles:
                continue  # skip known cycle edge
            deps.append(d)
        graph[name] = deps

    # DFS cycle detection
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {name: WHITE for name in graph}
    path: list[str] = []
    cycles: list[str] = []

    def dfs(node: str) -> None:
        color[node] = GRAY
        path.append(node)
        for neighbor in graph.get(node, []):
            if color[neighbor] == GRAY:
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:] + [neighbor]
                cycles.append(" → ".join(cycle))
            elif color[neighbor] == WHITE:
                dfs(neighbor)
        path.pop()
        color[node] = BLACK

    for node in graph:
        if color[node] == WHITE:
            dfs(node)

    if cycles:
        msg = "NEW circular dependency detected:\n"
        for cycle in cycles:
            msg += f"  {cycle}\n"
        msg += "  FIX: Break the cycle by moving shared code to a lower-level module.\n"
        msg += "  If this is intentional, add it to known_cycles in _architecture.py RULES."
        pytest.fail(msg)


# ---------------------------------------------------------------------------
# Test 10: Frontend file sizes
# ---------------------------------------------------------------------------


def _matches_frontend_legacy_pattern(filepath: pathlib.Path) -> bool:
    """Check if a file matches a frontend legacy pattern (JS app_parts exempted)."""
    import fnmatch

    for pattern in RULES.get("frontend_legacy_exempt", []):
        if fnmatch.fnmatch(str(filepath), pattern):
            return True
    return False


def test_frontend_file_sizes():
    """Frontend files (JS, CSS, HTML) must not exceed per-type limits.

    JS: max 800 lines (soft), 2000 (hard ceiling)
    CSS: max 600 lines (soft), 1200 (hard ceiling)
    HTML: max 2000 lines (soft), 3000 (hard ceiling)

    Legacy JS files in app_parts/part-*.js are exempt (documented migration debt).
    """
    web_root = THOMAS_ROOT / "server" / "web"
    if not web_root.exists():
        pytest.skip("Web directory not found")

    # Get limits from architecture rules
    limits = RULES.get(
        "frontend_limits",
        {
            "js": {"soft": 800, "hard": 2000},
            "css": {"soft": 600, "hard": 1200},
            "html": {"soft": 2000, "hard": 3000},
        },
    )

    violations = []
    warnings = []

    # Scan .js files in thomas/server/web/js/ and thomas/server/web/static/
    for js_file in web_root.rglob("*.js"):
        # Skip node_modules, dist, build, etc.
        if any(part in str(js_file) for part in ["node_modules", ".git", "__pycache__", "dist", "build"]):
            continue

        # Skip legacy exempted files (app_parts/part-*.js)
        if _matches_frontend_legacy_pattern(js_file):
            continue

        try:
            line_count = len(js_file.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue

        js_limits = limits["js"]
        soft = js_limits["soft"]
        hard = js_limits["hard"]
        rel = str(js_file.relative_to(REPO_ROOT)).replace("\\", "/")

        if line_count > hard:
            violations.append(f"  {rel}: {line_count} lines (limit: {soft}, ceiling: {hard})")
        elif line_count > soft:
            warnings.append(f"  {rel}: {line_count} lines (limit: {soft}, ceiling: {hard})")

    # Scan .css files in thomas/server/web/css/ and thomas/server/web/static/
    for css_file in web_root.rglob("*.css"):
        if any(part in str(css_file) for part in ["node_modules", ".git", "__pycache__", "dist", "build"]):
            continue

        try:
            line_count = len(css_file.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue

        css_limits = limits["css"]
        soft = css_limits["soft"]
        hard = css_limits["hard"]
        rel = str(css_file.relative_to(REPO_ROOT)).replace("\\", "/")

        if line_count > hard:
            violations.append(f"  {rel}: {line_count} lines (limit: {soft}, ceiling: {hard})")
        elif line_count > soft:
            warnings.append(f"  {rel}: {line_count} lines (limit: {soft}, ceiling: {hard})")

    # Scan .html files in thomas/server/web/
    for html_file in web_root.glob("*.html"):
        try:
            line_count = len(html_file.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue

        html_limits = limits["html"]
        soft = html_limits["soft"]
        hard = html_limits["hard"]
        rel = str(html_file.relative_to(REPO_ROOT)).replace("\\", "/")

        if line_count > hard:
            violations.append(f"  {rel}: {line_count} lines (limit: {soft}, ceiling: {hard})")
        elif line_count > soft:
            warnings.append(f"  {rel}: {line_count} lines (limit: {soft}, ceiling: {hard})")

    # Print warnings (informational, do not fail)
    if warnings:
        print("\nFRONTEND FILE SIZE WARNINGS (under ceiling, exceeds soft limit):")
        for w in warnings:
            print(w)

    # Fail on violations (exceeding hard ceiling)
    if violations:
        msg = "FRONTEND FILE SIZE VIOLATIONS (hard ceiling exceeded):\n" + "\n".join(violations)
        msg += "\nFIX: Split oversized files into smaller modules.\n"
        msg += "For JS: Consider extracting into thomas/server/web/js/modules/\n"
        msg += "For CSS: Consider extracting into component-specific CSS files\n"
        msg += "For HTML: Split standalone apps into separate files or use templating"
        pytest.fail(msg)
