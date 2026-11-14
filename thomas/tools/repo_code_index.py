"""Shared, incremental source map for Build lookups in a project.

The SQLite database lives under the project's .thomas directory. Every process
opens the same database; each lookup reconciles file metadata with the working
tree, so edits and deletions are visible without a server restart. References
are lexical occurrences, not proof of a runtime call; test links are imports,
not proof of test execution or coverage.
"""

from __future__ import annotations

import ast
import asyncio
import hashlib
import os
import posixpath
import re
import sqlite3
import stat
from contextlib import closing
from pathlib import Path

from thomas.core.file_access import names_another_volume
from thomas.tools.base import Tool, ToolResult
from thomas.tools.code_search_scan import ROOT_SKIP_DIRS, SKIP_DIRS
from thomas.tools.fs_scope import scopes

SOURCE_SUFFIXES = frozenset({".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".go", ".rs"})
NAME = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\(")
OTHER_DEFINITION = re.compile(
    r"\b(?:function|class|interface|type|enum|struct|trait|fn|func)\s+([A-Za-z_$][\w$]*)"
    r"|\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)"
)
JS_IMPORT = re.compile(r"\b(?:import\s+(?:[^;]*?\s+from\s+)?|require\s*\(\s*)['\"]([^'\"]+)['\"]")
INDEX_VERSION = 3
_REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT: a junction or symlink on Windows


def _source_files(root: Path):
    for folder, dirs, names in os.walk(root, followlinks=False):
        current = Path(folder)
        dirs[:] = sorted(
            name
            for name in dirs
            if name not in SKIP_DIRS
            and (current != root or name not in ROOT_SKIP_DIRS)
            and not (current / name).is_symlink()
        )
        for name in sorted(names):
            path = current / name
            if path.suffix.lower() in SOURCE_SUFFIXES and not path.is_symlink():
                yield path


def _module(path: str) -> str:
    result = path.replace("/", ".")
    if result.endswith(".__init__.py"):
        return result[: -len(".__init__.py")]
    return result[:-3] if result.endswith(".py") else result


def _parse(path: str, text: str):
    definitions: list[tuple[str, int]] = []
    imports: set[str] = set()
    if path.endswith(".py"):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    definitions.append((node.name, node.lineno))
                elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    definitions.extend((target.id, node.lineno) for target in targets if isinstance(target, ast.Name))
                elif isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    package = _module(path).split(".")
                    if not path.endswith("/__init__.py"):
                        package = package[:-1]
                    prefix = package[: max(0, len(package) - node.level + 1)] if node.level else []
                    base = ".".join([*prefix, *([node.module] if node.module else [])])
                    imports.add(base)
                    imports.update(f"{base}.{alias.name}" for alias in node.names)
    else:
        for line_no, line in enumerate(text.splitlines(), 1):
            for match in OTHER_DEFINITION.finditer(line):
                definitions.append((match.group(1) or match.group(2), line_no))
        if Path(path).suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
            for match in JS_IMPORT.finditer(text):
                specifier = match.group(1)
                if specifier.startswith("."):
                    imports.add(posixpath.normpath(posixpath.join(posixpath.dirname(path), specifier)))
    references = {
        (match.group(1), line_no) for line_no, line in enumerate(text.splitlines(), 1) for match in NAME.finditer(line)
    }
    references.difference_update(definitions)
    return list(dict.fromkeys(definitions)), references, imports


def _tables(db: sqlite3.Connection) -> None:
    for statement in (
        "CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, mtime INTEGER, size INTEGER, digest TEXT)",
        "CREATE TABLE IF NOT EXISTS defs (name TEXT, path TEXT, line INTEGER)",
        "CREATE TABLE IF NOT EXISTS refs (name TEXT, path TEXT, line INTEGER)",
        "CREATE TABLE IF NOT EXISTS imports (module TEXT, path TEXT)",
    ):
        db.execute(statement)
    if "digest" not in {column[1] for column in db.execute("PRAGMA table_info(files)")}:
        db.execute("ALTER TABLE files ADD COLUMN digest TEXT")
    if db.execute("PRAGMA user_version").fetchone()[0] != INDEX_VERSION:
        for table in ("files", "defs", "refs", "imports"):
            db.execute(f"DELETE FROM {table}")
        db.execute(f"PRAGMA user_version = {INDEX_VERSION}")


def _refresh(db: sqlite3.Connection, root: Path) -> None:
    known = {
        path: (mtime, size, digest)
        for path, mtime, size, digest in db.execute("SELECT path,mtime,size,digest FROM files")
    }
    seen: set[str] = set()
    for source in _source_files(root):
        path = source.relative_to(root).as_posix()
        seen.add(path)
        try:
            stat = source.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
            content = source.read_bytes()
        except OSError:
            continue
        digest = hashlib.blake2b(content, digest_size=16).hexdigest()
        if known.get(path) == (*stamp, digest):
            continue
        text = content.decode("utf-8", errors="replace")
        defs, refs, imports = _parse(path, text)
        if path in known:
            for table in ("files", "defs", "refs", "imports"):
                db.execute(f"DELETE FROM {table} WHERE path=?", (path,))
        db.execute("INSERT INTO files (path,mtime,size,digest) VALUES (?,?,?,?)", (path, *stamp, digest))
        db.executemany("INSERT INTO defs VALUES (?,?,?)", ((name, path, line) for name, line in defs))
        db.executemany("INSERT INTO refs VALUES (?,?,?)", ((name, path, line) for name, line in refs))
        db.executemany("INSERT INTO imports VALUES (?,?)", ((module, path) for module in imports if module))
    for path in known.keys() - seen:
        for table in ("files", "defs", "refs", "imports"):
            db.execute(f"DELETE FROM {table} WHERE path=?", (path,))


def _is_test_file(path: str) -> bool:
    parts = Path(path).parts
    return bool(
        Path(path).suffix in SOURCE_SUFFIXES
        and (
            any(part in {"test", "tests", "__tests__"} for part in parts[:-1])
            or parts[-1].startswith("test_")
            or re.search(r"(?:\.test|\.spec)\.[cm]?[jt]sx?$", parts[-1]) is not None
        )
    )


def _text_parts(root: Path, path: str) -> tuple[str, ...]:
    """The folders and name ``path`` gives under ``root``, read from the text alone: no filesystem call is made.

    Another drive, a network name, a ``..`` and an absolute path outside the root are refused here, so nothing is
    touched on a name that cannot be inside. An absolute path inside the root is taken as the relative one.
    """
    if names_another_volume(path, root):
        raise ValueError("Path escapes project")
    given = Path(path)
    if given.is_absolute() or given.drive or given.root:
        base = [os.path.normcase(part) for part in root.parts]
        got = [os.path.normcase(part) for part in given.parts]
        if got[: len(base)] != base:
            raise ValueError("Path escapes project")
        parts = given.parts[len(base) :]
    else:
        parts = given.parts
    if ".." in parts:
        raise ValueError("Path escapes project")
    return tuple(part for part in parts if part != ".")


def _is_link(path: Path) -> bool:
    """A symlink or a junction, read with lstat so the link itself is looked at and never what it leads to."""
    try:
        info = path.lstat()
    except OSError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def _link_on_the_way(root: Path, parts: tuple[str, ...]) -> bool:
    """True when any component between the root and the target, the target included, is a link."""
    current = root
    for part in parts:
        current = current / part
        if _is_link(current):
            return True
    return False


def _is_file(scope, rel: str) -> bool:
    try:
        return scope.resolve(rel).is_file()
    except (ValueError, OSError):
        return False


def lookup(root: Path, *, symbol: str = "", path: str = "", limit: int = 30) -> dict:
    """Find definitions and lexical references for a name, or importing tests for a file."""
    root = root.resolve()
    scope = scopes().scope(root)
    qualified = bool(symbol and "." in symbol and not path)
    if qualified:
        module, name = symbol.rsplit(".", 1)
        if module and name:
            symbol = name
            module_path = module.replace(".", "/")
            path = module_path + ".py"
            if not _is_file(scope, path) and _is_file(scope, module_path + "/__init__.py"):
                path = module_path + "/__init__.py"
    if not symbol and not path:
        raise ValueError("Provide a symbol or a source file path")
    if path:
        parts = _text_parts(root, path)
        if any(part in SKIP_DIRS for part in parts):
            raise ValueError("Path is outside the indexed source tree")
        if _link_on_the_way(root, parts):
            raise ValueError("Path is outside the indexed source tree")
        try:
            target = scope.resolve(path)
        except ValueError:
            raise ValueError("Path escapes project") from None
        path = target.relative_to(root).as_posix()
        if target.suffix.lower() not in SOURCE_SUFFIXES or not target.is_file():
            raise ValueError("Path must name an indexed source file")
        parts = target.relative_to(root).parts[:-1]
        if any(part in SKIP_DIRS for part in parts) or (parts and parts[0] in ROOT_SKIP_DIRS):
            raise ValueError("Path is outside the indexed source tree")
    limit = max(1, min(int(limit), 100))
    store = root / ".thomas" / "code_index.sqlite3"
    store.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(store, timeout=30)) as db:
        with db:
            # Serialize schema setup and the known-file snapshot with other writers.
            db.execute("BEGIN IMMEDIATE")
            _tables(db)
            _refresh(db, root)
            for table, column in (("defs", "name"), ("refs", "name"), ("imports", "module")):
                db.execute(f"CREATE INDEX IF NOT EXISTS {table}_{column} ON {table}({column})")
        if path and not symbol:
            defs = db.execute(
                "SELECT name,path,line FROM defs WHERE path=? ORDER BY line LIMIT ?", (path, limit)
            ).fetchall()
            refs = db.execute(
                "SELECT DISTINCT refs.name,refs.path,refs.line FROM refs "
                "JOIN defs ON defs.name=refs.name WHERE defs.path=? "
                "ORDER BY refs.path,refs.line LIMIT ?",
                (path, limit),
            ).fetchall()
        else:
            defs = db.execute(
                "SELECT name,path,line FROM defs WHERE name=? "
                + ("AND path=? " if path else "")
                + "ORDER BY path,line LIMIT ?",
                (symbol, path, limit) if path else (symbol, limit),
            ).fetchall()
            refs = db.execute(
                "SELECT name,path,line FROM refs WHERE name=? "
                + ("AND (path=? OR path IN (SELECT path FROM imports WHERE module=?)) " if qualified else "")
                + "ORDER BY path,line LIMIT ?",
                (symbol, path, _module(path) if path.endswith(".py") else path, limit)
                if qualified
                else (symbol, limit),
            ).fetchall()
        sources = {path} if path else {row[1] for row in defs}
        modules = {_module(source) if source.endswith(".py") else source for source in sources}
        for source in sources:
            if Path(source).suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"}:
                modules.add(posixpath.splitext(source)[0])
        tests = set()
        for module in modules:
            tests.update(
                row[0]
                for row in db.execute("SELECT path FROM imports WHERE module=?", (module,))
                if _is_test_file(row[0])
            )
    return {
        "definitions": [{"name": name, "path": file, "line": line} for name, file, line in defs],
        "references": [{"name": name, "path": file, "line": line} for name, file, line in refs],
        "tests_importing_files": sorted(tests)[:limit],
        "note": "References are lexical matches; test links indicate imports, not execution or coverage.",
    }


class RepoIndexTool(Tool):
    name = "code.repo_index"
    category = "code"
    description = (
        "Look up a symbol's definitions, lexical references and tests importing its files "
        "in the shared, automatically refreshed project index. Pass symbol or path."
    )
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {"type": "string", "description": "Exact name to look up"},
            "path": {"type": "string", "description": "Project-relative source file to inspect"},
            "limit": {"type": "integer", "description": "Maximum matches per category (1-100)"},
        },
    }

    def __init__(self, root: Path):
        self._root = root.resolve()

    async def execute(self, args: dict) -> ToolResult:
        try:
            result = await asyncio.to_thread(
                lookup,
                self._root,
                symbol=str(args.get("symbol") or ""),
                path=str(args.get("path") or ""),
                limit=args.get("limit", 30),
            )
            return ToolResult(ok=True, data=result)
        except (OSError, ValueError, sqlite3.Error) as exc:
            return ToolResult(ok=False, error=str(exc))
