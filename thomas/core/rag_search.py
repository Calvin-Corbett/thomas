"""Search and retrieval operations for RAG index.

Provides semantic search (Chroma), lexical search (FTS5), and hybrid search with RRF.
Includes query parsing with advanced operators (path:, file:, ext:, symbol:, kind:, phrase:, regex:).
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Tuple

logger = logging.getLogger(__name__)

DEFAULT_EXTENSIONS = [".py", ".md", ".toml", ".txt"]

# Query operators
_OP_RE = re.compile(
    r"""
    (?P<op>\bpath:|\bfile:|\bext:|\bsymbol:|\bkind:|\bphrase:|\bregex:)
""",
    re.VERBOSE,
)

_REGEX_LITERAL_RE = re.compile(r"^/(.*)/$")


@dataclass
class _QuerySpec:
    """Parsed query specification with operators extracted."""

    raw: str
    text: str  # remaining free text query
    ext: str | None = None
    path_substr: str | None = None
    file_substr: str | None = None
    symbol: str | None = None
    kind: str | None = None
    phrase: str | None = None
    regex: str | None = None


def _distance_to_score(dist: Any) -> float:
    """Convert Chroma distance to [0, 1] score.

    Chroma uses cosine distance; smaller distance = higher relevance.
    """
    try:
        d = float(dist)
    except (TypeError, ValueError):
        return 0.0
    if 0.0 <= d <= 2.0:
        return max(0.0, min(1.0, 1.0 - d))
    return 1.0 / (1.0 + max(0.0, d))


def _parse_query(query: str) -> _QuerySpec:
    """Parse query string into _QuerySpec with extracted operators.

    Supported operators:
    - path:substring     - filter by path substring
    - file:substring     - filter by filename substring
    - ext:.py            - filter by file extension
    - symbol:name        - filter by symbol name
    - kind:function      - filter by chunk kind (function|class|heading|chunk)
    - phrase:"exact"     - exact phrase search
    - regex:/pattern/    - regex pattern search
    - Free text          - semantic and full-text search
    """
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
                spec.regex = m.group(1) if m else val
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


def _distance_to_score(dist: Any) -> float:
    """Convert Chroma distance to [0, 1] score.

    Chroma uses cosine distance; smaller distance = higher relevance.
    """
    try:
        d = float(dist)
    except (TypeError, ValueError):
        return 0.0
    if 0.0 <= d <= 2.0:
        return max(0.0, min(1.0, 1.0 - d))
    return 1.0 / (1.0 + max(0.0, d))


class SearchOperations:
    """Encapsulates search logic for the RAG index.

    Used by RagIndex to perform semantic, lexical, and hybrid searches.
    """

    @staticmethod
    def _distance_to_score_impl(dist: Any) -> float:
        """Convert Chroma distance to [0, 1] score.

        Chroma uses cosine distance; smaller distance = higher relevance.
        """
        try:
            d = float(dist)
        except (TypeError, ValueError):
            return 0.0
        if 0.0 <= d <= 2.0:
            return max(0.0, min(1.0, 1.0 - d))
        return 1.0 / (1.0 + max(0.0, d))

    @staticmethod
    def fts_search(
        fts_path: Path,
        spec: _QuerySpec,
        n: int,
        ext: str | None,
    ) -> list[dict[str, Any]]:
        """Full-text search using SQLite FTS5.

        Applies keyword matching, filters by metadata (ext, path, kind, symbol).
        Returns scored results ranked by relevance.
        """
        if not fts_path.exists():
            return []

        try:
            conn = sqlite3.connect(str(fts_path))
            conn.row_factory = sqlite3.Row
            c = conn.cursor()

            # Build query
            where_clauses = ["fts_chunks.rowid IN (SELECT rowid FROM fts_idx WHERE fts_idx MATCH ?)"]
            params: list[Any] = []

            if spec.text:
                params.append(spec.text)
            else:
                params.append("*")

            if ext:
                where_clauses.append("chunks.ext = ?")
                params.append(ext)

            if spec.ext:
                where_clauses.append("chunks.ext = ?")
                params.append(spec.ext)

            if spec.path_substr:
                where_clauses.append("chunks.file_key LIKE ?")
                params.append(f"%{spec.path_substr}%")

            if spec.file_substr:
                where_clauses.append("chunks.file_path LIKE ?")
                params.append(f"%{spec.file_substr}%")

            if spec.kind:
                where_clauses.append("chunks.kind = ?")
                params.append(spec.kind)

            if spec.symbol:
                where_clauses.append("chunks.symbol LIKE ?")
                params.append(f"%{spec.symbol}%")

            where_clause = " AND ".join(where_clauses)
            sql = f"""
            SELECT chunks.file_key, chunks.file_path, chunks.chunk_id,
                   chunks.text, chunks.kind, chunks.symbol, chunks.title,
                   chunks.start_line, chunks.end_line,
                   rank AS score
            FROM fts_chunks
            JOIN chunks ON fts_chunks.chunk_id = chunks.chunk_id
            WHERE {where_clause}
            ORDER BY rank
            LIMIT ?
            """
            params.append(n)

            rows = c.execute(sql, params).fetchall()
            results = [dict(row) for row in rows]
            conn.close()
            return results
        except sqlite3.Error as e:
            logger.debug("FTS search error: %s", e)
            return []

    @staticmethod
    def chroma_search(
        collection: Any,
        query_embedding: list[float],
        query: str,
        n: int,
        ext: str | None,
    ) -> list[dict[str, Any]]:
        """Semantic search using Chroma and vector similarity.

        Searches via embedding vectors, applies metadata filters.
        Returns scored results ranked by cosine similarity.
        """
        try:
            where_filter = {}
            if ext:
                where_filter["ext"] = {"$eq": ext}

            results_raw = collection.query(
                query_embeddings=[query_embedding],
                n_results=n,
                where=where_filter if where_filter else None,
                include=["metadatas", "distances", "embeddings"],
            )

            if not results_raw or not results_raw.get("ids"):
                return []

            ids = results_raw.get("ids", [[]])[0]
            distances = results_raw.get("distances", [[]])[0]
            metadatas = results_raw.get("metadatas", [[]])[0]

            results = []
            for chunk_id, dist, meta in zip(ids, distances, metadatas):
                score = SearchOperations._distance_to_score(dist)
                result = dict(meta or {})
                result["id"] = chunk_id
                result["score"] = score
                results.append(result)

            return results
        except Exception as e:
            logger.debug("Chroma search error: %s", e)
            return []

    @staticmethod
    def regex_search(
        spec: _QuerySpec,
        k: int,
        ext: str | None,
        file_cache: dict[str, str],
        manifest: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Regex pattern search across cached file contents.

        Compiles regex, searches all cached files, extracts context windows.
        Useful for precise pattern matching and code discovery.
        """
        if not spec.regex:
            return []

        try:
            pattern = re.compile(spec.regex)
        except re.error as e:
            logger.debug("Invalid regex %s: %s", spec.regex, e)
            return []

        results = []
        seen_ids: set[str] = set()

        for file_key, content in file_cache.items():
            # Filter by extension
            if ext and not file_key.endswith(ext):
                continue
            if spec.ext and not file_key.endswith(spec.ext):
                continue

            # Filter by path
            if spec.path_substr and spec.path_substr not in file_key:
                continue

            # Search for matches
            for m in pattern.finditer(content):
                match_start = max(0, m.start() - 300)
                match_end = min(len(content), m.end() + 300)
                context = content[match_start:match_end].strip()

                start_line = content[: m.start()].count("\n") + 1
                end_line = content[: m.end()].count("\n") + 1

                chunk_id = f"{file_key}#L{start_line}-L{end_line}"
                if chunk_id in seen_ids:
                    continue
                seen_ids.add(chunk_id)

                results.append(
                    {
                        "id": chunk_id,
                        "file_key": file_key,
                        "file": f"{file_key}#L{start_line}-L{end_line}",
                        "chunk": context,
                        "score": 1.0,
                        "start_line": start_line,
                        "end_line": end_line,
                        "kind": "regex_match",
                        "title": f"Regex match: {m.group()[:80]}",
                    }
                )

                if len(results) >= k:
                    break

            if len(results) >= k:
                break

        return results[:k]


