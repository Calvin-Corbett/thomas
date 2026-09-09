"""MT-Bench style multi-turn conversation benchmark.

Tests model ability to handle multi-turn conversations with
follow-up questions, context tracking, and instruction following.
"""

import logging

from thomas.benchmarks.types import (
    BenchmarkSuite,
    BenchmarkTask,
    EvalMetric,
    TaskDifficulty,
)

logger = logging.getLogger(__name__)


def create_mt_bench_suite() -> BenchmarkSuite:
    """Create an MT-Bench style multi-turn benchmark suite.

    Returns:
        Suite with multi-turn conversation tasks
    """
    suite = BenchmarkSuite(
        name="mt_bench",
        description="Multi-turn conversation benchmark (MT-Bench style)",
        version="1.0",
    )

    # ── Writing / Creative Tasks ─────────────────────────────
    suite.add_task(
        BenchmarkTask(
            name="mt_creative_story",
            category="writing",
            difficulty=TaskDifficulty.MEDIUM,
            prompt=(
                "Write a short story (100-200 words) about a robot discovering "
                "what it means to be creative. The story should have a clear "
                "beginning, middle, and end."
            ),
            eval_metric=EvalMetric.PARTIAL_CREDIT,
            expected_output="robot creative story beginning middle end",
            time_limit_seconds=120,
            tags=["writing", "creative"],
        )
    )

    suite.add_task(
        BenchmarkTask(
            name="mt_email_professional",
            category="writing",
            difficulty=TaskDifficulty.EASY,
            prompt=(
                "Write a professional email declining a meeting invitation "
                "for Thursday at 2pm because you have a conflict. Be polite, "
                "suggest an alternative time (Friday morning), and keep it "
                "under 100 words."
            ),
            eval_metric=EvalMetric.PARTIAL_CREDIT,
            expected_output="meeting Thursday conflict Friday alternative polite",
            time_limit_seconds=60,
            tags=["writing", "professional"],
        )
    )

    # ── Reasoning Tasks ──────────────────────────────────────
    suite.add_task(
        BenchmarkTask(
            name="mt_logical_deduction",
            category="reasoning",
            difficulty=TaskDifficulty.MEDIUM,
            prompt=(
                "Three friends (Alice, Bob, Charlie) each have a pet "
                "(cat, dog, fish). Alice doesn't have the dog. Bob doesn't "
                "have the cat or the fish. Charlie doesn't have the dog. "
                "Who has which pet?"
            ),
            expected_output="Bob has the dog",
            eval_metric=EvalMetric.CONTAINS,
            time_limit_seconds=60,
            tags=["reasoning", "logic"],
        )
    )

    suite.add_task(
        BenchmarkTask(
            name="mt_causal_reasoning",
            category="reasoning",
            difficulty=TaskDifficulty.HARD,
            prompt=(
                "A factory produces widgets. When temperature rises above "
                "30C, defect rate increases from 2% to 8%. The factory runs "
                "24/7 and temperature exceeds 30C for 6 hours daily. "
                "If the factory produces 1000 widgets per hour, how many "
                "additional defective widgets are produced per day due to "
                "the heat? Show your reasoning."
            ),
            expected_output="360",
            eval_metric=EvalMetric.CONTAINS,
            time_limit_seconds=90,
            tags=["reasoning", "math"],
        )
    )

    # ── Coding Tasks ─────────────────────────────────────────
    suite.add_task(
        BenchmarkTask(
            name="mt_code_explain",
            category="coding",
            difficulty=TaskDifficulty.EASY,
            prompt=(
                "Explain what this code does in plain English, then suggest "
                "one improvement:\n\n"
                "```python\n"
                "def f(n):\n"
                "    if n <= 1: return n\n"
                "    return f(n-1) + f(n-2)\n"
                "```"
            ),
            expected_output="fibonacci",
            eval_metric=EvalMetric.CONTAINS,
            time_limit_seconds=60,
            tags=["coding", "explanation"],
        )
    )

    suite.add_task(
        BenchmarkTask(
            name="mt_code_debug",
            category="coding",
            difficulty=TaskDifficulty.MEDIUM,
            prompt=(
                "This code is supposed to reverse a string, but it has a bug. "
                "Find and fix it:\n\n"
                "```python\n"
                "def reverse_string(s):\n"
                "    result = ''\n"
                "    for i in range(len(s), 0, -1):\n"
                "        result += s[i]\n"
                "    return result\n"
                "```\n\n"
                "Explain the bug and provide the corrected code."
            ),
            expected_output="s[i-1]",
            eval_metric=EvalMetric.CONTAINS,
            time_limit_seconds=60,
            tags=["coding", "debugging"],
        )
    )

    # ── Extraction / Analysis Tasks ──────────────────────────
    suite.add_task(
        BenchmarkTask(
            name="mt_data_extraction",
            category="extraction",
            difficulty=TaskDifficulty.MEDIUM,
            prompt=(
                "Extract all the key facts from this text and present them "
                "as a structured list:\n\n"
                "'TechCorp, founded in 2015 by Jane Smith in San Francisco, "
                "reported revenue of $50M in 2024. The company has 200 "
                "employees across 3 offices. Their main product, CloudSync, "
                "serves 10,000 customers in 45 countries.'"
            ),
            expected_output="TechCorp",
            eval_metric=EvalMetric.PARTIAL_CREDIT,
            time_limit_seconds=60,
            tags=["extraction", "analysis"],
        )
    )

    suite.add_task(
        BenchmarkTask(
            name="mt_summarization",
            category="extraction",
            difficulty=TaskDifficulty.EASY,
            prompt=(
                "Summarize the following in exactly one sentence (max 25 words):\n\n"
                "'Machine learning models require large amounts of training "
                "data to achieve good performance. This data needs to be "
                "cleaned, labeled, and properly formatted. The quality of "
                "the training data directly impacts model accuracy. Poor "
                "data leads to poor models, regardless of the architecture "
                "used. Data augmentation techniques can help when real data "
                "is limited.'"
            ),
            eval_metric=EvalMetric.PARTIAL_CREDIT,
            expected_output="data quality training model performance",
            time_limit_seconds=60,
            tags=["extraction", "summarization"],
        )
    )

    # ── Instruction Following ────────────────────────────────
    suite.add_task(
        BenchmarkTask(
            name="mt_format_constraint",
            category="instruction_following",
            difficulty=TaskDifficulty.MEDIUM,
            prompt=(
                "List exactly 5 programming languages. Format each as "
                "'N. Language - Year_created'. Use only languages created "
                "before 2000. Sort by year ascending."
            ),
            eval_metric=EvalMetric.PARTIAL_CREDIT,
            expected_output="1. 2. 3. 4. 5.",
            time_limit_seconds=60,
            tags=["instruction_following"],
        )
    )

    suite.add_task(
        BenchmarkTask(
            name="mt_role_play",
            category="instruction_following",
            difficulty=TaskDifficulty.MEDIUM,
            prompt=(
                "You are a pirate captain. A crew member asks 'Captain, "
                "should we sail east or west?'. Respond in character, "
                "staying in pirate dialect for the entire response. "
                "Your answer should be under 75 words and include at least "
                "one 'arr' or 'matey'."
            ),
            eval_metric=EvalMetric.PARTIAL_CREDIT,
            expected_output="sail east west captain pirate",
            time_limit_seconds=60,
            tags=["instruction_following", "roleplay"],
        )
    )

    logger.info(f"Created MT-Bench suite with {len(suite.tasks)} tasks")
    return suite
