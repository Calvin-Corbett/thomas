"""Document database engine with collections, BSON-like documents, and aggregation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Index:
    """Index specification."""

    name: str
    fields: list[tuple[str, int]]  # [(field_name, direction)]
    unique: bool = False


@dataclass
class Document:
    """Document with ID and metadata."""

    doc_id: str
    data: dict[str, Any]
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        result = {"_id": self.doc_id}
        result.update(self.data)
        result["_created_at"] = self.created_at.isoformat()
        result["_updated_at"] = self.updated_at.isoformat()
        return result


class Collection:
    """Collection of documents with indexes and query capabilities."""

    def __init__(self, name: str):
        self.name = name
        self.docs: dict[str, Document] = {}
        self.indexes: dict[str, Index] = {}
        self._auto_id_counter = 0

    def insert_one(self, doc: dict[str, Any], doc_id: str | None = None) -> str:
        """Insert a single document. Returns document ID."""
        if doc_id is None:
            self._auto_id_counter += 1
            doc_id = f"{self.name}_{self._auto_id_counter}"

        if doc_id in self.docs:
            raise ValueError(f"Document with ID {doc_id} already exists")

        self.docs[doc_id] = Document(doc_id=doc_id, data=dict(doc))
        self._update_indexes(doc_id)
        return doc_id

    def insert_many(self, docs: list[dict[str, Any]]) -> list[str]:
        """Insert multiple documents. Returns list of IDs."""
        ids = []
        for doc in docs:
            doc_id = self.insert_one(doc)
            ids.append(doc_id)
        return ids

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        """Find a single document matching the query."""
        for doc_id, doc in self.docs.items():
            if self._matches_query(doc.data, query):
                return doc.to_dict()
        return None

    def find(self, query: dict[str, Any], limit: int = 0) -> list[dict[str, Any]]:
        """Find all documents matching the query."""
        results = []
        for doc_id, doc in self.docs.items():
            if self._matches_query(doc.data, query):
                results.append(doc.to_dict())
                if limit > 0 and len(results) >= limit:
                    break
        return results

    def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> int:
        """Update a single document. Returns count updated."""
        for doc_id, doc in self.docs.items():
            if self._matches_query(doc.data, query):
                self._apply_update(doc.data, update)
                doc.updated_at = datetime.now()
                self._update_indexes(doc_id)
                return 1
        return 0

    def update_many(self, query: dict[str, Any], update: dict[str, Any]) -> int:
        """Update multiple documents. Returns count updated."""
        count = 0
        for doc_id, doc in self.docs.items():
            if self._matches_query(doc.data, query):
                self._apply_update(doc.data, update)
                doc.updated_at = datetime.now()
                self._update_indexes(doc_id)
                count += 1
        return count

    def delete_one(self, query: dict[str, Any]) -> int:
        """Delete a single document. Returns count deleted."""
        for doc_id, doc in list(self.docs.items()):
            if self._matches_query(doc.data, query):
                del self.docs[doc_id]
                return 1
        return 0

    def delete_many(self, query: dict[str, Any]) -> int:
        """Delete multiple documents. Returns count deleted."""
        to_delete = []
        for doc_id, doc in self.docs.items():
            if self._matches_query(doc.data, query):
                to_delete.append(doc_id)

        for doc_id in to_delete:
            del self.docs[doc_id]
        return len(to_delete)

    def count_documents(self, query: dict[str, Any]) -> int:
        """Count documents matching the query."""
        return len(self.find(query))

    def create_index(self, fields: list[tuple[str, int]], name: str | None = None, unique: bool = False) -> str:
        """Create an index. Returns index name."""
        if name is None:
            name = f"idx_{len(self.indexes)}"

        self.indexes[name] = Index(name=name, fields=fields, unique=unique)

        if unique:
            self._check_unique_constraint(fields)

        return name

    def aggregate(self, pipeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Execute aggregation pipeline."""
        result = list(self.docs.values())

        for stage in pipeline:
            if "$match" in stage:
                query = stage["$match"]
                result = [d for d in result if self._matches_query(d.data, query)]

            elif "$project" in stage:
                proj = stage["$project"]
                new_result = []
                for doc in result:
                    new_doc = {"_id": doc.doc_id}
                    for field, include in proj.items():
                        if include and field in doc.data:
                            new_doc[field] = doc.data[field]
                    new_result.append(type("", (), {"data": new_doc, "doc_id": doc.doc_id})())
                result = new_result

            elif "$group" in stage:
                group = stage["$group"]
                group_by = group.get("_id")
                groups: dict[Any, dict[str, Any]] = {}

                for doc in result:
                    key = self._get_field_value(doc.data, group_by) if group_by else None
                    if key not in groups:
                        groups[key] = {"_id": key}

                    for field, op in group.items():
                        if field == "_id":
                            continue
                        if isinstance(op, dict):
                            agg_op = list(op.keys())[0]
                            src_field = list(op.values())[0]
                            value = self._get_field_value(doc.data, src_field)

                            if agg_op == "$sum":
                                groups[key][field] = groups[key].get(field, 0) + (
                                    value if isinstance(value, (int, float)) else 0
                                )
                            elif agg_op == "$avg":
                                groups[key][field] = groups[key].get(field, [])
                                if isinstance(groups[key][field], list):
                                    groups[key][field].append(value)
                            elif agg_op == "$max":
                                groups[key][field] = max(groups[key].get(field, value), value)
                            elif agg_op == "$min":
                                groups[key][field] = min(groups[key].get(field, value), value)

                result = [type("", (), {"data": g, "doc_id": k})() for g in groups.values()]

            elif "$sort" in stage:
                sort_spec = stage["$sort"]
                for field, direction in reversed(list(sort_spec.items())):
                    result.sort(key=lambda d: self._get_field_value(d.data, field), reverse=direction < 0)

            elif "$limit" in stage:
                result = result[: stage["$limit"]]

        return [d.data if hasattr(d, "data") else d for d in result]

    def _matches_query(self, doc: dict[str, Any], query: dict[str, Any]) -> bool:
        """Check if document matches query."""
        for field, condition in query.items():
            value = self._get_field_value(doc, field)

            if isinstance(condition, dict):
                for op, op_value in condition.items():
                    if (
                        op == "$eq"
                        and value != op_value
                        or op == "$ne"
                        and value == op_value
                        or op == "$gt"
                        and not (value > op_value)
                        or op == "$gte"
                        and not (value >= op_value)
                        or op == "$lt"
                        and not (value < op_value)
                        or op == "$lte"
                        and not (value <= op_value)
                        or op == "$in"
                        and value not in op_value
                        or op == "$nin"
                        and value in op_value
                        or op == "$exists"
                        and (value is None) != (not op_value)
                        or op == "$regex"
                        and not re.search(op_value, str(value))
                    ):
                        return False
            else:
                if value != condition:
                    return False

        return True

    def _get_field_value(self, doc: dict[str, Any], field: str) -> Any:
        """Get nested field value."""
        if field.startswith("$"):
            field = field[1:]

        parts = field.split(".")
        value = doc
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
        return value

    def _apply_update(self, doc: dict[str, Any], update: dict[str, Any]) -> None:
        """Apply update operators to document."""
        for op, fields in update.items():
            if op == "$set":
                doc.update(fields)
            elif op == "$unset":
                for field in fields:
                    doc.pop(field, None)
            elif op == "$inc":
                for field, value in fields.items():
                    doc[field] = doc.get(field, 0) + value

    def _update_indexes(self, doc_id: str) -> None:
        """Update indexes for a document."""
        for index in self.indexes.values():
            if index.unique:
                self._check_unique_constraint(index.fields)

    def _check_unique_constraint(self, fields: list[tuple[str, int]]) -> None:
        """Verify unique constraint."""
        seen: dict[Any, str] = {}
        for doc_id, doc in self.docs.items():
            key = tuple(self._get_field_value(doc.data, f[0]) for f in fields)
            if key in seen:
                raise ValueError(f"Duplicate value for unique index: {key}")
            seen[key] = doc_id


class DocumentDatabase:
    """Top-level document database."""

    def __init__(self, name: str = "thomas_db"):
        self.name = name
        self.collections: dict[str, Collection] = {}

    def create_collection(self, name: str) -> Collection:
        """Create or get a collection."""
        if name not in self.collections:
            self.collections[name] = Collection(name)
        return self.collections[name]

    def get_collection(self, name: str) -> Collection | None:
        """Get an existing collection."""
        return self.collections.get(name)

    def drop_collection(self, name: str) -> bool:
        """Drop a collection."""
        if name in self.collections:
            del self.collections[name]
            return True
        return False

    def list_collections(self) -> list[str]:
        """List all collection names."""
        return list(self.collections.keys())

    def get_stats(self) -> dict[str, Any]:
        """Get database statistics."""
        stats = {
            "name": self.name,
            "collections": len(self.collections),
            "total_documents": 0,
            "collections_detail": {},
        }

        for name, coll in self.collections.items():
            stats["total_documents"] += len(coll.docs)
            stats["collections_detail"][name] = {"documents": len(coll.docs), "indexes": len(coll.indexes)}

        return stats
