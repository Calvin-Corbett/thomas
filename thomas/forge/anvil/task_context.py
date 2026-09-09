"""Tell a dispatched agent where to look, instead of making it search.

A dispatch used to send the task sentence and nothing else: ``definition`` and
``plan`` defaulted to empty strings, so the model woke up in a 3,787-file
repository knowing only what it had been asked for. On 2026-09-03 a benchmark
task took Thomas 500 seconds, most of it spent grepping 958 test files to find
the one to edit. The same repository answers `branch claim expires` with that
exact file in six milliseconds, because the index already knows.

The gap was never intelligence. Every run started amnesiac.

Three rules shape this module:

**A hint, never an instruction.** The block says where the index thinks the
answer lives. Retrieval is often wrong - measured on this repo, three of five
sample queries landed in the top three and two missed entirely - so the text
says so, and an agent that finds the hint useless must feel free to ignore it
and search. A confident wrong pointer is worse than none.

**It must never break a dispatch.** No index, no build yet, a corrupt store: all
of them return an empty string. A retrieval failure is not a task failure.

**Small.** The point is to save the model turns, not to spend its context.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 5
MAX_BLOCK_CHARS = 1200

HEADER = (
    "Places in this repository that may be relevant, from its search index.\n"
    "These are hints, not answers - the index is often wrong. Verify before\n"
    "relying on one, and search normally if none of them fit."
)


class _Searcher(Protocol):
    def search(self, query: str, k: int = 5, **kwargs: Any) -> list[dict[str, Any]]: ...


def render_context(hits: list[dict[str, Any]], *, max_chars: int = MAX_BLOCK_CHARS) -> str:
    """Render retrieved hits as a short, citable block. No hits -> empty string."""
    lines = [line for line in (str(h.get("file") or h.get("relpath") or "").strip() for h in hits) if line]
    if not lines:
        return ""
    block = HEADER + "\n" + "\n".join(f"  - {line}" for line in lines)
    if len(block) > max_chars:
        # Drop whole entries rather than truncating one mid-path: half a path is
        # a pointer to a file that does not exist.
        kept: list[str] = []
        size = len(HEADER)
        for line in lines:
            entry = f"\n  - {line}"
            if size + len(entry) > max_chars:
                break
            kept.append(line)
            size += len(entry)
        if not kept:
            return ""
        block = HEADER + "\n" + "\n".join(f"  - {line}" for line in kept)
    return block


def repo_context_for(
    goal: str,
    *,
    limit: int = DEFAULT_LIMIT,
    searcher: _Searcher | None = None,
) -> str:
    """Best-effort context block for `goal`. Any failure yields an empty string.

    `searcher` is injectable so this is testable without building an index over
    a real repository.
    """
    query = str(goal or "").strip()
    if not query:
        return ""
    try:
        index = searcher
        if index is None:
            index = _shared_index()
            if index is None:
                return ""
        hits = _search_relaxing(index, query, limit=max(1, int(limit)))
    except Exception as exc:  # no index, no build, unreadable store
        logger.debug("task context unavailable for %r: %s", query[:60], exc)
        return ""
    if not isinstance(hits, list):
        return ""
    return render_context(hits)


_INDEX: Any = None
_INDEX_TRIED = False


def _shared_index() -> Any:
    """The repo index, if one is already built. Never starts a build.

    Deliberately not ``get_rag_index()``: that singleton builds the whole
    repository when it finds the store empty, which took 250 seconds here. A
    dispatch asking where to look must not silently start a job of that size -
    it would turn the first dispatch on a fresh checkout into the slowest one,
    which is the exact problem this module exists to fix. An unbuilt index
    simply yields no context.

    One instance is cached because each ``RagIndex`` starts a worker thread.
    """
    global _INDEX, _INDEX_TRIED
    if _INDEX is not None or _INDEX_TRIED:
        return _INDEX
    _INDEX_TRIED = True
    try:
        from thomas.core.rag_index import RagIndex

        candidate = RagIndex()
        if int(candidate.status().get("manifest_files") or 0) <= 0:
            logger.debug("task context: index is empty; not building one from a dispatch")
            return None
        _INDEX = candidate
    except Exception as exc:
        logger.debug("task context: no usable index (%s)", exc)
        return None
    return _INDEX


# Words that say what to DO, not what to look for. A task sentence is mostly
# these, and the lexical index matches on all terms at once, so leaving them in
# is what made a whole-sentence query match nothing at all.
_NOISE = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "can",
        "could",
        "do",
        "does",
        "fix",
        "add",
        "update",
        "make",
        "create",
        "remove",
        "delete",
        "change",
        "implement",
        "refactor",
        "write",
        "rewrite",
        "ensure",
        "for",
        "from",
        "get",
        "give",
        "go",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "me",
        "my",
        "need",
        "needs",
        "new",
        "not",
        "of",
        "on",
        "only",
        "or",
        "please",
        "should",
        "so",
        "that",
        "the",
        "their",
        "then",
        "there",
        "these",
        "they",
        "this",
        "to",
        "up",
        "use",
        "used",
        "using",
        "want",
        "was",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
        "will",
        "with",
        "would",
        "you",
        "your",
        "failing",
        "broken",
        "currently",
        "now",
        "just",
        "also",
    ]
)

# One distinctive word is a legitimate query. Setting this to 2 meant a
# single-word goal was never searched at all - caught by a test that asserted
# only that the block carries its own caveat.
_MIN_TERMS = 1
_MAX_TERMS = 6


def query_terms(goal: str) -> list[str]:
    """The content words of a task sentence, most distinctive kept first.

    `fix the failing branch claims expiry test` searched verbatim returns
    nothing; `branch claims expiry` returns the file that needs editing. The
    difference is entirely the words that describe the action rather than the
    subject.
    """
    words = [w.strip(".,:;!?()[]{}\"'`") for w in str(goal or "").lower().split()]
    kept = [w for w in words if w and w not in _NOISE and len(w) > 2]
    return kept[:_MAX_TERMS]


def _search_relaxing(index: Any, goal: str, *, limit: int) -> list[dict[str, Any]]:
    """Search, dropping the trailing term until something matches.

    The lexical index requires every term, so precision costs recall very
    sharply: measured on this repo, four terms returned one hit, three returned
    two, and the whole task sentence returned none.

    Two smarter strategies were measured and neither beat this one. Trying every
    (n-1) subset scored the same 3 of 6 real task sentences while running up to
    40 queries, because the first subset that matches is not the best one.
    Matching terms against file paths rescued 1 of the 3 misses and added noise
    to the rest. Both are recorded here so the next person does not re-run them.

    The remaining misses share a shape: the question is conceptual and its words
    do not appear in the code. That is what the semantic half answers, and the
    semantic half needs the dependency this project never declared.
    """
    terms = query_terms(goal)
    if not terms:
        return []
    while len(terms) >= _MIN_TERMS:
        hits = index.search(" ".join(terms), k=limit)
        if hits:
            return hits
        terms = terms[:-1]
    return []
