"""GPQA (Graduate-Level Google-Proof Q&A) benchmark suite.

Tests expert-level reasoning in science and domain knowledge
that cannot be easily looked up.
"""

import logging

from thomas.benchmarks.types import (
    BenchmarkSuite,
    BenchmarkTask,
    EvalMetric,
    TaskDifficulty,
)

logger = logging.getLogger(__name__)


def create_gpqa_suite() -> BenchmarkSuite:
    """Create a GPQA-style expert reasoning benchmark suite.

    Returns:
        Suite with graduate-level science questions
    """
    suite = BenchmarkSuite(
        name="gpqa",
        description="Graduate-level expert reasoning benchmark (GPQA style)",
        version="1.0",
    )

    tasks: list[tuple] = [
        # ── Physics ──────────────────────────────────────────
        (
            "physics_entropy",
            TaskDifficulty.HARD,
            "physics",
            "In an isothermal expansion of an ideal gas from volume V "
            "to 2V at temperature T, what is the change in entropy? "
            "Express in terms of n (moles) and R (gas constant).",
            "nR ln(2)",
        ),
        (
            "physics_uncertainty",
            TaskDifficulty.HARD,
            "physics",
            "If the position of an electron is measured with an "
            "uncertainty of 1 Angstrom (10^-10 m), what is the minimum "
            "uncertainty in its momentum? Express using h-bar.",
            "h-bar/2",
        ),
        (
            "physics_relativity",
            TaskDifficulty.EXPERT,
            "physics",
            "A spacecraft travels at 0.8c relative to Earth. How much "
            "time passes on the spacecraft for every 10 years on Earth? "
            "Use the Lorentz factor.",
            "6",
        ),
        # ── Chemistry ────────────────────────────────────────
        (
            "chemistry_orbital",
            TaskDifficulty.HARD,
            "chemistry",
            "How many radial nodes does a 3p orbital have? Use the formula: radial nodes = n - l - 1.",
            "1",
        ),
        (
            "chemistry_equilibrium",
            TaskDifficulty.HARD,
            "chemistry",
            "For the reaction N2 + 3H2 <-> 2NH3, if Kp = 0.5 at "
            "a certain temperature and we increase pressure, "
            "which direction does the equilibrium shift?",
            "right",
        ),
        (
            "chemistry_thermodynamics",
            TaskDifficulty.EXPERT,
            "chemistry",
            "Calculate the standard Gibbs free energy change for a "
            "reaction at 298 K where delta_H = -100 kJ/mol and "
            "delta_S = -200 J/(mol*K). Is the reaction spontaneous?",
            "-40.4",
        ),
        # ── Biology ──────────────────────────────────────────
        (
            "biology_genetics",
            TaskDifficulty.HARD,
            "biology",
            "In a dihybrid cross AaBb x AaBb, what fraction of "
            "offspring are expected to show both dominant phenotypes? "
            "Express as a fraction.",
            "9/16",
        ),
        (
            "biology_molecular",
            TaskDifficulty.HARD,
            "biology",
            "A mRNA strand has the sequence 5'-AUGCUAGGA-3'. "
            "What amino acid sequence does it code for? "
            "Use standard genetic code.",
            "Met-Leu-Gly",
        ),
        # ── Computer Science ─────────────────────────────────
        (
            "cs_complexity",
            TaskDifficulty.HARD,
            "computer_science",
            "What is the time complexity of finding the median of medians algorithm for selection? Express in Big-O.",
            "O(n)",
        ),
        (
            "cs_information_theory",
            TaskDifficulty.EXPERT,
            "computer_science",
            "A source emits symbols A (p=0.5), B (p=0.25), C (p=0.125), "
            "D (p=0.125). What is the Shannon entropy in bits?",
            "1.75",
        ),
        (
            "cs_graph_theory",
            TaskDifficulty.HARD,
            "computer_science",
            "A complete graph K_6 has how many edges? Use the formula n*(n-1)/2.",
            "15",
        ),
        # ── Mathematics ──────────────────────────────────────
        (
            "math_topology",
            TaskDifficulty.EXPERT,
            "mathematics",
            "What is the Euler characteristic of a torus? Use V - E + F for a standard triangulation.",
            "0",
        ),
        (
            "math_linear_algebra",
            TaskDifficulty.HARD,
            "mathematics",
            "What are the eigenvalues of the matrix [[2, 1], [0, 3]]?",
            "2 and 3",
        ),
    ]

    for name, difficulty, category, prompt, expected in tasks:
        suite.add_task(
            BenchmarkTask(
                name=name,
                category=category,
                difficulty=difficulty,
                prompt=(
                    f"Answer this expert-level question. Show your reasoning, "
                    f"then provide the final answer.\n\n{prompt}"
                ),
                expected_output=expected,
                eval_metric=EvalMetric.CONTAINS,
                time_limit_seconds=120,
                tags=["expert", category],
            )
        )

    logger.info(f"Created GPQA suite with {len(suite.tasks)} tasks")
    return suite
