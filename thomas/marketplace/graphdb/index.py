"""Index management and optimization for property lookups."""

from typing import TYPE_CHECKING, Any

from thomas.marketplace.graphdb._exceptions import IndexError
from thomas.marketplace.graphdb._types import IndexDefinition

if TYPE_CHECKING:
    from thomas.marketplace.graphdb.storage import GraphStorage


class IndexManager:
    """Manages indices for the graph database."""

    def __init__(self, storage: "GraphStorage") -> None:
        """Initialize index manager.

        Args:
            storage: Graph storage instance
        """
        self.storage = storage
        self.indices: dict[str, IndexDefinition] = {}
        self.query_patterns: dict[str, int] = {}  # Track query patterns for auto-suggestion

    def create_index(
        self,
        index_id: str,
        name: str,
        index_type: str,
        fields: list[str],
        unique: bool = False,
    ) -> IndexDefinition:
        """Create a new index.

        Args:
            index_id: Unique index identifier
            name: Human-readable name
            index_type: 'label', 'property', 'composite', 'fulltext'
            fields: Fields to index
            unique: Whether to enforce uniqueness

        Returns:
            IndexDefinition

        Raises:
            IndexError: If index creation fails
        """
        if index_id in self.indices:
            raise IndexError(index_id, "Index already exists")

        if index_type not in ("label", "property", "composite", "fulltext"):
            raise IndexError(index_id, f"Invalid index type: {index_type}")

        index = IndexDefinition(
            id=index_id,
            name=name,
            index_type=index_type,
            fields=fields,
            unique=unique,
            active=True,
        )

        self.indices[index_id] = index
        return index

    def delete_index(self, index_id: str) -> None:
        """Delete an index.

        Args:
            index_id: Index ID

        Raises:
            IndexError: If index doesn't exist
        """
        if index_id not in self.indices:
            raise IndexError(index_id, "Index not found")

        del self.indices[index_id]

    def get_index(self, index_id: str) -> IndexDefinition | None:
        """Get an index by ID.

        Args:
            index_id: Index ID

        Returns:
            IndexDefinition or None
        """
        return self.indices.get(index_id)

    def list_indices(self) -> list[IndexDefinition]:
        """List all active indices.

        Returns:
            List of IndexDefinition objects
        """
        return [idx for idx in self.indices.values() if idx.active]

    def lookup_by_property(self, key: str, value: Any) -> list[str]:
        """Look up nodes/edges by property using indices.

        Args:
            key: Property key
            value: Property value

        Returns:
            List of matching node/edge IDs
        """
        # Track the query pattern
        pattern = f"{key}:{value}"
        self.query_patterns[pattern] = self.query_patterns.get(pattern, 0) + 1

        # Use existing property index
        return self.storage.find_nodes_by_property(key, value)

    def lookup_by_label(self, label: str) -> list[str]:
        """Look up nodes by label using indices.

        Args:
            label: Node label

        Returns:
            List of matching node IDs
        """
        pattern = f":{label}"
        self.query_patterns[pattern] = self.query_patterns.get(pattern, 0) + 1

        return self.storage.find_nodes_by_label(label)

    def validate_unique_constraint(self, index_id: str, value: Any) -> bool:
        """Check if a value satisfies unique constraint.

        Args:
            index_id: Index ID
            value: Value to check

        Returns:
            True if value is unique or index is not unique

        Raises:
            IndexError: If index doesn't exist
        """
        index = self.get_index(index_id)
        if not index:
            raise IndexError(index_id, "Index not found")

        if not index.unique:
            return True

        # Check if value exists in the index
        field = index.fields[0] if index.fields else None
        if field:
            existing = self.storage.find_nodes_by_property(field, value)
            return len(existing) == 0

        return True

    def suggest_indices(self) -> list[tuple[str, int]]:
        """Suggest indices based on query patterns.

        Returns:
            List of (pattern, frequency) tuples, sorted by frequency
        """
        # Get the most frequently queried patterns
        suggestions = sorted(self.query_patterns.items(), key=lambda x: x[1], reverse=True)
        return suggestions[:10]  # Return top 10 suggestions

    def get_fulltext_matches(self, field: str, query: str) -> list[str]:
        """Find nodes/edges matching a full-text query.

        Args:
            field: Property field to search
            query: Search query string

        Returns:
            List of matching node/edge IDs
        """
        results: list[str] = []
        query_lower = query.lower()

        # Find all nodes with the field
        all_ids = self.storage.property_index.get(field, {})
        for ids_set in all_ids.values():
            for obj_id in ids_set:
                # Check if node or edge
                if obj_id in self.storage.node_store:
                    node = self.storage.node_store[obj_id]
                    value = node.properties.get(field, "")
                    if isinstance(value, str) and query_lower in value.lower():
                        results.append(obj_id)

                elif obj_id in self.storage.edge_store:
                    edge = self.storage.edge_store[obj_id]
                    value = edge.properties.get(field, "")
                    if isinstance(value, str) and query_lower in value.lower():
                        results.append(obj_id)

        return results

    def analyze_index_usage(self) -> dict[str, Any]:
        """Analyze index usage statistics.

        Returns:
            Dictionary with index statistics
        """
        stats: dict[str, Any] = {
            "total_queries": sum(self.query_patterns.values()),
            "unique_patterns": len(self.query_patterns),
            "top_patterns": self.suggest_indices(),
            "index_count": len(self.indices),
            "active_indices": len(self.list_indices()),
        }

        return stats


