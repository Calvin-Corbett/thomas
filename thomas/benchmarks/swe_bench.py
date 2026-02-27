"""SWE-bench style benchmark tasks.

Generates software engineering benchmark tasks that test:
- Bug fixing from issue descriptions
- Feature implementation from specs
- Code refactoring
- Test writing
- Documentation
"""

import logging

from thomas.benchmarks.types import (
    BenchmarkSuite,
    BenchmarkTask,
    EvalMetric,
    TaskDifficulty,
)

logger = logging.getLogger(__name__)


def create_swe_bench_suite() -> BenchmarkSuite:
    """Create a SWE-bench style benchmark suite.

    Returns:
        Suite with software engineering tasks
    """
    suite = BenchmarkSuite(
        name="swe_bench",
        description="Software engineering benchmark testing bug fixes, features, refactoring",
        version="1.0",
    )

    # ── Bug Fix Tasks ─────────────────────────────────────────
    suite.add_task(
        BenchmarkTask(
            name="fix_off_by_one",
            category="bug_fix",
            difficulty=TaskDifficulty.EASY,
            prompt=(
                "Fix the bug in this function:\n\n"
                "```python\n"
                "def get_last_n(items, n):\n"
                "    return items[len(items) - n - 1:]\n"
                "```\n\n"
                "The function should return the last n items from a list. "
                "get_last_n([1,2,3,4,5], 3) should return [3,4,5] but returns [2,3,4,5]."
            ),
            expected_output="items[len(items) - n:]",
            test_code=(
                "exec(output)\n"
                "assert get_last_n([1,2,3,4,5], 3) == [3,4,5]\n"
                "assert get_last_n([1,2,3], 1) == [3]\n"
                "assert get_last_n([1], 1) == [1]\n"
                "test_passed = True\n"
            ),
            eval_metric=EvalMetric.TESTS_PASS,
        )
    )

    suite.add_task(
        BenchmarkTask(
            name="fix_null_check",
            category="bug_fix",
            difficulty=TaskDifficulty.EASY,
            prompt=(
                "Fix the bug in this function that crashes on empty input:\n\n"
                "```python\n"
                "def find_max(numbers):\n"
                "    max_val = numbers[0]\n"
                "    for n in numbers[1:]:\n"
                "        if n > max_val:\n"
                "            max_val = n\n"
                "    return max_val\n"
                "```\n\n"
                "It should return None for empty lists instead of crashing."
            ),
            expected_output="if not numbers: return None",
            test_code=(
                "exec(output)\n"
                "assert find_max([]) is None\n"
                "assert find_max([5]) == 5\n"
                "assert find_max([1,3,2]) == 3\n"
                "test_passed = True\n"
            ),
            eval_metric=EvalMetric.TESTS_PASS,
        )
    )

    suite.add_task(
        BenchmarkTask(
            name="fix_race_condition",
            category="bug_fix",
            difficulty=TaskDifficulty.HARD,
            prompt=(
                "This counter class has a race condition when used with threads. "
                "Fix it using threading.Lock:\n\n"
                "```python\n"
                "class Counter:\n"
                "    def __init__(self):\n"
                "        self.value = 0\n"
                "    def increment(self):\n"
                "        self.value += 1\n"
                "    def get(self):\n"
                "        return self.value\n"
                "```"
            ),
            expected_output="threading.Lock",
            eval_metric=EvalMetric.CONTAINS,
        )
    )

    # ── Feature Implementation Tasks ──────────────────────────
    suite.add_task(
        BenchmarkTask(
            name="implement_lru_cache",
            category="feature",
            difficulty=TaskDifficulty.MEDIUM,
            prompt=(
                "Implement an LRU (Least Recently Used) cache class in Python.\n\n"
                "Requirements:\n"
                "- `LRUCache(capacity)` - create with given capacity\n"
                "- `get(key)` - return value or -1 if not found\n"
                "- `put(key, value)` - insert/update, evict LRU if at capacity\n"
                "- O(1) time for both operations\n\n"
                "Use only stdlib (no functools.lru_cache)."
            ),
            test_code=(
                "exec(output)\n"
                "cache = LRUCache(2)\n"
                "cache.put(1, 1)\n"
                "cache.put(2, 2)\n"
                "assert cache.get(1) == 1\n"
                "cache.put(3, 3)  # evicts key 2\n"
                "assert cache.get(2) == -1\n"
                "cache.put(4, 4)  # evicts key 1\n"
                "assert cache.get(1) == -1\n"
                "assert cache.get(3) == 3\n"
                "assert cache.get(4) == 4\n"
                "test_passed = True\n"
            ),
            eval_metric=EvalMetric.TESTS_PASS,
        )
    )

    suite.add_task(
        BenchmarkTask(
            name="implement_retry_decorator",
            category="feature",
            difficulty=TaskDifficulty.MEDIUM,
            prompt=(
                "Implement a retry decorator in Python:\n\n"
                "```python\n"
                "@retry(max_attempts=3, delay=0.1)\n"
                "def flaky_function():\n"
                "    ...\n"
                "```\n\n"
                "Requirements:\n"
                "- Retries the function up to max_attempts times\n"
                "- Waits delay seconds between retries\n"
                "- Raises the last exception if all attempts fail\n"
                "- Returns the result on first success"
            ),
            test_code=(
                "import time\n"
                "exec(output)\n"
                "call_count = 0\n"
                "@retry(max_attempts=3, delay=0.01)\n"
                "def fail_twice():\n"
                "    global call_count\n"
                "    call_count += 1\n"
                "    if call_count < 3:\n"
                "        raise ValueError('not yet')\n"
                "    return 'success'\n"
                "assert fail_twice() == 'success'\n"
                "assert call_count == 3\n"
                "test_passed = True\n"
            ),
            eval_metric=EvalMetric.TESTS_PASS,
        )
    )

    suite.add_task(
        BenchmarkTask(
            name="implement_event_emitter",
            category="feature",
            difficulty=TaskDifficulty.MEDIUM,
            prompt=(
                "Implement an EventEmitter class in Python:\n\n"
                "- `on(event, handler)` - register a handler for an event\n"
                "- `off(event, handler)` - remove a handler\n"
                "- `emit(event, *args)` - trigger all handlers for an event\n"
                "- `once(event, handler)` - register handler that fires only once\n"
            ),
            test_code=(
                "exec(output)\n"
                "ee = EventEmitter()\n"
                "results = []\n"
                "ee.on('data', lambda x: results.append(x))\n"
                "ee.emit('data', 42)\n"
                "ee.emit('data', 99)\n"
                "assert results == [42, 99]\n"
                "once_results = []\n"
                "ee.once('single', lambda x: once_results.append(x))\n"
                "ee.emit('single', 1)\n"
                "ee.emit('single', 2)\n"
                "assert once_results == [1]\n"
                "test_passed = True\n"
            ),
            eval_metric=EvalMetric.TESTS_PASS,
        )
    )

    # ── Refactoring Tasks ─────────────────────────────────────
    suite.add_task(
        BenchmarkTask(
            name="refactor_god_function",
            category="refactor",
            difficulty=TaskDifficulty.MEDIUM,
            prompt=(
                "Refactor this god function into clean, focused functions:\n\n"
                "```python\n"
                "def process_order(order):\n"
                "    # validate\n"
                "    if not order.get('items'):\n"
                "        return {'error': 'no items'}\n"
                "    if not order.get('customer'):\n"
                "        return {'error': 'no customer'}\n"
                "    # calculate total\n"
                "    total = 0\n"
                "    for item in order['items']:\n"
                "        total += item['price'] * item['qty']\n"
                "    # apply discount\n"
                "    if order.get('coupon') == 'SAVE10':\n"
                "        total *= 0.9\n"
                "    # apply tax\n"
                "    total *= 1.08\n"
                "    return {'total': round(total, 2), 'customer': order['customer']}\n"
                "```\n\n"
                "Split into: validate_order, calculate_total, apply_discount, apply_tax."
            ),
            eval_metric=EvalMetric.CODE_QUALITY,
        )
    )

    suite.add_task(
        BenchmarkTask(
            name="refactor_to_dataclass",
            category="refactor",
            difficulty=TaskDifficulty.EASY,
            prompt=(
                "Refactor this dict-heavy code to use Python dataclasses:\n\n"
                "```python\n"
                "def create_user(name, email, age):\n"
                "    return {'name': name, 'email': email, 'age': age}\n"
                "\n"
                "def user_to_string(user):\n"
                "    return f\"{user['name']} ({user['email']})\"\n"
                "\n"
                "def is_adult(user):\n"
                "    return user['age'] >= 18\n"
                "```"
            ),
            expected_output="@dataclass",
            eval_metric=EvalMetric.CONTAINS,
        )
    )

    # ── Test Writing Tasks ────────────────────────────────────
    suite.add_task(
        BenchmarkTask(
            name="write_tests_for_stack",
            category="testing",
            difficulty=TaskDifficulty.MEDIUM,
            prompt=(
                "Write comprehensive unit tests for this Stack class:\n\n"
                "```python\n"
                "class Stack:\n"
                "    def __init__(self):\n"
                "        self._items = []\n"
                "    def push(self, item):\n"
                "        self._items.append(item)\n"
                "    def pop(self):\n"
                "        if not self._items:\n"
                "            raise IndexError('pop from empty stack')\n"
                "        return self._items.pop()\n"
                "    def peek(self):\n"
                "        if not self._items:\n"
                "            raise IndexError('peek at empty stack')\n"
                "        return self._items[-1]\n"
                "    def is_empty(self):\n"
                "        return len(self._items) == 0\n"
                "    def size(self):\n"
                "        return len(self._items)\n"
                "```\n\n"
                "Cover: push, pop, peek, is_empty, size, edge cases, error conditions."
            ),
            expected_output="unittest",
            eval_metric=EvalMetric.CODE_QUALITY,
        )
    )

    # ── Multi-step Tasks ──────────────────────────────────────
    suite.add_task(
        BenchmarkTask(
            name="build_rest_endpoint",
            category="multi_step",
            difficulty=TaskDifficulty.HARD,
            prompt=(
                "Create a complete REST API endpoint handler (no framework needed) "
                "for a TODO list:\n\n"
                "- Parse JSON request body\n"
                "- Support GET (list all), POST (create), DELETE (by id)\n"
                "- Store todos in memory (list)\n"
                "- Each todo has: id, title, completed\n"
                "- Return JSON responses with proper status codes\n"
                "- Include input validation\n"
                "- Include error handling\n\n"
                "Write a TodoHandler class with handle_request(method, path, body) method."
            ),
            test_code=(
                "import json as _json\n"
                "exec(output)\n"
                "h = TodoHandler()\n"
                "# Create\n"
                "r = h.handle_request('POST', '/todos', '{\"title\": \"Buy milk\"}')\n"
                "assert r['status'] == 201\n"
                "# List\n"
                "r = h.handle_request('GET', '/todos', '')\n"
                "assert r['status'] == 200\n"
                "assert len(_json.loads(r['body'])) == 1\n"
                "test_passed = True\n"
            ),
            eval_metric=EvalMetric.TESTS_PASS,
        )
    )

    suite.add_task(
        BenchmarkTask(
            name="debug_from_traceback",
            category="debugging",
            difficulty=TaskDifficulty.HARD,
            prompt=(
                "Given this traceback, identify the bug and write the fix:\n\n"
                "```\n"
                "Traceback (most recent call last):\n"
                '  File "app.py", line 42, in process_data\n'
                "    result = data['users'][0]['address']['city']\n"
                "KeyError: 'address'\n"
                "```\n\n"
                "The data comes from an API where 'address' is optional. "
                "Write a safe_get function that handles missing nested keys:\n"
                "safe_get(data, 'users.0.address.city', default='Unknown')"
            ),
            test_code=(
                "exec(output)\n"
                "data = {'users': [{'name': 'Alice', 'address': {'city': 'NYC'}}]}\n"
                "assert safe_get(data, 'users.0.address.city') == 'NYC'\n"
                "data2 = {'users': [{'name': 'Bob'}]}\n"
                "assert safe_get(data2, 'users.0.address.city', default='Unknown') == 'Unknown'\n"
                "assert safe_get({}, 'a.b.c', default=None) is None\n"
                "test_passed = True\n"
            ),
            eval_metric=EvalMetric.TESTS_PASS,
        )
    )

    logger.info(f"Created SWE bench suite with {len(suite.tasks)} tasks")
    return suite


