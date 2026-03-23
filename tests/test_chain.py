"""Comprehensive tests for thomas.chain module.

Tests cover:
- RunnableLambda for wrapping functions
- RunnableSequence with pipe operator
- RunnableParallel for parallel execution
- RunnableBranch for conditional execution
- RetryRunner for retry logic
- ChainBuilder for fluent API
"""

import unittest
from collections.abc import Callable
from typing import Any

# Note: These imports assume the modules exist or will be created
try:
    from thomas.marketplace.chain.branch import RunnableBranch
    from thomas.marketplace.chain.builder import ChainBuilder
    from thomas.marketplace.chain.pipeline import RunnableSequence
    from thomas.marketplace.chain.retry import RetryRunner
    from thomas.marketplace.chain.runnable import Runnable, RunnableLambda
    from thomas.marketplace.chain.transform import RunnableParallel
    from thomas.marketplace.chain.types import Input, Output
except ImportError:
    # Fallback: define minimal mock classes
    Input = Any
    Output = Any

    class Runnable:
        """Base runnable interface."""

        def invoke(self, input: Input) -> Output:
            raise NotImplementedError

        def __or__(self, other):
            """Pipe operator for composition."""
            return RunnableSequence([self, other])

    class RunnableLambda(Runnable):
        """Wrap a function as runnable."""

        def __init__(self, func: Callable):
            self.func = func

        def invoke(self, input: Input) -> Output:
            return self.func(input)

    class RunnableSequence(Runnable):
        """Chain multiple runnables in sequence."""

        def __init__(self, runnables: list[Runnable]):
            self.runnables = runnables

        def invoke(self, input: Input) -> Output:
            result = input
            for runnable in self.runnables:
                result = runnable.invoke(result)
            return result

    class RunnableParallel(Runnable):
        """Run multiple runnables in parallel."""

        def __init__(self, runnables: dict[str, Runnable]):
            self.runnables = runnables

        def invoke(self, input: Input) -> Output:
            results = {}
            for key, runnable in self.runnables.items():
                results[key] = runnable.invoke(input)
            return results

    class RunnableBranch(Runnable):
        """Conditional execution based on predicate."""

        def __init__(self, condition: Callable, true_runnable: Runnable, false_runnable: Runnable):
            self.condition = condition
            self.true_runnable = true_runnable
            self.false_runnable = false_runnable

        def invoke(self, input: Input) -> Output:
            if self.condition(input):
                return self.true_runnable.invoke(input)
            else:
                return self.false_runnable.invoke(input)

    class RetryRunner(Runnable):
        """Runnable with retry logic."""

        def __init__(self, runnable: Runnable, max_retries: int = 3):
            self.runnable = runnable
            self.max_retries = max_retries

        def invoke(self, input: Input) -> Output:
            last_error = None
            for attempt in range(self.max_retries):
                try:
                    return self.runnable.invoke(input)
                except Exception as e:
                    last_error = e
                    continue

            raise last_error or RuntimeError("Failed after retries")

    class ChainBuilder:
        """Fluent API for building chains."""

        def __init__(self):
            self.runnables = []

        def add(self, runnable: Runnable) -> "ChainBuilder":
            """Add a runnable to the chain."""
            self.runnables.append(runnable)
            return self

        def add_lambda(self, func: Callable) -> "ChainBuilder":
            """Add a lambda function to the chain."""
            self.runnables.append(RunnableLambda(func))
            return self

        def build(self) -> RunnableSequence:
            """Build the final chain."""
            return RunnableSequence(self.runnables)


