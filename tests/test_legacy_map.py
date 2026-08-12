"""Tests for the legacy ingestion / code map (CAP-142).

Hermetic: a temp fixture Python package is written to disk, the map persists to
a temp sqlite file, and the clock is injected. No network, no shared state.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from thomas.tools.legacy_map import (
    EDGE_CALL,
    EDGE_IMPORT,
    KIND_CLASS,
    KIND_FUNCTION,
    KIND_METHOD,
    CodeMap,
    accuracy_report,
)

# --------------------------------------------------------------------------
# Fixture: a small legacy package with a clear dependency chain.
#
#   pkg/core.py       base()              <- leaf
#   pkg/service.py    service() -> base()
#   pkg/api.py        Handler.handle() -> service()
#   pkg/unrelated.py  orphan()            <- depends on nothing in pkg
# --------------------------------------------------------------------------

FILES = {
    "pkg/__init__.py": "",
    "pkg/core.py": ("def base():\n    return 1\n"),
    "pkg/service.py": ("from pkg.core import base\n\ndef service():\n    return base() + 1\n"),
    "pkg/api.py": (
        "from pkg.service import service\n\nclass Handler:\n    def handle(self):\n        return service()\n"
    ),
    "pkg/unrelated.py": ("def orphan():\n    return 0\n"),
}


class FakeClock:
    """Deterministic monotonically increasing injected clock."""

    def __init__(self) -> None:
        self._c = itertools.count(1000)

    def __call__(self) -> float:
        return float(next(self._c))


def _write(root: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "src"
    _write(root, FILES)
    return root


def _map(repo: Path, tmp_path: Path) -> CodeMap:
    return CodeMap(repo, db_path=tmp_path / "map.sqlite3", clock=FakeClock())


# --------------------------------------------------------------------------
# 1. Symbols + edges extracted with locations
# --------------------------------------------------------------------------


def test_symbols_extracted_with_locations(repo: Path, tmp_path: Path) -> None:
    cm = _map(repo, tmp_path)
    cm.ingest()
    by_name = {s.qualname: s for s in cm.symbols()}

    assert by_name["pkg.core.base"].kind == KIND_FUNCTION
    assert by_name["pkg.core.base"].file == "pkg/core.py"
    assert by_name["pkg.core.base"].lineno == 1

    assert by_name["pkg.api.Handler"].kind == KIND_CLASS
    assert by_name["pkg.api.Handler.handle"].kind == KIND_METHOD
    assert by_name["pkg.api.Handler.handle"].lineno == 4
    cm.close()


def test_edges_extracted_imports_and_calls(repo: Path, tmp_path: Path) -> None:
    cm = _map(repo, tmp_path)
    cm.ingest()
    edges = {(e.src, e.dst, e.kind) for e in cm.edges()}

    # Import edges (module -> imported symbol).
    assert ("pkg.service", "pkg.core.base", EDGE_IMPORT) in edges
    assert ("pkg.api", "pkg.service.service", EDGE_IMPORT) in edges

    # Call edges (enclosing symbol -> called symbol).
    assert ("pkg.service.service", "pkg.core.base", EDGE_CALL) in edges
    assert ("pkg.api.Handler.handle", "pkg.service.service", EDGE_CALL) in edges

    # Every edge carries a source location.
    for e in cm.edges():
        assert e.file.endswith(".py")
        assert e.lineno >= 1
    cm.close()


# --------------------------------------------------------------------------
# 2. Hash-gated incremental ingest
# --------------------------------------------------------------------------


def test_unchanged_reingest_is_noop(repo: Path, tmp_path: Path) -> None:
    cm = _map(repo, tmp_path)
    first = cm.ingest()
    assert first.files_parsed == len(FILES)
    assert first.files_skipped == 0

    second = cm.ingest()
    # Hash gate: nothing re-parsed, everything skipped.
    assert second.files_parsed == 0
    assert second.parsed_files == []
    assert second.files_skipped == len(FILES)
    assert sorted(second.skipped_files) == sorted(FILES)
    cm.close()


def test_changed_file_updates_only_itself(repo: Path, tmp_path: Path) -> None:
    cm = _map(repo, tmp_path)
    cm.ingest()
    hashes_before = {rel: cm.file_hash(rel) for rel in FILES}

    # Add a new symbol to exactly one file.
    (repo / "pkg/core.py").write_text(
        "def base():\n    return 1\n\ndef helper():\n    return 2\n",
        encoding="utf-8",
    )

    report = cm.ingest()
    assert report.parsed_files == ["pkg/core.py"]  # only the changed file
    assert "pkg/core.py" not in report.skipped_files
    assert report.files_skipped == len(FILES) - 1

    # Only pkg/core.py's hash changed; siblings untouched.
    assert cm.file_hash("pkg/core.py") != hashes_before["pkg/core.py"]
    for rel in ("pkg/service.py", "pkg/api.py", "pkg/unrelated.py"):
        assert cm.file_hash(rel) == hashes_before[rel]

    # New symbol is now present.
    assert cm.get_symbol("pkg.core.helper") is not None
    cm.close()


def test_removed_file_is_purged(repo: Path, tmp_path: Path) -> None:
    cm = _map(repo, tmp_path)
    cm.ingest()
    assert cm.get_symbol("pkg.unrelated.orphan") is not None

    (repo / "pkg/unrelated.py").unlink()
    report = cm.ingest()

    assert report.removed_files == ["pkg/unrelated.py"]
    assert cm.get_symbol("pkg.unrelated.orphan") is None
    assert cm.file_hash("pkg/unrelated.py") is None
    cm.close()


# --------------------------------------------------------------------------
# 3. Impact set = reverse-dependency closure
# --------------------------------------------------------------------------


def test_impact_set_is_reverse_dep_closure(repo: Path, tmp_path: Path) -> None:
    cm = _map(repo, tmp_path)
    cm.ingest()

    # Changing base() affects service() (calls it) and Handler.handle()
    # (calls service, which calls base) -- transitive reverse closure.
    impact = cm.impact_set("pkg.core.base")
    assert impact == ["pkg.api.Handler.handle", "pkg.service.service"]

    # The leaf's own caller only.
    assert cm.impact_set("pkg.service.service") == ["pkg.api.Handler.handle"]

    # Nothing depends on the orphan or the top of the chain.
    assert cm.impact_set("pkg.unrelated.orphan") == []
    assert cm.impact_set("pkg.api.Handler.handle") == []
    cm.close()


# --------------------------------------------------------------------------
# 4. Accuracy report vs golden set
# --------------------------------------------------------------------------


def test_accuracy_report_perfect_match(repo: Path, tmp_path: Path) -> None:
    cm = _map(repo, tmp_path)
    cm.ingest()

    computed = cm.impact_set("pkg.core.base")
    golden = ["pkg.service.service", "pkg.api.Handler.handle"]  # known-true
    report = accuracy_report(computed, golden)

    assert report.precision == 1.0
    assert report.recall == 1.0
    assert report.f1 == 1.0
    assert report.missing == ()
    assert report.spurious == ()
    cm.close()


def test_accuracy_report_fractional_precision_recall() -> None:
    # Golden has a symbol static analysis cannot see (dynamic dispatch) and the
    # computed set has one the golden considers spurious.
    computed = ["a", "b", "c"]  # c is a false positive
    golden = ["a", "b", "d"]  # d is a false negative (missed)
    report = accuracy_report(computed, golden)

    assert report.true_positives == 2
    assert report.false_positives == 1
    assert report.false_negatives == 1
    assert report.precision == pytest.approx(2 / 3)
    assert report.recall == pytest.approx(2 / 3)
    assert report.f1 == pytest.approx(2 / 3)
    assert report.missing == ("d",)
    assert report.spurious == ("c",)


def test_accuracy_report_empty_sets_are_perfect() -> None:
    report = accuracy_report([], [])
    assert report.precision == 1.0
    assert report.recall == 1.0
    assert report.f1 == 1.0


# --------------------------------------------------------------------------
# 5. Round-trip persistence (close, reopen, same results)
# --------------------------------------------------------------------------


def test_round_trip_persistence(repo: Path, tmp_path: Path) -> None:
    db = tmp_path / "rt.sqlite3"
    cm = CodeMap(repo, db_path=db, clock=FakeClock())
    cm.ingest()
    snapshot = cm.to_dict()
    impact = cm.impact_set("pkg.core.base")
    cm.close()

    # Reopen a fresh handle on the same db -- no re-ingest.
    reopened = CodeMap(repo, db_path=db, clock=FakeClock())
    assert reopened.to_dict() == snapshot
    assert reopened.impact_set("pkg.core.base") == impact

    # A no-op ingest after reopen still parses nothing (hashes persisted).
    report = reopened.ingest()
    assert report.files_parsed == 0
    assert report.files_skipped == len(FILES)
    reopened.close()


def test_snapshot_is_json_serializable(repo: Path, tmp_path: Path) -> None:
    cm = _map(repo, tmp_path)
    cm.ingest()
    blob = json.dumps(cm.to_dict())
    restored = json.loads(blob)
    assert {s["qualname"] for s in restored["symbols"]} >= {
        "pkg.core.base",
        "pkg.service.service",
        "pkg.api.Handler",
        "pkg.api.Handler.handle",
    }
    cm.close()


# --------------------------------------------------------------------------
# 6. Unparseable legacy file is hash-gated, not fatal
# --------------------------------------------------------------------------


def test_unparseable_file_is_gated(repo: Path, tmp_path: Path) -> None:
    (repo / "pkg/broken.py").write_text("def bad(:\n    pass\n", encoding="utf-8")
    cm = _map(repo, tmp_path)
    first = cm.ingest()
    assert "pkg/broken.py" in first.unparseable_files

    # Re-ingest: the broken file is gated by hash, not retried.
    second = cm.ingest()
    assert "pkg/broken.py" in second.skipped_files
    assert "pkg/broken.py" not in second.parsed_files
    cm.close()
