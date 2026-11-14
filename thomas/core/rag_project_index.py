"""Project-owned retrieval; roots and indexing facts never use global preferences."""

from __future__ import annotations

import errno
import os
import stat
import threading
import time
from collections.abc import Iterable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from thomas.core.rag_index import RagIndex
from thomas.core.rag_indexer import (
    DEFAULT_EXTENSIONS,
    DEFAULT_SKIP_DIRS,
    MANIFEST_NAME,
    MANIFEST_VERSION,
    _safe_json_load,
)


class _ProjectFacts:
    def __init__(self, root: Path, extensions: list[str]) -> None:
        self.values = {"rag.root_dir": str(root), "rag.extensions": ",".join(extensions)}

    def get_fact(self, key: str) -> str | None:
        return self.values.get(key)

    def set_fact(self, key: str, value: str) -> None:
        self.values[key] = value


class ProjectRagIndex(RagIndex):
    """Incremental on-demand index with no process-wide root or background scan."""

    def __init__(self, root: Path, *, extensions: list[str] | None = None) -> None:
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Semantic search requires a project directory")
        self.extensions = list(extensions or DEFAULT_EXTENSIONS)
        self._query_lock = threading.Lock()
        self._facts = _ProjectFacts(self.root, self.extensions)
        persist_dir = self.root / ".thomas" / "rag-index"
        with self._own_storage(persist_dir):
            self._validate_manifest(persist_dir)
            super().__init__(persist_dir=persist_dir, persistence_factory=lambda: self._facts, start_worker=False)
            self._manifest["root_dir"] = str(self.root)
            self._save_manifest()
            self._validate_manifest(persist_dir)

    def _validate_manifest(self, persist_dir: Path) -> None:
        if not persist_dir.exists() or not any(persist_dir.iterdir()):
            return
        manifest = _safe_json_load(persist_dir / MANIFEST_NAME)
        if not isinstance(manifest, dict):
            raise ValueError("Project search cache has no valid ownership manifest")
        saved_root = manifest.get("root_dir")
        if saved_root is not None and not isinstance(saved_root, str):
            raise ValueError("Project search cache has no valid ownership manifest")
        if saved_root and Path(saved_root).resolve() != self.root:
            raise ValueError("Semantic index belongs to a different project")
        if not saved_root or manifest.get("version") != MANIFEST_VERSION or not isinstance(manifest.get("files"), dict):
            raise ValueError("Project search cache has no valid ownership manifest; rebuild the cache before searching")

    def _check_storage(self, path: Path) -> None:
        def check(item: Path) -> None:
            if item.resolve() != item.absolute():
                raise ValueError("Semantic index storage cannot use linked paths")
            if item.is_file() and item.stat().st_nlink > 1:
                raise ValueError("Semantic index storage cannot use hard-linked files")

        check(path.parent)
        check(path)
        check(path.parent / "rag-index.lock")
        for directory, names, files in os.walk(path, followlinks=False):
            for name in names + files:
                check(Path(directory) / name)

    @contextmanager
    def _own_storage(self, path: Path):
        self._check_storage(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = path.parent / "rag-index.lock"
        with lock.open("a+b") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_ino != lock.lstat().st_ino:
                raise ValueError("Semantic index lock cannot use linked paths")
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b"\0")
                handle.flush()
            deadline = time.monotonic() + 30
            while True:
                handle.seek(0)
                try:
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                        raise
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Project search index is busy; retry shortly") from exc
                    time.sleep(0.05)
            try:
                self._check_storage(path)
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _iter_files(self, root: Path, extset: set) -> Iterable[Path]:
        for directory, names, files in os.walk(self.root, followlinks=False):
            base = Path(directory)
            names[:] = [
                name
                for name in names
                if name not in DEFAULT_SKIP_DIRS
                and not name.startswith(".")
                and (base / name).resolve() == (base / name).absolute()
            ]
            for name in files:
                path = base / name
                if (
                    path.suffix.lower() in extset
                    and path.resolve() == path.absolute()
                    and path.is_file()
                    and path.stat().st_nlink == 1
                ):
                    yield path

    def search(
        self, query: str, k: int = 5, filter_ext: str | None = None, max_per_file: int = 1
    ) -> list[dict[str, Any]]:
        with self._query_lock, self._own_storage(self.persist_dir):
            self._validate_manifest(self.persist_dir)
            self._load_manifest()
            self._do_build(self.root, self.extensions)
            return super().search(query, k=k, filter_ext=filter_ext, max_per_file=max_per_file)

    def _scoped_hits(self, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
        current = []
        for hit in hits:
            relative = Path(str(hit.get("relpath") or hit.get("file") or ""))
            if relative.anchor or any(part.startswith(".") or part in DEFAULT_SKIP_DIRS for part in relative.parts):
                continue
            target = self.root / relative
            resolved = target.resolve()
            if (
                resolved.is_relative_to(self.root)
                and resolved == target.absolute()
                and target.is_file()
                and target.stat().st_nlink == 1
            ):
                current.append(hit)
        return current

    def _fts_search(self, spec: Any, n: int, ext: str | None) -> list[dict[str, Any]]:
        return self._scoped_hits(super()._fts_search(spec, n, ext))

    def _chroma_search(self, query: str, n: int, ext: str | None) -> list[dict[str, Any]]:
        return self._scoped_hits(super()._chroma_search(query, n, ext))
