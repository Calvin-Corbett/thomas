"""HTTP/2 priority and dependency tree management."""

from thomas.http2._exceptions import StreamError


class PriorityNode:
    """Represents a node in the HTTP/2 priority tree."""

    def __init__(self, stream_id: int, weight: int = 16) -> None:
        """Initialize priority node.

        Args:
            stream_id: Stream ID.
            weight: Stream weight (1-256, default 16).

        Raises:
            ValueError: If weight is invalid.
        """
        if weight < 1 or weight > 256:
            raise ValueError(f"Weight must be 1-256, got {weight}")

        self.stream_id = stream_id
        self.weight = weight
        self.parent: int | None = None
        self.children: dict[int, int] = {}  # child_id -> weight
        self.exclusive = False

    def add_child(self, child_id: int, weight: int, exclusive: bool = False) -> None:
        """Add a child stream.

        Args:
            child_id: Child stream ID.
            weight: Child weight.
            exclusive: Whether dependency is exclusive.
        """
        if exclusive and self.children:
            # Move existing children to child
            self.children[child_id] = weight
        else:
            self.children[child_id] = weight

    def remove_child(self, child_id: int) -> None:
        """Remove a child stream.

        Args:
            child_id: Child stream ID.
        """
        self.children.pop(child_id, None)


