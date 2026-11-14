"""The fence: a carved plugin's code imports only the kernel, its own code and its declared needs.

Spec: docs/superpowers/specs/2026-10-29-kernel-plugins-fast-checks-design.md section 2. Standard library only.
"""

from __future__ import annotations

import ast
from collections.abc import Collection, Mapping
from functools import lru_cache

from thomas.core.plugin_manifest import KERNEL, PluginManifest, claims

_IN_KERNEL = claims(KERNEL)


def repo_roots(tracked: Collection[str]) -> frozenset[str]:
    """The top-level folders holding tracked Python: every package an import can land in."""
    return frozenset(p.split("/", 1)[0] for p in tracked if p.endswith(".py") and "/" in p)


def _package(path: str) -> list[str]:
    """The dotted package a file's relative imports resolve against (for ``__init__.py``, its own package)."""
    return path[:-3].split("/")[:-1]


@lru_cache(maxsize=16384)  # every plugin's fence and door reads the same files: each is parsed once
def _imports(path: str, source: str, roots: frozenset[str]) -> tuple[tuple[int, str], ...]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source, filename=path)):
        if isinstance(node, ast.Import):
            found.extend((node.lineno, alias.name) for alias in node.names if alias.name.split(".")[0] in roots)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                package = _package(path)
                base = package[: len(package) - (node.level - 1)]
                module = ".".join([*base, *([node.module] if node.module else [])])
            else:
                module = node.module or ""
            if module.split(".")[0] not in roots:
                continue
            found.extend((node.lineno, module if a.name == "*" else f"{module}.{a.name}") for a in node.names)
    return tuple(sorted(found))


def imports(path: str, source: str, roots: Collection[str] = ("thomas",)) -> list[tuple[int, str]]:
    """(line, module) for every import under *roots* in *source*, at any depth, relative imports resolved."""
    return list(_imports(path, source, frozenset(roots)))


def module_path(module: str, tracked: Collection[str]) -> str | None:
    """The tracked file a dotted *module* (or a name inside one) comes from: the longest prefix that is a module."""
    parts = module.split(".")
    for end in range(len(parts), 0, -1):
        stem = "/".join(parts[:end])
        for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
            if candidate in tracked:
                return candidate
    return None


@lru_cache(maxsize=16384)
def _attribute_reach(path: str, source: str, packages: frozenset[str]) -> tuple[tuple[int, str], ...]:
    """(line, module.name) for ``precard.slot`` where *path* bound ``precard`` to one of *packages*: no import shows it."""
    tree = ast.parse(source, filename=path)
    bound: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            bound.update({a.asname: a.name for a in node.names if a.asname and a.name in packages})
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            dotted = {a.asname or a.name: f"{node.module}.{a.name}" for a in node.names}
            bound.update({name: full for name, full in dotted.items() if full in packages})
    return tuple(
        (node.lineno, f"{bound[node.value.id]}.{node.attr}")
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in bound
    )


def _inside(manifest: PluginManifest, target: str) -> bool:
    if _IN_KERNEL(target) or manifest.in_code(target) or manifest.in_needs(target):
        return True
    # A parent package's __init__ runs whenever an allowed module under it is imported: no new reach.
    return target.endswith("/__init__.py") and target[: -len("__init__.py")] in manifest.folders


def violations(manifest: PluginManifest, sources: Mapping[str, str], tracked: Collection[str]) -> list[str]:
    """``"<path>:<line> imports <module>"`` for every import in the plugin's code that leaves the fence."""
    roots = repo_roots(tracked)
    out = []
    for path, source in sorted(sources.items()):
        if not path.endswith(".py") or not manifest.in_code(path):
            continue
        try:
            found = _imports(path, source, roots)
        except SyntaxError:  # a file that does not parse imports nothing, and every test of it says so
            continue
        for line, module in found:
            target = module_path(module, tracked)
            if target is not None and not _inside(manifest, target):
                out.append(f"{path}:{line} imports {module}")
    return out


def reaches(
    manifest: PluginManifest, sources: Mapping[str, str], tracked: Collection[str]
) -> list[tuple[str, int, str, str]]:
    """(path, line, module, target) for everything outside the plugin that lands on a file of its code.

    Tests outside the plugin are not counted: they are its integration tests, and the full check runs them.
    """
    roots = repo_roots(tracked)
    packages = frozenset(p[: -len("/__init__.py")].replace("/", ".") for p in tracked if p.endswith("/__init__.py"))
    out = []
    for path, source in sorted(sources.items()):
        if not path.endswith(".py") or path.startswith("tests/") or manifest.in_code(path) or manifest.in_tests(path):
            continue
        try:
            found = {*_imports(path, source, roots), *_attribute_reach(path, source, packages)}
        except SyntaxError:
            continue
        for line, module in sorted(found):
            target = module_path(module, tracked)
            if target is not None and manifest.in_code(target):
                out.append((path, line, module, target))
    return out


def outsiders(manifest: PluginManifest, sources: Mapping[str, str], tracked: Collection[str]) -> list[str]:
    """``"<path>:<line> reaches <module>"`` for everything outside the plugin that lands behind its door.

    Nothing outside may depend on what the door does not name, so the plugin's tests can stand for it alone. No door,
    no rule.
    """
    if not manifest.door:
        return []
    found = reaches(manifest, sources, tracked)
    return [f"{path}:{line} reaches {module}" for path, line, module, target in found if not manifest.in_door(target)]