# -------------------------
# FTS Search Function
# -------------------------


def fts_search_impl(
    fts_path: Path,
    spec: _QuerySpec,
    n: int,
    ext: str | None,
) -> list[dict[str, Any]]:
    """Full-text search implementation using FTS5.

    Args:
        fts_path: Path to FTS database
        spec: Parsed query specification
        n: Number of results to return
        ext: Optional extension filter

    Returns:
        List of search results
    """
    if not fts_path.exists():
        return []

    q = spec.phrase or spec.symbol or spec.text or spec.raw
    q = (q or "").strip()
    if not q:
        return []

    # Build MATCH query
    if '"' in q:
        match = q
    else:
        terms = [t for t in re.findall(r"[A-Za-z0-9_./-]+", q) if t]
        if not terms:
            return []
        match = " AND ".join(terms[:16])

    sql = "SELECT id, relpath, ext, start_line, end_line, kind, symbol, text, bm25(chunks_fts) as rank FROM chunks_fts WHERE chunks_fts MATCH ?"
    params: list[Any] = [match]

    if ext:
        sql += " AND ext = ?"
        params.append(ext)

    if spec.kind:
        sql += " AND kind = ?"
        params.append(spec.kind)
    if spec.symbol:
        sql += " AND symbol LIKE ?"
        params.append(f"%{spec.symbol}%")

    sql += " ORDER BY rank LIMIT ?"
    params.append(int(n))

    out: list[dict[str, Any]] = []
    try:
        conn = sqlite3.connect(str(fts_path))
        try:
            cur = conn.execute(sql, tuple(params))
            for cid, relpath, extv, sl, el, kind, symbol, textv, rank in cur.fetchall():
                relpath = relpath or "unknown"
                try:
                    r = float(rank)
                except (TypeError, ValueError):
                    r = 10.0
                score = 1.0 / (1.0 + max(0.0, r))
                out.append(
                    {
                        "id": str(cid),
                        "relpath": str(relpath),
                        "ext": str(extv),
                        "start_line": int(sl),
                        "end_line": int(el),
                        "kind": str(kind or ""),
                        "symbol": str(symbol or ""),
                        "chunk": str(textv),
                        "score": float(score),
                    }
                )
        finally:
            conn.close()
    except sqlite3.Error:
        return []

    out.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
    return out


