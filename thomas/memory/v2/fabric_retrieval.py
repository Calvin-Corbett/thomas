from __future__ import annotations

import json
import logging
from typing import Any

from .fabric_utils import _age_hours, _now_ms, _overlap_boost, _tokenize
from .scoring import SalienceInputs
from .scoring import score as salience_score
from .token import estimate_tokens, normalize_lines, redundancy_ratio
from .types import RetrievalItem, RetrievalResult

log = logging.getLogger(__name__)


class MemoryFabricV2Retrieval:
    """Mixin providing retrieval, packing, and diagnostics methods for MemoryFabricV2.

    This module handles:
    - Query-based retrieval (episodes, facts, profile hints)
    - Full-text search integration
    - Pack building and token optimization
    - Pack persistence
    - Retrieval traces and diagnostics
    """

    def retrieve(self, thread_id: str, query: str, budget_tokens: int | None = None) -> RetrievalResult:
        now_ms = _now_ms()
        settings = self.get_thread_settings(thread_id)

        if budget_tokens is None:
            budget_tokens = settings.max_pack_tokens

        trace_id = str(__import__("uuid").uuid4())

        if not settings.enabled:
            latency_ms = _now_ms() - now_ms
            return RetrievalResult(
                pack_text="",
                trace_id=trace_id,
                items=[],
                latency_ms=latency_ms,
                pack_tokens_est=0,
            )

        start_ms = now_ms

        if settings.pins_only:
            pins = self.list_pins(thread_id=thread_id, limit=settings.max_results)
            items: list[RetrievalItem] = []
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
            pack = self._build_pack(
                thread_id, query, items, budget_tokens=budget_tokens, include_profile=settings.include_profile
            )
            pack_id = None
            latency_ms = _now_ms() - start_ms
            self._write_trace(
                trace_id=trace_id,
                thread_id=thread_id,
                query=query,
                budget_tokens=budget_tokens,
                results=[item.__dict__ for item in items],
                pack_id=pack_id,
                latency_ms=latency_ms,
            )
            return RetrievalResult(
                pack_text=pack,
                trace_id=trace_id,
                items=items,
                latency_ms=latency_ms,
                pack_tokens_est=estimate_tokens(pack),
            )

        query_toks = _tokenize(query)

        items = []

        if settings.include_thread:
            ep_results = self._search_episodes(thread_id=thread_id, query=query, limit=settings.max_results)
            for r in ep_results:
                overlap = _overlap_boost(query_toks, r["content"])
                inputs = SalienceInputs(
                    base_salience=float(r["base_salience"]),
                    age_hours=_age_hours(now_ms, int(r["ts_ms"])),
                    half_life_hours=float(r["decay_half_life_hours"]),
                    retrieval_count=int(r["retrieval_count"]),
                    pinned=False,
                    relevance_boost=overlap,
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
                        meta={"ts_ms": int(r["ts_ms"]), "role": r["role"], "score_components": inputs.__dict__},
                    )
                )

        if settings.include_global:
            fact_results = self._search_facts(thread_id=thread_id, query=query, limit=settings.max_results)
            for r in fact_results:
                overlap = _overlap_boost(query_toks, f"{r['subject']} {r['predicate']} {r['obj']}")
                inputs = SalienceInputs(
                    base_salience=float(r["base_salience"]),
                    age_hours=_age_hours(now_ms, int(r["ts_ms"])),
                    half_life_hours=240.0,
                    retrieval_count=int(r["retrieval_count"]),
                    pinned=False,
                    relevance_boost=overlap,
                )
                sc = salience_score(inputs)
                items.append(
                    RetrievalItem(
                        kind="fact",
                        ref_id=str(int(r["id"])),
                        score=sc,
                        snippet=f"FACT: {r['subject']} • {r['predicate']} • {r['obj']} (conf {float(r['confidence']):.2f})",
                        meta={
                            "thread_id": r["thread_id"],
                            "polarity": int(r["polarity"]),
                            "score_components": inputs.__dict__,
                        },
                    )
                )

        if settings.include_profile:
            profile_results = self._get_profile_hints(limit=30)
            for r in profile_results:
                overlap = _overlap_boost(query_toks, f"{r['key']} {r['value']}")
                inputs = SalienceInputs(
                    base_salience=1.0,
                    age_hours=_age_hours(now_ms, int(r["last_seen_ts_ms"])),
                    half_life_hours=720.0,
                    retrieval_count=0,
                    pinned=bool(r["pinned"]),
                    relevance_boost=overlap,
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

        pins = self.list_pins(thread_id=thread_id, limit=50)
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
        items = items[: settings.max_results]

        self._mark_retrieved(items, now_ms)

        pack = self._build_pack(
            thread_id, query, items, budget_tokens=budget_tokens, include_profile=settings.include_profile
        )

        pack_id: int | None = None
        try:
            pack_id = self._upsert_pack(scope="thread", thread_id=thread_id, text=pack)
        except Exception as e:
            log.warning(f"Failed to upsert pack: {e}")

        latency_ms = _now_ms() - start_ms
        self._write_trace(
            trace_id=trace_id,
            thread_id=thread_id,
            query=query,
            budget_tokens=budget_tokens,
            results=[item.__dict__ for item in items],
            pack_id=pack_id,
            latency_ms=latency_ms,
        )

        return RetrievalResult(
            pack_text=pack,
            trace_id=trace_id,
            items=items,
            latency_ms=latency_ms,
            pack_tokens_est=estimate_tokens(pack),
        )

    def _search_episodes(self, thread_id: str, query: str, limit: int) -> list[dict[str, Any]]:
        query_toks = _tokenize(query)
        if not query_toks:
            return (
                self.db.execute(
                    "SELECT * FROM episodes WHERE thread_id=? ORDER BY ts_ms DESC LIMIT ?", (thread_id, int(limit))
                ).fetchall()
                if not query_toks
                else []
            )

        if self.episodes_fts_enabled:
            fts_query = " ".join(query_toks)
            try:
                rows = self.db.execute(
                    """
                    SELECT e.* FROM episodes e
                    INNER JOIN episodes_fts fts ON e.id = fts.rowid
                    WHERE e.thread_id=? AND fts.episodes_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (thread_id, fts_query, int(limit)),
                ).fetchall()
                if rows:
                    return [dict(r) for r in rows]
            except (OSError, RuntimeError):
                self.episodes_fts_enabled = False

        return [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM episodes WHERE thread_id=? ORDER BY ts_ms DESC LIMIT ?", (thread_id, int(limit))
            ).fetchall()
        ]

    def _search_facts(
        self,
        thread_id: str,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        query_toks = _tokenize(query)
        if not query_toks:
            return (
                [
                    dict(r)
                    for r in self.db.execute(
                        "SELECT * FROM semantic_facts WHERE thread_id IS NULL ORDER BY ts_ms DESC LIMIT ?",
                        (int(limit),),
                    ).fetchall()
                ]
                if not query_toks
                else []
            )

        if self.facts_fts_enabled:
            fts_query = " ".join(query_toks)
            try:
                rows = self.db.execute(
                    """
                    SELECT f.* FROM semantic_facts f
                    INNER JOIN semantic_facts_fts fts ON f.id = fts.rowid
                    WHERE f.thread_id IS NULL AND fts.semantic_facts_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_query, int(limit)),
                ).fetchall()
                if rows:
                    return [dict(r) for r in rows]
            except (OSError, RuntimeError):
                self.facts_fts_enabled = False

        return [
            dict(r)
            for r in self.db.execute(
                "SELECT * FROM semantic_facts WHERE thread_id IS NULL ORDER BY ts_ms DESC LIMIT ?", (int(limit),)
            ).fetchall()
        ]

    def _get_profile_hints(self, limit: int = 50) -> list[dict[str, Any]]:
        cur = self.db.execute("SELECT * FROM profile_hints ORDER BY last_seen_ts_ms DESC LIMIT ?", (int(limit),))
        return [dict(r) for r in cur.fetchall()]

    def _mark_retrieved(self, items: list[RetrievalItem], now_ms: int) -> None:
        with self.db.transact() as conn:
            for item in items:
                if item.kind == "episode":
                    conn.execute(
                        "UPDATE episodes SET retrieval_count=retrieval_count+1 WHERE id=?", (int(item.ref_id),)
                    )
                elif item.kind == "fact":
                    conn.execute(
                        "UPDATE semantic_facts SET retrieval_count=retrieval_count+1 WHERE id=?", (int(item.ref_id),)
                    )

    # -----------------------
    # Pack building
    # -----------------------
    def _build_pack(
        self,
        thread_id: str,
        query: str,
        items: list[RetrievalItem],
        budget_tokens: int = 800,
        include_profile: bool = True,
    ) -> str:
        sections = {}
        profile_tokens = 0

        if include_profile:
            profile_hints = self._get_profile_hints(limit=50)
            if profile_hints:
                profile_lines = ["[Profile]"]
                for h in profile_hints:
                    line = f"  {h['key']}: {h['value']}"
                    profile_lines.append(line)
                    profile_tokens += estimate_tokens(line)
                    if profile_tokens > int(budget_tokens * 0.15):
                        break
                sections["profile"] = "\n".join(profile_lines)

        pins = [it for it in items if it.kind == "pin"]
        hints = [it for it in items if it.kind == "hint"]
        facts = [it for it in items if it.kind == "fact"]
        episodes = [it for it in items if it.kind == "episode"]

        remaining_budget = budget_tokens - profile_tokens

        if pins:
            pin_lines = ["[Pins]"]
            for p in pins:
                line = f"  {p.snippet}"
                pin_lines.append(line)
            sections["pins"] = "\n".join(pin_lines)
            remaining_budget = max(0, remaining_budget - estimate_tokens("\n".join(pin_lines)))

        if facts:
            fact_lines = ["[Facts]"]
            for f in facts:
                if estimate_tokens("\n".join(fact_lines)) > remaining_budget:
                    break
                line = f"  {f.snippet}"
                fact_lines.append(line)
            if len(fact_lines) > 1:
                sections["facts"] = "\n".join(fact_lines)
                remaining_budget = max(0, remaining_budget - estimate_tokens("\n".join(fact_lines)))

        if episodes:
            ep_lines = ["[Episodes]"]
            for e in episodes:
                if estimate_tokens("\n".join(ep_lines)) > remaining_budget:
                    break
                line = f"  [{e.meta.get('role', 'unknown')}] {e.snippet}"
                ep_lines.append(line)
            if len(ep_lines) > 1:
                sections["episodes"] = "\n".join(ep_lines)
                remaining_budget = max(0, remaining_budget - estimate_tokens("\n".join(ep_lines)))

        if hints:
            hint_lines = ["[Hints]"]
            for h in hints:
                if estimate_tokens("\n".join(hint_lines)) > remaining_budget:
                    break
                line = f"  {h.snippet}"
                hint_lines.append(line)
            if len(hint_lines) > 1:
                sections["hints"] = "\n".join(hint_lines)

        pack_lines = []
        for key in ["profile", "pins", "facts", "episodes", "hints"]:
            if key in sections:
                pack_lines.append(sections[key])

        return "\n".join(pack_lines).strip() + "\n" if pack_lines else ""

    def _token_efficiency_optimize(self, text: str, target_tokens: int) -> str:
        if estimate_tokens(text) <= target_tokens:
            return text

        lines = normalize_lines(text)
        out: list[str] = []
        for ln in lines:
            out.append(ln)
            if estimate_tokens("\n".join(out)) >= target_tokens:
                out.pop()
                break

        clamped = out
        if not clamped:
            clamped = lines[:20]

        rewritten = "\n".join(clamped).strip() + "\n"

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
                        meta={"ts_ms": int(r["ts_ms"]), "role": r["role"], "score_components": inputs.__dict__},
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
                        meta={
                            "thread_id": r["thread_id"],
                            "polarity": int(r["polarity"]),
                            "score_components": inputs.__dict__,
                        },
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
        from .schema import SCHEMA_VERSION

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
