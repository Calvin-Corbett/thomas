                out.append(ln)
            clamped = out

        rewritten = "\n".join(clamped).strip() + "\n"

        # if still too long, prefer profile/pins/facts and early episodes
        if estimate_tokens(rewritten) > target_tokens:
            keep: list[str] = []
            section = None
            for ln in normalize_lines(rewritten):
                if ln.startswith("[") and ln.endswith("]"):
                    section = ln
                if section == "[Episodes]" and estimate_tokens("\n".join(keep)) > int(target_tokens * 0.85):
                    break
                keep.append(ln)
            rewritten = "\n".join(keep).strip() + "\n"

        return rewritten

    def _upsert_pack(self, scope: str, thread_id: str | None, text: str) -> int:
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

    def optimize_packs(
        self, threshold: float = 0.22, scope: str | None = None, thread_id: str | None = None
    ) -> dict[str, Any]:
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
                "SELECT id, text, tokens_est, waste FROM packs " "ORDER BY updated_at_ms DESC LIMIT 200"
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

    def compact(self, thread_id: str | None = None) -> dict[str, Any]:
        """Rebuild a representative pack from salient items (thread or global)."""
        now = _now_ms()

        if thread_id:
            settings = self.get_thread_settings(thread_id)
            ep = (
                self.db.execute(
                    "SELECT * FROM episodes WHERE thread_id=? ORDER BY ts_ms DESC LIMIT 250",
                    (thread_id,),
                ).fetchall()
                if settings.include_thread
                else []
            )
            if settings.include_thread and settings.include_global:
                facts = self.db.execute(
                    "SELECT * FROM semantic_facts WHERE thread_id=? OR thread_id IS NULL ORDER BY ts_ms DESC LIMIT 200",
                    (thread_id,),
                ).fetchall()
            elif settings.include_thread:
                facts = self.db.execute(
                    "SELECT * FROM semantic_facts WHERE thread_id=? ORDER BY ts_ms DESC LIMIT 200",
                    (thread_id,),
                ).fetchall()
            elif settings.include_global:
                facts = self.db.execute(
                    "SELECT * FROM semantic_facts WHERE thread_id IS NULL ORDER BY ts_ms DESC LIMIT 200"
                ).fetchall()
            else:
                facts = []
            hints = self._get_profile_hints(50) if settings.include_profile else []
            pins = self.list_pins(thread_id=thread_id, limit=200)
            if not settings.include_thread:
                pins = [p for p in pins if p.get("thread_id") is None]

            items: list[RetrievalItem] = []
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
                items.append(
                    RetrievalItem(
                        kind="episode",
                        ref_id=str(int(r["id"])),
                        score=sc,
                        snippet=snippet,
                        meta={"ts_ms": int(r["ts_ms"]), "role": r["role"]},
                    )
                )

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
                items.append(
                    RetrievalItem(
                        kind="fact",
                        ref_id=str(int(r["id"])),
                        score=sc,
                        snippet=f"FACT: {r['subject']} • {r['predicate']} • {r['obj']} (conf {float(r['confidence']):.2f})",
                        meta={"thread_id": r["thread_id"], "polarity": int(r["polarity"])},
                    )
                )

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
                items.append(
                    RetrievalItem(
                        kind="hint",
                        ref_id=str(r["key"]),
                        score=sc,
                        snippet=f"PROFILE: {r['key']} = {r['value']} (conf {float(r['confidence']):.2f})",
                        meta={"pinned": bool(r["pinned"]), "score_components": inputs.__dict__},
                    )
                )

            for p in pins:
                items.append(
                    RetrievalItem(
                        kind="pin",
                        ref_id=str(p["id"]),
                        score=2.0,
                        snippet=f"PIN({p['kind']}:{p['ref_id']}): {(p.get('note') or '').strip()}".strip(),
                        meta=p,
                    )
                )

            items.sort(key=lambda it: it.score, reverse=True)
            items = items[: max(25, settings.max_results)]
            pack = self._build_pack(
                thread_id, "", items, budget_tokens=settings.max_pack_tokens, include_profile=settings.include_profile
            )
            pack_id = self._upsert_pack(scope="thread", thread_id=thread_id, text=pack)
            return {
                "pack_id": pack_id,
                "thread_id": thread_id,
                "tokens_est": estimate_tokens(pack),
                "waste": redundancy_ratio(normalize_lines(pack)),
            }

        # global pack
        facts = self.db.execute(
            "SELECT * FROM semantic_facts WHERE thread_id IS NULL ORDER BY ts_ms DESC LIMIT 250"
        ).fetchall()
        hints = self._get_profile_hints(80)
        pins = self.list_pins(thread_id=None, limit=200)

        items: list[RetrievalItem] = []
        for r in hints:
            hint_inputs = SalienceInputs(
                base_salience=1.0,
                age_hours=_age_hours(now, int(r["last_seen_ts_ms"])),
                half_life_hours=720.0,
                retrieval_count=0,
                pinned=bool(r["pinned"]),
                relevance_boost=0.0,
            )
            items.append(
                RetrievalItem(
                    kind="hint",
                    ref_id=str(r["key"]),
                    score=1.3 + (0.8 if bool(r["pinned"]) else 0.0),
                    snippet=f"PROFILE: {r['key']} = {r['value']} (conf {float(r['confidence']):.2f})",
                    meta={"pinned": bool(r["pinned"]), "score_components": hint_inputs.__dict__},
                )
            )
        for r in facts:
            items.append(
                RetrievalItem(
                    kind="fact",
                    ref_id=str(int(r["id"])),
                    score=1.1,
                    snippet=f"FACT: {r['subject']} • {r['predicate']} • {r['obj']} (conf {float(r['confidence']):.2f})",
                    meta={"thread_id": None},
                )
            )
        for p in pins:
            items.append(
                RetrievalItem(
                    kind="pin",
                    ref_id=str(p["id"]),
                    score=2.0,
                    snippet=f"PIN({p['kind']}:{p['ref_id']}): {(p.get('note') or '').strip()}".strip(),
                    meta=p,
                )
            )

        items.sort(key=lambda it: it.score, reverse=True)
        pack = self._build_pack(
            thread_id="GLOBAL", query="", items=items[:120], budget_tokens=1500, include_profile=True
        )
        pack_id = self._upsert_pack(scope="global", thread_id=None, text=pack)
        return {
            "pack_id": pack_id,
            "scope": "global",
            "tokens_est": estimate_tokens(pack),
            "waste": redundancy_ratio(normalize_lines(pack)),
        }

    # -----------------------
    # Health / diagnostics
    # -----------------------
    def health(self) -> dict[str, Any]:
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

    def get_trace(self, trace_id: str) -> dict[str, Any] | None:
        cur = self.db.execute("SELECT * FROM retrieval_traces WHERE id=?", (trace_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    def list_traces(self, thread_id: str, limit: int = 50) -> list[dict[str, Any]]:
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
        results: list[dict[str, Any]],
        pack_id: int | None,
        latency_ms: int,
    ) -> None:
        with self.db.transact() as conn:
            conn.execute(
                "INSERT INTO retrieval_traces(id, thread_id, query, ts_ms, budget_tokens, results_json, pack_id, latency_ms) VALUES(?,?,?,?,?,?,?,?)",
                (
                    trace_id,
                    thread_id,
                    query,
                    self.db.now_ms(),
                    int(budget_tokens),
                    json.dumps(results, ensure_ascii=False),
                    pack_id,
                    int(latency_ms),
                ),
            )
