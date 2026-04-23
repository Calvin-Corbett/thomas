"""Tests for distributed cache with consistent hashing."""

import pytest

from thomas.marketplace.caching import ConsistentHashRing, SlotBasedRouter


class TestConsistentHashRing:
    """Test consistent hashing ring."""

    def test_add_node(self):
        """Test adding nodes to the ring."""
        ring = ConsistentHashRing()

        ring.add_node("node1")
        ring.add_node("node2")

        assert "node1" in ring.nodes
        assert "node2" in ring.nodes

    def test_get_node_for_key(self):
        """Test getting node for a key."""
        ring = ConsistentHashRing()

        ring.add_node("node1")
        ring.add_node("node2")

        node = ring.get_node("key1")
        assert node in ("node1", "node2")

    def test_consistent_placement(self):
        """Test that same key always maps to same node."""
        ring = ConsistentHashRing()

        ring.add_node("node1")
        ring.add_node("node2")

        node1 = ring.get_node("key1")
        node2 = ring.get_node("key1")
        node3 = ring.get_node("key1")

        assert node1 == node2 == node3

    def test_remove_node(self):
        """Test removing a node from the ring."""
        ring = ConsistentHashRing()

        ring.add_node("node1")
        ring.add_node("node2")

        ring.remove_node("node1")

        assert "node1" not in ring.nodes
        assert "node2" in ring.nodes

    def test_empty_ring_returns_none(self):
        """Test that empty ring returns None."""
        ring = ConsistentHashRing()

        assert ring.get_node("key1") is None

    def test_single_node(self):
        """Test ring with single node."""
        ring = ConsistentHashRing()

        ring.add_node("node1")

        for key in ["key1", "key2", "key3"]:
            assert ring.get_node(key) == "node1"

    def test_distribution(self):
        """Test distribution of keys across nodes."""
        ring = ConsistentHashRing()

        ring.add_node("node1")
        ring.add_node("node2")
        ring.add_node("node3")

        dist = ring.distribution()

        assert len(dist) == 3
        total_vnodes = sum(dist.values())
        assert total_vnodes == 150 * 3  # 3 nodes * 150 virtual nodes each

    def test_rebalance_info(self):
        """Test rebalance information calculation."""
        ring = ConsistentHashRing()

        ring.add_node("node1")
        ring.add_node("node2")

        rebalance = ring.rebalance_info()

        assert len(rebalance) == 2
        assert all(v >= 0 for v in rebalance.values())

    def test_get_multiple_nodes(self):
        """Test getting multiple nodes for replication."""
        ring = ConsistentHashRing()

        ring.add_node("node1")
        ring.add_node("node2")
        ring.add_node("node3")

        nodes = ring.get_nodes("key1", count=2)

        assert len(nodes) <= 2
        assert all(n in ring.nodes for n in nodes)

    def test_get_multiple_nodes_more_than_available(self):
        """Test requesting more nodes than available."""
        ring = ConsistentHashRing()

        ring.add_node("node1")
        ring.add_node("node2")

        nodes = ring.get_nodes("key1", count=5)

        # Should return at most the number of nodes available
        assert len(nodes) <= 2

    def test_virtual_nodes_configuration(self):
        """Test custom virtual node count."""
        ring = ConsistentHashRing(virtual_nodes=50)

        ring.add_node("node1")

        dist = ring.distribution()

        assert dist["node1"] == 50

    def test_invalid_virtual_nodes(self):
        """Test that invalid virtual node count is rejected."""
        with pytest.raises(ValueError):
            ConsistentHashRing(virtual_nodes=0)

        with pytest.raises(ValueError):
            ConsistentHashRing(virtual_nodes=-1)

    def test_add_duplicate_node(self):
        """Test adding duplicate node."""
        ring = ConsistentHashRing()

        ring.add_node("node1")
        ring.add_node("node1")  # Should not error, just skip

        assert len(ring.nodes) == 1

    def test_minimal_redistribution_on_node_add(self):
        """Test that adding a node causes minimal redistribution."""
        ring = ConsistentHashRing()

        ring.add_node("node1")
        ring.add_node("node2")

        # Get mapping for many keys
        original_mapping = {f"key{i}": ring.get_node(f"key{i}") for i in range(100)}

        # Add new node
        ring.add_node("node3")

        # Check how many keys changed
        new_mapping = {f"key{i}": ring.get_node(f"key{i}") for i in range(100)}
        changed = sum(1 for k in original_mapping if original_mapping[k] != new_mapping[k])

        # Should be roughly 1/3 of keys (going to new node)
        # Allow some variance
        assert 15 < changed < 50


