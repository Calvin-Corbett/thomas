"""Data warehouse with star schema, dimensions, facts, and ETL.

Implements a data warehouse system with dimensional modeling.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class DimensionRecord:
    """A record in a dimension table."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    is_active: bool = True


@dataclass
class FactRecord:
    """A record in a fact table."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    dimension_keys: dict[str, str] = field(default_factory=dict)  # dimension_name -> key
    measures: dict[str, float] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


class Dimension:
    """A dimension table in the data warehouse."""

    def __init__(self, name: str, key_column: str):
        self.id = str(uuid.uuid4())
        self.name = name
        self.key_column = key_column
        self.records: dict[str, DimensionRecord] = {}
        self.attributes: list[str] = [key_column]

    def add_attribute(self, attribute: str) -> None:
        """Add an attribute to the dimension."""
        if attribute not in self.attributes:
            self.attributes.append(attribute)

    def insert_record(self, key: str, attributes: dict[str, Any]) -> str:
        """Insert a record into the dimension."""
        record = DimensionRecord(attributes=attributes)
        self.records[key] = record
        return record.id

    def get_record(self, key: str) -> DimensionRecord | None:
        """Get a dimension record by key."""
        return self.records.get(key)

    def get_all_records(self) -> list[DimensionRecord]:
        """Get all records."""
        return list(self.records.values())

    def get_record_count(self) -> int:
        """Get record count."""
        return len([r for r in self.records.values() if r.is_active])

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "dimension_id": self.id,
            "name": self.name,
            "key_column": self.key_column,
            "record_count": self.get_record_count(),
            "attributes": self.attributes,
        }


class FactTable:
    """A fact table in the data warehouse."""

    def __init__(self, name: str):
        self.id = str(uuid.uuid4())
        self.name = name
        self.records: list[FactRecord] = []
        self.measures: list[str] = []
        self.dimensions: dict[str, Dimension] = {}

    def add_measure(self, measure: str) -> None:
        """Add a measure to the fact table."""
        if measure not in self.measures:
            self.measures.append(measure)

    def insert_record(self, dimension_keys: dict[str, str], measures: dict[str, float]) -> None:
        """Insert a fact record."""
        record = FactRecord(dimension_keys=dimension_keys, measures=measures)
        self.records.append(record)

    def get_record_count(self) -> int:
        """Get record count."""
        return len(self.records)

    def get_total_records(self) -> list[FactRecord]:
        """Get all records."""
        return self.records

    def get_measure_sum(self, measure: str) -> float:
        """Get sum of a measure."""
        return sum(r.measures.get(measure, 0) for r in self.records)

    def get_measure_avg(self, measure: str) -> float:
        """Get average of a measure."""
        if not self.records:
            return 0.0
        return self.get_measure_sum(measure) / len(self.records)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "fact_table_id": self.id,
            "name": self.name,
            "record_count": self.get_record_count(),
            "measures": self.measures,
            "dimensions": list(self.dimensions.keys()),
        }


class StarSchema:
    """A star schema in the data warehouse."""

    def __init__(self, name: str):
        self.id = str(uuid.uuid4())
        self.name = name
        self.fact_tables: dict[str, FactTable] = {}
        self.dimensions: dict[str, Dimension] = {}

    def add_dimension(self, dimension: Dimension) -> None:
        """Add a dimension to the schema."""
        self.dimensions[dimension.name] = dimension

    def add_fact_table(self, fact_table: FactTable) -> None:
        """Add a fact table to the schema."""
        self.fact_tables[fact_table.name] = fact_table

    def get_fact_table(self, name: str) -> FactTable | None:
        """Get a fact table by name."""
        return self.fact_tables.get(name)

    def get_dimension(self, name: str) -> Dimension | None:
        """Get a dimension by name."""
        return self.dimensions.get(name)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "schema_id": self.id,
            "name": self.name,
            "dimensions": [d.to_dict() for d in self.dimensions.values()],
            "fact_tables": [f.to_dict() for f in self.fact_tables.values()],
        }


class ETLJob:
    """An ETL job for loading data."""

    def __init__(self, name: str):
        self.id = str(uuid.uuid4())
        self.name = name
        self.status = "pending"  # pending, running, completed, failed
        self.source: str | None = None
        self.target: str | None = None
        self.created_at = datetime.now()
        self.started_at: datetime | None = None
        self.completed_at: datetime | None = None
        self.records_processed = 0
        self.records_failed = 0

    def start(self) -> None:
        """Start the ETL job."""
        self.status = "running"
        self.started_at = datetime.now()

    def complete(self, records_processed: int) -> None:
        """Complete the ETL job."""
        self.status = "completed"
        self.completed_at = datetime.now()
        self.records_processed = records_processed

    def fail(self, error: str) -> None:
        """Mark the ETL job as failed."""
        self.status = "failed"
        self.completed_at = datetime.now()

    def get_duration_seconds(self) -> float | None:
        """Get job duration in seconds."""
        if not self.started_at:
            return None
        end = self.completed_at or datetime.now()
        return (end - self.started_at).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "job_id": self.id,
            "name": self.name,
            "status": self.status,
            "records_processed": self.records_processed,
            "records_failed": self.records_failed,
            "duration_seconds": self.get_duration_seconds(),
        }


class DataWarehouse:
    """Main data warehouse class."""

    def __init__(self, name: str = "warehouse"):
        self.id = str(uuid.uuid4())
        self.name = name
        self.schemas: dict[str, StarSchema] = {}
        self.etl_jobs: list[ETLJob] = []
        self.created_at = datetime.now()

    def create_schema(self, name: str) -> StarSchema:
        """Create a new star schema."""
        schema = StarSchema(name)
        self.schemas[name] = schema
        return schema

    def get_schema(self, name: str) -> StarSchema | None:
        """Get a schema by name."""
        return self.schemas.get(name)

    def create_etl_job(self, name: str) -> ETLJob:
        """Create a new ETL job."""
        job = ETLJob(name)
        self.etl_jobs.append(job)
        return job

    def get_etl_job(self, job_id: str) -> ETLJob | None:
        """Get an ETL job by ID."""
        for job in self.etl_jobs:
            if job.id == job_id:
                return job
        return None

    def get_warehouse_stats(self) -> dict[str, Any]:
        """Get warehouse statistics."""
        total_records = 0
        for schema in self.schemas.values():
            for fact_table in schema.fact_tables.values():
                total_records += fact_table.get_record_count()

        completed_jobs = sum(1 for j in self.etl_jobs if j.status == "completed")
        failed_jobs = sum(1 for j in self.etl_jobs if j.status == "failed")

        return {
            "warehouse_id": self.id,
            "name": self.name,
            "schemas": len(self.schemas),
            "total_records": total_records,
            "etl_jobs": len(self.etl_jobs),
            "completed_jobs": completed_jobs,
            "failed_jobs": failed_jobs,
        }

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "warehouse_id": self.id,
            "name": self.name,
            "schemas": [s.to_dict() for s in self.schemas.values()],
            "etl_jobs": [j.to_dict() for j in self.etl_jobs],
        }
