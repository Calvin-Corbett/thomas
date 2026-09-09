"""Monorepo-scale performance primitives (CAP-145).

The incremental lexical index in :mod:`thomas.core.incremental_index` (CAP-015)
proves *immediacy* of a single edit. This module proves *scale*: that the cost
of answering a query and the cost of rebuilding after a change both grow **far
slower than the corpus**, so a repo can grow 10x without the tooling getting 10x
slower.

Three deterministic pieces, all stdlib-only (no embeddings, no threads, no
network, no wall-clock -- work is *counted*, not timed):

1. :class:`InvertedIndex` -- a sub-linear query index. Content is tokenized into
   an inverted **posting list** (``term -> sorted doc-ids``) and defined symbols
   (via :mod:`ast`) into a second posting map. A query is answered by touching
   only the posting lists of the query terms, so its cost is ``O(number of
   matches)``, independent of corpus size. Every query reports ``work`` (the
   number of postings actually touched) alongside ``baseline`` (the ``N`` docs a
   naive full scan would read), making sub-linearity measurable rather than
   asserted.

2. :class:`BuildGraph` -- an import reverse-dependency graph parsed from source
   ASTs. Given a changed file, :meth:`BuildGraph.impacted_partition` returns the
   minimal reverse-dependency closure -- the only files a build/test run has to
   touch. When the repo is partitioned into independent clusters, that closure
   stays bounded as the repo grows, so a build touches a partition, not the repo.

3. :func:`run_benchmark` -- synthesizes 1x/2x/5x/10x corpora, measures query work
   and partition size at each scale, and publishes a :class:`BenchmarkReport`
   with a computed **scaling exponent** (the log-log least-squares slope). An
   exponent below ``1.0`` is the proof of sub-linearity.

Everything is deterministic: the same scale yields the same corpus, the same
query yields the same work count and the same hits, run to run.
"""

from __future__ import annotations

import ast
import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

__all__ = [
    "InvertedIndex",
    "QueryResult",
    "BuildGraph",
    "ScalePoint",
    "BenchmarkReport",
    "synthesize_corpus",
    "run_benchmark",
    "SUBLINEAR_EXPONENT",
]

# A scaling exponent (log-log slope of work vs corpus size) strictly below this
# is what "sub-linear" means: query/build work grows slower than the corpus.
SUBLINEAR_EXPONENT = 1.0

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _tokenize(text: str) -> list[str]:
    """Lowercase identifier/word tokens, deterministic order (as they appear)."""
    return [m.group(0).lower() for m in _WORD_RE.finditer(text)]


def _path_to_module(path: str) -> str:
    """``repo/cluster0/core.py`` -> ``repo.cluster0.core`` (deterministic)."""
    norm = path.replace("\\", "/")
    if norm.endswith(".py"):
        norm = norm[: -len(".py")]
    if norm.endswith("/__init__"):
        norm = norm[: -len("/__init__")]
    return norm.strip("/").replace("/", ".")


# ---------------------------------------------------------------------------
# 1. Sub-linear query index -- inverted posting lists over files and symbols
# ---------------------------------------------------------------------------


@dataclass
class QueryResult:
    """Outcome of a query over :class:`InvertedIndex`.

    ``hits`` are matching paths (sorted). ``work`` is the number of postings the
    query touched -- the true cost of an inverted-index merge, scaling with the
    number of matches, not the corpus. ``baseline`` is ``N``: the documents a
    naive full-scan grep would have to read to answer the same query.
    """

    hits: list[str]
    work: int
    baseline: int