class BTreeIndex:
    """Simple B-tree-like index for property lookups."""

    def __init__(self, field: str, unique: bool = False) -> None:
        """Initialize B-tree index.

        Args:
            field: Field name to index
            unique: Whether to enforce uniqueness
        """
        self.field = field
        self.unique = unique
        self.tree: dict[Any, set[str]] = {}

    def insert(self, value: Any, obj_id: str) -> None:
        """Insert a value into the index.

        Args:
            value: Value to index
            obj_id: Object ID

        Raises:
            IndexError: If unique constraint violated
        """
        if self.unique and value in self.tree and self.tree[value]:
            raise IndexError(self.field, f"Unique constraint violated for {value}")

        if value not in self.tree:
            self.tree[value] = set()

        self.tree[value].add(obj_id)

    def delete(self, value: Any, obj_id: str) -> None:
        """Delete a value from the index.

        Args:
            value: Value to remove
            obj_id: Object ID
        """
        if value in self.tree:
            self.tree[value].discard(obj_id)
            if not self.tree[value]:
                del self.tree[value]

    def search(self, value: Any) -> list[str]:
        """Search for a value in the index.

        Args:
            value: Value to search

        Returns:
            List of matching object IDs
        """
        return list(self.tree.get(value, set()))

    def range_search(self, min_val: Any, max_val: Any, inclusive: bool = True) -> list[str]:
        """Range search in the index.

        Args:
            min_val: Minimum value
            max_val: Maximum value
            inclusive: Whether range is inclusive

        Returns:
            List of matching object IDs
        """
        results: list[str] = []

        try:
            for value in self.tree.keys():
                if inclusive:
                    if min_val <= value <= max_val:
                        results.extend(self.tree[value])
                else:
                    if min_val < value < max_val:
                        results.extend(self.tree[value])
        except TypeError:
            # Values not comparable
            pass

        return results

    def clear(self) -> None:
        """Clear the index."""
        self.tree.clear()


class CompositeIndex:
    """Index over multiple fields."""

    def __init__(self, fields: list[str], unique: bool = False) -> None:
        """Initialize composite index.

        Args:
            fields: List of field names
            unique: Whether to enforce uniqueness
        """
        self.fields = fields
        self.unique = unique
        self.tree: dict[tuple[Any, ...], set[str]] = {}

    def insert(self, values: dict[str, Any], obj_id: str) -> None:
        """Insert values into the index.

        Args:
            values: Dictionary of field->value
            obj_id: Object ID

        Raises:
            IndexError: If unique constraint violated
        """
        key = tuple(values.get(field) for field in self.fields)

        if self.unique and key in self.tree and self.tree[key]:
            raise IndexError(",".join(self.fields), f"Unique constraint violated for {key}")

        if key not in self.tree:
            self.tree[key] = set()

        self.tree[key].add(obj_id)

    def delete(self, values: dict[str, Any], obj_id: str) -> None:
        """Delete values from the index.

        Args:
            values: Dictionary of field->value
            obj_id: Object ID
        """
        key = tuple(values.get(field) for field in self.fields)

        if key in self.tree:
            self.tree[key].discard(obj_id)
            if not self.tree[key]:
                del self.tree[key]

    def search(self, values: dict[str, Any]) -> list[str]:
        """Search for values in the index.

        Args:
            values: Dictionary of field->value

        Returns:
            List of matching object IDs
        """
        key = tuple(values.get(field) for field in self.fields)
        return list(self.tree.get(key, set()))

    def clear(self) -> None:
        """Clear the index."""
        self.tree.clear()
