"""Local research library for long-form reference knowledge.

The library is intentionally separate from conversational memory:
- memory = short/medium-term personalized context
- library = durable reference artifacts (papers, notes, docs, findings)
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from thomas.core.config import AppConfig

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_FILE_CHARS = 48_000
_MAX_CTX_CHARS = 7_500


def default_library_root(config: AppConfig) -> Path:
    """Compute the default library folder path.

    If memory root is `<project>/runtime`, keep library at `<project>/library`.
    Otherwise colocate at `<memory_root>/library`.
    """
    root = config.memory.root_path
    if root.name.lower() == "runtime":
        return root.parent / "library"
    return root / "library"


def _slugify(text: str, *, fallback: str = "entry") -> str:
    s = _SAFE_RE.sub("-", (text or "").strip()).strip("-").lower()
    return s[:80] if s else fallback


def _tokenize(text: str) -> List[str]:
    return [x.lower() for x in _WORD_RE.findall(text or "") if len(x) >= 2]


def _compact_ws(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


@dataclass
class LibraryEntry:
    entry_id: str
    title: str
    category: str
    summary: str
    source: str
    tags: List[str]
    path: str
    created_ts_utc: int
    updated_ts_utc: int
    fingerprint: str
    query: str = ""
    auto_captured: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.entry_id,
            "title": self.title,
            "category": self.category,
            "summary": self.summary,
            "source": self.source,
            "tags": list(self.tags),
            "path": self.path,
            "created_ts_utc": int(self.created_ts_utc),
            "updated_ts_utc": int(self.updated_ts_utc),
            "fingerprint": self.fingerprint,
            "query": self.query,
            "auto_captured": bool(self.auto_captured),
        }


class ResearchLibrary:
    """Filesystem-backed categorized library with index + table of contents."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.entries_dir = self.root / "entries"
        self.index_path = self.root / "catalog.json"
        self.toc_path = self.root / "INDEX.md"
        self._lock = threading.RLock()
        self.ensure_layout()

    def ensure_layout(self) -> None:
        with self._lock:
            self.root.mkdir(parents=True, exist_ok=True)
            self.entries_dir.mkdir(parents=True, exist_ok=True)
            if not self.index_path.exists():
                payload = {"version": 1, "entries": []}
                self.index_path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            if not self.toc_path.exists():
                self.rebuild_toc()

    def _load_index(self) -> List[Dict[str, Any]]:
        if not self.index_path.exists():
            return []
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            return []
        entries = payload.get("entries")
        return entries if isinstance(entries, list) else []

    def _save_index(self, entries: List[Dict[str, Any]]) -> None:
        payload = {"version": 1, "entries": entries}
        tmp = self.index_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.index_path)

    def rebuild_toc(self) -> None:
        with self._lock:
            rows = self._load_index()
            by_cat: Dict[str, List[Dict[str, Any]]] = {}
            for row in rows:
                cat = str(row.get("category", "uncategorized") or "uncategorized")
                by_cat.setdefault(cat, []).append(row)

            lines = [
                "# Library Index",
                "",
                "Durable research/reference library for Thomas.",
                "",
            ]
            total = 0
            for cat in sorted(by_cat.keys()):
                lines.append(f"## {cat}")
                for row in sorted(by_cat[cat], key=lambda x: str(x.get("updated_ts_utc", 0)), reverse=True):
                    rid = str(row.get("id", ""))
                    title = str(row.get("title", rid))
                    summary = _compact_ws(str(row.get("summary", "")))
                    source = _compact_ws(str(row.get("source", "")))
                    path = str(row.get("path", ""))
                    tag_str = ", ".join(str(x) for x in (row.get("tags") or [])[:8])
                    lines.append(f"- `{rid}`: {title}")
                    if summary:
                        lines.append(f"  - Summary: {summary}")
                    if source:
                        lines.append(f"  - Source: {source}")
                    if tag_str:
                        lines.append(f"  - Tags: {tag_str}")
                    if path:
                        lines.append(f"  - File: `{path}`")
                    total += 1
                lines.append("")
            lines.append(f"_Total entries: {total}_")
            self.toc_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _normalize_tags(self, tags: Optional[Iterable[str]]) -> List[str]:
        out: List[str] = []
        for raw in tags or []:
            t = _slugify(str(raw), fallback="")
            if not t:
                continue
            if t not in out:
                out.append(t)
        return out[:16]

    def _hash_fingerprint(self, *, title: str, content: str, source: str, query: str) -> str:
        h = hashlib.sha256()
        h.update(_compact_ws(title).lower().encode("utf-8"))
        h.update(b"\n")
        h.update(_compact_ws(source).lower().encode("utf-8"))
        h.update(b"\n")
        h.update(_compact_ws(query).lower().encode("utf-8"))
        h.update(b"\n")
        h.update(_compact_ws(content).lower().encode("utf-8"))
        return h.hexdigest()

    def add_entry(
        self,
        *,
        title: str,
        category: str,
        content: str,
        summary: str = "",
        source: str = "",
        tags: Optional[Iterable[str]] = None,
        query: str = "",
        auto_captured: bool = False,
        dedupe: bool = True,
    ) -> Dict[str, Any]:
        with self._lock:
            now = int(time.time())
            safe_cat = _slugify(category or "uncategorized", fallback="uncategorized")
            safe_title = _slugify(title or "entry", fallback="entry")
            clean_content = str(content or "").strip()
            clean_summary = _compact_ws(summary)
            clean_query = _compact_ws(query)
            clean_source = _compact_ws(source)

            if len(clean_content) > _MAX_FILE_CHARS:
                clean_content = clean_content[:_MAX_FILE_CHARS] + "\n... (truncated)"

            fp = self._hash_fingerprint(
                title=title,
                content=clean_content,
                source=clean_source,
                query=clean_query,
            )

            entries = self._load_index()
            if dedupe:
                for row in entries:
                    if str(row.get("fingerprint", "")) == fp:
                        return dict(row)

            entry_id = f"{now}-{safe_title}"
            rel_dir = Path("entries") / safe_cat
            abs_dir = self.root / rel_dir
            abs_dir.mkdir(parents=True, exist_ok=True)
            rel_path = rel_dir / f"{entry_id}.md"
            abs_path = self.root / rel_path

            tag_list = self._normalize_tags(tags)
            md = [
                f"# {title.strip() or safe_title}",
                "",
                f"- id: `{entry_id}`",
                f"- category: `{safe_cat}`",
                f"- source: {clean_source or 'unspecified'}",
                f"- created_ts_utc: {now}",
                f"- tags: {', '.join(tag_list) if tag_list else '(none)'}",
            ]
            if clean_query:
                md.append(f"- query: {clean_query}")
            if clean_summary:
                md.extend(["", "## Summary", clean_summary])
            md.extend(["", "## Content", clean_content, ""])
            abs_path.write_text("\n".join(md), encoding="utf-8")

            row = LibraryEntry(
                entry_id=entry_id,
                title=title.strip() or safe_title,
                category=safe_cat,
                summary=clean_summary,
                source=clean_source,
                tags=tag_list,
                path=str(rel_path).replace("\\", "/"),
                created_ts_utc=now,
                updated_ts_utc=now,
                fingerprint=fp,
                query=clean_query,
                auto_captured=bool(auto_captured),
            ).to_dict()
            entries.append(row)
            self._save_index(entries)
            self.rebuild_toc()
            return row

    def list_entries(
        self,
        *,
        category: Optional[str] = None,
        query: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        rows = self._load_index()
        if category:
            want = _slugify(category, fallback="uncategorized")
            rows = [r for r in rows if str(r.get("category", "")) == want]

        if query and query.strip():
            q_toks = set(_tokenize(query))

            def _score(row: Dict[str, Any]) -> float:
                hay = " ".join(
                    [
                        str(row.get("title", "")),
                        str(row.get("summary", "")),
                        str(row.get("source", "")),
                        " ".join(str(t) for t in (row.get("tags") or [])),
                    ]
                )
                toks = set(_tokenize(hay))
                if not toks:
                    return 0.0
                hit = sum(1 for t in q_toks if t in toks)
                freshness = float(row.get("updated_ts_utc", 0) or 0) / 1_000_000_000.0
                return float(hit) + freshness * 0.0001

            rows = sorted(rows, key=_score, reverse=True)
        else:
            rows = sorted(rows, key=lambda r: int(r.get("updated_ts_utc", 0) or 0), reverse=True)

        lim = max(1, int(limit))
        return [dict(r) for r in rows[:lim]]

    def get_entry(self, entry_id: str) -> Optional[Dict[str, Any]]:
        rid = str(entry_id or "").strip()
        if not rid:
            return None
        rows = self._load_index()
        row = next((r for r in rows if str(r.get("id", "")) == rid), None)
        if row is None:
            return None
        rel = Path(str(row.get("path", "")))
        abs_path = self.root / rel
        content = ""
        if abs_path.exists():
            content = abs_path.read_text(encoding="utf-8", errors="replace")
        out = dict(row)
        out["content"] = content
        return out

    def scan_entries(
        self,
        *,
        updated_after_ts_utc: int = 0,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return entries updated after a checkpoint, oldest-first.

        This is intended for background curator pipelines that need deterministic,
        incremental processing without re-reading the whole catalog every run.
        """
        cutoff = int(updated_after_ts_utc or 0)
        lim = max(1, int(limit))
        rows = self._load_index()
        filtered = [
            dict(r)
            for r in rows
            if int(r.get("updated_ts_utc", 0) or 0) > cutoff
        ]
        filtered.sort(key=lambda r: int(r.get("updated_ts_utc", 0) or 0))
        return filtered[:lim]

    def build_context(self, *, query: str, max_tokens: int = 900, limit: int = 4) -> str:
        q = str(query or "").strip()
        if not q:
            return ""
        rows = self.list_entries(query=q, limit=max(1, limit))
        if not rows:
            return ""

        char_budget = max(600, int(max_tokens) * 4)
        parts = ["## Library Context"]
        used = len(parts[0]) + 2
        for row in rows:
            rid = str(row.get("id", ""))
            title = str(row.get("title", rid))
            category = str(row.get("category", "uncategorized"))
            summary = _compact_ws(str(row.get("summary", "")))
            source = _compact_ws(str(row.get("source", "")))
            rel = Path(str(row.get("path", "")))
            text = ""
            abs_path = self.root / rel
            if abs_path.exists():
                text = abs_path.read_text(encoding="utf-8", errors="replace")
            text = _compact_ws(text)
            if len(text) > 420:
                text = text[:420] + "..."

            block_lines = [f"- [{category}] {title} (`{rid}`)"]
            if summary:
                block_lines.append(f"  summary: {summary}")
            if source:
                block_lines.append(f"  source: {source}")
            if text:
                block_lines.append(f"  excerpt: {text}")
            block = "\n".join(block_lines) + "\n"
            if used + len(block) > min(char_budget, _MAX_CTX_CHARS):
                break
            parts.append(block.rstrip())
            used += len(block)

        if len(parts) <= 1:
            return ""
        return "\n".join(parts).strip()

    def add_research_note(
        self,
        *,
        query: str,
        answer: str,
        source: str = "assistant",
        category: str = "research-notes",
        tags: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        title = _compact_ws(query)[:120] or "research-note"
        summary = _compact_ws(answer)[:260]
        return self.add_entry(
            title=title,
            category=category,
            content=answer,
            summary=summary,
            source=source,
            tags=tags or ["research", "auto-captured"],
            query=query,
            auto_captured=True,
            dedupe=True,
        )
