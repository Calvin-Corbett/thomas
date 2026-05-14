"""
thomas/tools/search_code.py

Tool: rag.search
Category: search
Parameters: {"query": str, "k": int=5, "extension": str optional}

Returns formatted results with file paths + line hints, grouped by file,
with short line-numbered previews.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict

from thomas.core.rag_index import get_rag_index


class RagSearchTool:
    name = "rag.search"
    category = "search"
    description = (
        "Hybrid repo search (semantic + lexical) with query operators: "
        "path:, file:, ext:, symbol:, kind:, phrase:, regex:/.../"
    )

    parameters = {
        "query": {"type": "string", "required": True, "description": "Search query (supports operators inside text)"},
        "k": {"type": "integer", "required": False, "default": 5, "description": "Top-k results"},
        "extension": {"type": "string", "required": False, "description": "Optional extension filter like .py"},
    }

    def execute(self, args: dict[str, Any]) -> str:
        args = args or {}
        query = str(args.get("query", "")).strip()
        if not query:
            return "Missing required parameter: query"

        k = args.get("k", 5)
        try:
            k_int = max(1, int(k))
        except Exception:
            k_int = 5

        ext = args.get("extension")
        ext_str = str(ext).strip() if ext is not None else None

        idx = get_rag_index()

        try:
            results = idx.search(query, k=k_int, filter_ext=ext_str)
            st = idx.status()
        except Exception as e:
            return (
                "RAG search unavailable.\n"
                f"Error: {e}\n"
                "Fix: pip install chromadb sentence-transformers"
            )

        if not results:
            build_state = "running" if st.get("build_running") else "idle"
            return (
                "No matches found in the RAG index yet.\n"
                f"Index: vectors={st.get('vector_count')} files={st.get('manifest_files')} fts={st.get('fts_enabled')}\n"
                f"Build state: {build_state}, pending updates: {st.get('pending_updates')}\n"
                "Tip: try query operators like `path:thomas/tools ToolRegistry` or `regex:/rag\\.search/`"
            )

        # Group by file
        by_file = defaultdict(list)
        for r in results:
            by_file[r.get("file", "unknown")].append(r)

        ordered_files = []
        seen = set()
        for r in results:
            f = r.get("file", "unknown")
            if f not in seen:
                ordered_files.append(f)
                seen.add(f)

        lines = []
        lines.append(f"Repo search results (k={k_int})")
        lines.append(f"Index: vectors={st.get('vector_count')} files={st.get('manifest_files')} fts={st.get('fts_enabled')}")
        lines.append("")

        shown = 0
        for f in ordered_files:
            hits = by_file[f]
            if not hits:
                continue
            lines.append(f"- {f}  (hits={len(hits)})")
            for h in hits[:2]:
                score = float(h.get("score", 0.0))
                chunk = (h.get("chunk") or "").strip()
                if len(chunk) > 1800:
                    chunk = chunk[:1800].rstrip() + " …"
                lines.append(f"  score={score:.3f}")
                # indent chunk
                lines.append("  " + chunk.replace("\n", "\n  "))
                lines.append("")
                shown += 1
                if shown >= k_int:
                    break
            if shown >= k_int:
                break

        return "\n".join(lines).rstrip()


TOOL = RagSearchTool()


def register(registry) -> None:
    registry.register(TOOL)
