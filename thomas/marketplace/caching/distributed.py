"""Consistent hashing ring for distributed cache."""

from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger(__name__)


class ConsistentHashRing:
    """Implements consistent hashing for distributed cache nodes.

    Distributes keys across nodes with minimal redistribution when
    nodes are added or removed. Uses virtual nodes to improve distribution.

    Attributes:
        nodes: Set of current nodes in the ring.
        virtual_nodes: Number of virtual nodes per physical node.
    """

    def __init__(self, virtual_nodes: int = 150) -> None:
        """Initialize the consistent hash ring.

        Args:
            virtual_nodes: Number of virtual nodes per physical node.

        Raises:
            ValueError: If virtual_nodes is not positive.
        """
        if virtual_nodes <= 0:
            raise ValueError("virtual_nodes must be positive")

        self.virtual_nodes = virtual_nodes
        self.nodes: set[str] = set()
        self._ring: dict[int, str] = {}
        self._sorted_keys: list[int] = []
        logger.info("Initialized consistent hash ring (virtual_nodes=%d)", virtual_nodes)

    def add_node(self, node: str) -> None:
        """Add a node to the ring.

        Args:
            node: Node identifier.
        """
        if node in self.nodes:
            logger.warning("Node already exists: %s", node)
            return

        self.nodes.add(node)

        # Add virtual nodes
        for i in range(self.virtual_nodes):
            virtual_key = f"{node}:{i}"
            hash_value = self._hash(virtual_key)
            self._ring[hash_value] = node

        # Rebuild sorted keys
        self._sorted_keys = sorted(self._ring.keys())
        logger.info("Added node: %s (added %d virtual nodes)", node, self.virtual_nodes)

    def remove_node(self, node: str) -> None:
        """Remove a node from the ring.

        Args:
            node: Node identifier.
        """
        if node not in self.nodes:
            logger.warning("Node not found: %s", node)
            return

        self.nodes.discard(node)

        # Remove virtual nodes
        keys_to_remove = [hash_value for hash_value, n in self._ring.items() if n == node]
        for hash_value in keys_to_remove:
            del self._ring[hash_value]

        # Rebuild sorted keys
        self._sorted_keys = sorted(self._ring.keys())
        logger.info("Removed node: %s (removed %d virtual nodes)", node, len(keys_to_remove))

    def get_node(self, key: str) -> str | None:
        """Get the node responsible for a key.

        Uses binary search to find the first node with a hash >= the key's hash.

        Args:
            key: The key to locate.

        Returns:
            The node identifier, or None if ring is empty.
        """
        if not self._ring:
            logger.warning("Ring is empty, cannot locate key: %s", key)
            return None

        hash_value = self._hash(key)
        return self._find_node(hash_value)

    def get_nodes(self, key: str, count: int = 1) -> list[str]:
        """Get multiple nodes for a key (for replication).

        Args:
            key: The key to locate.
            count: Number of nodes to return.

        Returns:
            List of node identifiers.
        """
        if not self._ring:
            return []

        if count > len(self.nodes):
            count = len(self.nodes)

        hash_value = self._hash(key)
        nodes = []
        seen: set[str] = set()

        # Find primary and replicas
        idx = self._find_node_index(hash_value)
        if idx is None:
            return []

        for i in range(len(self._sorted_keys) * 2):
            node = self._ring[self._sorted_keys[(idx + i) % len(self._sorted_keys)]]
            if node not in seen:
                nodes.append(node)
                seen.add(node)
                if len(nodes) >= count:
                    break

        return nodes

    def distribution(self) -> dict[str, int]:
        """Get the distribution of keys across nodes.

        Returns:
            Dictionary mapping nodes to number of virtual nodes.
        """
        dist: dict[str, int] = {node: 0 for node in self.nodes}
        for node in self._ring.values():
            dist[node] += 1
        return dist

    def rebalance_info(self) -> dict[str, int]:
        """Get information about redistribution needed.

        Shows how many keys would need to move if each node were removed.

        Returns:
            Dictionary mapping nodes to estimated keys to redistribute.
        """
        if not self.nodes:
            return {}

        avg_keys = sum(self.distribution().values()) / len(self.nodes)
        rebalance: dict[str, int] = {}

        for node in self.nodes:
            current = self.distribution().get(node, 0)
            rebalance[node] = abs(current - int(avg_keys))

        return rebalance

    def _hash(self, value: str) -> int:
        """Hash a value to a ring position.

        Args:
            value: The value to hash.

        Returns:
            Hash value as integer.
        """
        hash_obj = hashlib.md5(value.encode("utf-8"))
        return int(hash_obj.hexdigest(), 16)

    def _find_node(self, hash_value: int) -> str | None:
        """Find the node for a hash value.

        Args:
            hash_value: The hash value.

        Returns:
            The node identifier, or None if ring is empty.
        """
        idx = self._find_node_index(hash_value)
        if idx is None:
            return None
        return self._ring[self._sorted_keys[idx]]

    def _find_node_index(self, hash_value: int) -> int | None:
        """Find the index of the node for a hash value using binary search.

        Args:
            hash_value: The hash value.

        Returns:
            Index in _sorted_keys, or None if ring is empty.
        """
        if not self._sorted_keys:
            return None

        # Binary search for the first key >= hash_value
        left, right = 0, len(self._sorted_keys)

        while left < right:
            mid = (left + right) // 2
            if self._sorted_keys[mid] < hash_value:
                left = mid + 1
            else:
                right = mid

        # If not found, wrap around to the beginning
        if left >= len(self._sorted_keys):
            return 0

        return left