class InvertedIndex:
    """In-memory inverted index answering queries without a full corpus scan.

    A document is assigned a monotonically increasing integer id, so posting
    lists are naturally built in ascending order (no per-add sort needed). Two
    posting maps are maintained: one over content tokens (``term_postings``) and
    one over defined symbol names (``symbol_postings``, parsed via :mod:`ast`).
    """

    def __init__(self) -> None:
        self._paths: list[str] = []
        self._term_postings: dict[str, list[int]] = {}
        self._symbol_postings: dict[str, list[int]] = {}

    def __len__(self) -> int:
        return len(self._paths)

    def paths(self) -> list[str]:
        return list(self._paths)

    # -- indexing ---------------------------------------------------------

    def add_document(self, path: str, content: str) -> int:
        """Index one document; returns its assigned doc id.

        Postings are appended in ascending doc-id order and de-duplicated within
        a document, so each posting list stays sorted and unique.
        """
        doc_id = len(self._paths)
        self._paths.append(path)

        seen_terms: set[str] = set()
        for term in _tokenize(content):
            if term in seen_terms:
                continue
            seen_terms.add(term)
            self._term_postings.setdefault(term, []).append(doc_id)

        for symbol in self._extract_symbols(content):
            low = symbol.lower()
            postings = self._symbol_postings.setdefault(low, [])
            if not postings or postings[-1] != doc_id:
                postings.append(doc_id)
        return doc_id

    def index_corpus(self, corpus: dict[str, str]) -> int:
        """Index a ``path -> content`` mapping in sorted-path order (deterministic)."""
        count = 0
        for path in sorted(corpus):
            self.add_document(path, corpus[path])
            count += 1
        return count

    @staticmethod
    def _extract_symbols(content: str) -> list[str]:
        """Return top-level and nested def/class names defined in ``content``."""
        try:
            tree = ast.parse(content)
        except SyntaxError:
            # Non-Python or malformed content contributes no symbols; its tokens
            # are still indexed for the content posting list.
            return []
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.append(node.name)
        return names

    # -- retrieval --------------------------------------------------------

    def query(self, terms: Sequence[str] | str) -> QueryResult:
        """AND-query the content posting lists; cost scales with matches.

        Returns docs containing *every* query term. ``work`` counts the postings
        touched across the queried terms -- the merge cost -- which is bounded by
        the size of the matched posting lists, not by the corpus.
        """
        return self._query(self._term_postings, terms)

    def symbol_query(self, terms: Sequence[str] | str) -> QueryResult:
        """AND-query the symbol posting lists (files defining the named symbols)."""
        return self._query(self._symbol_postings, terms)

    def _query(self, postings_map: dict[str, list[int]], terms: Sequence[str] | str) -> QueryResult:
        query_terms = [terms.lower()] if isinstance(terms, str) else [t.lower() for t in terms]
        query_terms = [t for t in query_terms if t]
        baseline = len(self._paths)
        if not query_terms:
            return QueryResult(hits=[], work=0, baseline=baseline)

        posting_lists: list[list[int]] = []
        work = 0
        for term in query_terms:
            postings = postings_map.get(term, [])
            work += len(postings)  # touching this posting list is the query's cost
            posting_lists.append(postings)

        if any(not pl for pl in posting_lists):
            return QueryResult(hits=[], work=work, baseline=baseline)

        # Intersect smallest-first; sets over the (short) posting lists only.
        posting_lists.sort(key=len)
        matched: set[int] = set(posting_lists[0])
        for pl in posting_lists[1:]:
            matched &= set(pl)
            if not matched:
                break

        hits = sorted(self._paths[i] for i in matched)
        return QueryResult(hits=hits, work=work, baseline=baseline)


# ---------------------------------------------------------------------------
# 2. Build-graph partitioning -- reverse-dependency closure of a changed file
# ---------------------------------------------------------------------------


