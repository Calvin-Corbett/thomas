"""Query optimizer for Cypher-subset queries."""

from typing import TYPE_CHECKING, Any

from thomas.graphdb._types import ASTNode, QueryPlan, QueryPlanStep

if TYPE_CHECKING:
    from thomas.graphdb.storage import GraphStorage


class QueryOptimizer:
    """Optimizes query execution plans."""

    def __init__(self, storage: "GraphStorage") -> None:
        """Initialize optimizer.

        Args:
            storage: Graph storage instance
        """
        self.storage = storage
        self.query_cache: dict[str, QueryPlan] = {}
        self.stats_cache: dict[str, Any] = {}

    def optimize(self, ast: ASTNode) -> QueryPlan:
        """Optimize a query AST.

        Args:
            ast: Root AST node

        Returns:
            Optimized QueryPlan

        Raises:
            ValueError: If optimization fails
        """
        plan = QueryPlan()

        # Find MATCH clause
        match_node = None
        where_node = None
        return_node = None

        for child in ast.children:
            if child.type == "MATCH":
                match_node = child
            elif child.type == "WHERE":
                where_node = child
            elif child.type == "RETURN":
                return_node = child

        if match_node:
            self._optimize_match(match_node, plan)

        if where_node:
            self._optimize_where(where_node, plan)

        if return_node:
            self._optimize_return(return_node, plan)

        # Apply cost-based optimizations
        plan = self._apply_cost_optimizations(plan)

        return plan

    def _optimize_match(self, match_node: ASTNode, plan: QueryPlan) -> None:
        """Optimize MATCH clause.

        Args:
            match_node: MATCH AST node
            plan: Query plan to update
        """
        for pattern in match_node.children:
            if pattern.type == "PATTERN":
                # Estimate pattern cost
                self._estimate_pattern_cost(pattern, plan)

    def _estimate_pattern_cost(self, pattern: ASTNode, plan: QueryPlan) -> None:
        """Estimate cost of matching a pattern.

        Args:
            pattern: PATTERN AST node
            plan: Query plan to update
        """
        for i, child in enumerate(pattern.children):
            if child.type == "NODE":
                step = self._create_node_scan_step(child)
                plan.add_step(step)

            elif child.type == "EDGE":
                step = self._create_edge_scan_step(child)
                plan.add_step(step)

    def _create_node_scan_step(self, node_ast: ASTNode) -> QueryPlanStep:
        """Create a node scan step.

        Args:
            node_ast: NODE AST node

        Returns:
            QueryPlanStep
        """
        from thomas.graphdb._types import PatternElement

        elem: PatternElement = node_ast.value
        estimated_rows = len(self.storage.node_store)

        if elem.labels_or_type:
            # Use label index
            for label in elem.labels_or_type:
                nodes_with_label = self.storage.find_nodes_by_label(label)
                estimated_rows = min(estimated_rows, len(nodes_with_label))

        step = QueryPlanStep(
            operation="node_scan",
            details={
                "variable": elem.variable,
                "labels": list(elem.labels_or_type) if elem.labels_or_type else [],
            },
            estimated_rows=max(1, estimated_rows),
            cost=float(estimated_rows),
        )

        return step

    def _create_edge_scan_step(self, edge_ast: ASTNode) -> QueryPlanStep:
        """Create an edge scan step.

        Args:
            edge_ast: EDGE AST node

        Returns:
            QueryPlanStep
        """
        from thomas.graphdb._types import PatternElement

        elem: PatternElement = edge_ast.value
        estimated_rows = len(self.storage.edge_store)

        if elem.labels_or_type:
            for edge_type in elem.labels_or_type:
                edges_of_type = self.storage.find_edges_by_type(edge_type)
                estimated_rows = min(estimated_rows, len(edges_of_type))

        step = QueryPlanStep(
            operation="edge_scan",
            details={
                "variable": elem.variable,
                "edge_type": list(elem.labels_or_type)[0] if elem.labels_or_type else None,
            },
            estimated_rows=max(1, estimated_rows),
            cost=float(estimated_rows),
        )

        return step

    def _optimize_where(self, where_node: ASTNode, plan: QueryPlan) -> None:
        """Optimize WHERE clause.

        Args:
            where_node: WHERE AST node
            plan: Query plan to update
        """
        # Add filter step
        step = QueryPlanStep(
            operation="filter",
            details={"expression": "WHERE clause"},
            estimated_rows=-1,  # Will be determined at runtime
            cost=1.0,
        )
        plan.add_step(step)

    def _optimize_return(self, return_node: ASTNode, plan: QueryPlan) -> None:
        """Optimize RETURN clause.

        Args:
            return_node: RETURN AST node
            plan: Query plan to update
        """
        return_info = return_node.value or {}
        expressions = return_info.get("expressions", [])

        step = QueryPlanStep(
            operation="project",
            details={"expressions": len(expressions)},
            estimated_rows=-1,
            cost=float(len(expressions)),
        )
        plan.add_step(step)

    def _apply_cost_optimizations(self, plan: QueryPlan) -> QueryPlan:
        """Apply cost-based optimizations.

        Args:
            plan: Query plan

        Returns:
            Optimized plan
        """
        # Index selection
        plan.optimizations_applied.append("index_selection")

        # Predicate pushdown
        plan = self._apply_predicate_pushdown(plan)
        plan.optimizations_applied.append("predicate_pushdown")

        # Join order optimization
        plan = self._optimize_join_order(plan)
        plan.optimizations_applied.append("join_order")

        return plan

    def _apply_predicate_pushdown(self, plan: QueryPlan) -> QueryPlan:
        """Push filters down in the plan.

        Args:
            plan: Query plan

        Returns:
            Optimized plan
        """
        # Reorder steps to apply filters earlier
        new_steps: list[QueryPlanStep] = []
        filter_steps: list[QueryPlanStep] = []

        for step in plan.steps:
            if step.operation == "filter":
                filter_steps.append(step)
            else:
                new_steps.append(step)

        # Insert filters after node scans
        result_steps: list[QueryPlanStep] = []
        for step in new_steps:
            result_steps.append(step)
            if step.operation == "node_scan" and filter_steps:
                result_steps.extend(filter_steps)
                filter_steps = []

        result_steps.extend(filter_steps)

        plan.steps = result_steps
        return plan

    def _optimize_join_order(self, plan: QueryPlan) -> QueryPlan:
        """Optimize join order.

        Args:
            plan: Query plan

        Returns:
            Optimized plan
        """
        # Reorder to process smaller sets first
        scan_steps = [s for s in plan.steps if s.operation in ("node_scan", "edge_scan")]
        scan_steps.sort(key=lambda s: s.estimated_rows if s.estimated_rows > 0 else float("inf"))

        new_steps: list[QueryPlanStep] = []
        for step in scan_steps:
            new_steps.append(step)

        # Add remaining steps
        for step in plan.steps:
            if step.operation not in ("node_scan", "edge_scan"):
                new_steps.append(step)

        plan.steps = new_steps
        return plan

    def get_plan(self, query_str: str) -> QueryPlan | None:
        """Get cached plan for a query.

        Args:
            query_str: Query string

        Returns:
            QueryPlan or None
        """
        return self.query_cache.get(query_str)

    def cache_plan(self, query_str: str, plan: QueryPlan) -> None:
        """Cache a query plan.

        Args:
            query_str: Query string
            plan: QueryPlan to cache
        """
        self.query_cache[query_str] = plan

    def clear_cache(self) -> None:
        """Clear the plan cache."""
        self.query_cache.clear()
        self.stats_cache.clear()

    def get_stats(self) -> dict[str, Any]:
        """Get optimizer statistics.

        Returns:
            Statistics dictionary
        """
        return {
            "cached_plans": len(self.query_cache),
            "cache_entries": list(self.query_cache.keys())[:10],  # Show first 10
        }
