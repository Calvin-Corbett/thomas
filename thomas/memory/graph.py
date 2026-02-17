"""Knowledge graph store and entity extraction.

Wraps DerivedDB graph operations with higher-level methods for
entity extraction from conversation text and graph traversal.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from thomas.memory.store import DerivedDB

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class Entity:
    """An extracted entity from text."""
    type_name: str
    key: str
    label: str


@dataclass
class Triple:
    """An extracted relationship triple."""
    subject: Entity
    relation: str
    object: Entity
    confidence: float = 0.5


@dataclass
class GraphContext:
    """Packed graph context for injection into LLM prompt."""
    entities: List[Dict[str, Any]] = field(default_factory=list)
    relations: List[Dict[str, Any]] = field(default_factory=list)
    summary: str = ""


# ---------------------------------------------------------------------------
# Entity extraction — regex-based (no LLM dependency)
# ---------------------------------------------------------------------------

# Patterns for extracting entities from conversation text
_ENTITY_PATTERNS: Dict[str, List[re.Pattern]] = {
    "Project": [
        re.compile(r"(?:project|repo|repository|codebase)\s+['\"]?(\w[\w\-/.]+)['\"]?", re.I),
        re.compile(r"(?:working on|building|developing)\s+['\"]?(\w[\w\-/.]+)['\"]?", re.I),
    ],
    "Concept": [
        re.compile(r"(?:uses?|using|implement|with)\s+([\w\-]+(?:\s+[\w\-]+)?)\s+(?:for|to|in)", re.I),
    ],
    "User": [
        re.compile(r"(?:my name is|I'm|I am)\s+(\w+)", re.I),
    ],
    "Preference": [
        re.compile(r"(?:I (?:prefer|like|want|use))\s+(.+?)(?:\.|$)", re.I),
    ],
    "Task": [
        re.compile(r"(?:TODO|FIXME|HACK|task):\s*(.+?)(?:\n|$)", re.I),
    ],
}

# Relation patterns: (subject_type, relation, object_type, pattern)
_RELATION_PATTERNS: List[Tuple[str, str, str, re.Pattern]] = [
    ("Project", "uses", "Concept",
     re.compile(r"(?:project|repo)\s+(\w+)\s+(?:uses?|with)\s+(\w[\w\s]*\w)", re.I)),
    ("User", "prefers", "Concept",
     re.compile(r"(?:I|user)\s+(?:prefer|like)\s+(\w[\w\s]*\w)", re.I)),
    ("User", "works_on", "Project",
     re.compile(r"(?:I'm|I am|user)\s+(?:working on|building)\s+(\w[\w\-/.]+)", re.I)),
]


def extract_entities(text: str) -> List[Entity]:
    """Extract entities from text using regex patterns.

    This is a fast, dependency-free extraction. For better quality,
    use LLM-based extraction via GraphStore.extract_with_llm().
    """
    seen: Set[Tuple[str, str]] = set()
    entities: List[Entity] = []

    for type_name, patterns in _ENTITY_PATTERNS.items():
        for pat in patterns:
            for match in pat.finditer(text):
                value = match.group(1).strip()
                if len(value) < 2 or len(value) > 100:
                    continue
                key = _normalize_key(value)
                if (type_name, key) in seen:
                    continue
                seen.add((type_name, key))
                entities.append(Entity(type_name=type_name, key=key, label=value))

    return entities


def extract_triples(text: str) -> List[Triple]:
    """Extract relationship triples from text using regex patterns."""
    triples: List[Triple] = []

    for subj_type, rel, obj_type, pat in _RELATION_PATTERNS:
        for match in pat.finditer(text):
            groups = match.groups()
            if len(groups) >= 2:
                subj_val = groups[0].strip()
                obj_val = groups[1].strip()
            elif len(groups) == 1:
                # Single capture group patterns
                subj_val = "user"
                obj_val = groups[0].strip()
            else:
                continue

            if len(obj_val) < 2:
                continue

            subj = Entity(type_name=subj_type, key=_normalize_key(subj_val), label=subj_val)
            obj_ = Entity(type_name=obj_type, key=_normalize_key(obj_val), label=obj_val)
            triples.append(Triple(subject=subj, relation=rel, object=obj_, confidence=0.3))

    return triples


def _normalize_key(value: str) -> str:
    """Normalize a value to a stable key."""
    return re.sub(r"[^a-z0-9_]", "_", value.lower().strip())[:80]


# ---------------------------------------------------------------------------
# GraphStore — higher-level graph operations
# ---------------------------------------------------------------------------


class GraphStore:
    """High-level graph operations over DerivedDB.

    Provides entity/relation ingestion and context retrieval
    for memory-augmented conversations.
    """

    def __init__(self, derived: DerivedDB):
        self._db = derived

    def ingest_text(
        self, text: str, event_ids: Optional[List[int]] = None
    ) -> Tuple[int, int]:
        """Extract and store entities + relations from text.

        Returns (entities_added, relations_added).
        """
        entities = extract_entities(text)
        triples = extract_triples(text)

        receipts = event_ids or []
        e_count = 0
        r_count = 0

        # Upsert entities
        node_ids: Dict[Tuple[str, str], int] = {}
        for ent in entities:
            nid = self._db.node_upsert(ent.type_name, ent.key, ent.label)
            node_ids[(ent.type_name, ent.key)] = nid
            e_count += 1

        # Add relations
        for triple in triples:
            src_key = (triple.subject.type_name, triple.subject.key)
            dst_key = (triple.object.type_name, triple.object.key)

            # Ensure both nodes exist
            if src_key not in node_ids:
                nid = self._db.node_upsert(
                    triple.subject.type_name, triple.subject.key, triple.subject.label
                )
                node_ids[src_key] = nid
            if dst_key not in node_ids:
                nid = self._db.node_upsert(
                    triple.object.type_name, triple.object.key, triple.object.label
                )
                node_ids[dst_key] = nid

            self._db.edge_add(
                src_node=node_ids[src_key],
                rel=triple.relation,
                dst_node=node_ids[dst_key],
                confidence=triple.confidence,
                receipts=receipts,
            )
            r_count += 1

        return e_count, r_count

    def get_context(
        self,
        query: str,
        max_entities: int = 10,
        max_hops: int = 1,
    ) -> GraphContext:
        """Retrieve relevant graph context for a query.

        Searches for entities matching the query, then traverses
        edges up to max_hops to build context.
        """
        ctx = GraphContext()

        # Search for nodes matching query terms
        terms = query.lower().split()
        seen_nodes: Set[int] = set()
        seed_nodes: List[Dict[str, Any]] = []

        for term in terms:
            if len(term) < 3:
                continue
            nodes = self._db.nodes_search_label(term, limit=max_entities)
            for n in nodes:
                if n["node_id"] not in seen_nodes:
                    seen_nodes.add(n["node_id"])
                    seed_nodes.append(n)
                    ctx.entities.append(n)

        if not seed_nodes:
            return ctx

        # Traverse edges from seed nodes
        for hop in range(max_hops):
            next_seeds: List[Dict[str, Any]] = []
            # Collect all edges from current seeds
            all_edges: List[Dict[str, Any]] = []
            for node in seed_nodes:
                edges = self._db.edges_from(node["node_id"], limit=20)
                all_edges.extend(edges)

            # Batch-load all destination nodes we haven't seen
            new_dst_ids = [
                e["dst"] for e in all_edges
                if e["dst"] not in seen_nodes
            ]
            if new_dst_ids:
                dst_nodes = self._db.nodes_get_by_ids(new_dst_ids)
            else:
                dst_nodes = {}

            for edge in all_edges:
                ctx.relations.append(edge)
                dst_id = edge["dst"]
                if dst_id not in seen_nodes:
                    seen_nodes.add(dst_id)
                    dst_node = dst_nodes.get(dst_id)
                    if dst_node:
                        ctx.entities.append(dst_node)
                        next_seeds.append(dst_node)

            seed_nodes = next_seeds

        # Build summary
        if ctx.entities or ctx.relations:
            parts: List[str] = []
            if ctx.entities:
                ent_strs = [f"{e['type']}:{e['label']}" for e in ctx.entities[:8]]
                parts.append(f"Entities: {', '.join(ent_strs)}")
            if ctx.relations:
                rel_strs = [f"{r['src']}-[{r['rel']}]->{r['dst']}" for r in ctx.relations[:8]]
                parts.append(f"Relations: {', '.join(rel_strs)}")
            ctx.summary = "; ".join(parts)

        return ctx
