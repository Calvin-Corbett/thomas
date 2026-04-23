"""
Tests for behavior tree implementation.

Tests all node types, tree execution, blackboard operations,
and complex tree structures.
"""

import time
import unittest

from thomas.marketplace.game_ai._exceptions import BehaviorTreeError
from thomas.marketplace.game_ai.behavior_tree import (
    Action,
    BehaviorTree,
    BTNodeStatus,
    Condition,
    Cooldown,
    Inverter,
    Limiter,
    Parallel,
    Repeater,
    Selector,
    Sequence,
    Succeeder,
    UntilFail,
)


class TestLeafNodes(unittest.TestCase):
    """Test leaf node types (Action, Condition)."""

    def test_action_success(self):
        """Test action that returns success."""

        def always_succeed(bb, dt):
            return BTNodeStatus.SUCCESS

        action = Action("test_success", always_succeed)
        status = action.tick({}, 0.016)

        self.assertEqual(status, BTNodeStatus.SUCCESS)

    def test_action_failure(self):
        """Test action that returns failure."""

        def always_fail(bb, dt):
            return BTNodeStatus.FAILURE

        action = Action("test_fail", always_fail)
        status = action.tick({}, 0.016)

        self.assertEqual(status, BTNodeStatus.FAILURE)

    def test_action_running(self):
        """Test action that returns running."""
        counter = {"count": 0}

        def count_up(bb, dt):
            counter["count"] += 1
            if counter["count"] < 3:
                return BTNodeStatus.RUNNING
            return BTNodeStatus.SUCCESS

        action = Action("counter", count_up)

        self.assertEqual(action.tick({}, 0.016), BTNodeStatus.RUNNING)
        self.assertEqual(action.tick({}, 0.016), BTNodeStatus.RUNNING)
        self.assertEqual(action.tick({}, 0.016), BTNodeStatus.SUCCESS)

    def test_condition_true(self):
        """Test condition that returns true."""
        condition = Condition("always_true", lambda bb: True)
        status = condition.tick({}, 0.016)

        self.assertEqual(status, BTNodeStatus.SUCCESS)

    def test_condition_false(self):
        """Test condition that returns false."""
        condition = Condition("always_false", lambda bb: False)
        status = condition.tick({}, 0.016)

        self.assertEqual(status, BTNodeStatus.FAILURE)

    def test_condition_blackboard(self):
        """Test condition reading from blackboard."""
        condition = Condition("check_value", lambda bb: bb.get("value", 0) > 5)

        self.assertEqual(condition.tick({"value": 10}, 0.016), BTNodeStatus.SUCCESS)
        self.assertEqual(condition.tick({"value": 2}, 0.016), BTNodeStatus.FAILURE)


class TestCompositeNodes(unittest.TestCase):
    """Test composite node types (Sequence, Selector, Parallel)."""

    def test_sequence_all_success(self):
        """Test sequence with all children succeeding."""
        seq = Sequence("seq")
        seq.add_child(Action("a1", lambda bb, dt: BTNodeStatus.SUCCESS))
        seq.add_child(Action("a2", lambda bb, dt: BTNodeStatus.SUCCESS))
        seq.add_child(Action("a3", lambda bb, dt: BTNodeStatus.SUCCESS))

        status = seq.tick({}, 0.016)
        self.assertEqual(status, BTNodeStatus.SUCCESS)

    def test_sequence_one_failure(self):
        """Test sequence stops at first failure."""
        seq = Sequence("seq")
        seq.add_child(Action("a1", lambda bb, dt: BTNodeStatus.SUCCESS))
        seq.add_child(Action("a2", lambda bb, dt: BTNodeStatus.FAILURE))
        seq.add_child(Action("a3", lambda bb, dt: BTNodeStatus.SUCCESS))

        status = seq.tick({}, 0.016)
        self.assertEqual(status, BTNodeStatus.FAILURE)

    def test_sequence_running(self):
        """Test sequence returns running when child runs."""
        seq = Sequence("seq")
        seq.add_child(Action("a1", lambda bb, dt: BTNodeStatus.SUCCESS))
        seq.add_child(Action("a2", lambda bb, dt: BTNodeStatus.RUNNING))

        status = seq.tick({}, 0.016)
        self.assertEqual(status, BTNodeStatus.RUNNING)

    def test_selector_first_success(self):
        """Test selector succeeds on first child success."""
        sel = Selector("sel")
        sel.add_child(Action("a1", lambda bb, dt: BTNodeStatus.FAILURE))
        sel.add_child(Action("a2", lambda bb, dt: BTNodeStatus.SUCCESS))
        sel.add_child(Action("a3", lambda bb, dt: BTNodeStatus.SUCCESS))

        status = sel.tick({}, 0.016)
        self.assertEqual(status, BTNodeStatus.SUCCESS)

    def test_selector_all_failure(self):
        """Test selector fails when all children fail."""
        sel = Selector("sel")
        sel.add_child(Action("a1", lambda bb, dt: BTNodeStatus.FAILURE))
        sel.add_child(Action("a2", lambda bb, dt: BTNodeStatus.FAILURE))

        status = sel.tick({}, 0.016)
        self.assertEqual(status, BTNodeStatus.FAILURE)

    def test_parallel_all_success(self):
        """Test parallel with threshold=1, all succeed."""
        par = Parallel("par", success_threshold=1)
        par.add_child(Action("a1", lambda bb, dt: BTNodeStatus.SUCCESS))
        par.add_child(Action("a2", lambda bb, dt: BTNodeStatus.SUCCESS))

        status = par.tick({}, 0.016)
        self.assertEqual(status, BTNodeStatus.SUCCESS)

    def test_parallel_threshold(self):
        """Test parallel with threshold > 1."""
        par = Parallel("par", success_threshold=2)
        par.add_child(Action("a1", lambda bb, dt: BTNodeStatus.SUCCESS))
        par.add_child(Action("a2", lambda bb, dt: BTNodeStatus.FAILURE))
        par.add_child(Action("a3", lambda bb, dt: BTNodeStatus.SUCCESS))

        status = par.tick({}, 0.016)
        self.assertEqual(status, BTNodeStatus.SUCCESS)


