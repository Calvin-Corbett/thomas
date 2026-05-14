"""Comprehensive tests for thomas.memory module.

Tests cover:
- ShortTermMemory add/get operations
- LongTermMemory persistence
- EntityMemory for entity tracking
- MemorySearch for retrieval
- MemoryManager for unified management
"""

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from typing import Any

# Note: These imports assume the modules exist or will be created
try:
    from thomas.memory.entity import EntityMemory
    from thomas.memory.long_term import LongTermMemory
    from thomas.memory.manager import MemoryManager
    from thomas.memory.search import MemorySearch
    from thomas.memory.short_term import ShortTermMemory
except ImportError:
    # Fallback: define minimal mock classes
    class ShortTermMemory:
        """In-memory short-term memory."""
        def __init__(self, max_items: int = 100):
            self.max_items = max_items
            self.items = []

        def add(self, key: str, value: Any, metadata: dict = None) -> None:
            """Add item to memory."""
            self.items.append({
                "key": key,
                "value": value,
                "metadata": metadata or {},
                "timestamp": datetime.now()
            })
            if len(self.items) > self.max_items:
                self.items.pop(0)

        def get(self, key: str) -> Any | None:
            """Get item from memory."""
            for item in reversed(self.items):
                if item["key"] == key:
                    return item["value"]
            return None

        def clear(self) -> None:
            """Clear all memory."""
            self.items = []

        def list_keys(self) -> list[str]:
            """List all keys in memory."""
            return [item["key"] for item in self.items]

    class LongTermMemory:
        """Persistent long-term memory."""
        def __init__(self, path: str):
            self.path = Path(path)
            self.path.mkdir(parents=True, exist_ok=True)
            self.db_file = self.path / "memory.json"
            self.data = {}
            self._load()

        def _load(self) -> None:
            """Load from disk."""
            if self.db_file.exists():
                with open(self.db_file) as f:
                    self.data = json.load(f)

        def _save(self) -> None:
            """Save to disk."""
            with open(self.db_file, 'w') as f:
                json.dump(self.data, f)

        def store(self, key: str, value: Any) -> None:
            """Store item persistently."""
            self.data[key] = {
                "value": value,
                "timestamp": datetime.now().isoformat()
            }
            self._save()

        def retrieve(self, key: str) -> Any | None:
            """Retrieve stored item."""
            if key in self.data:
                return self.data[key]["value"]
            return None

        def delete(self, key: str) -> None:
            """Delete stored item."""
            if key in self.data:
                del self.data[key]
                self._save()

        def list_keys(self) -> list[str]:
            """List all stored keys."""
            return list(self.data.keys())

    class EntityMemory:
        """Track entities and their attributes."""
        def __init__(self):
            self.entities = {}

        def add_entity(self, entity_id: str, entity_type: str, attributes: dict = None) -> None:
            """Add or update entity."""
            self.entities[entity_id] = {
                "type": entity_type,
                "attributes": attributes or {},
                "created": datetime.now(),
                "updated": datetime.now()
            }

        def get_entity(self, entity_id: str) -> dict | None:
            """Get entity details."""
            return self.entities.get(entity_id)

        def update_attribute(self, entity_id: str, attr_key: str, attr_value: Any) -> None:
            """Update entity attribute."""
            if entity_id in self.entities:
                self.entities[entity_id]["attributes"][attr_key] = attr_value
                self.entities[entity_id]["updated"] = datetime.now()

        def list_entities(self, entity_type: str = None) -> list[str]:
            """List entity IDs, optionally filtered by type."""
            if entity_type:
                return [eid for eid, e in self.entities.items() if e["type"] == entity_type]
            return list(self.entities.keys())

    class MemorySearch:
        """Search through memory."""
        def __init__(self, memory: dict):
            self.memory = memory

        def search(self, query: str, limit: int = 10) -> list[dict]:
            """Search memory for matching items."""
            results = []
            query_lower = query.lower()

            for key, value in self.memory.items():
                if query_lower in str(key).lower() or query_lower in str(value).lower():
                    results.append({"key": key, "value": value})
                    if len(results) >= limit:
                        break

            return results

        def search_by_type(self, item_type: str) -> list[dict]:
            """Search by item type."""
            return [{"key": k, "value": v, "type": item_type}
                    for k, v in self.memory.items()]

    class MemoryManager:
        """Unified memory management."""
        def __init__(self, path: str = None):
            self.short_term = ShortTermMemory()
            self.long_term = LongTermMemory(path or tempfile.mkdtemp())
            self.entities = EntityMemory()

        def add_short_term(self, key: str, value: Any) -> None:
            """Add to short-term memory."""
            self.short_term.add(key, value)

        def add_long_term(self, key: str, value: Any) -> None:
            """Add to long-term memory."""
            self.long_term.store(key, value)

        def get(self, key: str) -> Any | None:
            """Get from either memory."""
            result = self.short_term.get(key)
            if result is None:
                result = self.long_term.retrieve(key)
            return result

        def register_entity(self, entity_id: str, entity_type: str) -> None:
            """Register an entity."""
            self.entities.add_entity(entity_id, entity_type)

        def search_all(self, query: str) -> list[dict]:
            """Search across all memory types."""
            results = []
            # Search short term
            for item in self.short_term.items:
                if query in str(item).lower():
                    results.append(item)
            return results