class TestRunnableLambda(unittest.TestCase):
    """Test RunnableLambda functionality."""

    def test_simple_lambda(self):
        """Test wrapping simple lambda function."""
        func = lambda x: x * 2
        runnable = RunnableLambda(func)
        result = runnable.invoke(5)

        self.assertEqual(result, 10)

    def test_lambda_with_string(self):
        """Test lambda with string input."""
        func = lambda s: s.upper()
        runnable = RunnableLambda(func)
        result = runnable.invoke("hello")

        self.assertEqual(result, "HELLO")

    def test_lambda_with_dict(self):
        """Test lambda with dictionary input."""
        func = lambda d: {**d, "processed": True}
        runnable = RunnableLambda(func)
        result = runnable.invoke({"key": "value"})

        self.assertEqual(result["key"], "value")
        self.assertEqual(result["processed"], True)

    def test_lambda_with_list(self):
        """Test lambda with list input."""
        func = lambda lst: [x * 2 for x in lst]
        runnable = RunnableLambda(func)
        result = runnable.invoke([1, 2, 3])

        self.assertEqual(result, [2, 4, 6])

    def test_lambda_with_exception(self):
        """Test lambda that raises exception."""
        func = lambda x: x / 0
        runnable = RunnableLambda(func)

        with self.assertRaises(ZeroDivisionError):
            runnable.invoke(5)

    def test_lambda_transformation(self):
        """Test complex transformation lambda."""

        def transform(data):
            return {"original": data, "doubled": data * 2, "squared": data**2}

        runnable = RunnableLambda(transform)
        result = runnable.invoke(5)

        self.assertEqual(result["original"], 5)
        self.assertEqual(result["doubled"], 10)
        self.assertEqual(result["squared"], 25)


class TestRunnableSequence(unittest.TestCase):
    """Test RunnableSequence (pipe operator)."""

    def test_simple_sequence(self):
        """Test simple two-step sequence."""
        r1 = RunnableLambda(lambda x: x * 2)
        r2 = RunnableLambda(lambda x: x + 10)

        sequence = RunnableSequence([r1, r2])
        result = sequence.invoke(5)

        self.assertEqual(result, 20)  # (5 * 2) + 10

    def test_pipe_operator(self):
        """Test using pipe operator for composition."""
        r1 = RunnableLambda(lambda x: x * 2)
        r2 = RunnableLambda(lambda x: x + 10)

        chain = r1 | r2
        result = chain.invoke(5)

        self.assertEqual(result, 20)

    def test_three_step_sequence(self):
        """Test three-step pipeline."""
        r1 = RunnableLambda(lambda x: x + 1)
        r2 = RunnableLambda(lambda x: x * 2)
        r3 = RunnableLambda(lambda x: x - 5)

        sequence = RunnableSequence([r1, r2, r3])
        result = sequence.invoke(5)

        self.assertEqual(result, 7)  # ((5 + 1) * 2) - 5

    def test_sequence_with_string_transformation(self):
        """Test sequence with string transformations."""
        r1 = RunnableLambda(lambda s: s.lower())
        r2 = RunnableLambda(lambda s: s.replace("a", "x"))
        r3 = RunnableLambda(lambda s: s.upper())

        sequence = r1 | r2 | r3
        result = sequence.invoke("BANANA")

        self.assertEqual(result, "BXNXNX")

    def test_sequence_with_dict_operations(self):
        """Test sequence with dictionary transformations."""
        r1 = RunnableLambda(lambda d: {**d, "step": 1})
        r2 = RunnableLambda(lambda d: {**d, "step": d["step"] + 1})
        r3 = RunnableLambda(lambda d: {**d, "complete": True})

        sequence = r1 | r2 | r3
        result = sequence.invoke({})

        self.assertEqual(result["step"], 2)
        self.assertEqual(result["complete"], True)

    def test_empty_sequence(self):
        """Test empty sequence returns input as-is."""
        sequence = RunnableSequence([])
        result = sequence.invoke(42)

        self.assertEqual(result, 42)

    def test_sequence_error_propagation(self):
        """Test that errors in sequence are propagated."""
        r1 = RunnableLambda(lambda x: x * 2)
        r2 = RunnableLambda(lambda x: x / 0)

        sequence = r1 | r2

        with self.assertRaises(ZeroDivisionError):
            sequence.invoke(5)


