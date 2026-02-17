from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .db import SqliteDB
from .schema import INIT_SQL, SCHEMA_VERSION, fts_sql, FTS_TRIGGERS_SQL, facts_fts_sql, FACTS_FTS_TRIGGERS_SQL
from .token import estimate_tokens, normalize_lines, redundancy_ratio, truncate_to_token_budget, compact_lines
from .scoring import SalienceInputs, score as salience_score
from .types import RetrievalItem, RetrievalResult
from .contradictions import contradiction_score_for_fact
from .profile_hints import extract_profile_hints

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
log = logging.getLogger(__name__)

def _now_ms() -> int:
    return int(time.time() * 1000)

def _age_hours(now_ms: int, ts_ms: int) -> float:
    return max(0.0, (now_ms - ts_ms) / 1000.0 / 3600.0)

def _tokenize(s: str) -> List[str]:
    return [t.lower() for t in _WORD_RE.findall(s or "") if len(t) >= 2]

def _overlap_boost(query_toks: Sequence[str], text: str) -> float:
    if not query_toks:
        return 0.0
    toks = set(_tokenize(text))
    if not toks:
        return 0.0
    hit = sum(1 for t in set(query_toks) if t in toks)
    return min(1.0, hit / max(3, len(set(query_toks))))

@dataclass
class MemorySettings:
    enabled: bool = True
    include_global: bool = True
    include_profile: bool = True
    pins_only: bool = False
    max_pack_tokens: int = 1200
    max_results: int = 30
    decay_half_life_hours: float = 240.0
    auto_compact_enabled: bool = True
    auto_compact_episode_threshold: int = 2000
    auto_compact_min_interval_hours: float = 24.0
    auto_optimize_enabled: bool = True
    auto_optimize_waste_threshold: float = 0.22
    auto_optimize_min_interval_hours: float = 12.0

class MemoryFabricV2:
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
                except Exception:
                    current = 0

            if current < SCHEMA_VERSION:
                self._migrate_schema(conn, current, SCHEMA_VERSION)
                conn.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION),))

            # Best-effort FTS (auto-disables if SQLite build lacks it)
            try:
                conn.executescript(fts_sql("episodes_fts"))
                conn.executescript(FTS_TRIGGERS_SQL)
                self.episodes_fts_enabled = True
            except Exception:
                self.episodes_fts_enabled = False

            try:
                conn.executescript(facts_fts_sql("semantic_facts_fts"))
                conn.executescript(FACTS_FTS_TRIGGERS_SQL)
                self.facts_fts_enabled = True
            except Exception:
                self.facts_fts_enabled = False

    def _migrate_schema(self, conn, current: int, target: int) -> None:
        """Schema migrations for existing DBs.

        INIT_SQL is idempotent (CREATE IF NOT EXISTS). This method applies ALTER TABLE changes.
        """
        if current < 2 <= target:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(thread_settings)").fetchall()]

            def _add(col: str, ddl: str) -> None:
                if col not in cols:
                    conn.execute(ddl)

            _add("auto_compact_enabled", "ALTER TABLE thread_settings ADD COLUMN auto_compact_enabled INTEGER NOT NULL DEFAULT 1")
            _add("auto_compact_episode_threshold", "ALTER TABLE thread_settings ADD COLUMN auto_compact_episode_threshold INTEGER NOT NULL DEFAULT 2000")
            _add("auto_compact_min_interval_hours", "ALTER TABLE thread_settings ADD COLUMN auto_compact_min_interval_hours REAL NOT NULL DEFAULT 24")
            _add("auto_optimize_enabled", "ALTER TABLE thread_settings ADD COLUMN auto_optimize_enabled INTEGER NOT NULL DEFAULT 1")
            _add("auto_optimize_waste_threshold", "ALTER TABLE thread_settings ADD COLUMN auto_optimize_waste_threshold REAL NOT NULL DEFAULT 0.22")
            _add("auto_optimize_min_interval_hours", "ALTER TABLE thread_settings ADD COLUMN auto_optimize_min_interval_hours REAL NOT NULL DEFAULT 12")

