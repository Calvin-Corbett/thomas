"""MBPP (Mostly Basic Python Problems) benchmark suite.

Standard code generation benchmark with simple Python tasks,
testing basic programming competency.
"""

import logging

from thomas.benchmarks.types import (
    BenchmarkSuite,
    BenchmarkTask,
    EvalMetric,
    TaskDifficulty,
)

logger = logging.getLogger(__name__)


def create_mbpp_suite() -> BenchmarkSuite:
    """Create an MBPP-style benchmark suite.

    Returns:
        Suite with basic Python programming tasks
    """
    suite = BenchmarkSuite(
        name="mbpp",
        description="Mostly Basic Python Problems - standard code generation benchmark",
        version="1.0",
    )

    tasks: list[tuple] = [
        (
            "find_missing_number",
            TaskDifficulty.EASY,
            "Write a function find_missing_number(lst) that finds the missing "
            "number in a list of consecutive integers from 1 to n. "
            "Example: find_missing_number([1, 2, 4, 5]) == 3",
            "exec(output)\n"
            "assert find_missing_number([1, 2, 4, 5]) == 3\n"
            "assert find_missing_number([1, 3]) == 2\n"
            "assert find_missing_number([2, 3, 4]) == 1\n"
            "test_passed = True\n",
        ),
        (
            "is_palindrome",
            TaskDifficulty.EASY,
            "Write a function is_palindrome(s) that checks if a string is "
            "a palindrome (ignoring case and non-alphanumeric chars). "
            "is_palindrome('A man, a plan, a canal: Panama') == True",
            "exec(output)\n"
            "assert is_palindrome('A man, a plan, a canal: Panama') == True\n"
            "assert is_palindrome('race a car') == False\n"
            "assert is_palindrome('') == True\n"
            "test_passed = True\n",
        ),
        (
            "flatten_list",
            TaskDifficulty.EASY,
            "Write a function flatten(lst) that flattens a nested list. "
            "flatten([1, [2, [3, 4], 5], 6]) == [1, 2, 3, 4, 5, 6]",
            "exec(output)\n"
            "assert flatten([1, [2, [3, 4], 5], 6]) == [1, 2, 3, 4, 5, 6]\n"
            "assert flatten([]) == []\n"
            "assert flatten([[1], [2], [3]]) == [1, 2, 3]\n"
            "test_passed = True\n",
        ),
        (
            "two_sum",
            TaskDifficulty.EASY,
            "Write a function two_sum(nums, target) that returns indices of "
            "two numbers that add up to target. "
            "two_sum([2, 7, 11, 15], 9) should return (0, 1) or [0, 1].",
            "exec(output)\n"
            "result = two_sum([2, 7, 11, 15], 9)\n"
            "assert sorted(result) == [0, 1]\n"
            "result2 = two_sum([3, 2, 4], 6)\n"
            "assert sorted(result2) == [1, 2]\n"
            "test_passed = True\n",
        ),
        (
            "roman_to_int",
            TaskDifficulty.MEDIUM,
            "Write a function roman_to_int(s) that converts a Roman numeral "
            "string to an integer. "
            "roman_to_int('MCMXCIV') == 1994",
            "exec(output)\n"
            "assert roman_to_int('III') == 3\n"
            "assert roman_to_int('IV') == 4\n"
            "assert roman_to_int('IX') == 9\n"
            "assert roman_to_int('MCMXCIV') == 1994\n"
            "test_passed = True\n",
        ),
        (
            "matrix_multiply",
            TaskDifficulty.MEDIUM,
            "Write a function matrix_multiply(a, b) that multiplies two 2D "
            "matrices represented as lists of lists. "
            "matrix_multiply([[1,2],[3,4]], [[5,6],[7,8]]) == [[19,22],[43,50]]",
            "exec(output)\n"
            "assert matrix_multiply([[1,2],[3,4]], [[5,6],[7,8]]) == [[19,22],[43,50]]\n"
            "assert matrix_multiply([[1]], [[2]]) == [[2]]\n"
            "test_passed = True\n",
        ),
        (
            "group_anagrams",
            TaskDifficulty.MEDIUM,
            "Write a function group_anagrams(strs) that groups anagrams "
            "together. group_anagrams(['eat','tea','tan','ate','nat','bat']) "
            "should return groups: [['eat','tea','ate'], ['tan','nat'], ['bat']] "
            "(order within groups doesn't matter).",
            "exec(output)\n"
            "result = group_anagrams(['eat','tea','tan','ate','nat','bat'])\n"
            "sorted_result = [sorted(g) for g in result]\n"
            "sorted_result.sort()\n"
            "assert sorted_result == [['bat'], ['ant', 'nat', 'tan'], ['ate', 'eat', 'tea']]\n"
            "test_passed = True\n",
        ),
        (
            "binary_search",
            TaskDifficulty.EASY,
            "Write a function binary_search(arr, target) that returns the "
            "index of target in a sorted list, or -1 if not found. "
            "binary_search([1, 3, 5, 7, 9], 5) == 2",
            "exec(output)\n"
            "assert binary_search([1, 3, 5, 7, 9], 5) == 2\n"
            "assert binary_search([1, 3, 5, 7, 9], 6) == -1\n"
            "assert binary_search([], 1) == -1\n"
            "test_passed = True\n",
        ),
        (
            "merge_sorted_lists",
            TaskDifficulty.EASY,
            "Write a function merge_sorted(a, b) that merges two sorted "
            "lists into one sorted list. "
            "merge_sorted([1, 3, 5], [2, 4, 6]) == [1, 2, 3, 4, 5, 6]",
            "exec(output)\n"
            "assert merge_sorted([1, 3, 5], [2, 4, 6]) == [1, 2, 3, 4, 5, 6]\n"
            "assert merge_sorted([], [1, 2]) == [1, 2]\n"
            "assert merge_sorted([1], []) == [1]\n"
            "test_passed = True\n",
        ),
        (
            "longest_common_prefix",
            TaskDifficulty.EASY,
            "Write a function longest_common_prefix(strs) that finds the "
            "longest common prefix among a list of strings. "
            "longest_common_prefix(['flower', 'flow', 'flight']) == 'fl'",
            "exec(output)\n"
            "assert longest_common_prefix(['flower', 'flow', 'flight']) == 'fl'\n"
            "assert longest_common_prefix(['dog', 'racecar', 'car']) == ''\n"
            "assert longest_common_prefix(['a']) == 'a'\n"
            "test_passed = True\n",
        ),
        (
            "valid_parentheses",
            TaskDifficulty.EASY,
            "Write a function is_valid(s) that checks if parentheses "
            "are balanced. Supports '()', '[]', '{}'. "
            "is_valid('()[]{}') == True, is_valid('(]') == False",
            "exec(output)\n"
            "assert is_valid('()[]{}') == True\n"
            "assert is_valid('(]') == False\n"
            "assert is_valid('{[]}') == True\n"
            "assert is_valid('([)]') == False\n"
            "test_passed = True\n",
        ),
        (
            "count_primes",
            TaskDifficulty.MEDIUM,
            "Write a function count_primes(n) that counts the number of "
            "prime numbers less than n using the Sieve of Eratosthenes. "
            "count_primes(10) == 4 (primes: 2, 3, 5, 7)",
            "exec(output)\n"
            "assert count_primes(10) == 4\n"
            "assert count_primes(2) == 0\n"
            "assert count_primes(20) == 8\n"
            "test_passed = True\n",
        ),
    ]

    for name, difficulty, prompt, test_code in tasks:
        suite.add_task(
            BenchmarkTask(
                name=name,
                category="code_gen",
                difficulty=difficulty,
                prompt=prompt,
                test_code=test_code,
                eval_metric=EvalMetric.TESTS_PASS,
                time_limit_seconds=60,
            )
        )

    logger.info(f"Created MBPP suite with {len(suite.tasks)} tasks")
    return suite