class TestSlotBasedRouter:
    """Test slot-based routing (Redis-style)."""

    def test_create_router(self):
        """Test creating a slot-based router."""
        router = SlotBasedRouter()

        assert router.SLOT_COUNT == 16384
        assert len(router._slots) == 16384

    def test_assign_slots(self):
        """Test assigning slots to a node."""
        router = SlotBasedRouter()

        router.assign_slots("node1", 0, 1000)

        assert "node1" in router.nodes
        assert router.get_slot_node(500) == "node1"

    def test_get_node_for_key(self):
        """Test getting node for a key."""
        router = SlotBasedRouter()

        router.assign_slots("node1", 0, 8191)
        router.assign_slots("node2", 8192, 16383)

        # Both nodes should be assigned keys
        assert router.get_node("key1") is not None

    def test_invalid_slot_range(self):
        """Test that invalid slot ranges are rejected."""
        router = SlotBasedRouter()

        with pytest.raises(ValueError):
            router.assign_slots("node1", -1, 100)

        with pytest.raises(ValueError):
            router.assign_slots("node1", 100, 16384)

        with pytest.raises(ValueError):
            router.assign_slots("node1", 1000, 500)

    def test_slot_coverage(self):
        """Test slot coverage calculation."""
        router = SlotBasedRouter()

        assert router.coverage() == 0.0

        router.assign_slots("node1", 0, 8191)
        router.assign_slots("node2", 8192, 16383)

        assert router.coverage() == 1.0

    def test_distribution(self):
        """Test distribution of slots."""
        router = SlotBasedRouter()

        router.assign_slots("node1", 0, 5461)
        router.assign_slots("node2", 5462, 10922)
        router.assign_slots("node3", 10923, 16383)

        dist = router.distribution()

        assert len(dist) == 3
        total = sum(dist.values())
        assert total == 16384

    def test_unassigned_slot(self):
        """Test getting node for unassigned slot."""
        router = SlotBasedRouter()

        router.assign_slots("node1", 0, 1000)

        assert router.get_slot_node(5000) is None

    def test_redistribution_info(self):
        """Test redistribution information."""
        router = SlotBasedRouter()

        router.assign_slots("node1", 0, 8191)
        router.assign_slots("node2", 8192, 16383)

        rebalance = router.redistribution_needed("node1")

        assert len(rebalance) == 8192
        assert all(v is None for v in rebalance.values())

    def test_consistent_slot_assignment(self):
        """Test that same key always maps to same slot."""
        router = SlotBasedRouter()

        router.assign_slots("node1", 0, 16383)

        slot1 = router.get_slot("key1")
        slot2 = router.get_slot("key1")

        assert slot1 == slot2

    def test_key_distribution(self):
        """Test that keys are distributed across assigned slots."""
        router = SlotBasedRouter()

        router.assign_slots("node1", 0, 8191)
        router.assign_slots("node2", 8192, 16383)

        # Generate many keys and check distribution
        slots_used = set()
        for i in range(1000):
            slot = router.get_slot(f"key{i}")
            slots_used.add(slot)

        # Should use both halves
        lower_used = any(s < 8192 for s in slots_used)
        upper_used = any(s >= 8192 for s in slots_used)

        assert lower_used and upper_used


class TestConsistentHashingProperties:
    """Test mathematical properties of consistent hashing."""

    def test_deterministic(self):
        """Test that hashing is deterministic."""
        ring = ConsistentHashRing()

        ring.add_node("node1")

        results = [ring.get_node("key1") for _ in range(10)]

        assert all(r == results[0] for r in results)

    def test_balanced_distribution(self):
        """Test that distribution is reasonably balanced."""
        ring = ConsistentHashRing(virtual_nodes=100)

        for i in range(10):
            ring.add_node(f"node{i}")

        dist = ring.distribution()

        # Each node should have roughly equal distribution
        avg = sum(dist.values()) / len(dist)
        max_diff = max(abs(v - avg) for v in dist.values())

        # Allow 20% variance
        assert max_diff / avg < 0.2

    def test_minimal_key_migration(self):
        """Test that removing a node causes minimal key migration."""
        ring = ConsistentHashRing()

        ring.add_node("node1")
        ring.add_node("node2")
        ring.add_node("node3")

        # Map many keys
        original = {f"key{i}": ring.get_node(f"key{i}") for i in range(1000)}

        # Remove a node
        ring.remove_node("node2")

        # Map again
        new = {f"key{i}": ring.get_node(f"key{i}") for i in range(1000)}

        # Count changes that map to the removed node
        affected = sum(1 for k in original if original[k] == "node2")

        # Only keys that were on node2 should change
        changed = sum(1 for k in original if original[k] != new[k])

        assert changed <= affected * 1.1  # Allow 10% extra changes
