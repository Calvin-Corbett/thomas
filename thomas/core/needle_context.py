"""CAP-011: Large-context handling via needle-in-a-haystack retrieval.

Acceptance line (Level 2): *"Add a 300K-token needle test that returns the
correct file citation."*

A 300K-token context is far larger than most naive readers will splice into a
single prompt window. The honest way to "handle" it is **retrieval**: index the
corpus, and answer a query by citing the one file (and line range) that holds
the fact -- rather than brute-forcing the whole context and hoping the fact
survives truncation. This module proves exactly that:

1. :func:`generate_needle_corpus` synthesizes a large, multi-file corpus
   (scalable toward 300K tokens) with a single unique **needle** fact planted in
   exactly one file, positioned *past* a naive truncation window so that simple
   "take the first N tokens" truncation cannot see it.
2. :func:`naive_truncate` is the **control**: it concatenates the corpus and
   keeps only the leading ``window`` tokens -- the way a context-window-limited
   reader would. The needle is guaranteed to fall outside it.
3. :class:`NeedleReader` is the large-context reader. Given the needle query it
   returns the **correct file citation** (``path#Lx-Ly``) using a retrieval
   strategy. The default strategy is a deterministic, offline lexical index
   (:class:`thomas.core.incremental_index.IncrementalIndex`) -- no network, no
   embeddings, no threads. A live-embedding lane is documented below.

Token counting is via an **injectable counter** (default ``chars // 4``). A real
300K-token run against a live tokenizer/model is the credential-gated lane; the
hermetic core proves the retrieval contract deterministically against the
default counter.

Live-embedding lane (documented, credential-gated -- NOT exercised here)
------------------------------------------------------------------------
Construct :class:`NeedleReader` with a ``retriever`` that wraps a real embedding
backend (e.g. :class:`thomas.core.rag_index.RagIndex`, which yields
``path#Lx-Ly`` citations once ``status()['vector_count'] > 0``). The retriever
contract is a single call: ``retriever(corpus, query, k) -> list[Citation]``.
The default retriever is fully offline; swapping in an embedding-backed one is
the only change needed to run the same assertions against live vectors, and a
true 300K-token model run additionally needs a real tokenizer for the counter.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field

from thomas.core.incremental_index import IncrementalIndex

logger = logging.getLogger(__name__)

__all__ = [
    "Citation",
    "NeedleCorpus",
    "NeedleReader",
    "chars_over_four",
    "default_retriever",
    "generate_needle_corpus",
    "naive_truncate",
]

# A token counter maps text -> an integer token estimate. Injectable so a real
# tokenizer can replace the offline default without touching call sites.
TokenCounter = Callable[[str], int]

# A retriever maps (corpus, query, k) -> ranked citations. Injectable so a live
# embedding backend can replace the offline lexical default.
Retriever = Callable[["NeedleCorpus", str, int], "list[Citation]"]

# Deterministic filler vocabulary. Fixed order + seeded index selection keeps
# corpus generation reproducible with no PRNG state leaking between calls.
_FILLER_WORDS: tuple[str, ...] = (
    "system",
    "module",
    "handler",
    "request",
    "response",
    "context",
    "buffer",
    "gateway",
    "session",
    "payload",
    "adapter",
    "registry",
    "pipeline",
    "manifest",
    "checkpoint",
    "scheduler",
    "throughput",
    "latency",
    "retrieval",
    "embedding",
    "corpus",
    "document",
    "fragment",
    "citation",
    "boundary",
    "threshold",
    "heuristic",
    "invariant",
    "telemetry",
    "artifact",
)


def chars_over_four(text: str) -> int:
    """Default offline token estimate: ``ceil(len(text) / 4)``.

    The classic "~4 characters per token" heuristic. Deterministic and
    dependency-free; the credential-gated lane swaps this for a real tokenizer.
    """
    n = len(text)
    if n <= 0:
        return 0
    return (n + 3) // 4


@dataclass(frozen=True)
class Citation:
    """A file citation with an inclusive 1-based line range.

    ``ref`` renders as ``path#Lx-Ly`` -- the same shape
    :class:`thomas.core.rag_index.RagIndex` emits, so downstream consumers treat
    offline and live citations identically.
    """

    path: str
    start_line: int
    end_line: int

    @property
    def ref(self) -> str:
        return f"{self.path}#L{self.start_line}-L{self.end_line}"


@dataclass(frozen=True)
class NeedleCorpus:
    """A synthesized large-context corpus with one planted needle.

    ``files`` maps path -> content in deterministic insertion order. The needle
    fact lives only in ``needle_path`` across the inclusive line span
    ``needle_start_line .. needle_end_line``. ``naive_truncation_window`` is the
    token budget past which the needle sits, so a leading-window truncation
    cannot reach it.
    """

    files: dict[str, str]
    needle_path: str
    needle_start_line: int
    needle_end_line: int
    needle_fact: str
    needle_query: str
    total_tokens: int
    naive_truncation_window: int
    concat_order: list[str] = field(default_factory=list)

    @property
    def needle_citation(self) -> Citation:
        """The ground-truth citation the reader must reproduce."""
        return Citation(self.needle_path, self.needle_start_line, self.needle_end_line)

    def concatenated(self) -> str:
        """The full corpus as one string, in ``concat_order`` (needle last)."""
        return "\n".join(self.files[p] for p in self.concat_order)


def _filler_line(index: int, width: int) -> str:
    """Deterministic filler line of ``width`` words chosen by ``index``.

    Uses a simple LCG-style mix over ``index`` (pure function, no shared PRNG
    state) so the same index always yields the same line -- corpus generation is
    reproducible bit-for-bit.
    """
    words: list[str] = []
    state = (index * 2654435761 + 40503) & 0xFFFFFFFF
    for _ in range(width):
        state = (state * 1103515245 + 12345) & 0x7FFFFFFF
        words.append(_FILLER_WORDS[state % len(_FILLER_WORDS)])
    return f"line {index:06d}: " + " ".join(words)


def _make_filler_file(path_index: int, line_count: int, width: int) -> str:
    """Build one deterministic filler file body."""
    base = path_index * 100_003  # distinct, deterministic per-file line seeds
    return "\n".join(_filler_line(base + i, width) for i in range(line_count))


def generate_needle_corpus(
    target_tokens: int = 300_000,
    *,
    needle_fact: str = (
        "The activation passphrase for the Orion relay is "
        "quicksilver-lantern-4417, authorized only by the night custodian."
    ),
    needle_query: str = "Orion relay activation passphrase quicksilver-lantern-4417",
    token_counter: TokenCounter = chars_over_four,
    lines_per_file: int = 40,
    words_per_line: int = 12,
    naive_truncation_window: int = 8_000,
) -> NeedleCorpus:
    """Synthesize a large multi-file corpus with one planted needle.

    The corpus grows (by adding filler files) until ``token_counter`` reports at
    least ``target_tokens`` tokens, then the needle file is appended **last** so
    the needle sits past the ``naive_truncation_window``. Generation is fully
    deterministic for fixed arguments.

    Returns a :class:`NeedleCorpus`. The needle fact appears in exactly one file
    (``needle_path``), on a known line span, and nowhere else.
    """
    if target_tokens < 1:
        raise ValueError("target_tokens must be positive")
    if naive_truncation_window < 1:
        raise ValueError("naive_truncation_window must be positive")

    files: dict[str, str] = {}
    concat_order: list[str] = []
    running_tokens = 0

    # We must guarantee the needle lands past the truncation window, so filler
    # must supply strictly more than ``naive_truncation_window`` tokens before
    # the needle file regardless of ``target_tokens``.
    min_prefix_tokens = max(target_tokens, naive_truncation_window + 1)

    file_index = 0
    while running_tokens <= min_prefix_tokens:
        path = f"corpus/doc_{file_index:04d}.txt"
        body = _make_filler_file(file_index, lines_per_file, words_per_line)
        files[path] = body
        concat_order.append(path)
        running_tokens += token_counter(body)
        file_index += 1

    # The needle file: deterministic preamble lines, the fact on a known line,
    # then trailing filler so the citation is a genuine internal span.
    preamble = [_filler_line(9_000_001 + i, words_per_line) for i in range(3)]
    trailer = [_filler_line(9_100_001 + i, words_per_line) for i in range(2)]
    fact_line = f"FACT: {needle_fact}"
    needle_lines = [*preamble, fact_line, *trailer]
    needle_body = "\n".join(needle_lines)
    needle_path = "corpus/vault/secret_manifest.txt"
    files[needle_path] = needle_body
    concat_order.append(needle_path)
    running_tokens += token_counter(needle_body)

    fact_line_no = len(preamble) + 1  # 1-based line of the fact within the file

    return NeedleCorpus(
        files=files,
        needle_path=needle_path,
        needle_start_line=fact_line_no,
        needle_end_line=fact_line_no,
        needle_fact=needle_fact,
        needle_query=needle_query,
        total_tokens=running_tokens,
        naive_truncation_window=naive_truncation_window,
        concat_order=concat_order,
    )


def naive_truncate(
    corpus: NeedleCorpus,
    *,
    window: int | None = None,
    token_counter: TokenCounter = chars_over_four,
) -> str:
    """Control: keep only the leading ``window`` tokens of the concatenated corpus.

    Models a context-window-limited reader that simply takes the front of the
    input. Truncation is done at token granularity via ``token_counter`` on a
    growing prefix so it honors the injected counter exactly. The returned text
    is guaranteed to exclude the needle for a well-formed corpus.
    """
    budget = corpus.naive_truncation_window if window is None else window
    if budget < 0:
        raise ValueError("window must be non-negative")

    text = corpus.concatenated()
    # chars/4-style counters are monotonic in length, so we can binary-search the
    # longest character prefix whose token count fits the budget.
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if token_counter(text[:mid]) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo]


def default_retriever(corpus: NeedleCorpus, query: str, k: int = 5) -> list[Citation]:
    """Offline deterministic retriever over an in-memory lexical index.

    Builds a :class:`IncrementalIndex` from the corpus and returns citations for
    the top-``k`` files, resolving each hit's line span to the contiguous block
    of lines that actually match the query tokens. No network, no embeddings.
    """
    index = IncrementalIndex()
    index.index_files(corpus.files)
    hits = index.query(query, k=k, prefer_semantic=False)

    citations: list[Citation] = []
    for hit in hits:
        content = corpus.files.get(hit.path, "")
        start, end = _resolve_line_span(content, query)
        citations.append(Citation(hit.path, start, end))
    return citations


def _resolve_line_span(content: str, query: str) -> tuple[int, int]:
    """Return the inclusive 1-based line span best matching ``query`` in ``content``.

    Scores each line by how many distinct query tokens it contains, then returns
    the maximal contiguous run of nonzero-scoring lines around the single best
    line. Deterministic: ties resolve to the earliest line.
    """
    from thomas.core.incremental_index import _tokenize  # local: internal reuse

    q_terms = set(_tokenize(query))
    lines = content.splitlines()
    if not lines or not q_terms:
        return (1, 1)

    scores = [len(q_terms & set(_tokenize(line))) for line in lines]
    best_score = max(scores)
    if best_score <= 0:
        return (1, 1)

    best_idx = scores.index(best_score)  # earliest best line (deterministic)
    start = best_idx
    while start > 0 and scores[start - 1] > 0:
        start -= 1
    end = best_idx
    while end + 1 < len(scores) and scores[end + 1] > 0:
        end += 1
    return (start + 1, end + 1)


class NeedleReader:
    """Large-context reader that answers via retrieval, not brute context.

    The reader delegates to an injectable ``retriever`` (default:
    :func:`default_retriever`, a deterministic offline lexical index). It never
    materializes the whole context into a fixed window -- that is the naive
    control's job, and the control provably misses the needle.
    """

    def __init__(self, retriever: Retriever | None = None) -> None:
        self._retriever = retriever or default_retriever

    def cite(self, corpus: NeedleCorpus, query: str, k: int = 5) -> Citation | None:
        """Return the top citation (``path#Lx-Ly``) for ``query``, or ``None``."""
        results = self.locate(corpus, query, k=k)
        return results[0] if results else None

    def locate(self, corpus: NeedleCorpus, query: str, k: int = 5) -> list[Citation]:
        """Return up to ``k`` ranked citations for ``query``."""
        if not (query or "").strip():
            return []
        try:
            k = max(1, int(k))
        except (TypeError, ValueError):
            k = 5
        return list(self._retriever(corpus, query, k))
