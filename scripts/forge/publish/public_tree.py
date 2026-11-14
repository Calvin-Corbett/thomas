"""The public file list: what a public release leaves out, and what that would break.

``docs/ops/public_exclude.txt`` names files that stay private. A release builds its tree from the development tree
minus that list (and minus the folders ``docs/repo_hygiene_baseline.json`` already strips). Leaving a Python file out
is only safe when nothing that stays imports it, so :func:`files_importing` reads every kept ``.py`` file with ``ast``
and names each one that does.

Nothing here talks to a remote or starts a process of its own: git runs through ``thomas.core.git_process``.
"""

from __future__ import annotations

import ast
import fnmatch
import json
import os
import stat
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from thomas.core.git_process import run_git

EXCLUDE_LIST = "docs/ops/public_exclude.txt"
HYGIENE_BASELINE = "docs/repo_hygiene_baseline.json"
_MAX_SOURCE_BYTES = 2_000_000


@dataclass(frozen=True)
class Rule:
    """One line of the list: a path or pattern, and why it stays private."""

    pattern: str
    reason: str

    def matches(self, path: str) -> bool:
        if self.pattern.endswith("/"):
            return path.startswith(self.pattern)
        if any(ch in self.pattern for ch in "*?["):
            return fnmatch.fnmatchcase(path, self.pattern)
        return path == self.pattern


def parse_exclude_list(text: str) -> list[Rule]:
    """Read the list. A line with no reason, or with nothing before the bar, is refused."""
    rules: list[Rule] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pattern, bar, reason = (part.strip() for part in line.partition("|"))
        if not bar or not pattern or not reason:
            raise ValueError(f"{EXCLUDE_LIST} line {number} needs a path, a bar and a reason: {line!r}")
        rules.append(Rule(pattern.replace("\\", "/"), reason))
    return rules


def load_exclude_list(repo_root: Path) -> list[Rule]:
    return parse_exclude_list((repo_root / EXCLUDE_LIST).read_text(encoding="utf-8"))


def baseline_rules(repo_root: Path, paths: Iterable[str] = ()) -> list[Rule]:
    """What the hygiene baseline already keeps out of a public release.

    That is its private folders, its blocked file endings and, when ``paths`` is given, every file at the root of the
    tree that the baseline does not list as allowed there (the public copy has never carried those).
    """
    path = repo_root / HYGIENE_BASELINE
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    rules = [
        Rule(str(item).replace("\\", "/"), "listed as private in the hygiene baseline")
        for key in ("publish_strip_prefixes", "forbidden_tracked_prefixes")
        for item in data.get(key) or []
        if str(item).strip()
    ]
    rules += [
        Rule(f"*{item}", "a file ending the hygiene baseline blocks")
        for item in data.get("blocked_tracked_suffixes") or []
        if str(item).strip()
    ]
    allowed = {str(item) for item in data.get("allowed_tracked_root_files") or []}
    if allowed:
        rules += [
            Rule(name, "not on the hygiene baseline's list of files allowed at the root")
            for name in sorted(set(paths))
            if "/" not in name and name not in allowed
        ]
    return rules


def public_rules(repo_root: Path, paths: Iterable[str] = ()) -> list[Rule]:
    return load_exclude_list(repo_root) + baseline_rules(repo_root, paths)


def split_paths(paths: Iterable[str], rules: list[Rule]) -> tuple[list[str], dict[str, str]]:
    """Return the paths that stay, and each path that goes with the reason of the first rule that took it."""
    kept: list[str] = []
    removed: dict[str, str] = {}
    for raw in paths:
        path = raw.replace("\\", "/")
        rule = next((r for r in rules if r.matches(path)), None)
        if rule is None:
            kept.append(path)
        else:
            removed[path] = rule.reason
    return sorted(kept), dict(sorted(removed.items()))


def module_name(path: str) -> str | None:
    """``a/b/c.py`` is ``a.b.c`` and ``a/b/__init__.py`` is ``a.b``; anything that is not Python is None."""
    if not path.endswith(".py"):
        return None
    parts = path[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or None


def _names_imported(path: str, source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    package = (module_name(path) or "").split(".")
    if not path.endswith("__init__.py"):
        package = package[:-1]
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                keep = package[: len(package) - node.level + 1] if node.level <= len(package) + 1 else []
                base = ".".join([*keep, base] if base else keep)
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names if base)
        elif isinstance(node, ast.Call) and node.args:
            func = node.func
            label = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            first = node.args[0]
            if label in {"import_module", "__import__"} and isinstance(first, ast.Constant):
                if isinstance(first.value, str):
                    names.add(first.value)
    return names


def files_importing(sources: Mapping[str, str], excluded_modules: Iterable[str]) -> dict[str, list[str]]:
    """Every file in ``sources`` that imports one of ``excluded_modules``, with the modules it imports.

    A file imports a module when it names it, or names something inside it. Relative imports are resolved, an import
    inside a function counts, and so does ``importlib.import_module("a.b")`` with a literal name.
    """
    targets = sorted(set(excluded_modules))
    found: dict[str, list[str]] = {}
    for path, source in sources.items():
        if not path.endswith(".py"):
            continue
        names = _names_imported(path, source)
        hit = sorted({t for t in targets for n in names if n == t or n.startswith(t + ".")})
        if hit:
            found[path] = hit
    return dict(sorted(found.items()))


@dataclass
class TreeReport:
    """What pruning a tree did, and what is still wrong with it."""

    kept: list[str] = field(default_factory=list)
    removed: dict[str, str] = field(default_factory=dict)
    importers: dict[str, list[str]] = field(default_factory=dict)

    def excluded_modules(self) -> list[str]:
        return sorted(name for p in self.removed if (name := module_name(p)))

    @property
    def problems(self) -> list[str]:
        return [
            f"{path} imports {', '.join(mods)}, which a public release leaves out"
            for path, mods in self.importers.items()
        ]


def tracked_files(root: Path) -> list[str]:
    result = run_git(["ls-files", "-z"], cwd=root, timeout=120)
    if not result.ok:
        raise RuntimeError(f"could not list the files in {root}: {result.message()}")
    return [p for p in result.stdout.split("\0") if p]


def read_sources(root: Path, paths: Iterable[str]) -> dict[str, str]:
    sources: dict[str, str] = {}
    for path in paths:
        full = root / path
        if not path.endswith(".py") or not full.is_file():
            continue
        try:
            if full.stat().st_size <= _MAX_SOURCE_BYTES:
                sources[path] = full.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
    return sources


def check_tree(root: Path, removed: Mapping[str, str], paths: Iterable[str] | None = None) -> TreeReport:
    """Report the files of ``root`` that import a Python file that was removed from it."""
    kept = sorted(paths) if paths is not None else tracked_files(root)
    report = TreeReport(kept=kept, removed=dict(removed))
    report.importers = files_importing(read_sources(root, kept), report.excluded_modules())
    return report


def _delete(full: Path) -> None:
    try:
        full.unlink()
    except PermissionError:
        os.chmod(full, stat.S_IWRITE)
        full.unlink()


def prune_tree(root: Path, rules: list[Rule]) -> TreeReport:
    """Delete from the git checkout at ``root`` every file the rules leave out, then check what is left.

    ``root`` must be a git checkout that is a copy made for this release, never the working checkout.
    """
    if not (root / ".git").exists():
        raise ValueError(f"{root} is not a git checkout, so nothing was removed")
    kept, removed = split_paths(tracked_files(root), rules)
    base = root.resolve()
    for path in removed:
        full = (root / path).resolve()
        if base in full.parents and full.is_file():
            _delete(full)
    return check_tree(root, removed, kept)
