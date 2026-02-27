"""Document chunking, indexing operations, and index management for RAG.

Provides smart chunking strategies (Python AST, Markdown headings, whitespace tokens),
document processing, and index building/update operations.
"""

from __future__ import annotations

import ast
import hashlib
import json
import logging
import re
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Constants
TOKENS_PER_CHUNK = 400
OVERLAP_TOKENS = 80
MAX_FILE_BYTES = 5_000_000
MANIFEST_VERSION = 3
MANIFEST_NAME = "manifest.json"
FTS_DB_NAME = "rag_fts.sqlite3"

DEFAULT_EXTENSIONS = [".py", ".md", ".toml", ".txt"]
DEFAULT_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "coverage",
    "runtime",
    "thomas_rag_index",
}

_TOKEN_RE = re.compile(r"\S+")
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class _Chunk:
    """Represents a chunk of text from a source file."""

    text: str
    start_char: int
    end_char: int
    start_line: int
    end_line: int
    index: int
    title: str = ""  # e.g. "function foo" or "### Heading"
    kind: str = ""  # function|class|heading|chunk
    symbol: str = ""  # name if applicable


# ---------------------------
# Utility Functions
# ---------------------------


def _now_iso() -> str:
    """Get current UTC time as ISO8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _sha1_bytes(b: bytes) -> str:
    """Compute SHA1 hash of bytes."""
    return hashlib.sha1(b).hexdigest()


def _sha1_str(s: str) -> str:
    """Compute SHA1 hash of string."""
    return hashlib.sha1(s.encode("utf-8", errors="ignore")).hexdigest()


def _newline_positions(text: str) -> list[int]:
    """Return character offsets of all newlines in text."""
    return [m.start() for m in re.finditer(r"\n", text)]


def _line_for_offset(newlines: list[int], offset: int) -> int:
    """Convert character offset to 1-indexed line number."""
    return bisect_right(newlines, offset) + 1


def _default_repo_root() -> Path:
    """Get default repository root directory (parent of core/)."""
    here = Path(__file__).resolve()
    return here.parents[2]


def _normalize_ext_list(extensions: list[str]) -> list[str]:
    """Normalize file extensions to lowercase with leading dots."""
    exts = [e if e.startswith(".") else f".{e}" for e in (extensions or DEFAULT_EXTENSIONS)]
    return [e.lower() for e in exts]


def _normalize_relpath(rel: str) -> str:
    """Normalize path separators to forward slashes."""
    return rel.replace("\\", "/") if rel else ""


def _safe_json_load(path: Path) -> dict[str, Any]:
    """Safely load JSON, returning empty dict on error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _safe_json_dump(path: Path, data: dict[str, Any]) -> None:
    """Safely dump JSON with atomic write."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _read_text_bytes(path: Path, max_bytes: int = MAX_FILE_BYTES) -> tuple[str | None, bytes | None]:
    """Read file as text and bytes, with encoding fallback and size limits.

    Returns (text_content, raw_bytes) or (None, None) if unreadable.
    """
    try:
        data = path.read_bytes()
    except OSError:
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
        except (UnicodeDecodeError, AttributeError):
            return None, None


# ---------------------------
# Chunking Strategies
# ---------------------------


def _chunk_text_whitespace_tokens(text: str) -> list[_Chunk]:
    """Chunk text by whitespace tokens with overlapping windows.

    Fallback strategy: simple 400-token chunks with 80-token overlap.
    """
    text = text or ""
    if not text.strip():
        return []
    spans = [(m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]
    if not spans:
        return []
    newlines = _newline_positions(text)
    step = max(1, TOKENS_PER_CHUNK - OVERLAP_TOKENS)

    chunks: list[_Chunk] = []
    idx = 0
    chunk_i = 0
    n = len(spans)

    while idx < n:
        end_idx = min(n, idx + TOKENS_PER_CHUNK)
        start_char = spans[idx][0]
        end_char = spans[end_idx - 1][1]
        chunk_text = text[start_char:end_char].strip()
        if chunk_text:
            chunks.append(
                _Chunk(
                    text=chunk_text,
                    start_char=start_char,
                    end_char=end_char,
                    start_line=_line_for_offset(newlines, start_char),
                    end_line=_line_for_offset(newlines, end_char),
                    index=chunk_i,
                    title="",
                    kind="chunk",
                    symbol="",
                )
            )
            chunk_i += 1
        if end_idx >= n:
            break
        idx += step
    return chunks


def _chunk_python_ast(text: str) -> list[_Chunk] | None:
    """Chunk Python source code by AST: functions and class definitions.

    If any block is > 12KB, re-chunk it using whitespace-token fallback.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None

    lines = text.splitlines(True)
    newlines = _newline_positions(text)

    def line_to_char(line_no: int) -> int:
        return sum(len(lines[i]) for i in range(max(0, line_no - 1)))

    blocks: list[_Chunk] = []
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

            blocks.append(
                _Chunk(
                    text=chunk_text,
                    start_char=start_char,
                    end_char=end_char,
                    start_line=sl,
                    end_line=el,
                    index=i,
                    title=title,
                    kind=kind,
                    symbol=symbol,
                )
            )
            i += 1

    if not blocks:
        return None

    # Re-chunk huge blocks
    final: list[_Chunk] = []
    idx = 0
    for b in blocks:
        if len(b.text) > 12000:
            subs = _chunk_text_whitespace_tokens(b.text)
            for s in subs:
                final.append(
                    _Chunk(
                        text=s.text,
                        start_char=b.start_char + s.start_char,
                        end_char=b.start_char + s.end_char,
                        start_line=b.start_line + (s.start_line - 1),
                        end_line=b.start_line + (s.end_line - 1),
                        index=idx,
                        title=b.title,
                        kind=b.kind,
                        symbol=b.symbol,
                    )
                )
                idx += 1
        else:
            final.append(
                _Chunk(b.text, b.start_char, b.end_char, b.start_line, b.end_line, idx, b.title, b.kind, b.symbol)
            )
            idx += 1

    return final