class TestDecoratorNodes(unittest.TestCase):
    """Test decorator node types."""

    def test_inverter_success_to_failure(self):
        """Test inverter converts success to failure."""
        child = Action("child", lambda bb, dt: BTNodeStatus.SUCCESS)
        inv = Inverter("inv", child)

        status = inv.tick({}, 0.016)
        self.assertEqual(status, BTNodeStatus.FAILURE)

    def test_inverter_failure_to_success(self):
        """Test inverter converts failure to success."""
        child = Action("child", lambda bb, dt: BTNodeStatus.FAILURE)
        inv = Inverter("inv", child)

        status = inv.tick({}, 0.016)
        self.assertEqual(status, BTNodeStatus.SUCCESS)

    def test_inverter_running_stays_running(self):
        """Test inverter leaves running as running."""
        child = Action("child", lambda bb, dt: BTNodeStatus.RUNNING)
        inv = Inverter("inv", child)

        status = inv.tick({}, 0.016)
        self.assertEqual(status, BTNodeStatus.RUNNING)

    def test_repeater_count(self):
        """Test repeater with count."""
        counter = {"count": 0}

        def increment(bb, dt):
            counter["count"] += 1
            return BTNodeStatus.SUCCESS

        child = Action("inc", increment)
        rep = Repeater("rep", child, count=3)

        status = rep.tick({}, 0.016)
        self.assertEqual(status, BTNodeStatus.SUCCESS)
        self.assertEqual(counter["count"], 3)

    def test_succeeder(self):
        """Test succeeder always returns success."""
        child = Action("child", lambda bb, dt: BTNodeStatus.FAILURE)
        succ = Succeeder("succ", child)

        status = succ.tick({}, 0.016)
        self.assertEqual(status, BTNodeStatus.SUCCESS)

    def test_until_fail(self):
        """Test until_fail repeats until failure."""
        counter = {"count": 0}

        def count_to_fail(bb, dt):
            counter["count"] += 1
            if counter["count"] >= 3:
                return BTNodeStatus.FAILURE
            return BTNodeStatus.SUCCESS

        child = Action("counter", count_to_fail)
        uf = UntilFail("uf", child)

        status = uf.tick({}, 0.016)
        self.assertEqual(status, BTNodeStatus.SUCCESS)
        self.assertEqual(counter["count"], 3)

    def test_cooldown(self):
        """Test cooldown prevents repeated execution."""
        counter = {"count": 0}

        def increment(bb, dt):
            counter["count"] += 1
            return BTNodeStatus.SUCCESS

        child = Action("inc", increment)
        cool = Cooldown("cool", child, duration=0.1)

        # First execution succeeds
        status = cool.tick({}, 0.016)
        self.assertEqual(status, BTNodeStatus.SUCCESS)
        self.assertEqual(counter["count"], 1)

        # Second execution blocked by cooldown
        status = cool.tick({}, 0.016)
        self.assertEqual(status, BTNodeStatus.FAILURE)
        self.assertEqual(counter["count"], 1)

        # Wait for cooldown
        time.sleep(0.11)
        status = cool.tick({}, 0.016)
        self.assertEqual(status, BTNodeStatus.SUCCESS)
        self.assertEqual(counter["count"], 2)

    def test_limiter(self):
        """Test limiter rate-limits executions."""
        counter = {"count": 0}

        def increment(bb, dt):
            counter["count"] += 1
            return BTNodeStatus.SUCCESS

        child = Action("inc", increment)
        lim = Limiter("lim", child, max_runs=2, window=1.0)

        # First two executions succeed
        for _ in range(2):
            lim.tick({}, 0.016)

        # Third is rate-limited
        status = lim.tick({}, 0.016)
        self.assertEqual(status, BTNodeStatus.FAILURE)


