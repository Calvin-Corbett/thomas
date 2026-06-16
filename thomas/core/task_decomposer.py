"""Pre-dispatch task analysis: clarity, complexity, recommended Effort, and whether
an Intent Review is warranted.

Step 3 of the control plane. This runs ONLY for explicit task dispatch (not every
chat message), and it is ADVISORY: it populates task metadata and *recommends* an
Effort, but never overrides the user's choice. The Exhaustive pipeline (later step)
uses ``needs_intent_review`` to gate the front intent-review — catching ambiguous
tasks before an expensive crew is staffed.

The scoring is a transparent heuristic (keyword + length signals) so the reason a
task was flagged is debuggable; a model classifier can refine it later.
"""

from __future__ import annotations

from dataclasses import dataclass

# Signals that a task is well-specified (raise clarity).
_CLARITY_SIGNALS = (
    "should",
    "must",
    "so that",
    "given",
    "when ",
    "expected",
    "acceptance",
    "input",
    "output",
    "return",
    "constraint",
    "spec",
    "requirement",
    "step",
)
# Signals of ambiguity (lower clarity).
_VAGUE_SIGNALS = (
    "something",
    "somehow",
    "maybe",
    " etc",
    "stuff",
    "whatever",
    "or something",
    "kind of",
    "fix it",
    "make it better",
    "improve it",
)
# Signals of structural complexity.
_COMPLEX_SIGNALS = (
    "architecture",
    "migrate",
    "refactor",
    "across",
    "multiple",
    "integrate",
    "end to end",
    "end-to-end",
    "system",
    "pipeline",
    "scale",
    "concurren",
    "distributed",
)

# Clarity at/below this recommends an Intent Review before staffing.
INTENT_REVIEW_THRESHOLD = 50

_RECOMMENDED_EFFORT = {"simple": "brisk", "moderate": "diligent", "hard": "diligent"}


@dataclass(frozen=True)
class TaskAnalysis:
    clarity_score: int  # 0-100 (higher = clearer intent)
    complexity: str  # simple | moderate | hard
    recommended_effort: str  # brisk | diligent | exhaustive (advisory)
    needs_intent_review: bool


def _count_hits(text: str, signals: tuple[str, ...]) -> int:
    return sum(1 for s in signals if s in text)


def analyze_task(prompt: str) -> TaskAnalysis:
    """Analyze a task prompt; advisory only (never forces Effort choice)."""
    text = f" {str(prompt or '').lower()} "
    word_count = len(text.split())

    clarity = 50
    clarity += 8 * _count_hits(text, _CLARITY_SIGNALS)
    clarity -= 14 * _count_hits(text, _VAGUE_SIGNALS)
    if word_count < 4:
        clarity -= 25  # too terse to pin intent
    elif word_count >= 9:
        clarity += 10  # a fuller description reads as clearer
    clarity = max(0, min(100, clarity))

    complex_hits = _count_hits(text, _COMPLEX_SIGNALS)
    if complex_hits >= 2 or word_count > 40:
        complexity = "hard"
    elif complex_hits >= 1 or word_count > 15:
        complexity = "moderate"
    else:
        complexity = "simple"

    recommended = _RECOMMENDED_EFFORT[complexity]
    # Ambiguous tasks OR hard tasks warrant an intent double-check before staffing.
    needs_review = clarity < INTENT_REVIEW_THRESHOLD or complexity == "hard"
    return TaskAnalysis(
        clarity_score=clarity,
        complexity=complexity,
        recommended_effort=recommended,
        needs_intent_review=needs_review,
    )