def _chunk_markdown_headings(text: str) -> list[_Chunk] | None:
    """Chunk Markdown by heading blocks (H1-H6).

    Each heading and its content until the next heading form a chunk.
    """
    matches = list(_MD_HEADING_RE.finditer(text))
    if not matches:
        return None

    newlines = _newline_positions(text)
    chunks: list[_Chunk] = []
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

        chunks.append(
            _Chunk(
                text=chunk_text,
                start_char=start,
                end_char=end,
                start_line=_line_for_offset(newlines, start),
                end_line=_line_for_offset(newlines, end),
                index=idx,
                title=heading_line,
                kind="heading",
                symbol=heading_line.lstrip("#").strip(),
            )
        )
        idx += 1

    return chunks if chunks else None


def _chunk_by_type(path: Path, text: str) -> list[_Chunk]:
    """Select chunking strategy based on file extension.

    .py -> AST-based
    .md -> Markdown headings
    others -> whitespace-token fallback
    """
    ext = path.suffix.lower()
    if ext == ".py":
        c = _chunk_python_ast(text)
        if c:
            return c
    if ext == ".md":
        c = _chunk_markdown_headings(text)
        if c:
            # re-chunk huge sections using fallback
            final: list[_Chunk] = []
            idx = 0
            for b in c:
                if len(b.text) > 16000:
                    subs = _chunk_text_whitespace_tokens(b.text)
                    for s in subs:
                        final.append(
                            _Chunk(
                                text=s.text,
                                start_char=b.start_char + s.start_char,
                                end_char=b.start_char + s.end_char,
                                start_line=b.start_line + (s.start_line - 1),
                                end_line=b.start_line + (s.end_line - 1),
                                index=idx,
                                title=b.title,
                                kind=b.kind,
                                symbol=b.symbol,
                            )
                        )
                        idx += 1
                else:
                    final.append(
                        _Chunk(
                            b.text, b.start_char, b.end_char, b.start_line, b.end_line, idx, b.title, b.kind, b.symbol
                        )
                    )
                    idx += 1
            return final
    return _chunk_text_whitespace_tokens(text)
