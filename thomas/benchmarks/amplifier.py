"""Amplification scorer — measures how much Thomas boosts model performance.

Compares raw model results vs Thomas-augmented results to quantify
the value Thomas adds as an execution layer.
"""

import logging
from collections import defaultdict

from thomas.benchmarks.types import BenchmarkResult, RunMode

logger = logging.getLogger(__name__)


class AmplificationScorer:
    """Calculates amplification metrics from benchmark results.

    Compares RAW_MODEL vs THOMAS_FULL results to quantify how much
    Thomas improves a model's performance.
    """

    def score(self, results: list[BenchmarkResult]) -> dict:
        """Calculate comprehensive amplification metrics.

        Args:
            results: All benchmark results (must include both run modes)

        Returns:
            Dictionary with amplification metrics
        """
        raw = [r for r in results if r.run_mode == RunMode.RAW_MODEL]
        thomas = [r for r in results if r.run_mode in (RunMode.THOMAS_FULL, RunMode.THOMAS_BASIC)]

        if not raw or not thomas:
            return {"error": "Need both RAW_MODEL and THOMAS results"}

        raw_by_task = {r.task_id: r for r in raw}
        thomas_by_task = {r.task_id: r for r in thomas}

        # Overall pass rates
        raw_pass = sum(1 for r in raw if r.passed) / len(raw) if raw else 0
        thomas_pass = sum(1 for r in thomas if r.passed) / len(thomas) if thomas else 0

        # Average scores
        raw_avg = sum(r.score for r in raw) / len(raw) if raw else 0
        thomas_avg = sum(r.score for r in thomas) / len(thomas) if thomas else 0

        # Amplification factor
        amp_factor = thomas_avg / raw_avg if raw_avg > 0 else float("inf")

        # Per-task deltas
        task_deltas = []
        for tid in raw_by_task:
            if tid in thomas_by_task:
                delta = thomas_by_task[tid].score - raw_by_task[tid].score
                task_deltas.append(
                    {
                        "task_id": tid,
                        "task_name": raw_by_task[tid].task_name,
                        "raw_score": raw_by_task[tid].score,
                        "thomas_score": thomas_by_task[tid].score,
                        "delta": delta,
                        "improved": delta > 0,
                    }
                )

        improved = sum(1 for d in task_deltas if d["improved"])
        regressed = sum(1 for d in task_deltas if d["delta"] < 0)
        unchanged = sum(1 for d in task_deltas if d["delta"] == 0)

        return {
            "overall": {
                "raw_pass_rate": round(raw_pass, 4),
                "thomas_pass_rate": round(thomas_pass, 4),
                "pass_rate_lift": round(thomas_pass - raw_pass, 4),
                "raw_avg_score": round(raw_avg, 4),
                "thomas_avg_score": round(thomas_avg, 4),
                "score_lift": round(thomas_avg - raw_avg, 4),
                "amplification_factor": round(amp_factor, 2),
            },
            "task_analysis": {
                "total_tasks": len(task_deltas),
                "improved": improved,
                "regressed": regressed,
                "unchanged": unchanged,
                "improvement_rate": round(improved / len(task_deltas), 4) if task_deltas else 0,
            },
            "per_task": task_deltas,
            "by_category": self._by_category(results),
            "by_difficulty": self._by_difficulty(results),
            "by_model": self._by_model(results),
        }

    def _by_category(self, results: list[BenchmarkResult]) -> dict:
        """Break down amplification by task category."""
        categories: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"raw": [], "thomas": []})
        for r in results:
            cat = r.eval_details.get("category", r.task_name.split("_")[0])
            if r.run_mode == RunMode.RAW_MODEL:
                categories[cat]["raw"].append(r.score)
            else:
                categories[cat]["thomas"].append(r.score)

        breakdown = {}
        for cat, scores in categories.items():
            raw_avg = sum(scores["raw"]) / len(scores["raw"]) if scores["raw"] else 0
            thomas_avg = sum(scores["thomas"]) / len(scores["thomas"]) if scores["thomas"] else 0
            breakdown[cat] = {
                "raw_avg": round(raw_avg, 4),
                "thomas_avg": round(thomas_avg, 4),
                "lift": round(thomas_avg - raw_avg, 4),
            }
        return breakdown

    def _by_difficulty(self, results: list[BenchmarkResult]) -> dict:
        """Break down amplification by difficulty level."""
        by_diff: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"raw": [], "thomas": []})

        # We don't have difficulty in result, use task_name heuristic
        for r in results:
            diff = "unknown"
            if r.run_mode == RunMode.RAW_MODEL:
                by_diff[diff]["raw"].append(r.score)
            else:
                by_diff[diff]["thomas"].append(r.score)

        breakdown = {}
        for diff, scores in by_diff.items():
            raw_avg = sum(scores["raw"]) / len(scores["raw"]) if scores["raw"] else 0
            thomas_avg = sum(scores["thomas"]) / len(scores["thomas"]) if scores["thomas"] else 0
            breakdown[diff] = {
                "raw_avg": round(raw_avg, 4),
                "thomas_avg": round(thomas_avg, 4),
                "lift": round(thomas_avg - raw_avg, 4),
            }
        return breakdown

    def _by_model(self, results: list[BenchmarkResult]) -> dict:
        """Break down amplification by model."""
        by_model: dict[str, dict[str, list[float]]] = defaultdict(lambda: {"raw": [], "thomas": []})
        for r in results:
            if r.run_mode == RunMode.RAW_MODEL:
                by_model[r.model_name]["raw"].append(r.score)
            else:
                by_model[r.model_name]["thomas"].append(r.score)

        breakdown = {}
        for model, scores in by_model.items():
            raw_avg = sum(scores["raw"]) / len(scores["raw"]) if scores["raw"] else 0
            thomas_avg = sum(scores["thomas"]) / len(scores["thomas"]) if scores["thomas"] else 0
            breakdown[model] = {
                "raw_avg": round(raw_avg, 4),
                "thomas_avg": round(thomas_avg, 4),
                "lift": round(thomas_avg - raw_avg, 4),
                "amplification": round(thomas_avg / raw_avg, 2) if raw_avg > 0 else 0,
            }
        return breakdown

    def format_summary(self, metrics: dict) -> str:
        """Format metrics into a human-readable summary.

        Args:
            metrics: Output from score()

        Returns:
            Formatted string
        """
        if "error" in metrics:
            return f"Error: {metrics['error']}"

        o = metrics["overall"]
        t = metrics["task_analysis"]

        lines = [
            "=" * 60,
            "  THOMAS AMPLIFICATION REPORT",
            "=" * 60,
            "",
            f"  Raw Model Pass Rate:    {o['raw_pass_rate']:.1%}",
            f"  Thomas Pass Rate:       {o['thomas_pass_rate']:.1%}",
            f"  Pass Rate Lift:         +{o['pass_rate_lift']:.1%}",
            "",
            f"  Raw Model Avg Score:    {o['raw_avg_score']:.3f}",
            f"  Thomas Avg Score:       {o['thomas_avg_score']:.3f}",
            f"  Score Lift:             +{o['score_lift']:.3f}",
            f"  Amplification Factor:   {o['amplification_factor']}x",
            "",
            f"  Tasks Improved:         {t['improved']}/{t['total_tasks']}",
            f"  Tasks Regressed:        {t['regressed']}/{t['total_tasks']}",
            f"  Tasks Unchanged:        {t['unchanged']}/{t['total_tasks']}",
            f"  Improvement Rate:       {t['improvement_rate']:.1%}",
            "",
        ]

        # Per-model breakdown
        if metrics.get("by_model"):
            lines.append("  Per-Model Amplification:")
            for model, data in metrics["by_model"].items():
                lines.append(
                    f"    {model}: {data['raw_avg']:.3f} -> " f"{data['thomas_avg']:.3f} ({data['amplification']}x)"
                )
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)
