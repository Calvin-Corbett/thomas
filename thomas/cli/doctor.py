"""thomas doctor — architecture health check command.

Runs all fitness checks from _architecture.py and reports results.
"""

from __future__ import annotations

import pathlib
import sys

import click

from thomas._architecture import MODULES, RULES, get_all_by_tier

THOMAS_ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO_ROOT = THOMAS_ROOT.parent


def _count_lines(path: pathlib.Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return 0


def _check_forbidden(repo_root: pathlib.Path, thomas_root: pathlib.Path) -> list[str]:
    import fnmatch
    hits = []
    for pattern in RULES["forbidden_patterns"]:
        for match in repo_root.glob(pattern):
            if match.is_file():
                hits.append(match.name)
        for py_file in thomas_root.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
            if fnmatch.fnmatch(py_file.name, pattern):
                hits.append(str(py_file.relative_to(repo_root)))
    return hits


def _check_debt() -> list[str]:
    items = []
    for name, mod in MODULES.items():
        debt = mod.get("debt", "")
        if debt:
            items.append(f"{name}: {debt}")
    return items


def _check_ext_isolation(thomas_root: pathlib.Path) -> list[str]:
    import ast
    ext_modules = set(get_all_by_tier("ext").keys())
    exceptions = {(a, b) for a, b in RULES.get("ext_isolation_exceptions", [])}
    violations = []
    for ext_name in ext_modules:
        ext_dir = thomas_root / ext_name
        if not ext_dir.is_dir():
            continue
        for py_file in ext_dir.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
            try:
                source = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source)
            except (SyntaxError, OSError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("thomas."):
                    imported = node.module.split(".")[1]
                    if imported in ext_modules and imported != ext_name:
                        if (ext_name, imported) in exceptions:
                            continue
                        violations.append(f"{py_file.name} imports {imported}")
    return violations


@click.command("doctor")
def doctor_command() -> None:
    """Run Thomas architecture health checks."""
    from thomas import __version__

    click.echo(f"Thomas Health Report v{__version__}")
    ok_count = 0
    total = 6

    # 1. Forbidden patterns
    forbidden = _check_forbidden(REPO_ROOT, THOMAS_ROOT)
    if forbidden:
        click.echo(f"  Forbidden:     FAIL  {len(forbidden)} files ({', '.join(forbidden[:3])}...)")
    else:
        click.echo("  Forbidden:     ok")
        ok_count += 1

    # 2. Extension isolation
    ext_issues = _check_ext_isolation(THOMAS_ROOT)
    if ext_issues:
        click.echo(f"  Extensions:    FAIL  {len(ext_issues)} violations")
    else:
        click.echo("  Extensions:    ok (fully isolated)")
        ok_count += 1

    # 3. Known debt
    debt_items = _check_debt()
    click.echo(f"  Known debt:    {len(debt_items)} items")
    ok_count += 1  # informational, not a fail

    # 4. Module coverage
    uncovered = []
    for entry in THOMAS_ROOT.iterdir():
        if not entry.is_dir() or entry.name.startswith("_") or entry.name == "__pycache__":
            continue
        if any(entry.rglob("*.py")) and entry.name not in MODULES:
            uncovered.append(entry.name)
    if uncovered:
        click.echo(f"  Coverage:      FAIL  unregistered: {', '.join(uncovered)}")
    else:
        click.echo("  Coverage:      ok (all modules registered)")
        ok_count += 1

    # 5. Test coverage for required dirs
    tests_dir = REPO_ROOT / "tests"
    missing_tests = []
    for req_dir in RULES["test_required_dirs"]:
        parts = req_dir.strip("/").split("/")
        mod_name = parts[1] if len(parts) > 1 else parts[0]
        if not list(tests_dir.glob(f"test_{mod_name}*.py")) and not list(tests_dir.glob(f"test_*{mod_name}*.py")):
            missing_tests.append(mod_name)
    if missing_tests:
        click.echo(f"  Tests:         FAIL  missing for: {', '.join(missing_tests)}")
    else:
        click.echo("  Tests:         ok (required dirs covered)")
        ok_count += 1

    # 6. Fitness tests summary
    try:
        import subprocess
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_architecture.py", "-x", "--tb=no", "-q"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=30,
        )
        if result.returncode == 0:
            # Extract pass count from pytest output
            pass_line = [l for l in result.stdout.splitlines() if "passed" in l]
            summary = pass_line[0].strip() if pass_line else "all passing"
            click.echo(f"  Fitness tests: ok ({summary})")
            ok_count += 1
        else:
            # Extract failure count from pytest output
            click.echo("  Fitness tests: FAIL")
            for line in result.stdout.splitlines():
                if "failed" in line or "error" in line:
                    click.echo(f"                 {line.strip()}")
    except (OSError, RuntimeError, ValueError, AttributeError, TypeError, ImportError, KeyError) as exc:
        click.echo(f"  Fitness tests: ERROR ({exc})")

    # Overall
    if ok_count == total:
        status = "HEALTHY"
        if debt_items:
            status += f" ({len(debt_items)} known debt items)"
        click.echo(f"  Overall:       {status}")
    else:
        click.echo(f"  Overall:       {ok_count}/{total} checks passing")
        sys.exit(1)
