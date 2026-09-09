"""CAP-015: incremental indexing with immediate post-edit retrieval.

Proves the exact acceptance line: filesystem changes are wired into incremental
indexing and retrieval reflects an edit immediately.
"""

from __future__ import annotations

from typing import Any

import pytest

from thomas.core.incremental_index import (
    VALID_EVENTS,
    IncrementalIndex,
    SearchHit,
)


def _paths(hits: list[SearchHit]) -> list[str]:
    return [h.path for h in hits]


def test_index_files_then_query_finds_term() -> None:
    idx = IncrementalIndex()
    changed = idx.index_files(
        {
            "a.py": "def alpha():\n    return payment_idempotency\n",
            "b.py": "def beta():\n    return unrelated_widget\n",
        }
    )
    assert changed == 2
    assert len(idx) == 2

    hits = idx.query("idempotency")
    assert _paths(hits) == ["a.py"]
    assert "payment_idempotency" in hits[0].snippet
    assert hits[0].line == 2


def test_modify_reflects_immediately_new_content_and_drops_removed_term() -> None:
    idx = IncrementalIndex()
    idx.index_file("mod.py", "def old_handler():\n    return legacytoken\n")

    # Sanity: old term retrievable, new term absent.
    assert _paths(idx.query("legacytoken")) == ["mod.py"]
    assert idx.query("refreshedtoken") == []

    # Filesystem edit -> incremental apply_change -> IMMEDIATE query.
    changed = idx.apply_change(
        "mod.py",
        "modified",
        content="def new_handler():\n    return refreshedtoken\n",
    )
    assert changed is True

    # New content is retrievable right away...
    new_hits = idx.query("refreshedtoken")
    assert _paths(new_hits) == ["mod.py"]
    assert "refreshedtoken" in new_hits[0].snippet

    # ...and the removed term is gone from retrieval immediately.
    assert idx.query("legacytoken") == []


def test_create_event_makes_file_immediately_retrievable() -> None:
    idx = IncrementalIndex()
    idx.index_file("existing.py", "def existing():\n    pass\n")
    assert idx.query("brandnewsymbol") == []

    idx.apply_change("created.py", "created", content="def brandnewsymbol():\n    pass\n")

    hits = idx.query("brandnewsymbol")
    assert _paths(hits) == ["created.py"]
    assert "created.py" in idx


def test_delete_event_makes_file_no_longer_retrievable() -> None:
    idx = IncrementalIndex()
    idx.index_files(
        {
            "keep.py": "sharedmarker keepbody\n",
            "gone.py": "sharedmarker gonebody\n",
        }
    )
    assert set(_paths(idx.query("sharedmarker"))) == {"keep.py", "gone.py"}
    assert _paths(idx.query("gonebody")) == ["gone.py"]

    changed = idx.apply_change("gone.py", "deleted")
    assert changed is True

    assert "gone.py" not in idx
    assert idx.query("gonebody") == []
    # The surviving file is still retrievable via the shared term.
    assert _paths(idx.query("sharedmarker")) == ["keep.py"]


def test_unchanged_reindex_is_hash_guarded_noop() -> None:
    idx = IncrementalIndex()
    content = "def stable():\n    return constant_value\n"
    assert idx.index_file("s.py", content) is True
    first_hash = idx.content_hash("s.py")

    # Re-indexing identical content is a genuine no-op.
    assert idx.index_file("s.py", content) is False
    assert idx.content_hash("s.py") == first_hash
    assert idx.apply_change("s.py", "modified", content=content) is False

    # A real edit does register as a change.
    assert idx.index_file("s.py", content + "# touched\n") is True
    assert idx.content_hash("s.py") != first_hash


def test_ranking_is_deterministic() -> None:
    files = {
        "one.py": "search search search index",
        "two.py": "search index",
        "three.py": "search search index",
    }
    # Build the index in several orders; ranking must be identical each time.
    orders = [
        ["one.py", "two.py", "three.py"],
        ["three.py", "one.py", "two.py"],
        ["two.py", "three.py", "one.py"],
    ]
    rankings = []
    for order in orders:
        idx = IncrementalIndex()
        for path in order:
            idx.index_file(path, files[path])
        hits = idx.query("search", k=5)
        rankings.append([(h.path, h.score) for h in hits])

    assert rankings[0] == rankings[1] == rankings[2]
    # More occurrences of "search" -> higher rank.
    assert [p for p, _ in rankings[0]] == ["one.py", "three.py", "two.py"]


def test_tie_broken_by_ascending_path() -> None:
    idx = IncrementalIndex()
    idx.index_file("zeta.py", "token")
    idx.index_file("alpha.py", "token")
    hits = idx.query("token")
    assert _paths(hits) == ["alpha.py", "zeta.py"]
    assert hits[0].score == hits[1].score


def test_identifier_fragments_are_searchable() -> None:
    idx = IncrementalIndex()
    idx.index_file("h.py", "def apply_change(path):\n    return IndexEntry(path)\n")
    assert _paths(idx.query("apply")) == ["h.py"]
    assert _paths(idx.query("change")) == ["h.py"]
    assert _paths(idx.query("index")) == ["h.py"]
    assert _paths(idx.query("entry")) == ["h.py"]


def test_apply_change_validates_event_and_content() -> None:
    idx = IncrementalIndex()
    with pytest.raises(ValueError, match="unknown event"):
        idx.apply_change("x.py", "renamed", content="x")
    with pytest.raises(ValueError, match="requires content"):
        idx.apply_change("x.py", "created")
    assert "created" in VALID_EVENTS and "modified" in VALID_EVENTS and "deleted" in VALID_EVENTS


def test_empty_query_returns_no_hits() -> None:
    idx = IncrementalIndex()
    idx.index_file("a.py", "content")
    assert idx.query("") == []
    assert idx.query("   ") == []


class _FakeSemanticIndex:
    """External embedding backend stand-in (not an internal module mock)."""

    def __init__(self, vector_count: int) -> None:
        self._vector_count = vector_count
        self.calls: list[str] = []

    def status(self) -> dict[str, Any]:
        return {"vector_count": self._vector_count, "fts_enabled": True}

    def search(self, query: str, k: int = 5, filter_ext: str | None = None) -> list[dict[str, Any]]:
        self.calls.append(query)
        return [{"file": "semantic_hit.py#L1-L3", "chunk": "semantic snippet", "score": 0.99}]


def test_delegates_to_rag_index_when_embeddings_present() -> None:
    backend = _FakeSemanticIndex(vector_count=42)
    idx = IncrementalIndex(rag_index=backend)
    idx.index_file("local.py", "local_only_term here")

    hits = idx.query("anything")
    assert backend.calls == ["anything"]
    assert _paths(hits) == ["semantic_hit.py"]
    assert hits[0].snippet == "semantic snippet"


def test_stays_local_when_backend_has_no_vectors() -> None:
    backend = _FakeSemanticIndex(vector_count=0)
    idx = IncrementalIndex(rag_index=backend)
    idx.index_file("local.py", "local_only_term here")

    hits = idx.query("local_only_term")
    assert backend.calls == []  # never delegated
    assert _paths(hits) == ["local.py"]


def test_prefer_semantic_false_forces_local_path() -> None:
    backend = _FakeSemanticIndex(vector_count=42)
    idx = IncrementalIndex(rag_index=backend)
    idx.index_file("local.py", "local_only_term here")

    hits = idx.query("local_only_term", prefer_semantic=False)
    assert backend.calls == []
    assert _paths(hits) == ["local.py"]
