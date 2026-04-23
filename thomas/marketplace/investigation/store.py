"""SQLite store for investigation cases, documents, claims, patterns, and timeline.

Database: ``~/.thomas/investigation.sqlite3`` (configurable).
Thread-safe via RLock.  WAL mode for concurrent readers.
FTS5 on documents and claims for fast full-text search.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _now_ms() -> int:
    return int(time.time() * 1000)


def _default_db_path() -> str:
    return str(Path.home() / ".thomas" / "investigation.sqlite3")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Case:
    id: str
    name: str
    source_path: str
    description: str = ""
    status: str = "active"
    created_at_ms: int = 0
    updated_at_ms: int = 0


@dataclass
class Document:
    id: int = 0
    case_id: str = ""
    file_path: str = ""
    file_name: str = ""
    file_type: str = ""
    file_size_bytes: int = 0
    file_hash: str = ""
    extracted_text: str | None = None
    extraction_method: str = ""
    page_count: int | None = None
    ingested_at_ms: int = 0
    analyzed_at_ms: int | None = None
    analysis_status: str = "pending"
    analysis_error: str | None = None


@dataclass
class Claim:
    id: int = 0
    case_id: str = ""
    doc_id: int = 0
    claim_text: str = ""
    category: str = "other"
    subcategory: str | None = None
    date_referenced: str | None = None
    date_precision: str = "unknown"
    people_involved: list[str] = field(default_factory=list)
    sentiment: str = "neutral"
    severity: int = 0
    confidence: float = 0.7
    quote_excerpt: str | None = None
    created_at_ms: int = 0


@dataclass
class Pattern:
    id: int = 0
    case_id: str = ""
    pattern_text: str = ""
    category: str = ""
    evidence_count: int = 0
    claim_ids: list[int] = field(default_factory=list)
    first_seen: str | None = None
    last_seen: str | None = None
    strength: float = 0.0
    created_at_ms: int = 0
    updated_at_ms: int = 0


@dataclass
class TimelineEvent:
    id: int = 0
    case_id: str = ""
    event_date: str = ""
    event_summary: str = ""
    category: str | None = None
    doc_ids: list[int] = field(default_factory=list)
    claim_ids: list[int] = field(default_factory=list)
    severity: int = 0
    created_at_ms: int = 0


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS cases (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    source_path TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_type TEXT NOT NULL,
    file_size_bytes INTEGER DEFAULT 0,
    file_hash TEXT NOT NULL,
    extracted_text TEXT,
    extraction_method TEXT DEFAULT '',
    page_count INTEGER,
    ingested_at_ms INTEGER NOT NULL,
    analyzed_at_ms INTEGER,
    analysis_status TEXT NOT NULL DEFAULT 'pending',
    analysis_error TEXT,
    UNIQUE(case_id, file_hash),
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_docs_case_status ON documents(case_id, analysis_status);

CREATE TABLE IF NOT EXISTS claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    doc_id INTEGER NOT NULL,
    claim_text TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'other',
    subcategory TEXT,
    date_referenced TEXT,
    date_precision TEXT DEFAULT 'unknown',
    people_involved TEXT DEFAULT '[]',
    sentiment TEXT DEFAULT 'neutral',
    severity INTEGER DEFAULT 0,
    confidence REAL DEFAULT 0.7,
    quote_excerpt TEXT,
    created_at_ms INTEGER NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE,
    FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_claims_case_cat ON claims(case_id, category);
CREATE INDEX IF NOT EXISTS idx_claims_case_date ON claims(case_id, date_referenced);
CREATE INDEX IF NOT EXISTS idx_claims_doc ON claims(doc_id);

CREATE TABLE IF NOT EXISTS patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    pattern_text TEXT NOT NULL,
    category TEXT NOT NULL,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    claim_ids TEXT NOT NULL DEFAULT '[]',
    first_seen TEXT,
    last_seen TEXT,
    strength REAL NOT NULL DEFAULT 0.0,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_patterns_case_strength ON patterns(case_id, strength DESC);

CREATE TABLE IF NOT EXISTS timeline_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    event_date TEXT NOT NULL,
    event_summary TEXT NOT NULL,
    category TEXT,
    doc_ids TEXT NOT NULL DEFAULT '[]',
    claim_ids TEXT NOT NULL DEFAULT '[]',
    severity INTEGER DEFAULT 0,
    created_at_ms INTEGER NOT NULL,
    FOREIGN KEY (case_id) REFERENCES cases(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_timeline_case_date ON timeline_events(case_id, event_date);

CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    extracted_text, file_name, content=documents, content_rowid=id
);

CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(
    claim_text, category, quote_excerpt, content=claims, content_rowid=id
);
"""


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class InvestigationStore:
    """Thread-safe SQLite store for investigation data."""

    def __init__(self, db_path: str | None = None):
        self._path = db_path or _default_db_path()
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _migrate(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            # Check if schema_version table exists
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'")
            if cur.fetchone() is None:
                # Fresh DB — create everything
                cur.executescript(_SCHEMA_V1)
                cur.execute("INSERT INTO schema_version (version) VALUES (1)")
                self._conn.commit()

    # -- Cases ---------------------------------------------------------------

    def create_case(self, name: str, source_path: str, description: str = "") -> Case:
        case_id = uuid.uuid4().hex[:16]
        now = _now_ms()
        with self._lock:
            self._conn.execute(
                "INSERT INTO cases (id, name, description, source_path, status, created_at_ms, updated_at_ms) "
                "VALUES (?, ?, ?, ?, 'active', ?, ?)",
                (case_id, name, description, source_path, now, now),
            )
            self._conn.commit()
        return Case(
            id=case_id,
            name=name,
            source_path=source_path,
            description=description,
            status="active",
            created_at_ms=now,
            updated_at_ms=now,
        )

    def get_case(self, case_id: str) -> Case | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
        if row is None:
            return None
        return Case(**dict(row))

    def list_cases(self) -> list[Case]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM cases ORDER BY created_at_ms DESC").fetchall()
        return [Case(**dict(r)) for r in rows]

    def get_latest_case(self) -> Case | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM cases ORDER BY created_at_ms DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return Case(**dict(row))

    def find_case_by_source(self, source_path: str) -> Case | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM cases WHERE source_path = ? AND status = 'active' "
                "ORDER BY created_at_ms DESC LIMIT 1",
                (source_path,),
            ).fetchone()
        if row is None:
            return None
        return Case(**dict(row))

    # -- Documents -----------------------------------------------------------

    def document_exists(self, case_id: str, file_hash: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM documents WHERE case_id = ? AND file_hash = ?",
                (case_id, file_hash),
            ).fetchone()
        return row is not None

    def add_document(self, doc: Document) -> int:
        now = _now_ms()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO documents "
                "(case_id, file_path, file_name, file_type, file_size_bytes, file_hash, "
                " extracted_text, extraction_method, page_count, ingested_at_ms, analysis_status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    doc.case_id,
                    doc.file_path,
                    doc.file_name,
                    doc.file_type,
                    doc.file_size_bytes,
                    doc.file_hash,
                    doc.extracted_text,
                    doc.extraction_method,
                    doc.page_count,
                    now,
                    "pending",
                ),
            )
            doc_id = cur.lastrowid
            # Update FTS
            if doc.extracted_text:
                self._conn.execute(
                    "INSERT INTO documents_fts(rowid, extracted_text, file_name) VALUES (?, ?, ?)",
                    (doc_id, doc.extracted_text, doc.file_name),
                )
            self._conn.commit()
        return doc_id  # type: ignore[return-value]

    def get_pending_documents(self, case_id: str) -> list[Document]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM documents WHERE case_id = ? AND analysis_status = 'pending' " "ORDER BY id",
                (case_id,),
            ).fetchall()
        return [self._row_to_doc(r) for r in rows]

    def get_documents(self, case_id: str) -> list[Document]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM documents WHERE case_id = ? ORDER BY id", (case_id,)).fetchall()
        return [self._row_to_doc(r) for r in rows]

    def update_document_text(self, doc_id: int, text: str, extraction_method: str = "transcription") -> None:
        """Update a document's extracted_text (e.g. after image transcription)."""
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET extracted_text = ?, extraction_method = ? WHERE id = ?",
                (text, extraction_method, doc_id),
            )
            # Re-index FTS: delete old entry then insert new
            self._conn.execute("DELETE FROM documents_fts WHERE rowid = ?", (doc_id,))
            row = self._conn.execute("SELECT file_name FROM documents WHERE id = ?", (doc_id,)).fetchone()
            fname = row["file_name"] if row else ""
            self._conn.execute(
                "INSERT INTO documents_fts(rowid, extracted_text, file_name) VALUES (?, ?, ?)",
                (doc_id, text, fname),
            )
            self._conn.commit()

    def get_document_path(self, doc_id: int) -> str | None:
        """Return the original file_path for a document by ID."""
        with self._lock:
            row = self._conn.execute("SELECT file_path FROM documents WHERE id = ?", (doc_id,)).fetchone()
        return row["file_path"] if row else None

    def get_image_documents(self, case_id: str, *, only_untranscribed: bool = False) -> list[Document]:
        """Return image documents, optionally only those with no extracted_text."""
        with self._lock:
            if only_untranscribed:
                rows = self._conn.execute(
                    "SELECT * FROM documents WHERE case_id = ? "
                    "AND (file_type = 'image' OR extraction_method = 'image_placeholder') "
                    "AND (extracted_text IS NULL OR extracted_text = '') "
                    "ORDER BY id",
                    (case_id,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM documents WHERE case_id = ? "
                    "AND (file_type = 'image' OR extraction_method = 'image_placeholder') "
                    "ORDER BY id",
                    (case_id,),
                ).fetchall()
        return [self._row_to_doc(r) for r in rows]

    def get_claims_with_source(
        self,
        case_id: str,
        *,
        category: str | None = None,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        """Return claims joined with their source document info (file_path, file_name)."""
        with self._lock:
            sql = (
                "SELECT c.*, d.file_path AS source_file, d.file_name AS source_file_name "
                "FROM claims c "
                "LEFT JOIN documents d ON c.doc_id = d.id "
                "WHERE c.case_id = ?"
            )
            params: list = [case_id]
            if category:
                sql += " AND c.category = ?"
                params.append(category)
            sql += " ORDER BY c.date_referenced, c.id LIMIT ?"
            params.append(limit)
            rows = self._conn.execute(sql, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("people_involved"), str):
                try:
                    d["people_involved"] = json.loads(d["people_involved"])
                except (json.JSONDecodeError, TypeError):
                    d["people_involved"] = []
            results.append(d)
        return results

    def mark_document_analyzed(self, doc_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET analysis_status = 'done', analyzed_at_ms = ? WHERE id = ?",
                (_now_ms(), doc_id),
            )
            self._conn.commit()

    def mark_document_failed(self, doc_id: int, error: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE documents SET analysis_status = 'failed', analysis_error = ?, analyzed_at_ms = ? "
                "WHERE id = ?",
                (error, _now_ms(), doc_id),
            )
            self._conn.commit()

    @staticmethod
    def _row_to_doc(row: sqlite3.Row) -> Document:
        d = dict(row)
        return Document(**d)

    # -- Claims --------------------------------------------------------------

    def add_claim(self, claim: Claim) -> int:
        now = _now_ms()
        people_json = json.dumps(claim.people_involved, ensure_ascii=False)
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO claims "
                "(case_id, doc_id, claim_text, category, subcategory, date_referenced, "
                " date_precision, people_involved, sentiment, severity, confidence, "
                " quote_excerpt, created_at_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    claim.case_id,
                    claim.doc_id,
                    claim.claim_text,
                    claim.category,
                    claim.subcategory,
                    claim.date_referenced,
                    claim.date_precision,
                    people_json,
                    claim.sentiment,
                    claim.severity,
                    claim.confidence,
                    claim.quote_excerpt,
                    now,
                ),
            )
            claim_id = cur.lastrowid
            # Update FTS
            self._conn.execute(
                "INSERT INTO claims_fts(rowid, claim_text, category, quote_excerpt) " "VALUES (?, ?, ?, ?)",
                (claim_id, claim.claim_text, claim.category, claim.quote_excerpt or ""),
            )
            self._conn.commit()
        return claim_id  # type: ignore[return-value]

    def add_claims_batch(self, claims: Sequence[Claim]) -> list[int]:
        ids = []
        for c in claims:
            ids.append(self.add_claim(c))
        return ids

    def get_claims(
        self,
        case_id: str,
        *,
        category: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        with self._lock:
            if category:
                rows = self._conn.execute(
                    "SELECT * FROM claims WHERE case_id = ? AND category = ? " "ORDER BY date_referenced, id LIMIT ?",
                    (case_id, category, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM claims WHERE case_id = ? " "ORDER BY date_referenced, id LIMIT ?",
                    (case_id, limit),
                ).fetchall()
        return [self._claim_row_to_dict(r) for r in rows]

    def search_claims(
        self, query: str, case_id: str, *, category: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        with self._lock:
            if category:
                rows = self._conn.execute(
                    "SELECT c.* FROM claims c "
                    "JOIN claims_fts f ON f.rowid = c.id "
                    "WHERE f.claims_fts MATCH ? AND c.case_id = ? AND c.category = ? "
                    "ORDER BY rank LIMIT ?",
                    (query, case_id, category, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT c.* FROM claims c "
                    "JOIN claims_fts f ON f.rowid = c.id "
                    "WHERE f.claims_fts MATCH ? AND c.case_id = ? "
                    "ORDER BY rank LIMIT ?",
                    (query, case_id, limit),
                ).fetchall()
        return [self._claim_row_to_dict(r) for r in rows]

    def search_documents(self, query: str, case_id: str, *, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT d.id, d.file_name, d.file_type, d.file_path, d.analysis_status "
                "FROM documents d "
                "JOIN documents_fts f ON f.rowid = d.id "
                "WHERE f.documents_fts MATCH ? AND d.case_id = ? "
                "ORDER BY rank LIMIT ?",
                (query, case_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _claim_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        if isinstance(d.get("people_involved"), str):
            try:
                d["people_involved"] = json.loads(d["people_involved"])
            except (json.JSONDecodeError, TypeError):
                d["people_involved"] = []
        return d

    # -- Patterns ------------------------------------------------------------

    def add_pattern(self, pattern: Pattern) -> int:
        now = _now_ms()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO patterns "
                "(case_id, pattern_text, category, evidence_count, claim_ids, "
                " first_seen, last_seen, strength, created_at_ms, updated_at_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    pattern.case_id,
                    pattern.pattern_text,
                    pattern.category,
                    pattern.evidence_count,
                    json.dumps(pattern.claim_ids),
                    pattern.first_seen,
                    pattern.last_seen,
                    pattern.strength,
                    now,
                    now,
                ),
            )
            self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_patterns(
        self, case_id: str, *, min_strength: float = 0.0, category: str | None = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            sql = "SELECT * FROM patterns WHERE case_id = ? AND strength >= ?"
            params: list = [case_id, min_strength]
            if category:
                sql += " AND category = ?"
                params.append(category)
            sql += " ORDER BY strength DESC"
            rows = self._conn.execute(sql, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("claim_ids"), str):
                try:
                    d["claim_ids"] = json.loads(d["claim_ids"])
                except (json.JSONDecodeError, TypeError):
                    d["claim_ids"] = []
            results.append(d)
        return results

    def clear_patterns(self, case_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM patterns WHERE case_id = ?", (case_id,))
            self._conn.commit()

    # -- Timeline ------------------------------------------------------------

    def add_timeline_event(self, event: TimelineEvent) -> int:
        now = _now_ms()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO timeline_events "
                "(case_id, event_date, event_summary, category, doc_ids, claim_ids, "
                " severity, created_at_ms) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.case_id,
                    event.event_date,
                    event.event_summary,
                    event.category,
                    json.dumps(event.doc_ids),
                    json.dumps(event.claim_ids),
                    event.severity,
                    now,
                ),
            )
            self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def get_timeline(
        self,
        case_id: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            sql = "SELECT * FROM timeline_events WHERE case_id = ?"
            params: list = [case_id]
            if start_date:
                sql += " AND event_date >= ?"
                params.append(start_date)
            if end_date:
                sql += " AND event_date <= ?"
                params.append(end_date)
            if category:
                sql += " AND category = ?"
                params.append(category)
            sql += " ORDER BY event_date ASC"
            rows = self._conn.execute(sql, params).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            for key in ("doc_ids", "claim_ids"):
                if isinstance(d.get(key), str):
                    try:
                        d[key] = json.loads(d[key])
                    except (json.JSONDecodeError, TypeError):
                        d[key] = []
            results.append(d)
        return results

    def clear_timeline(self, case_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM timeline_events WHERE case_id = ?", (case_id,))
            self._conn.commit()

    # -- Summary -------------------------------------------------------------

    def get_case_summary(self, case_id: str) -> dict[str, Any]:
        with self._lock:
            case = self._conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)).fetchone()
            if case is None:
                return {"error": "case not found"}

            doc_total = self._conn.execute("SELECT COUNT(*) FROM documents WHERE case_id = ?", (case_id,)).fetchone()[0]
            doc_analyzed = self._conn.execute(
                "SELECT COUNT(*) FROM documents WHERE case_id = ? AND analysis_status = 'done'",
                (case_id,),
            ).fetchone()[0]
            doc_pending = self._conn.execute(
                "SELECT COUNT(*) FROM documents WHERE case_id = ? AND analysis_status = 'pending'",
                (case_id,),
            ).fetchone()[0]
            doc_failed = self._conn.execute(
                "SELECT COUNT(*) FROM documents WHERE case_id = ? AND analysis_status = 'failed'",
                (case_id,),
            ).fetchone()[0]
            claim_count = self._conn.execute("SELECT COUNT(*) FROM claims WHERE case_id = ?", (case_id,)).fetchone()[0]
            pattern_count = self._conn.execute(
                "SELECT COUNT(*) FROM patterns WHERE case_id = ?", (case_id,)
            ).fetchone()[0]
            timeline_count = self._conn.execute(
                "SELECT COUNT(*) FROM timeline_events WHERE case_id = ?", (case_id,)
            ).fetchone()[0]

        return {
            "case_id": case_id,
            "case_name": case["name"],
            "source_path": case["source_path"],
            "status": case["status"],
            "documents": {
                "total": doc_total,
                "analyzed": doc_analyzed,
                "pending": doc_pending,
                "failed": doc_failed,
            },
            "claims": claim_count,
            "patterns": pattern_count,
            "timeline_events": timeline_count,
        }