def create_humaneval_suite() -> BenchmarkSuite:
    """Create a HumanEval-style code generation suite.

    Returns:
        Suite with algorithmic coding tasks
    """
    suite = BenchmarkSuite(
        name="humaneval",
        description="Code generation benchmark (HumanEval style)",
        version="1.0",
    )

    tasks = [
        (
            "has_close_elements",
            "easy",
            "Write a function has_close_elements(numbers: List[float], threshold: float) -> bool "
            "that checks if any two numbers in the list are closer than the threshold.",
            "exec(output)\nassert has_close_elements([1.0, 2.0, 3.0], 0.5) == False\n"
            "assert has_close_elements([1.0, 2.8, 3.0], 0.3) == True\ntest_passed = True\n",
        ),
        (
            "separate_paren_groups",
            "medium",
            "Write a function separate_paren_groups(paren_string: str) -> List[str] "
            "that separates balanced parentheses groups. "
            "Input: '( ) (( )) (( )( ))' Output: ['()', '(())', '(()())']",
            "exec(output)\nassert separate_paren_groups('( ) (( )) (( )( ))') == ['()', '(())', '(()())']\ntest_passed = True\n",
        ),
        (
            "truncate_number",
            "easy",
            "Write a function truncate_number(number: float) -> float "
            "that returns the decimal part. truncate_number(3.5) == 0.5",
            "exec(output)\nassert abs(truncate_number(3.5) - 0.5) < 1e-9\n"
            "assert abs(truncate_number(1.25) - 0.25) < 1e-9\ntest_passed = True\n",
        ),
        (
            "below_zero",
            "easy",
            "Write a function below_zero(operations: List[int]) -> bool "
            "that detects if a bank balance starting at 0 ever goes below zero. "
            "below_zero([1, 2, -3, 1, 2, -9]) == True",
            "exec(output)\nassert below_zero([1, 2, -3, 1, 2, -9]) == True\n"
            "assert below_zero([1, 2, 3]) == False\ntest_passed = True\n",
        ),
        (
            "mean_absolute_deviation",
            "medium",
            "Write a function mean_absolute_deviation(numbers: List[float]) -> float "
            "that computes the mean absolute deviation around the mean.",
            "exec(output)\nassert abs(mean_absolute_deviation([1.0, 2.0, 3.0, 4.0]) - 1.0) < 1e-6\ntest_passed = True\n",
        ),
        (
            "intersperse",
            "easy",
            "Write a function intersperse(numbers: List[int], delimeter: int) -> List[int] "
            "that inserts delimeter between every two elements. "
            "intersperse([1, 2, 3], 4) == [1, 4, 2, 4, 3]",
            "exec(output)\nassert intersperse([1, 2, 3], 4) == [1, 4, 2, 4, 3]\n"
            "assert intersperse([], 4) == []\ntest_passed = True\n",
        ),
        (
            "parse_nested_parens",
            "hard",
            "Write a function parse_nested_parens(paren_string: str) -> List[int] "
            "that returns the max nesting depth for each group of parentheses. "
            "parse_nested_parens('(()()) ((())) () ((())())')  == [2, 3, 1, 3]",
            "exec(output)\nassert parse_nested_parens('(()()) ((())) () ((())())') == [2, 3, 1, 3]\ntest_passed = True\n",
        ),
        (
            "filter_by_substring",
            "easy",
            "Write a function filter_by_substring(strings: List[str], substring: str) -> List[str] "
            "that filters strings containing the substring.",
            "exec(output)\nassert filter_by_substring(['abc', 'def', 'abcdef'], 'abc') == ['abc', 'abcdef']\ntest_passed = True\n",
        ),
    ]

    diff_map = {"easy": TaskDifficulty.EASY, "medium": TaskDifficulty.MEDIUM, "hard": TaskDifficulty.HARD}

    for name, diff, prompt, test_code in tasks:
        suite.add_task(
            BenchmarkTask(
                name=name,
                category="code_gen",
                difficulty=diff_map[diff],
                prompt=prompt,
                test_code=test_code,
                eval_metric=EvalMetric.TESTS_PASS,
                time_limit_seconds=60,
            )
        )

    logger.info(f"Created HumanEval suite with {len(suite.tasks)} tasks")
    return suite