# -------------------------
# Chroma Search Function
# -------------------------

# -------------------------
# FTS Management Functions
# -------------------------


def ensure_fts_impl(fts_path: Path) -> bool:
    """Initialize FTS5 database.

    Returns:
        True if FTS was successfully enabled, False otherwise
    """
    try:
        fts_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(fts_path))
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
            return True
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def fts_delete_file_impl(fts_path: Path, file_key: str) -> None:
    """Delete all FTS chunks for a file."""
    try:
        conn = sqlite3.connect(str(fts_path))
        try:
            conn.execute("DELETE FROM chunks_fts WHERE file_key = ?", (file_key,))
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        pass


def fts_upsert_chunks_impl(
    fts_path: Path,
    rows: list[Tuple[str, str, str, str, int, int, str, str, str]],
) -> None:
    """Insert chunks into FTS index."""
    try:
        conn = sqlite3.connect(str(fts_path))
        try:
            conn.executemany(
                "INSERT INTO chunks_fts (id, file_key, relpath, ext, start_line, end_line, kind, symbol, text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        pass


# -------------------------
# Chroma Search Function
# -------------------------


def regex_search_impl(
    spec: _QuerySpec,
    k: int,
    ext: str | None,
    manifest: dict[str, Any],
    iter_files_fn: Callable[[Path, set], Iterable[Path]],
    root_dir: str,
) -> list[dict[str, Any]]:
    """Regex pattern search across files.

    Args:
        spec: Parsed query specification with regex pattern
        k: Number of results to return
        ext: Optional extension filter
        manifest: File manifest for prioritizing files
        iter_files_fn: Function to iterate files
        root_dir: Root directory for file walking

    Returns:
        List of search results
    """
    from thomas.core.rag_format import render_snippet
    from thomas.core.rag_indexer import _normalize_relpath, _read_text_bytes, _sha1_str

    root = Path(root_dir).resolve()

    # candidate extensions
    if ext:
        extset = {ext}
    else:
        extset = set(DEFAULT_EXTENSIONS)

    pat = spec.regex or ""
    try:
        rx = re.compile(pat, re.IGNORECASE)
    except re.error:
        rx = re.compile(re.escape(pat), re.IGNORECASE)

    results: list[dict[str, Any]] = []
    # prioritize files from manifest first
    files = []
    for fk, info in (manifest.get("files") or {}).items():
        rel = info.get("relpath") or fk or ""
        e = info.get("ext") or ""
        if e and e.lower() not in extset:
            continue
        if spec.path_substr and spec.path_substr.lower() not in rel.lower():
            continue
        if spec.file_substr and spec.file_substr.lower() not in rel.lower():
            continue
        files.append((rel, info.get("abspath")))

    # fallback: if manifest empty, walk filesystem
    if not files:
        for p in iter_files_fn(root, extset):
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
        for i, line in enumerate(lines, start=1):
            if rx.search(line):
                sl = max(1, i - 2)
                el = min(len(lines), i + 2)
                snippet = render_snippet(lines, sl, el, highlight_terms=[pat])
                results.append(
                    {
                        "file": f"{_normalize_relpath(rel)}#L{sl}-L{el}",
                        "chunk": snippet,
                        "score": 1.0,
                        "relpath": _normalize_relpath(rel),
                        "start_line": sl,
                        "end_line": el,
                        "kind": "",
                        "symbol": "",
                        "id": _sha1_str(f"regex:{rel}:{i}:{pat}"),
                    }
                )
                break

    return results


def chroma_search_impl(
    collection: Any,
    embed_fn: Any,
    query: str,
    n: int,
    ext: str | None,
) -> list[dict[str, Any]]:
    """Semantic search implementation using Chroma embeddings.

    Args:
        collection: Chroma collection
        embed_fn: Function to generate embeddings
        query: Search query
        n: Number of results
        ext: Optional extension filter

    Returns:
        List of search results
    """
    where = {"ext": ext} if ext else None

    try:
        q_emb = embed_fn([query])[0]
        res = collection.query(
            query_embeddings=[q_emb],
            n_results=n,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        return []

    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]

    out: list[dict[str, Any]] = []
    for doc, meta, dist in zip(docs, metas, dists):
        if not doc or not meta:
            continue
        out.append(
            {
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
            }
        )

    out.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
    return out
