"""
thomas/core/rag_index.py

FEATURE 2 — FULL-REPO RAG INDEX (delight edition)

Meets original requirements:
- RagIndex
- sentence-transformers (all-MiniLM-L6-v2) embeddings + Chroma persistent store
- Persist dir: ./thomas_rag_index/
- build(root_dir, extensions=...) runs in a thread (non-blocking startup)
- update(filepath) re-indexes a single file (call from loop.py after writes)
- search(query, k=5, filter_ext=None) -> [{"file": path#Lx-Ly, "chunk": text, "score": float}]
- clear() wipe and rebuild
- get_rag_index() singleton loads instantly, builds in background if missing/empty

Meaningful, consumer-loved upgrades:
1) Hybrid search: Semantic (Chroma) + Lexical (SQLite FTS5) fused with RRF.
2) Query operators INSIDE the query string (no schema changes):
     - path:thomas/tools
     - file:rag_index.py
     - ext:.py   (or ext:py)
     - symbol:ToolRegistry
     - kind:function|class
     - phrase:"exact phrase"
     - regex:/pattern/   (fast-ish grep over candidate files)
   These dramatically improve “I know what I want” searches.
3) Preview snippets with LINE NUMBERS + light highlighting:
   Consumers want answers they can act on immediately, not a blob.
   search() returns chunk text formatted as a snippet with line numbers when possible.
4) Smarter chunking:
   - Python: AST function/class blocks + symbol metadata
   - Markdown: heading blocks + heading metadata
   - Fallback: 400 whitespace-token chunks w/ overlap
5) One background worker thread; debounced updates; incremental builds; deleted-file pruning.

Design philosophy: strong defaults, minimal knobs, no fragile magic.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import threading
import time
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from thomas.core.persistence import get_persistence

logger = logging.getLogger(__name__)

DEFAULT_INDEX_DIR = Path("./thomas_rag_index").resolve()
DEFAULT_MODEL_NAME = "all-MiniLM-L6-v2"
DEFAULT_COLLECTION = "thomas_repo"
DEFAULT_EXTENSIONS = [".py", ".md", ".toml", ".txt"]

DEFAULT_SKIP_DIRS = {
    ".git", ".hg", ".svn",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".venv", "venv", "env",
    "node_modules",
    "dist", "build",
    "coverage",
    "runtime",
    "thomas_rag_index",
}

MAX_FILE_BYTES = 5_000_000
TOKENS_PER_CHUNK = 400
OVERLAP_TOKENS = 80
DEFAULT_UPDATE_DEBOUNCE_S = 0.30

MANIFEST_VERSION = 3
MANIFEST_NAME = "manifest.json"
FTS_DB_NAME = "rag_fts.sqlite3"

_TOKEN_RE = re.compile(r"\S+")
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

# Query operators: keep it simple and robust
_OP_RE = re.compile(r"""
    (?P<op>\bpath:|\bfile:|\bext:|\bsymbol:|\bkind:|\bphrase:|\bregex:)
