"""
Tests for data lineage tracking.
"""

import sys

sys.path.insert(0, "/sessions/zen-pensive-cannon/mnt/Thomas")


from thomas.marketplace.data_pipeline.lineage import (
    ColumnLineage,
    DataCatalog,
    DatasetMetadata,
    ImpactAnalyzer,
    LineageGraph,
    LineageTracker,
    TransformationStep,
)


class TestColumnLineage:
    """Test column lineage."""

    def test_column_lineage_creation(self):
        """Test creating column lineage."""
        lineage = ColumnLineage(
            output_column="full_name",
            output_table="users",
            input_columns=[("first_name", "users"), ("last_name", "users")],
            transformation="CONCAT(first_name, ' ', last_name)",
        )

        assert lineage.output_column == "full_name"
        assert len(lineage.input_columns) == 2


class TestLineageGraph:
    """Test lineage graph."""

    def test_add_steps(self):
        """Test adding transformation steps."""
        graph = LineageGraph()

        step1 = TransformationStep(step_id="step1", step_name="Read CSV", step_type="source", outputs=["raw_data"])
        step2 = TransformationStep(
            step_id="step2",
            step_name="Transform",
            step_type="transform",
            inputs=["raw_data"],
            outputs=["transformed_data"],
        )

        graph.add_step(step1)
        graph.add_step(step2)
        graph.add_edge("step1", "step2")

        assert len(graph._nodes) == 2
        assert "step2" in graph._edges["step1"]

    def test_upstream_tracking(self):
        """Test upstream traversal."""
        graph = LineageGraph()

        # Create chain: step1 -> step2 -> step3
        graph.add_step(TransformationStep("step1", "s1", "source"))
        graph.add_step(TransformationStep("step2", "s2", "transform"))
        graph.add_step(TransformationStep("step3", "s3", "sink"))

        graph.add_edge("step1", "step2")
        graph.add_edge("step2", "step3")

        upstream = graph.get_upstream("step3")

        assert "step2" in upstream
        assert "step1" in upstream

    def test_downstream_tracking(self):
        """Test downstream traversal."""
        graph = LineageGraph()

        graph.add_step(TransformationStep("step1", "s1", "source"))
        graph.add_step(TransformationStep("step2", "s2", "transform"))
        graph.add_step(TransformationStep("step3", "s3", "sink"))

        graph.add_edge("step1", "step2")
        graph.add_edge("step2", "step3")

        downstream = graph.get_downstream("step1")

        assert "step2" in downstream
        assert "step3" in downstream

    def test_column_level_lineage(self):
        """Test column-level lineage."""
        graph = LineageGraph()

        lineage = ColumnLineage(
            output_column="total", output_table="summary", input_columns=[("amount", "orders"), ("tax", "orders")]
        )
        graph.add_column_lineage(lineage)

        sources = graph.get_column_sources("summary", "total")

        assert ("amount", "orders") in sources
        assert ("tax", "orders") in sources

    def test_dot_graph_generation(self):
        """Test DOT graph generation."""
        graph = LineageGraph()

        graph.add_step(TransformationStep("step1", "Read", "source"))
        graph.add_step(TransformationStep("step2", "Transform", "transform"))
        graph.add_edge("step1", "step2")

        dot = graph.to_dot_graph()

        assert "digraph" in dot
        assert "step1" in dot
        assert "step2" in dot


class TestImpactAnalyzer:
    """Test impact analysis."""

    def test_affected_stages(self):
        """Test identifying affected stages."""
        graph = LineageGraph()

        graph.add_step(TransformationStep("source", "s", "source"))
        graph.add_step(TransformationStep("transform1", "t1", "transform"))
        graph.add_step(TransformationStep("transform2", "t2", "transform"))
        graph.add_step(TransformationStep("sink", "s", "sink"))

        graph.add_edge("source", "transform1")
        graph.add_edge("transform1", "transform2")
        graph.add_edge("transform2", "sink")

        analyzer = ImpactAnalyzer(graph)
        affected = analyzer.get_affected_stages("source")

        assert "transform1" in affected
        assert "transform2" in affected
        assert "sink" in affected

    def test_column_impact(self):
        """Test column impact analysis."""
        graph = LineageGraph()

        l1 = ColumnLineage("first_name", "users", [("fname", "raw")])
        l2 = ColumnLineage("full_name", "users", [("first_name", "users")])

        graph.add_column_lineage(l1)
        graph.add_column_lineage(l2)

        analyzer = ImpactAnalyzer(graph)
        affected = analyzer.get_affected_columns("raw", "fname")

        assert ("full_name", "users") in affected

    def test_impact_scope_estimation(self):
        """Test impact scope estimation."""
        graph = LineageGraph()

        for i in range(5):
            graph.add_step(TransformationStep(f"step{i}", f"Step {i}", "transform"))
            if i > 0:
                graph.add_edge(f"step{i-1}", f"step{i}")

        analyzer = ImpactAnalyzer(graph)
        scope = analyzer.estimate_impact_scope("step0")

        assert "directly_affected" in scope
        assert "total_affected" in scope
        assert scope["total_affected"] > 0