@dataclass
class BuildGraph:
    """Import reverse-dependency graph for build-graph partitioning.

    Files are added with their source; imports are parsed with :mod:`ast` and,
    after :meth:`resolve`, matched against known module paths to build forward
    (``file -> imported files``) and reverse (``file -> importers``) edges.
    """

    _module_to_file: dict[str, str] = field(default_factory=dict)
    _imports: dict[str, list[str]] = field(default_factory=dict)
    _forward: dict[str, set[str]] = field(default_factory=dict)
    _reverse: dict[str, set[str]] = field(default_factory=dict)
    _resolved: bool = False

    def add_file(self, path: str, source: str) -> None:
        module = _path_to_module(path)
        self._module_to_file[module] = path
        self._imports[path] = self._parse_imports(source)
        self._forward.setdefault(path, set())
        self._reverse.setdefault(path, set())
        self._resolved = False

    def add_corpus(self, corpus: dict[str, str]) -> None:
        for path in sorted(corpus):
            self.add_file(path, corpus[path])

    @staticmethod
    def _parse_imports(source: str) -> list[str]:
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules.append(node.module)
        return modules

    def resolve(self) -> None:
        """Resolve import module names to files and build forward/reverse edges."""
        self._forward = {path: set() for path in self._imports}
        self._reverse = {path: set() for path in self._imports}
        for path, modules in self._imports.items():
            for module in modules:
                target = self._module_to_file.get(module)
                if target is not None and target != path:
                    self._forward[path].add(target)
                    self._reverse[target].add(path)
        self._resolved = True

    def impacted_partition(self, changed_file: str) -> list[str]:
        """Return the reverse-dependency closure of ``changed_file`` (sorted).

        This is the minimal partition a build/test run must touch: the changed
        file plus every file that transitively imports it. Files in unrelated
        partitions are excluded, so build scope tracks the partition, not the
        repo.
        """
        if not self._resolved:
            self.resolve()
        if changed_file not in self._reverse:
            return []
        closure: set[str] = {changed_file}
        frontier = [changed_file]
        while frontier:
            current = frontier.pop()
            for importer in self._reverse.get(current, ()):  # who imports current
                if importer not in closure:
                    closure.add(importer)
                    frontier.append(importer)
        return sorted(closure)

    def direct_dependents(self, path: str) -> list[str]:
        """Files that directly import ``path`` (sorted)."""
        if not self._resolved:
            self.resolve()
        return sorted(self._reverse.get(path, set()))


# ---------------------------------------------------------------------------
# 3. Scaling benchmark -- synthesize corpora, measure, publish a report
# ---------------------------------------------------------------------------

# A rare token embedded only in "needle" clusters' entrypoints. Query work for
# this token equals the number of needle files, which we grow sub-linearly.
_NEEDLE_TOKEN = "zqxjneedle"

_BASE_CLUSTERS = 4  # clusters at scale 1x
_FILES_PER_CLUSTER = 4  # core + util_a + util_b + app


def _needle_clusters(num_clusters: int) -> int:
    """How many clusters carry the needle token: ~sqrt(clusters) (sub-linear)."""
    return max(1, math.isqrt(num_clusters))


def synthesize_corpus(scale: int, base_clusters: int = _BASE_CLUSTERS) -> dict[str, str]:
    """Build a deterministic ``path -> source`` corpus at ``scale`` x.

    The corpus is partitioned into independent clusters of four files each:
    ``core`` (imported by both utils), ``util_a`` / ``util_b`` (import ``core``),
    and ``app`` (imports both utils). Clusters do not import each other, so the
    reverse-dependency closure of any file stays inside its own cluster. The
    needle token is embedded in the ``app`` of the first ~``sqrt(clusters)``
    clusters, so a needle query matches a sub-linearly growing number of files.
    """
    if scale < 1:
        raise ValueError(f"scale must be >= 1, got {scale}")
    num_clusters = base_clusters * scale
    needle_count = _needle_clusters(num_clusters)
    corpus: dict[str, str] = {}
    for i in range(num_clusters):
        base = f"repo/cluster{i}"
        corpus[f"{base}/core.py"] = f"def core_service_{i}():\n    return {i}\n"
        corpus[f"{base}/util_a.py"] = (
            f"from repo.cluster{i}.core import core_service_{i}\n\ndef helper_a_{i}():\n    return core_service_{i}()\n"
        )
        corpus[f"{base}/util_b.py"] = (
            f"from repo.cluster{i}.core import core_service_{i}\n\ndef helper_b_{i}():\n    return core_service_{i}()\n"
        )
        app = (
            f"from repo.cluster{i}.util_a import helper_a_{i}\n"
            f"from repo.cluster{i}.util_b import helper_b_{i}\n\n"
            f"def app_main_{i}():\n    return helper_a_{i}() + helper_b_{i}()\n"
        )
        if i < needle_count:
            app += f"\n# marker {_NEEDLE_TOKEN} entrypoint\n"
        corpus[f"{base}/app.py"] = app
    return corpus


