"""Tests for schema management, validation, and constraints."""

import pytest

from thomas.marketplace.graphdb._exceptions import SchemaError
from thomas.marketplace.graphdb._types import Edge, Node, PropertyDefinition, PropertyType
from thomas.marketplace.graphdb.schema import SchemaManager
from thomas.marketplace.graphdb.storage import GraphStorage


@pytest.fixture
def schema_manager():
    """Create a fresh schema manager."""
    return SchemaManager()


class TestNodeLabelSchema:
    """Test node label schema definition."""

    def test_add_node_label_schema(self, schema_manager: SchemaManager) -> None:
        """Test adding node label schema."""
        properties = {
            "name": PropertyDefinition("name", PropertyType.STRING, required=True),
            "age": PropertyDefinition("age", PropertyType.INTEGER),
        }

        schema_manager.add_node_label_schema("Person", properties)

        person_schema = schema_manager.get_node_label_schema("Person")
        assert person_schema is not None
        assert "name" in person_schema.properties

    def test_add_node_label_schema_abstract(self, schema_manager: SchemaManager) -> None:
        """Test adding abstract node label schema."""
        properties = {}
        schema_manager.add_node_label_schema("Entity", properties, abstract=True)

        entity_schema = schema_manager.get_node_label_schema("Entity")
        assert entity_schema is not None
        assert entity_schema.abstract is True

    def test_empty_label_fails(self, schema_manager: SchemaManager) -> None:
        """Test that empty label raises error."""
        with pytest.raises(SchemaError):
            schema_manager.add_node_label_schema("", {})


class TestEdgeTypeSchema:
    """Test edge type schema definition."""

    def test_add_edge_type_schema(self, schema_manager: SchemaManager) -> None:
        """Test adding edge type schema."""
        properties = {
            "since": PropertyDefinition("since", PropertyType.INTEGER),
        }

        schema_manager.add_edge_type_schema("KNOWS", properties)

        knows_schema = schema_manager.get_edge_type_schema("KNOWS")
        assert knows_schema is not None

    def test_add_edge_type_with_constraints(self, schema_manager: SchemaManager) -> None:
        """Test adding edge type with source/target constraints."""
        schema_manager.add_edge_type_schema(
            "WORKS_AT",
            {},
            source_labels={"Person"},
            target_labels={"Company"},
        )

        works_at_schema = schema_manager.get_edge_type_schema("WORKS_AT")
        assert "Person" in works_at_schema.source_labels
        assert "Company" in works_at_schema.target_labels


class TestPropertyValidation:
    """Test property validation against schema."""

    def test_validate_node_required_property(self, schema_manager: SchemaManager) -> None:
        """Test validation of required properties."""
        properties = {
            "name": PropertyDefinition("name", PropertyType.STRING, required=True),
        }
        schema_manager.add_node_label_schema("Person", properties)

        # Valid node
        valid_node = Node(id="p1", labels=frozenset(["Person"]), properties={"name": "Alice"})
        schema_manager.validate_node(valid_node)  # Should not raise

        # Invalid node (missing required property)
        invalid_node = Node(id="p2", labels=frozenset(["Person"]), properties={})
        with pytest.raises(SchemaError):
            schema_manager.validate_node(invalid_node)

    def test_validate_node_property_type(self, schema_manager: SchemaManager) -> None:
        """Test validation of property types."""
        properties = {
            "age": PropertyDefinition("age", PropertyType.INTEGER, required=True),
        }
        schema_manager.add_node_label_schema("Person", properties)

        # Valid type
        valid_node = Node(id="p1", labels=frozenset(["Person"]), properties={"age": 30})
        schema_manager.validate_node(valid_node)  # Should not raise

        # Invalid type
        invalid_node = Node(id="p2", labels=frozenset(["Person"]), properties={"age": "thirty"})
        with pytest.raises(SchemaError):
            schema_manager.validate_node(invalid_node)

    def test_validate_all_property_types(self, schema_manager: SchemaManager) -> None:
        """Test validation of all property types."""
        properties = {
            "name": PropertyDefinition("name", PropertyType.STRING),
            "age": PropertyDefinition("age", PropertyType.INTEGER),
            "height": PropertyDefinition("height", PropertyType.FLOAT),
            "active": PropertyDefinition("active", PropertyType.BOOLEAN),
            "tags": PropertyDefinition("tags", PropertyType.LIST),
            "metadata": PropertyDefinition("metadata", PropertyType.MAP),
        }
        schema_manager.add_node_label_schema("Person", properties)

        valid_node = Node(
            id="p1",
            labels=frozenset(["Person"]),
            properties={
                "name": "Alice",
                "age": 30,
                "height": 5.6,
                "active": True,
                "tags": ["engineer", "lead"],
                "metadata": {"level": 3},
            },
        )
        schema_manager.validate_node(valid_node)  # Should not raise


