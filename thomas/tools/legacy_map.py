"""Legacy ingestion / code map (CAP-142).

Build a symbol/edge code map over a (potentially large, legacy) Python
codebase, ingest it incrementally with a per-file content-hash gate, and answer
reverse-dependency *impact set* questions with a measured precision/recall
accuracy report against a known golden set.

Design (honest "adapter" seam):
    * The only external edge is the *filesystem* (reading source files) and the
      *wall clock* (recording ``ingested_at``). Both are injectable:
      ``root`` points at any tree (a temp fixture in tests), and ``clock`` is a
      ``Callable[[], float]`` defaulting to :func:`time.time`. No network, no
      new pip dependencies -- parsing is stdlib :mod:`ast`, persistence is
      stdlib :mod:`sqlite3`.

The map has three moving parts:

1. **Code map** -- every ``def``/``class`` becomes a :class:`Symbol`
   (module-qualified name + ``file:line``); imports and resolvable call
   references become :class:`Edge` rows (``src`` depends on ``dst``).

2. **Hash-gated incremental ingest** -- each file carries a sha256 content
   hash. Re-ingesting is ``O(changed)``: an unchanged file is skipped without
   re-parsing, a changed/new file re-parses *only itself* and replaces its own
   symbols/edges, and a file that vanished from disk has its rows purged.

3. **Impact set + accuracy** -- given a changed symbol, :meth:`CodeMap.impact_set`
   returns its transitive reverse-dependency closure ("who is affected"), and
   :func:`accuracy_report` scores a computed set against a golden set
   (precision / recall / f1).

Everything is deterministic: query results are sorted, traversal order is
stable, and timestamps come from the injected clock.
"""

from __future__ import annotations

import ast
import hashlib
import logging
import os
import sqlite3
import time
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default on-disk location; overridable per-instance or via env var.
ENV_DB_PATH = "THOMAS_LEGACY_MAP_DB"
_DEFAULT_DB_NAME = "legacy_code_map.sqlite3"

# Node kinds.
KIND_MODULE = "module"
KIND_CLASS = "class"
KIND_FUNCTION = "function"
KIND_METHOD = "method"

# Edge kinds.
EDGE_IMPORT = "import"
EDGE_CALL = "call"

_SKIP_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "node_modules",
    "build",
    "dist",
}


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class Symbol:
    """A defined function/class/method with its source location."""

    qualname: str
    kind: str
    file: str
    lineno: int


@dataclass(frozen=True, order=True)
class Edge:
    """A directed dependency: ``src`` references/imports/calls ``dst``."""

    src: str
    dst: str
    kind: str
    file: str
    lineno: int


@dataclass
class IngestReport:
    """Outcome of a single :meth:`CodeMap.ingest` pass."""

    files_scanned: int = 0
    parsed_files: list[str] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
    removed_files: list[str] = field(default_factory=list)
    unparseable_files: list[str] = field(default_factory=list)
    symbols_written: int = 0
    edges_written: int = 0

    @property
    def files_parsed(self) -> int:
        return len(self.parsed_files)

    @property
    def files_skipped(self) -> int:
        return len(self.skipped_files)

    @property
    def files_removed(self) -> int:
        return len(self.removed_files)


@dataclass(frozen=True)
class AccuracyReport:
    """Precision/recall of a computed impact set against a golden set."""

    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    computed: tuple[str, ...]
    golden: tuple[str, ...]
    missing: tuple[str, ...]  # golden - computed (false negatives)
    spurious: tuple[str, ...]  # computed - golden (false positives)


# ---------------------------------------------------------------------------
# Per-file parse result (in-memory, pre-persistence)
# ---------------------------------------------------------------------------


@dataclass
class _FileParse:
    module: str
    file_rel: str
    symbols: list[Symbol]
    import_edges: list[Edge]
    bindings: dict[str, str]
    # (enclosing_qualname, (mode, ident), lineno) captured for call resolution.
    raw_calls: list[tuple[str, tuple[str, str | None], int]]