""", re.VERBOSE)

_REGEX_LITERAL_RE = re.compile(r"^/(.*)/$")

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Chunk:
    text: str
    start_char: int
    end_char: int
    start_line: int
    end_line: int
    index: int
    title: str = ""          # e.g. "function foo" or "### Heading"
    kind: str = ""           # function|class|heading|chunk
    symbol: str = ""         # name if applicable


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha1_bytes(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def _sha1_str(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()


def _newline_positions(text: str) -> List[int]:
    return [m.start() for m in re.finditer(r"\n", text)]


def _line_for_offset(newlines: List[int], offset: int) -> int:
    return bisect_right(newlines, offset) + 1


def _distance_to_score(dist: Any) -> float:
    try:
        d = float(dist)
    except Exception:
        return 0.0
    if 0.0 <= d <= 2.0:
        return max(0.0, min(1.0, 1.0 - d))
    return 1.0 / (1.0 + max(0.0, d))


def _default_repo_root() -> Path:
    here = Path(__file__).resolve()
    return here.parents[2]


def _normalize_ext_list(extensions: List[str]) -> List[str]:
    exts = [e if e.startswith(".") else f".{e}" for e in (extensions or DEFAULT_EXTENSIONS)]
    return [e.lower() for e in exts]


def _normalize_relpath(rel: str) -> str:
    return rel.replace("\\", "/") if rel else ""


def _safe_json_load(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _safe_json_dump(path: Path, data: Dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _read_text_bytes(path: Path, max_bytes: int = MAX_FILE_BYTES) -> Tuple[Optional[str], Optional[bytes]]:
    try:
        data = path.read_bytes()
    except Exception:
        return None, None
    if len(data) > max_bytes:
        data = data[:max_bytes]
    if b"\x00" in data:
        return None, None
    try:
        return data.decode("utf-8"), data
    except UnicodeDecodeError:
        try:
            return data.decode("latin-1"), data
        except Exception:
            return None, None


# ---------------------------
# Chunking
# ---------------------------

def _chunk_text_whitespace_tokens(text: str) -> List[_Chunk]:
    text = text or ""
    if not text.strip():
        return []
    spans = [(m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]
    if not spans:
        return []
    newlines = _newline_positions(text)
    step = max(1, TOKENS_PER_CHUNK - OVERLAP_TOKENS)

    chunks: List[_Chunk] = []
    idx = 0
    chunk_i = 0
    n = len(spans)

    while idx < n:
        end_idx = min(n, idx + TOKENS_PER_CHUNK)
        start_char = spans[idx][0]
        end_char = spans[end_idx - 1][1]
        chunk_text = text[start_char:end_char].strip()
        if chunk_text:
            chunks.append(_Chunk(
                text=chunk_text,
                start_char=start_char,
                end_char=end_char,
                start_line=_line_for_offset(newlines, start_char),
                end_line=_line_for_offset(newlines, end_char),
                index=chunk_i,
                title="",
                kind="chunk",
                symbol="",
            ))
            chunk_i += 1
        if end_idx >= n:
            break
        idx += step
    return chunks


def _chunk_python_ast(text: str) -> Optional[List[_Chunk]]:
    try:
        tree = ast.parse(text)
    except Exception:
        return None

    lines = text.splitlines(True)
    newlines = _newline_positions(text)

    def line_to_char(line_no: int) -> int:
        return sum(len(lines[i]) for i in range(max(0, line_no - 1)))

    blocks: List[_Chunk] = []
    i = 0

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not (hasattr(node, "lineno") and hasattr(node, "end_lineno")):
                continue
            sl = max(1, int(node.lineno))
            el = max(sl, int(node.end_lineno))
            start_char = line_to_char(sl)
            end_char = line_to_char(el + 1) if el < len(lines) else len(text)
            chunk_text = text[start_char:end_char].strip()
            if not chunk_text:
                continue

            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            symbol = getattr(node, "name", "") or ""
            title = f"{kind} {symbol}".strip()

            blocks.append(_Chunk(
                text=chunk_text,
                start_char=start_char,
                end_char=end_char,
                start_line=sl,
                end_line=el,
                index=i,
                title=title,
                kind=kind,
                symbol=symbol,
            ))
            i += 1

    if not blocks:
        return None

    # Re-chunk huge blocks
    final: List[_Chunk] = []
    idx = 0
    for b in blocks:
        if len(b.text) > 12000:
            subs = _chunk_text_whitespace_tokens(b.text)
            for s in subs:
                final.append(_Chunk(
                    text=s.text,
                    start_char=b.start_char + s.start_char,
                    end_char=b.start_char + s.end_char,
                    start_line=b.start_line + (s.start_line - 1),
                    end_line=b.start_line + (s.end_line - 1),
                    index=idx,
                    title=b.title,
                    kind=b.kind,
                    symbol=b.symbol,
                ))
                idx += 1
        else:
            final.append(_Chunk(b.text, b.start_char, b.end_char, b.start_line, b.end_line, idx, b.title, b.kind, b.symbol))
            idx += 1

    return final


def _chunk_markdown_headings(text: str) -> Optional[List[_Chunk]]:
    matches = list(_MD_HEADING_RE.finditer(text))
    if not matches:
        return None

    newlines = _newline_positions(text)
    chunks: List[_Chunk] = []
    positions = [m.start() for m in matches] + [len(text)]
    idx = 0

    for i, start in enumerate(positions[:-1]):
        end = positions[i + 1]
        chunk_text = text[start:end].strip()
        if not chunk_text:
            continue

        # find the heading line
        heading_line = ""
        m = _MD_HEADING_RE.search(chunk_text.splitlines(True)[0])
        if m:
            heading_line = (m.group(0) or "").strip()

        chunks.append(_Chunk(
            text=chunk_text,
            start_char=start,
            end_char=end,
            start_line=_line_for_offset(newlines, start),
            end_line=_line_for_offset(newlines, end),
            index=idx,
            title=heading_line,
            kind="heading",
            symbol=heading_line.lstrip("#").strip(),
        ))
        idx += 1

    return chunks if chunks else None


def _chunk_by_type(path: Path, text: str) -> List[_Chunk]:
    ext = path.suffix.lower()
    if ext == ".py":
        c = _chunk_python_ast(text)
        if c:
            return c
    if ext == ".md":
        c = _chunk_markdown_headings(text)
        if c:
            # re-chunk huge sections using fallback
            final: List[_Chunk] = []
            idx = 0
            for b in c:
                if len(b.text) > 16000:
                    subs = _chunk_text_whitespace_tokens(b.text)
                    for s in subs:
                        final.append(_Chunk(
                            text=s.text,
                            start_char=b.start_char + s.start_char,
                            end_char=b.start_char + s.end_char,
                            start_line=b.start_line + (s.start_line - 1),
                            end_line=b.start_line + (s.end_line - 1),
                            index=idx,
                            title=b.title,
                            kind=b.kind,
                            symbol=b.symbol,
                        ))
                        idx += 1
                else:
                    final.append(_Chunk(b.text, b.start_char, b.end_char, b.start_line, b.end_line, idx, b.title, b.kind, b.symbol))
                    idx += 1
            return final
    return _chunk_text_whitespace_tokens(text)


# ---------------------------
# Storage helpers
# ---------------------------

def _make_chroma_collection(persist_dir: str, collection_name: str):
    try:
        import chromadb
    except Exception as e:
        raise RuntimeError("chromadb is required. Install: pip install chromadb") from e

    client = chromadb.PersistentClient(path=persist_dir)
    col = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    return client, col


def _load_embedder(model_name: str):
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as e:
        raise RuntimeError("sentence-transformers required. Install: pip install sentence-transformers") from e
    return SentenceTransformer(model_name)


def _rrf_fuse(a: List[Dict[str, Any]], b: List[Dict[str, Any]], k0: int = 60) -> List[Dict[str, Any]]:
    fused: Dict[str, Dict[str, Any]] = {}

    def add(lst: List[Dict[str, Any]], weight: float):
        for r, item in enumerate(lst, start=1):
            key = item.get("id") or item.get("file") or f"r{r}"
            contrib = weight * (1.0 / (k0 + r))
            if key not in fused:
                fused[key] = dict(item)
                fused[key]["score"] = float(contrib)
            else:
                fused[key]["score"] = float(fused[key].get("score", 0.0) + contrib)

    add(a, 1.0)
    add(b, 1.0)

    out = list(fused.values())
    out.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
    return out


# ---------------------------
# Query parsing
# ---------------------------

@dataclass
class _QuerySpec:
    raw: str
    text: str                # remaining free text query
    ext: Optional[str] = None
    path_substr: Optional[str] = None
    file_substr: Optional[str] = None
    symbol: Optional[str] = None
    kind: Optional[str] = None
    phrase: Optional[str] = None
    regex: Optional[str] = None


def _parse_query(query: str) -> _QuerySpec:
    q = (query or "").strip()
    spec = _QuerySpec(raw=q, text=q)

    if not q:
        return spec

    # Extract explicit ops. We do simple regex splits instead of a full parser.
    parts = _OP_RE.split(q)
    # split gives: [before, op1, after1, op2, after2, ...]
    if len(parts) > 1:
        base = parts[0].strip()
        spec.text = base
        i = 1
        while i < len(parts) - 1:
            op = (parts[i] or "").strip().rstrip(":")
            val = (parts[i + 1] or "").strip()
            # val may include other operators; stop at the next operator start by scanning
            # but split already separated operators, so val is until next op.
            if op == "path":
                spec.path_substr = val
            elif op == "file":
                spec.file_substr = val
            elif op == "ext":
                v = val.strip()
                if v and not v.startswith("."):
                    v = f".{v}"
                spec.ext = v.lower() if v else None
            elif op == "symbol":
                spec.symbol = val
            elif op == "kind":
                spec.kind = val.lower()
            elif op == "phrase":
                # allow phrase:"..." or phrase:...
                spec.phrase = val.strip().strip('"')
            elif op == "regex":
                # allow regex:/.../ or regex:...
                m = _REGEX_LITERAL_RE.match(val)
                spec.regex = (m.group(1) if m else val)
            i += 2

    # If the remaining text contains a quoted phrase, treat it as phrase too
    if spec.phrase is None:
        m = re.search(r'"([^"]{2,})"', q)
        if m:
            spec.phrase = m.group(1)

    # If text starts with /.../ treat as regex
    if spec.regex is None:
        m = _REGEX_LITERAL_RE.match(spec.text.strip())
        if m:
            spec.regex = m.group(1)
            spec.text = ""

    spec.text = (spec.text or "").strip()
    return spec


# ---------------------------
# The index
# ---------------------------

class RagIndex:
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

        self._manifest: Dict[str, Any] = {
            "version": MANIFEST_VERSION,
            "root_dir": "",
            "extensions": [],
            "files": {},
        }

        # background worker state
        self._cv = threading.Condition()
        self._stop = False
        self._build_requested: Optional[Tuple[Path, List[str]]] = None
        self._clear_requested: bool = False
        self._build_running: bool = False
        self._pending_updates: Dict[str, Tuple[str, float]] = {}

        # quick open
        self._ensure_chroma(load_embedder=False)
        self._load_manifest()
        self._ensure_fts()

        self._worker = threading.Thread(target=self._worker_loop, name="RagIndexWorker", daemon=True)
        self._worker.start()

    # ----- API -----

    def build(self, root_dir: str, extensions: List[str] = DEFAULT_EXTENSIONS) -> None:
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
        p = Path(filepath).resolve()

        pe = get_persistence()
        exts_str = pe.get_fact("rag.extensions")
        exts = [e.strip().lower() for e in str(exts_str).split(",") if e.strip()] if exts_str else list(DEFAULT_EXTENSIONS)
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

    def search(self, query: str, k: int = 5, filter_ext: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Hybrid semantic+lexical search + query operators + snippet rendering.

        Returns a list of dicts:
          {"file": "path#Lx-Ly", "chunk": "<snippet>", "score": float}
        """
        q = (query or "").strip()
        if not q:
            return []

        try:
            k = max(1, int(k))
        except Exception:
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

        # regex mode: fast grep over candidate files (best for power users)
        if spec.regex:
            return self._regex_search(spec, k=k, ext=ext)

        # lexical: use phrase/spec.text/spec.symbol into FTS query
        lex = self._fts_search(spec, n=max(12, k * 5), ext=ext)

        # semantic: embed only free text / phrase / symbol (pick best input)
        sem: List[Dict[str, Any]] = []
        try:
            sem_query = spec.phrase or spec.symbol or spec.text or spec.raw
            sem = self._chroma_search(sem_query, n=max(12, k * 5), ext=ext)
        except Exception:
            sem = []

        # post-filter by path/file substring constraints
        def ok_path(item: Dict[str, Any]) -> bool:
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
            return [self._format_result(r) for r in fused]

        base = sem if sem else lex
        base = base[:k]
        return [self._format_result(r) for r in base]

    def clear(self) -> None:
        with self._cv:
            self._clear_requested = True
            self._cv.notify_all()

    def status(self) -> Dict[str, Any]:
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
    # Worker loop
    # -------------------------

    def _worker_loop(self) -> None:
        pe = get_persistence()

        while True:
            job_build: Optional[Tuple[Path, List[str]]] = None
            job_clear = False
            due_updates: List[Tuple[str, str]] = []

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
        with self._lock:
            try:
                if self.persist_dir.exists():
                    shutil.rmtree(self.persist_dir, ignore_errors=True)
            except Exception:
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
        exts = [e.strip().lower() for e in str(exts_str).split(",") if e.strip()] if exts_str else list(DEFAULT_EXTENSIONS)

        with self._cv:
            self._build_requested = (root, exts)
            self._cv.notify_all()

    def _do_build(self, root: Path, exts: List[str]) -> None:
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
            except Exception:
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
                    self._manifest["files"][file_key] = {**prev, "mtime": mtime, "size": size, "abspath": str(path.resolve()), "relpath": relpath}
                    self._save_manifest()
                processed += 1
                pe.set_fact("rag.build_files_done", str(processed))
                continue

            self._index_one_file(path, root, file_key, relpath, txt, raw, (mtime, size))
            processed += 1
            pe.set_fact("rag.build_files_done", str(processed))

        # prune deleted
        to_remove: List[str] = []
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
        except Exception:
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

    def _embed(self, texts: List[str]) -> List[List[float]]:
        if self._embedder is None:
            self._ensure_chroma(load_embedder=True)
        assert self._embedder is not None
        with self._embed_lock:
            arr = self._embedder.encode(texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True)
        return [list(map(float, row)) for row in arr]

    def _delete_file_chunks(self, file_key: str) -> None:
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
        stat: Tuple[float, int],
    ) -> None:
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

        ids: List[str] = []
        documents: List[str] = []
        metadatas: List[Dict[str, Any]] = []
        fts_rows: List[Tuple[str, str, str, str, int, int, str, str, str]] = []

        for c in chunks:
            cid = _sha1_str(f"{file_key}:{c.index}")
            ids.append(cid)
            documents.append(c.text)

            metadatas.append({
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
            })

            # Include title/symbol in lexical index too (helps exact find)
            lex_text = c.text
            if c.title:
                lex_text = f"{c.title}\n{lex_text}"
            fts_rows.append((cid, file_key, relpath, ext, int(c.start_line), int(c.end_line), c.kind or "", c.symbol or "", lex_text))

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

    def _make_file_key(self, path: Path, root: Path) -> Tuple[str, str]:
        relpath = ""
        try:
            relpath = str(path.resolve().relative_to(root.resolve()))
        except Exception:
            relpath = ""
        relpath = _normalize_relpath(relpath)
        file_key = relpath if relpath else str(path.resolve())
        return file_key, relpath

    def _iter_files(self, root: Path, extset: set) -> Iterable[Path]:
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
        with self._lock:
            if self._manifest_path.exists():
                m = _safe_json_load(self._manifest_path)
                if isinstance(m, dict) and m.get("version") == MANIFEST_VERSION:
                    m.setdefault("files", {})
                    self._manifest = m
                    return
            self._manifest = {"version": MANIFEST_VERSION, "root_dir": "", "extensions": [], "files": {}}

    def _save_manifest(self) -> None:
        try:
            self.persist_dir.mkdir(parents=True, exist_ok=True)
            _safe_json_dump(self._manifest_path, self._manifest)
        except Exception as e:
            logger.debug("RAG: manifest write failed: %s", e)

    # -------------------------
    # FTS (lexical) index
    # -------------------------

    def _ensure_fts(self) -> None:
        try:
            self.persist_dir.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._fts_path))
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
                conn.execute("PRAGMA synchronous=NORMAL;")
                conn.execute("PRAGMA temp_store=MEMORY;")
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts
                    USING fts5(
                        id UNINDEXED,
                        file_key UNINDEXED,
                        relpath UNINDEXED,
                        ext UNINDEXED,
                        start_line UNINDEXED,
                        end_line UNINDEXED,
                        kind UNINDEXED,
                        symbol UNINDEXED,
                        text,
                        tokenize='unicode61'
                    );
                """)
                conn.commit()
                self._fts_enabled = True
            finally:
                conn.close()
        except Exception as e:
            self._fts_enabled = False
            logger.debug("RAG: FTS disabled (%s)", e)

    def _fts_delete_file(self, file_key: str) -> None:
        if not self._fts_enabled:
            return
        try:
            conn = sqlite3.connect(str(self._fts_path))
            try:
                conn.execute("DELETE FROM chunks_fts WHERE file_key = ?", (file_key,))
                conn.commit()
            finally:
                conn.close()
        except Exception:
            return

    def _fts_upsert_chunks(self, rows: List[Tuple[str, str, str, str, int, int, str, str, str]]) -> None:
        if not self._fts_enabled:
            return
        try:
            conn = sqlite3.connect(str(self._fts_path))
            try:
                conn.executemany(
                    "INSERT INTO chunks_fts (id, file_key, relpath, ext, start_line, end_line, kind, symbol, text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            return

    def _fts_search(self, spec: _QuerySpec, n: int, ext: Optional[str]) -> List[Dict[str, Any]]:
        if not self._fts_enabled:
            return []

        q = spec.phrase or spec.symbol or spec.text or spec.raw
        q = (q or "").strip()
        if not q:
            return []

        # Build MATCH query:
        # - preserve quoted phrase if present
        # - else AND terms
        if '"' in q:
            match = q
        else:
            terms = [t for t in re.findall(r"[A-Za-z0-9_./-]+", q) if t]
            if not terms:
                return []
            match = " AND ".join(terms[:16])

        sql = "SELECT id, relpath, ext, start_line, end_line, kind, symbol, text, bm25(chunks_fts) as rank FROM chunks_fts WHERE chunks_fts MATCH ?"
        params: List[Any] = [match]

        if ext:
            sql += " AND ext = ?"
            params.append(ext)

        # kind/symbol filters:
        if spec.kind:
            sql += " AND kind = ?"
            params.append(spec.kind)
        if spec.symbol:
            # not indexed, but stored; allow exact-ish filter
            sql += " AND symbol LIKE ?"
            params.append(f"%{spec.symbol}%")

        sql += " ORDER BY rank LIMIT ?"
        params.append(int(n))

        out: List[Dict[str, Any]] = []
        try:
            conn = sqlite3.connect(str(self._fts_path))
            try:
                cur = conn.execute(sql, tuple(params))
                for (cid, relpath, extv, sl, el, kind, symbol, textv, rank) in cur.fetchall():
                    relpath = relpath or "unknown"
                    try:
                        r = float(rank)
                    except Exception:
                        r = 10.0
                    score = 1.0 / (1.0 + max(0.0, r))
                    out.append({
                        "id": str(cid),
                        "relpath": str(relpath),
                        "ext": str(extv),
                        "start_line": int(sl),
                        "end_line": int(el),
                        "kind": str(kind or ""),
                        "symbol": str(symbol or ""),
                        "chunk": str(textv),
                        "score": float(score),
                    })
            finally:
                conn.close()
        except Exception:
            return []

        out.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
        return out

    # -------------------------
    # Chroma (semantic) search
    # -------------------------

    def _chroma_search(self, query: str, n: int, ext: Optional[str]) -> List[Dict[str, Any]]:
        self._ensure_chroma(load_embedder=True)
        where = {"ext": ext} if ext else None

        with self._lock:
            if self._collection is None:
                return []
            q_emb = self._embed([query])[0]
            res = self._collection.query(
                query_embeddings=[q_emb],
                n_results=n,
                where=where,
                include=["documents", "metadatas", "distances"],
            )

        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]

        out: List[Dict[str, Any]] = []
        for doc, meta, dist in zip(docs, metas, dists):
            if not doc or not meta:
                continue
            out.append({
                "id": meta.get("chunk_id") or meta.get("file_key"),
                "relpath": meta.get("relpath") or meta.get("abspath") or meta.get("file_key") or "unknown",
                "ext": meta.get("ext") or "",
                "start_line": meta.get("start_line"),
                "end_line": meta.get("end_line"),
                "kind": meta.get("kind") or "",
                "symbol": meta.get("symbol") or "",
                "title": meta.get("title") or "",
                "chunk": doc,
                "score": float(_distance_to_score(dist)),
            })

        out.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
        return out

    # -------------------------
    # Regex “grep” mode (consumer power)
    # -------------------------

    def _regex_search(self, spec: _QuerySpec, k: int, ext: Optional[str]) -> List[Dict[str, Any]]:
        """
        Fast-ish grep: scan candidate files and return first k line-range hits with context.
        """
        pe = get_persistence()
        root_str = pe.get_fact("rag.root_dir") or self._manifest.get("root_dir") or str(_default_repo_root())
        root = Path(root_str).resolve()

        # candidate extensions
        if ext:
            extset = {ext}
        else:
            exts_str = pe.get_fact("rag.extensions")
            extset = set([e.strip().lower() for e in str(exts_str).split(",") if e.strip()]) if exts_str else set(DEFAULT_EXTENSIONS)

        pat = spec.regex or ""
        try:
            rx = re.compile(pat, re.IGNORECASE)
        except Exception:
            # treat as literal
            rx = re.compile(re.escape(pat), re.IGNORECASE)

        results: List[Dict[str, Any]] = []
        # prioritize files mentioned by path/file ops if any by scanning manifest first
        files = []
        with self._lock:
            for fk, info in (self._manifest.get("files") or {}).items():
                rel = (info.get("relpath") or fk or "")
                e = (info.get("ext") or "")
                if e and e.lower() not in extset:
                    continue
                if spec.path_substr and spec.path_substr.lower() not in rel.lower():
                    continue
                if spec.file_substr and spec.file_substr.lower() not in rel.lower():
                    continue
                files.append((rel, info.get("abspath")))

        # fallback: if manifest empty, walk filesystem
        if not files:
            for p in self._iter_files(root, extset):
                files.append((str(p.relative_to(root)).replace("\\", "/"), str(p)))

        for rel, abspath in files:
            if len(results) >= k:
                break
            if not abspath:
                continue
            p = Path(abspath)
            txt, _raw = _read_text_bytes(p)
            if txt is None:
                continue
            lines = txt.splitlines()
            # find first match line(s)
            for i, line in enumerate(lines, start=1):
                if rx.search(line):
                    sl = max(1, i - 2)
                    el = min(len(lines), i + 2)
                    snippet = self._render_snippet(lines, sl, el, highlight_terms=[pat])
                    results.append({
                        "file": f"{_normalize_relpath(rel)}#L{sl}-L{el}",
                        "chunk": snippet,
                        "score": 1.0,  # regex hits are “hard hits”
                        "relpath": _normalize_relpath(rel),
                        "start_line": sl,
                        "end_line": el,
                        "kind": "",
                        "symbol": "",
                        "id": _sha1_str(f"regex:{rel}:{i}:{pat}"),
                    })
                    break

        return results

    # -------------------------
    # Result formatting (snippets)
    # -------------------------

    def _format_result(self, r: Dict[str, Any]) -> Dict[str, Any]:
        rel = r.get("relpath") or r.get("file") or "unknown"
        sl = r.get("start_line")
        el = r.get("end_line")
        file_with_lines = f"{rel}#L{sl}-L{el}" if isinstance(sl, int) and isinstance(el, int) else str(rel)

        # render snippet with line numbers if we can read the file
        snippet = r.get("chunk") or ""
        snippet = self._maybe_render_from_disk(relpath=str(rel), start_line=sl, end_line=el, fallback=str(snippet))

        # add a tiny header for kind/symbol if it exists (humans love this)
        header_bits = []
        if r.get("kind"):
            header_bits.append(str(r.get("kind")))
        if r.get("symbol"):
            header_bits.append(str(r.get("symbol")))
        if r.get("title") and str(r.get("title")).strip():
            # avoid duplicating function name
            t = str(r.get("title")).strip()
            if t.lower() not in " ".join(header_bits).lower():
                header_bits.append(t)
        if header_bits:
            header = " • ".join(header_bits)
            snippet = f"[{header}]\n{snippet}"

        return {"file": file_with_lines, "chunk": snippet, "score": float(r.get("score", 0.0))}

    def _maybe_render_from_disk(self, relpath: str, start_line: Any, end_line: Any, fallback: str) -> str:
        if not isinstance(start_line, int) or not isinstance(end_line, int):
            return fallback

        pe = get_persistence()
        root_str = pe.get_fact("rag.root_dir") or self._manifest.get("root_dir")
        if not root_str:
            return fallback
        root = Path(str(root_str)).resolve()

        # relpath might already include #L...
        rel = str(relpath).split("#", 1)[0]
        p = root / rel
        if not p.exists():
            return fallback

        txt, _ = _read_text_bytes(p)
        if txt is None:
            return fallback

        lines = txt.splitlines()
        sl = max(1, start_line - 2)
        el = min(len(lines), end_line + 2)
        return self._render_snippet(lines, sl, el, highlight_terms=[])

    def _render_snippet(self, lines: List[str], sl: int, el: int, highlight_terms: List[str]) -> str:
        """
        Render a line-numbered snippet. Highlight_terms is best-effort.
        """
        width = len(str(el))
        out_lines = []
        for ln in range(sl, el + 1):
            s = lines[ln - 1]
            # lightweight highlight (avoid heavy ANSI; keep plain text)
            for term in highlight_terms:
                t = term.strip()
                if not t:
                    continue
                # mark term with brackets if present (case-insensitive)
                try:
                    s = re.sub(re.escape(t), lambda m: f"[{m.group(0)}]", s, flags=re.IGNORECASE)
                except Exception:
                    pass
            out_lines.append(f"{str(ln).rjust(width)} | {s}")
        return "\n".join(out_lines)

# -------------------------
# Singleton accessor
# -------------------------

_RAG_SINGLETON: Optional[RagIndex] = None
_RAG_LOCK = threading.Lock()


def get_rag_index() -> RagIndex:
    global _RAG_SINGLETON
    with _RAG_LOCK:
        if _RAG_SINGLETON is None:
            _RAG_SINGLETON = RagIndex()

            pe = get_persistence()
            root_str = pe.get_fact("rag.root_dir") or str(_default_repo_root())
            exts_str = pe.get_fact("rag.extensions")
            exts = [e.strip().lower() for e in str(exts_str).split(",") if e.strip()] if exts_str else list(DEFAULT_EXTENSIONS)

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
