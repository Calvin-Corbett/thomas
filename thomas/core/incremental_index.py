"""Incremental repo index with immediate post-edit retrieval (CAP-015).

The heavyweight :class:`thomas.core.rag_index.RagIndex` builds an embedding
store in a background thread and re-chunks a file on ``update()``. That is the
right tool for a full-repo semantic build, but it has two properties that make
it a poor fit for *proving immediacy* of a single filesystem edit:

1. its embedding backend (chromadb / sentence-transformers) is frequently not
   installed, so retrieval quietly degrades; and
2. a fresh ``update()`` re-reads from disk and re-embeds, which is neither
   deterministic nor guaranteed to be reflected synchronously in a query.

This module is the **offline-deterministic path**. :class:`IncrementalIndex`
keeps a tiny in-process lexical index keyed by path. Each entry carries a
content hash so re-indexing an unchanged file is a genuine no-op, and
:meth:`IncrementalIndex.apply_change` mutates *only* the touched entry
(add / replace / remove) rather than rebuilding. Because the mutation happens
synchronously in memory, a :meth:`IncrementalIndex.query` issued immediately
after :meth:`apply_change` observes the new content and no longer observes the
removed content -- the immediacy guarantee CAP-015 requires.

Ranking is a deterministic tf-idf-style lexical score computed over the current
index state, with ties broken by path so results never depend on dict ordering
or wall-clock time. No embeddings, no threads, no network, no disk.

Delegation: when a semantic backend *is* available, construct the index with a
``rag_index`` handle. :meth:`query` will delegate to
``RagIndex.search`` whenever that index reports live embedding vectors
(``status()['vector_count'] > 0``); otherwise it stays on this deterministic
lexical path. Incremental bookkeeping (hashes, immediacy) is always local.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "IncrementalIndex",
    "IndexEntry",
    "SearchHit",
    "VALID_EVENTS",
]

# Filesystem change events understood by :meth:`IncrementalIndex.apply_change`.
CREATED = "created"
MODIFIED = "modified"
DELETED = "deleted"
VALID_EVENTS = frozenset({CREATED, MODIFIED, DELETED})

# Token = run of word characters; identifiers are additionally split on
# underscores and camelCase boundaries so ``apply_change`` matches ``apply`` and
# ``change``. Kept intentionally simple and deterministic.
_WORD_RE = re.compile(r"[A-Za-z0-9]+")
_CAMEL_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|[0-9]+")


@runtime_checkable
class _SemanticIndex(Protocol):
    """Minimal contract for optional delegation to an embedding index."""

    def search(self, query: str, k: int = 5, filter_ext: str | None = None) -> list[dict[str, Any]]: ...

    def status(self) -> dict[str, Any]: ...


def _tokenize(text: str) -> list[str]:
    """Deterministically lowercase-tokenize, splitting identifiers into parts.

    ``"apply_change"`` -> ``["apply", "change"]`` and ``"IndexEntry"`` ->
    ``["index", "entry"]`` while the whole-word forms are preserved too, so both
    a fragment query and an exact query can match.
    """
    tokens: list[str] = []
    for word in _WORD_RE.findall(text):
        lowered = word.lower()
        tokens.append(lowered)
        parts = _CAMEL_RE.findall(word)
        for part in parts:
            low = part.lower()
            if low != lowered:
                tokens.append(low)
    return tokens


def _hash_content(content: str) -> str:
    return hashlib.sha1(content.encode("utf-8", "replace")).hexdigest()


@dataclass
class IndexEntry:
    """A single indexed file's current state."""

    path: str
    content_hash: str
    term_freq: Counter[str] = field(default_factory=Counter)
    lines: list[str] = field(default_factory=list)


@dataclass
class SearchHit:
    """A ranked retrieval result over the current index state."""

    path: str
    score: float
    snippet: str
    line: int