# -----------------------
    # Thread settings
    # -----------------------
    def get_thread_settings(self, thread_id: str) -> MemorySettings:
        cur = self.db.execute("SELECT * FROM thread_settings WHERE thread_id=?", (thread_id,))
        row = cur.fetchone()
        if not row:
            with self.db.transact() as conn:
                conn.execute("INSERT OR IGNORE INTO thread_settings(thread_id) VALUES(?)", (thread_id,))
            return MemorySettings()
        return MemorySettings(
            enabled=bool(row["enabled"]),
            include_global=bool(row["include_global"]),
            include_profile=bool(row["include_profile"]),
            pins_only=bool(row["pins_only"]),
            max_pack_tokens=int(row["max_pack_tokens"]),
            max_results=int(row["max_results"]),
            decay_half_life_hours=float(row["decay_half_life_hours"]),
            auto_compact_enabled=bool(row["auto_compact_enabled"]),
            auto_compact_episode_threshold=int(row["auto_compact_episode_threshold"]),
            auto_compact_min_interval_hours=float(row["auto_compact_min_interval_hours"]),
            auto_optimize_enabled=bool(row["auto_optimize_enabled"]),
            auto_optimize_waste_threshold=float(row["auto_optimize_waste_threshold"]),
            auto_optimize_min_interval_hours=float(row["auto_optimize_min_interval_hours"]),
        )

    def update_thread_settings(self, thread_id: str, patch: Dict[str, Any]) -> MemorySettings:
        allowed = {
            "enabled",
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
        }
        fields = {k: patch[k] for k in patch.keys() if k in allowed}
        if not fields:
            return self.get_thread_settings(thread_id)

        enabled_set = int("enabled" in fields)
        include_global_set = int("include_global" in fields)
        include_profile_set = int("include_profile" in fields)
        pins_only_set = int("pins_only" in fields)
        max_pack_tokens_set = int("max_pack_tokens" in fields)
        max_results_set = int("max_results" in fields)
        decay_half_life_set = int("decay_half_life_hours" in fields)
        auto_compact_enabled_set = int("auto_compact_enabled" in fields)
        auto_compact_threshold_set = int("auto_compact_episode_threshold" in fields)
        auto_compact_interval_set = int("auto_compact_min_interval_hours" in fields)
        auto_optimize_enabled_set = int("auto_optimize_enabled" in fields)
        auto_optimize_threshold_set = int("auto_optimize_waste_threshold" in fields)
        auto_optimize_interval_set = int("auto_optimize_min_interval_hours" in fields)

        enabled_val = int(bool(fields.get("enabled", False)))
        include_global_val = int(bool(fields.get("include_global", False)))
        include_profile_val = int(bool(fields.get("include_profile", False)))
        pins_only_val = int(bool(fields.get("pins_only", False)))
        max_pack_tokens_val = int(fields.get("max_pack_tokens", 0) or 0)
        max_results_val = int(fields.get("max_results", 0) or 0)
        decay_half_life_val = float(fields.get("decay_half_life_hours", 0.0) or 0.0)
        auto_compact_enabled_val = int(bool(fields.get("auto_compact_enabled", False)))
        auto_compact_threshold_val = int(fields.get("auto_compact_episode_threshold", 0) or 0)
        auto_compact_interval_val = float(fields.get("auto_compact_min_interval_hours", 0.0) or 0.0)
        auto_optimize_enabled_val = int(bool(fields.get("auto_optimize_enabled", False)))
        auto_optimize_threshold_val = float(fields.get("auto_optimize_waste_threshold", 0.0) or 0.0)
        auto_optimize_interval_val = float(fields.get("auto_optimize_min_interval_hours", 0.0) or 0.0)

        with self.db.transact() as conn:
            conn.execute("INSERT OR IGNORE INTO thread_settings(thread_id) VALUES(?)", (thread_id,))
            conn.execute(
                """
                UPDATE thread_settings SET
                    enabled=CASE WHEN ? THEN ? ELSE enabled END,
                    include_global=CASE WHEN ? THEN ? ELSE include_global END,
                    include_profile=CASE WHEN ? THEN ? ELSE include_profile END,
                    pins_only=CASE WHEN ? THEN ? ELSE pins_only END,
                    max_pack_tokens=CASE WHEN ? THEN ? ELSE max_pack_tokens END,
                    max_results=CASE WHEN ? THEN ? ELSE max_results END,
                    decay_half_life_hours=CASE WHEN ? THEN ? ELSE decay_half_life_hours END,
                    auto_compact_enabled=CASE WHEN ? THEN ? ELSE auto_compact_enabled END,
                    auto_compact_episode_threshold=CASE WHEN ? THEN ? ELSE auto_compact_episode_threshold END,
                    auto_compact_min_interval_hours=CASE WHEN ? THEN ? ELSE auto_compact_min_interval_hours END,
                    auto_optimize_enabled=CASE WHEN ? THEN ? ELSE auto_optimize_enabled END,
                    auto_optimize_waste_threshold=CASE WHEN ? THEN ? ELSE auto_optimize_waste_threshold END,
                    auto_optimize_min_interval_hours=CASE WHEN ? THEN ? ELSE auto_optimize_min_interval_hours END
                WHERE thread_id=?;
                """,
                (
                    enabled_set,
                    enabled_val,
                    include_global_set,
                    include_global_val,
                    include_profile_set,
                    include_profile_val,
                    pins_only_set,
                    pins_only_val,
                    max_pack_tokens_set,
                    max_pack_tokens_val,
                    max_results_set,
                    max_results_val,
                    decay_half_life_set,
                    decay_half_life_val,
                    auto_compact_enabled_set,
                    auto_compact_enabled_val,
                    auto_compact_threshold_set,
                    auto_compact_threshold_val,
                    auto_compact_interval_set,
                    auto_compact_interval_val,
                    auto_optimize_enabled_set,
                    auto_optimize_enabled_val,
                    auto_optimize_threshold_set,
                    auto_optimize_threshold_val,
                    auto_optimize_interval_set,
                    auto_optimize_interval_val,
                    thread_id,
                ),
            )
        return self.get_thread_settings(thread_id)

    # -----------------------
    # Ingest (episodic)
    # -----------------------
    def ingest_episode(
        self,
        thread_id: str,
        role: str,
        content: str,
        ts_ms: Optional[int] = None,
        base_salience: float = 1.0,
        decay_half_life_hours: Optional[float] = None,
        source: str = "chat",
        also_extract_profile: bool = True,
    ) -> int:
        ts = ts_ms or _now_ms()
        tokens = estimate_tokens(content)
        settings = self.get_thread_settings(thread_id)
        half_life = float(decay_half_life_hours) if decay_half_life_hours is not None else float(settings.decay_half_life_hours)

        with self.db.transact() as conn:
            cur = conn.execute(
                """INSERT INTO episodes(thread_id, ts_ms, role, content, tokens, base_salience, decay_half_life_hours, retrieval_count, created_at_ms, source)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (thread_id, ts, role, content, tokens, float(base_salience), half_life, 0, self.db.now_ms(), source),
            )
            episode_id = int(cur.lastrowid)

        if also_extract_profile:
            hints = extract_profile_hints(content)
            if hints:
                self.upsert_profile_hints(
                    thread_id=thread_id,
                    hints=[{"key": h.key, "value": h.value, "confidence": h.confidence} for h in hints],
                    source_episode_id=episode_id,
                    ts_ms=ts,
                )
        # best-effort maintenance
        self._maybe_auto_maintain(thread_id)
        return episode_id

    # -----------------------
    # Semantic facts (external extractor may call this)
    # -----------------------
    def upsert_fact(
        self,
        *,
        thread_id: Optional[str],
        subject: str,
        predicate: str,
        obj: str,
        polarity: int = 1,
        confidence: float = 0.7,
        provenance_episode_id: Optional[int] = None,
        ts_ms: Optional[int] = None,
        base_salience: float = 1.1,
    ) -> int:
        ts = ts_ms or _now_ms()
        polarity = 1 if polarity >= 0 else -1
        confidence = float(max(0.0, min(1.0, confidence)))

        # contradiction detection against recent facts for same (subject,predicate,thread)
        cur = self.db.execute(
            """SELECT id, obj, polarity, confidence
               FROM semantic_facts
               WHERE subject=? AND predicate=? AND ((thread_id IS NULL AND ? IS NULL) OR thread_id=?)
               ORDER BY id DESC LIMIT 20""",
            (subject, predicate, thread_id, thread_id),
        )
        existing = cur.fetchall()

        with self.db.transact() as conn:
            cur2 = conn.execute(
                """INSERT INTO semantic_facts(thread_id, ts_ms, subject, predicate, obj, polarity, confidence, provenance_episode_id, base_salience, retrieval_count, created_at_ms)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (thread_id, ts, subject, predicate, obj, polarity, confidence, provenance_episode_id, float(base_salience), 0, self.db.now_ms()),
            )
            fact_id = int(cur2.lastrowid)

        for row in existing:
            contra = contradiction_score_for_fact(row["obj"], obj, int(row["polarity"]), polarity)
            if contra and min(float(row["confidence"]), confidence) >= 0.55:
                self._record_contradiction(
                    left_kind="fact",
                    left_id=str(int(row["id"])),
                    right_kind="fact",
                    right_id=str(fact_id),
                    score=float(contra.score),
                    reason=f"{contra.reason}; subj={subject} pred={predicate}",
                )
                break

        return fact_id

    # -----------------------
    # Profile hints (global)
    # -----------------------
    def upsert_profile_hints(
        self,
        *,
        thread_id: Optional[str],
        hints: List[Dict[str, Any]],
        source_episode_id: Optional[int],
        ts_ms: Optional[int] = None,
    ) -> None:
        ts = ts_ms or _now_ms()
        now = self.db.now_ms()

        for h in hints:
            key = str(h.get("key", "")).strip()
            val = str(h.get("value", "")).strip()
            if not key or not val:
                continue
            conf = float(h.get("confidence", 0.4))
            conf = max(0.0, min(1.0, conf))

            # contradiction: same key, different value (high confidence only)
            cur = self.db.execute("SELECT value, confidence FROM profile_hints WHERE key=?", (key,))
            row = cur.fetchone()
            if row and str(row["value"]).strip() != val and min(float(row["confidence"]), conf) >= 0.65:
                self._record_contradiction(
                    left_kind="hint",
                    left_id=key,
                    right_kind="hint",
                    right_id=key,
                    score=0.7,
                    reason=f"profile_hint_value_change:{key}",
                )

            with self.db.transact() as conn:
                conn.execute(
                    """INSERT INTO profile_hints(key, value, confidence, last_seen_ts_ms, source_episode_id, pinned, created_at_ms, updated_at_ms)
                       VALUES(?,?,?,?,?,COALESCE((SELECT pinned FROM profile_hints WHERE key=?),0),?,?)
                       ON CONFLICT(key) DO UPDATE SET
                          value=excluded.value,
                          confidence=max(profile_hints.confidence, excluded.confidence),
                          last_seen_ts_ms=max(profile_hints.last_seen_ts_ms, excluded.last_seen_ts_ms),
                          source_episode_id=COALESCE(excluded.source_episode_id, profile_hints.source_episode_id),
                          updated_at_ms=excluded.updated_at_ms
                    """,
                    (key, val, conf, ts, source_episode_id, key, now, now),
                )

    def pin_profile_hint(self, key: str, pinned: bool = True) -> None:
        with self.db.transact() as conn:
            conn.execute("UPDATE profile_hints SET pinned=? WHERE key=?", (1 if pinned else 0, key))

    # -----------------------
    # Pins
    # -----------------------
    def add_pin(self, kind: str, ref_id: str, thread_id: Optional[str] = None, note: str = "") -> int:
        with self.db.transact() as conn:
            cur = conn.execute(
                "INSERT INTO pins(kind, ref_id, thread_id, note, created_at_ms) VALUES(?,?,?,?,?)",
                (kind, str(ref_id), thread_id, note, self.db.now_ms()),
            )
            return int(cur.lastrowid)

    def remove_pin(self, pin_id: int) -> None:
        with self.db.transact() as conn:
            conn.execute("DELETE FROM pins WHERE id=?", (int(pin_id),))

    def list_pins(self, thread_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        if thread_id:
            cur = self.db.execute(
                "SELECT * FROM pins WHERE thread_id=? OR thread_id IS NULL ORDER BY created_at_ms DESC LIMIT ?",
                (thread_id, int(limit)),
            )
        else:
            cur = self.db.execute("SELECT * FROM pins ORDER BY created_at_ms DESC LIMIT ?", (int(limit),))
        return [dict(r) for r in cur.fetchall()]

    # -----------------------
    # Contradictions
    # -----------------------
    def _record_contradiction(
        self,
        left_kind: str,
        left_id: str,
        right_kind: str,
        right_id: str,
        score: float,
        reason: str,
    ) -> None:
        with self.db.transact() as conn:
            conn.execute(
                "INSERT INTO contradictions(left_kind,left_id,right_kind,right_id,score,reason,created_at_ms,resolved) VALUES(?,?,?,?,?,?,?,0)",
                (left_kind, str(left_id), right_kind, str(right_id), float(score), reason, self.db.now_ms()),
            )

    def list_contradictions(self, only_open: bool = True, limit: int = 50) -> List[Dict[str, Any]]:
        if only_open:
            cur = self.db.execute(
                "SELECT * FROM contradictions WHERE resolved=0 ORDER BY score DESC, created_at_ms DESC LIMIT ?",
                (int(limit),),
            )
        else:
            cur = self.db.execute("SELECT * FROM contradictions ORDER BY created_at_ms DESC LIMIT ?", (int(limit),))
        return [dict(r) for r in cur.fetchall()]

    def resolve_contradiction(self, cid: int, resolved: bool = True) -> None:
        with self.db.transact() as conn:
            conn.execute("UPDATE contradictions SET resolved=? WHERE id=?", (1 if resolved else 0, int(cid)))

        # -----------------------
    # Auto maintenance
    # -----------------------
    def _get_maintenance_state(self, thread_id: str) -> Dict[str, Any]:
        cur = self.db.execute("SELECT * FROM maintenance_state WHERE thread_id=?", (thread_id,))
        row = cur.fetchone()
        if row:
            return dict(row)
        now = self.db.now_ms()
        with self.db.transact() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO maintenance_state(thread_id, last_compact_ts_ms, last_optimize_ts_ms, created_at_ms, updated_at_ms) VALUES(?,?,?,?,?)",
                (thread_id, None, None, now, now),
            )
        row2 = self.db.execute("SELECT * FROM maintenance_state WHERE thread_id=?", (thread_id,)).fetchone()
        return dict(row2) if row2 else {"thread_id": thread_id, "last_compact_ts_ms": None, "last_optimize_ts_ms": None}

    def _update_maintenance_state(self, thread_id: str, *, last_compact_ts_ms: Optional[int] = None, last_optimize_ts_ms: Optional[int] = None) -> None:
        now = self.db.now_ms()
        st = self._get_maintenance_state(thread_id)
        lc = last_compact_ts_ms if last_compact_ts_ms is not None else st.get("last_compact_ts_ms")
        lo = last_optimize_ts_ms if last_optimize_ts_ms is not None else st.get("last_optimize_ts_ms")
        with self.db.transact() as conn:
            conn.execute(
                "UPDATE maintenance_state SET last_compact_ts_ms=?, last_optimize_ts_ms=?, updated_at_ms=? WHERE thread_id=?",
                (lc, lo, now, thread_id),
            )

    def _maybe_auto_maintain(self, thread_id: str) -> None:
        settings = self.get_thread_settings(thread_id)
        now = self.db.now_ms()
        st = self._get_maintenance_state(thread_id)
        last_compact = int(st.get("last_compact_ts_ms") or 0)
        last_opt = int(st.get("last_optimize_ts_ms") or 0)

        if settings.auto_compact_enabled:
            interval_ms = int(float(settings.auto_compact_min_interval_hours) * 3600 * 1000)
            if now - last_compact >= max(0, interval_ms):
                try:
                    cnt = int(self.db.execute("SELECT COUNT(*) c FROM episodes WHERE thread_id=?", (thread_id,)).fetchone()["c"])
                    if cnt >= int(settings.auto_compact_episode_threshold):
                        self.compact(thread_id=thread_id)
                        self._update_maintenance_state(thread_id, last_compact_ts_ms=now)
                except Exception as e:
                    log.debug("Auto-compact skipped for thread %s: %s", thread_id, e)

        if settings.auto_optimize_enabled:
            interval_ms = int(float(settings.auto_optimize_min_interval_hours) * 3600 * 1000)
            if now - last_opt >= max(0, interval_ms):
                try:
                    rows = self.db.execute(
                        "SELECT waste FROM packs WHERE scope='thread' AND thread_id=? ORDER BY updated_at_ms DESC LIMIT 5",
                        (thread_id,),
                    ).fetchall()
                    wastes = [float(r["waste"]) for r in rows] if rows else []
                    avg_waste = (sum(wastes) / len(wastes)) if wastes else 0.0
                    if avg_waste >= float(settings.auto_optimize_waste_threshold):
                        self.optimize_packs(threshold=float(settings.auto_optimize_waste_threshold), scope="thread", thread_id=thread_id)
                        self._update_maintenance_state(thread_id, last_optimize_ts_ms=now)
                except Exception as e:
                    log.debug("Auto-optimize skipped for thread %s: %s", thread_id, e)