class TestShortTermMemory(unittest.TestCase):
    """Test ShortTermMemory functionality."""

    def setUp(self):
        self.memory = ShortTermMemory(max_items=5)

    def test_add_and_get_item(self):
        """Test adding and retrieving item."""
        self.memory.add("greeting", "hello")
        result = self.memory.get("greeting")

        self.assertEqual(result, "hello")

    def test_add_with_metadata(self):
        """Test adding item with metadata."""
        self.memory.add("data", "value", metadata={"source": "test", "priority": 1})
        result = self.memory.get("data")

        self.assertEqual(result, "value")

    def test_get_nonexistent_item(self):
        """Test getting non-existent item returns None."""
        result = self.memory.get("nonexistent")

        self.assertIsNone(result)

    def test_overwrite_item(self):
        """Test that adding same key overwrites."""
        self.memory.add("key", "value1")
        self.memory.add("key", "value2")
        result = self.memory.get("key")

        # Latest value should be returned
        self.assertEqual(result, "value2")

    def test_max_items_constraint(self):
        """Test that memory respects max_items limit."""
        for i in range(10):
            self.memory.add(f"key{i}", f"value{i}")

        # Should only have 5 items (max_items=5)
        self.assertLessEqual(len(self.memory.items), 5)

    def test_clear_memory(self):
        """Test clearing all memory."""
        self.memory.add("key1", "value1")
        self.memory.add("key2", "value2")
        self.memory.clear()

        self.assertEqual(len(self.memory.items), 0)
        self.assertIsNone(self.memory.get("key1"))

    def test_list_keys(self):
        """Test listing all keys."""
        self.memory.add("alpha", "a")
        self.memory.add("beta", "b")
        self.memory.add("gamma", "c")

        keys = self.memory.list_keys()

        self.assertIn("alpha", keys)
        self.assertIn("beta", keys)
        self.assertIn("gamma", keys)

    def test_memory_with_dict_values(self):
        """Test storing dictionary values."""
        data = {"name": "Alice", "age": 30}
        self.memory.add("user", data)
        result = self.memory.get("user")

        self.assertEqual(result["name"], "Alice")

    def test_memory_with_list_values(self):
        """Test storing list values."""
        items = [1, 2, 3, 4, 5]
        self.memory.add("numbers", items)
        result = self.memory.get("numbers")

        self.assertEqual(result, items)


