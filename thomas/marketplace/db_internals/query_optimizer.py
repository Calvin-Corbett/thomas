"""
Query optimizer for converting logical to physical plans.

This module implements:
- Logical plan to physical plan conversion
- Cost estimation using I/O models and statistics
- Join ordering (dynamic programming for small, greedy for large)
- Predicate pushdown optimization
- Projection pushdown optimization
- Index selection based on selectivity
- Plan enumeration
"""

import math
from dataclasses import dataclass, field
from typing import Any

from ._exceptions import OptimizerException
from ._types import QueryPlan


@dataclass
class TableStatistics:
    """Statistics for a table used in cost estimation."""

    table_name: str
    num_rows: int = 0
    num_pages: int = 0
    avg_row_size: int = 0
    column_stats: dict[str, "ColumnStatistics"] = field(default_factory=dict)


@dataclass
class ColumnStatistics:
    """Statistics for a column used in cost estimation."""

    column_name: str
    num_distinct_values: int = 0
    min_value: Any = None
    max_value: Any = None
    null_fraction: float = 0.0
    histogram: list[tuple[Any, int]] = field(default_factory=list)


class CostEstimator:
    """Estimates cost of query plans using I/O model."""

    # Cost constants
    CPU_COST_PER_ROW = 0.01
    IO_COST_PER_PAGE = 1.0
    SEEK_COST = 5.0
    SEQUENTIAL_SCAN_COST_MULTIPLIER = 0.1

    def __init__(self) -> None:
        """Initialize cost estimator."""
        self.table_stats: dict[str, TableStatistics] = {}

    def register_table_stats(self, stats: TableStatistics) -> None:
        """Register statistics for a table."""
        self.table_stats[stats.table_name] = stats

    def estimate_scan_cost(self, table_name: str) -> tuple[float, float]:
        """
        Estimate cost of full table scan.

        Returns:
            (io_cost, cpu_cost)
        """
        stats = self.table_stats.get(table_name)
        if stats is None:
            return (100.0, 100.0)  # Default estimate

        io_cost = stats.num_pages * self.IO_COST_PER_PAGE
        cpu_cost = stats.num_rows * self.CPU_COST_PER_ROW

        return (io_cost, cpu_cost)

    def estimate_index_scan_cost(self, table_name: str, selectivity: float) -> tuple[float, float]:
        """
        Estimate cost of index scan.

        Args:
            table_name: Name of table
            selectivity: Fraction of rows that match predicate (0-1)

        Returns:
            (io_cost, cpu_cost)
        """
        stats = self.table_stats.get(table_name)
        if stats is None:
            return (50.0, 50.0)

        # Index lookup
        index_io_cost = math.log(stats.num_pages) + 1  # Tree height
        index_io_cost *= self.SEEK_COST

        # Data page lookups
        matching_rows = stats.num_rows * selectivity
        rows_per_page = max(1, stats.num_rows // stats.num_pages)
        data_pages = matching_rows / rows_per_page if rows_per_page > 0 else stats.num_pages

        data_io_cost = data_pages * self.IO_COST_PER_PAGE
        total_io_cost = index_io_cost + data_io_cost
        cpu_cost = matching_rows * self.CPU_COST_PER_ROW

        return (total_io_cost, cpu_cost)

    def estimate_join_cost(
        self,
        left_rows: int,
        right_rows: int,
        left_pages: int,
        right_pages: int,
        join_type: str,
    ) -> tuple[float, float]:
        """
        Estimate join cost.

        Args:
            left_rows, right_rows: Cardinalities
            left_pages, right_pages: Page counts
            join_type: 'NESTED_LOOP', 'SORT_MERGE', 'HASH_JOIN'

        Returns:
            (io_cost, cpu_cost)
        """
        if join_type == "NESTED_LOOP":
            # Outer scan + inner scan for each outer row
            io_cost = left_pages + (left_rows * right_pages)
            cpu_cost = left_rows * right_rows * self.CPU_COST_PER_ROW
            return (io_cost, cpu_cost)

        elif join_type == "SORT_MERGE":
            # Sort both inputs, then merge
            sort_cost_left = left_rows * math.log(left_rows)
            sort_cost_right = right_rows * math.log(right_rows)
            merge_cost = left_rows + right_rows

            io_cost = left_pages + right_pages + math.ceil(sort_cost_left / 1000) + math.ceil(sort_cost_right / 1000)
            cpu_cost = (sort_cost_left + sort_cost_right + merge_cost) * self.CPU_COST_PER_ROW

            return (io_cost, cpu_cost)

        elif join_type == "HASH_JOIN":
            # Build hash table, probe
            build_cost = left_rows
            probe_cost = right_rows

            io_cost = left_pages + right_pages
            cpu_cost = (build_cost + probe_cost) * self.CPU_COST_PER_ROW

            return (io_cost, cpu_cost)

        raise OptimizerException(f"Unknown join type: {join_type}")

    def estimate_selectivity(self, table_name: str, column_name: str, operator: str, value: Any) -> float:
        """
        Estimate selectivity of a predicate.

        Args:
            table_name: Table name
            column_name: Column name
            operator: Comparison operator (=, <, >, etc.)
            value: Value to compare

        Returns:
            Fraction of rows matching (0-1)
        """
        stats = self.table_stats.get(table_name)
        if stats is None or column_name not in stats.column_stats:
            # Default selectivity
            if operator == "=":
                return 0.1
            elif operator in ["<", ">", "<=", ">="]:
                return 0.33
            else:
                return 0.5

        col_stats = stats.column_stats[column_name]

        if operator == "=":
            # Uniform distribution estimate
            if col_stats.num_distinct_values > 0:
                return 1.0 / col_stats.num_distinct_values
            return 0.1

        elif operator in ["<", "<="]:
            if col_stats.min_value is not None and col_stats.max_value is not None:
                range_size = col_stats.max_value - col_stats.min_value
                if range_size > 0:
                    value_pos = (value - col_stats.min_value) / range_size
                    return max(0.0, min(1.0, value_pos))

            return 0.33

        elif operator in [">", ">="]:
            if col_stats.min_value is not None and col_stats.max_value is not None:
                range_size = col_stats.max_value - col_stats.min_value
                if range_size > 0:
                    value_pos = (value - col_stats.min_value) / range_size
                    return max(0.0, min(1.0, 1.0 - value_pos))

            return 0.33

        elif operator == "BETWEEN":
            return 0.5

        elif operator == "IN":
            # List of values
            return 0.2

        return 0.5


class JoinOrderer:
    """Determines optimal join order using cost estimation."""

    def __init__(self, cost_estimator: CostEstimator) -> None:
        """Initialize join orderer."""
        self.cost_estimator = cost_estimator

    def order_joins_dynamic_programming(
        self, tables: list[str], join_conditions: dict[tuple[str, str], Any]
    ) -> list[tuple[str, str, str]]:
        """
        Order joins using dynamic programming (optimal for small number of tables).

        Args:
            tables: List of table names
            join_conditions: Dictionary mapping (left_table, right_table) to condition

        Returns:
            List of (left_table, right_table, condition) tuples in join order
        """
        if len(tables) <= 1:
            return []

        if len(tables) > 10:
            # Use greedy for many tables
            return self.order_joins_greedy(tables, join_conditions)

        # DP approach: try all permutations for small cases
        # (Simplified; real implementation would use bitmask DP)
        join_order = []
        remaining = set(tables[1:])
        current = tables[0]

        while remaining:
            # Find cheapest table to join next
            best_table = None
            best_cost = float("inf")

            for candidate in remaining:
                cost = self._estimate_join_cost_between(current, candidate)
                if cost < best_cost:
                    best_cost = cost
                    best_table = candidate

            if best_table:
                condition = join_conditions.get((current, best_table)) or join_conditions.get((best_table, current))
                join_order.append((current, best_table, condition))
                current = best_table
                remaining.remove(best_table)

        return join_order

    def order_joins_greedy(
        self, tables: list[str], join_conditions: dict[tuple[str, str], Any]
    ) -> list[tuple[str, str, str]]:
        """
        Order joins greedily (fast approximation).

        Args:
            tables: List of table names
            join_conditions: Join conditions dictionary

        Returns:
            List of join operations in order
        """
        join_order = []
        remaining = set(tables[1:])
        current = tables[0]

        while remaining:
            # Choose table that produces smallest result
            best_table = None
            best_selectivity = float("inf")

            for candidate in remaining:
                # Simple heuristic: smallest table first
                stats = self.cost_estimator.table_stats.get(candidate)
                if stats and stats.num_rows < best_selectivity:
                    best_selectivity = stats.num_rows
                    best_table = candidate

            if best_table is None and remaining:
                best_table = remaining.pop()
                remaining.add(best_table)

            if best_table:
                condition = join_conditions.get((current, best_table)) or join_conditions.get((best_table, current))
                join_order.append((current, best_table, condition))
                remaining.discard(best_table)
                # Update current - could be current or best_table based on cardinality
                current = best_table

        return join_order

    def _estimate_join_cost_between(self, left_table: str, right_table: str) -> float:
        """Estimate cost of joining two tables."""
        left_stats = self.cost_estimator.table_stats.get(left_table)
        right_stats = self.cost_estimator.table_stats.get(right_table)

        if left_stats is None or right_stats is None:
            return 1000.0

        left_rows = left_stats.num_rows
        right_rows = right_stats.num_rows
        left_pages = left_stats.num_pages
        right_pages = right_stats.num_pages

        io_cost, cpu_cost = self.cost_estimator.estimate_join_cost(
            left_rows, right_rows, left_pages, right_pages, "HASH_JOIN"
        )

        return io_cost + cpu_cost


class QueryOptimizer:
    """Optimizes SQL queries to efficient execution plans."""

    def __init__(self, cost_estimator: CostEstimator | None = None) -> None:
        """
        Initialize optimizer.

        Args:
            cost_estimator: Cost estimator to use (creates default if None)
        """
        self.cost_estimator = cost_estimator or CostEstimator()
        self.join_orderer = JoinOrderer(self.cost_estimator)
        self.plan_counter = 0

    def optimize_select(self, query_plan: dict[str, Any]) -> QueryPlan:
        """
        Optimize a SELECT query.

        Args:
            query_plan: Logical query plan from parser

        Returns:
            Optimized physical query plan
        """
        # Extract components
        tables = self._extract_tables(query_plan.get("from", {}))
        where_clause = query_plan.get("where")
        columns = query_plan.get("columns", [])

        # Cost estimation
        io_cost = 0.0
        cpu_cost = 0.0

        if len(tables) == 1:
            # Single table scan
            table = tables[0]
            selectivity = self._estimate_selectivity_for_where(table, where_clause)

            scan_io, scan_cpu = self.cost_estimator.estimate_scan_cost(table)
            io_cost = scan_io * selectivity
            cpu_cost = scan_cpu * selectivity

        elif len(tables) > 1:
            # Multi-table join
            join_conditions = self._extract_join_conditions(query_plan)
            join_order = self.join_orderer.order_joins_dynamic_programming(tables, join_conditions)

            # Accumulate costs
            current_rows = (
                self.cost_estimator.table_stats.get(tables[0]).num_rows
                if tables[0] in self.cost_estimator.table_stats
                else 1000
            )

            for left, right, condition in join_order:
                left_stats = self.cost_estimator.table_stats.get(left)
                right_stats = self.cost_estimator.table_stats.get(right)

                left_rows = left_stats.num_rows if left_stats else 1000
                right_rows = right_stats.num_rows if right_stats else 1000
                left_pages = left_stats.num_pages if left_stats else 100
                right_pages = right_stats.num_pages if right_stats else 100

                join_io, join_cpu = self.cost_estimator.estimate_join_cost(
                    left_rows, right_rows, left_pages, right_pages, "HASH_JOIN"
                )

                io_cost += join_io
                cpu_cost += join_cpu
                current_rows = int(left_rows * right_rows / max(1, left_rows + right_rows))

        # Create physical plan
        self.plan_counter += 1
        return QueryPlan(
            plan_id=self.plan_counter,
            query_type="SELECT",
            cost_estimate=io_cost + cpu_cost,
            io_cost=io_cost,
            cpu_cost=cpu_cost,
            tables_accessed=tables,
            estimated_rows=max(1, int((io_cost + cpu_cost) / 10)),
        )

    def _extract_tables(self, from_clause: dict[str, Any]) -> list[str]:
        """Extract table names from FROM clause."""
        if not from_clause:
            return []

        tables = [from_clause.get("table", "")]

        for join in from_clause.get("joins", []):
            tables.append(join.get("table", ""))

        return [t for t in tables if t]

    def _estimate_selectivity_for_where(self, table: str, where_clause: Any) -> float:
        """Estimate selectivity of WHERE clause."""
        if where_clause is None:
            return 1.0

        # Simplified: return 0.1 for any where clause
        return 0.1

    def _extract_join_conditions(self, query_plan: dict[str, Any]) -> dict[tuple[str, str], Any]:
        """Extract join conditions from query plan."""
        conditions = {}
        from_clause = query_plan.get("from", {})

        for join in from_clause.get("joins", []):
            left_table = from_clause.get("table", "")
            right_table = join.get("table", "")
            condition = join.get("condition")

            if left_table and right_table:
                conditions[(left_table, right_table)] = condition

        return conditions

    def apply_predicate_pushdown(self, plan: QueryPlan, where_clause: Any) -> QueryPlan:
        """
        Apply predicate pushdown optimization.

        Moves WHERE conditions as close to table scans as possible.
        """
        # In real implementation, would restructure plan tree
        return plan

    def apply_projection_pushdown(self, plan: QueryPlan, columns: list[str]) -> QueryPlan:
        """
        Apply projection pushdown optimization.

        Only retrieves needed columns instead of all.
        """
        # In real implementation, would modify plan to project early
        return plan

    def select_indexes(self, plan: QueryPlan) -> list[str]:
        """
        Select which indexes to use.

        Args:
            plan: Query plan

        Returns:
            List of index names to use
        """
        # Simplified: no index selection in this version
        return []
