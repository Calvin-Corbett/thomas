"""MATH and GSM8K benchmark suites.

Tests mathematical reasoning — from grade-school word problems
(GSM8K) to competition-level math (MATH).
"""

import logging

from thomas.benchmarks.types import (
    BenchmarkSuite,
    BenchmarkTask,
    EvalMetric,
    TaskDifficulty,
)

logger = logging.getLogger(__name__)


def create_math_suite() -> BenchmarkSuite:
    """Create a MATH competition-level benchmark suite.

    Returns:
        Suite with competition math problems
    """
    suite = BenchmarkSuite(
        name="math",
        description="Competition-level math benchmark (MATH style)",
        version="1.0",
    )

    tasks: list[tuple] = [
        (
            "algebra_linear",
            TaskDifficulty.EASY,
            "algebra",
            "Solve for x: 3x + 7 = 22. Provide just the numeric answer.",
            "5",
        ),
        (
            "algebra_quadratic",
            TaskDifficulty.MEDIUM,
            "algebra",
            "Find all real solutions to x^2 - 5x + 6 = 0. " "List the solutions separated by comma.",
            "2, 3",
        ),
        (
            "algebra_system",
            TaskDifficulty.MEDIUM,
            "algebra",
            "Solve the system: 2x + y = 7, x - y = 2. " "Give the answer as (x, y).",
            "(3, 1)",
        ),
        (
            "number_theory_gcd",
            TaskDifficulty.EASY,
            "number_theory",
            "What is the greatest common divisor of 48 and 18?",
            "6",
        ),
        (
            "number_theory_mod",
            TaskDifficulty.MEDIUM,
            "number_theory",
            "What is 7^100 mod 13? Use Fermat's little theorem.",
            "9",
        ),
        (
            "counting_combinations",
            TaskDifficulty.MEDIUM,
            "counting",
            "How many ways can you choose 3 items from 10? " "Calculate C(10, 3).",
            "120",
        ),
        (
            "counting_permutations",
            TaskDifficulty.EASY,
            "counting",
            "How many ways can 5 people stand in a line? Calculate 5!.",
            "120",
        ),
        (
            "geometry_triangle",
            TaskDifficulty.MEDIUM,
            "geometry",
            "A right triangle has legs of length 5 and 12. " "What is the length of the hypotenuse?",
            "13",
        ),
        (
            "geometry_circle",
            TaskDifficulty.EASY,
            "geometry",
            "A circle has radius 7. What is its area? " "Express as a multiple of pi (e.g., '49pi').",
            "49pi",
        ),
        (
            "probability_dice",
            TaskDifficulty.MEDIUM,
            "probability",
            "What is the probability of rolling a sum of 7 with two " "fair six-sided dice? Express as a fraction.",
            "1/6",
        ),
        (
            "probability_cards",
            TaskDifficulty.MEDIUM,
            "probability",
            "What is the probability of drawing 2 aces from a standard "
            "52-card deck (without replacement)? Express as a fraction.",
            "1/221",
        ),
        (
            "calculus_derivative",
            TaskDifficulty.HARD,
            "calculus",
            "Find the derivative of f(x) = x^3 * sin(x). " "Express in terms of x.",
            "3x^2*sin(x) + x^3*cos(x)",
        ),
        (
            "calculus_integral",
            TaskDifficulty.HARD,
            "calculus",
            "Evaluate the definite integral of x^2 from 0 to 3.",
            "9",
        ),
        (
            "sequences_arithmetic",
            TaskDifficulty.EASY,
            "sequences",
            "In an arithmetic sequence, a_1 = 3 and d = 5. " "What is a_10?",
            "48",
        ),
        (
            "sequences_geometric",
            TaskDifficulty.MEDIUM,
            "sequences",
            "A geometric sequence starts with 2, 6, 18, ... " "What is the sum of the first 5 terms?",
            "242",
        ),
    ]

    for name, difficulty, category, prompt, expected in tasks:
        suite.add_task(
            BenchmarkTask(
                name=name,
                category=category,
                difficulty=difficulty,
                prompt=prompt,
                expected_output=expected,
                eval_metric=EvalMetric.CONTAINS,
                time_limit_seconds=90,
                tags=["math"],
            )
        )

    logger.info(f"Created MATH suite with {len(suite.tasks)} tasks")
    return suite


def create_gsm8k_suite() -> BenchmarkSuite:
    """Create a GSM8K grade-school math benchmark suite.

    Returns:
        Suite with grade-school math word problems
    """
    suite = BenchmarkSuite(
        name="gsm8k",
        description="Grade-school math word problems (GSM8K style)",
        version="1.0",
    )

    tasks: list[tuple] = [
        (
            "gsm_shopping",
            TaskDifficulty.EASY,
            "Janet has 5 apples. She buys 3 more bags of apples with "
            "4 apples each. How many apples does she have now?",
            "17",
        ),
        (
            "gsm_speed",
            TaskDifficulty.EASY,
            "A train travels 60 miles per hour. How far does it travel " "in 2 hours and 30 minutes?",
            "150",
        ),
        (
            "gsm_discount",
            TaskDifficulty.EASY,
            "A shirt costs $40. It's on sale for 25% off. " "What is the sale price?",
            "30",
        ),
        (
            "gsm_multi_step",
            TaskDifficulty.MEDIUM,
            "Tom has 3 boxes. Each box has 5 bags. Each bag has 8 marbles. "
            "He gives away half of all the marbles. How many does he have left?",
            "60",
        ),
        (
            "gsm_ratio",
            TaskDifficulty.MEDIUM,
            "In a class, the ratio of boys to girls is 3:5. " "If there are 24 students total, how many are girls?",
            "15",
        ),
        (
            "gsm_interest",
            TaskDifficulty.MEDIUM,
            "Sarah deposits $1000 in a bank with 5% annual simple interest. "
            "How much money will she have after 3 years?",
            "1150",
        ),
        (
            "gsm_work_rate",
            TaskDifficulty.HARD,
            "Alice can paint a room in 6 hours. Bob can paint the same "
            "room in 4 hours. Working together, how many hours will it "
            "take them? Express as a fraction.",
            "12/5",
        ),
        (
            "gsm_profit",
            TaskDifficulty.MEDIUM,
            "A store buys items for $15 each and sells them for $25 each. "
            "If they sell 40 items but have to return 5 defective ones "
            "(refunding customers), what is the total profit?",
            "275",
        ),
        (
            "gsm_average",
            TaskDifficulty.EASY,
            "A student scored 85, 92, 78, 96, and 89 on five tests. " "What is the average score?",
            "88",
        ),
        (
            "gsm_distance",
            TaskDifficulty.MEDIUM,
            "A car drives 30 mph for 2 hours, then 50 mph for 3 hours. "
            "What is the average speed for the whole trip? "
            "Round to 1 decimal place.",
            "42",
        ),
    ]

    for name, difficulty, prompt, expected in tasks:
        suite.add_task(
            BenchmarkTask(
                name=name,
                category="word_problem",
                difficulty=difficulty,
                prompt=f"Solve this math problem step by step, then give " f"the final numeric answer.\n\n{prompt}",
                expected_output=expected,
                eval_metric=EvalMetric.CONTAINS,
                time_limit_seconds=60,
                tags=["math", "word_problem"],
            )
        )

    logger.info(f"Created GSM8K suite with {len(suite.tasks)} tasks")
    return suite