@dataclass
class ScalePoint:
    """Measurements at a single corpus scale."""

    scale: int
    corpus_size: int  # number of files/documents indexed
    needle_matches: int  # docs matching the needle query
    query_work: int  # postings touched to answer the needle query
    baseline_work: int  # docs a naive full scan would read (== corpus_size)
    changed_file: str  # the file we perturb for the partition measurement
    partition_size: int  # reverse-dep closure size (files a build must touch)

    def as_dict(self) -> dict[str, object]:
        return {
            "scale": self.scale,
            "corpus_size": self.corpus_size,
            "needle_matches": self.needle_matches,
            "query_work": self.query_work,
            "baseline_work": self.baseline_work,
            "changed_file": self.changed_file,
            "partition_size": self.partition_size,
        }


@dataclass
class BenchmarkReport:
    """Published scaling report with computed sub-linear exponents."""

    points: list[ScalePoint]
    query_scaling_exponent: float
    partition_scaling_exponent: float
    query_work_ratio: float  # work at max scale / work at min scale
    corpus_size_ratio: float  # corpus at max scale / corpus at min scale

    @property
    def sublinear(self) -> bool:
        return self.query_scaling_exponent < SUBLINEAR_EXPONENT and self.partition_scaling_exponent < SUBLINEAR_EXPONENT

    def as_dict(self) -> dict[str, object]:
        return {
            "points": [p.as_dict() for p in self.points],
            "query_scaling_exponent": self.query_scaling_exponent,
            "partition_scaling_exponent": self.partition_scaling_exponent,
            "query_work_ratio": self.query_work_ratio,
            "corpus_size_ratio": self.corpus_size_ratio,
            "sublinear": self.sublinear,
            "sublinear_threshold": SUBLINEAR_EXPONENT,
        }


def _loglog_slope(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Least-squares slope of ``log(y)`` vs ``log(x)`` -- the scaling exponent."""
    n = len(xs)
    if n < 2:
        return 0.0
    lx = [math.log(x) for x in xs]
    ly = [math.log(max(y, 1.0)) for y in ys]
    mx = sum(lx) / n
    my = sum(ly) / n
    num = sum((lx[i] - mx) * (ly[i] - my) for i in range(n))
    den = sum((lx[i] - mx) ** 2 for i in range(n))
    if den == 0.0:
        return 0.0
    return round(num / den, 6)


def run_benchmark(
    scales: Iterable[int] = (1, 2, 5, 10),
    base_clusters: int = _BASE_CLUSTERS,
) -> BenchmarkReport:
    """Run the 10x scaling benchmark and publish a :class:`BenchmarkReport`.

    For each scale it synthesizes the corpus, builds the inverted index and the
    build graph, then records the needle-query work and the reverse-dependency
    partition size of a fixed changed file (``repo/cluster0/core.py``). The
    report carries the four scale points plus the log-log scaling exponents.
    """
    scale_list = sorted(set(scales))
    if len(scale_list) < 2:
        raise ValueError("run_benchmark needs at least two distinct scales")

    points: list[ScalePoint] = []
    for scale in scale_list:
        corpus = synthesize_corpus(scale, base_clusters=base_clusters)

        index = InvertedIndex()
        index.index_corpus(corpus)
        result = index.query(_NEEDLE_TOKEN)

        graph = BuildGraph()
        graph.add_corpus(corpus)
        changed = "repo/cluster0/core.py"
        partition = graph.impacted_partition(changed)

        points.append(
            ScalePoint(
                scale=scale,
                corpus_size=len(corpus),
                needle_matches=len(result.hits),
                query_work=result.work,
                baseline_work=result.baseline,
                changed_file=changed,
                partition_size=len(partition),
            )
        )

    corpus_sizes = [p.corpus_size for p in points]
    query_exponent = _loglog_slope(corpus_sizes, [p.query_work for p in points])
    partition_exponent = _loglog_slope(corpus_sizes, [p.partition_size for p in points])

    first, last = points[0], points[-1]
    query_ratio = round(last.query_work / first.query_work, 6) if first.query_work else 0.0
    corpus_ratio = round(last.corpus_size / first.corpus_size, 6) if first.corpus_size else 0.0

    return BenchmarkReport(
        points=points,
        query_scaling_exponent=query_exponent,
        partition_scaling_exponent=partition_exponent,
        query_work_ratio=query_ratio,
        corpus_size_ratio=corpus_ratio,
    )
