"""A plugin's proof set: the tracked files a slim copy must hold to check a change inside the plugin.

Spec: docs/superpowers/specs/2026-10-29-kernel-plugins-fast-checks-design.md section 3. Standard library only.
``python -m thomas.core.plugin_proof <name>`` prints the set's size for a manifest in the current checkout, and the
seeds (kernel, code, needs, tests, harness) that pull in the most files.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Collection
from dataclasses import replace
from pathlib import Path

from thomas.core.plugin_fence import imports, module_path, repo_roots
from thomas.core.plugin_manifest import KERNEL, PluginManifest, claims, load

_IN_KERNEL = claims(KERNEL)
# What every test run in a proof copy loads, whatever it tests.
HARNESS = (
    "pyproject.toml",
    "thomas/server/rows/default.toml",
    "tests/__init__.py",
    "tests/conftest.py",
    "tests/between_tests.py",
    "tests/real_data_child_audit.py",
    "tests/collect_only_named.py",
    "tests/slim_copy_audit.py",
    "tests/test_plugins_stay_fenced.py",
    "tests/test_architecture.py",  # not run in a proof copy, but test selection names it every time
    "scripts/fast_tests_plugin.py",
    "thomas/core/plugin_manifest.py",
    "thomas/core/plugin_fence.py",
    "thomas/core/plugin_proof.py",
)


def seeds(manifest: PluginManifest, tracked: Collection[str]) -> list[str]:
    """The tracked files a plugin's proof starts from: kernel, code, needs, tests, the harness and the manifest."""
    wanted = (_IN_KERNEL, manifest.in_code, manifest.in_needs, manifest.in_tests)
    found = sorted(p for p in tracked if any(claimed(p) for claimed in wanted))
    return found + [p for p in (*HARNESS, manifest.source) if p in tracked and p not in found]


def _parents(path: str, tracked: Collection[str]) -> list[str]:
    parts = path.split("/")[:-1]
    inits = [f"{'/'.join(parts[:i])}/__init__.py" for i in range(1, len(parts) + 1)]
    return [p for p in inits if p in tracked]


# A quoted dotted name loads its module at runtime too: importlib.import_module("thomas.x"), patch("thomas.x.y"),
# monkeypatch.setattr("thomas.x.y", ...). tests/conftest.py imports six modules that way to move their home folders.
# Only a file that calls one of these can load a module by name; elsewhere a dotted string is text (a logger name,
# "thomas.toml", or checker_run.py's BOOT_IMPORTS, which boots a different tree in a child process).
_BY_NAME = re.compile(r"\b(?:import_module|__import__|importorskip|find_spec|resolve_name|run_module|patch|setattr)\b")


def _dotted_name(roots: Collection[str]) -> re.Pattern[str]:
    return re.compile(rf"(?:{'|'.join(map(re.escape, sorted(roots)))})(?:\.[A-Za-z_]\w*)+")


def _is_sys_modules(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "modules" and getattr(node.value, "id", "") == "sys"


def _dotted(path: str, source: str, name: re.Pattern[str]) -> list[str]:
    """Strings that are a whole dotted repo module name: each one after ``"-m"`` in a command (it runs from this copy),
    and, in a file that loads modules by name, every other one except where it only asks ``sys.modules`` whether a
    module is already loaded (``sys.modules.get("thomas.x")``, ``sys.modules["thomas.x"]``, ``"thomas.x" in
    sys.modules``)."""
    by_name = _BY_NAME.search(source) is not None
    if not by_name and '"-m"' not in source and "'-m'" not in source:
        return []  # most files: no second parse
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []
    asks, launched = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _is_sys_modules(getattr(node.func, "value", None)):
            asks.update(id(arg) for arg in node.args)
        elif isinstance(node, ast.Subscript) and _is_sys_modules(node.value):
            asks.add(id(node.slice))
        elif isinstance(node, ast.Compare) and any(_is_sys_modules(c) for c in node.comparators):
            asks.add(id(node.left))
        elif isinstance(node, (ast.List, ast.Tuple)):
            launched.update(id(b) for a, b in zip(node.elts, node.elts[1:]) if getattr(a, "value", None) == "-m")
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and (id(node) in launched or (by_name and id(node) not in asks))
        and name.fullmatch(node.value)
    ]


class ImportGraph:
    """What each tracked file pulls in, read once however many plugins ask."""

    def __init__(self, tracked: Collection[str], read: Callable[[str], str]) -> None:
        self.tracked, self.read = tracked, read
        self.roots = repo_roots(tracked)
        self.name = _dotted_name(self.roots)
        self.known: dict[str, tuple[str, ...]] = {}

    def targets(self, path: str) -> tuple[str, ...]:
        found = self.known.get(path)
        if found is None:
            more = _parents(path, self.tracked)
            if path.endswith(".py"):
                source = self.read(path)
                try:
                    modules = [m for _, m in imports(path, source, self.roots)]
                except SyntaxError:
                    modules = []
                modules += _dotted(path, source, self.name)
                more += [t for m in modules if (t := module_path(m, self.tracked)) is not None]
            found = self.known[path] = tuple(dict.fromkeys(more))
        return found


def _closure(
    start: list[str], tracked: Collection[str], read: Callable[[str], str], graph: ImportGraph | None = None
) -> dict[str, str]:
    """Each reached file, mapped to the seed that first pulled it in."""
    graph = graph or ImportGraph(tracked, read)
    reached = {s: s for s in start}
    queue = list(start)
    while queue:
        path = queue.pop()
        for target in graph.targets(path):
            if target not in reached:
                reached[target] = reached[path]
                queue.append(target)
    return reached


def proof_set(manifest: PluginManifest, tracked: Collection[str], read: Callable[[str], str]) -> list[str]:
    """The seeds, every package ``__init__`` above them, and every tracked Thomas module they import at any depth."""
    return sorted(_closure(seeds(manifest, tracked), tracked, read))


def strays(
    manifest: PluginManifest,
    tracked: Collection[str],
    read: Callable[[str], str],
    graph: ImportGraph | None = None,
) -> dict[str, str]:
    """Files outside ``tests/`` and ``scripts/`` that only the plugin's tests pull into its proof set, each mapped to
    the test that pulls it in. A plugin test may lean on test helpers and scripts; one that drags in Thomas its code
    never reaches (tests/test_a_change_is_checked_before_your_card.py's fixtures reach 1,050 files) is an integration
    test, and its place is the full check. *graph* lets many plugins share one reading of the repo."""
    graph = graph or ImportGraph(tracked, read)
    base = _closure(seeds(replace(manifest, tests=()), tracked), tracked, read, graph)
    full = _closure(seeds(manifest, tracked), tracked, read, graph)
    return {p: seed for p, seed in sorted(full.items()) if p not in base and not p.startswith(("tests/", "scripts/"))}


def main(argv: list[str]) -> int:
    root = Path.cwd()
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True, timeout=120).stdout
    tracked = {p.decode("utf-8") for p in out.split(b"\0") if p}
    manifest = next((m for m in load(root) if m.name == (argv[0] if argv else "")), None)
    if manifest is None:
        print("usage: python -m thomas.core.plugin_proof <plugin name>")
        return 2
    reached = _closure(seeds(manifest, tracked), tracked, lambda rel: (root / rel).read_text("utf-8", "replace"))
    print(f"{manifest.name}: {len(reached)} of {len(tracked)} tracked files")
    for seed, count in Counter(reached.values()).most_common(10):
        print(f"  {count:5d}  {seed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
