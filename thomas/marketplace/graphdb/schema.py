"""Schema management, validation, and constraints."""

from typing import TYPE_CHECKING, Any, Optional

from thomas.marketplace.graphdb._exceptions import SchemaError
from thomas.marketplace.graphdb._types import (
    Edge,
    EdgeTypeSchema,
    GraphSchema,
    Node,
    NodeLabelSchema,
    PropertyDefinition,
    PropertyType,
)

if TYPE_CHECKING:
    from thomas.marketplace.graphdb.storage import GraphStorage


class SchemaManager:
    """Manages graph schema, validation, and constraints."""

    def __init__(self) -> None:
        """Initialize schema manager."""
        self.schema = GraphSchema()
        self.node_key_constraints: dict[str, set[str]] = {}  # label -> set of property keys
        self.unique_constraints: dict[str, set[str]] = {}  # label.property -> set of values

    def add_node_label_schema(
        self, label: str, properties: dict[str, PropertyDefinition], abstract: bool = False
    ) -> None:
        """Define schema for a node label.

        Args:
            label: Node label
            properties: Property definitions
            abstract: Whether this is an abstract label

        Raises:
            SchemaError: If schema is invalid
        """
        if not label:
            raise SchemaError("Label cannot be empty")

        node_schema = NodeLabelSchema(label=label, properties=properties, abstract=abstract)
        self.schema.add_node_label_schema(node_schema)

    def add_edge_type_schema(
        self,
        edge_type: str,
        properties: dict[str, PropertyDefinition],
        source_labels: set[str] | None = None,
        target_labels: set[str] | None = None,
    ) -> None:
        """Define schema for an edge type.

        Args:
            edge_type: Edge type
            properties: Property definitions
            source_labels: Allowed source node labels (None = any)
            target_labels: Allowed target node labels (None = any)

        Raises:
            SchemaError: If schema is invalid
        """
        if not edge_type:
            raise SchemaError("Edge type cannot be empty")

        edge_schema = EdgeTypeSchema(
            type=edge_type,
            properties=properties,
            source_labels=source_labels or set(),
            target_labels=target_labels or set(),
        )
        self.schema.add_edge_type_schema(edge_schema)

    def add_unique_constraint(self, label: str, *properties: str) -> None:
        """Add unique constraint on node property.

        Args:
            label: Node label
            properties: Property names

        Raises:
            SchemaError: If constraint is invalid
        """
        if not label or not properties:
            raise SchemaError("Label and properties required for unique constraint")

        key = f"{label}.{'.'.join(properties)}"
        self.unique_constraints[key] = set()

    def add_exists_constraint(self, label: str, property_name: str) -> None:
        """Add exists constraint on node property.

        Args:
            label: Node label
            property_name: Property name

        Raises:
            SchemaError: If constraint is invalid
        """
        if not label or not property_name:
            raise SchemaError("Label and property required for exists constraint")

        node_schema = self.schema.get_node_label_schema(label)
        if node_schema:
            if property_name in node_schema.properties:
                node_schema.properties[property_name].required = True

    def add_node_key_constraint(self, label: str, *properties: str) -> None:
        """Add node key constraint (unique + required).

        Args:
            label: Node label
            properties: Property names

        Raises:
            SchemaError: If constraint is invalid
        """
        if not label or not properties:
            raise SchemaError("Label and properties required for node key constraint")

        self.node_key_constraints[label] = set(properties)

    def validate_node(self, node: Node) -> None:
        """Validate node against schema.

        Args:
            node: Node to validate

        Raises:
            SchemaError: If validation fails
        """
        for label in node.labels:
            node_schema = self.schema.get_node_label_schema(label)
            if node_schema:
                self._validate_properties(node.properties, node_schema.properties, label)

                # Check node key constraint
                if label in self.node_key_constraints:
                    key_props = self.node_key_constraints[label]
                    for prop in key_props:
                        if prop not in node.properties:
                            raise SchemaError(f"Node key constraint violated: missing {prop} in {label}")

    def validate_edge(self, edge: Edge, storage: Optional["GraphStorage"] = None) -> None:
        """Validate edge against schema.

        Args:
            edge: Edge to validate
            storage: Storage instance for label checking

        Raises:
            SchemaError: If validation fails
        """
        edge_schema = self.schema.get_edge_type_schema(edge.type)
        if edge_schema:
            self._validate_properties(edge.properties, edge_schema.properties, edge.type)

            # Check source/target label constraints
            if storage:
                if edge_schema.source_labels:
                    try:
                        source_node = storage.get_node(edge.source)
                        if not any(label in source_node.labels for label in edge_schema.source_labels):
                            raise SchemaError(f"Edge {edge.type}: source must have one of {edge_schema.source_labels}")
                    except SchemaError:
                        raise
                    except Exception:
                        pass

                if edge_schema.target_labels:
                    try:
                        target_node = storage.get_node(edge.target)
                        if not any(label in target_node.labels for label in edge_schema.target_labels):
                            raise SchemaError(f"Edge {edge.type}: target must have one of {edge_schema.target_labels}")
                    except SchemaError:
                        raise
                    except Exception:
                        pass

    def _validate_properties(
        self, obj_props: dict[str, Any], schema_props: dict[str, PropertyDefinition], context: str
    ) -> None:
        """Validate object properties against schema.

        Args:
            obj_props: Object properties
            schema_props: Schema property definitions
            context: Context for error messages

        Raises:
            SchemaError: If validation fails
        """
        # Check required properties
        for prop_name, prop_def in schema_props.items():
            if prop_def.required and prop_name not in obj_props:
                raise SchemaError(f"{context}: required property {prop_name} not found")

            if prop_name in obj_props:
                self._validate_property_type(obj_props[prop_name], prop_def, f"{context}.{prop_name}")

    def _validate_property_type(self, value: Any, prop_def: PropertyDefinition, context: str) -> None:
        """Validate property value against type definition.

        Args:
            value: Property value
            prop_def: Property definition
            context: Context for error messages

        Raises:
            SchemaError: If validation fails
        """
        if value is None:
            return

        expected_type = prop_def.type
        actual_type = type(value).__name__

        if expected_type == PropertyType.STRING and not isinstance(value, str):
            raise SchemaError(f"{context}: expected string, got {actual_type}")

        elif expected_type == PropertyType.INTEGER and not isinstance(value, int):
            raise SchemaError(f"{context}: expected integer, got {actual_type}")

        elif expected_type == PropertyType.FLOAT and not isinstance(value, (int, float)):
            raise SchemaError(f"{context}: expected float, got {actual_type}")

        elif expected_type == PropertyType.BOOLEAN and not isinstance(value, bool):
            raise SchemaError(f"{context}: expected boolean, got {actual_type}")

        elif expected_type == PropertyType.LIST and not isinstance(value, list):
            raise SchemaError(f"{context}: expected list, got {actual_type}")

        elif expected_type == PropertyType.MAP and not isinstance(value, dict):
            raise SchemaError(f"{context}: expected map, got {actual_type}")

    def check_unique_constraint(self, label: str, property_name: str, value: Any) -> bool:
        """Check if value satisfies unique constraint.

        Args:
            label: Node label
            property_name: Property name
            value: Property value

        Returns:
            True if value is unique or no constraint exists
        """
        key = f"{label}.{property_name}"

        if key not in self.unique_constraints:
            return True

        constraint_values = self.unique_constraints[key]
        return value not in constraint_values

    def record_unique_value(self, label: str, property_name: str, value: Any) -> None:
        """Record a value for unique constraint checking.

        Args:
            label: Node label
            property_name: Property name
            value: Property value
        """
        key = f"{label}.{property_name}"

        if key in self.unique_constraints:
            self.unique_constraints[key].add(value)

    def get_node_label_schema(self, label: str) -> NodeLabelSchema | None:
        """Get node label schema.

        Args:
            label: Node label

        Returns:
            NodeLabelSchema or None
        """
        return self.schema.get_node_label_schema(label)

    def get_edge_type_schema(self, edge_type: str) -> EdgeTypeSchema | None:
        """Get edge type schema.

        Args:
            edge_type: Edge type

        Returns:
            EdgeTypeSchema or None
        """
        return self.schema.get_edge_type_schema(edge_type)

    def get_schema(self) -> GraphSchema:
        """Get the complete schema.

        Returns:
            GraphSchema object
        """
        return self.schema

    def migrate_schema(self, migration_fn: callable) -> None:
        """Apply a schema migration.

        Args:
            migration_fn: Function that takes schema and modifies it
        """
        migration_fn(self.schema)

    def export_schema(self) -> dict[str, Any]:
        """Export schema as dictionary.

        Returns:
            Schema dictionary
        """
        return {
            "node_labels": {
                label: {
                    "abstract": schema.abstract,
                    "properties": {
                        name: {
                            "type": prop.type.value,
                            "required": prop.required,
                            "unique": prop.unique,
                            "indexed": prop.indexed,
                        }
                        for name, prop in schema.properties.items()
                    },
                }
                for label, schema in self.schema.node_label_schemas.items()
            },
            "edge_types": {
                edge_type: {
                    "source_labels": list(schema.source_labels),
                    "target_labels": list(schema.target_labels),
                    "properties": {
                        name: {
                            "type": prop.type.value,
                            "required": prop.required,
                            "unique": prop.unique,
                            "indexed": prop.indexed,
                        }
                        for name, prop in schema.properties.items()
                    },
                }
                for edge_type, schema in self.schema.edge_type_schemas.items()
            },
            "constraints": self.schema.constraints,
        }
