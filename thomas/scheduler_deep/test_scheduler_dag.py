"""
Tests for DAG scheduling and dependency management.
"""

import pytest

from thomas.scheduler_deep._exceptions import CycleDetected, InvalidDAG
from thomas.scheduler_deep._types import IntervalTrigger, Job
from thomas.scheduler_deep.dag import DAGScheduler


class TestDAGScheduler:
    """Test DAG scheduling functionality."""

    def test_add_job_no_dependencies(self) -> None:
        """Test adding job without dependencies."""
        dag = DAGScheduler()

        def dummy() -> None:
            pass

        trigger = IntervalTrigger(3600)
        job = Job(dummy, trigger, name="job1")

        dag.add_job(job)
        assert "job1" in dag._nodes

    def test_add_job_with_dependencies(self) -> None:
        """Test adding job with dependencies."""
        dag = DAGScheduler()

        def dummy() -> None:
            pass

        trigger = IntervalTrigger(3600)
        job1 = Job(dummy, trigger, job_id="job1", name="job1")
        job2 = Job(dummy, trigger, job_id="job2", name="job2")

        dag.add_job(job1)
        dag.add_job(job2, dependencies=["job1"])

        assert "job1" in dag._nodes
        assert "job2" in dag._nodes
        assert "job1" in dag._nodes["job2"].dependencies

    def test_duplicate_job_id_raises_error(self) -> None:
        """Test adding duplicate job ID raises error."""
        dag = DAGScheduler()

        def dummy() -> None:
            pass

        trigger = IntervalTrigger(3600)
        job = Job(dummy, trigger, job_id="same_id")

        dag.add_job(job)
        with pytest.raises(InvalidDAG):
            dag.add_job(job)

    def test_missing_dependency_raises_error(self) -> None:
        """Test adding job with missing dependency raises error."""
        dag = DAGScheduler()

        def dummy() -> None:
            pass

        trigger = IntervalTrigger(3600)
        job = Job(dummy, trigger, job_id="job2")

        with pytest.raises(InvalidDAG):
            dag.add_job(job, dependencies=["missing_job"])

    def test_cycle_detection(self) -> None:
        """Test cycle detection in dependencies."""
        dag = DAGScheduler()

        def dummy() -> None:
            pass

        trigger = IntervalTrigger(3600)
        job1 = Job(dummy, trigger, job_id="job1")
        job2 = Job(dummy, trigger, job_id="job2")
        job3 = Job(dummy, trigger, job_id="job3")

        dag.add_job(job1)
        dag.add_job(job2, dependencies=["job1"])
        dag.add_job(job3, dependencies=["job2"])

        # Try to add circular dependency
        with pytest.raises(CycleDetected):
            dag.add_dependency("job1", "job3")

    def test_remove_job(self) -> None:
        """Test removing job from DAG."""
        dag = DAGScheduler()

        def dummy() -> None:
            pass

        trigger = IntervalTrigger(3600)
        job = Job(dummy, trigger, job_id="job1")

        dag.add_job(job)
        assert "job1" in dag._nodes

        dag.remove_job("job1")
        assert "job1" not in dag._nodes

    def test_remove_job_with_dependents_fails(self) -> None:
        """Test removing job with dependents fails."""
        dag = DAGScheduler()

        def dummy() -> None:
            pass

        trigger = IntervalTrigger(3600)
        job1 = Job(dummy, trigger, job_id="job1")
        job2 = Job(dummy, trigger, job_id="job2")

        dag.add_job(job1)
        dag.add_job(job2, dependencies=["job1"])

        with pytest.raises(InvalidDAG):
            dag.remove_job("job1")

    def test_get_topological_order(self) -> None:
        """Test getting topological execution order."""
        dag = DAGScheduler()

        def dummy() -> None:
            pass

        trigger = IntervalTrigger(3600)
        job1 = Job(dummy, trigger, job_id="job1")
        job2 = Job(dummy, trigger, job_id="job2")
        job3 = Job(dummy, trigger, job_id="job3")

        dag.add_job(job1)
        dag.add_job(job2, dependencies=["job1"])
        dag.add_job(job3, dependencies=["job2"])

        order = dag.get_topological_order()
        assert order == ["job1", "job2", "job3"]

    def test_get_ready_jobs(self) -> None:
        """Test getting jobs ready to run."""
        dag = DAGScheduler()

        def dummy() -> None:
            pass

        trigger = IntervalTrigger(3600)
        job1 = Job(dummy, trigger, job_id="job1")
        job2 = Job(dummy, trigger, job_id="job2")

        dag.add_job(job1)
        dag.add_job(job2, dependencies=["job1"])

        # job1 should be ready
        ready = dag.get_ready_jobs()
        assert any(j.id == "job1" for j in ready)

    def test_mark_job_complete(self) -> None:
        """Test marking job as complete."""
        dag = DAGScheduler()

        def dummy() -> None:
            pass

        trigger = IntervalTrigger(3600)
        job1 = Job(dummy, trigger, job_id="job1")
        job2 = Job(dummy, trigger, job_id="job2")

        dag.add_job(job1)
        dag.add_job(job2, dependencies=["job1"])

        dag.mark_job_complete("job1", result="output")
        assert dag.get_result("job1") == "output"

    def test_get_critical_path(self) -> None:
        """Test critical path calculation."""
        dag = DAGScheduler()

        def dummy() -> None:
            pass

        trigger = IntervalTrigger(3600)
        job1 = Job(dummy, trigger, job_id="job1")
        job2 = Job(dummy, trigger, job_id="job2")
        job3 = Job(dummy, trigger, job_id="job3")

        dag.add_job(job1)
        dag.add_job(job2, dependencies=["job1"])
        dag.add_job(job3, dependencies=["job2"])

        path = dag.get_critical_path()
        assert len(path) > 0

    def test_get_job_dependencies(self) -> None:
        """Test getting job dependencies."""
        dag = DAGScheduler()

        def dummy() -> None:
            pass

        trigger = IntervalTrigger(3600)
        job1 = Job(dummy, trigger, job_id="job1")
        job2 = Job(dummy, trigger, job_id="job2")
        job3 = Job(dummy, trigger, job_id="job3")

        dag.add_job(job1)
        dag.add_job(job2, dependencies=["job1"])
        dag.add_job(job3, dependencies=["job1", "job2"])

        deps = dag.get_job_dependencies("job3")
        assert "job1" in deps
        assert "job2" in deps

    def test_get_job_dependents(self) -> None:
        """Test getting jobs that depend on a job."""
        dag = DAGScheduler()

        def dummy() -> None:
            pass

        trigger = IntervalTrigger(3600)
        job1 = Job(dummy, trigger, job_id="job1")
        job2 = Job(dummy, trigger, job_id="job2")
        job3 = Job(dummy, trigger, job_id="job3")

        dag.add_job(job1)
        dag.add_job(job2, dependencies=["job1"])
        dag.add_job(job3, dependencies=["job1"])

        dependents = dag.get_job_dependents("job1")
        assert "job2" in dependents
        assert "job3" in dependents

    def test_execution_stats(self) -> None:
        """Test getting execution statistics."""
        dag = DAGScheduler()

        def dummy() -> None:
            pass

        trigger = IntervalTrigger(3600)
        job1 = Job(dummy, trigger, job_id="job1")
        job2 = Job(dummy, trigger, job_id="job2")

        dag.add_job(job1)
        dag.add_job(job2, dependencies=["job1"])

        stats = dag.get_execution_stats()
        assert stats["total_jobs"] == 2
        assert stats["completed_jobs"] == 0

    def test_complex_dag(self) -> None:
        """Test complex DAG with multiple branches."""
        dag = DAGScheduler()

        def dummy() -> None:
            pass

        trigger = IntervalTrigger(3600)

        # Create diamond dependency pattern
        job_a = Job(dummy, trigger, job_id="a")
        job_b = Job(dummy, trigger, job_id="b")
        job_c = Job(dummy, trigger, job_id="c")
        job_d = Job(dummy, trigger, job_id="d")

        dag.add_job(job_a)
        dag.add_job(job_b, dependencies=["a"])
        dag.add_job(job_c, dependencies=["a"])
        dag.add_job(job_d, dependencies=["b", "c"])

        order = dag.get_topological_order()
        assert order[0] == "a"
        assert order[-1] == "d"
        assert order.index("b") < order.index("d")
        assert order.index("c") < order.index("d")