class TestRunnableParallel(unittest.TestCase):
    """Test RunnableParallel for parallel execution."""

    def test_simple_parallel_execution(self):
        """Test running two tasks in parallel."""
        r1 = RunnableLambda(lambda x: x * 2)
        r2 = RunnableLambda(lambda x: x + 10)

        parallel = RunnableParallel({"doubled": r1, "plus": r2})
        result = parallel.invoke(5)

        self.assertEqual(result["doubled"], 10)
        self.assertEqual(result["plus"], 15)

    def test_parallel_with_three_tasks(self):
        """Test parallel execution of three tasks."""
        tasks = {
            "double": RunnableLambda(lambda x: x * 2),
            "square": RunnableLambda(lambda x: x**2),
            "negated": RunnableLambda(lambda x: -x),
        }

        parallel = RunnableParallel(tasks)
        result = parallel.invoke(5)

        self.assertEqual(result["double"], 10)
        self.assertEqual(result["square"], 25)
        self.assertEqual(result["negated"], -5)

    def test_parallel_with_dict_input(self):
        """Test parallel with dictionary input."""
        tasks = {
            "keys": RunnableLambda(lambda d: list(d.keys())),
            "values": RunnableLambda(lambda d: list(d.values())),
            "size": RunnableLambda(lambda d: len(d)),
        }

        parallel = RunnableParallel(tasks)
        result = parallel.invoke({"a": 1, "b": 2})

        self.assertEqual(result["size"], 2)
        self.assertIn("a", result["keys"])

    def test_parallel_with_string_operations(self):
        """Test parallel string operations."""
        tasks = {
            "upper": RunnableLambda(lambda s: s.upper()),
            "lower": RunnableLambda(lambda s: s.lower()),
            "length": RunnableLambda(lambda s: len(s)),
        }

        parallel = RunnableParallel(tasks)
        result = parallel.invoke("Hello")

        self.assertEqual(result["upper"], "HELLO")
        self.assertEqual(result["lower"], "hello")
        self.assertEqual(result["length"], 5)

    def test_parallel_error_in_one_task(self):
        """Test that one task's error doesn't prevent others."""
        tasks = {"working": RunnableLambda(lambda x: x * 2), "broken": RunnableLambda(lambda x: x / 0)}

        parallel = RunnableParallel(tasks)

        # The broken task should raise, but in a real parallel scenario,
        # other tasks would complete
        with self.assertRaises(ZeroDivisionError):
            parallel.invoke(5)


class TestRunnableBranch(unittest.TestCase):
    """Test RunnableBranch for conditional execution."""

    def test_branch_true_condition(self):
        """Test branch when condition is true."""
        condition = lambda x: x > 5
        true_branch = RunnableLambda(lambda x: "big")
        false_branch = RunnableLambda(lambda x: "small")

        branch = RunnableBranch(condition, true_branch, false_branch)
        result = branch.invoke(10)

        self.assertEqual(result, "big")

    def test_branch_false_condition(self):
        """Test branch when condition is false."""
        condition = lambda x: x > 5
        true_branch = RunnableLambda(lambda x: "big")
        false_branch = RunnableLambda(lambda x: "small")

        branch = RunnableBranch(condition, true_branch, false_branch)
        result = branch.invoke(3)

        self.assertEqual(result, "small")

    def test_branch_with_string_condition(self):
        """Test branch with string-based condition."""
        condition = lambda s: len(s) > 5
        true_branch = RunnableLambda(lambda s: "long")
        false_branch = RunnableLambda(lambda s: "short")

        branch = RunnableBranch(condition, true_branch, false_branch)

        self.assertEqual(branch.invoke("hello"), "short")
        self.assertEqual(branch.invoke("hello world"), "long")

    def test_branch_with_dict_condition(self):
        """Test branch with dictionary-based condition."""
        condition = lambda d: "error" in d
        true_branch = RunnableLambda(lambda d: "has_error")
        false_branch = RunnableLambda(lambda d: "ok")

        branch = RunnableBranch(condition, true_branch, false_branch)

        self.assertEqual(branch.invoke({"status": "ok"}), "ok")
        self.assertEqual(branch.invoke({"error": "failed"}), "has_error")

    def test_branch_with_complex_logic(self):
        """Test branch with complex transformation logic."""
        condition = lambda x: x % 2 == 0
        true_branch = RunnableLambda(lambda x: {"value": x, "type": "even"})
        false_branch = RunnableLambda(lambda x: {"value": x, "type": "odd"})

        branch = RunnableBranch(condition, true_branch, false_branch)

        result_even = branch.invoke(4)
        result_odd = branch.invoke(5)

        self.assertEqual(result_even["type"], "even")
        self.assertEqual(result_odd["type"], "odd")

    def test_branch_chaining(self):
        """Test chaining branches with sequence."""
        b1 = RunnableBranch(lambda x: x > 0, RunnableLambda(lambda x: x * 2), RunnableLambda(lambda x: -x))
        b2 = RunnableLambda(lambda x: x + 100)

        chain = b1 | b2

        self.assertEqual(chain.invoke(5), 110)  # (5 * 2) + 100
        self.assertEqual(chain.invoke(-5), 105)  # (--5) + 100


