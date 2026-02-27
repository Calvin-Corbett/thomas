from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

from agent_memory.graph.store import GraphStore
from agent_memory.indexing.derived_db import DerivedDB
from agent_memory.rerank.features import CandidateFeatures, recency_feature
from agent_memory.rerank.tier1 import Tier1Reranker
from agent_memory.rerank.tier2 import Tier2Reranker
from agent_memory.retrieval.packing import PackConfig, pack_context
from agent_memory.storage.meta_db import MetaDB
from agent_memory.storage.sqlite_log import ImmortalLog
from agent_memory.vector.index import VectorIndex


def _fts_query(text: str) -> str:
    toks = re.findall(r"[A-Za-z0-9_]{3,}", text.lower())
    stop = {
        "what",
        "was",
        "the",
        "and",
        "for",
        "you",
        "your",
        "are",
        "did",
        "just",
        "say",
        "earlier",
        "mentioned",
        "about",
        "with",
        "this",
        "that",
        "from",
        "have",
        "has",
        "how",
        "show",
        "me",
        "my",
        "to",
        "of",
        "in",
        "on",
        "it",
        "is",
        "a",
        "an",
    }
    toks = [t for t in toks if t not in stop]
    toks = toks[:16]
    if not toks:
        return text

    def pref(t: str) -> str:
        # crude stemming via prefix to avoid plural/tense misses
        return t[: max(4, min(6, len(t)))]

    parts = [f"{pref(t)}*" for t in toks]
    return "(" + " OR ".join(parts) + ")"


@dataclass
class RetrievalConfig:
    fts_limit: int = 80
    recent_limit: int = 20
    graph_receipt_limit: int = 120
    final_k: int = 10
    candidate_cap: int = 220
    pack: PackConfig = field(default_factory=PackConfig)


def _etype_bonus(etype: str) -> float:
    et = etype.lower()
    if et in ("user", "instruction", "goal"):
        return 0.20
    if et in ("note", "decision"):
        return 0.12
    return 0.0


def _merge_scores(a: dict[int, float], b: dict[int, float]) -> dict[int, float]:
    out = dict(a)
    for k, v in b.items():
        out[k] = max(out.get(k, 0.0), v)
    return out


