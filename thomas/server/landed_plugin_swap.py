"""Classify landed Python changes and preflight them before live replacement."""

from __future__ import annotations

import ast
import fnmatch
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from thomas.core.kernel.context import KernelError

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def _matches(path: str, pattern: str) -> bool:
    pattern = pattern.replace("\\", "/").removeprefix("./")
    if pattern.endswith("/**"):
        prefix = pattern[:-3].rstrip("/")
        return path == prefix or path.startswith(prefix + "/")
    if any(c in pattern for c in "*?["):
        return fnmatch.fnmatchcase(path, pattern)
    prefix = pattern.rstrip("/")
    return path == prefix or path.startswith(prefix + "/")


def _relative(repo: Path, path: str | Path) -> str:
    root = repo.resolve()
    value = Path(str(path).replace("\\", "/"))
    full = (value if value.is_absolute() else root / value).resolve()
    try:
        return full.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"path is outside repository: {path}") from exc


def _module(path: str) -> str | None:
    parts = list(Path(path).with_suffix("").parts)
    if not parts or any(not part.isidentifier() for part in parts):
        return None
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or None


def classify(repo: str | Path, paths: Iterable[str | Path]) -> dict[str, Any]:
    """Identify row-owned changes; treat shared and unknown code as restart-only."""
    root = Path(repo).resolve()
    manifests: dict[str, list[str]] = {}
    for file in sorted((root / "plugins").glob("*.toml")):
        data = _read_toml(file)
        name = str(data.get("id") or data.get("name") or file.stem)
        if name in manifests:
            raise ValueError(f"duplicate plugin manifest id: {name}")
        patterns = data.get("owns", data.get("code", []))
        if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
            raise ValueError(f"invalid ownership list in {file.name}")
        manifests[name] = patterns

    profile = root / "thomas/server/rows/default.toml"
    rows = _read_toml(profile).get("row", []) if profile.is_file() else []
    entries = {str(row["id"]): str(row["entry"]).partition(":")[0] for row in rows}
    imports = {}
    for row, entry in entries.items():
        file = root / (entry.replace(".", "/") + ".py")
        declared = {entry}
        if file.is_file():
            try:
                tree = ast.parse(file.read_text(encoding="utf-8"))
            except SyntaxError:
                # Ownership still comes from the manifest; preflight rejects bad candidates.
                tree = ast.Module(body=[], type_ignores=[])
            for node in ast.walk(tree):
                if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "imports" for target in node.targets
                ):
                    declared.update(ast.literal_eval(node.value))
        imports[row] = declared
    kernel_files: set[str] = set()
    modules: dict[str, set[str]] = {}
    for original in paths:
        path = _relative(root, original)
        if not path.endswith(".py"):
            continue
        if path.startswith("thomas/core/kernel/"):
            kernel_files.add(path)
            continue
        changed_module = _module(path)
        if changed_module is None:
            raise ValueError(f"cannot identify changed Python module: {path}")
        owners = [name for name, patterns in manifests.items() if any(_matches(path, p) for p in patterns)]
        if len(owners) > 1:
            raise ValueError(f"ambiguous plugin ownership for {path}: {', '.join(owners)}")
        if not owners:
            kernel_files.add(path)
            continue
        affected = [
            row
            for row, declared in imports.items()
            if any(changed_module == name or changed_module.startswith(name + ".") for name in declared)
        ]
        if not affected:
            kernel_files.add(path)
            continue
        for row_id in affected:
            modules.setdefault(row_id, set()).update({changed_module, *imports[row_id]})
    return {
        "kernel_files": sorted(kernel_files),
        "plugin_rows": sorted(modules),
        "modules": {row: sorted(names) for row, names in sorted(modules.items())},
    }


def _preflight(repo: Path, paths: Iterable[str | Path]) -> None:
    """Check changed source without importing it or touching a live module."""
    for original in paths:
        path = _relative(repo, original)
        if path.endswith(".py"):
            source = repo / path
            compile(source.read_bytes(), str(source), "exec", dont_inherit=True)


# What a candidate's import, mount, route replay or self-check raises; the stage has already undone the candidate,
# and the old rows keep serving. Anything outside this list is a fault in the swap itself and reaches the reload
# watcher's log.
CANDIDATE_ERRORS = (
    ImportError,
    AttributeError,
    TypeError,
    ValueError,
    OSError,
    RuntimeError,
    SyntaxError,
    KernelError,
)


async def swap(app: Any, repo: str | Path, paths: Iterable[str | Path]) -> dict[str, Any]:
    """Load candidates beside the live generation, then publish one checked table."""
    paths = tuple(paths)
    try:
        result = classify(repo, paths)
    except (OSError, ValueError, KeyError, TypeError, SyntaxError) as exc:
        return {"swapped_rows": [], "swapped_at": None, "error": f"classification failed: {exc}"}
    if result["kernel_files"]:
        return {**result, "swapped_rows": [], "swapped_at": None, "error": "kernel changes require a restart"}
    if result["plugin_rows"]:
        try:
            _preflight(Path(repo).resolve(), paths)
        except (OSError, ValueError, SyntaxError) as exc:
            return {**result, "swapped_rows": [], "swapped_at": None, "error": f"preflight failed: {exc}"}
        from thomas.server.landed_plugin_runtime import NeedsRestart, replace
        from thomas.server.runtime_plugins import APP_RUNTIME_PLUGINS

        runtime = app.get(APP_RUNTIME_PLUGINS)
        if runtime is None:
            return {**result, "swapped_rows": [], "swapped_at": None, "error": "row runtime is not available"}
        names = sorted({name for group in result["modules"].values() for name in group})
        try:
            await replace(runtime, {"plugins": result["plugin_rows"], "modules": names})
        except NeedsRestart as exc:  # sound, but only a restart can load it: not an error, and not swapped
            return {**result, "swapped_rows": [], "swapped_at": None, "error": None, "needs_restart": str(exc)}
        except CANDIDATE_ERRORS as exc:
            return {**result, "swapped_rows": [], "swapped_at": None, "error": f"candidate rejected: {exc}"}
        return {**result, "swapped_rows": list(result["plugin_rows"]), "swapped_at": time.time(), "error": None}
    return {**result, "swapped_rows": [], "swapped_at": None, "error": None}
