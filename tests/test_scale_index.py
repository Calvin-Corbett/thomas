"""CAP-145: monorepo-scale performance.

Proves the exact acceptance line: a 10x scaling benchmark backed by a sub-linear
posting-list index and build-graph partitioning. Specifically:

* the inverted index returns correct hits;
* query WORK (postings touched) at 10x corpus is far below 10x the 1x work
  (sub-linear -- the ratio is asserted);
* the build graph computes the correct reverse-dependency partition for a
  changed file;
* the published benchmark report has the four scale points plus a sub-linear
  scaling exponent;
* everything is deterministic (identical run to run).
"""

from __future__ import annotations

from thomas.core.scale_index import (
    SUBLINEAR_EXPONENT,
    BenchmarkReport,
    BuildGraph,
    InvertedIndex,
    run_benchmark,
    synthesize_corpus,
)

# ---------------------------------------------------------------------------
# 1. Inverted index returns correct hits, cost scales with matches
# ---------------------------------------------------------------------------


def test_inverted_index_returns_correct_hits() -> None:
    idx = InvertedIndex()
    idx.index_corpus(
        {
            "a.py": "def alpha():\n    return payment_token\n",
            "b.py": "def beta():\n    return unrelated_widget\n",
            "c.py": "def gamma():\n    return payment_token_v2\n",
        }
    )
    # 'payment_token' whole-token appears in a.py and c.py (c has payment_token_v2
    # -> tokenizes to 'payment_token_v2', a distinct token), so only a.py.
    result = idx.query("payment_token")
    assert result.hits == ["a.py"]

    # AND-query: docs containing every term (identifiers are single tokens).
    both = idx.query(["def", "unrelated_widget"])
    assert both.hits == ["b.py"]

    # A missing term yields no hits but still reports the baseline (full-scan N).
    miss = idx.query("nonexistent_symbol")
    assert miss.hits == []
    assert miss.baseline == 3


def test_symbol_query_finds_defining_files() -> None:
    idx = InvertedIndex()
    idx.index_corpus(
        {
            "svc.py": "class PaymentService:\n    def charge(self):\n        return 1\n",
            "other.py": "def helper():\n    return 0\n",
        }
    )
    assert idx.symbol_query("PaymentService").hits == ["svc.py"]
    assert idx.symbol_query("charge").hits == ["svc.py"]
    assert idx.symbol_query("helper").hits == ["other.py"]


def test_query_work_scales_with_matches_not_corpus() -> None:
    # A rare needle in one doc of a large corpus: work == 1 posting, while a
    # naive full scan (baseline) would read every document.
    corpus = {f"f{i}.py": f"def fn_{i}():\n    return common_token\n" for i in range(50)}
    corpus["needle.py"] = "def needle():\n    return zqxjrare_marker\n"
    idx = InvertedIndex()
    idx.index_corpus(corpus)

    result = idx.query("zqxjrare_marker")
    assert result.hits == ["needle.py"]
    assert result.work == 1  # touched exactly one posting
    assert result.baseline == 51  # a full scan would read all docs
    assert result.work < result.baseline


# ---------------------------------------------------------------------------
# 2. Build-graph partitioning -- correct reverse-dependency closure
# ---------------------------------------------------------------------------


def test_build_graph_reverse_dep_partition_for_changed_file() -> None:
    corpus = synthesize_corpus(1)
    graph = BuildGraph()
    graph.add_corpus(corpus)

    # cluster0/core is imported by util_a and util_b, which are imported by app.
    partition = graph.impacted_partition("repo/cluster0/core.py")
    assert partition == [
        "repo/cluster0/app.py",
        "repo/cluster0/core.py",
        "repo/cluster0/util_a.py",
        "repo/cluster0/util_b.py",
    ]

    # Direct dependents of core are exactly the two utils.
    assert graph.direct_dependents("repo/cluster0/core.py") == [
        "repo/cluster0/util_a.py",
        "repo/cluster0/util_b.py",
    ]

    # A leaf (app) is imported by nothing -> partition is just itself.
    assert graph.impacted_partition("repo/cluster0/app.py") == ["repo/cluster0/app.py"]

    # Clusters are independent: changing cluster0 never touches cluster1.
    assert not any(p.startswith("repo/cluster1/") for p in partition)


