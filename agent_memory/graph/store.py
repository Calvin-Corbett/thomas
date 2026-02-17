from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agent_memory.indexing.derived_db import DerivedDB
from agent_memory.graph.extract import extract_edges

@dataclass
class GraphConfig:
    max_edges_per_event: int = 8

class GraphStore:
    def __init__(self, db: DerivedDB, cfg: GraphConfig = GraphConfig()):
        self.db = db
        self.cfg = cfg

    def ingest_event(self, event_id: int, text: str, ts_utc: int, thread: str, user_asserted: bool = False) -> None:
        edges = extract_edges(text)[: self.cfg.max_edges_per_event]
        receipts = [{"event_id": event_id, "thread": thread, "ts_utc": ts_utc}]
        for e in edges:
            src_t, src_k, src_label = e["src"]
            dst_t, dst_k, dst_label = e["dst"]
            src_id = self.db.node_upsert(src_t, src_k, src_label, user_asserted=user_asserted)
            dst_id = self.db.node_upsert(dst_t, dst_k, dst_label, user_asserted=user_asserted)
            self.db.edge_add(src_id, e["rel"], dst_id, confidence=float(e.get("confidence", 0.5)), user_asserted=user_asserted, receipts=receipts)

    def related_receipts(self, like_label: str, max_hops: int = 2, limit_edges: int = 80) -> List[int]:
        # naive: find nodes by label substring, hop outward, collect receipts event_ids
        nodes = self.db.nodes_search_label(like_label, limit=12)
        receipts: List[int] = []
        seen_edges = 0
        seen_nodes = set()
        frontier = [n["node_id"] for n in nodes]
        for nid in frontier:
            seen_nodes.add(nid)
        for hop in range(max_hops):
            next_frontier: List[int] = []
            for nid in frontier:
                edges = self.db.edges_from(nid, rel=None, limit=limit_edges)
                for ed in edges:
                    seen_edges += 1
                    if seen_edges > 500:
                        break
                    for r in ed.get("receipts", []):
                        eid = int(r.get("event_id"))
                        receipts.append(eid)
                    dst = int(ed["dst_node"])
                    if dst not in seen_nodes:
                        seen_nodes.add(dst)
                        next_frontier.append(dst)
            frontier = next_frontier
            if not frontier:
                break
        # uniq preserving order
        out = []
        s = set()
        for x in receipts:
            if x not in s:
                s.add(x)
                out.append(x)
        return out[:200]
