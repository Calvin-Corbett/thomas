"""
Edge computing simulation for distributed IoT processing.

Provides edge node management, local rule processing, data
aggregation, offline operation, and cloud synchronization.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import uuid4

from thomas.iot_platform._exceptions import IoTException
from thomas.iot_platform._types import TelemetryPoint


class EdgeNodeManager:
    """
    Manages edge nodes for distributed IoT computing.

    Provides local processing, data aggregation, offline queue,
    and cloud synchronization.
    """

    def __init__(self) -> None:
        """Initialize the edge node manager."""
        self._nodes: dict[str, dict[str, Any]] = {}
        self._local_rules: dict[str, list[dict[str, Any]]] = {}
        self._offline_queue: dict[str, list[TelemetryPoint]] = {}
        self._aggregation_windows: dict[str, dict[str, list[float]]] = {}
        self._sync_handlers: list[Callable[[str, list[TelemetryPoint]], None]] = []
        self._lock = threading.RLock()

    def create_edge_node(
        self,
        node_id: str,
        location: str,
        capacity_mb: int,
    ) -> dict[str, Any]:
        """
        Create an edge computing node.

        Args:
            node_id: Unique node identifier.
            location: Geographic or logical location.
            capacity_mb: Storage capacity in MB.

        Returns:
            Edge node configuration.

        Raises:
            IoTException: If node already exists.
        """
        with self._lock:
            if node_id in self._nodes:
                raise IoTException(f"Edge node {node_id} already exists")

            node = {
                "node_id": node_id,
                "location": location,
                "capacity_mb": capacity_mb,
                "used_mb": 0,
                "created_at": datetime.utcnow(),
                "connected": False,
                "last_sync": None,
                "processing_rules": 0,
                "devices_connected": 0,
            }

            self._nodes[node_id] = node
            self._local_rules[node_id] = []
            self._offline_queue[node_id] = []
            self._aggregation_windows[node_id] = {}

            return node

    def connect_edge_node(self, node_id: str) -> dict[str, Any]:
        """
        Connect an edge node to cloud.

        Args:
            node_id: Node ID to connect.

        Returns:
            Updated node state.

        Raises:
            IoTException: If node not found.
        """
        with self._lock:
            if node_id not in self._nodes:
                raise IoTException(f"Edge node {node_id} not found")

            node = self._nodes[node_id]
            node["connected"] = True
            node["last_sync"] = datetime.utcnow()

            return node

    def disconnect_edge_node(self, node_id: str) -> dict[str, Any]:
        """
        Disconnect an edge node from cloud.

        Args:
            node_id: Node ID to disconnect.

        Returns:
            Updated node state.

        Raises:
            IoTException: If node not found.
        """
        with self._lock:
            if node_id not in self._nodes:
                raise IoTException(f"Edge node {node_id} not found")

            node = self._nodes[node_id]
            node["connected"] = False

            return node

    def add_local_rule(
        self,
        node_id: str,
        rule: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Add a rule to be processed locally on edge node.

        Args:
            node_id: Target edge node.
            rule: Rule specification.

        Returns:
            Rule with edge node ID.

        Raises:
            IoTException: If node not found.
        """
        with self._lock:
            if node_id not in self._nodes:
                raise IoTException(f"Edge node {node_id} not found")

            rule_with_id = {
                **rule,
                "rule_id": str(uuid4()),
                "edge_node_id": node_id,
                "created_at": datetime.utcnow().isoformat(),
            }

            self._local_rules[node_id].append(rule_with_id)
            self._nodes[node_id]["processing_rules"] += 1

            return rule_with_id

    def process_telemetry_local(
        self,
        node_id: str,
        point: TelemetryPoint,
    ) -> list[dict[str, Any]]:
        """
        Process telemetry locally on edge node.

        Args:
            node_id: Edge node processing.
            point: Telemetry point to process.

        Returns:
            List of triggered rule actions.

        Raises:
            IoTException: If node not found.
        """
        with self._lock:
            if node_id not in self._nodes:
                raise IoTException(f"Edge node {node_id} not found")

            node = self._nodes[node_id]

            # Check if node has capacity
            point_size = len(str(point.to_dict())) / 1024  # KB

            if node["used_mb"] + (point_size / 1024) > node["capacity_mb"]:
                # Queue for later processing
                self._offline_queue[node_id].append(point)
                return []

            actions = []

            # Evaluate local rules
            for rule in self._local_rules[node_id]:
                if self._evaluate_local_condition(rule.get("condition"), point):
                    actions.extend(rule.get("actions", []))

            # Update used capacity
            node["used_mb"] += point_size / 1024

            return actions

    def _evaluate_local_condition(
        self,
        condition: dict[str, Any] | None,
        point: TelemetryPoint,
    ) -> bool:
        """Evaluate rule condition locally."""
        if not condition:
            return False

        cond_type = condition.get("type")

        if cond_type == "threshold":
            metric = condition.get("metric")
            operator = condition.get("operator")
            value = condition.get("value")

            if metric != point.metric:
                return False

            if not isinstance(point.value, (int, float)):
                return False

            point_value = float(point.value)

            if operator == ">":
                return point_value > value
            elif operator == "<":
                return point_value < value
            elif operator == ">=":
                return point_value >= value
            elif operator == "<=":
                return point_value <= value

        return False

    def queue_offline_data(
        self,
        node_id: str,
        points: list[TelemetryPoint],
    ) -> int:
        """
        Queue telemetry for offline processing.

        Args:
            node_id: Edge node.
            points: Telemetry points to queue.

        Returns:
            Number of points queued.

        Raises:
            IoTException: If node not found.
        """
        with self._lock:
            if node_id not in self._nodes:
                raise IoTException(f"Edge node {node_id} not found")

            for point in points:
                self._offline_queue[node_id].append(point)

            return len(points)

    def sync_to_cloud(self, node_id: str) -> list[TelemetryPoint]:
        """
        Sync queued data from edge node to cloud.

        Args:
            node_id: Edge node to sync.

        Returns:
            List of synced points.

        Raises:
            IoTException: If node not found.
        """
        with self._lock:
            if node_id not in self._nodes:
                raise IoTException(f"Edge node {node_id} not found")

            node = self._nodes[node_id]
            queue = self._offline_queue[node_id]

            synced = list(queue)
            queue.clear()

            node["last_sync"] = datetime.utcnow()
            node["used_mb"] = 0

            # Notify sync handlers
            for handler in self._sync_handlers:
                try:
                    handler(node_id, synced)
                except (ValueError, TypeError):
                    pass

            return synced

    def aggregate_at_edge(
        self,
        node_id: str,
        metric: str,
        values: list[float],
        aggregation: str = "avg",
    ) -> float:
        """
        Perform data aggregation at edge.

        Args:
            node_id: Edge node.
            metric: Metric name.
            values: Values to aggregate.
            aggregation: Aggregation type.

        Returns:
            Aggregated value.
        """
        if not values:
            return 0.0

        if aggregation == "avg":
            return sum(values) / len(values)
        elif aggregation == "min":
            return min(values)
        elif aggregation == "max":
            return max(values)
        elif aggregation == "sum":
            return sum(values)
        elif aggregation == "count":
            return float(len(values))

        return 0.0

    def send_only_deltas(
        self,
        node_id: str,
        current_values: dict[str, float],
        previous_values: dict[str, float] | None = None,
        threshold: float = 0.1,
    ) -> dict[str, float]:
        """
        Filter values to send only significant changes (deltas).

        Args:
            node_id: Edge node.
            current_values: Current metric values.
            previous_values: Previous metric values.
            threshold: Minimum change percentage to send.

        Returns:
            Filtered values with only significant changes.
        """
        if not previous_values:
            return current_values

        deltas = {}

        for key, current in current_values.items():
            previous = previous_values.get(key, current)

            if previous == 0:
                if current != previous:
                    deltas[key] = current
            else:
                change_pct = abs((current - previous) / previous)

                if change_pct >= threshold:
                    deltas[key] = current

        return deltas

    def get_edge_node(self, node_id: str) -> dict[str, Any] | None:
        """
        Get edge node information.

        Args:
            node_id: Node ID.

        Returns:
            Node data or None if not found.
        """
        with self._lock:
            return self._nodes.get(node_id)

    def list_edge_nodes(self) -> list[dict[str, Any]]:
        """List all edge nodes."""
        with self._lock:
            return list(self._nodes.values())

    def get_node_queue_size(self, node_id: str) -> int:
        """
        Get offline queue size for edge node.

        Args:
            node_id: Node ID.

        Returns:
            Number of queued telemetry points.
        """
        with self._lock:
            if node_id not in self._offline_queue:
                return 0
            return len(self._offline_queue[node_id])

    def register_sync_handler(
        self,
        handler: Callable[[str, list[TelemetryPoint]], None],
    ) -> None:
        """
        Register handler for cloud sync events.

        Args:
            handler: Callable receiving (node_id, synced_points).
        """
        with self._lock:
            self._sync_handlers.append(handler)

    def get_node_stats(self, node_id: str) -> dict[str, Any]:
        """
        Get statistics for an edge node.

        Args:
            node_id: Node ID.

        Returns:
            Node statistics.

        Raises:
            IoTException: If node not found.
        """
        with self._lock:
            if node_id not in self._nodes:
                raise IoTException(f"Edge node {node_id} not found")

            node = self._nodes[node_id]

            return {
                "node_id": node_id,
                "connected": node["connected"],
                "capacity_mb": node["capacity_mb"],
                "used_mb": node["used_mb"],
                "free_mb": node["capacity_mb"] - node["used_mb"],
                "local_rules": len(self._local_rules[node_id]),
                "queued_data_points": len(self._offline_queue[node_id]),
                "last_sync": node["last_sync"].isoformat() if node["last_sync"] else None,
                "uptime_seconds": (datetime.utcnow() - node["created_at"]).total_seconds(),
            }

    def delete_edge_node(self, node_id: str) -> bool:
        """
        Delete an edge node.

        Args:
            node_id: Node ID.

        Returns:
            True if deleted successfully.
        """
        with self._lock:
            if node_id in self._nodes:
                del self._nodes[node_id]

            if node_id in self._local_rules:
                del self._local_rules[node_id]

            if node_id in self._offline_queue:
                del self._offline_queue[node_id]

            if node_id in self._aggregation_windows:
                del self._aggregation_windows[node_id]

            return True

        return False

    def get_edge_node_count(self) -> int:
        """Get total number of edge nodes."""
        with self._lock:
            return len(self._nodes)
