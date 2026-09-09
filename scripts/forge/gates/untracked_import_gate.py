#!/usr/bin/env python3
"""Refuse a commit whose staged Python imports a module git does not track.

On 2026-09-07 four modules under ``thomas/`` were found imported by committed
files and never added to git (the session-identity pair behind every board
tool, the delegation tool receipts, the work execution adapter). Every working
tree that held the files passed every hook; a clean clone of ``dev`` failed
with an ImportError on the server and on every board command. Hooks run on the
working tree and cannot see this class; this one asks git instead.

``--staged`` (default): the imports of every staged ``.py`` must resolve to a
tracked or staged module when they resolve to a file in the tree at all.
``--all``: the same over every tracked ``.py``, the scan that found the four.
Imports that resolve to nothing in the tree (stdlib, site-packages) are not
this gate's business.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOTS = ("thomas", "scripts", "evolve_supervisor", "evolve_corpus", "tests")


def _git(repo: Path, *args: str) -> list[str]:
    out = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    if out.returncode != 0:
        return []
    return [line.strip().replace("\\", "/") for line in out.stdout.splitlines() if line.strip()]


def _tracked(repo: Path) -> set[str]:
    return set(_git(repo, "ls-files"))


def _staged(repo: Path) -> set[str]:
    return set(_git(repo, "diff", "--cached", "--name-only", "--diff-filter=ACMR"))


def _untracked_py(repo: Path) -> set[str]:
    return {p for p in _git(repo, "ls-files", "--others", "--exclude-standard") if p.endswith(".py")}


def module_of(path: str) -> str:
    """``thomas/core/x.py`` -> ``thomas.core.x``; a package ``__init__`` names the package."""
    parts = path[:-3].split("/") if path.endswith(".py") else path.split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _imports_of(source: str, importer: str) -> set[str]:
    """Every dotted name the file imports, relative imports resolved against its package."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    package = module_of(importer).rsplit(".", 1)[0] if "/" in importer else ""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")
                anchor = anchor[: max(0, len(anchor) - (node.level - 1))]
                base = ".".join([*anchor, base]) if base else ".".join(anchor)
            if base:
                found.add(base)
                for alias in node.names:
                    found.add(f"{base}.{alias.name}")
        elif isinstance(node, ast.Call):
            func = node.func
            is_import_module = (isinstance(func, ast.Attribute) and func.attr == "import_module") or (
                isinstance(func, ast.Name) and func.id == "import_module"
            )
            if is_import_module and node.args and isinstance(node.args[0], ast.Constant):
                value = node.args[0].value
                if isinstance(value, str):
                    found.add(value)
    return {name for name in found if name.split(".", 1)[0] in PACKAGE_ROOTS}


def _resolve(name: str, untracked_by_module: dict[str, str]) -> str | None:
    """The untracked file a dotted name lands on, walking from the full name to its packages."""
    parts = name.split(".")
    while parts:
        hit = untracked_by_module.get(".".join(parts))
        if hit:
            return hit
        parts.pop()
    return None


def _check(repo: Path, importers: set[str], allowed: set[str]) -> list[tuple[str, str, str]]:
    untracked = _untracked_py(repo) - allowed
    if not untracked:
        return []
    by_module = {module_of(path): path for path in untracked}
    findings: list[tuple[str, str, str]] = []
    for path in sorted(importers):
        if not path.endswith(".py"):
            continue
        try:
            source = (repo / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        seen: set[str] = set()
        for name in sorted(_imports_of(source, path)):
            hit = _resolve(name, by_module)
            if hit and hit not in seen:
                seen.add(hit)
                findings.append((path, module_of(hit), hit))
    return findings


def check_staged(repo: Path = ROOT) -> list[tuple[str, str, str]]:
    """(importer, module, untracked file) for every staged file importing an untracked module."""
    staged = _staged(repo)
    return _check(repo, staged, allowed=staged)


def check_all(repo: Path = ROOT) -> list[tuple[str, str, str]]:
    """The same over every tracked file: what a clean clone would fail on."""
    return _check(repo, _tracked(repo), allowed=set())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=str(ROOT))
    parser.add_argument("--all", action="store_true", help="scan every tracked file, not only the staged ones")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    findings = check_all(repo) if args.all else check_staged(repo)
    if not findings:
        print("untracked-import gate: PASS")
        return 0
    print("untracked-import gate: FAIL - a file imports a module git does not track; a clean clone would fail:")
    for importer, module, path in findings:
        print(f"- {importer} imports {module}, but {path} is untracked (git add it, or drop the import)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