class IncrementalIndex:
    """In-memory incremental lexical index with immediate retrieval.

    Not thread-safe by design: the immediacy guarantee is about a synchronous
    ``apply_change`` -> ``query`` sequence on one thread. Callers needing
    concurrency should serialize access externally.
    """

    def __init__(self, rag_index: _SemanticIndex | None = None) -> None:
        self._entries: dict[str, IndexEntry] = {}
        # Document frequency per term, maintained incrementally so idf never
        # requires a full scan of the corpus.
        self._doc_freq: Counter[str] = Counter()
        self._rag_index = rag_index

    # -- introspection ----------------------------------------------------

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, path: str) -> bool:
        return path in self._entries

    def paths(self) -> list[str]:
        """Return indexed paths in deterministic sorted order."""
        return sorted(self._entries)

    def content_hash(self, path: str) -> str | None:
        entry = self._entries.get(path)
        return entry.content_hash if entry else None

    # -- indexing ---------------------------------------------------------

    def index_file(self, path: str, content: str) -> bool:
        """Index or re-index a single file.

        Returns ``True`` if the index changed, ``False`` if the file was already
        indexed with identical content (hash-guarded no-op).
        """
        new_hash = _hash_content(content)
        existing = self._entries.get(path)
        if existing is not None and existing.content_hash == new_hash:
            return False

        if existing is not None:
            self._retract(existing)

        entry = self._build_entry(path, content, new_hash)
        self._entries[path] = entry
        for term in entry.term_freq:
            self._doc_freq[term] += 1
        return True

    def index_files(self, files: dict[str, str]) -> int:
        """Index a mapping of ``path -> content``.

        Returns the number of files whose entry actually changed. Paths are
        processed in sorted order so a full (re)index is deterministic.
        """
        changed = 0
        for path in sorted(files):
            if self.index_file(path, files[path]):
                changed += 1
        return changed

    def remove_file(self, path: str) -> bool:
        """Remove a file from the index. Returns ``True`` if it was present."""
        entry = self._entries.pop(path, None)
        if entry is None:
            return False
        self._retract(entry)
        return True

    def apply_change(self, path: str, event: str, content: str | None = None) -> bool:
        """Apply one filesystem change event, updating only ``path``'s entry.

        ``event`` is one of ``created`` / ``modified`` / ``deleted``. For
        ``created`` and ``modified``, ``content`` is required and the entry is
        added or replaced incrementally. For ``deleted``, the entry is removed.

        Returns ``True`` if the index changed. The mutation is synchronous, so a
        :meth:`query` issued immediately afterward reflects it.
        """
        if event not in VALID_EVENTS:
            raise ValueError(f"unknown event {event!r}; expected one of {sorted(VALID_EVENTS)}")

        if event == DELETED:
            return self.remove_file(path)

        if content is None:
            raise ValueError(f"event {event!r} for {path!r} requires content")
        return self.index_file(path, content)

    # -- retrieval --------------------------------------------------------

    def query(self, text: str, k: int = 5, prefer_semantic: bool = True) -> list[SearchHit]:
        """Return up to ``k`` ranked hits over the *current* index state.

        Scoring is a deterministic tf-idf sum over the query's tokens; ties are
        broken by ascending path so ranking never depends on insertion order.

        When a delegating ``rag_index`` with live embeddings was supplied and
        ``prefer_semantic`` is set, retrieval is served by that backend instead;
        otherwise this deterministic lexical path is used.
        """
        query = (text or "").strip()
        if not query:
            return []
        try:
            k = max(1, int(k))
        except (TypeError, ValueError):
            k = 5

        if prefer_semantic and self._semantic_ready():
            delegated = self._delegate_query(query, k)
            if delegated is not None:
                return delegated

        q_terms = set(_tokenize(query))
        if not q_terms:
            return []

        n_docs = len(self._entries)
        scored: list[tuple[float, str]] = []
        for path, entry in self._entries.items():
            score = 0.0
            for term in q_terms:
                tf = entry.term_freq.get(term, 0)
                if not tf:
                    continue
                df = self._doc_freq.get(term, 0)
                idf = math.log((n_docs + 1) / (df + 1)) + 1.0
                score += tf * idf
            if score > 0.0:
                scored.append((score, path))

        # Descending score, then ascending path for a total, stable ordering.
        scored.sort(key=lambda item: (-item[0], item[1]))

        hits: list[SearchHit] = []
        for score, path in scored[:k]:
            line_no, snippet = self._best_snippet(self._entries[path], q_terms)
            hits.append(SearchHit(path=path, score=round(score, 6), snippet=snippet, line=line_no))
        return hits

    # -- internals --------------------------------------------------------

    @staticmethod
    def _build_entry(path: str, content: str, content_hash: str) -> IndexEntry:
        lines = content.splitlines()
        term_freq: Counter[str] = Counter(_tokenize(content))
        return IndexEntry(path=path, content_hash=content_hash, term_freq=term_freq, lines=lines)

    def _retract(self, entry: IndexEntry) -> None:
        """Remove an entry's contribution to corpus document frequencies."""
        for term in entry.term_freq:
            remaining = self._doc_freq.get(term, 0) - 1
            if remaining > 0:
                self._doc_freq[term] = remaining
            else:
                self._doc_freq.pop(term, None)

    @staticmethod
    def _best_snippet(entry: IndexEntry, q_terms: set[str]) -> tuple[int, str]:
        """Return ``(1-based line, text)`` of the best line for the query."""
        for idx, line in enumerate(entry.lines):
            if q_terms & set(_tokenize(line)):
                return idx + 1, line.strip()
        for idx, line in enumerate(entry.lines):
            if line.strip():
                return idx + 1, line.strip()
        return 0, ""

    def _semantic_ready(self) -> bool:
        if self._rag_index is None:
            return False
        try:
            status = self._rag_index.status()
            return int(status.get("vector_count", 0) or 0) > 0
        except (RuntimeError, OSError, ValueError, TypeError):
            return False

    def _delegate_query(self, query: str, k: int) -> list[SearchHit] | None:
        """Translate a delegated ``RagIndex.search`` result into SearchHits."""
        try:
            raw = self._rag_index.search(query, k=k)  # type: ignore[union-attr]
        except (RuntimeError, OSError, ValueError) as exc:  # pragma: no cover - defensive
            # Delegation is best-effort; fall back to the local lexical path.
            import logging

            logging.getLogger(__name__).warning("incremental_index delegation failed: %s", exc)
            return None

        hits: list[SearchHit] = []
        for item in raw:
            file_ref = str(item.get("file", "")) or ""
            path = file_ref.split("#", 1)[0]
            hits.append(
                SearchHit(
                    path=path,
                    score=round(float(item.get("score", 0.0) or 0.0), 6),
                    snippet=str(item.get("chunk", "") or "").strip(),
                    line=0,
                )
            )
        return hits
