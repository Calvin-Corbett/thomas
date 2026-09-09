"""CAP-011: Large-context handling -- 300K-token needle test.

Proves the exact Level-2 acceptance line: *"Add a 300K-token needle test that
returns the correct file citation."*

The suite proves, hermetically and deterministically:
  * the needle corpus plants the fact in exactly one file;
  * a query returns the CORRECT file citation (``path#Lx-Ly``);
  * the naive-truncation control does NOT contain the needle (it sits past the
    window), so retrieval -- not brute context -- is what works;
  * scaling the corpus keeps the citation correct;
  * generation and retrieval are deterministic.
"""

from __future__ import annotations

from thomas.core.needle_context import (
    Citation,
    NeedleReader,
    chars_over_four,
    generate_needle_corpus,
    naive_truncate,
)


def test_corpus_plants_fact_in_exactly_one_file() -> None:
    corpus = generate_needle_corpus(target_tokens=20_000)

    holders = [p for p, body in corpus.files.items() if corpus.needle_fact in body]
    assert holders == [corpus.needle_path]

    # The planted line span really contains the fact.
    lines = corpus.files[corpus.needle_path].splitlines()
    span = lines[corpus.needle_start_line - 1 : corpus.needle_end_line]
    assert any(corpus.needle_fact in ln for ln in span)


def test_300k_token_query_returns_correct_file_citation() -> None:
    # The headline acceptance case: a corpus scaled to >= 300K tokens.
    corpus = generate_needle_corpus(target_tokens=300_000)
    assert corpus.total_tokens >= 300_000

    reader = NeedleReader()  # offline deterministic retriever (default)
    citation = reader.cite(corpus, corpus.needle_query)

    assert citation is not None
    # CORRECT FILE CITATION: path#Lx-Ly pointing at the needle's file + line.
    assert citation == corpus.needle_citation
    assert citation.ref == (f"{corpus.needle_path}#L{corpus.needle_start_line}-L{corpus.needle_end_line}")
    assert citation.path == "corpus/vault/secret_manifest.txt"


def test_naive_truncation_control_misses_the_needle() -> None:
    # Retrieval works; brute truncation does NOT. This is the whole point.
    corpus = generate_needle_corpus(target_tokens=300_000)

    truncated = naive_truncate(corpus)  # keep only leading window tokens

    # The needle is UNREACHABLE by simple truncation: it sits past the window.
    assert corpus.needle_fact not in truncated
    assert "quicksilver-lantern-4417" not in truncated
    # The truncation honored its token budget...
    assert chars_over_four(truncated) <= corpus.naive_truncation_window
    # ...yet the corpus as a whole DOES contain the needle.
    assert corpus.needle_fact in corpus.concatenated()

    # And retrieval over the full corpus still finds it.
    citation = NeedleReader().cite(corpus, corpus.needle_query)
    assert citation == corpus.needle_citation


def test_scaling_corpus_keeps_citation_correct() -> None:
    reader = NeedleReader()
    prev_tokens = 0
    for target in (10_000, 50_000, 150_000, 300_000):
        corpus = generate_needle_corpus(target_tokens=target)
        assert corpus.total_tokens >= target
        assert corpus.total_tokens > prev_tokens  # genuinely larger each step
        prev_tokens = corpus.total_tokens

        citation = reader.cite(corpus, corpus.needle_query)
        assert citation == corpus.needle_citation
        # Larger haystack must not leak the needle into the naive window.
        assert corpus.needle_fact not in naive_truncate(corpus)


def test_generation_and_retrieval_are_deterministic() -> None:
    a = generate_needle_corpus(target_tokens=40_000)
    b = generate_needle_corpus(target_tokens=40_000)

    assert a.files == b.files
    assert a.concat_order == b.concat_order
    assert a.total_tokens == b.total_tokens
    assert a.needle_citation == b.needle_citation

    reader = NeedleReader()
    c1 = reader.cite(a, a.needle_query)
    c2 = reader.cite(b, b.needle_query)
    assert c1 == c2 == a.needle_citation


def test_injectable_token_counter_changes_sizing() -> None:
    # A counter that treats every char as a token yields far more tokens for the
    # same body, proving the counter is genuinely injected into sizing.
    def one_token_per_char(text: str) -> int:
        return len(text)

    default_corpus = generate_needle_corpus(target_tokens=20_000)
    dense_corpus = generate_needle_corpus(target_tokens=20_000, token_counter=one_token_per_char)
    # Same token target, but the char-counter reaches it with far fewer files.
    assert len(dense_corpus.files) < len(default_corpus.files)

    # Citation still resolves correctly under the injected counter, and the
    # control truncation (using the same counter) still misses the needle.
    citation = NeedleReader().cite(dense_corpus, dense_corpus.needle_query)
    assert citation == dense_corpus.needle_citation
    assert dense_corpus.needle_fact not in naive_truncate(dense_corpus, token_counter=one_token_per_char)


def test_reader_accepts_injected_live_lane_style_retriever() -> None:
    # Documents the live-embedding lane seam: any retriever with the
    # (corpus, query, k) -> [Citation] contract can be swapped in. Here a fake
    # stands in for an embedding backend and returns the ground-truth citation.
    corpus = generate_needle_corpus(target_tokens=5_000)

    calls: list[str] = []

    def fake_embedding_retriever(c, query: str, k: int = 5) -> list[Citation]:
        calls.append(query)
        return [c.needle_citation]

    reader = NeedleReader(retriever=fake_embedding_retriever)
    citation = reader.cite(corpus, corpus.needle_query)
    assert citation == corpus.needle_citation
    assert calls == [corpus.needle_query]