# -----------------------
    # Retrieval
    # -----------------------
    def retrieve(self, thread_id: str, query: str, budget_tokens: Optional[int] = None) -> RetrievalResult:
        t0 = time.perf_counter()
        now = _now_ms()
        settings = self.get_thread_settings(thread_id)
        budget = int(budget_tokens or settings.max_pack_tokens)
        q_toks = _tokenize(query)

        trace_id = str(uuid.uuid4())
        if not settings.enabled:
            latency_ms = int((time.perf_counter() - t0) * 1000)
            self._write_trace(trace_id, thread_id, query, budget, [], None, latency_ms)
            return RetrievalResult(pack_text="", trace_id=trace_id, items=[], latency_ms=latency_ms, pack_tokens_est=0)

        # pins first
        pins = self.list_pins(thread_id=thread_id, limit=200)
        pin_items: List[RetrievalItem] = [
            RetrievalItem(
                kind="pin",
                ref_id=str(p["id"]),
                score=2.0,
                snippet=f"PIN({p['kind']}:{p['ref_id']}): {(p.get('note') or '').strip()}".strip(),
                meta=p,
            )
            for p in pins
        ]

        if settings.pins_only:
            pack = self._build_pack(thread_id, query, items=pin_items, budget_tokens=budget, include_profile=settings.include_profile)
            latency_ms = int((time.perf_counter() - t0) * 1000)
            self._write_trace(trace_id, thread_id, query, budget, [it.__dict__ for it in pin_items], None, latency_ms)
            return RetrievalResult(pack_text=pack, trace_id=trace_id, items=pin_items, latency_ms=latency_ms, pack_tokens_est=estimate_tokens(pack))

        # candidates
        ep_rows = self._search_episodes(thread_id, query, settings.max_results * 4)
        fact_rows = self._search_facts(thread_id, query, settings.include_global, settings.max_results * 3)
        hint_rows = self._get_profile_hints(limit=60) if settings.include_profile else []

        items: List[RetrievalItem] = []

        # score episodes
        for r in ep_rows:
            rel = _overlap_boost(q_toks, r["content"])
            inputs = SalienceInputs(
                base_salience=float(r["base_salience"]),
                age_hours=_age_hours(now, int(r["ts_ms"])),
                half_life_hours=float(r["decay_half_life_hours"]),
                retrieval_count=int(r["retrieval_count"]),
                pinned=False,
                relevance_boost=rel,
            )
            sc = salience_score(inputs)
            snippet = r["content"].strip().replace("\n", " ")
            if len(snippet) > 220:
                snippet = snippet[:217] + "..."
            items.append(
                RetrievalItem(
                    kind="episode",
                    ref_id=str(int(r["id"])),
                    score=sc,
                    snippet=snippet,
                    meta={"ts_ms": int(r["ts_ms"]), "role": r["role"], "score_components": inputs.__dict__},
                )
            )

        # score facts
        for r in fact_rows:
            txt = f"{r['subject']} {r['predicate']} {r['obj']}"
            rel = _overlap_boost(q_toks, txt)
            inputs = SalienceInputs(
                base_salience=float(r["base_salience"]),
                age_hours=_age_hours(now, int(r["ts_ms"])),
                half_life_hours=float(settings.decay_half_life_hours),
                retrieval_count=int(r["retrieval_count"]),
                pinned=False,
                relevance_boost=rel,
            )
            sc = salience_score(inputs)
            snippet = f"FACT: {r['subject']} • {r['predicate']} • {r['obj']} (conf {float(r['confidence']):.2f})"
            items.append(
                RetrievalItem(
                    kind="fact",
                    ref_id=str(int(r["id"])),
                    score=sc,
                    snippet=snippet,
                    meta={"thread_id": r["thread_id"], "polarity": int(r["polarity"]), "score_components": inputs.__dict__},
                )
            )

        # score profile hints
        for r in hint_rows:
            rel = _overlap_boost(q_toks, f"{r['key']} {r['value']}")
            inputs = SalienceInputs(
                base_salience=1.0,
                age_hours=_age_hours(now, int(r["last_seen_ts_ms"])),
                half_life_hours=720.0,
                retrieval_count=0,
                pinned=bool(r["pinned"]),
                relevance_boost=rel,
            )
            sc = salience_score(inputs)
            snippet = f"PROFILE: {r['key']} = {r['value']} (conf {float(r['confidence']):.2f})"
            items.append(RetrievalItem(kind="hint", ref_id=str(r["key"]), score=sc, snippet=snippet, meta={"pinned": bool(r["pinned"]), "score_components": inputs.__dict__}))

        items.extend(pin_items)

        items.sort(key=lambda it: it.score, reverse=True)
        items = items[: max(10, settings.max_results)]

        pack = self._build_pack(thread_id, query, items=items, budget_tokens=budget, include_profile=settings.include_profile)

        latency_ms = int((time.perf_counter() - t0) * 1000)

        # update retrieval counts (best effort)
        self._mark_retrieved(items, now)

        pack_id = None
        if pack.strip():
            pack_id = self._upsert_pack(scope="thread", thread_id=thread_id, text=pack)

        self._write_trace(trace_id, thread_id, query, budget, [it.__dict__ for it in items], pack_id, latency_ms)

        return RetrievalResult(pack_text=pack, trace_id=trace_id, items=items, latency_ms=latency_ms, pack_tokens_est=estimate_tokens(pack))

    def _search_episodes(self, thread_id: str, query: str, limit: int) -> List[Dict[str, Any]]:
        lim = int(max(1, min(500, limit)))
        if self.episodes_fts_enabled and query.strip():
            try:
                cur = self.db.execute(
                    """SELECT e.* FROM episodes_fts
                        JOIN episodes e ON e.id = episodes_fts.episode_id
                        WHERE episodes_fts MATCH ? AND e.thread_id=?
                        ORDER BY bm25(episodes_fts) LIMIT ?""",
                    (query, thread_id, lim),
                )
                rows = cur.fetchall()
                if rows:
                    return [dict(r) for r in rows]
            except Exception:
                log.debug("FTS episode query failed; falling back to LIKE search", exc_info=True)

        q = f"%{query.strip()}%" if query.strip() else "%"
        cur = self.db.execute(
            """SELECT * FROM episodes
               WHERE thread_id=? AND content LIKE ?
               ORDER BY ts_ms DESC LIMIT ?""",
            (thread_id, q, lim),
        )
        return [dict(r) for r in cur.fetchall()]

    def _search_facts(self, thread_id: str, query: str, include_global: bool, limit: int) -> List[Dict[str, Any]]:
        lim = int(max(1, min(500, limit)))

        if self.facts_fts_enabled and query.strip():
            try:
                if include_global:
                    cur = self.db.execute(
                        """SELECT f.* FROM semantic_facts_fts
                           JOIN semantic_facts f ON f.id = semantic_facts_fts.fact_id
                           WHERE semantic_facts_fts MATCH ? AND (f.thread_id=? OR f.thread_id IS NULL)
                           ORDER BY bm25(semantic_facts_fts) LIMIT ?""",
                        (query, thread_id, lim),
                    )
                else:
                    cur = self.db.execute(
                        """SELECT f.* FROM semantic_facts_fts
                           JOIN semantic_facts f ON f.id = semantic_facts_fts.fact_id
                           WHERE semantic_facts_fts MATCH ? AND f.thread_id=?
                           ORDER BY bm25(semantic_facts_fts) LIMIT ?""",
                        (query, thread_id, lim),
                    )
                rows = cur.fetchall()
                if rows:
                    return [dict(r) for r in rows]
            except Exception:
                log.debug("FTS fact query failed; falling back to LIKE search", exc_info=True)

        q = f"%{query.strip()}%" if query.strip() else "%"
        if include_global:
            cur = self.db.execute(
                """SELECT * FROM semantic_facts
                   WHERE (thread_id=? OR thread_id IS NULL) AND (subject LIKE ? OR predicate LIKE ? OR obj LIKE ?)
                   ORDER BY ts_ms DESC LIMIT ?""",
                (thread_id, q, q, q, lim),
            )
        else:
            cur = self.db.execute(
                """SELECT * FROM semantic_facts
                   WHERE thread_id=? AND (subject LIKE ? OR predicate LIKE ? OR obj LIKE ?)
                   ORDER BY ts_ms DESC LIMIT ?""",
                (thread_id, q, q, q, lim),
            )
        return [dict(r) for r in cur.fetchall()]


    def _get_profile_hints(self, limit: int = 50) -> List[Dict[str, Any]]:
        cur = self.db.execute(
            "SELECT * FROM profile_hints ORDER BY pinned DESC, confidence DESC, last_seen_ts_ms DESC LIMIT ?",
            (int(limit),),
        )
        return [dict(r) for r in cur.fetchall()]

    def _mark_retrieved(self, items: List[RetrievalItem], now_ms: int) -> None:
        ep_ids = [int(it.ref_id) for it in items if it.kind == "episode" and it.ref_id.isdigit()]
        fact_ids = [int(it.ref_id) for it in items if it.kind == "fact" and it.ref_id.isdigit()]
        with self.db.transact() as conn:
            if ep_ids:
                conn.executemany(
                    "UPDATE episodes SET retrieval_count=retrieval_count+1, last_retrieved_ts_ms=? WHERE id=?",
                    [(now_ms, i) for i in ep_ids],
                )
            if fact_ids:
                conn.executemany(
                    "UPDATE semantic_facts SET retrieval_count=retrieval_count+1, last_retrieved_ts_ms=? WHERE id=?",
                    [(now_ms, i) for i in fact_ids],
                )

    # -----------------------
    # Pack building + optimizer
    # -----------------------
    def _build_pack(self, thread_id: str, query: str, items: List[RetrievalItem], budget_tokens: int, include_profile: bool) -> str:
        # Stable high-density format
        profile_lines: List[str] = []
        if include_profile:
            hints = [it for it in items if it.kind == "hint"]
            for it in hints[:12]:
                profile_lines.append(f"- {it.snippet.replace('PROFILE:','').strip()}")
        pins = [it for it in items if it.kind == "pin"]
        facts = [it for it in items if it.kind == "fact"]
        episodes = [it for it in items if it.kind == "episode"]

        lines: List[str] = []
        lines.append("[Memory Fabric v2]")
        lines.append(f"Thread: {thread_id}")
        if query:
            lines.append(f"Query: {query}")

        if profile_lines:
            lines.append("")
            lines.append("[Profile]")
            lines.extend(profile_lines)

        if pins:
            lines.append("")
            lines.append("[Pins]")
            for it in pins[:20]:
                lines.append(f"- {it.snippet}")

        if facts:
            lines.append("")
            lines.append("[Facts]")
            for it in facts[:25]:
                lines.append(f"- {it.snippet.replace('FACT:','').strip()}")

        if episodes:
            lines.append("")
            lines.append("[Episodes]")
            for it in episodes[:25]:
                role = it.meta.get("role", "?")
                lines.append(f"- {role}: {it.snippet}")

        contras = self.list_contradictions(only_open=True, limit=10)
        if contras:
            lines.append("")
            lines.append("[Open contradictions]")
            for c in contras:
                lines.append(f"- ({c['score']:.2f}) {c['reason']}")
        text = "\n".join(lines).strip() + "\n"

        # token-efficiency optimizer (inline rewrite)
        text = self._token_efficiency_optimize(text, target_tokens=budget_tokens)
        text, _ = truncate_to_token_budget(text, budget_tokens)
        return text

    def _token_efficiency_optimize(self, text: str, target_tokens: int) -> str:
        lines = normalize_lines(text)

        # clamp very long bullet lines
        clamped: List[str] = []
        for ln in lines:
            if ln.startswith("- ") and len(ln) > 320:
                clamped.append(ln[:317] + "...")
            else:
                clamped.append(ln)

        # de-dupe exact lines
        clamped = compact_lines(clamped, max_lines=2000)

        waste = redundancy_ratio(clamped)
        if waste >= 0.22:
            # de-dupe bullets more aggressively per section
            out: List[str] = []
            seen = set()
            for ln in clamped:
                if ln.startswith("[") and ln.endswith("]"):
                    out.append(ln)
                    continue
                if ln.startswith("- "):
                    k = ln[2:].strip().lower()
                    if k in seen:
                        continue
                    seen.add(k)
                out.append(ln)
            clamped = out

        rewritten = "\n".join(clamped).strip() + "\n"

        # if still too long, prefer profile/pins/facts and early episodes
        if estimate_tokens(rewritten) > target_tokens:
            keep: List[str] = []
            section = None
            for ln in normalize_lines(rewritten):
                if ln.startswith("[") and ln.endswith("]"):
                    section = ln
                if section == "[Episodes]" and estimate_tokens("\n".join(keep)) > int(target_tokens * 0.85):
                    break
                keep.append(ln)
            rewritten = "\n".join(keep).strip() + "\n"

        return rewritten

    def _upsert_pack(self, scope: str, thread_id: Optional[str], text: str) -> int:
        tokens = estimate_tokens(text)
        waste = redundancy_ratio(normalize_lines(text))
        now = self.db.now_ms()
        with self.db.transact() as conn:
            cur = conn.execute(
                "SELECT id, version FROM packs WHERE scope=? AND ((thread_id IS NULL AND ? IS NULL) OR thread_id=?) ORDER BY id DESC LIMIT 1",
                (scope, thread_id, thread_id),
            )
            row = cur.fetchone()
            if row:
                pack_id = int(row["id"])
                ver = int(row["version"]) + 1
                conn.execute(
                    "UPDATE packs SET text=?, tokens_est=?, waste=?, version=?, updated_at_ms=? WHERE id=?",
                    (text, tokens, waste, ver, now, pack_id),
                )
                return pack_id
            cur2 = conn.execute(
                "INSERT INTO packs(scope, thread_id, text, tokens_est, waste, version, created_at_ms, updated_at_ms) VALUES(?,?,?,?,?,?,?,?)",
                (scope, thread_id, text, tokens, waste, 1, now, now),
            )
            return int(cur2.lastrowid)

    def optimize_packs(self, threshold: float = 0.22, scope: Optional[str] = None, thread_id: Optional[str] = None) -> Dict[str, Any]:
        """Rewrite existing packs if redundancy/waste exceeds threshold."""
        threshold = float(threshold)
        if scope and thread_id is not None:
            rows = self.db.execute(
                "SELECT id, text, tokens_est, waste FROM packs "
                "WHERE scope=? AND thread_id=? "
                "ORDER BY updated_at_ms DESC LIMIT 200",
                (scope, thread_id),
            ).fetchall()
        elif scope:
            rows = self.db.execute(
                "SELECT id, text, tokens_est, waste FROM packs "
                "WHERE scope=? "
                "ORDER BY updated_at_ms DESC LIMIT 200",
                (scope,),
            ).fetchall()
        elif thread_id is not None:
            rows = self.db.execute(
                "SELECT id, text, tokens_est, waste FROM packs "
                "WHERE thread_id=? "
                "ORDER BY updated_at_ms DESC LIMIT 200",
                (thread_id,),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT id, text, tokens_est, waste FROM packs "
                "ORDER BY updated_at_ms DESC LIMIT 200"
            ).fetchall()

        updated = 0
        for r in rows:
            waste = float(r["waste"])
            if waste < threshold:
                continue
            text = str(r["text"])
            rewritten = self._token_efficiency_optimize(text, target_tokens=max(200, int(r["tokens_est"])))
            # recompute metrics
            tokens = estimate_tokens(rewritten)
            new_waste = redundancy_ratio(normalize_lines(rewritten))
            with self.db.transact() as conn:
                conn.execute(
                    "UPDATE packs SET text=?, tokens_est=?, waste=?, version=version+1, updated_at_ms=? WHERE id=?",
                    (rewritten, tokens, new_waste, self.db.now_ms(), int(r["id"])),
                )
            updated += 1
        return {"updated": updated, "threshold": threshold, "scope": scope, "thread_id": thread_id}

    def compact(self, thread_id: Optional[str] = None) -> Dict[str, Any]:
        """Rebuild a representative pack from salient items (thread or global)."""
        now = _now_ms()

        if thread_id:
            settings = self.get_thread_settings(thread_id)
            ep = self.db.execute("SELECT * FROM episodes WHERE thread_id=? ORDER BY ts_ms DESC LIMIT 250", (thread_id,)).fetchall()
            facts = self.db.execute(
                "SELECT * FROM semantic_facts WHERE thread_id=? OR thread_id IS NULL ORDER BY ts_ms DESC LIMIT 200",
                (thread_id,),
            ).fetchall()
            hints = self._get_profile_hints(50) if settings.include_profile else []
            pins = self.list_pins(thread_id=thread_id, limit=200)

            items: List[RetrievalItem] = []
            for r in ep:
                inputs = SalienceInputs(
                    base_salience=float(r["base_salience"]),
                    age_hours=_age_hours(now, int(r["ts_ms"])),
                    half_life_hours=float(r["decay_half_life_hours"]),
                    retrieval_count=int(r["retrieval_count"]),
                    pinned=False,
                    relevance_boost=0.0,
                )
                sc = salience_score(inputs)
                snippet = str(r["content"]).strip().replace("\n", " ")
                if len(snippet) > 220:
                    snippet = snippet[:217] + "..."
                items.append(RetrievalItem(kind="episode", ref_id=str(int(r["id"])), score=sc, snippet=snippet, meta={"ts_ms": int(r["ts_ms"]), "role": r["role"]}))

            for r in facts:
                inputs = SalienceInputs(
                    base_salience=float(r["base_salience"]),
                    age_hours=_age_hours(now, int(r["ts_ms"])),
                    half_life_hours=float(settings.decay_half_life_hours),
                    retrieval_count=int(r["retrieval_count"]),
                    pinned=False,
                    relevance_boost=0.0,
                )
                sc = salience_score(inputs)
                items.append(RetrievalItem(kind="fact", ref_id=str(int(r["id"])), score=sc,
                                           snippet=f"FACT: {r['subject']} • {r['predicate']} • {r['obj']} (conf {float(r['confidence']):.2f})",
                                           meta={"thread_id": r["thread_id"], "polarity": int(r["polarity"])}))

            for r in hints:
                inputs = SalienceInputs(
                    base_salience=1.0,
                    age_hours=_age_hours(now, int(r["last_seen_ts_ms"])),
                    half_life_hours=720.0,
                    retrieval_count=0,
                    pinned=bool(r["pinned"]),
                    relevance_boost=0.0,
                )
                sc = salience_score(inputs)
                items.append(RetrievalItem(kind="hint", ref_id=str(r["key"]), score=sc, snippet=f"PROFILE: {r['key']} = {r['value']} (conf {float(r['confidence']):.2f})", meta={"pinned": bool(r["pinned"]), "score_components": inputs.__dict__}))

            for p in pins:
                items.append(RetrievalItem(kind="pin", ref_id=str(p["id"]), score=2.0, snippet=f"PIN({p['kind']}:{p['ref_id']}): {(p.get('note') or '').strip()}".strip(), meta=p))

            items.sort(key=lambda it: it.score, reverse=True)
            items = items[: max(25, settings.max_results)]
            pack = self._build_pack(thread_id, "", items, budget_tokens=settings.max_pack_tokens, include_profile=settings.include_profile)
            pack_id = self._upsert_pack(scope="thread", thread_id=thread_id, text=pack)
            return {"pack_id": pack_id, "thread_id": thread_id, "tokens_est": estimate_tokens(pack), "waste": redundancy_ratio(normalize_lines(pack))}

        # global pack
        facts = self.db.execute("SELECT * FROM semantic_facts WHERE thread_id IS NULL ORDER BY ts_ms DESC LIMIT 250").fetchall()
        hints = self._get_profile_hints(80)
        pins = self.list_pins(thread_id=None, limit=200)

        items: List[RetrievalItem] = []
        for r in hints:
            hint_inputs = SalienceInputs(
                base_salience=1.0,
                age_hours=_age_hours(now, int(r["last_seen_ts_ms"])),
                half_life_hours=720.0,
                retrieval_count=0,
                pinned=bool(r["pinned"]),
                relevance_boost=0.0,
            )
            items.append(RetrievalItem(kind="hint", ref_id=str(r["key"]), score=1.3 + (0.8 if bool(r["pinned"]) else 0.0),
                                       snippet=f"PROFILE: {r['key']} = {r['value']} (conf {float(r['confidence']):.2f})", meta={"pinned": bool(r["pinned"]), "score_components": hint_inputs.__dict__}))
        for r in facts:
            items.append(RetrievalItem(kind="fact", ref_id=str(int(r["id"])), score=1.1,
                                       snippet=f"FACT: {r['subject']} • {r['predicate']} • {r['obj']} (conf {float(r['confidence']):.2f})", meta={"thread_id": None}))
        for p in pins:
            items.append(RetrievalItem(kind="pin", ref_id=str(p["id"]), score=2.0, snippet=f"PIN({p['kind']}:{p['ref_id']}): {(p.get('note') or '').strip()}".strip(), meta=p))

        items.sort(key=lambda it: it.score, reverse=True)
        pack = self._build_pack(thread_id="GLOBAL", query="", items=items[:120], budget_tokens=1500, include_profile=True)
        pack_id = self._upsert_pack(scope="global", thread_id=None, text=pack)
        return {"pack_id": pack_id, "scope": "global", "tokens_est": estimate_tokens(pack), "waste": redundancy_ratio(normalize_lines(pack))}

    # -----------------------
    # Health / diagnostics
    # -----------------------
    def health(self) -> Dict[str, Any]:
        now = self.db.now_ms()
        ep = int(self.db.execute("SELECT COUNT(*) c FROM episodes").fetchone()["c"])
        facts = int(self.db.execute("SELECT COUNT(*) c FROM semantic_facts").fetchone()["c"])
        hints = int(self.db.execute("SELECT COUNT(*) c FROM profile_hints").fetchone()["c"])
        pins = int(self.db.execute("SELECT COUNT(*) c FROM pins").fetchone()["c"])
        packs = int(self.db.execute("SELECT COUNT(*) c FROM packs").fetchone()["c"])
        contra_open = int(self.db.execute("SELECT COUNT(*) c FROM contradictions WHERE resolved=0").fetchone()["c"])

        recent = self.db.execute("SELECT latency_ms FROM retrieval_traces ORDER BY ts_ms DESC LIMIT 50").fetchall()
        lat = [int(r["latency_ms"]) for r in recent] if recent else []
        avg_lat = int(sum(lat) / len(lat)) if lat else 0
        p95_lat = int(sorted(lat)[max(0, int(len(lat) * 0.95) - 1)]) if lat else 0

        waste_rows = self.db.execute("SELECT waste FROM packs ORDER BY updated_at_ms DESC LIMIT 30").fetchall()
        wastes = [float(r["waste"]) for r in waste_rows] if waste_rows else []
        avg_waste = float(sum(wastes) / len(wastes)) if wastes else 0.0

        db_bytes = self.db.size_bytes()

        return {
            "schema_version": SCHEMA_VERSION,
            "db_path": self.db.path,
            "db_size_bytes": db_bytes,
            "episodes": ep,
            "facts": facts,
            "profile_hints": hints,
            "pins": pins,
            "packs": packs,
            "contradictions_open": contra_open,
            "retrieval_latency_ms_avg_50": avg_lat,
            "retrieval_latency_ms_p95_50": p95_lat,
            "pack_waste_avg_30": avg_waste,
            "episodes_fts_enabled": self.episodes_fts_enabled,
            "facts_fts_enabled": self.facts_fts_enabled,
            "ts_ms": now,
        }

    def get_trace(self, trace_id: str) -> Optional[Dict[str, Any]]:
        cur = self.db.execute("SELECT * FROM retrieval_traces WHERE id=?", (trace_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def list_traces(self, thread_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        cur = self.db.execute(
            "SELECT * FROM retrieval_traces WHERE thread_id=? ORDER BY ts_ms DESC LIMIT ?",
            (thread_id, int(limit)),
        )
        return [dict(r) for r in cur.fetchall()]

    def _write_trace(
        self,
        trace_id: str,
        thread_id: str,
        query: str,
        budget_tokens: int,
        results: List[Dict[str, Any]],
        pack_id: Optional[int],
        latency_ms: int,
    ) -> None:
        with self.db.transact() as conn:
            conn.execute(
                "INSERT INTO retrieval_traces(id, thread_id, query, ts_ms, budget_tokens, results_json, pack_id, latency_ms) VALUES(?,?,?,?,?,?,?,?)",
                (trace_id, thread_id, query, self.db.now_ms(), int(budget_tokens), json.dumps(results, ensure_ascii=False), pack_id, int(latency_ms)),
            )

class MemoryFabricCompat:
    """Compatibility shim for older Thomas memory call sites."""

    def __init__(self, fabric: MemoryFabricV2):
        self.fabric = fabric

    @classmethod
    def from_root_path(cls, root_path: str) -> "MemoryFabricCompat":
        return cls(MemoryFabricV2(root_path=root_path))

    def ingest_message(self, thread_id: str, role: str, content: str, ts_ms: Optional[int] = None, base_salience: float = 1.0) -> int:
        return self.fabric.ingest_episode(thread_id=thread_id, role=role, content=content, ts_ms=ts_ms, base_salience=base_salience)

    def build_memory_pack(self, thread_id: str, query: str, budget_tokens: int = 800) -> Tuple[str, str]:
        res = self.fabric.retrieve(thread_id=thread_id, query=query, budget_tokens=budget_tokens)
        return res.pack_text, res.trace_id
