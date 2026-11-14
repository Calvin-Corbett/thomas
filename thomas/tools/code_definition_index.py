"""Incremental, in-process index for Python definition lookup in a Build project.

A lookup stats source files and reads new, changed, or matching files for context.
The first lookup builds the index; later lookups in the same process reuse it.
"""

from __future__ import annotations

import re
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from thomas.tools import code_search_scan as scan

_NAMES = re.compile(r"^(?:class|def|async\s+def)\s+([^\s:(]+)\s*[:(]|^([^\s=:(]+)\s*=")
_LOCK = threading.RLock()
_CACHES: OrderedDict[Path, DefinitionIndex] = OrderedDict()


@dataclass
class _Entry:
    stamp: tuple[int, int]
    definitions: dict[str, list[int]]


class DefinitionIndex:
    """Keep definition locations current by statting and re-reading changed files."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._files: dict[Path, _Entry] = {}

    def lookup(self, base: Path, symbol: str, *, limit: int = 20) -> list[str] | None:
        """Return scan-compatible blocks; None asks the caller to use its old scan."""
        budget = scan.ScanBudget()
        seen: set[Path] = set()
        try:
            for path in scan.iter_source_files(base, exts={".py"}, budget=budget):
                seen.add(path)
                stat = path.stat()
                stamp = (stat.st_mtime_ns, stat.st_size)
                old = self._files.get(path)
                if old is not None and old.stamp == stamp:
                    continue
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                definitions: dict[str, list[int]] = {}
                for number, line in enumerate(lines, 1):
                    match = _NAMES.match(line)
                    if match:
                        definitions.setdefault(match.group(1) or match.group(2), []).append(number)
                self._files[path] = _Entry(stamp, definitions)
            if budget.stopped:
                return None
            # Forget deleted files, but only within the subtree just scanned.
            for path in list(self._files):
                if path == base or base in path.parents:
                    if path not in seen:
                        del self._files[path]
            blocks: list[str] = []
            for path in sorted(seen):
                entry = self._files[path]
                numbers = entry.definitions.get(symbol, [])
                if not numbers:
                    continue
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                for number in numbers:
                    end = min(len(lines), number + 3)
                    body = "\n".join(f"  {i + 1}: {lines[i]}" for i in range(number - 1, end))
                    blocks.append(f"{path.relative_to(self.root)}:{number}\n{body}")
                    if len(blocks) >= limit:
                        return blocks
            return blocks
        except (OSError, ValueError):
            return None


def find_definitions(root: Path, base: Path, symbol: str) -> list[str] | None:
    """Reuse a bounded per-project cache, serializing refreshes across Build calls."""
    with _LOCK:
        index = _CACHES.get(root)
        if index is None:
            index = DefinitionIndex(root)
            _CACHES[root] = index
            if len(_CACHES) > 4:
                _CACHES.popitem(last=False)
        _CACHES.move_to_end(root)
        return index.lookup(base, symbol)