class HashSlot:
    """Represents a hash slot in the ring."""

    def __init__(self, slot: int, node: str) -> None:
        """Initialize a hash slot.

        Args:
            slot: The slot number (0-16383 for Redis-like slots).
            node: The node responsible for this slot.
        """
        self.slot = slot
        self.node = node

    def __repr__(self) -> str:
        """String representation."""
        return f"HashSlot({self.slot}, {self.node})"


class SlotBasedRouter:
    """Routes keys to nodes using hash slots (Redis-style).

    Fixed set of 16384 slots, easier to reason about than consistent hashing.
    """

    SLOT_COUNT = 16384

    def __init__(self) -> None:
        """Initialize the slot-based router."""
        self._slots: list[str | None] = [None] * self.SLOT_COUNT
        self.nodes: set[str] = set()

    def assign_slots(self, node: str, start: int, end: int) -> None:
        """Assign a range of slots to a node.

        Args:
            node: The node identifier.
            start: Starting slot (inclusive).
            end: Ending slot (inclusive).

        Raises:
            ValueError: If slot range is invalid.
        """
        if start < 0 or end >= self.SLOT_COUNT or start > end:
            raise ValueError(f"Invalid slot range: {start}-{end}")

        self.nodes.add(node)
        for i in range(start, end + 1):
            self._slots[i] = node

        logger.info("Assigned slots %d-%d to node: %s", start, end, node)

    def get_slot(self, key: str) -> int:
        """Get the slot for a key.

        Args:
            key: The key.

        Returns:
            Slot number (0-16383).
        """
        hash_value = int(hashlib.md5(key.encode("utf-8")).hexdigest(), 16)
        return hash_value % self.SLOT_COUNT

    def get_node(self, key: str) -> str | None:
        """Get the node for a key.

        Args:
            key: The key.

        Returns:
            The node identifier, or None if slot is unassigned.
        """
        slot = self.get_slot(key)
        return self._slots[slot]

    def get_slot_node(self, slot: int) -> str | None:
        """Get the node for a slot.

        Args:
            slot: The slot number.

        Returns:
            The node identifier, or None if slot is unassigned.

        Raises:
            ValueError: If slot is invalid.
        """
        if slot < 0 or slot >= self.SLOT_COUNT:
            raise ValueError(f"Invalid slot: {slot}")
        return self._slots[slot]

    def redistribution_needed(self, node: str) -> dict[int, str | None]:
        """Get slots that would need to move if a node were removed.

        Args:
            node: The node to analyze.

        Returns:
            Dictionary of affected slots and their current assignments.
        """
        affected = {}
        for i, assigned_node in enumerate(self._slots):
            if assigned_node == node:
                affected[i] = None

        return affected

    def distribution(self) -> dict[str, int]:
        """Get the distribution of slots across nodes.

        Returns:
            Dictionary mapping nodes to number of slots.
        """
        dist: dict[str, int] = {node: 0 for node in self.nodes}
        for node in self._slots:
            if node is not None:
                dist[node] = dist.get(node, 0) + 1

        return dist

    def coverage(self) -> float:
        """Get the percentage of slots that are assigned.

        Returns:
            Coverage as a ratio from 0.0 to 1.0.
        """
        assigned = sum(1 for slot in self._slots if slot is not None)
        return assigned / self.SLOT_COUNT if self.SLOT_COUNT > 0 else 0.0