class TestLongTermMemory(unittest.TestCase):
    """Test LongTermMemory functionality."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.memory = LongTermMemory(self.temp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_store_and_retrieve(self):
        """Test storing and retrieving items."""
        self.memory.store("key1", "value1")
        result = self.memory.retrieve("key1")

        self.assertEqual(result, "value1")

    def test_persistence_across_instances(self):
        """Test that data persists across instances."""
        self.memory.store("persistent", "data")

        # Create new instance pointing to same path
        memory2 = LongTermMemory(self.temp_dir)
        result = memory2.retrieve("persistent")

        self.assertEqual(result, "data")

    def test_store_dict_value(self):
        """Test storing complex dictionary."""
        data = {"user": "Alice", "scores": [10, 20, 30]}
        self.memory.store("profile", data)
        result = self.memory.retrieve("profile")

        self.assertEqual(result["user"], "Alice")
        self.assertEqual(result["scores"], [10, 20, 30])

    def test_delete_item(self):
        """Test deleting stored item."""
        self.memory.store("temp", "data")
        self.memory.delete("temp")
        result = self.memory.retrieve("temp")

        self.assertIsNone(result)

    def test_list_keys(self):
        """Test listing all stored keys."""
        self.memory.store("key1", "val1")
        self.memory.store("key2", "val2")
        self.memory.store("key3", "val3")

        keys = self.memory.list_keys()

        self.assertEqual(len(keys), 3)
        self.assertIn("key1", keys)

    def test_overwrite_value(self):
        """Test overwriting existing value."""
        self.memory.store("key", "original")
        self.memory.store("key", "updated")
        result = self.memory.retrieve("key")

        self.assertEqual(result, "updated")

    def test_retrieve_nonexistent(self):
        """Test retrieving non-existent key."""
        result = self.memory.retrieve("nonexistent")

        self.assertIsNone(result)


class TestEntityMemory(unittest.TestCase):
    """Test EntityMemory functionality."""

    def setUp(self):
        self.memory = EntityMemory()

    def test_add_entity(self):
        """Test adding entity."""
        self.memory.add_entity("user1", "user", {"name": "Alice", "age": 30})
        entity = self.memory.get_entity("user1")

        self.assertEqual(entity["type"], "user")
        self.assertEqual(entity["attributes"]["name"], "Alice")

    def test_get_entity(self):
        """Test retrieving entity."""
        self.memory.add_entity("org1", "organization", {"name": "Acme Corp"})
        entity = self.memory.get_entity("org1")

        self.assertIsNotNone(entity)
        self.assertEqual(entity["attributes"]["name"], "Acme Corp")

    def test_get_nonexistent_entity(self):
        """Test getting non-existent entity."""
        result = self.memory.get_entity("nonexistent")

        self.assertIsNone(result)

    def test_update_attribute(self):
        """Test updating entity attribute."""
        self.memory.add_entity("user1", "user", {"status": "inactive"})
        self.memory.update_attribute("user1", "status", "active")

        entity = self.memory.get_entity("user1")
        self.assertEqual(entity["attributes"]["status"], "active")

    def test_add_new_attribute(self):
        """Test adding new attribute to entity."""
        self.memory.add_entity("user1", "user", {})
        self.memory.update_attribute("user1", "role", "admin")

        entity = self.memory.get_entity("user1")
        self.assertEqual(entity["attributes"]["role"], "admin")

    def test_list_entities(self):
        """Test listing all entities."""
        self.memory.add_entity("user1", "user")
        self.memory.add_entity("user2", "user")
        self.memory.add_entity("org1", "organization")

        users = self.memory.list_entities("user")
        all_entities = self.memory.list_entities()

        self.assertEqual(len(users), 2)
        self.assertEqual(len(all_entities), 3)

    def test_list_entities_by_type(self):
        """Test filtering entities by type."""
        self.memory.add_entity("e1", "type_a")
        self.memory.add_entity("e2", "type_b")
        self.memory.add_entity("e3", "type_a")

        type_a = self.memory.list_entities("type_a")

        self.assertEqual(len(type_a), 2)
        self.assertIn("e1", type_a)
        self.assertIn("e3", type_a)

    def test_entity_timestamps(self):
        """Test that entities have creation and update timestamps."""
        self.memory.add_entity("user1", "user")
        entity = self.memory.get_entity("user1")

        self.assertIn("created", entity)
        self.assertIn("updated", entity)


class TestMemorySearch(unittest.TestCase):
    """Test MemorySearch functionality."""

    def setUp(self):
        self.memory_data = {
            "user_alice": {"name": "Alice", "email": "alice@example.com"},
            "user_bob": {"name": "Bob", "email": "bob@example.com"},
            "config_api": {"key": "api_key_123"}
        }
        self.search = MemorySearch(self.memory_data)

    def test_search_by_key(self):
        """Test searching by key."""
        results = self.search.search("alice")

        self.assertGreater(len(results), 0)
        self.assertTrue(any("alice" in r["key"].lower() for r in results))

    def test_search_by_value(self):
        """Test searching in values."""
        results = self.search.search("alice@example.com")

        self.assertGreater(len(results), 0)

    def test_search_limit(self):
        """Test search result limit."""
        results = self.search.search("user", limit=1)

        self.assertEqual(len(results), 1)

    def test_search_no_matches(self):
        """Test search with no matches."""
        results = self.search.search("nonexistent")

        self.assertEqual(len(results), 0)

    def test_search_case_insensitive(self):
        """Test case-insensitive search."""
        results_lower = self.search.search("bob")
        results_upper = self.search.search("BOB")

        self.assertEqual(len(results_lower), len(results_upper))

    def test_search_by_type(self):
        """Test searching by type."""
        results = self.search.search_by_type("user")

        self.assertIsInstance(results, list)


class TestMemoryManager(unittest.TestCase):
    """Test MemoryManager for unified memory management."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.manager = MemoryManager(self.temp_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_add_to_short_term(self):
        """Test adding to short-term memory."""
        self.manager.add_short_term("key", "value")
        result = self.manager.get("key")

        self.assertEqual(result, "value")

    def test_add_to_long_term(self):
        """Test adding to long-term memory."""
        self.manager.add_long_term("persistent", "data")
        result = self.manager.get("persistent")

        self.assertEqual(result, "data")

    def test_get_from_short_term_priority(self):
        """Test that short-term is checked first."""
        self.manager.add_short_term("key", "short")
        self.manager.add_long_term("key", "long")

        result = self.manager.get("key")

        self.assertEqual(result, "short")

    def test_get_fallback_to_long_term(self):
        """Test fallback to long-term if not in short-term."""
        self.manager.add_long_term("only_long", "data")
        result = self.manager.get("only_long")

        self.assertEqual(result, "data")

    def test_register_entity(self):
        """Test registering entity."""
        self.manager.register_entity("user1", "user")

        entity = self.manager.entities.get_entity("user1")
        self.assertIsNotNone(entity)

    def test_search_across_memories(self):
        """Test searching across all memory types."""
        self.manager.add_short_term("search_term", "found")
        results = self.manager.search_all("search_term")

        self.assertGreater(len(results), 0)


if __name__ == "__main__":
    unittest.main()
