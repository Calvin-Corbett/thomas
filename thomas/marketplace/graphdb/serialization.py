"""Graph serialization: JSON, GraphML, DOT, edge list formats."""

import json
from typing import TYPE_CHECKING

from thomas.marketplace.graphdb._types import Edge, Node

if TYPE_CHECKING:
    from thomas.marketplace.graphdb.storage import GraphStorage


class GraphSerializer:
    """Serializes and deserializes graph data."""

    def __init__(self, storage: "GraphStorage") -> None:
        """Initialize serializer.

        Args:
            storage: Graph storage instance
        """
        self.storage = storage

    def to_json(self) -> str:
        """Export graph as JSON.

        Returns:
            JSON string with nodes and edges
        """
        nodes_list = []
        for node_id, node in self.storage.node_store.items():
            nodes_list.append(
                {
                    "id": node.id,
                    "labels": list(node.labels),
                    "properties": node.properties,
                }
            )

        edges_list = []
        for edge_id, edge in self.storage.edge_store.items():
            edges_list.append(
                {
                    "id": edge.id,
                    "source": edge.source,
                    "target": edge.target,
                    "type": edge.type,
                    "properties": edge.properties,
                }
            )

        data = {
            "nodes": nodes_list,
            "edges": edges_list,
            "metadata": {
                "node_count": len(nodes_list),
                "edge_count": len(edges_list),
            },
        }

        return json.dumps(data, indent=2)

    def from_json(self, json_str: str) -> None:
        """Import graph from JSON.

        Args:
            json_str: JSON string
        """
        data = json.loads(json_str)

        # Import nodes
        for node_data in data.get("nodes", []):
            node = Node(
                id=node_data["id"],
                labels=frozenset(node_data.get("labels", [])),
                properties=node_data.get("properties", {}),
            )
            self.storage.add_node(node)

        # Import edges
        for edge_data in data.get("edges", []):
            edge = Edge(
                id=edge_data["id"],
                source=edge_data["source"],
                target=edge_data["target"],
                type=edge_data["type"],
                properties=edge_data.get("properties", {}),
            )
            self.storage.add_edge(edge)

    def to_graphml(self) -> str:
        """Export graph as GraphML.

        Returns:
            GraphML string
        """
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<graphml xmlns="http://graphml.graphdrawing.org/xmlns" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
            '  xsi:schemaLocation="http://graphml.graphdrawing.org/xmlns http://graphml.graphdrawing.org/xmlns/1.0/graphml.xsd">',
            '  <graph id="G" edgedefault="directed">',
        ]

        # Add nodes
        for node_id, node in self.storage.node_store.items():
            labels_str = ",".join(node.labels) if node.labels else "Node"
            lines.append(f'    <node id="{self._escape_xml(node_id)}" label="{self._escape_xml(labels_str)}">')
            for key, value in node.properties.items():
                lines.append(f'      <data key="{key}">{self._escape_xml(str(value))}</data>')
            lines.append("    </node>")

        # Add edges
        for edge_id, edge in self.storage.edge_store.items():
            lines.append(
                f'    <edge id="{self._escape_xml(edge_id)}" source="{self._escape_xml(edge.source)}" '
                f'target="{self._escape_xml(edge.target)}" label="{self._escape_xml(edge.type)}">'
            )
            for key, value in edge.properties.items():
                lines.append(f'      <data key="{key}">{self._escape_xml(str(value))}</data>')
            lines.append("    </edge>")

        lines.append("  </graph>")
        lines.append("</graphml>")

        return "\n".join(lines)

    def to_dot(self) -> str:
        """Export graph as DOT format for Graphviz.

        Returns:
            DOT format string
        """
        lines = ["digraph G {"]
        lines.append("  rankdir=LR;")
        lines.append("  node [shape=ellipse];")

        # Add nodes with labels
        for node_id, node in self.storage.node_store.items():
            labels_str = ",".join(node.labels) if node.labels else "Node"
            lines.append(f'  "{self._escape_dot(node_id)}" [label="{self._escape_dot(labels_str)}"];')

        # Add edges
        for edge in self.storage.edge_store.values():
            lines.append(
                f'  "{self._escape_dot(edge.source)}" -> "{self._escape_dot(edge.target)}" '
                f'[label="{self._escape_dot(edge.type)}"];'
            )

        lines.append("}")
        return "\n".join(lines)

    def to_edge_list(self, include_properties: bool = False) -> str:
        """Export graph as edge list format.

        Args:
            include_properties: Whether to include edge properties

        Returns:
            Edge list string (one edge per line)
        """
        lines = []

        for edge in self.storage.edge_store.values():
            if include_properties:
                props_str = json.dumps(edge.properties)
                lines.append(f"{edge.source}\t{edge.target}\t{edge.type}\t{props_str}")
            else:
                lines.append(f"{edge.source}\t{edge.target}\t{edge.type}")

        return "\n".join(lines)

    def to_adjacency_matrix(self) -> dict[str, list[float]]:
        """Export graph as adjacency matrix.

        Returns:
            Dictionary with node order and matrix
        """
        node_ids = sorted(self.storage.node_store.keys())
        n = len(node_ids)
        node_to_idx = {nid: i for i, nid in enumerate(node_ids)}

        # Initialize matrix
        matrix = [[0.0] * n for _ in range(n)]

        # Fill matrix with edge weights
        for edge in self.storage.edge_store.values():
            if edge.source in node_to_idx and edge.target in node_to_idx:
                i = node_to_idx[edge.source]
                j = node_to_idx[edge.target]
                weight = edge.properties.get("weight", 1.0)
                if isinstance(weight, (int, float)):
                    matrix[i][j] = float(weight)

        return {
            "nodes": node_ids,
            "matrix": matrix,
        }

    def save_json(self, filepath: str) -> None:
        """Save graph as JSON file.

        Args:
            filepath: Output file path
        """
        with open(filepath, "w") as f:
            f.write(self.to_json())

    def load_json(self, filepath: str) -> None:
        """Load graph from JSON file.

        Args:
            filepath: Input file path
        """
        with open(filepath) as f:
            self.from_json(f.read())

    def save_graphml(self, filepath: str) -> None:
        """Save graph as GraphML file.

        Args:
            filepath: Output file path
        """
        with open(filepath, "w") as f:
            f.write(self.to_graphml())

    def save_dot(self, filepath: str) -> None:
        """Save graph as DOT file.

        Args:
            filepath: Output file path
        """
        with open(filepath, "w") as f:
            f.write(self.to_dot())

    def save_edge_list(self, filepath: str, include_properties: bool = False) -> None:
        """Save graph as edge list file.

        Args:
            filepath: Output file path
            include_properties: Whether to include properties
        """
        with open(filepath, "w") as f:
            f.write(self.to_edge_list(include_properties))

    @staticmethod
    def _escape_xml(text: str) -> str:
        """Escape XML special characters.

        Args:
            text: Text to escape

        Returns:
            Escaped text
        """
        replacements = {
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&apos;",
        }
        result = str(text)
        for char, escaped in replacements.items():
            result = result.replace(char, escaped)
        return result

    @staticmethod
    def _escape_dot(text: str) -> str:
        """Escape DOT special characters.

        Args:
            text: Text to escape

        Returns:
            Escaped text
        """
        return str(text).replace('"', '\\"').replace("\n", "\\n")