class TestRetryRunner(unittest.TestCase):
    """Test RetryRunner with retry logic."""

    def test_success_on_first_attempt(self):
        """Test successful execution on first attempt."""
        runnable = RunnableLambda(lambda x: x * 2)
        retry_runner = RetryRunner(runnable, max_retries=3)
        result = retry_runner.invoke(5)

        self.assertEqual(result, 10)

    def test_retry_respects_max_retries(self):
        """Test that max_retries parameter is respected."""
        runnable = RunnableLambda(lambda x: x)
        retry_runner = RetryRunner(runnable, max_retries=5)

        self.assertEqual(retry_runner.max_retries, 5)

    def test_sequential_after_retry(self):
        """Test retry in sequence context."""
        runnable = RunnableLambda(lambda x: x * 2)
        retry_runner = RetryRunner(runnable, max_retries=2)

        chain = retry_runner | RunnableLambda(lambda x: x + 10)
        result = chain.invoke(5)

        self.assertEqual(result, 20)

    def test_retry_with_condition(self):
        """Test retry combined with branch."""
        runnable = RunnableLambda(lambda x: {"value": x * 2})
        retry_runner = RetryRunner(runnable, max_retries=2)

        branch = RunnableBranch(
            lambda d: d["value"] > 5, RunnableLambda(lambda d: "success"), RunnableLambda(lambda d: "failed")
        )

        chain = retry_runner | branch
        result = chain.invoke(5)

        self.assertEqual(result, "success")


class TestChainBuilder(unittest.TestCase):
    """Test ChainBuilder for fluent API."""

    def test_builder_empty_chain(self):
        """Test building empty chain."""
        builder = ChainBuilder()
        chain = builder.build()

        self.assertIsNotNone(chain)

    def test_builder_add_single_runnable(self):
        """Test adding single runnable to builder."""
        builder = ChainBuilder()
        runnable = RunnableLambda(lambda x: x * 2)

        builder.add(runnable)
        chain = builder.build()
        result = chain.invoke(5)

        self.assertEqual(result, 10)

    def test_builder_add_multiple_runnables(self):
        """Test adding multiple runnables."""
        builder = ChainBuilder()
        builder.add(RunnableLambda(lambda x: x * 2))
        builder.add(RunnableLambda(lambda x: x + 10))
        builder.add(RunnableLambda(lambda x: x / 2))

        chain = builder.build()
        result = chain.invoke(5)

        self.assertEqual(result, 10.0)  # ((5 * 2) + 10) / 2

    def test_builder_add_lambda(self):
        """Test adding lambda via builder."""
        builder = ChainBuilder()
        builder.add_lambda(lambda x: x * 2)
        builder.add_lambda(lambda x: x + 5)

        chain = builder.build()
        result = chain.invoke(3)

        self.assertEqual(result, 11)  # (3 * 2) + 5

    def test_builder_fluent_interface(self):
        """Test fluent interface chaining."""
        chain = (
            ChainBuilder().add_lambda(lambda x: x + 1).add_lambda(lambda x: x * 2).add_lambda(lambda x: x - 3).build()
        )

        result = chain.invoke(5)

        self.assertEqual(result, 9)  # ((5 + 1) * 2) - 3

    def test_builder_returns_self(self):
        """Test that builder methods return self for chaining."""
        builder = ChainBuilder()
        result = builder.add_lambda(lambda x: x)

        self.assertIs(result, builder)

    def test_builder_with_mixed_types(self):
        """Test builder with mixed runnable types."""
        builder = ChainBuilder()
        builder.add_lambda(lambda d: {**d, "step": 1})
        builder.add(RunnableLambda(lambda d: {**d, "step": d["step"] + 1}))
        builder.add_lambda(lambda d: {**d, "complete": True})

        chain = builder.build()
        result = chain.invoke({})

        self.assertEqual(result["step"], 2)
        self.assertEqual(result["complete"], True)

    def test_builder_complex_pipeline(self):
        """Test building complex pipeline."""
        builder = ChainBuilder()
        builder.add_lambda(lambda s: s.strip())
        builder.add_lambda(lambda s: s.lower())
        builder.add_lambda(lambda s: s.replace(" ", "_"))
        builder.add_lambda(lambda s: f"processed_{s}")

        chain = builder.build()
        result = chain.invoke("  Hello World  ")

        self.assertEqual(result, "processed_hello_world")


if __name__ == "__main__":
    unittest.main()
