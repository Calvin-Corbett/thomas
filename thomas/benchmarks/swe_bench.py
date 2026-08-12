"""SWE-bench style benchmark tasks.

Generates software engineering benchmark tasks that test:
- Bug fixing from issue descriptions
- Feature implementation from specs
- Code refactoring
- Test writing
- Documentation
"""

import logging
import re
from dataclasses import dataclass, field
from difflib import unified_diff
from typing import Any

from thomas.benchmarks.types import (
    BenchmarkSuite,
    BenchmarkTask,
    EvalMetric,
    TaskDifficulty,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LocalSWEBenchFixture:
    """Offline issue-to-patch fixture small enough for unit tests and CI gates."""

    issue_id: str
    repository: str
    issue_title: str
    issue_body: str
    base_files: dict[str, str]
    expected_files: dict[str, str]
    fail_to_pass_tests: list[str] = field(default_factory=list)
    pass_to_pass_tests: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = "local-swe-bench-v1"

    def __post_init__(self) -> None:
        _validate_fixture_paths(self.base_files)
        _validate_fixture_paths(self.expected_files)
        missing_base = sorted(set(self.expected_files) - set(self.base_files))
        if missing_base:
            raise ValueError(f"local SWE-bench fixtures only support existing-file patches: {missing_base}")

    def prompt(self) -> str:
        """Render the issue and repository snapshot as a patch-generation prompt."""
        file_blocks = []
        for path in sorted(self.base_files):
            file_blocks.append(f"### {path}\n```python\n{self.base_files[path]}```")
        tests = self.fail_to_pass_tests + self.pass_to_pass_tests
        tests_text = "\n".join(f"- {item}" for item in tests) if tests else "- No test commands declared"
        files_text = "\n\n".join(file_blocks)
        return (
            f"You are fixing issue {self.issue_id} in repository {self.repository}.\n\n"
            f"Title: {self.issue_title}\n\n"
            f"{self.issue_body.strip()}\n\n"
            "Return a unified diff patch only. Do not rewrite unrelated files.\n\n"
            "Repository files:\n\n"
            f"{files_text}\n\n"
            "Offline verification commands:\n"
            f"{tests_text}\n"
        )

    def reference_patch(self) -> str:
        """Return the canonical unified diff from base files to expected files."""
        chunks: list[str] = []
        for path in sorted(self.expected_files):
            before = self.base_files[path].splitlines()
            after = self.expected_files[path].splitlines()
            chunks.extend(
                unified_diff(
                    before,
                    after,
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                    lineterm="",
                )
            )
        return "\n".join(chunks) + "\n"

    def to_benchmark_task(self) -> BenchmarkTask:
        """Convert the local fixture into the existing benchmark task contract."""
        return BenchmarkTask(
            name=f"local_swe_bench_{self.issue_id}",
            description="Offline SWE-bench style repository issue patch fixture",
            category="issue_patch",
            difficulty=TaskDifficulty.EASY,
            prompt=self.prompt(),
            expected_output=self.reference_patch(),
            eval_metric=EvalMetric.FUNCTIONAL,
            eval_fn=lambda output, _expected: score_swe_bench_patch(self, output)["score"],
            tags=["swe-bench", "local-fixture", "offline", "issue-to-patch"],
            metadata={
                "schema_version": self.schema_version,
                "issue_id": self.issue_id,
                "repository": self.repository,
                "base_files": sorted(self.base_files),
                "expected_files": sorted(self.expected_files),
                "fail_to_pass_tests": list(self.fail_to_pass_tests),
                "pass_to_pass_tests": list(self.pass_to_pass_tests),
                **dict(self.metadata),
            },
            time_limit_seconds=60,
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the fixture schema for future file-backed loaders."""
        return {
            "schema_version": self.schema_version,
            "issue_id": self.issue_id,
            "repository": self.repository,
            "issue_title": self.issue_title,
            "issue_body": self.issue_body,
            "base_files": dict(self.base_files),
            "expected_files": dict(self.expected_files),
            "fail_to_pass_tests": list(self.fail_to_pass_tests),
            "pass_to_pass_tests": list(self.pass_to_pass_tests),
            "metadata": dict(self.metadata),
        }


def _validate_fixture_paths(files: dict[str, str]) -> None:
    for path in files:
        normalized = path.replace("\\", "/").strip()
        if not normalized or normalized.startswith("/") or normalized.startswith("../") or "/../" in normalized:
            raise ValueError(f"invalid fixture path: {path!r}")


def create_local_swe_bench_fixture() -> LocalSWEBenchFixture:
    """Create a tiny offline repository issue fixture inspired by SWE-bench."""
    base = (
        "def percentage(numerator, denominator):\n"
        '    """Return numerator as a percentage of denominator."""\n'
        "    return round((numerator / denominator) * 100, 2)\n"
    )
    expected = (
        "def percentage(numerator, denominator):\n"
        '    """Return numerator as a percentage of denominator."""\n'
        "    if denominator == 0:\n"
        "        return None\n"
        "    return round((numerator / denominator) * 100, 2)\n"
    )
    return LocalSWEBenchFixture(
        issue_id="local-zero-division-001",
        repository="local/finance-utils",
        issue_title="percentage crashes when denominator is zero",
        issue_body=(
            "Users report that percentage(5, 0) raises ZeroDivisionError. The repository contract expects "
            "None when the denominator is zero, while existing non-zero behavior must remain unchanged."
        ),
        base_files={"finance_utils/metrics.py": base},
        expected_files={"finance_utils/metrics.py": expected},
        fail_to_pass_tests=["pytest tests/test_metrics.py::test_percentage_zero_denominator"],
        pass_to_pass_tests=["pytest tests/test_metrics.py::test_percentage_regular_values"],
        metadata={"source": "local-offline-fixture"},
    )


def create_local_swe_bench_suite() -> BenchmarkSuite:
    """Create a one-task local SWE-bench style issue-to-patch suite."""
    suite = BenchmarkSuite(
        name="swe_bench_local",
        description="Offline SWE-bench inspired issue-to-patch fixture",
        version="1.0",
    )
    suite.add_task(create_local_swe_bench_fixture().to_benchmark_task())
    return suite


def score_swe_bench_patch(fixture: LocalSWEBenchFixture, candidate_patch: str) -> dict[str, Any]:
    """Score a candidate unified diff against a local SWE-bench fixture."""
    try:
        diff_text = _extract_unified_diff(candidate_patch)
        patched_files = _apply_unified_diff(fixture.base_files, diff_text)
    except ValueError as exc:
        return {
            "passed": False,
            "score": 0.0,
            "error": str(exc),
            "modified_files": [],
            "missing_files": sorted(fixture.expected_files),
            "mismatched_files": [],
        }

    modified = sorted(path for path in patched_files if patched_files[path] != fixture.base_files.get(path, ""))
    missing = sorted(path for path in fixture.expected_files if path not in patched_files)
    mismatched = sorted(
        path for path, expected in fixture.expected_files.items() if patched_files.get(path) != expected
    )
    unexpected = sorted(path for path in patched_files if path not in fixture.base_files)

    required_count = max(1, len(fixture.expected_files))
    matched_count = len(fixture.expected_files) - len(set(missing) | set(mismatched))
    score = max(0.0, matched_count / required_count)
    if unexpected:
        score = min(score, 0.5)

    passed = not missing and not mismatched and not unexpected
    return {
        "passed": passed,
        "score": 1.0 if passed else score,
        "error": "",
        "modified_files": modified,
        "missing_files": missing,
        "mismatched_files": mismatched,
        "unexpected_files": unexpected,
    }


def _extract_unified_diff(text: str) -> str:
    raw = str(text or "")
    if not raw.strip():
        raise ValueError("candidate patch is empty")
    fenced = re.search(r"```(?:diff|patch)?\s*(.*?)```", raw, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        raw = fenced.group(1).strip("\n")
    markers = ("diff --git ", "--- a/", "--- ")
    for marker in markers:
        idx = raw.find(marker)
        if idx >= 0:
            return raw[idx:].lstrip()
    raise ValueError("candidate patch does not contain a unified diff")


def _apply_unified_diff(base_files: dict[str, str], diff_text: str) -> dict[str, str]:
    patched = dict(base_files)
    lines = str(diff_text or "").splitlines(keepends=True)
    index = 0
    touched = False
    while index < len(lines):
        line = lines[index]
        if line.startswith("diff --git "):
            index += 1
            continue
        if not line.startswith("--- "):
            index += 1
            continue

        old_path = _diff_path(line[4:].strip())
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise ValueError(f"missing +++ header after {old_path}")
        new_path = _diff_path(lines[index][4:].strip())
        index += 1
        target_path = new_path if new_path != "/dev/null" else old_path
        if target_path not in base_files:
            raise ValueError(f"candidate patch modifies unknown file: {target_path}")

        source = patched[target_path].splitlines(keepends=True)
        output: list[str] = []
        source_index = 0
        saw_hunk = False
        while index < len(lines):
            current = lines[index]
            if current.startswith(("diff --git ", "--- ")):
                break
            if not current.startswith("@@ "):
                index += 1
                continue

            old_start = _parse_old_hunk_start(current)
            output.extend(source[source_index : old_start - 1])
            source_index = old_start - 1
            saw_hunk = True
            index += 1

            while index < len(lines):
                patch_line = lines[index]
                if patch_line.startswith(("@@ ", "diff --git ", "--- ")):
                    break
                if patch_line.startswith("\\"):
                    index += 1
                    continue
                if not patch_line:
                    index += 1
                    continue
                prefix = patch_line[0]
                content = patch_line[1:]
                if prefix == " ":
                    _require_source_line(source, source_index, content, target_path)
                    output.append(source[source_index])
                    source_index += 1
                elif prefix == "-":
                    _require_source_line(source, source_index, content, target_path)
                    source_index += 1
                elif prefix == "+":
                    output.append(content)
                else:
                    raise ValueError(f"unsupported diff line for {target_path}: {patch_line.rstrip()}")
                index += 1

        if not saw_hunk:
            raise ValueError(f"no hunks found for {target_path}")
        output.extend(source[source_index:])
        patched[target_path] = "".join(output)
        touched = True

    if not touched:
        raise ValueError("candidate patch did not modify any files")
    return patched


def _diff_path(raw: str) -> str:
    token = raw.split("\t", 1)[0].strip()
    if token in {"/dev/null", "dev/null"}:
        return "/dev/null"
    if token.startswith(("a/", "b/")):
        token = token[2:]
    return token.replace("\\", "/").strip()


def _parse_old_hunk_start(header: str) -> int:
    match = re.match(r"@@ -(?P<start>\d+)(?:,\d+)? \+\d+(?:,\d+)? @@", header)
    if not match:
        raise ValueError(f"invalid unified diff hunk header: {header.rstrip()}")
    return int(match.group("start"))


def _require_source_line(source: list[str], source_index: int, expected: str, path: str) -> None:
    if source_index >= len(source):
        raise ValueError(f"candidate patch hunk extends past end of {path}")
    if source[source_index] != expected:
        raise ValueError(f"candidate patch context mismatch in {path}")


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
