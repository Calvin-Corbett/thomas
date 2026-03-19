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

            def _add(col: str, ddl: str) -> None:
                if col not in cols:
                    conn.execute(ddl)

            _add(
                "auto_compact_enabled",
                "ALTER TABLE thread_settings ADD COLUMN auto_compact_enabled INTEGER NOT NULL DEFAULT 1",
            )
            _add(
                "auto_compact_episode_threshold",
                "ALTER TABLE thread_settings ADD COLUMN auto_compact_episode_threshold INTEGER NOT NULL DEFAULT 2000",
            )
            _add(
                "auto_compact_min_interval_hours",
                "ALTER TABLE thread_settings ADD COLUMN auto_compact_min_interval_hours REAL NOT NULL DEFAULT 24",
            )
            _add(
                "auto_optimize_enabled",
                "ALTER TABLE thread_settings ADD COLUMN auto_optimize_enabled INTEGER NOT NULL DEFAULT 1",
            )
            _add(
                "auto_optimize_waste_threshold",
                "ALTER TABLE thread_settings ADD COLUMN auto_optimize_waste_threshold REAL NOT NULL DEFAULT 0.22",
            )
            _add(
                "auto_optimize_min_interval_hours",
                "ALTER TABLE thread_settings ADD COLUMN auto_optimize_min_interval_hours REAL NOT NULL DEFAULT 12",
            )

        if current < 3 <= target:
            cols = [r[1] for r in conn.execute("PRAGMA table_info(thread_settings)").fetchall()]
            if "include_thread" not in cols:
                conn.execute("ALTER TABLE thread_settings ADD COLUMN include_thread INTEGER NOT NULL DEFAULT 1")

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
            include_thread=bool(row["include_thread"]),
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

    def update_thread_settings(self, thread_id: str, patch: dict[str, Any]) -> MemorySettings:
        allowed = {
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
        }
        fields = {k: patch[k] for k in patch if k in allowed}
        if not fields:
            return self.get_thread_settings(thread_id)

        enabled_set = int("enabled" in fields)
        include_thread_set = int("include_thread" in fields)
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
        include_thread_val = int(bool(fields.get("include_thread", False)))
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
                    include_thread=CASE WHEN ? THEN ? ELSE include_thread END,
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
                    include_thread_set,
                    include_thread_val,
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
        ts_ms: int | None = None,
        base_salience: float = 1.0,
        decay_half_life_hours: float | None = None,
        source: str = "chat",
        also_extract_profile: bool = True,
    ) -> int:
        ts = ts_ms or _now_ms()
        tokens = estimate_tokens(content)
        settings = self.get_thread_settings(thread_id)
        half_life = (
            float(decay_half_life_hours) if decay_half_life_hours is not None else float(settings.decay_half_life_hours)
        )

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
        thread_id: str | None,
        subject: str,
        predicate: str,
        obj: str,
        polarity: int = 1,
        confidence: float = 0.7,
        provenance_episode_id: int | None = None,
        ts_ms: int | None = None,
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
                (
                    thread_id,
                    ts,
                    subject,
                    predicate,
                    obj,
                    polarity,
                    confidence,
                    provenance_episode_id,
                    float(base_salience),
                    0,
                    self.db.now_ms(),
                ),
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
        thread_id: str | None,
        hints: list[dict[str, Any]],
        source_episode_id: int | None,
        ts_ms: int | None = None,
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
                          value=CASE
                              WHEN excluded.confidence >= profile_hints.confidence THEN excluded.value
                              ELSE profile_hints.value
                          END,
                          confidence=max(profile_hints.confidence, excluded.confidence),
                          last_seen_ts_ms=max(profile_hints.last_seen_ts_ms, excluded.last_seen_ts_ms),
                          source_episode_id=CASE
                              WHEN excluded.confidence >= profile_hints.confidence
                                  THEN COALESCE(excluded.source_episode_id, profile_hints.source_episode_id)
                              ELSE profile_hints.source_episode_id
                          END,
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
    def add_pin(self, kind: str, ref_id: str, thread_id: str | None = None, note: str = "") -> int:
        with self.db.transact() as conn:
            cur = conn.execute(
                "INSERT INTO pins(kind, ref_id, thread_id, note, created_at_ms) VALUES(?,?,?,?,?)",
                (kind, str(ref_id), thread_id, note, self.db.now_ms()),
            )
            return int(cur.lastrowid)

    def remove_pin(self, pin_id: int) -> None:
        with self.db.transact() as conn:
            conn.execute("DELETE FROM pins WHERE id=?", (int(pin_id),))

    def list_pins(self, thread_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
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
    def _contradiction_severity_route(self, *, score: float, reason: str) -> tuple[str, str]:
        return contradiction_severity_route(score=float(score), reason=str(reason or ""))

    def _upsert_contradiction_review_state(
        self,
        *,
        cid: int,
        severity: str,
        route: str,
        status: str = "pending",
        actor: str = "system",
        note: str = "",
    ) -> None:
        upsert_contradiction_review_state(
            self.db,
            cid=int(cid),
            severity=str(severity),
            route=str(route),
            status=str(status),
            actor=str(actor),
            note=str(note),
        )

    def _record_contradiction(
        self,
        left_kind: str,
        left_id: str,
        right_kind: str,
        right_id: str,
        score: float,
        reason: str,
    ) -> None:
        severity, route = self._contradiction_severity_route(score=float(score), reason=str(reason or ""))
        with self.db.transact() as conn:
            cur = conn.execute(
                "INSERT INTO contradictions(left_kind,left_id,right_kind,right_id,score,reason,created_at_ms,resolved) VALUES(?,?,?,?,?,?,?,0)",
                (left_kind, str(left_id), right_kind, str(right_id), float(score), str(reason), self.db.now_ms()),
            )
            cid = int(cur.lastrowid)
        if cid > 0:
            self._upsert_contradiction_review_state(
                cid=cid,
                severity=severity,
                route=route,
                status="pending",
                actor="system.detector",
                note="auto_routed",
            )

    def list_contradictions(self, only_open: bool = True, limit: int = 50) -> list[dict[str, Any]]:
        return list_contradictions_with_reviews(
            self.db,
            only_open=bool(only_open),
            limit=int(limit),
        )

    def list_contradictions_for_review(
        self,
        *,
        status: str | None = None,
        severity: str | None = None,
        route: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return list_contradictions_for_review_rows(
            self.db,
            status=str(status or "").strip() or None,
            severity=str(severity or "").strip() or None,
            route=str(route or "").strip() or None,
            limit=int(limit),
        )

    def review_contradiction(
        self,
        cid: int,
        *,
        decision: str,
        actor: str = "system",
        reason: str = "",
    ) -> bool:
        return apply_contradiction_review(
            self.db,
            int(cid),
            decision=str(decision or ""),
            actor=str(actor or "system"),
            reason=str(reason or ""),
        )

    def resolve_contradiction(self, cid: int, resolved: bool = True) -> None:
        action = "approve" if bool(resolved) else "reopen"
        if not self.review_contradiction(int(cid), decision=action, actor="system.resolve", reason="legacy_resolve"):
            with self.db.transact() as conn:
                conn.execute("UPDATE contradictions SET resolved=? WHERE id=?", (1 if resolved else 0, int(cid)))

        # -----------------------

    # Auto maintenance
    # -----------------------
    def _get_maintenance_state(self, thread_id: str) -> dict[str, Any]:
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

    def _update_maintenance_state(
        self, thread_id: str, *, last_compact_ts_ms: int | None = None, last_optimize_ts_ms: int | None = None
    ) -> None:
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
                    cnt = int(
                        self.db.execute("SELECT COUNT(*) c FROM episodes WHERE thread_id=?", (thread_id,)).fetchone()[
                            "c"
                        ]
                    )
                    if cnt >= int(settings.auto_compact_episode_threshold):
                        self.compact(thread_id=thread_id)
                        self._update_maintenance_state(thread_id, last_compact_ts_ms=now)
                except (RuntimeError, OSError) as e:
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
                        self.optimize_packs(
                            threshold=float(settings.auto_optimize_waste_threshold), scope="thread", thread_id=thread_id
                        )
                        self._update_maintenance_state(thread_id, last_optimize_ts_ms=now)
                except (RuntimeError, OSError) as e:
                    log.debug("Auto-optimize skipped for thread %s: %s", thread_id, e)

    # -----------------------
    # Retrieval
    # -----------------------
    def retrieve(self, thread_id: str, query: str, budget_tokens: int | None = None) -> RetrievalResult:
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
        pin_items: list[RetrievalItem] = [
            RetrievalItem(
                kind="pin",
                ref_id=str(p["id"]),
                score=2.0,
                snippet=f"PIN({p['kind']}:{p['ref_id']}): {(p.get('note') or '').strip()}".strip(),
                meta=p,
            )
            for p in pins
        ]
        profile_pin_items: list[RetrievalItem] = []
        if settings.include_profile:
            for r in self._get_profile_hints(limit=60):
                if not bool(r["pinned"]):
                    continue
                profile_pin_items.append(
                    RetrievalItem(
                        kind="hint",
                        ref_id=str(r["key"]),
                        score=2.1,
                        snippet=f"PROFILE: {r['key']} = {r['value']} (conf {float(r['confidence']):.2f})",
                        meta={"pinned": True},
                    )
                )

        if settings.pins_only:
            pins_only_items = [*profile_pin_items, *pin_items]
            pack = self._build_pack(
                thread_id,
                query,
                items=pins_only_items,
                budget_tokens=budget,
                include_profile=settings.include_profile,
            )
            latency_ms = int((time.perf_counter() - t0) * 1000)
            self._write_trace(
                trace_id,
                thread_id,
                query,
                budget,
                [it.__dict__ for it in pins_only_items],
                None,
                latency_ms,
            )
            return RetrievalResult(
                pack_text=pack,
                trace_id=trace_id,
                items=pins_only_items,
                latency_ms=latency_ms,
                pack_tokens_est=estimate_tokens(pack),
            )

        # candidates
        ep_rows = self._search_episodes(thread_id, query, settings.max_results * 4) if settings.include_thread else []
        fact_rows = self._search_facts(
            thread_id,
            query,
            include_thread=settings.include_thread,
            include_global=settings.include_global,
            limit=settings.max_results * 3,
        )
        hint_rows = self._get_profile_hints(limit=60) if settings.include_profile else []

        items: list[RetrievalItem] = []

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
            conf = max(0.0, min(1.0, float(r["confidence"])))
            confidence_weight = 0.72 + (0.48 * conf)
            sc = salience_score(inputs) * confidence_weight
            snippet = f"FACT: {r['subject']} • {r['predicate']} • {r['obj']} (conf {float(r['confidence']):.2f})"
            items.append(
                RetrievalItem(
                    kind="fact",
                    ref_id=str(int(r["id"])),
                    score=sc,
                    snippet=snippet,
                    meta={
                        "thread_id": r["thread_id"],
                        "polarity": int(r["polarity"]),
                        "confidence": conf,
                        "confidence_weight": round(confidence_weight, 4),
                        "score_components": inputs.__dict__,
                    },
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
            items.append(
                RetrievalItem(
                    kind="hint",
                    ref_id=str(r["key"]),
                    score=sc,
                    snippet=snippet,
                    meta={"pinned": bool(r["pinned"]), "score_components": inputs.__dict__},
                )
            )

        items.extend(pin_items)

        items.sort(key=lambda it: it.score, reverse=True)
        items = items[: max(10, settings.max_results)]

        pack = self._build_pack(
            thread_id, query, items=items, budget_tokens=budget, include_profile=settings.include_profile
        )

        latency_ms = int((time.perf_counter() - t0) * 1000)

        # update retrieval counts (best effort)
        self._mark_retrieved(items, now)

        pack_id = None
        if pack.strip():
            pack_id = self._upsert_pack(scope="thread", thread_id=thread_id, text=pack)

        self._write_trace(trace_id, thread_id, query, budget, [it.__dict__ for it in items], pack_id, latency_ms)

        return RetrievalResult(
            pack_text=pack, trace_id=trace_id, items=items, latency_ms=latency_ms, pack_tokens_est=estimate_tokens(pack)
        )

    def _search_episodes(self, thread_id: str, query: str, limit: int) -> list[dict[str, Any]]:
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

    def _search_facts(
        self,
        thread_id: str,
        query: str,
        *,
        include_thread: bool,
        include_global: bool,
        limit: int,
    ) -> list[dict[str, Any]]:
        lim = int(max(1, min(500, limit)))
        if not include_thread and not include_global:
            return []

        thread_scope = bool(include_thread)
        global_scope = bool(include_global)

        if self.facts_fts_enabled and query.strip():
            try:
                if thread_scope and global_scope:
                    cur = self.db.execute(
                        """SELECT f.* FROM semantic_facts_fts
                           JOIN semantic_facts f ON f.id = semantic_facts_fts.fact_id
                           WHERE semantic_facts_fts MATCH ? AND (f.thread_id=? OR f.thread_id IS NULL)
                           ORDER BY bm25(semantic_facts_fts) LIMIT ?""",
                        (query, thread_id, lim),
                    )
                elif global_scope:
                    cur = self.db.execute(
                        """SELECT f.* FROM semantic_facts_fts
                           JOIN semantic_facts f ON f.id = semantic_facts_fts.fact_id
                           WHERE semantic_facts_fts MATCH ? AND f.thread_id IS NULL
                           ORDER BY bm25(semantic_facts_fts) LIMIT ?""",
                        (query, lim),
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
        if thread_scope and global_scope:
            cur = self.db.execute(
                """SELECT * FROM semantic_facts
                   WHERE (thread_id=? OR thread_id IS NULL) AND (subject LIKE ? OR predicate LIKE ? OR obj LIKE ?)
                   ORDER BY ts_ms DESC LIMIT ?""",
                (thread_id, q, q, q, lim),
            )
        elif global_scope:
            cur = self.db.execute(
                """SELECT * FROM semantic_facts
                   WHERE thread_id IS NULL AND (subject LIKE ? OR predicate LIKE ? OR obj LIKE ?)
                   ORDER BY ts_ms DESC LIMIT ?""",
                (q, q, q, lim),
            )
        else:
            cur = self.db.execute(
                """SELECT * FROM semantic_facts
                   WHERE thread_id=? AND (subject LIKE ? OR predicate LIKE ? OR obj LIKE ?)
                   ORDER BY ts_ms DESC LIMIT ?""",
                (thread_id, q, q, q, lim),
            )
        return [dict(r) for r in cur.fetchall()]

    def _get_profile_hints(self, limit: int = 50) -> list[dict[str, Any]]:
        cur = self.db.execute(
            "SELECT * FROM profile_hints ORDER BY pinned DESC, confidence DESC, last_seen_ts_ms DESC LIMIT ?",
            (int(limit),),
        )
        return [dict(r) for r in cur.fetchall()]

    def _mark_retrieved(self, items: list[RetrievalItem], now_ms: int) -> None:
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
    def _build_pack(
        self, thread_id: str, query: str, items: list[RetrievalItem], budget_tokens: int, include_profile: bool
    ) -> str:
        # Stable high-density format
        profile_lines: list[str] = []
        if include_profile:
            hints = [it for it in items if it.kind == "hint"]
            for it in hints[:12]:
                profile_lines.append(f"- {it.snippet.replace('PROFILE:','').strip()}")
        pins = [it for it in items if it.kind == "pin"]
        facts = [it for it in items if it.kind == "fact"]
        episodes = [it for it in items if it.kind == "episode"]

        lines: list[str] = []
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
        clamped: list[str] = []
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
            out: list[str] = []
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