def test_partition_stays_bounded_as_repo_grows() -> None:
    sizes = []
    for scale in (1, 2, 5, 10):
        corpus = synthesize_corpus(scale)
        graph = BuildGraph()
        graph.add_corpus(corpus)
        sizes.append(len(graph.impacted_partition("repo/cluster0/core.py")))
    # Constant partition (4 files) even as the corpus grows 10x.
    assert sizes == [4, 4, 4, 4]


# ---------------------------------------------------------------------------
# 3. Scaling benchmark report -- four points + sub-linear exponent
# ---------------------------------------------------------------------------


def test_benchmark_report_has_four_points_and_is_sublinear() -> None:
    report = run_benchmark()
    assert isinstance(report, BenchmarkReport)

    # Exactly the four required scale points.
    scales = [p.scale for p in report.points]
    assert scales == [1, 2, 5, 10]

    # Corpus really grows 10x (16 -> 160 files).
    assert report.points[0].corpus_size == 16
    assert report.points[-1].corpus_size == 160
    assert report.corpus_size_ratio == 10.0

    # Query work at 10x is FAR below 10x the 1x work -> sub-linear.
    first, last = report.points[0], report.points[-1]
    assert last.query_work == last.needle_matches  # work == matches touched
    assert report.query_work_ratio < report.corpus_size_ratio / 2.0
    assert report.query_work_ratio < 5.0

    # Computed scaling exponents are sub-linear.
    assert report.query_scaling_exponent < SUBLINEAR_EXPONENT
    assert report.partition_scaling_exponent < SUBLINEAR_EXPONENT
    # Partition scope is flat (constant closure) -> exponent ~ 0.
    assert report.partition_scaling_exponent == 0.0
    assert report.sublinear is True

    # Each point: index work strictly beats the naive full-scan baseline.
    for point in report.points:
        assert point.query_work < point.baseline_work


def test_benchmark_query_hits_are_correct_at_each_scale() -> None:
    # The needle query at each scale returns exactly the needle 'app.py' files,
    # and the number of them grows sub-linearly (~sqrt of clusters).
    for scale in (1, 2, 5, 10):
        corpus = synthesize_corpus(scale)
        idx = InvertedIndex()
        idx.index_corpus(corpus)
        result = idx.query("zqxjneedle")
        assert all(p.endswith("/app.py") for p in result.hits)
        assert result.hits == sorted(result.hits)
        assert len(result.hits) == result.work
    # matches: isqrt(4)=2, isqrt(8)=2, isqrt(20)=4, isqrt(40)=6
    counts = []
    for scale in (1, 2, 5, 10):
        idx = InvertedIndex()
        idx.index_corpus(synthesize_corpus(scale))
        counts.append(idx.query("zqxjneedle").work)
    assert counts == [2, 2, 4, 6]


# ---------------------------------------------------------------------------
# 4. Determinism -- identical corpus, work, hits, and report run to run
# ---------------------------------------------------------------------------


def test_determinism_of_corpus_query_and_report() -> None:
    assert synthesize_corpus(5) == synthesize_corpus(5)

    idx_a = InvertedIndex()
    idx_a.index_corpus(synthesize_corpus(5))
    idx_b = InvertedIndex()
    idx_b.index_corpus(synthesize_corpus(5))
    ra, rb = idx_a.query("zqxjneedle"), idx_b.query("zqxjneedle")
    assert (ra.hits, ra.work, ra.baseline) == (rb.hits, rb.work, rb.baseline)

    report_a = run_benchmark().as_dict()
    report_b = run_benchmark().as_dict()
    assert report_a == report_b
