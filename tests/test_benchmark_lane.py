from __future__ import annotations

from pathlib import Path

from thomas.benchmarks.benchmark_lane import get_benchmark_context, resolve_benchmark_root


def test_resolve_benchmark_root_requires_output_benchmarks(tmp_path: Path) -> None:
    repo_root = tmp_path
    allowed = repo_root / "output" / "benchmarks" / "snake" / "run-1" / "thomas"
    allowed.mkdir(parents=True)
    blocked = repo_root / "output" / "other" / "snake"
    blocked.mkdir(parents=True)

    resolved_allowed, allowed_error = resolve_benchmark_root(repo_root, str(allowed))
    resolved_blocked, blocked_error = resolve_benchmark_root(repo_root, str(blocked))

    assert resolved_allowed == allowed.resolve()
    assert allowed_error is None
    assert resolved_blocked is None
    assert blocked_error is not None


def test_get_benchmark_context_validates_required_env(tmp_path: Path) -> None:
    repo_root = tmp_path
    root = repo_root / "output" / "benchmarks" / "snake" / "run-1" / "thomas"
    root.mkdir(parents=True)
    context, error = get_benchmark_context(
        repo_root,
        env={
            "THOMAS_BENCHMARK_MODE": "1",
            "THOMAS_BENCHMARK_RUN_ID": "run-1",
            "THOMAS_BENCHMARK_REASON": "snake benchmark",
            "THOMAS_BENCHMARK_ROOT": str(root),
        },
    )

    assert error is None
    assert context is not None
    assert context["lane"] == "benchmark"
    assert context["root"] == str(root.resolve())
