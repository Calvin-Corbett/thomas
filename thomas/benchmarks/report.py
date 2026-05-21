"""Benchmark report generator.

Creates human-readable and machine-parseable reports from benchmark
results, with support for multiple output formats.
"""

import json
import logging
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from thomas.benchmarks.types import BenchmarkResult, RunMode

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class BenchmarkReport:
    """Generates formatted benchmark reports.

    Supports text, JSON, and HTML output formats.
    """

    def __init__(self, results: list[BenchmarkResult] | None = None) -> None:
        self._results: list[BenchmarkResult] = results or []

    def add_results(self, results: list[BenchmarkResult]) -> None:
        """Add results to the report."""
        self._results.extend(results)

    def clear(self) -> None:
        """Clear all results."""
        self._results.clear()

    @property
    def result_count(self) -> int:
        """Number of results in this report."""
        return len(self._results)

    def summary(self) -> dict[str, Any]:
        """Generate a summary dictionary from results.

        Returns:
            Dictionary with aggregated metrics
        """
        if not self._results:
            return {"error": "No results to report"}

        by_mode: dict[str, list[BenchmarkResult]] = defaultdict(list)
        by_model: dict[str, list[BenchmarkResult]] = defaultdict(list)
        by_category: dict[str, list[BenchmarkResult]] = defaultdict(list)

        for r in self._results:
            by_mode[r.run_mode.value].append(r)
            by_model[r.model_name].append(r)
            cat = r.eval_details.get("category", r.task_name.split("_")[0])
            by_category[cat].append(r)

        return {
            "total_results": len(self._results),
            "total_passed": sum(1 for r in self._results if r.passed),
            "overall_pass_rate": self._pass_rate(self._results),
            "avg_score": self._avg_score(self._results),
            "avg_duration_ms": self._avg_duration(self._results),
            "by_mode": {mode: self._mode_summary(results) for mode, results in by_mode.items()},
            "by_model": {model: self._model_summary(results) for model, results in by_model.items()},
            "by_category": {cat: self._category_summary(results) for cat, results in by_category.items()},
        }

    def to_text(self) -> str:
        """Generate a plain-text report.

        Returns:
            Formatted text string
        """
        s = self.summary()
        if "error" in s:
            return f"Report Error: {s['error']}"

        lines = [
            "=" * 64,
            "  THOMAS BENCHMARK REPORT",
            f"  Generated: {_utc_now().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            "=" * 64,
            "",
            f"  Total Tasks:     {s['total_results']}",
            f"  Passed:          {s['total_passed']}",
            f"  Pass Rate:       {s['overall_pass_rate']:.1%}",
            f"  Avg Score:       {s['avg_score']:.4f}",
            f"  Avg Duration:    {s['avg_duration_ms']:.0f}ms",
            "",
            "-" * 64,
            "  RESULTS BY MODE",
            "-" * 64,
        ]

        for mode, data in s["by_mode"].items():
            lines.append(
                f"  {mode:20s}  pass={data['pass_rate']:.1%}  "
                f"avg={data['avg_score']:.3f}  "
                f"dur={data['avg_duration_ms']:.0f}ms"
            )

        lines.extend(["", "-" * 64, "  RESULTS BY MODEL", "-" * 64])

        for model, data in s["by_model"].items():
            lines.append(f"  {model:20s}  pass={data['pass_rate']:.1%}  avg={data['avg_score']:.3f}")

        lines.extend(["", "-" * 64, "  RESULTS BY CATEGORY", "-" * 64])

        for cat, data in s["by_category"].items():
            lines.append(f"  {cat:20s}  pass={data['pass_rate']:.1%}  avg={data['avg_score']:.3f}  n={data['count']}")

        lines.extend(["", "=" * 64])
        return "\n".join(lines)

    def to_json(self, indent: int = 2) -> str:
        """Generate a JSON report.

        Args:
            indent: JSON indentation level

        Returns:
            JSON string
        """
        data = {
            "report_type": "thomas_benchmark",
            "generated_at": _utc_now().isoformat(),
            "summary": self.summary(),
            "results": [r.to_dict() for r in self._results],
        }
        return json.dumps(data, indent=indent)

    def to_html(self) -> str:
        """Generate an HTML report.

        Returns:
            HTML string
        """
        s = self.summary()
        if "error" in s:
            return f"<html><body><p>{s['error']}</p></body></html>"

        rows = ""
        for r in self._results:
            status = "PASS" if r.passed else "FAIL"
            color = "#22c55e" if r.passed else "#ef4444"
            rows += (
                f"<tr>"
                f"<td>{r.task_name}</td>"
                f"<td>{r.model_name}</td>"
                f"<td>{r.run_mode.value}</td>"
                f'<td style="color:{color};font-weight:bold">{status}</td>'
                f"<td>{r.score:.3f}</td>"
                f"<td>{r.duration_ms:.0f}ms</td>"
                f"</tr>\n"
            )

        html = (
            "<!DOCTYPE html>\n<html>\n<head>\n"
            "<title>Thomas Benchmark Report</title>\n"
            "<style>\n"
            "body{font-family:system-ui;margin:2rem;background:#f8f9fa}\n"
            "h1{color:#1a1a2e}\n"
            "table{border-collapse:collapse;width:100%}\n"
            "th,td{border:1px solid #dee2e6;padding:8px 12px;text-align:left}\n"
            "th{background:#1a1a2e;color:white}\n"
            "tr:nth-child(even){background:#e9ecef}\n"
            ".metric{display:inline-block;margin:1rem;padding:1rem;"
            "background:white;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,.1)}\n"
            ".metric .value{font-size:2rem;font-weight:bold;color:#1a1a2e}\n"
            ".metric .label{color:#6c757d;font-size:.875rem}\n"
            "</style>\n</head>\n<body>\n"
            "<h1>Thomas Benchmark Report</h1>\n"
            f"<p>Generated: {_utc_now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>\n"
            '<div class="metrics">\n'
            f'<div class="metric"><div class="value">{s["total_results"]}</div>'
            f'<div class="label">Total Tasks</div></div>\n'
            f'<div class="metric"><div class="value">{s["overall_pass_rate"]:.1%}</div>'
            f'<div class="label">Pass Rate</div></div>\n'
            f'<div class="metric"><div class="value">{s["avg_score"]:.3f}</div>'
            f'<div class="label">Avg Score</div></div>\n'
            f'<div class="metric"><div class="value">{s["avg_duration_ms"]:.0f}ms</div>'
            f'<div class="label">Avg Duration</div></div>\n'
            "</div>\n"
            "<h2>All Results</h2>\n"
            "<table>\n<tr><th>Task</th><th>Model</th><th>Mode</th>"
            "<th>Status</th><th>Score</th><th>Duration</th></tr>\n"
            f"{rows}</table>\n"
            "</body>\n</html>"
        )
        return html

    def save(self, path: str, fmt: str = "text") -> str:
        """Save report to file.

        Args:
            path: Output file path
            fmt: Format - 'text', 'json', or 'html'

        Returns:
            Path of saved file
        """
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

        if fmt == "json":
            content = self.to_json()
        elif fmt == "html":
            content = self.to_html()
        else:
            content = self.to_text()

        with open(path, "w") as f:
            f.write(content)

        logger.info(f"Report saved to {path}")
        return path

    def comparison_table(self) -> str:
        """Generate a side-by-side raw vs Thomas comparison.

        Returns:
            Formatted comparison text
        """
        raw = [r for r in self._results if r.run_mode == RunMode.RAW_MODEL]
        thomas = [r for r in self._results if r.run_mode in (RunMode.THOMAS_FULL, RunMode.THOMAS_BASIC)]

        if not raw or not thomas:
            return "Need both RAW_MODEL and THOMAS results for comparison"

        raw_by_task = {r.task_id: r for r in raw}
        thomas_by_task = {r.task_id: r for r in thomas}

        lines = [
            f"{'Task':<30} {'Raw':>8} {'Thomas':>8} {'Delta':>8} {'Result':>8}",
            "-" * 66,
        ]

        for tid, r_raw in raw_by_task.items():
            r_thomas = thomas_by_task.get(tid)
            if not r_thomas:
                continue
            delta = r_thomas.score - r_raw.score
            symbol = "+" if delta > 0 else ("-" if delta < 0 else "=")
            lines.append(
                f"{r_raw.task_name:<30} {r_raw.score:>8.3f} "
                f"{r_thomas.score:>8.3f} {symbol}{abs(delta):>7.3f} "
                f"{'UP' if delta > 0 else ('DOWN' if delta < 0 else 'SAME'):>8}"
            )

        return "\n".join(lines)

    # ── Private helpers ──────────────────────────────────────

    @staticmethod
    def _pass_rate(results: list[BenchmarkResult]) -> float:
        if not results:
            return 0.0
        return sum(1 for r in results if r.passed) / len(results)

    @staticmethod
    def _avg_score(results: list[BenchmarkResult]) -> float:
        if not results:
            return 0.0
        return sum(r.score for r in results) / len(results)

    @staticmethod
    def _avg_duration(results: list[BenchmarkResult]) -> float:
        if not results:
            return 0.0
        return sum(r.duration_ms for r in results) / len(results)

    def _mode_summary(self, results: list[BenchmarkResult]) -> dict:
        return {
            "count": len(results),
            "pass_rate": self._pass_rate(results),
            "avg_score": round(self._avg_score(results), 4),
            "avg_duration_ms": round(self._avg_duration(results), 1),
        }

    def _model_summary(self, results: list[BenchmarkResult]) -> dict:
        return {
            "count": len(results),
            "pass_rate": self._pass_rate(results),
            "avg_score": round(self._avg_score(results), 4),
        }

    def _category_summary(self, results: list[BenchmarkResult]) -> dict:
        return {
            "count": len(results),
            "pass_rate": self._pass_rate(results),
            "avg_score": round(self._avg_score(results), 4),
        }
