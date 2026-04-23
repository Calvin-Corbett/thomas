"""Cypher-subset query engine with pattern matching and execution."""

from typing import TYPE_CHECKING, Any

from thomas.marketplace.graphdb._exceptions import (
    EdgeNotFoundError,
    GraphDBError,
    NodeNotFoundError,
)
from thomas.marketplace.graphdb._types import ASTNode, Edge, Node, PatternElement
from thomas.marketplace.graphdb.query_planner import parse_query

if TYPE_CHECKING:
    from thomas.marketplace.graphdb.storage import GraphStorage


class QueryExecutor:
    """Executes parsed Cypher queries."""

    def __init__(self, storage: "GraphStorage") -> None:
        """Initialize query executor.

        Args:
            storage: Graph storage instance
        """
        self.storage = storage

    def execute(self, query: str) -> list[dict[str, Any]]:
        """Execute a Cypher query string.

        Args:
            query: Cypher query string

        Returns:
            List of result rows

        Raises:
            QuerySyntaxError: If query syntax is invalid
        """
        ast = parse_query(query)
        return self._execute_ast(ast)

    def _execute_ast(self, ast: ASTNode) -> list[dict[str, Any]]:
        """Execute AST nodes."""
        results: list[dict[str, Any]] = []
        context: dict[str, Any] = {}

        for child in ast.children:
            if child.type == "MATCH":
                context.update(self._execute_match(child, context))
            elif child.type == "WHERE":
                context = self._execute_where(child, context)
            elif child.type == "CREATE":
                self._execute_create(child, context)
            elif child.type == "DELETE":
                self._execute_delete(child, context)
            elif child.type == "SET":
                self._execute_set(child, context)
            elif child.type == "RETURN":
                results = self._execute_return(child, context)
            elif child.type == "ORDER_BY":
                results = self._execute_order_by(child, results)
            elif child.type == "LIMIT":
                results = results[: child.value]
            elif child.type == "SKIP":
                results = results[child.value :]

        return results

    def _execute_match(self, match_node: ASTNode, context: dict[str, Any]) -> dict[str, Any]:
        """Execute MATCH clause."""
        new_context: dict[str, Any] = {}

        for pattern in match_node.children:
            if pattern.type == "PATTERN":
                matches = self._match_pattern(pattern, context)
                new_context.update(matches)

        return new_context

    def _match_pattern(self, pattern: ASTNode, context: dict[str, Any]) -> dict[str, Any]:
        """Match a pattern against the graph."""
        results: dict[str, Any] = {}
        nodes = []
        edges = []

        # Parse pattern structure
        for i, child in enumerate(pattern.children):
            if child.type == "NODE":
                nodes.append((i, child))
            elif child.type == "EDGE":
                edges.append((i, child))

        # Start pattern matching
        if nodes:
            first_node_idx, first_node = nodes[0]
            results = self._match_node_pattern(first_node, pattern, context)

        return results

    def _match_node_pattern(self, node_ast: ASTNode, pattern: ASTNode, context: dict[str, Any]) -> dict[str, Any]:
        """Match a node pattern."""
        elem: PatternElement = node_ast.value
        matches: dict[str, Any] = {}

        if elem.labels_or_type:
            # Find nodes with matching label
            for label in elem.labels_or_type:
                node_ids = self.storage.find_nodes_by_label(label)
                for node_id in node_ids:
                    node = self.storage.get_node(node_id)
                    if self._check_properties(node.properties, elem.properties):
                        if elem.variable:
                            matches[elem.variable] = node
        else:
            # Match any node
            for node_id, node in self.storage.node_store.items():
                if self._check_properties(node.properties, elem.properties):
                    if elem.variable:
                        matches[elem.variable] = node

        return matches

    def _check_properties(self, obj_props: dict[str, Any], pattern_props: dict[str, Any]) -> bool:
        """Check if object properties match pattern."""
        for key, value in pattern_props.items():
            if key not in obj_props or obj_props[key] != value:
                return False
        return True

    def _execute_where(self, where_node: ASTNode, context: dict[str, Any]) -> dict[str, Any]:
        """Execute WHERE clause."""
        if not where_node.value:
            return context

        expr = where_node.value
        if self._evaluate_expression(expr, context):
            return context
        return {}

    def _evaluate_expression(self, expr: ASTNode, context: dict[str, Any]) -> bool:
        """Evaluate a WHERE expression."""
        if expr.type == "AND":
            left = self._evaluate_expression(expr.children[0], context)
            right = self._evaluate_expression(expr.children[1], context)
            return left and right

        elif expr.type == "OR":
            left = self._evaluate_expression(expr.children[0], context)
            right = self._evaluate_expression(expr.children[1], context)
            return left or right

        elif expr.type == "NOT":
            return not self._evaluate_expression(expr.children[0], context)

        elif expr.type == "COMPARISON":
            left_val = self._evaluate_value(expr.children[0], context)
            right_val = self._evaluate_value(expr.children[1], context)
            op = expr.value

            if op == "=":
                return left_val == right_val
            elif op == "!=":
                return left_val != right_val
            elif op == "<":
                return left_val < right_val
            elif op == ">":
                return left_val > right_val
            elif op == "<=":
                return left_val <= right_val
            elif op == ">=":
                return left_val >= right_val

        return True

    def _evaluate_value(self, expr: ASTNode, context: dict[str, Any]) -> Any:
        """Evaluate an expression to get a value."""
        if expr.type == "LITERAL":
            return expr.value

        elif expr.type == "VARIABLE":
            var_name = expr.value
            if var_name in context:
                obj = context[var_name]
                if isinstance(obj, (Node, Edge)):
                    return obj
                return obj
            return None

        elif expr.type == "PROPERTY":
            parts = expr.value.split(".")
            if len(parts) == 2:
                var_name, prop_name = parts
                if var_name in context:
                    obj = context[var_name]
                    if isinstance(obj, (Node, Edge)):
                        return obj.get_property(prop_name)

        return None

    def _execute_create(self, create_node: ASTNode, context: dict[str, Any]) -> None:
        """Execute CREATE clause."""
        for pattern in create_node.children:
            if pattern.type == "PATTERN":
                self._create_pattern(pattern, context)

    def _create_pattern(self, pattern: ASTNode, context: dict[str, Any]) -> None:
        """Create nodes and edges from a pattern."""
        nodes_to_create: list[tuple[str, PatternElement]] = []
        edges_to_create: list[tuple[str, PatternElement, str, str]] = []

        # Collect node and edge specs
        current_source = None
        for i, child in enumerate(pattern.children):
            if child.type == "NODE":
                elem: PatternElement = child.value
                if elem.variable:
                    nodes_to_create.append((elem.variable, elem))
                    current_source = elem.variable

            elif child.type == "EDGE":
                elem: PatternElement = child.value
                # Next node is target
                if i + 1 < len(pattern.children):
                    next_child = pattern.children[i + 1]
                    if next_child.type == "NODE":
                        target_elem: PatternElement = next_child.value
                        target_var = target_elem.variable or f"node_{i}"
                        edges_to_create.append((elem.variable or f"edge_{i}", elem, current_source, target_var))

        # Create nodes
        for var_name, elem in nodes_to_create:
            labels = elem.labels_or_type or set()
            props = elem.properties
            node = Node(id=var_name, labels=frozenset(labels), properties=props)
            try:
                self.storage.add_node(node)
                context[var_name] = node
            except GraphDBError:
                pass  # Node may already exist

        # Create edges
        for edge_var, edge_elem, source_var, target_var in edges_to_create:
            source_id = source_var
            target_id = target_var
            edge_type = list(edge_elem.labels_or_type)[0] if edge_elem.labels_or_type else "RELATED"
            props = edge_elem.properties

            edge = Edge(id=edge_var, source=source_id, target=target_id, type=edge_type, properties=props)
            try:
                self.storage.add_edge(edge)
                context[edge_var] = edge
            except (GraphDBError, NodeNotFoundError):
                pass

    def _execute_delete(self, delete_node: ASTNode, context: dict[str, Any]) -> None:
        """Execute DELETE clause."""
        if not delete_node.value:
            return

        for var_name in delete_node.value:
            if var_name in context:
                obj = context[var_name]
                if isinstance(obj, Node):
                    try:
                        self.storage.delete_node(obj.id)
                    except NodeNotFoundError:
                        pass
                elif isinstance(obj, Edge):
                    try:
                        self.storage.delete_edge(obj.id)
                    except EdgeNotFoundError:
                        pass

    def _execute_set(self, set_node: ASTNode, context: dict[str, Any]) -> None:
        """Execute SET clause."""
        if not set_node.value:
            return

        for path, value_str in set_node.value.items():
            parts = path.split(".")
            if len(parts) == 2:
                var_name, prop_name = parts
                if var_name in context:
                    obj = context[var_name]
                    # Parse the value
                    value = self._parse_literal(value_str)

                    if isinstance(obj, Node):
                        props = dict(obj.properties)
                        props[prop_name] = value
                        updated = Node(id=obj.id, labels=obj.labels, properties=props)
                        self.storage.update_node(updated)
                        context[var_name] = updated

                    elif isinstance(obj, Edge):
                        props = dict(obj.properties)
                        props[prop_name] = value
                        updated = Edge(id=obj.id, source=obj.source, target=obj.target, type=obj.type, properties=props)
                        self.storage.update_edge(updated)
                        context[var_name] = updated

    def _execute_return(self, return_node: ASTNode, context: dict[str, Any]) -> list[dict[str, Any]]:
        """Execute RETURN clause."""
        results: list[dict[str, Any]] = []
        return_info = return_node.value or {}
        expressions = return_info.get("expressions", [])

        if not expressions:
            # Return entire context
            results.append(context.copy())
        else:
            for expr_str, alias in expressions:
                result = {}
                var_name = expr_str.strip()

                if var_name in context:
                    obj = context[var_name]
                    if isinstance(obj, Node):
                        result[alias or var_name] = {
                            "id": obj.id,
                            "labels": list(obj.labels),
                            "properties": obj.properties,
                        }
                    elif isinstance(obj, Edge):
                        result[alias or var_name] = {
                            "id": obj.id,
                            "source": obj.source,
                            "target": obj.target,
                            "type": obj.type,
                            "properties": obj.properties,
                        }
                    else:
                        result[alias or var_name] = obj

                if result:
                    results.append(result)

        return results

    def _execute_order_by(self, order_node: ASTNode, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Execute ORDER BY clause."""
        if not results or not order_node.value:
            return results

        for field, direction in reversed(order_node.value):
            reverse = direction == "DESC"
            try:
                results.sort(key=lambda r: self._get_sort_key(r, field), reverse=reverse)
            except (KeyError, TypeError):
                pass

        return results

    @staticmethod
    def _get_sort_key(row: dict[str, Any], field: str) -> Any:
        """Get sort key from a result row."""
        if field in row:
            val = row[field]
            if isinstance(val, dict) and "properties" in val:
                return val["properties"].get("name", "")
            return val
        return None

    @staticmethod
    def _parse_literal(value_str: str) -> Any:
        """Parse a literal value."""
        value_str = value_str.strip()

        if value_str == "true":
            return True
        elif value_str == "false":
            return False
        elif value_str == "null":
            return None
        elif (
            value_str.startswith('"')
            and value_str.endswith('"')
            or value_str.startswith("'")
            and value_str.endswith("'")
        ):
            return value_str[1:-1]
        else:
            try:
                if "." in value_str:
                    return float(value_str)
                return int(value_str)
            except ValueError:
                return value_str


def execute_query(storage: "GraphStorage", query: str) -> list[dict[str, Any]]:
    """Execute a Cypher query.

    Args:
        storage: Graph storage instance
        query: Cypher query string

    Returns:
        List of result rows

    Raises:
        QuerySyntaxError: If query syntax is invalid
    """
    executor = QueryExecutor(storage)
    return executor.execute(query)
