"""
Data lineage tracking for the pipeline.

Implements column-level lineage, transformation lineage graph, impact analysis,
data catalog integration, and audit trails.
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ColumnLineage:
    """Tracks lineage of a single column."""

    output_column: str
    output_table: str
    input_columns: list[tuple[str, str]] = field(default_factory=list)  # (column, table)
    transformation: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TransformationStep:
    """Represents a transformation in lineage."""

    step_id: str
    step_name: str
    step_type: str  # "source", "transform", "sink"
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class DatasetMetadata:
    """Metadata about a dataset in the catalog."""

    dataset_id: str
    dataset_name: str
    dataset_type: str  # "source", "intermediate", "sink"
    schema: dict[str, str] = field(default_factory=dict)  # column -> type
    owner: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    description: str = ""
    tags: dict[str, str] = field(default_factory=dict)


@dataclass
class AuditLog:
    """Entry in the audit log."""

    log_id: str
    pipeline_name: str
    stage_name: str
    action: str  # "execute", "fail", "retry"
    executed_by: str | None = None
    status: str = "success"  # "success", "failure"
    record_count: int = 0
    duration_seconds: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    details: dict[str, Any] = field(default_factory=dict)


class LineageGraph:
    """
    Represents transformation lineage as a directed graph.

    Tracks how data flows through pipeline stages.
    """

    def __init__(self) -> None:
        """Initialize lineage graph."""
        self._nodes: dict[str, TransformationStep] = {}
        self._edges: dict[str, list[str]] = defaultdict(list)
        self._column_lineage: dict[str, ColumnLineage] = {}

    def add_step(self, step: TransformationStep) -> None:
        """Add a transformation step."""
        self._nodes[step.step_id] = step

    def add_edge(self, from_step: str, to_step: str) -> None:
        """Add edge between steps."""
        if from_step not in self._edges:
            self._edges[from_step] = []
        self._edges[from_step].append(to_step)

    def add_column_lineage(self, lineage: ColumnLineage) -> None:
        """Add column-level lineage."""
        key = f"{lineage.output_table}.{lineage.output_column}"
        self._column_lineage[key] = lineage

    def get_upstream(self, step_id: str) -> set[str]:
        """Get all upstream steps."""
        visited = set()
        to_visit = deque([step_id])

        while to_visit:
            current = to_visit.popleft()
            if current in visited:
                continue

            visited.add(current)

            # Find predecessors
            for node_id, successors in self._edges.items():
                if current in successors:
                    to_visit.append(node_id)

        visited.discard(step_id)
        return visited

    def get_downstream(self, step_id: str) -> set[str]:
        """Get all downstream steps."""
        visited = set()
        to_visit = deque([step_id])

        while to_visit:
            current = to_visit.popleft()
            if current in visited:
                continue

            visited.add(current)

            for successor in self._edges.get(current, []):
                to_visit.append(successor)

        visited.discard(step_id)
        return visited

    def get_column_sources(self, table: str, column: str) -> list[tuple[str, str]]:
        """Get all source columns for an output column."""
        key = f"{table}.{column}"
        if key in self._column_lineage:
            return self._column_lineage[key].input_columns
        return []

    def get_column_targets(self, table: str, column: str) -> list[tuple[str, str]]:
        """Get all target columns that use an input column."""
        targets = []

        for lineage in self._column_lineage.values():
            if (column, table) in lineage.input_columns:
                targets.append((lineage.output_column, lineage.output_table))

        return targets

    def to_dot_graph(self) -> str:
        """Generate DOT graph representation for visualization."""
        lines = ["digraph DataLineage {"]

        # Add nodes
        for step_id, step in self._nodes.items():
            label = f"{step.step_name}\\n({step.step_type})"
            lines.append(f'  "{step_id}" [label="{label}"];')

        # Add edges
        for from_step, to_steps in self._edges.items():
            for to_step in to_steps:
                lines.append(f'  "{from_step}" -> "{to_step}";')

        lines.append("}")
        return "\n".join(lines)


class ImpactAnalyzer:
    """Analyzes impact of changes on downstream systems."""

    def __init__(self, lineage_graph: LineageGraph) -> None:
        """
        Initialize impact analyzer.

        Args:
            lineage_graph: Lineage graph to analyze
        """
        self.lineage_graph = lineage_graph

    def get_affected_stages(self, changed_stage: str) -> set[str]:
        """
        Get stages affected by change in source stage.

        Args:
            changed_stage: Stage that changed

        Returns:
            Set of affected downstream stages
        """
        return self.lineage_graph.get_downstream(changed_stage)

    def get_affected_columns(self, table: str, column: str) -> list[tuple[str, str]]:
        """
        Get columns affected by change in input column.

        Args:
            table: Table name
            column: Column name

        Returns:
            List of affected output columns
        """
        return self.lineage_graph.get_column_targets(table, column)

    def get_dependency_chains(self, stage_id: str) -> list[list[str]]:
        """
        Get all dependency chains from a stage.

        Args:
            stage_id: Starting stage

        Returns:
            List of dependency chains
        """
        chains = []

        def dfs(current: str, path: list[str]) -> None:
            path.append(current)
            successors = [s for ss in self.lineage_graph._edges.get(current, []) for s in [ss]]

            if not successors:
                chains.append(path.copy())
            else:
                for successor in successors:
                    dfs(successor, path)

            path.pop()

        dfs(stage_id, [])
        return chains

    def estimate_impact_scope(self, stage_id: str) -> dict[str, int]:
        """
        Estimate the scope of impact.

        Args:
            stage_id: Changed stage

        Returns:
            Dictionary with impact metrics
        """
        affected = self.get_affected_stages(stage_id)
        chains = self.get_dependency_chains(stage_id)

        return {
            "directly_affected": len([s for s in affected if s in self.lineage_graph._edges.get(stage_id, [])]),
            "total_affected": len(affected),
            "dependency_chains": len(chains),
            "max_chain_length": max(len(c) for c in chains) if chains else 0,
        }


class DataCatalog:
    """
    Manages dataset metadata and registration.

    Provides a central registry of datasets in the pipeline.
    """

    def __init__(self) -> None:
        """Initialize data catalog."""
        self._datasets: dict[str, DatasetMetadata] = {}
        self._dataset_lineage: dict[str, set[str]] = defaultdict(set)

    def register_dataset(self, metadata: DatasetMetadata) -> None:
        """Register a dataset in the catalog."""
        self._datasets[metadata.dataset_id] = metadata

    def get_dataset(self, dataset_id: str) -> DatasetMetadata | None:
        """Get dataset metadata."""
        return self._datasets.get(dataset_id)

    def list_datasets(self, dataset_type: str | None = None) -> list[DatasetMetadata]:
        """List all registered datasets, optionally filtered by type."""
        datasets = list(self._datasets.values())
        if dataset_type:
            datasets = [d for d in datasets if d.dataset_type == dataset_type]
        return datasets

    def update_dataset(self, dataset_id: str, metadata: DatasetMetadata) -> None:
        """Update dataset metadata."""
        if dataset_id in self._datasets:
            metadata.updated_at = datetime.utcnow()
            self._datasets[dataset_id] = metadata

    def add_lineage_link(self, source_dataset: str, target_dataset: str) -> None:
        """Add lineage link between datasets."""
        self._dataset_lineage[source_dataset].add(target_dataset)

    def get_upstream_datasets(self, dataset_id: str) -> set[str]:
        """Get all upstream datasets."""
        # Simplified: return direct dependencies
        upstream = set()
        for source, targets in self._dataset_lineage.items():
            if dataset_id in targets:
                upstream.add(source)
        return upstream

    def get_downstream_datasets(self, dataset_id: str) -> set[str]:
        """Get all downstream datasets."""
        return self._dataset_lineage.get(dataset_id, set())

    def get_dataset_relationships(self) -> dict[str, dict[str, Any]]:
        """Get all dataset relationships."""
        relationships = {}
        for dataset_id in self._datasets:
            relationships[dataset_id] = {
                "upstream": list(self.get_upstream_datasets(dataset_id)),
                "downstream": list(self.get_downstream_datasets(dataset_id)),
            }
        return relationships


class LineageTracker:
    """
    Central lineage tracking system.

    Integrates column lineage, transformation lineage, and impact analysis.
    """

    def __init__(self) -> None:
        """Initialize lineage tracker."""
        self.lineage_graph = LineageGraph()
        self.impact_analyzer = ImpactAnalyzer(self.lineage_graph)
        self.catalog = DataCatalog()
        self._audit_logs: list[AuditLog] = []

    def track_transformation(
        self,
        step_id: str,
        step_name: str,
        step_type: str,
        inputs: list[str],
        outputs: list[str],
    ) -> None:
        """
        Track a transformation step.

        Args:
            step_id: Unique step identifier
            step_name: Human-readable step name
            step_type: Type of step (source, transform, sink)
            inputs: Input datasets/columns
            outputs: Output datasets/columns
        """
        step = TransformationStep(
            step_id=step_id,
            step_name=step_name,
            step_type=step_type,
            inputs=inputs,
            outputs=outputs,
        )
        self.lineage_graph.add_step(step)

    def track_column_lineage(
        self,
        output_column: str,
        output_table: str,
        input_columns: list[tuple[str, str]],
        transformation: str = "",
    ) -> None:
        """
        Track column-level lineage.

        Args:
            output_column: Output column name
            output_table: Output table name
            input_columns: List of (column, table) tuples for inputs
            transformation: Description of transformation
        """
        lineage = ColumnLineage(
            output_column=output_column,
            output_table=output_table,
            input_columns=input_columns,
            transformation=transformation,
        )
        self.lineage_graph.add_column_lineage(lineage)

    def log_execution(
        self,
        pipeline_name: str,
        stage_name: str,
        action: str,
        record_count: int = 0,
        duration_seconds: float = 0.0,
        status: str = "success",
        executed_by: str | None = None,
    ) -> None:
        """
        Log pipeline execution.

        Args:
            pipeline_name: Name of pipeline
            stage_name: Name of stage
            action: Action performed
            record_count: Number of records processed
            duration_seconds: Execution duration
            status: Execution status
            executed_by: User who executed
        """
        log = AuditLog(
            log_id=f"{pipeline_name}-{stage_name}-{int(datetime.utcnow().timestamp())}",
            pipeline_name=pipeline_name,
            stage_name=stage_name,
            action=action,
            record_count=record_count,
            duration_seconds=duration_seconds,
            status=status,
            executed_by=executed_by,
        )
        self._audit_logs.append(log)

    def get_audit_trail(
        self,
        pipeline_name: str | None = None,
        stage_name: str | None = None,
    ) -> list[AuditLog]:
        """
        Get audit logs.

        Args:
            pipeline_name: Optional filter by pipeline
            stage_name: Optional filter by stage

        Returns:
            List of audit logs
        """
        logs = self._audit_logs
        if pipeline_name:
            logs = [l for l in logs if l.pipeline_name == pipeline_name]
        if stage_name:
            logs = [l for l in logs if l.stage_name == stage_name]
        return logs

    def generate_lineage_report(self) -> dict[str, Any]:
        """Generate comprehensive lineage report."""
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "lineage_graph": self.lineage_graph.to_dot_graph(),
            "datasets": [
                {
                    "id": d.dataset_id,
                    "name": d.dataset_name,
                    "type": d.dataset_type,
                    "owner": d.owner,
                }
                for d in self.catalog.list_datasets()
            ],
            "relationships": self.catalog.get_dataset_relationships(),
            "audit_entries": len(self._audit_logs),
        }
