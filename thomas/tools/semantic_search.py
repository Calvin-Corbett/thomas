"""Semantic (concept) code search tool backed by the RAG index.

Registers ``code.semantic_search`` into the live ``code.*`` toolset. Unlike the
lexical ``code.search`` (regex / keyword) tools, this queries the embedding-backed
RAG index (``thomas.core.rag_index``) so a natural-language *concept* query can
retrieve relevant code even when it shares zero literal keywords with the matching
snippet (e.g. "how do we stop duplicate charges" -> a snippet about
"idempotency keys for payment de-duplication").

Degradation: the underlying ``RagIndex.search`` fuses a semantic (embeddings)
result set with a lexical (SQLite FTS5) result set. When the embedding backend
(chromadb / sentence-transformers) is unavailable it transparently falls back to
the lexical index. This tool inspects the index status and reports which backend
served the hits so callers know whether a true concept match was possible.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from thomas.tools.base import Tool, ToolResult

logger = logging.getLogger(__name__)


@runtime_checkable
class SemanticIndex(Protocol):
    """Minimal contract this tool needs from a RAG index.

    ``thomas.core.rag_index.RagIndex`` satisfies this. Tests may inject a
    deterministic in-memory implementation.
    """

    def search(self, query: str, k: int = 5, filter_ext: str | None = None) -> list[dict[str, Any]]: ...

    def status(self) -> dict[str, Any]: ...


class SemanticSearchTool(Tool):
    """Concept search over the indexed codebase using semantic embeddings."""

    name = "code.semantic_search"
    category = "code"
    description = (
        "Concept search over the codebase using semantic embeddings. Give a "
        "natural-language description of what you are looking for (e.g. 'where do "
        "we prevent duplicate charges') and get ranked file/snippet hits even when "
        "they share no literal keywords with your query. Complements the keyword/"
        "regex code.search tools; falls back to lexical search when the embedding "
        "backend is unavailable."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural-language concept query describing what you want to find.",
            },
            "k": {
                "type": "integer",
                "description": "Number of ranked hits to return (default: 5, max: 50).",
            },
            "extension": {
                "type": "string",
                "description": "Optional file-extension filter, e.g. '.py'.",
            },
        },
        "required": ["query"],
    }

    def __init__(self, index: SemanticIndex | None = None) -> None:
        # ``index`` may be injected for tests; production resolves the singleton
        # lazily on first execute so importing this module stays cheap.
        self._index = index

    def _get_index(self) -> SemanticIndex:
        if self._index is not None:
            return self._index
        from thomas.core.rag_index import get_rag_index

        self._index = get_rag_index()
        return self._index

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        query = str(args.get("query", "")).strip()
        if not query:
            return ToolResult(ok=False, error="Missing required parameter: query")

        raw_k = args.get("k", 5)
        try:
            k_int = max(1, min(50, int(raw_k)))
        except (TypeError, ValueError):
            k_int = 5

        ext = args.get("extension")
        ext_str = str(ext).strip() if ext not in (None, "") else None

        try:
            index = self._get_index()
        except (RuntimeError, OSError, ImportError) as e:
            logger.warning("code.semantic_search: index unavailable: %s", e)
            return ToolResult(
                ok=False,
                error=(
                    f"Semantic index unavailable: {e}. Install embeddings: pip install chromadb sentence-transformers"
                ),
            )

        try:
            hits = index.search(query, k=k_int, filter_ext=ext_str)
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning("code.semantic_search: query failed: %s", e)
            return ToolResult(ok=False, error=f"Semantic search failed: {e}")

        backend = self._detect_backend(index)

        results: list[dict[str, Any]] = []
        for hit in hits:
            snippet = str(hit.get("chunk") or "").strip()
            if len(snippet) > 1200:
                snippet = snippet[:1200].rstrip() + " …"
            results.append(
                {
                    "file": hit.get("file", "unknown"),
                    "score": round(float(hit.get("score", 0.0) or 0.0), 6),
                    "snippet": snippet,
                }
            )

        return ToolResult(
            ok=True,
            data={
                "query": query,
                "backend": backend,
                "count": len(results),
                "results": results,
            },
        )

    @staticmethod
    def _detect_backend(index: SemanticIndex) -> str:
        """Report whether embeddings or the lexical fallback served results."""
        try:
            status = index.status()
        except (RuntimeError, OSError, ValueError):
            return "unknown"
        try:
            vector_count = int(status.get("vector_count", 0) or 0)
        except (TypeError, ValueError):
            vector_count = 0
        if vector_count > 0:
            return "semantic"
        if status.get("fts_enabled"):
            return "lexical"
        return "unknown"


def register_semantic_search_tool(registry: Any, index: SemanticIndex | None = None) -> SemanticSearchTool:
    """Register the ``code.semantic_search`` tool into a tool registry.

    Called from ``register_code_search_tools`` so the tool is present in every
    live toolset (CLI, server, agent loop, forge, bootdoctor).
    """
    tool = SemanticSearchTool(index=index)
    registry.register(tool)
    return tool
