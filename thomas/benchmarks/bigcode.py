"""BigCodeBench-style practical coding benchmark.

Tests real-world coding tasks that require using libraries,
handling edge cases, and writing production-quality code.
"""

import logging

from thomas.benchmarks.types import (
    BenchmarkSuite,
    BenchmarkTask,
    EvalMetric,
    TaskDifficulty,
)

logger = logging.getLogger(__name__)


def create_bigcode_suite() -> BenchmarkSuite:
    """Create a BigCodeBench-style practical coding suite.

    Returns:
        Suite with real-world coding tasks
    """
    suite = BenchmarkSuite(
        name="bigcode_bench",
        description="Practical coding tasks requiring library use and production quality",
        version="1.0",
    )

    tasks: list[tuple] = [
        (
            "csv_parser",
            TaskDifficulty.MEDIUM,
            "Write a function parse_csv(text) that parses CSV text into a list "
            "of dictionaries, using the first row as headers. Handle quoted "
            "fields with commas inside them.\n"
            "Example: parse_csv('name,age\\n\"Smith, John\",30\\nJane,25') "
            "returns [{'name': 'Smith, John', 'age': '30'}, {'name': 'Jane', 'age': '25'}]",
            "exec(output)\n"
            "result = parse_csv('name,age\\n\"Smith, John\",30\\nJane,25')\n"
            "assert len(result) == 2\n"
            "assert result[0]['name'] == 'Smith, John'\n"
            "assert result[1]['age'] == '25'\n"
            "test_passed = True\n",
        ),
        (
            "json_path_query",
            TaskDifficulty.HARD,
            "Write a function json_query(data, path) that supports simple "
            "JSONPath-like queries on nested dicts/lists.\n"
            "Support: dot notation for keys, [n] for array index.\n"
            "json_query({'a': {'b': [1, 2, 3]}}, 'a.b[1]') == 2",
            "exec(output)\n"
            "data = {'a': {'b': [1, 2, 3]}, 'c': 'hello'}\n"
            "assert json_query(data, 'a.b[1]') == 2\n"
            "assert json_query(data, 'c') == 'hello'\n"
            "assert json_query(data, 'a.b[0]') == 1\n"
            "test_passed = True\n",
        ),
        (
            "rate_limiter",
            TaskDifficulty.HARD,
            "Write a RateLimiter class that limits calls to max_calls per "
            "window_seconds.\n"
            "- RateLimiter(max_calls=3, window_seconds=1.0)\n"
            "- allow() -> bool: returns True if call is allowed\n"
            "- reset() -> None: reset the limiter",
            "import time\n"
            "exec(output)\n"
            "rl = RateLimiter(max_calls=3, window_seconds=10.0)\n"
            "assert rl.allow() == True\n"
            "assert rl.allow() == True\n"
            "assert rl.allow() == True\n"
            "assert rl.allow() == False\n"
            "rl.reset()\n"
            "assert rl.allow() == True\n"
            "test_passed = True\n",
        ),
        (
            "url_parser",
            TaskDifficulty.MEDIUM,
            "Write a function parse_url(url) that parses a URL string into "
            "a dictionary with keys: scheme, host, port, path, query_params.\n"
            "parse_url('https://example.com:8080/api/v1?key=val&foo=bar')\n"
            "Should return {'scheme': 'https', 'host': 'example.com', "
            "'port': 8080, 'path': '/api/v1', "
            "'query_params': {'key': 'val', 'foo': 'bar'}}",
            "exec(output)\n"
            "r = parse_url('https://example.com:8080/api/v1?key=val&foo=bar')\n"
            "assert r['scheme'] == 'https'\n"
            "assert r['host'] == 'example.com'\n"
            "assert r['port'] == 8080\n"
            "assert r['path'] == '/api/v1'\n"
            "assert r['query_params']['key'] == 'val'\n"
            "test_passed = True\n",
        ),
        (
            "mini_template_engine",
            TaskDifficulty.HARD,
            "Write a function render(template, context) that renders a "
            "template string with {{ var }} placeholders.\n"
            "Support: variable substitution, {{ if condition }}...{{ endif }}, "
            "{{ for item in list }}...{{ endfor }}.\n"
            "render('Hello {{ name }}!', {'name': 'World'}) == 'Hello World!'",
            "exec(output)\n"
            "assert render('Hello {{ name }}!', {'name': 'World'}) == 'Hello World!'\n"
            "assert render('{{ x }} + {{ y }}', {'x': '1', 'y': '2'}) == '1 + 2'\n"
            "test_passed = True\n",
        ),
        (
            "cron_parser",
            TaskDifficulty.HARD,
            "Write a function parse_cron(expr) that parses a cron expression "
            "(5 fields: minute hour day month weekday) and returns a dict.\n"
            "Support: numbers, * (any), ranges (1-5), lists (1,3,5).\n"
            "parse_cron('*/15 0 1,15 * 1-5') should parse into structured fields.",
            "exec(output)\n"
            "r = parse_cron('30 2 * * 1')\n"
            "assert r['minute'] == [30]\n"
            "assert r['hour'] == [2]\n"
            "assert r['weekday'] == [1]\n"
            "r2 = parse_cron('0 0 1,15 * *')\n"
            "assert r2['day'] == [1, 15]\n"
            "test_passed = True\n",
        ),
        (
            "trie_implementation",
            TaskDifficulty.MEDIUM,
            "Implement a Trie (prefix tree) class:\n"
            "- insert(word: str) -> None\n"
            "- search(word: str) -> bool (exact match)\n"
            "- starts_with(prefix: str) -> bool\n"
            "- autocomplete(prefix: str) -> List[str] (all words with prefix)",
            "exec(output)\n"
            "t = Trie()\n"
            "t.insert('apple')\n"
            "t.insert('app')\n"
            "t.insert('banana')\n"
            "assert t.search('apple') == True\n"
            "assert t.search('app') == True\n"
            "assert t.search('ap') == False\n"
            "assert t.starts_with('app') == True\n"
            "assert sorted(t.autocomplete('app')) == ['app', 'apple']\n"
            "test_passed = True\n",
        ),
        (
            "mini_regex",
            TaskDifficulty.EXPERT,
            "Write a function match(pattern, text) that implements basic "
            "regex matching supporting:\n"
            "- . (any single char)\n"
            "- * (zero or more of preceding)\n"
            "- + (one or more of preceding)\n"
            "- ? (zero or one of preceding)\n"
            "- literal characters\n"
            "Returns True if the entire text matches the pattern.",
            "exec(output)\n"
            "assert match('a.c', 'abc') == True\n"
            "assert match('a*', 'aaa') == True\n"
            "assert match('a*', '') == True\n"
            "assert match('a+', '') == False\n"
            "assert match('a+', 'a') == True\n"
            "assert match('ab?c', 'ac') == True\n"
            "assert match('ab?c', 'abc') == True\n"
            "test_passed = True\n",
        ),
    ]

    for name, difficulty, prompt, test_code in tasks:
        suite.add_task(
            BenchmarkTask(
                name=name,
                category="practical_coding",
                difficulty=difficulty,
                prompt=prompt,
                test_code=test_code,
                eval_metric=EvalMetric.TESTS_PASS,
                time_limit_seconds=120,
                tags=["coding", "practical"],
            )
        )

    logger.info(f"Created BigCodeBench suite with {len(suite.tasks)} tasks")
    return suite
