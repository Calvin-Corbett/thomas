"""RAG Index: Hybrid semantic + lexical search with smart document chunking.

FEATURE 2 — FULL-REPO RAG INDEX (delight edition)

Meets original requirements:
- RagIndex class with background indexing
- sentence-transformers (all-MiniLM-L6-v2) embeddings + Chroma persistent store
- Persist dir: ./thomas_rag_index/
- build(root_dir, extensions=...) runs in a thread (non-blocking startup)
- update(filepath) re-indexes a single file
- search(query, k=5, filter_ext=None) -> [{"file": path#Lx-Ly, "chunk": text, "score": float}]
- clear() wipe and rebuild
- get_rag_index() singleton loads instantly, builds in background if missing/empty

Consumer-loved upgrades:
1) Hybrid search: Semantic (Chroma) + Lexical (SQLite FTS5) fused with RRF.
2) Query operators INSIDE the query string (no schema changes):
     - path:thomas/tools, file:rag_index.py, ext:.py, symbol:ToolRegistry
     - kind:function|class, phrase:"exact phrase", regex:/pattern/
3) Preview snippets with LINE NUMBERS + light highlighting.
4) Smart chunking: Python AST, Markdown headings, whitespace-token fallback.
5) Background worker thread, debounced updates, incremental builds, deleted-file pruning.

Design philosophy: strong defaults, minimal knobs, no fragile magic.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from thomas.core.persistence import get_persistence
from thomas.core.rag_embeddings import (
    _load_embedder,
    _make_chroma_collection,
    _rrf_fuse,
)
from thomas.core.rag_format import (
    format_result,
    maybe_render_from_disk,
)
from thomas.core.rag_indexer import (
    DEFAULT_EXTENSIONS,
    DEFAULT_SKIP_DIRS,
    FTS_DB_NAME,
    MANIFEST_NAME,
    MANIFEST_VERSION,
    _chunk_by_type,
    _default_repo_root,
    _normalize_relpath,
    _now_iso,
    _read_text_bytes,
    _safe_json_dump,
    _safe_json_load,
    _sha1_bytes,
    _sha1_str,
)
from thomas.core.rag_search import (
    _parse_query,
    _QuerySpec,
    chroma_search_impl,
    ensure_fts_impl,
    fts_delete_file_impl,
    fts_search_impl,
    fts_upsert_chunks_impl,
    regex_search_impl,
)

logger = logging.getLogger(__name__)

# Constants
DEFAULT_INDEX_DIR = Path("./thomas_rag_index").resolve()
DEFAULT_MODEL_NAME = "all-MiniLM-L6-v2"
DEFAULT_COLLECTION = "thomas_repo"
DEFAULT_UPDATE_DEBOUNCE_S = 0.30


class RagIndex:
    """RAG index with hybrid search, smart chunking, and background updates.

    Provides semantic search via embeddings, lexical search via FTS5, and
    advanced query operators for precise searching.
    """

    def __init__(
        self,
        persist_dir: Path = DEFAULT_INDEX_DIR,
        model_name: str = DEFAULT_MODEL_NAME,
        collection_name: str = DEFAULT_COLLECTION,
        update_debounce_s: float = DEFAULT_UPDATE_DEBOUNCE_S,
    ) -> None:
        self.persist_dir = Path(persist_dir)
        self.model_name = model_name
        self.collection_name = collection_name
        self.update_debounce_s = float(update_debounce_s)

        self._lock = threading.RLock()
        self._embed_lock = threading.Lock()
        self._client = None
        self._collection = None
        self._embedder = None

        self._manifest_path = self.persist_dir / MANIFEST_NAME
        self._fts_path = self.persist_dir / FTS_DB_NAME
        self._fts_enabled = False

        self._manifest: dict[str, Any] = {
            "version": MANIFEST_VERSION,
            "root_dir": "",
            "extensions": [],
            "files": {},
        }

        # background worker state
        self._cv = threading.Condition()
        self._stop = False
        self._build_requested: tuple[Path, list[str]] | None = None
        self._clear_requested: bool = False
        self._build_running: bool = False
        self._pending_updates: dict[str, tuple[str, float]] = {}

        # quick open
        self._ensure_chroma(load_embedder=False)
        self._load_manifest()
        self._ensure_fts()

        self._worker = threading.Thread(target=self._worker_loop, name="RagIndexWorker", daemon=True)
        self._worker.start()

    # ----- API -----

    def build(self, root_dir: str, extensions: list[str] = DEFAULT_EXTENSIONS) -> None:
        """Request a full index build in background thread.

        Args:
            root_dir: Root directory to index
            extensions: File extensions to include (e.g., ['.py', '.md'])
        """
        from thomas.core.rag_indexer import _normalize_ext_list

        root = Path(root_dir).resolve()
        exts = _normalize_ext_list(extensions)

        pe = get_persistence()
        pe.set_fact("rag.root_dir", str(root))
        pe.set_fact("rag.extensions", ",".join(exts))
        pe.set_fact("rag.build_requested_ts", _now_iso())

        with self._cv:
            self._build_requested = (root, exts)
            self._cv.notify_all()

    def update(self, filepath: str) -> None:
        """Request incremental update for a single file.

        Called after file writes. Debounced to batch rapid updates.

        Args:
            filepath: Path to file to re-index
        """
        p = Path(filepath).resolve()

        pe = get_persistence()
        exts_str = pe.get_fact("rag.extensions")
        exts = (
            [e.strip().lower() for e in str(exts_str).split(",") if e.strip()] if exts_str else list(DEFAULT_EXTENSIONS)
        )
        if p.suffix.lower() not in set(exts):
            return

        root_str = pe.get_fact("rag.root_dir")
        root = Path(root_str).resolve() if root_str else _default_repo_root()
        file_key, _ = self._make_file_key(p, root)

        due = time.time() + self.update_debounce_s
        with self._cv:
            self._pending_updates[file_key] = (str(p), due)
            self._cv.notify_all()

        pe.set_fact("rag.last_update", str(p))
        pe.set_fact("rag.last_update_enqueued_ts", _now_iso())

    def search(self, query: str, k: int = 5, filter_ext: str | None = None) -> list[dict[str, Any]]:
        """Hybrid semantic+lexical search with advanced query operators.

        Returns a list of dicts:
          {"file": "path#Lx-Ly", "chunk": "<snippet>", "score": float}

        Query operators:
          path:substring, file:substring, ext:.py, symbol:name, kind:function,
          phrase:"exact", regex:/pattern/
        """
        q = (query or "").strip()
        if not q:
            return []

        try:
            k = max(1, int(k))
        except (TypeError, ValueError):
            k = 5

        spec = _parse_query(q)

        # override ext from filter_ext if provided
        ext = None
        if filter_ext:
            ext = filter_ext.strip().lower()
            if ext and not ext.startswith("."):
                ext = f".{ext}"
        elif spec.ext:
            ext = spec.ext

        # regex mode: fast grep over candidate files
        if spec.regex:
            return self._regex_search(spec, k=k, ext=ext)

        # lexical: use phrase/spec.text/spec.symbol into FTS query
        lex = self._fts_search(spec, n=max(12, k * 5), ext=ext)

        # semantic: embed only free text / phrase / symbol
        sem: list[dict[str, Any]] = []
        try:
            sem_query = spec.phrase or spec.symbol or spec.text or spec.raw
            sem = self._chroma_search(sem_query, n=max(12, k * 5), ext=ext)
        except Exception:
            sem = []

        # post-filter by path/file substring constraints
        def ok_path(item: dict[str, Any]) -> bool:
            rel = (item.get("relpath") or item.get("file") or "").lower()
            if spec.path_substr and spec.path_substr.lower() not in rel:
                return False
            if spec.file_substr and spec.file_substr.lower() not in rel:
                return False
            if spec.kind and (item.get("kind") or "").lower() != spec.kind:
                return False
            if spec.symbol and spec.symbol.lower() not in (item.get("symbol") or "").lower():
                return False
            return True

        sem = [x for x in sem if ok_path(x)]
        lex = [x for x in lex if ok_path(x)]

        if sem and lex:
            fused = _rrf_fuse(sem, lex, k0=60)
            fused = fused[:k]
            return [
                format_result(
                    r, maybe_render_fn=lambda **kw: maybe_render_from_disk(**kw, root_dir=self._get_root_dir())
                )
                for r in fused
            ]

        base = sem if sem else lex
        base = base[:k]
        return [
            format_result(r, maybe_render_fn=lambda **kw: maybe_render_from_disk(**kw, root_dir=self._get_root_dir()))
            for r in base
        ]

    def clear(self) -> None:
        """Clear the index and request rebuild."""
        with self._cv:
            self._clear_requested = True
            self._cv.notify_all()

    def status(self) -> dict[str, Any]:
        """Return status dict with index statistics and pending operations."""
        pe = get_persistence()
        root = pe.get_fact("rag.root_dir") or self._manifest.get("root_dir") or str(_default_repo_root())
        exts = pe.get_fact("rag.extensions") or ",".join(self._manifest.get("extensions") or DEFAULT_EXTENSIONS)

        count = 0
        try:
            self._ensure_chroma(load_embedder=False)
            with self._lock:
                count = int(self._collection.count()) if self._collection else 0
        except Exception:
            count = 0

        with self._cv:
            pending = len(self._pending_updates)
            build_req = self._build_requested is not None
            building = self._build_running

        return {
            "persist_dir": str(self.persist_dir),
            "collection": self.collection_name,
            "model": self.model_name,
            "root_dir": str(root),
            "extensions": str(exts),
            "vector_count": count,
            "manifest_files": int(len(self._manifest.get("files", {}))),
            "fts_enabled": bool(self._fts_enabled),
            "build_running": bool(building),
            "build_requested": bool(build_req),
            "pending_updates": int(pending),
            "last_build_ts": pe.get_fact("rag.last_build_ts"),
            "last_build_error": pe.get_fact("rag.last_build_error"),
            "last_update": pe.get_fact("rag.last_update"),
            "last_update_action": pe.get_fact("rag.last_update_action"),
            "last_update_ts": pe.get_fact("rag.last_update_ts"),
        }

    # -------------------------
    # Worker loop (background thread)
    # -------------------------

    def _worker_loop(self) -> None:
        """Main loop for background indexing worker."""
        pe = get_persistence()

        while True:
            job_build: tuple[Path, list[str]] | None = None
            job_clear = False
            due_updates: list[tuple[str, str]] = []

            with self._cv:
                if self._stop:
                    return

                if self._clear_requested:
                    job_clear = True
                    self._clear_requested = False
                else:
                    if self._build_requested is not None and not self._build_running:
                        job_build = self._build_requested
                        self._build_requested = None
                        self._build_running = True
                    else:
                        now = time.time()
                        due_keys = [k for k, (_, due) in self._pending_updates.items() if due <= now]
                        for fk in due_keys:
                            abspath, _ = self._pending_updates.pop(fk)
                            due_updates.append((fk, abspath))

                        if not job_clear and job_build is None and not due_updates:
                            next_due = None
                            for _, (_, due) in self._pending_updates.items():
                                next_due = due if next_due is None else min(next_due, due)
                            timeout = None
                            if next_due is not None:
                                timeout = max(0.05, next_due - time.time())
                            self._cv.wait(timeout=timeout)
                            continue

            if job_clear:
                try:
                    self._do_clear()
                    pe.set_fact("rag.last_clear_ts", _now_iso())
                except Exception as e:
                    logger.exception("RAG: clear failed: %s", e)
                    pe.set_fact("rag.last_build_error", str(e))
                continue

            if job_build is not None:
                root, exts = job_build
                pe.set_fact("rag.build_started_ts", _now_iso())
                pe.set_fact("rag.last_build_error", "")
                pe.set_fact("rag.build_running", "1")
                try:
                    self._do_build(root, exts)
                    pe.set_fact("rag.last_build_ts", _now_iso())
                    pe.set_fact("rag.last_build_root", str(root))
                except Exception as e:
                    logger.exception("RAG: build failed: %s", e)
                    pe.set_fact("rag.last_build_error", str(e))
                finally:
                    pe.set_fact("rag.build_running", "0")
                    pe.set_fact("rag.build_finished_ts", _now_iso())
                    with self._cv:
                        self._build_running = False
                continue

            if due_updates:
                for file_key, abspath in due_updates:
                    try:
                        self._do_update_one(file_key=file_key, abspath=abspath)
                    except Exception as e:
                        logger.debug("RAG: update failed for %s: %s", abspath, e)
                continue

    # -------------------------
    # Build/update core
    # -------------------------

    def _do_clear(self) -> None:
        """Clear all indexes and restart."""
        with self._lock:
            try:
                if self.persist_dir.exists():
                    shutil.rmtree(self.persist_dir, ignore_errors=True)
            except OSError:
                pass

            self._client = None
            self._collection = None
            self._embedder = None
            self._fts_enabled = False

            self.persist_dir.mkdir(parents=True, exist_ok=True)
            self._manifest_path = self.persist_dir / MANIFEST_NAME
            self._fts_path = self.persist_dir / FTS_DB_NAME

            self._manifest = {
                "version": MANIFEST_VERSION,
                "root_dir": "",
                "extensions": [],
                "files": {},
            }
            self._save_manifest()

        self._ensure_chroma(load_embedder=False)
        self._ensure_fts()

        pe = get_persistence()
        root_str = pe.get_fact("rag.root_dir")
        exts_str = pe.get_fact("rag.extensions")
        root = Path(root_str).resolve() if root_str else _default_repo_root()
        exts = (
            [e.strip().lower() for e in str(exts_str).split(",") if e.strip()] if exts_str else list(DEFAULT_EXTENSIONS)
        )

        with self._cv:
            self._build_requested = (root, exts)
            self._cv.notify_all()

    def _do_build(self, root: Path, exts: list[str]) -> None:
        """Full index build."""
        root = root.resolve()
        extset = set([e.lower() for e in exts])

        with self._lock:
            self._manifest["version"] = MANIFEST_VERSION
            self._manifest["root_dir"] = str(root)
            self._manifest["extensions"] = list(sorted(extset))
            self._manifest.setdefault("files", {})
            self._save_manifest()

        pe = get_persistence()
        pe.set_fact("rag.build_files_done", "0")
        logger.info("RAG: build scanning %s", root)

        seen_keys: set[str] = set()
        processed = 0

        for path in self._iter_files(root, extset):
            pe.set_fact("rag.build_current_file", str(path))

            file_key, relpath = self._make_file_key(path, root)
            seen_keys.add(file_key)

            try:
                st = path.stat()
                mtime = float(st.st_mtime)
                size = int(st.st_size)
            except OSError:
                mtime, size = 0.0, 0

            with self._lock:
                prev = self._manifest.get("files", {}).get(file_key, {})

            if isinstance(prev, dict) and prev.get("mtime") == mtime and prev.get("size") == size:
                processed += 1
                pe.set_fact("rag.build_files_done", str(processed))
                continue

            txt, raw = _read_text_bytes(path)
            if txt is None or raw is None:
                processed += 1
                pe.set_fact("rag.build_files_done", str(processed))
                continue

            sha1 = _sha1_bytes(raw)
            if isinstance(prev, dict) and prev.get("sha1") == sha1:
                with self._lock:
                    self._manifest["files"][file_key] = {
                        **prev,
                        "mtime": mtime,
                        "size": size,
                        "abspath": str(path.resolve()),
                        "relpath": relpath,
                    }
                    self._save_manifest()
                processed += 1
                pe.set_fact("rag.build_files_done", str(processed))
                continue

            self._index_one_file(path, root, file_key, relpath, txt, raw, (mtime, size))
            processed += 1
            pe.set_fact("rag.build_files_done", str(processed))

        # prune deleted
        to_remove: list[str] = []
        with self._lock:
            for fk in list(self._manifest.get("files", {}).keys()):
                if fk not in seen_keys:
                    to_remove.append(fk)

        for fk in to_remove:
            self._delete_file_chunks(file_key=fk)
            self._fts_delete_file(file_key=fk)
            with self._lock:
                self._manifest["files"].pop(fk, None)
                self._save_manifest()

        logger.info("RAG: build finished. processed=%d pruned=%d", processed, len(to_remove))

    def _do_update_one(self, file_key: str, abspath: str) -> None:
        """Incremental update of a single file."""
        pe = get_persistence()
        pe.set_fact("rag.last_update_ts", _now_iso())

        p = Path(abspath).resolve()
        root_str = pe.get_fact("rag.root_dir")
        root = Path(root_str).resolve() if root_str else _default_repo_root()

        if not p.exists() or not p.is_file():
            self._delete_file_chunks(file_key=file_key)
            self._fts_delete_file(file_key=file_key)
            with self._lock:
                self._manifest.get("files", {}).pop(file_key, None)
                self._save_manifest()
            pe.set_fact("rag.last_update_action", "delete")
            return

        txt, raw = _read_text_bytes(p)
        if txt is None or raw is None:
            pe.set_fact("rag.last_update_action", "skip_unreadable")
            return

        sha1 = _sha1_bytes(raw)
        try:
            st = p.stat()
            mtime = float(st.st_mtime)
            size = int(st.st_size)
        except OSError:
            mtime, size = 0.0, len(raw)

        with self._lock:
            prev = self._manifest.get("files", {}).get(file_key, {})
        if isinstance(prev, dict) and prev.get("sha1") == sha1:
            with self._lock:
                self._manifest["files"][file_key] = {**prev, "mtime": mtime, "size": size, "abspath": str(p.resolve())}
                self._save_manifest()
            pe.set_fact("rag.last_update_action", "skip_unchanged")
            return

        _, relpath = self._make_file_key(p, root)
        self._index_one_file(p, root, file_key, relpath, txt, raw, (mtime, size))
        pe.set_fact("rag.last_update_action", "upsert")

    # -------------------------
    # Indexing / storage operations
    # -------------------------

    def _ensure_chroma(self, load_embedder: bool) -> None:
        """Ensure Chroma collection exists and embedder is loaded if requested."""
        with self._lock:
            if self._collection is None:
                self.persist_dir.mkdir(parents=True, exist_ok=True)
                self._client, self._collection = _make_chroma_collection(
                    persist_dir=str(self.persist_dir),
                    collection_name=self.collection_name,
                )
        if load_embedder and self._embedder is None:
            emb = _load_embedder(self.model_name)
            with self._lock:
                self._embedder = emb

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for texts."""
        if self._embedder is None:
            self._ensure_chroma(load_embedder=True)
        assert self._embedder is not None
        with self._embed_lock:
            arr = self._embedder.encode(texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True)
        return [list(map(float, row)) for row in arr]

    def _delete_file_chunks(self, file_key: str) -> None:
        """Delete all chunks for a file from Chroma."""
        self._ensure_chroma(load_embedder=False)
        with self._lock:
            if self._collection is None:
                return
            try:
                self._collection.delete(where={"file_key": file_key})
                return
            except Exception:
                pass
            try:
                got = self._collection.get(where={"file_key": file_key}, include=["ids"])
                ids = got.get("ids") if isinstance(got, dict) else None
                if isinstance(ids, list) and ids:
                    self._collection.delete(ids=ids)
            except Exception:
                return

    def _index_one_file(
        self,
        path: Path,
        root: Path,
        file_key: str,
        relpath: str,
        text: str,
        raw: bytes,
        stat: tuple[float, int],
    ) -> None:
        """Index a single file into both semantic and lexical indexes."""
        chunks = _chunk_by_type(path, text)
        if not chunks:
            return

        sha1 = _sha1_bytes(raw)
        mtime, size = stat
        ext = path.suffix.lower()
        abspath = str(path.resolve())
        relpath = relpath or ""

        # keep clean
        self._delete_file_chunks(file_key=file_key)
        self._fts_delete_file(file_key=file_key)

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []
        fts_rows: list[tuple[str, str, str, str, int, int, str, str, str]] = []

        for c in chunks:
            cid = _sha1_str(f"{file_key}:{c.index}")
            ids.append(cid)
            documents.append(c.text)

            metadatas.append(
                {
                    "chunk_id": cid,
                    "file_key": file_key,
                    "relpath": relpath,
                    "abspath": abspath,
                    "ext": ext,
                    "start_line": int(c.start_line),
                    "end_line": int(c.end_line),
                    "chunk_index": int(c.index),
                    "file_sha1": sha1,
                    "file_mtime": float(mtime),
                    "file_size": int(size),
                    "title": c.title or "",
                    "kind": c.kind or "",
                    "symbol": c.symbol or "",
                }
            )

            # Include title/symbol in lexical index too
            lex_text = c.text
            if c.title:
                lex_text = f"{c.title}\n{lex_text}"
            fts_rows.append(
                (
                    cid,
                    file_key,
                    relpath,
                    ext,
                    int(c.start_line),
                    int(c.end_line),
                    c.kind or "",
                    c.symbol or "",
                    lex_text,
                )
            )

        # lexical first
        self._fts_upsert_chunks(fts_rows)

        # semantic
        self._ensure_chroma(load_embedder=True)
        embeddings = self._embed(documents)

        with self._lock:
            if self._collection is None:
                return
            self._collection.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)

            self._manifest.setdefault("files", {})
            self._manifest["files"][file_key] = {
                "sha1": sha1,
                "mtime": float(mtime),
                "size": int(size),
                "ext": ext,
                "chunks": len(chunks),
                "abspath": abspath,
                "relpath": relpath,
                "indexed_ts": _now_iso(),
            }
            self._save_manifest()

    def _make_file_key(self, path: Path, root: Path) -> tuple[str, str]:
        """Create a file key (relative path or fallback to abs path)."""
        relpath = ""
        try:
            relpath = str(path.resolve().relative_to(root.resolve()))
        except ValueError:
            relpath = ""
        relpath = _normalize_relpath(relpath)
        file_key = relpath if relpath else str(path.resolve())
        return file_key, relpath

    def _iter_files(self, root: Path, extset: set) -> Iterable[Path]:
        """Walk root directory, yielding files matching extensions."""
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in DEFAULT_SKIP_DIRS and not d.startswith(".")]
            for fn in filenames:
                p = Path(dirpath) / fn
                if p.suffix.lower() not in extset:
                    continue
                if "thomas_rag_index" in p.parts:
                    continue
                yield p

    def _load_manifest(self) -> None:
        """Load manifest from disk."""
        with self._lock:
            if self._manifest_path.exists():
                m = _safe_json_load(self._manifest_path)
                if isinstance(m, dict) and m.get("version") == MANIFEST_VERSION:
                    m.setdefault("files", {})
                    self._manifest = m
                    return
            self._manifest = {"version": MANIFEST_VERSION, "root_dir": "", "extensions": [], "files": {}}

    def _save_manifest(self) -> None:
        """Save manifest to disk."""
        try:
            self.persist_dir.mkdir(parents=True, exist_ok=True)
            _safe_json_dump(self._manifest_path, self._manifest)
        except OSError as e:
            logger.debug("RAG: manifest write failed: %s", e)

    # -------------------------
    # FTS (lexical) index operations
    # -------------------------

    def _ensure_fts(self) -> None:
        """Ensure FTS5 database is initialized."""
        self._fts_enabled = ensure_fts_impl(self._fts_path)
        if not self._fts_enabled:
            logger.debug("RAG: FTS disabled")

    def _fts_delete_file(self, file_key: str) -> None:
        """Delete all FTS chunks for a file."""
        if self._fts_enabled:
            fts_delete_file_impl(self._fts_path, file_key)

    def _fts_upsert_chunks(self, rows: list[tuple[str, str, str, int, int, str, str, str]]) -> None:
        """Insert chunks into FTS index."""
        if self._fts_enabled:
            fts_upsert_chunks_impl(self._fts_path, rows)

    def _fts_search(self, spec: _QuerySpec, n: int, ext: str | None) -> list[dict[str, Any]]:
        """Full-text search in FTS index."""
        if not self._fts_enabled:
            return []
        return fts_search_impl(self._fts_path, spec, n, ext)

    # -------------------------
    # Chroma (semantic) search
    # -------------------------

    def _chroma_search(self, query: str, n: int, ext: str | None) -> list[dict[str, Any]]:
        """Semantic search using embeddings."""
        self._ensure_chroma(load_embedder=True)
        with self._lock:
            if self._collection is None:
                return []
            return chroma_search_impl(self._collection, self._embed, query, n, ext)

    # -------------------------
    # Regex "grep" mode
    # -------------------------

    def _regex_search(self, spec: _QuerySpec, k: int, ext: str | None) -> list[dict[str, Any]]:
        """Fast grep: scan candidate files and return matches with context."""
        root_str = self._get_root_dir()
        return regex_search_impl(spec, k, ext, self._manifest, self._iter_files, root_str)

    def _get_root_dir(self) -> str:
        """Get root directory from persistence or manifest."""
        pe = get_persistence()
        return pe.get_fact("rag.root_dir") or self._manifest.get("root_dir") or str(_default_repo_root())


# -------------------------
# Singleton accessor
# -------------------------

_RAG_SINGLETON: RagIndex | None = None
_RAG_LOCK = threading.Lock()


def get_rag_index() -> RagIndex:
    """Get or create the RAG index singleton.

    Initializes instantly, builds in background if empty.
    """
    global _RAG_SINGLETON
    with _RAG_LOCK:
        if _RAG_SINGLETON is None:
            _RAG_SINGLETON = RagIndex()

            pe = get_persistence()
            root_str = pe.get_fact("rag.root_dir") or str(_default_repo_root())
            exts_str = pe.get_fact("rag.extensions")
            exts = (
                [e.strip().lower() for e in str(exts_str).split(",") if e.strip()]
                if exts_str
                else list(DEFAULT_EXTENSIONS)
            )

            # auto-build if empty
            try:
                _RAG_SINGLETON._ensure_chroma(load_embedder=False)
                with _RAG_SINGLETON._lock:
                    count = int(_RAG_SINGLETON._collection.count()) if _RAG_SINGLETON._collection else 0
                if count == 0:
                    _RAG_SINGLETON.build(root_str, extensions=exts)
            except Exception:
                logger.debug("RAG: unable to count collection; skipping auto-build.")

    return _RAG_SINGLETON
