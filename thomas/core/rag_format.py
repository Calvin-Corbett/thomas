"""Result formatting and snippet rendering for RAG search results.

Provides functions to format search results with line numbers, context,
and highlighted snippets.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from thomas.core.rag_indexer import _read_text_bytes


def format_result(r: dict[str, Any], maybe_render_fn=None) -> dict[str, Any]:
    """Format a search result with line numbers and snippet.

    Args:
        r: Raw result dict from search
        maybe_render_fn: Optional function to render snippet from disk

    Returns:
        Formatted result with file, chunk, and score
    """
    rel = r.get("relpath") or r.get("file") or "unknown"
    sl = r.get("start_line")
    el = r.get("end_line")
    file_with_lines = f"{rel}#L{sl}-L{el}" if isinstance(sl, int) and isinstance(el, int) else str(rel)

    # render snippet with line numbers if we can read the file
    snippet = r.get("chunk") or ""
    if maybe_render_fn:
        snippet = maybe_render_fn(relpath=str(rel), start_line=sl, end_line=el, fallback=str(snippet))

    # add a tiny header for kind/symbol
    header_bits = []
    if r.get("kind"):
        header_bits.append(str(r.get("kind")))
    if r.get("symbol"):
        header_bits.append(str(r.get("symbol")))
    if r.get("title") and str(r.get("title")).strip():
        t = str(r.get("title")).strip()
        if t.lower() not in " ".join(header_bits).lower():
            header_bits.append(t)
    if header_bits:
        header = " • ".join(header_bits)
        snippet = f"[{header}]\n{snippet}"

    return {"file": file_with_lines, "chunk": snippet, "score": float(r.get("score", 0.0))}


def maybe_render_from_disk(relpath: str, start_line: Any, end_line: Any, fallback: str, root_dir: str = None) -> str:
    """Render snippet from disk if possible.

    Args:
        relpath: Relative path to file
        start_line: Starting line number
        end_line: Ending line number
        fallback: Fallback text if file can't be read
        root_dir: Optional root directory (for resolving relative paths)

    Returns:
        Rendered snippet with line numbers
    """
    if not isinstance(start_line, int) or not isinstance(end_line, int):
        return fallback

    if not root_dir:
        return fallback

    root = Path(str(root_dir)).resolve()

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
    return render_snippet(lines, sl, el, highlight_terms=[])


def render_snippet(lines: list[str], sl: int, el: int, highlight_terms: list[str] = None) -> str:
    """Render a line-numbered snippet with optional highlighting.

    Args:
        lines: List of source lines
        sl: Starting line number (1-indexed)
        el: Ending line number (1-indexed)
        highlight_terms: Terms to highlight in the snippet

    Returns:
        Formatted snippet with line numbers
    """
    if highlight_terms is None:
        highlight_terms = []

    width = len(str(el))
    out_lines = []
    for ln in range(sl, el + 1):
        if ln > len(lines) or ln < 1:
            continue
        s = lines[ln - 1]
        # lightweight highlight
        for term in highlight_terms:
            t = term.strip()
            if not t:
                continue
            try:
                s = re.sub(re.escape(t), lambda m: f"[{m.group(0)}]", s, flags=re.IGNORECASE)
            except re.error:
                pass
        out_lines.append(f"{str(ln).rjust(width)} | {s}")
    return "\n".join(out_lines)
