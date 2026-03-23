"""Data catalog with schema discovery, lineage, and tags.

Implements a metadata management system for data assets.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Column:
    """A column in a dataset."""

    name: str
    data_type: str = "string"
    nullable: bool = True
    description: str = ""
    statistics: dict[str, Any] = field(default_factory=dict)


@dataclass
class Dataset:
    """A dataset in the catalog."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    columns: list[Column] = field(default_factory=list)
    owner: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    tags: set[str] = field(default_factory=set)
    lineage_upstream: list[str] = field(default_factory=list)
    lineage_downstream: list[str] = field(default_factory=list)
    quality_score: float = 0.0
    record_count: int = 0

    def add_column(self, column: Column) -> None:
        """Add a column to the dataset."""
        self.columns.append(column)
        self.updated_at = datetime.now()

    def add_tag(self, tag: str) -> None:
        """Add a tag to the dataset."""
        self.tags.add(tag)

    def remove_tag(self, tag: str) -> None:
        """Remove a tag from the dataset."""
        self.tags.discard(tag)

    def get_column(self, name: str) -> Column | None:
        """Get a column by name."""
        for col in self.columns:
            if col.name == name:
                return col
        return None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "columns": [{"name": c.name, "type": c.data_type} for c in self.columns],
            "owner": self.owner,
            "tags": list(self.tags),
            "quality_score": self.quality_score,
            "record_count": self.record_count,
        }


class DataLineage:
    """Tracks data lineage and dependencies."""

    def __init__(self):
        self.lineage_graph: dict[str, set[str]] = {}  # dataset_id -> set of upstream datasets

    def add_dependency(self, downstream_id: str, upstream_id: str) -> None:
        """Add a lineage dependency."""
        if downstream_id not in self.lineage_graph:
            self.lineage_graph[downstream_id] = set()
        self.lineage_graph[downstream_id].add(upstream_id)

    def get_upstream(self, dataset_id: str) -> set[str]:
        """Get all upstream datasets."""
        return self.lineage_graph.get(dataset_id, set())

    def get_downstream(self, dataset_id: str) -> set[str]:
        """Get all downstream datasets."""
        downstream = set()
        for did, upstreams in self.lineage_graph.items():
            if dataset_id in upstreams:
                downstream.add(did)
        return downstream

    def get_impact(self, dataset_id: str) -> set[str]:
        """Get all datasets impacted by a change to this dataset."""
        impacted = set()
        to_process = [dataset_id]

        while to_process:
            current = to_process.pop()
            downstream = self.get_downstream(current)
            for ds_id in downstream:
                if ds_id not in impacted:
                    impacted.add(ds_id)
                    to_process.append(ds_id)

        return impacted


class DataCatalog:
    """Main data catalog."""

    def __init__(self, name: str = "catalog"):
        self.id = str(uuid.uuid4())
        self.name = name
        self.datasets: dict[str, Dataset] = {}
        self.lineage = DataLineage()
        self.tags: set[str] = set()
        self.searches: list[dict[str, Any]] = []

    def register_dataset(self, dataset: Dataset) -> None:
        """Register a dataset in the catalog."""
        self.datasets[dataset.id] = dataset
        self.tags.update(dataset.tags)

    def get_dataset(self, dataset_id: str) -> Dataset | None:
        """Get a dataset by ID."""
        return self.datasets.get(dataset_id)

    def find_by_name(self, name: str) -> list[Dataset]:
        """Find datasets by name."""
        results = []
        for dataset in self.datasets.values():
            if name.lower() in dataset.name.lower():
                results.append(dataset)
        return results

    def find_by_tag(self, tag: str) -> list[Dataset]:
        """Find datasets by tag."""
        return [d for d in self.datasets.values() if tag in d.tags]

    def find_by_owner(self, owner: str) -> list[Dataset]:
        """Find datasets by owner."""
        return [d for d in self.datasets.values() if d.owner == owner]

    def search(self, query: str) -> list[Dataset]:
        """Search for datasets."""
        results = []
        query_lower = query.lower()

        for dataset in self.datasets.values():
            if (
                query_lower in dataset.name.lower()
                or query_lower in dataset.description.lower()
                or any(col.name == query for col in dataset.columns)
            ):
                results.append(dataset)

        self.searches.append({"timestamp": datetime.now().isoformat(), "query": query, "results": len(results)})

        return results

    def get_dataset_lineage(self, dataset_id: str) -> dict[str, Any]:
        """Get lineage for a dataset."""
        if dataset_id not in self.datasets:
            return {}

        dataset = self.datasets[dataset_id]
        return {
            "dataset_id": dataset_id,
            "dataset_name": dataset.name,
            "upstream": list(self.lineage.get_upstream(dataset_id)),
            "downstream": list(self.lineage.get_downstream(dataset_id)),
            "impact": list(self.lineage.get_impact(dataset_id)),
        }

    def get_catalog_stats(self) -> dict[str, Any]:
        """Get catalog statistics."""
        total_columns = sum(len(d.columns) for d in self.datasets.values())
        avg_quality = sum(d.quality_score for d in self.datasets.values()) / len(self.datasets) if self.datasets else 0

        return {
            "catalog_id": self.id,
            "catalog_name": self.name,
            "datasets": len(self.datasets),
            "total_columns": total_columns,
            "unique_tags": len(self.tags),
            "average_quality_score": avg_quality,
            "total_searches": len(self.searches),
        }
