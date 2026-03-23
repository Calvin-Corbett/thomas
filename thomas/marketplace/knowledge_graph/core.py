"""Knowledge graph with triples, entities, relations, and SPARQL-like queries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Triple:
    """RDF-like triple (subject, predicate, object)."""

    subject: str
    predicate: str
    obj: str
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __hash__(self):
        return hash((self.subject, self.predicate, self.obj))

    def __eq__(self, other):
        return self.subject == other.subject and self.predicate == other.predicate and self.obj == other.obj


class Entity:
    """Knowledge graph entity."""

    def __init__(self, entity_id: str, entity_type: str = "Thing"):
        self.entity_id = entity_id
        self.entity_type = entity_type
        self.properties: dict[str, Any] = {}
        self.aliases: list[str] = []
        self.confidence_score: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "properties": self.properties,
            "aliases": self.aliases,
            "confidence": self.confidence_score,
        }


class Relation:
    """Relation between entities."""

    def __init__(self, relation_type: str):
        self.relation_type = relation_type
        self.description: str = ""
        self.inverse_relation: str | None = None
        self.symmetric: bool = False
        self.transitive: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "relation_type": self.relation_type,
            "description": self.description,
            "symmetric": self.symmetric,
            "transitive": self.transitive,
        }


class KnowledgeGraph:
    """Knowledge graph store."""

    def __init__(self, name: str = "default"):
        self.name = name
        self.triples: set[Triple] = set()
        self.entities: dict[str, Entity] = {}
        self.relations: dict[str, Relation] = {}
        self._index: dict[str, list[Triple]] = {}  # subject -> triples

    def add_entity(self, entity: Entity) -> None:
        """Add entity to graph."""
        self.entities[entity.entity_id] = entity

    def add_relation_type(self, relation: Relation) -> None:
        """Add relation type."""
        self.relations[relation.relation_type] = relation

    def add_triple(self, triple: Triple) -> None:
        """Add triple to graph."""
        # Add entities if not exist
        if triple.subject not in self.entities:
            self.add_entity(Entity(triple.subject))
        if triple.obj not in self.entities:
            self.add_entity(Entity(triple.obj))

        self.triples.add(triple)
        self._build_index()

    def add_fact(self, subject: str, predicate: str, obj: str, confidence: float = 1.0) -> None:
        """Add a fact as triple."""
        triple = Triple(subject, predicate, obj, confidence)
        self.add_triple(triple)

    def remove_triple(self, triple: Triple) -> None:
        """Remove triple from graph."""
        self.triples.discard(triple)
        self._build_index()

    def _build_index(self) -> None:
        """Rebuild subject index."""
        self._index = {}
        for triple in self.triples:
            if triple.subject not in self._index:
                self._index[triple.subject] = []
            self._index[triple.subject].append(triple)

    def query_triples(
        self, subject: str | None = None, predicate: str | None = None, obj: str | None = None
    ) -> list[Triple]:
        """Query triples with pattern matching."""
        results = []
        for triple in self.triples:
            if subject and triple.subject != subject:
                continue
            if predicate and triple.predicate != predicate:
                continue
            if obj and triple.obj != obj:
                continue
            results.append(triple)
        return results

    def get_outgoing(self, entity_id: str) -> list[Triple]:
        """Get outgoing triples from entity."""
        return self._index.get(entity_id, [])

    def get_incoming(self, entity_id: str) -> list[Triple]:
        """Get incoming triples to entity."""
        results = []
        for triple in self.triples:
            if triple.obj == entity_id:
                results.append(triple)
        return results

    def get_neighbors(self, entity_id: str, relation: str | None = None) -> list[str]:
        """Get neighboring entities."""
        neighbors = []
        for triple in self.get_outgoing(entity_id):
            if relation is None or triple.predicate == relation:
                neighbors.append(triple.obj)
        return neighbors

    def find_path(self, start: str, end: str, max_hops: int = 5) -> list[str] | None:
        """Find path between entities using BFS."""
        if start == end:
            return [start]

        visited = set()
        queue = [(start, [start])]

        while queue:
            current, path = queue.pop(0)

            if len(path) > max_hops:
                continue

            for neighbor in self.get_neighbors(current):
                if neighbor == end:
                    return path + [end]

                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))

        return None

    def get_schema(self) -> dict[str, Any]:
        """Get graph schema information."""
        relation_counts = {}
        for triple in self.triples:
            relation = triple.predicate
            relation_counts[relation] = relation_counts.get(relation, 0) + 1

        return {
            "entities": len(self.entities),
            "triples": len(self.triples),
            "relations": len(self.relations),
            "relation_distribution": relation_counts,
        }

    def get_entity_info(self, entity_id: str) -> dict[str, Any] | None:
        """Get detailed entity information."""
        entity = self.entities.get(entity_id)
        if not entity:
            return None

        return {
            "entity": entity.to_dict(),
            "outgoing": [{"predicate": t.predicate, "target": t.obj} for t in self.get_outgoing(entity_id)],
            "incoming": [{"predicate": t.predicate, "source": t.subject} for t in self.get_incoming(entity_id)],
        }

    def infer_transitive(self) -> list[Triple]:
        """Infer transitive relations."""
        new_triples = []
        for relation_name, relation in self.relations.items():
            if not relation.transitive:
                continue

            # Find chains: A -rel-> B -rel-> C => A -rel-> C
            for triple1 in self.query_triples(predicate=relation_name):
                for triple2 in self.query_triples(subject=triple1.obj, predicate=relation_name):
                    inferred = Triple(
                        triple1.subject, relation_name, triple2.obj, min(triple1.confidence, triple2.confidence)
                    )
                    if inferred not in self.triples:
                        new_triples.append(inferred)

        return new_triples
