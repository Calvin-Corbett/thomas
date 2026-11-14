"""Plugin manifests: which plugin owns a path, and which changes can be checked as one plugin alone.

Spec: docs/superpowers/specs/2026-10-29-kernel-plugins-fast-checks-design.md. A plugin is ``plugins/<name>.toml`` at
the repo root, claiming paths by glob (``**`` spans folders, ``*`` and ``?`` stay inside one). Standard library only:
this sits beside the kernel at the bottom of the tree.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cached_property, lru_cache
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 uses the declared tomli dependency.
    import tomli as tomllib

MANIFEST_DIR = "plugins"
KERNEL = ("thomas/core/kernel/**",)
# A change touching any of these is never scoped: it can change what every plugin's proof means.
UNSCOPED = (
    *KERNEL,
    "plugins/**",
    "thomas/server/rows/default.toml",
    "thomas/core/plugin_manifest.py",
    "thomas/core/plugin_fence.py",
    "thomas/core/plugin_proof.py",
    "tests/conftest.py",
    "tests/real_data_child_audit.py",
    "tests/collect_only_named.py",
    "tests/slim_copy_audit.py",
    "tests/test_plugins_stay_fenced.py",
    "scripts/fast_tests_plugin.py",
    "pyproject.toml",
)
# Nearly every hand-in carries one, and no test reads the real ones: the release checks them as it folds them in.
NOTES = ("changelog.d/*.md",)
_LISTS = ("code", "tests", "needs", "provides", "uses", "door")


class ManifestError(ValueError):
    """A manifest that cannot be read, or two manifests that claim one path."""


@dataclass(frozen=True)
class PluginManifest:
    name: str
    code: tuple[str, ...]
    tests: tuple[str, ...]
    needs: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()
    uses: tuple[str, ...] = ()
    door: tuple[str, ...] = ()  # the only modules of its code that code outside the plugin may touch
    source: str = ""

    @cached_property
    def in_code(self) -> Callable[[str], bool]:
        return claims(self.code)

    @cached_property
    def in_tests(self) -> Callable[[str], bool]:
        return claims(self.tests)

    @cached_property
    def in_needs(self) -> Callable[[str], bool]:
        return claims(self.needs)

    @cached_property
    def in_door(self) -> Callable[[str], bool]:
        return claims(self.door)

    @cached_property
    def folders(self) -> frozenset[str]:
        """Every folder (ending in /) above what this plugin may import: its code, its needs and the kernel."""
        patterns = (*KERNEL, *self.code, *self.needs)
        return frozenset("/".join(p.split("/")[:n]) + "/" for p in patterns for n in range(1, p.count("/") + 1))


@lru_cache(maxsize=4096)
def _regex(pattern: str) -> re.Pattern[str]:
    parts = pattern.split("/")
    out = []
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if part == "**":
            out.append(".*" if last else "(?:[^/]+/)*")
            continue
        seg = "".join("[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c) for c in part)
        out.append(seg if last else seg + "/")
    return re.compile("".join(out) + r"\Z")


def matches(pattern: str, path: str) -> bool:
    """*path* (repo-relative, forward slashes) matches the glob *pattern*."""
    return bool(_regex(pattern).match(path.replace("\\", "/")))


@lru_cache(maxsize=4096)
def claims(patterns: tuple[str, ...]) -> Callable[[str], bool]:
    """A test for whether a path matches any of *patterns*. Manifests hold exact paths by the hundred, so those are a
    set lookup, and only the globs are a regular expression."""
    exact = frozenset(p for p in patterns if "*" not in p and "?" not in p)
    globs = [_regex(p).pattern for p in patterns if p not in exact]
    joined = re.compile("|".join(f"(?:{g})" for g in globs)) if globs else None

    def claimed(path: str) -> bool:
        posix = path.replace("\\", "/")
        return posix in exact or (joined is not None and joined.match(posix) is not None)

    return claimed


def _any(patterns: Sequence[str], path: str) -> bool:
    return claims(tuple(patterns))(path)


def load(root: Path) -> tuple[PluginManifest, ...]:
    """Every manifest under ``<root>/plugins``, sorted by name. A missing folder is no plugins."""
    folder = Path(root) / MANIFEST_DIR
    manifests = []
    for file in sorted(folder.glob("*.toml")) if folder.is_dir() else ():
        rel = f"{MANIFEST_DIR}/{file.name}"
        try:
            data = tomllib.loads(file.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ManifestError(f"{rel} cannot be read: {exc}") from exc
        if data.get("name") != file.stem:
            raise ManifestError(f"{rel}: name {data.get('name')!r} is not its file name {file.stem!r}")
        lists = {}
        for key in _LISTS:
            value = data.get(key, [])
            if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
                raise ManifestError(f"{rel}: {key} must be a list of path globs")
            lists[key] = tuple(value)
        if not lists["code"]:
            raise ManifestError(f"{rel}: code must claim at least one path")
        manifests.append(PluginManifest(name=file.stem, source=rel, **lists))
    return tuple(manifests)


def owner(manifests: Sequence[PluginManifest], path: str) -> PluginManifest | None:
    """The plugin whose code or tests claim *path*, None when no plugin does."""
    found = [m for m in manifests if m.in_code(path) or m.in_tests(path)]
    if len(found) > 1:
        raise ManifestError(f"{path} is claimed by {' and '.join(m.name for m in found)}")
    return found[0] if found else None


def scope(manifests: Sequence[PluginManifest], changed: Sequence[str]) -> PluginManifest | None:
    """The one plugin a change can be checked as, or None: some path is unscoped, unowned, owned by another, or part
    of the plugin's door, which outside code can feel. A changelog fragment counts for nothing either way."""
    owners = set()
    for path in changed:
        if _any(NOTES, path):
            continue
        if _any(UNSCOPED, path):
            return None
        found = owner(manifests, path)
        if found is None or _any(found.door, path):
            return None
        owners.add(found)
    return owners.pop() if len(owners) == 1 else None