class PriorityTree:
    """Manages HTTP/2 stream priority tree."""

    def __init__(self) -> None:
        """Initialize priority tree."""
        # Virtual root stream (stream 0)
        self.root = PriorityNode(0, 1)
        self.nodes: dict[int, PriorityNode] = {0: self.root}

    def create_stream(
        self,
        stream_id: int,
        depends_on: int = 0,
        weight: int = 16,
        exclusive: bool = False,
    ) -> None:
        """Create a new stream in the priority tree.

        Args:
            stream_id: Stream ID.
            depends_on: Parent stream ID (0 = root).
            weight: Stream weight (1-256).
            exclusive: Whether dependency is exclusive.

        Raises:
            ValueError: If stream already exists or parameters invalid.
            StreamError: If parent doesn't exist.
        """
        if stream_id in self.nodes:
            raise ValueError(f"Stream {stream_id} already exists")

        if depends_on not in self.nodes:
            # Auto-create dependency on root
            depends_on = 0

        node = PriorityNode(stream_id, weight)
        parent = self.nodes[depends_on]

        if exclusive:
            # Steal all children from parent
            for child_id, child_weight in list(parent.children.items()):
                node.add_child(child_id, child_weight)
            parent.children.clear()

        parent.add_child(stream_id, weight, exclusive=False)
        node.parent = depends_on
        self.nodes[stream_id] = node

    def remove_stream(self, stream_id: int) -> None:
        """Remove a stream from the priority tree.

        Any children move to the removed stream's parent.

        Args:
            stream_id: Stream ID.

        Raises:
            ValueError: If stream doesn't exist.
        """
        if stream_id not in self.nodes:
            raise ValueError(f"Stream {stream_id} doesn't exist")

        if stream_id == 0:
            raise ValueError("Cannot remove root stream")

        node = self.nodes[stream_id]
        parent_id = node.parent or 0
        parent = self.nodes[parent_id]

        # Move children to parent
        for child_id, child_weight in node.children.items():
            child_node = self.nodes[child_id]
            child_node.parent = parent_id
            parent.add_child(child_id, child_weight)

        # Remove from parent
        if parent_id in self.nodes:
            parent.remove_child(stream_id)

        del self.nodes[stream_id]

    def reprioritize_stream(
        self,
        stream_id: int,
        depends_on: int = 0,
        weight: int = 16,
        exclusive: bool = False,
    ) -> None:
        """Change a stream's priority.

        Args:
            stream_id: Stream ID.
            depends_on: New parent stream ID.
            weight: New weight.
            exclusive: Whether new dependency is exclusive.

        Raises:
            ValueError: If stream doesn't exist.
            StreamError: If would create cycle.
        """
        if stream_id not in self.nodes:
            raise ValueError(f"Stream {stream_id} doesn't exist")

        if stream_id == 0:
            raise ValueError("Cannot reprioritize root stream")

        if depends_on == stream_id:
            raise ValueError("Stream cannot depend on itself")

        # Check for cycle
        if self._would_create_cycle(stream_id, depends_on):
            raise StreamError(f"Reprioritizing {stream_id} to depend on {depends_on} would create cycle")

        node = self.nodes[stream_id]
        old_parent_id = node.parent or 0
        old_parent = self.nodes[old_parent_id]

        # Remove from old parent
        old_parent.remove_child(stream_id)

        # Add to new parent
        depends_on = depends_on or 0
        if depends_on not in self.nodes:
            depends_on = 0

        new_parent = self.nodes[depends_on]

        if exclusive:
            # Steal children from new parent
            for child_id, child_weight in list(new_parent.children.items()):
                if child_id != stream_id:
                    node.add_child(child_id, child_weight)
            new_parent.children.clear()

        new_parent.add_child(stream_id, weight)
        node.parent = depends_on
        node.weight = weight

    def get_stream_priority(self, stream_id: int) -> tuple[int, int, bool]:
        """Get a stream's priority information.

        Args:
            stream_id: Stream ID.

        Returns:
            Tuple of (depends_on, weight, exclusive).

        Raises:
            ValueError: If stream doesn't exist.
        """
        if stream_id not in self.nodes:
            raise ValueError(f"Stream {stream_id} doesn't exist")

        node = self.nodes[stream_id]
        depends_on = node.parent or 0
        return depends_on, node.weight, node.exclusive

    def get_stream_weight(self, stream_id: int) -> int:
        """Get a stream's weight.

        Args:
            stream_id: Stream ID.

        Returns:
            Weight value (1-256).

        Raises:
            ValueError: If stream doesn't exist.
        """
        if stream_id not in self.nodes:
            raise ValueError(f"Stream {stream_id} doesn't exist")

        return self.nodes[stream_id].weight

    def get_children(self, stream_id: int) -> dict[int, int]:
        """Get direct children of a stream.

        Args:
            stream_id: Stream ID.

        Returns:
            Dictionary of child_id -> weight.

        Raises:
            ValueError: If stream doesn't exist.
        """
        if stream_id not in self.nodes:
            raise ValueError(f"Stream {stream_id} doesn't exist")

        return dict(self.nodes[stream_id].children)

    def get_parent(self, stream_id: int) -> int | None:
        """Get parent of a stream.

        Args:
            stream_id: Stream ID.

        Returns:
            Parent stream ID or None.

        Raises:
            ValueError: If stream doesn't exist.
        """
        if stream_id not in self.nodes:
            raise ValueError(f"Stream {stream_id} doesn't exist")

        parent = self.nodes[stream_id].parent
        return parent if parent != 0 else None

    def get_schedulable_streams(self) -> list[int]:
        """Get list of active (non-closed) streams in priority order.

        Returns:
            List of stream IDs ordered by priority.
        """
        # Breadth-first traversal from root
        streams = []
        queue = [(0, 0)]  # (stream_id, depth)

        while queue:
            stream_id, depth = queue.pop(0)
            if stream_id != 0:
                streams.append(stream_id)

            node = self.nodes.get(stream_id)
            if node:
                # Sort children by weight (higher weight = higher priority)
                for child_id in sorted(
                    node.children.keys(),
                    key=lambda cid: self.nodes[cid].weight,
                    reverse=True,
                ):
                    queue.append((child_id, depth + 1))

        return streams

    def calculate_bandwidth_allocation(self, parent_id: int) -> dict[int, float]:
        """Calculate bandwidth allocation for children using weighted fair queuing.

        Args:
            parent_id: Parent stream ID.

        Returns:
            Dictionary of child_id -> allocation (0.0-1.0).

        Raises:
            ValueError: If stream doesn't exist.
        """
        if parent_id not in self.nodes:
            raise ValueError(f"Stream {parent_id} doesn't exist")

        parent = self.nodes[parent_id]
        children = parent.children

        if not children:
            return {}

        total_weight = sum(children.values())
        allocation = {}

        for child_id, weight in children.items():
            allocation[child_id] = weight / total_weight

        return allocation

    def _would_create_cycle(self, stream_id: int, depends_on: int) -> bool:
        """Check if making stream_id depend on depends_on would create a cycle.

        Args:
            stream_id: Stream to move.
            depends_on: New parent.

        Returns:
            True if would create cycle.
        """
        # Walk up from depends_on to root
        current = depends_on
        visited: set[int] = set()

        while current in self.nodes and current != 0:
            if current == stream_id:
                return True
            if current in visited:
                break  # Cycle in tree, shouldn't happen
            visited.add(current)
            current = self.nodes[current].parent or 0

        return False

    def get_all_streams(self) -> list[int]:
        """Get all stream IDs in tree.

        Returns:
            List of all stream IDs except root.
        """
        return [sid for sid in self.nodes.keys() if sid != 0]

    def dump_tree(self, stream_id: int = 0, indent: int = 0) -> str:
        """Dump tree structure for debugging.

        Args:
            stream_id: Root of subtree to dump (0 = full tree).
            indent: Current indentation level.

        Returns:
            String representation of tree.
        """
        if stream_id not in self.nodes:
            return ""

        node = self.nodes[stream_id]
        prefix = "  " * indent
        lines = []

        if stream_id == 0:
            lines.append(f"{prefix}[ROOT]")
        else:
            lines.append(f"{prefix}Stream {stream_id} (weight={node.weight})")

        for child_id in sorted(node.children.keys()):
            lines.append(self.dump_tree(child_id, indent + 1))

        return "\n".join(lines)