# ---------------------------------------------------------------------------
# AST extraction
# ---------------------------------------------------------------------------


def module_name_for(root: Path, file: Path) -> str:
    """Derive a dotted module name for ``file`` relative to ``root``.

    ``pkg/mod.py`` -> ``pkg.mod``; ``pkg/__init__.py`` -> ``pkg``.
    """
    rel = file.relative_to(root)
    parts = list(rel.parts)
    if parts and parts[-1] == "__init__.py":
        parts = parts[:-1]
    elif parts:
        parts[-1] = parts[-1][:-3] if parts[-1].endswith(".py") else parts[-1]
    return ".".join(parts)


class _Extractor(ast.NodeVisitor):
    """Collect symbols, import bindings, and call edges from one module."""

    def __init__(self, module: str, rel_file: str) -> None:
        self.module = module
        self.rel_file = rel_file
        self.symbols: list[Symbol] = []
        # local binding name -> resolved dotted target (module or symbol)
        self.bindings: dict[str, str] = {}
        self.import_edges: list[Edge] = []
        self.raw_calls: list[tuple[str, tuple[str, str | None], int]] = []
        self._stack: list[tuple[str, str]] = []  # (name, kind)

    # -- scope helpers --

    def _qual(self, name: str) -> str:
        prefix = ".".join(n for n, _ in self._stack)
        base = f"{self.module}.{prefix}" if prefix else self.module
        return f"{base}.{name}"

    def _enclosing_symbol(self) -> str:
        """Qualname of the nearest def/class enclosing the current node."""
        if not self._stack:
            return self.module
        prefix = ".".join(n for n, _ in self._stack)
        return f"{self.module}.{prefix}"

    def _in_class(self) -> bool:
        return bool(self._stack) and self._stack[-1][1] == KIND_CLASS

    # -- definitions --

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.symbols.append(Symbol(self._qual(node.name), KIND_CLASS, self.rel_file, node.lineno))
        self._stack.append((node.name, KIND_CLASS))
        self.generic_visit(node)
        self._stack.pop()

    def _visit_func(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        kind = KIND_METHOD if self._in_class() else KIND_FUNCTION
        self.symbols.append(Symbol(self._qual(node.name), kind, self.rel_file, node.lineno))
        self._stack.append((node.name, kind))
        self.generic_visit(node)
        self._stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_func(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_func(node)

    # -- imports --

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.asname:
                self.bindings[alias.asname] = alias.name
            else:
                root = alias.name.split(".")[0]
                self.bindings[root] = root
            self.import_edges.append(Edge(self.module, alias.name, EDGE_IMPORT, self.rel_file, node.lineno))
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        base = self._resolve_from_module(node)
        for alias in node.names:
            if alias.name == "*":
                continue
            target = f"{base}.{alias.name}" if base else alias.name
            bind = alias.asname or alias.name
            self.bindings[bind] = target
            self.import_edges.append(Edge(self.module, target, EDGE_IMPORT, self.rel_file, node.lineno))
        self.generic_visit(node)

    def _resolve_from_module(self, node: ast.ImportFrom) -> str:
        if not node.level:
            return node.module or ""
        # Relative import: the current module ``pkg.sub.mod`` lives in package
        # ``pkg.sub``; each extra level strips one more package component.
        pkg_parts = self.module.split(".")[:-1]
        if node.level > 1:
            pkg_parts = pkg_parts[: len(pkg_parts) - (node.level - 1)]
        base = ".".join(pkg_parts)
        if node.module:
            base = f"{base}.{node.module}" if base else node.module
        return base

    # -- calls --

    def visit_Call(self, node: ast.Call) -> None:
        info = _call_name(node.func)
        if info is not None:
            self.raw_calls.append((self._enclosing_symbol(), info, node.lineno))
        self.generic_visit(node)


def _call_name(func: ast.expr) -> tuple[str, str | None] | None:
    """Classify a call target.

    ``("name", ident)`` for a bare ``foo()``; ``("attr", "root.attr")`` for
    ``root.attr()``; ``("method", attr)`` for a deeper ``a.b.method()``.
    """
    if isinstance(func, ast.Name):
        return ("name", func.id)
    if isinstance(func, ast.Attribute):
        if isinstance(func.value, ast.Name):
            return ("attr", f"{func.value.id}.{func.attr}")
        return ("method", func.attr)
    return None


def _parse_module(root: Path, file: Path) -> _FileParse:
    """Parse one file into symbols, import edges, bindings, and raw calls."""
    module = module_name_for(root, file)
    rel = file.relative_to(root).as_posix()
    source = file.read_text(encoding="utf-8", errors="strict")
    tree = ast.parse(source, filename=str(file))
    ex = _Extractor(module, rel)
    ex.visit(tree)
    return _FileParse(
        module=module,
        file_rel=rel,
        symbols=list(ex.symbols),
        import_edges=list(ex.import_edges),
        bindings=dict(ex.bindings),
        raw_calls=list(ex.raw_calls),
    )


def _resolve_calls(
    fp: _FileParse,
    symbol_index: dict[str, Symbol],
    short_index: dict[str, list[str]],
) -> list[Edge]:
    """Resolve a module's raw calls into concrete symbol->symbol edges."""
    module = fp.module
    module_syms = {q for q in symbol_index if q == module or q.startswith(module + ".")}
    edges: set[Edge] = set()
    for enclosing, (mode, ident), lineno in fp.raw_calls:
        assert ident is not None
        target: str | None = None
        if mode == "name":
            if ident in fp.bindings and fp.bindings[ident] in symbol_index:
                target = fp.bindings[ident]
            else:
                cand = f"{module}.{ident}"
                if cand in symbol_index:
                    target = cand
        elif mode == "attr":
            root_name, _, attr = ident.partition(".")
            if root_name in fp.bindings:
                cand = f"{fp.bindings[root_name]}.{attr}"
                if cand in symbol_index:
                    target = cand
            if target is None:
                target = _unique_short(attr, short_index, module_syms)
        else:  # "method"
            target = _unique_short(ident, short_index, module_syms)
        if target is not None and target != enclosing:
            edges.add(Edge(enclosing, target, EDGE_CALL, fp.file_rel, lineno))
    return sorted(edges)


def _unique_short(
    short: str,
    short_index: dict[str, list[str]],
    prefer: set[str],
) -> str | None:
    """Resolve a bare method/attr name to a single symbol if unambiguous.

    Prefers a same-module match; otherwise accepts a globally unique match.
    """
    candidates = short_index.get(short, [])
    if not candidates:
        return None
    local = [c for c in candidates if c in prefer]
    if len(local) == 1:
        return local[0]
    if len(candidates) == 1:
        return candidates[0]
    return None


# ---------------------------------------------------------------------------
# The code map
# ---------------------------------------------------------------------------


class CodeMap:
    """A persisted symbol/edge map with hash-gated incremental ingest."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        db_path: str | os.PathLike[str] | None = None,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self._clock = clock or time.time
        resolved = db_path or os.environ.get(ENV_DB_PATH) or (self.root / _DEFAULT_DB_NAME)
        self.db_path = str(resolved)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    # -- lifecycle --

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> CodeMap:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                hash TEXT NOT NULL,
                ingested_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS symbols (
                qualname TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                file TEXT NOT NULL,
                lineno INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS edges (
                src TEXT NOT NULL,
                dst TEXT NOT NULL,
                kind TEXT NOT NULL,
                file TEXT NOT NULL,
                lineno INTEGER NOT NULL,
                UNIQUE(src, dst, kind, file, lineno)
            );
            CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file);
            CREATE INDEX IF NOT EXISTS idx_edges_file ON edges(file);
            CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst);
            CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src);
            """
        )
        self._conn.commit()

    # -- ingest --

    def _iter_source_files(self) -> Iterator[Path]:
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
            for name in sorted(filenames):
                if name.endswith(".py"):
                    yield Path(dirpath) / name

    @staticmethod
    def _hash_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def ingest(self) -> IngestReport:
        """Scan ``root`` and update the map, re-parsing only changed files."""
        report = IngestReport()
        stored = {row["path"]: row["hash"] for row in self._conn.execute("SELECT path, hash FROM files")}
        seen: set[str] = set()
        changed: list[tuple[Path, str, str]] = []  # (file, rel, hash)

        for file in self._iter_source_files():
            rel = file.relative_to(self.root).as_posix()
            seen.add(rel)
            report.files_scanned += 1
            digest = self._hash_bytes(file.read_bytes())
            if stored.get(rel) == digest:
                report.skipped_files.append(rel)  # hash gate: no re-parse
                continue
            changed.append((file, rel, digest))

        # Purge files that disappeared from disk (O(removed)).
        for rel in sorted(set(stored) - seen):
            self._purge_file(rel)
            report.removed_files.append(rel)

        # Parse only changed/new files.
        parses: dict[str, _FileParse] = {}
        for file, rel, digest in changed:
            try:
                fp = _parse_module(self.root, file)
            except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
                # Legacy trees contain unparseable files; gate them by hash so
                # they are not retried every pass, but record no symbols.
                logger.warning("legacy_map: cannot parse %s: %s", rel, exc)
                self._purge_file(rel)
                self._conn.execute(
                    "INSERT OR REPLACE INTO files(path, hash, ingested_at) VALUES (?, ?, ?)",
                    (rel, digest, self._clock()),
                )
                report.unparseable_files.append(rel)
                report.parsed_files.append(rel)
                continue
            parses[fp.module] = fp
            report.parsed_files.append(rel)

        if parses:
            self._apply_parses(parses)
            report.symbols_written = sum(len(p.symbols) for p in parses.values())
        self._conn.commit()

        report.edges_written = self._count_edges_for(sorted(p.file_rel for p in parses.values()))
        report.parsed_files.sort()
        report.skipped_files.sort()
        return report

    def _apply_parses(self, parses: dict[str, _FileParse]) -> None:
        # Full symbol index = stored symbols (minus files being replaced) +
        # freshly parsed symbols. Cross-module call resolution needs the whole
        # picture, but only the changed files' rows are rewritten.
        replaced_files = {p.file_rel for p in parses.values()}
        symbol_index: dict[str, Symbol] = {}
        for row in self._conn.execute("SELECT qualname, kind, file, lineno FROM symbols"):
            if row["file"] in replaced_files:
                continue
            symbol_index[row["qualname"]] = Symbol(row["qualname"], row["kind"], row["file"], row["lineno"])
        for fp in parses.values():
            for sym in fp.symbols:
                symbol_index[sym.qualname] = sym

        short_index: dict[str, list[str]] = {}
        for q in symbol_index:
            short_index.setdefault(q.split(".")[-1], []).append(q)
        for lst in short_index.values():
            lst.sort()

        for fp in parses.values():
            rel = fp.file_rel
            self._purge_file(rel)
            digest = self._hash_bytes((self.root / rel).read_bytes())
            self._conn.execute(
                "INSERT OR REPLACE INTO files(path, hash, ingested_at) VALUES (?, ?, ?)",
                (rel, digest, self._clock()),
            )
            for sym in fp.symbols:
                self._conn.execute(
                    "INSERT OR REPLACE INTO symbols(qualname, kind, file, lineno) VALUES (?, ?, ?, ?)",
                    (sym.qualname, sym.kind, sym.file, sym.lineno),
                )
            call_edges = _resolve_calls(fp, symbol_index, short_index)
            for edge in list(fp.import_edges) + call_edges:
                self._conn.execute(
                    "INSERT OR IGNORE INTO edges(src, dst, kind, file, lineno) VALUES (?, ?, ?, ?, ?)",
                    (edge.src, edge.dst, edge.kind, edge.file, edge.lineno),
                )

    def _purge_file(self, rel: str) -> None:
        self._conn.execute("DELETE FROM symbols WHERE file = ?", (rel,))
        self._conn.execute("DELETE FROM edges WHERE file = ?", (rel,))
        self._conn.execute("DELETE FROM files WHERE path = ?", (rel,))

    def _count_edges_for(self, rels: Iterable[str]) -> int:
        total = 0
        for rel in rels:
            cur = self._conn.execute("SELECT COUNT(*) AS n FROM edges WHERE file = ?", (rel,))
            total += cur.fetchone()["n"]
        return total

    # -- queries --

    def symbols(self) -> list[Symbol]:
        rows = self._conn.execute("SELECT qualname, kind, file, lineno FROM symbols ORDER BY qualname")
        return [Symbol(r["qualname"], r["kind"], r["file"], r["lineno"]) for r in rows]

    def edges(self) -> list[Edge]:
        rows = self._conn.execute(
            "SELECT src, dst, kind, file, lineno FROM edges ORDER BY src, dst, kind, file, lineno"
        )
        return [Edge(r["src"], r["dst"], r["kind"], r["file"], r["lineno"]) for r in rows]

    def get_symbol(self, qualname: str) -> Symbol | None:
        row = self._conn.execute(
            "SELECT qualname, kind, file, lineno FROM symbols WHERE qualname = ?", (qualname,)
        ).fetchone()
        if row is None:
            return None
        return Symbol(row["qualname"], row["kind"], row["file"], row["lineno"])

    def file_hash(self, rel: str) -> str | None:
        row = self._conn.execute("SELECT hash FROM files WHERE path = ?", (rel,)).fetchone()
        return row["hash"] if row else None

    # -- impact set --

    def impact_set(self, qualname: str, *, symbols_only: bool = True) -> list[str]:
        """Transitive reverse-dependency closure of ``qualname``.

        Returns the set of nodes that (transitively) depend on ``qualname`` --
        i.e. would be affected if it changed. With ``symbols_only`` (default),
        module-level pseudo-nodes are excluded so callers get concrete symbols.
        """
        reverse: dict[str, set[str]] = {}
        for r in self._conn.execute("SELECT src, dst FROM edges"):
            reverse.setdefault(r["dst"], set()).add(r["src"])
        known = {s.qualname for s in self.symbols()}

        visited: set[str] = set()
        queue: deque[str] = deque([qualname])
        while queue:
            node = queue.popleft()
            for dep in sorted(reverse.get(node, ())):
                if dep not in visited and dep != qualname:
                    visited.add(dep)
                    queue.append(dep)
        result = visited
        if symbols_only:
            result = {n for n in result if n in known}
        return sorted(result)

    # -- round-trip snapshot --

    def to_dict(self) -> dict[str, Any]:
        """Serialize the whole map to a plain dict (json-round-trippable)."""
        return {
            "symbols": [vars(s) for s in self.symbols()],
            "edges": [vars(e) for e in self.edges()],
            "files": [
                {"path": r["path"], "hash": r["hash"]}
                for r in self._conn.execute("SELECT path, hash FROM files ORDER BY path")
            ],
        }


# ---------------------------------------------------------------------------
# Accuracy report
# ---------------------------------------------------------------------------


def accuracy_report(computed: Iterable[str], golden: Iterable[str]) -> AccuracyReport:
    """Score a computed impact set against a golden (known-true) set."""
    c = set(computed)
    g = set(golden)
    tp = len(c & g)
    fp = len(c - g)
    fn = len(g - c)
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return AccuracyReport(
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        computed=tuple(sorted(c)),
        golden=tuple(sorted(g)),
        missing=tuple(sorted(g - c)),
        spurious=tuple(sorted(c - g)),
    )