class TestUniqueConstraints:
    """Test unique constraints."""

    def test_add_unique_constraint(self, schema_manager: SchemaManager) -> None:
        """Test adding unique constraint."""
        schema_manager.add_unique_constraint("Person", "email")

        # Record some values
        schema_manager.record_unique_value("Person", "email", "alice@example.com")
        schema_manager.record_unique_value("Person", "email", "bob@example.com")

        # Check uniqueness
        assert schema_manager.check_unique_constraint("Person", "email", "alice@example.com") is False
        assert schema_manager.check_unique_constraint("Person", "email", "charlie@example.com") is True

    def test_unique_constraint_on_property(self) -> None:
        """Test unique constraint during property validation."""
        GraphStorage()
        schema_manager = SchemaManager()

        properties = {
            "email": PropertyDefinition("email", PropertyType.STRING, unique=True),
        }
        schema_manager.add_node_label_schema("User", properties)

        # Record existing email
        schema_manager.record_unique_value("User", "email", "alice@example.com")

        # Check constraint violation
        assert schema_manager.check_unique_constraint("User", "email", "alice@example.com") is False


class TestNodeKeyConstraints:
    """Test node key constraints."""

    def test_add_node_key_constraint(self, schema_manager: SchemaManager) -> None:
        """Test adding node key constraint."""
        schema_manager.add_node_key_constraint("Person", "ssn")

        # Valid node
        valid_node = Node(id="p1", labels=frozenset(["Person"]), properties={"ssn": "123-45-6789"})
        schema_manager.validate_node(valid_node)  # Should not raise

        # Invalid node (missing node key)
        invalid_node = Node(id="p2", labels=frozenset(["Person"]), properties={})
        with pytest.raises(SchemaError):
            schema_manager.validate_node(invalid_node)

    def test_composite_node_key(self, schema_manager: SchemaManager) -> None:
        """Test composite node key constraint."""
        schema_manager.add_node_key_constraint("Event", "date", "location", "name")

        # Valid node
        valid_node = Node(
            id="e1",
            labels=frozenset(["Event"]),
            properties={"date": "2024-01-01", "location": "NYC", "name": "Conference"},
        )
        schema_manager.validate_node(valid_node)  # Should not raise


class TestExistsConstraints:
    """Test exists (required) constraints."""

    def test_add_exists_constraint(self, schema_manager: SchemaManager) -> None:
        """Test adding exists constraint."""
        properties = {
            "name": PropertyDefinition("name", PropertyType.STRING),
        }
        schema_manager.add_node_label_schema("Person", properties)

        schema_manager.add_exists_constraint("Person", "name")

        # Check property is now required
        person_schema = schema_manager.get_node_label_schema("Person")
        assert person_schema.properties["name"].required is True


class TestEdgeValidation:
    """Test edge validation."""

    def test_validate_edge(self, schema_manager: SchemaManager) -> None:
        """Test validating edge."""
        schema_manager.add_edge_type_schema("KNOWS", {})

        edge = Edge(id="e1", source="p1", target="p2", type="KNOWS")
        schema_manager.validate_edge(edge)  # Should not raise

    def test_validate_edge_with_properties(self, schema_manager: SchemaManager) -> None:
        """Test validating edge with properties."""
        properties = {
            "since": PropertyDefinition("since", PropertyType.INTEGER, required=True),
        }
        schema_manager.add_edge_type_schema("KNOWS", properties)

        # Valid edge
        valid_edge = Edge(id="e1", source="p1", target="p2", type="KNOWS", properties={"since": 2015})
        schema_manager.validate_edge(valid_edge)  # Should not raise

        # Invalid edge
        invalid_edge = Edge(id="e2", source="p3", target="p4", type="KNOWS")
        with pytest.raises(SchemaError):
            schema_manager.validate_edge(invalid_edge)


class TestSchemaMigration:
    """Test schema migration."""

    def test_schema_migration(self, schema_manager: SchemaManager) -> None:
        """Test applying schema migration."""
        # Initial schema
        properties = {
            "name": PropertyDefinition("name", PropertyType.STRING),
        }
        schema_manager.add_node_label_schema("Person", properties)

        # Migration function
        def add_email_property(schema):
            person_schema = schema.get_node_label_schema("Person")
            if person_schema:
                person_schema.properties["email"] = PropertyDefinition("email", PropertyType.STRING)

        schema_manager.migrate_schema(add_email_property)

        # Verify migration
        person_schema = schema_manager.get_node_label_schema("Person")
        assert "email" in person_schema.properties


class TestSchemaExport:
    """Test schema export."""

    def test_export_schema(self, schema_manager: SchemaManager) -> None:
        """Test exporting schema to dictionary."""
        properties = {
            "name": PropertyDefinition("name", PropertyType.STRING, required=True),
            "age": PropertyDefinition("age", PropertyType.INTEGER),
        }
        schema_manager.add_node_label_schema("Person", properties)

        schema_dict = schema_manager.export_schema()

        assert "node_labels" in schema_dict
        assert "Person" in schema_dict["node_labels"]
        assert "name" in schema_dict["node_labels"]["Person"]["properties"]

    def test_exported_schema_structure(self, schema_manager: SchemaManager) -> None:
        """Test structure of exported schema."""
        schema_manager.add_edge_type_schema("KNOWS", {})

        schema_dict = schema_manager.export_schema()

        assert "edge_types" in schema_dict
        assert "KNOWS" in schema_dict["edge_types"]