class TestDataCatalog:
    """Test data catalog."""

    def test_dataset_registration(self):
        """Test registering datasets."""
        catalog = DataCatalog()

        metadata = DatasetMetadata(
            dataset_id="users", dataset_name="Users Table", dataset_type="source", owner="data_team"
        )

        catalog.register_dataset(metadata)
        retrieved = catalog.get_dataset("users")

        assert retrieved is not None
        assert retrieved.dataset_name == "Users Table"

    def test_dataset_listing(self):
        """Test listing datasets."""
        catalog = DataCatalog()

        source = DatasetMetadata("source1", "Source", "source")
        sink = DatasetMetadata("sink1", "Sink", "sink")

        catalog.register_dataset(source)
        catalog.register_dataset(sink)

        all_datasets = catalog.list_datasets()
        assert len(all_datasets) == 2

        sources = catalog.list_datasets("source")
        assert len(sources) == 1

    def test_dataset_lineage(self):
        """Test dataset lineage links."""
        catalog = DataCatalog()

        source = DatasetMetadata("source", "Source", "source")
        target = DatasetMetadata("target", "Target", "sink")

        catalog.register_dataset(source)
        catalog.register_dataset(target)
        catalog.add_lineage_link("source", "target")

        downstream = catalog.get_downstream_datasets("source")
        assert "target" in downstream

        upstream = catalog.get_upstream_datasets("target")
        assert "source" in upstream

    def test_dataset_relationships(self):
        """Test getting all relationships."""
        catalog = DataCatalog()

        catalog.register_dataset(DatasetMetadata("ds1", "D1", "source"))
        catalog.register_dataset(DatasetMetadata("ds2", "D2", "intermediate"))
        catalog.register_dataset(DatasetMetadata("ds3", "D3", "sink"))

        catalog.add_lineage_link("ds1", "ds2")
        catalog.add_lineage_link("ds2", "ds3")

        relationships = catalog.get_dataset_relationships()

        assert relationships["ds1"]["downstream"] == ["ds2"]
        assert relationships["ds3"]["upstream"] == ["ds2"]


class TestLineageTracker:
    """Test central lineage tracker."""

    def test_track_transformation(self):
        """Test tracking transformations."""
        tracker = LineageTracker()

        tracker.track_transformation("step1", "Read CSV", "source", [], ["raw_data"])

        tracker.track_transformation("step2", "Transform", "transform", ["raw_data"], ["processed_data"])

        assert len(tracker.lineage_graph._nodes) == 2

    def test_track_column_lineage(self):
        """Test tracking column lineage."""
        tracker = LineageTracker()

        tracker.track_column_lineage("user_age", "users", [("age", "raw_users")], "Cast to integer")

        sources = tracker.lineage_graph.get_column_sources("users", "user_age")
        assert ("age", "raw_users") in sources

    def test_execution_logging(self):
        """Test execution logging."""
        tracker = LineageTracker()

        tracker.log_execution(
            "my_pipeline",
            "stage1",
            "execute",
            record_count=100,
            duration_seconds=5.5,
            status="success",
            executed_by="alice",
        )

        logs = tracker.get_audit_trail("my_pipeline")
        assert len(logs) == 1
        assert logs[0].status == "success"

    def test_lineage_report(self):
        """Test report generation."""
        tracker = LineageTracker()

        tracker.track_transformation("s1", "Read", "source", [], ["data"])
        tracker.log_execution("pipeline", "stage", "execute", 50, 2.0)

        report = tracker.generate_lineage_report()

        assert "timestamp" in report
        assert "lineage_graph" in report
        assert "datasets" in report
        assert "audit_entries" in report


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