class RetrievalPipeline:
    def __init__(
        self,
        log: ImmortalLog,
        meta: MetaDB,
        base_db: DerivedDB,
        delta_db: DerivedDB,
        tier1: Tier1Reranker,
        tier2: Tier2Reranker,
        cfg: RetrievalConfig = RetrievalConfig(),
    ):
        self.log = log
        self.meta = meta
        self.base_db = base_db
        self.delta_db = delta_db
        self.cfg = cfg
        self.tier1 = tier1
        self.tier2 = tier2
        self.vec_base = VectorIndex(base_db)
        self.vec_delta = VectorIndex(delta_db)
        self.graph_base = GraphStore(base_db)
        self.graph_delta = GraphStore(delta_db)

    def _pins(self) -> list[tuple[str, str]]:
        return [(k, txt) for k, txt, _ in self.meta.pin_list()]

    def _l2_summary(self, thread: str) -> str | None:
        # Prefer base rollup then delta rollup
        k = f"thread:{thread}:weekly"
        s = self.delta_db.rollup_get(k)
        if s:
            return s
        return self.base_db.rollup_get(k)

    def query(self, thread: str, mode: str, text: str) -> dict[str, Any]:
        now = int(time.time())
        query_text = self.meta.lex_translate(text)

        # Scouts
        recent = self.log.recent_events(thread, limit=self.cfg.recent_limit)
        recent_ids = [e.id for e in recent]

        # keyword search
        q = _fts_query(query_text)
        fts_hits = self.log.search_fts(q, thread=thread, limit=self.cfg.fts_limit)
        fts_scores = {eid: score for eid, score in fts_hits}

        # graph receipts (base+delta) via label substring
        graph_ids = []
        if len(query_text) >= 3:
            graph_ids.extend(self.graph_delta.related_receipts(query_text[:32], max_hops=2))
            graph_ids.extend(self.graph_base.related_receipts(query_text[:32], max_hops=2))
        # uniq
        gset = set()
        guniq = []
        for x in graph_ids:
            if x not in gset:
                gset.add(x)
                guniq.append(x)
        graph_ids = guniq[: self.cfg.graph_receipt_limit]
        graph_scores = {eid: 0.7 for eid in graph_ids}  # conservative boost

        # Vector candidates: bound to recent + fts + graph + recency window
        candidate_ids = []
        for x in recent_ids + list(fts_scores.keys()) + graph_ids:
            if x not in candidate_ids:
                candidate_ids.append(x)

        # Expand with recent global if deep mode
        if mode in ("deep", "learning"):
            base_more = self.base_db.vec_candidates_by_thread(thread, limit=700)
            for x in base_more:
                if x not in candidate_ids:
                    candidate_ids.append(x)
                if len(candidate_ids) >= 1400:
                    break

        # Hard cap before expensive scoring
        candidate_ids = candidate_ids[: self.cfg.candidate_cap]

        # Vector similarity from base+delta
        vec_scores = {}
        if candidate_ids:
            vb = self.vec_base.query(query_text, candidate_ids)
            vd = self.vec_delta.query(query_text, candidate_ids)
            vec_scores = _merge_scores(vb, vd)

        # Build features
        feats: list[CandidateFeatures] = []
        pins = self._pins()
        pinned_ids = set()  # pins are text, not IDs; set later via search (v4)
        for eid in candidate_ids:
            ev = self.log.get_event(eid)
            if not ev:
                continue
            if ev.thread != thread:
                continue
            f = CandidateFeatures(
                eid=eid,
                fts=float(fts_scores.get(eid, 0.0)),
                vec=float(vec_scores.get(eid, 0.0)),
                graph=float(graph_scores.get(eid, 0.0)),
                recency_s=recency_feature(now, ev.ts_utc),
                etype_bonus=_etype_bonus(ev.etype),
                thread_match=1.0,
                pinned_bonus=0.0,
                prior_useful=0.0,
            )
            feats.append(f)

        # Tier 1 -> shortlist
        ranked1 = self.tier1.rank(feats)
        shortlist = ranked1[: max(self.cfg.final_k * 4, 40)]
        shortlist_ids = [eid for eid, _ in shortlist]

        # Tier 2 optional rerank
        if mode in ("deep", "learning") and self.tier2.enabled:
            id_to_feat = {f.eid: f for f in feats}
            feats2 = [id_to_feat[eid] for eid in shortlist_ids if eid in id_to_feat]
            ranked2 = self.tier2.rank(feats2)
            ranked = ranked2
        else:
            ranked = shortlist

        selected_ids = [eid for eid, _ in ranked[: self.cfg.final_k]]

        # Receipts (verbatim from log)
        receipts = []
        for eid in selected_ids:
            ev = self.log.get_event(eid)
            if not ev:
                continue
            receipts.append(
                {
                    "event_id": ev.id,
                    "thread": ev.thread,
                    "ts_utc": ev.ts_utc,
                    "etype": ev.etype,
                    "text": ev.text,
                }
            )

        # Pack context
        packed = pack_context(
            mode=mode,
            pins=[(k, txt) for k, txt, _ in self.meta.pin_list()],
            l2_summary=self._l2_summary(thread),
            receipts=receipts,
            recent_turns=[{"etype": e.etype, "text": e.text} for e in recent[: self.cfg.pack.include_recent_turns]],
            cfg=self.cfg.pack,
        )

        # Trace (bounded)
        trace_cands = []
        # store only top N candidate feature rows
        for f in feats[: min(len(feats), 80)]:
            trace_cands.append(
                {
                    "eid": f.eid,
                    **f.to_dict(),
                }
            )
        trace = {
            "thread": thread,
            "mode": mode,
            "query": query_text,
            "selected": selected_ids,
            "candidates": trace_cands,
        }
        self.meta.trace_add(thread=thread, mode=mode, query=query_text, trace=trace)

        return {"packed": packed["packed"], "selected": selected_ids, "trace": trace}
