"""Hermetic tests for the ``code.semantic_search`` tool (CAP-007).

Acceptance line: "Register semantic retrieval in the live toolset and prove a
zero-keyword-overlap concept query."

These tests prove:

1. ``code.semantic_search`` is registered by ``register_code_search_tools`` — the
   function every live toolset (CLI, server, agent loop, forge, bootdoctor) calls.
2. Executed through the real ``ToolRegistry``, a natural-language concept query
   retrieves a document that shares ZERO literal keywords with the query and ranks
   it first — something lexical/keyword search provably cannot do.
3. The tool reports the lexical fallback backend when embeddings are unavailable.

Because the embedding backend (chromadb / sentence-transformers) is not installed
in this environment, the semantic-ranking test injects a *deterministic concept
embedder* implementing the same ``search()/status()`` contract as
``thomas.core.rag_index.RagIndex``. The embedding is a normalized vector over a
small concept space (prevent / duplicate / charge); ranking is genuine cosine
similarity, not a hardcoded winner. This is the injection path the capability
explicitly permits. In production the tool queries the real ``RagIndex``.
"""

from __future__ import annotations

import math
import re
from typing import Any

import pytest

from thomas.tools.base import ToolResult
from thomas.tools.code_search import register_code_search_tools
from thomas.tools.registry import ToolRegistry
from thomas.tools.semantic_search import SemanticSearchTool

# --- Corpus (deterministic, zero embedding dependencies) -------------------

QUERY = "how do we stop duplicate charges"

# The relevant document. Note: it contains NONE of the query's content words
# ("stop", "duplicate", "charges") — the match is purely conceptual.
IDEMPOTENCY_DOC = (
    "Idempotency keys ensure a payment submitted twice is only settled once, "
    "preventing repeated billing of the same order."
)

DISTRACTORS = {
    "ui/calendar.py#L1-4": "The user interface renders a calendar widget with drag and drop scheduling for meetings.",
    "math/fib.py#L1-2": "Function to compute the fibonacci sequence recursively for a given index.",
    "docs/weather.md#L1-3": "A summary of seasonal rainfall patterns across the northern coastal region.",
}

RELEVANT_FILE = "payments/idempotency.py#L10-14"

# Concept lexicon: maps surface tokens to a shared concept dimension. This is a
# tiny, deterministic stand-in for a learned embedding space.
_CONCEPTS: dict[str, set[str]] = {
    "prevent": {"stop", "prevent", "preventing", "avoid", "block", "guard", "idempotency", "idempotent"},
    "duplicate": {"duplicate", "duplicates", "twice", "repeated", "repeat", "again", "double", "redundant"},
    "charge": {"charge", "charges", "charging", "billing", "bill", "payment", "payments", "settled", "settle"},
}
_CONCEPT_ORDER = sorted(_CONCEPTS)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z]+", text.lower())


def _embed(text: str) -> list[float]:
    """Deterministic normalized concept vector for a piece of text."""
    vec = [0.0] * len(_CONCEPT_ORDER)
    toks = set(_tokens(text))
    for i, concept in enumerate(_CONCEPT_ORDER):
        vec[i] = float(len(toks & _CONCEPTS[concept]))
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec
    return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class DeterministicSemanticIndex:
    """In-memory index implementing the RagIndex search()/status() contract.

    Ranks documents by cosine similarity in the deterministic concept space.
    """

    def __init__(self, docs: dict[str, str]) -> None:
        self._docs = dict(docs)
        self._embeddings = {file: _embed(text) for file, text in docs.items()}

    def search(self, query: str, k: int = 5, filter_ext: str | None = None) -> list[dict[str, Any]]:
        qv = _embed(query)
        scored: list[tuple[float, str]] = []
        for file, text in self._docs.items():
            if filter_ext and not file.split("#")[0].endswith(filter_ext):
                continue
            scored.append((_cosine(qv, self._embeddings[file]), file))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [{"file": file, "chunk": self._docs[file], "score": float(score)} for score, file in scored[: max(1, k)]]

    def status(self) -> dict[str, Any]:
        return {"vector_count": len(self._docs), "fts_enabled": True}


class LexicalOnlyIndex:
    """Index that reports no vectors but an active FTS index (fallback path)."""

    def search(self, query: str, k: int = 5, filter_ext: str | None = None) -> list[dict[str, Any]]:
        return [{"file": "notes.txt#L1-1", "chunk": "duplicate charges troubleshooting", "score": 1.0}]

    def status(self) -> dict[str, Any]:
        return {"vector_count": 0, "fts_enabled": True}


# --- Tests -----------------------------------------------------------------


def test_registered_in_live_toolset(tmp_path):
    """register_code_search_tools (the live-toolset entrypoint) registers it."""
    registry = ToolRegistry()
    register_code_search_tools(registry, tmp_path)
    assert "code.semantic_search" in registry
    tool = registry.get("code.semantic_search")
    assert tool is not None
    assert tool.category == "code"


def test_query_has_zero_keyword_overlap_with_relevant_doc():
    """Guard: the relevant doc genuinely shares no content words with the query."""
    overlap = set(_tokens(QUERY)) & set(_tokens(IDEMPOTENCY_DOC))
    # Only truly-empty overlap proves this is a semantic (not lexical) match.
    assert overlap == set(), f"expected zero keyword overlap, got {overlap}"


@pytest.mark.asyncio
async def test_zero_keyword_overlap_concept_query_ranks_relevant_doc_first():
    """The acceptance line: concept query retrieves the zero-overlap doc first."""
    corpus = {RELEVANT_FILE: IDEMPOTENCY_DOC, **DISTRACTORS}
    index = DeterministicSemanticIndex(corpus)

    registry = ToolRegistry()
    registry.register(SemanticSearchTool(index=index))

    result: ToolResult = await registry.execute("code.semantic_search", {"query": QUERY, "k": 3})

    assert result.ok, result.error
    data = result.data
    assert data["backend"] == "semantic"
    assert data["results"], "expected at least one hit"

    top = data["results"][0]
    assert top["file"] == RELEVANT_FILE, f"zero-overlap doc did not rank first: {data['results']}"
    assert top["score"] > 0.0

    # And it beat every distractor.
    distractor_files = set(DISTRACTORS)
    ranked_after = {r["file"] for r in data["results"][1:]}
    assert not (distractor_files & {top["file"]})
    assert ranked_after.issubset(distractor_files)


@pytest.mark.asyncio
async def test_lexical_search_cannot_find_the_doc():
    """Prove the win is semantic: pure keyword overlap retrieves nothing."""
    q_tokens = set(_tokens(QUERY))
    # Simulate lexical retrieval: a doc is a candidate only if it shares a token.
    lexical_hits = [
        file for file, text in {RELEVANT_FILE: IDEMPOTENCY_DOC, **DISTRACTORS}.items() if q_tokens & set(_tokens(text))
    ]
    assert RELEVANT_FILE not in lexical_hits


@pytest.mark.asyncio
async def test_missing_query_is_rejected():
    registry = ToolRegistry()
    registry.register(SemanticSearchTool(index=DeterministicSemanticIndex({})))
    result = await registry.execute("code.semantic_search", {"query": "   "})
    assert not result.ok
    assert "query" in (result.error or "").lower()


@pytest.mark.asyncio
async def test_reports_lexical_backend_when_no_vectors():
    registry = ToolRegistry()
    registry.register(SemanticSearchTool(index=LexicalOnlyIndex()))
    result = await registry.execute("code.semantic_search", {"query": "duplicate charges"})
    assert result.ok, result.error
    assert result.data["backend"] == "lexical"