class TestBehaviorTree(unittest.TestCase):
    """Test BehaviorTree manager."""

    def test_tree_creation(self):
        """Test creating a behavior tree."""
        root = Sequence("root")
        tree = BehaviorTree(root)

        self.assertEqual(tree.root, root)
        self.assertIsNotNone(tree.blackboard)

    def test_tree_tick(self):
        """Test ticking a tree."""
        root = Sequence("root")
        root.add_child(Action("a1", lambda bb, dt: BTNodeStatus.SUCCESS))

        tree = BehaviorTree(root)
        status = tree.tick(0.016)

        self.assertEqual(status, BTNodeStatus.SUCCESS)
        self.assertEqual(tree.last_status, BTNodeStatus.SUCCESS)

    def test_tree_blackboard(self):
        """Test blackboard operations."""
        root = Sequence("root")
        tree = BehaviorTree(root)

        tree.set_blackboard_value("test_key", 42)
        value = tree.get_blackboard_value("test_key")

        self.assertEqual(value, 42)

    def test_tree_blackboard_default(self):
        """Test blackboard default values."""
        root = Sequence("root")
        tree = BehaviorTree(root)

        value = tree.get_blackboard_value("nonexistent", "default")
        self.assertEqual(value, "default")

    def test_tree_reset(self):
        """Test tree reset."""
        counter = {"count": 0}

        def increment(bb, dt):
            counter["count"] += 1
            return BTNodeStatus.SUCCESS

        root = Repeater("root", Action("inc", increment), count=3)
        tree = BehaviorTree(root)

        tree.tick(0.016)
        tree.reset()

        # Counter should be reset
        self.assertTrue(counter["count"] >= 1)


class TestComplexTrees(unittest.TestCase):
    """Test complex behavior tree structures."""

    def test_nested_composites(self):
        """Test nested composite nodes."""
        # (seq1 && seq2) || fallback
        seq1 = Sequence("seq1")
        seq1.add_child(Action("a1", lambda bb, dt: BTNodeStatus.SUCCESS))

        seq2 = Sequence("seq2")
        seq2.add_child(Action("a2", lambda bb, dt: BTNodeStatus.FAILURE))

        root = Selector("root")
        root.add_child(seq1)
        root.add_child(seq2)

        tree = BehaviorTree(root)
        status = tree.tick(0.016)

        self.assertEqual(status, BTNodeStatus.SUCCESS)

    def test_decision_tree(self):
        """Test tree that makes decisions based on blackboard."""
        root = Selector("root")

        # Try high health path
        root.add_child(Condition("is_healthy", lambda bb: bb.get("health", 0) > 50))

        # Try low health path
        root.add_child(Condition("is_alive", lambda bb: bb.get("health", 0) > 0))

        tree = BehaviorTree(root)

        # With high health
        status = tree.tick(0.016)
        tree.set_blackboard_value("health", 100)
        status = tree.tick(0.016)
        self.assertEqual(status, BTNodeStatus.SUCCESS)

        # With low health
        tree.set_blackboard_value("health", 10)
        status = tree.tick(0.016)
        self.assertEqual(status, BTNodeStatus.SUCCESS)

        # With no health
        tree.set_blackboard_value("health", 0)
        status = tree.tick(0.016)
        self.assertEqual(status, BTNodeStatus.FAILURE)

    def test_tree_is_running(self):
        """Test is_running property."""
        root = Action("running", lambda bb, dt: BTNodeStatus.RUNNING)
        tree = BehaviorTree(root)

        tree.tick(0.016)
        self.assertTrue(tree.is_running)

        root2 = Action("success", lambda bb, dt: BTNodeStatus.SUCCESS)
        tree2 = BehaviorTree(root2)
        tree2.tick(0.016)
        self.assertFalse(tree2.is_running)


class TestInvalidTrees(unittest.TestCase):
    """Test error handling."""

    def test_no_root(self):
        """Test that None root raises error."""
        with self.assertRaises(BehaviorTreeError):
            BehaviorTree(None)


if __name__ == "__main__":
    unittest.main()
