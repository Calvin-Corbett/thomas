from __future__ import annotations

import logging
import os
from typing import Any

from .contradiction_review import (
    list_contradictions as list_contradictions_with_reviews,
)
from .contradiction_review import (
    list_contradictions_for_review as list_contradictions_for_review_rows,
)
from .contradiction_review import (
    review_contradiction as apply_contradiction_review,
)
from .contradiction_review import (
    severity_route as contradiction_severity_route,
)
from .contradiction_review import (
    upsert_review_state as upsert_contradiction_review_state,
)
from .contradictions import contradiction_score_for_fact
from .db import SqliteDB
from .fabric_retrieval import MemoryFabricV2Retrieval
from .fabric_utils import (
    MemorySettings,
    _now_ms,
)
from .schema import FACTS_FTS_TRIGGERS_SQL, FTS_TRIGGERS_SQL, INIT_SQL, SCHEMA_VERSION, facts_fts_sql, fts_sql
from .token import estimate_tokens

log = logging.getLogger(__name__)


class MemoryFabricV2(MemoryFabricV2Retrieval):
    """SQLite-backed hybrid memory (episodic + semantic + profile).

    Design goals:
    - Predictable, deterministic behavior (no hidden model calls).
    - Token-efficient memory pack output (with a redundancy/waste heuristic).
    - Diagnostics & traces for every retrieval.
    - Best-effort full-text search (FTS5) with safe fallback.
    """

    def __init__(self, root_path: str, db_filename: str = "memory_fabric_v2.sqlite3"):
        self.root_path = root_path
        os.makedirs(self.root_path, exist_ok=True)
        self.db = SqliteDB(os.path.join(self.root_path, db_filename))
        self.episodes_fts_enabled = False
        self.facts_fts_enabled = False
        self._init_schema()

    def _init_schema(self) -> None:
        with self.db.transact() as conn:
            conn.executescript(INIT_SQL)
            cur = conn.execute("SELECT value FROM meta WHERE key='schema_version'")
            row = cur.fetchone()
            if row is None:
                conn.execute("INSERT INTO meta(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
                current = SCHEMA_VERSION
            else:
                try:
                    current = int(str(row["value"]))
                except (ValueError, TypeError):
                    current = 0

            if current < SCHEMA_VERSION:
                self._migrate_schema(conn, current, SCHEMA_VERSION)
                conn.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))

            # Best-effort FTS (auto-disables if SQLite build lacks it)
            try:
                conn.executescript(fts_sql("episodes_fts"))
                conn.executescript(FTS_TRIGGERS_SQL)
                self.episodes_fts_enabled = True
            except (OSError, RuntimeError):
                self.episodes_fts_enabled = False

            try:
                conn.executescript(facts_fts_sql("semantic_facts_fts"))
                conn.executescript(FACTS_FTS_TRIGGERS_SQL)
                self.facts_fts_enabled = True
            except (OSError, RuntimeError):
                self.facts_fts_enabled = False

    def _migrate_schema(self, conn, current: int, target: int) -> None:
        """Schema migrations for existing DBs.

        INIT_SQL is idempotent (CREATE IF NOT EXISTS). This method applies ALTER TABLE changes.
        """
        if current < 2 <= target:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(thread_settings)").fetchall()]
            if "decay_half_life_hours" not in cols:
                conn.execute("ALTER TABLE thread_settings ADD COLUMN decay_half_life_hours REAL DEFAULT 240.0")
            if "include_profile" not in cols:
                conn.execute("ALTER TABLE thread_settings ADD COLUMN include_profile INTEGER DEFAULT 1")

    def get_thread_settings(self, thread_id: str) -> MemorySettings:
        with self.db.transact() as conn:
            row = conn.execute(
                "SELECT * FROM thread_settings WHERE thread_id=?",
                (thread_id,),
            ).fetchone()
            if row:
                return MemorySettings(
                    enabled=bool(row["enabled"]),
                    include_thread=bool(row["include_thread"]),
                    include_global=bool(row["include_global"]),
                    include_profile=bool(row["include_profile"]),
                    max_results=int(row["max_results"]),
                    max_pack_tokens=int(row["max_pack_tokens"]),
                    pins_only=bool(row["pins_only"]),
                    decay_half_life_hours=float(row["decay_half_life_hours"]),
                    auto_compact_enabled=bool(row["auto_compact_enabled"]),
                    auto_compact_episode_threshold=int(row["auto_compact_episode_threshold"]),
                    auto_compact_min_interval_hours=float(row["auto_compact_min_interval_hours"]),
                    auto_optimize_enabled=bool(row["auto_optimize_enabled"]),
                    auto_optimize_waste_threshold=float(row["auto_optimize_waste_threshold"]),
                    auto_optimize_min_interval_hours=float(row["auto_optimize_min_interval_hours"]),
                )
            return MemorySettings()

    def update_thread_settings(self, thread_id: str, patch: dict[str, Any]) -> MemorySettings:
        """Update thread settings, creating the row if needed (UPSERT)."""
        columns = [
            "enabled",
            "include_thread",
            "include_global",
            "include_profile",
            "pins_only",
            "max_pack_tokens",
            "max_results",
            "decay_half_life_hours",
            "auto_compact_enabled",
            "auto_compact_episode_threshold",
            "auto_compact_min_interval_hours",
            "auto_optimize_enabled",
            "auto_optimize_waste_threshold",
            "auto_optimize_min_interval_hours",
        ]
        defaults = MemorySettings().__dict__.copy()
        config = {**defaults, **patch}

        with self.db.transact() as conn:
            existing = conn.execute("SELECT 1 FROM thread_settings WHERE thread_id=?", (thread_id,)).fetchone()
            if existing:
                fields = []
                values = []
                for key in columns:
                    if key in patch:
                        fields.append(f"{key}=?")
                        values.append(config[key])
                if fields:
                    values.append(thread_id)
                    query = f"UPDATE thread_settings SET {','.join(fields)} WHERE thread_id=?"
                    conn.execute(query, values)
            else:
                placeholders = ",".join(["?"] * (len(columns) + 1))
                conn.execute(
                    f"INSERT INTO thread_settings(thread_id, {', '.join(columns)}) VALUES ({placeholders})",
                    (thread_id, *[config[column] for column in columns]),
                )

        return self.get_thread_settings(thread_id)

    def ingest_episode(
        self,
        thread_id: str,
        role: str,
        content: str,
        ts_ms: int | None = None,
        base_salience: float = 1.0,
        decay_half_life_hours: float = 48.0,
        source: str = "chat",
        also_extract_profile: bool = False,
    ) -> dict[str, Any]:
        event_ts = int(ts_ms if ts_ms is not None else _now_ms())
        created_at_ms = _now_ms()
        tokens = estimate_tokens(content)
        with self.db.transact() as conn:
            cur = conn.execute(
                """
                INSERT INTO episodes(
                    thread_id, ts_ms, role, content, tokens, base_salience,
                    decay_half_life_hours, created_at_ms, source
                ) VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (
                    thread_id,
                    event_ts,
                    role,
                    content,
                    tokens,
                    base_salience,
                    decay_half_life_hours,
                    created_at_ms,
                    source,
                ),
            )
            episode = {
                "id": int(cur.lastrowid),
                "thread_id": thread_id,
                "role": role,
                "content": content,
                "base_salience": base_salience,
                "ts_ms": event_ts,
                "decay_half_life_hours": decay_half_life_hours,
                "tokens": tokens,
                "source": source,
            }
        self._maybe_auto_maintain(thread_id)
        return episode

    def upsert_fact(
        self,
        subject: str,
        predicate: str,
        obj: str,
        confidence: float = 1.0,
        polarity: int = 1,
        thread_id: str | None = None,
        base_salience: float = 0.8,
        provenance_episode_id: int | None = None,
        ts_ms: int | None = None,
    ) -> dict[str, Any]:
        """Insert or update a semantic fact (globally or thread-scoped)."""
        now = int(ts_ms if ts_ms is not None else _now_ms())

        existing = self.db.execute(
            "SELECT * FROM semantic_facts WHERE subject=? AND predicate=? AND obj=? AND thread_id IS ?",
            (subject, predicate, obj, thread_id),
        ).fetchone()
        if existing:
            fact_id = int(existing["id"])
            with self.db.transact() as conn:
                conn.execute(
                    "UPDATE semantic_facts SET confidence=?, polarity=?, ts_ms=?, provenance_episode_id=? WHERE id=?",
                    (confidence, polarity, now, provenance_episode_id, fact_id),
                )
            return dict(self.db.execute("SELECT * FROM semantic_facts WHERE id=?", (fact_id,)).fetchone())

        prior_rows = self.db.execute(
            "SELECT id, obj, polarity FROM semantic_facts WHERE subject=? AND predicate=? AND thread_id IS ?",
            (subject, predicate, thread_id),
        ).fetchall()

        with self.db.transact() as conn:
            cur = conn.execute(
                """
                INSERT INTO semantic_facts(
                    thread_id, ts_ms, subject, predicate, obj, polarity,
                    confidence, provenance_episode_id, base_salience, created_at_ms
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    thread_id,
                    now,
                    subject,
                    predicate,
                    obj,
                    polarity,
                    confidence,
                    provenance_episode_id,
                    base_salience,
                    now,
                ),
            )
            fact_id_new = int(cur.lastrowid)

        for row in prior_rows:
            signal = contradiction_score_for_fact(
                old_obj=str(row["obj"]),
                new_obj=obj,
                old_polarity=int(row["polarity"]),
                new_polarity=int(polarity),
            )
            if signal is None:
                continue
            self._record_contradiction(
                left_kind="fact",
                left_id=str(int(row["id"])),
                right_kind="fact",
                right_id=str(fact_id_new),
                reason=str(signal.reason),
                score=float(signal.score),
            )

        return dict(self.db.execute("SELECT * FROM semantic_facts WHERE id=?", (fact_id_new,)).fetchone())

    def upsert_profile_hints(
        self,
        hints: dict[str, tuple[str, float]] | list[dict[str, Any]],
        *,
        thread_id: str | None = None,
        source_episode_id: int | None = None,
        ts_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        """Upsert profile hints while preserving higher-confidence existing values."""
        _ = thread_id
        now = int(ts_ms if ts_ms is not None else _now_ms())
        created_at_ms = _now_ms()

        if isinstance(hints, dict):
            rows = [{"key": key, "value": value, "confidence": conf} for key, (value, conf) in hints.items()]
        else:
            rows = [dict(item) for item in hints]

        result: list[dict[str, Any]] = []
        with self.db.transact() as conn:
            for row in rows:
                key = str(row.get("key") or "").strip()
                value = str(row.get("value") or "").strip()
                conf = float(row.get("confidence", 0.0) or 0.0)
                if not key or not value:
                    continue

                existing = conn.execute("SELECT * FROM profile_hints WHERE key=?", (key,)).fetchone()
                effective_value = value
                effective_conf = conf
                if existing is not None:
                    old_value = str(existing["value"])
                    old_conf = float(existing["confidence"])
                    if old_value != value and conf >= old_conf:
                        conn.execute(
                            """
                            UPDATE profile_hints
                            SET value=?, confidence=?, last_seen_ts_ms=?, source_episode_id=?, updated_at_ms=?
                            WHERE key=?
                            """,
                            (value, conf, now, source_episode_id, created_at_ms, key),
                        )
                        self._record_contradiction(
                            left_kind="profile_hint",
                            left_id=key,
                            right_kind="profile_hint",
                            right_id=key,
                            reason="profile_hint_value_change",
                            score=0.7,
                        )
                    elif old_value == value:
                        merged_conf = max(old_conf, conf)
                        conn.execute(
                            """
                            UPDATE profile_hints
                            SET confidence=?, last_seen_ts_ms=?, source_episode_id=?, updated_at_ms=?
                            WHERE key=?
                            """,
                            (merged_conf, now, source_episode_id, created_at_ms, key),
                        )
                        effective_conf = merged_conf
                    else:
                        effective_value = old_value
                        effective_conf = old_conf
                        conn.execute(
                            "UPDATE profile_hints SET last_seen_ts_ms=?, updated_at_ms=? WHERE key=?",
                            (now, created_at_ms, key),
                        )
                else:
                    conn.execute(
                        """
                        INSERT INTO profile_hints(
                            key, value, confidence, last_seen_ts_ms, source_episode_id,
                            created_at_ms, updated_at_ms
                        ) VALUES(?,?,?,?,?,?,?)
                        """,
                        (key, value, conf, now, source_episode_id, created_at_ms, created_at_ms),
                    )

                current = conn.execute("SELECT * FROM profile_hints WHERE key=?", (key,)).fetchone()
                if current is not None:
                    result.append(dict(current))
                else:
                    result.append(
                        {
                            "key": key,
                            "value": effective_value,
                            "confidence": effective_conf,
                            "last_seen_ts_ms": now,
                        }
                    )
        return result

    def pin_profile_hint(self, key: str, pinned: bool = True) -> None:
        with self.db.transact() as conn:
            conn.execute("UPDATE profile_hints SET pinned=? WHERE key=?", (int(pinned), key))

    def add_pin(self, kind: str, ref_id: str, thread_id: str | None = None, note: str = "") -> int:
        now = _now_ms()
        cur = self.db.execute(
            "INSERT INTO pins(kind, ref_id, thread_id, note, created_at_ms) VALUES(?,?,?,?,?)",
            (kind, ref_id, thread_id, note, now),
        )
        return int(cur.lastrowid)

    def remove_pin(self, pin_id: int) -> None:
        self.db.execute("DELETE FROM pins WHERE id=?", (pin_id,))

    def list_pins(self, thread_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        if thread_id is not None:
            rows = self.db.execute(
                "SELECT * FROM pins WHERE thread_id=? ORDER BY created_at_ms DESC LIMIT ?",
                (thread_id, int(limit)),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM pins WHERE thread_id IS NULL ORDER BY created_at_ms DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(r) for r in rows]

    def _contradiction_severity_route(self, *, score: float, reason: str) -> tuple[str, str]:
        return contradiction_severity_route(score=score, reason=reason)

    def _upsert_contradiction_review_state(self, cid: int, action: str, notes: str = "") -> dict[str, Any]:
        return upsert_contradiction_review_state(self.db, cid=cid, action=action, notes=notes)

    def _record_contradiction(
        self,
        *,
        left_kind: str,
        left_id: str,
        right_kind: str,
        right_id: str,
        reason: str,
        score: float,
    ) -> int:
        severity, route = self._contradiction_severity_route(score=score, reason=reason)
        created_at_ms = _now_ms()
        with self.db.transact() as conn:
            cur = conn.execute(
                """
                INSERT INTO contradictions(
                    left_kind, left_id, right_kind, right_id, score, reason, created_at_ms, resolved
                ) VALUES(?,?,?,?,?,?,?,0)
                """,
                (left_kind, left_id, right_kind, right_id, score, reason, created_at_ms),
            )
            cid = int(cur.lastrowid)
        upsert_contradiction_review_state(
            self.db,
            cid=cid,
            severity=severity,
            route=route,
            status="pending",
            actor="system",
            note="",
        )
        return cid

    def list_contradictions(self, only_open: bool = True, limit: int = 50) -> list[dict[str, Any]]:
        return list_contradictions_with_reviews(self.db, only_open=only_open, limit=limit)

    def list_contradictions_for_review(
        self,
        status: str | None = None,
        severity: str | None = None,
        route: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return list_contradictions_for_review_rows(
            self.db,
            status=status,
            severity=severity,
            route=route,
            limit=limit,
        )

    def review_contradiction(
        self,
        cid: int,
        decision: str | None = None,
        *,
        actor: str = "system",
        reason: str = "",
        action: str | None = None,
        notes: str = "",
    ) -> bool:
        chosen_decision = str(decision or action or "").strip()
        chosen_reason = str(reason or notes or "")
        return apply_contradiction_review(
            self.db,
            cid=cid,
            decision=chosen_decision,
            actor=actor,
            reason=chosen_reason,
        )

    def resolve_contradiction(self, cid: int, resolved: bool = True) -> None:
        with self.db.transact() as conn:
            conn.execute("UPDATE contradictions SET resolved=? WHERE id=?", (int(resolved), cid))

    def _get_maintenance_state(self, thread_id: str) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT last_compact_ts_ms, last_optimize_ts_ms FROM maintenance_state WHERE thread_id=?",
            (thread_id,),
        ).fetchone()
        if row:
            return {
                "last_compact_ms": int(row["last_compact_ts_ms"]) if row["last_compact_ts_ms"] else None,
                "last_optimize_ms": int(row["last_optimize_ts_ms"]) if row["last_optimize_ts_ms"] else None,
            }
        return {"last_compact_ms": None, "last_optimize_ms": None}

    def _update_maintenance_state(
        self, thread_id: str, compact_ms: int | None = None, optimize_ms: int | None = None
    ) -> None:
        current = self._get_maintenance_state(thread_id)
        now = _now_ms()
        last_compact = compact_ms if compact_ms is not None else current["last_compact_ms"]
        last_optimize = optimize_ms if optimize_ms is not None else current["last_optimize_ms"]
        with self.db.transact() as conn:
            conn.execute(
                """
                INSERT INTO maintenance_state(
                    thread_id, last_compact_ts_ms, last_optimize_ts_ms, created_at_ms, updated_at_ms
                ) VALUES(?,?,?,?,?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    last_compact_ts_ms=excluded.last_compact_ts_ms,
                    last_optimize_ts_ms=excluded.last_optimize_ts_ms,
                    updated_at_ms=excluded.updated_at_ms
                """,
                (thread_id, last_compact, last_optimize, now, now),
            )

    def _maybe_auto_maintain(self, thread_id: str) -> None:
        """Auto-compact and auto-optimize based on thread settings."""
        settings = self.get_thread_settings(thread_id)
        state = self._get_maintenance_state(thread_id)
        now = _now_ms()

        if settings.auto_compact_enabled:
            min_interval_ms = int(max(0.0, settings.auto_compact_min_interval_hours) * 3600 * 1000)
            episode_count_row = self.db.execute(
                "SELECT COUNT(*) AS c FROM episodes WHERE thread_id=?",
                (thread_id,),
            ).fetchone()
            episode_count = int((episode_count_row or {"c": 0})["c"])
            last_compact = state["last_compact_ms"]
            if episode_count >= int(settings.auto_compact_episode_threshold) and (
                last_compact is None or (now - last_compact) >= min_interval_ms
            ):
                try:
                    self.compact(thread_id=thread_id)
                    self._update_maintenance_state(thread_id, compact_ms=now)
                    log.info("Auto-compacted thread %s", thread_id)
                except Exception as e:
                    log.warning("Auto-compact failed for %s: %s", thread_id, e)

        if settings.auto_optimize_enabled:
            min_interval_ms = int(max(0.0, settings.auto_optimize_min_interval_hours) * 3600 * 1000)
            waste_row = self.db.execute(
                "SELECT MAX(waste) AS waste FROM packs WHERE scope='thread' AND thread_id=?",
                (thread_id,),
            ).fetchone()
            max_waste = float((waste_row or {"waste": 0.0})["waste"] or 0.0)
            last_optimize = state["last_optimize_ms"]
            if max_waste >= float(settings.auto_optimize_waste_threshold) and (
                last_optimize is None or (now - last_optimize) >= min_interval_ms
            ):
                try:
                    self.optimize_packs(
                        threshold=float(settings.auto_optimize_waste_threshold),
                        scope="thread",
                        thread_id=thread_id,
                    )
                    self._update_maintenance_state(thread_id, optimize_ms=now)
                    log.info("Auto-optimized packs for thread %s", thread_id)
                except Exception as e:
                    log.warning("Auto-optimize failed for %s: %s", thread_id, e)
