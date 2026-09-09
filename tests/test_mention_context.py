"""Tests for the at-mention context-object resolver + budgeted retrieval core.

Everything here is hermetic: a fake resolver and fake relation provider stand in
for the live file/thread stores, a deterministic word-count token counter drives
the budget, and no network or wall clock is touched.
"""

from __future__ import annotations

from thomas.tools.mention_context import (
    ContextObject,
    DefaultMentionResolver,
    Mention,
    RelationCandidate,
    assemble_context_bundle,
    default_token_counter,
    parse_mentions,
)


class FakeResolver:
    """Resolves mentions from an in-memory table; unknown refs come back unresolved."""

    def __init__(self, table: dict[str, ContextObject]) -> None:
        self._table = table

    def resolve(self, mention: Mention) -> ContextObject:
        key = f"{mention.kind}:{mention.ref}"
        obj = self._table.get(key)
        if obj is None:
            return ContextObject(
                kind=mention.kind,
                ref=mention.ref,
                resolved=False,
                error="not found",
            )
        return obj


class FakeRelations:
    """Yields a fixed set of related candidates keyed by anchor object key."""

    def __init__(self, table: dict[str, list[RelationCandidate]]) -> None:
        self._table = table

    def related(self, obj: ContextObject):
        return list(self._table.get(obj.key, []))


def _words(n: int) -> str:
    # n whitespace-separated tokens -> default_token_counter returns exactly n.
    return " ".join(["w"] * n)


# --------------------------------------------------------------------------- #
# Parsing / typed resolution
# --------------------------------------------------------------------------- #


def test_parse_typed_mentions_in_order_dedup():
    mentions = parse_mentions("look at @file:src/app.py and @thread:42, also @session:s9 plus @file:src/app.py")
    assert [(m.kind, m.ref) for m in mentions] == [
        ("file", "src/app.py"),
        ("thread", "42"),
        ("session", "s9"),
    ]


def test_trailing_punctuation_trimmed_from_ref():
    (m,) = parse_mentions("see @thread:42.")
    assert m.kind == "thread"
    assert m.ref == "42"


def test_each_kind_resolves_to_correctly_typed_context_object():
    table = {
        "file:a.py": ContextObject(kind="file", ref="a.py", content=_words(3)),
        "thread:7": ContextObject(kind="thread", ref="7", content=_words(3)),
        "session:z": ContextObject(kind="session", ref="z", content=_words(3)),
    }
    resolver = FakeResolver(table)
    bundle = assemble_context_bundle(
        "@file:a.py @thread:7 @session:z",
        resolver,
        budget=100,
    )
    kinds = {(e.obj.kind, e.obj.ref) for e in bundle.included}
    assert kinds == {("file", "a.py"), ("thread", "7"), ("session", "z")}
    assert all(e.relation == "mention" for e in bundle.included)


def test_unresolvable_mention_is_reported_not_silently_dropped():
    resolver = FakeResolver({"file:known.py": ContextObject(kind="file", ref="known.py", content=_words(2))})
    bundle = assemble_context_bundle(
        "@file:known.py @thread:ghost",
        resolver,
        budget=100,
    )
    assert bundle.included_keys() == ["file:known.py"]
    dropped = [d for d in bundle.dropped if d.reason == "unresolvable"]
    assert len(dropped) == 1
    assert (dropped[0].kind, dropped[0].ref) == ("thread", "ghost")
    assert dropped[0].error == "not found"


# --------------------------------------------------------------------------- #
# Budgeted relation retrieval
# --------------------------------------------------------------------------- #


def test_related_included_in_relevance_order_and_stops_at_budget():
    anchor = ContextObject(kind="file", ref="main.py", content=_words(2))
    # Related objects: 3 tokens each. Relevance descending: r_hi, r_mid, r_lo.
    r_hi = ContextObject(kind="file", ref="hi.py", content=_words(3))
    r_mid = ContextObject(kind="file", ref="mid.py", content=_words(3))
    r_lo = ContextObject(kind="file", ref="lo.py", content=_words(3))
    resolver = FakeResolver({"file:main.py": anchor})
    relations = FakeRelations(
        {
            "file:main.py": [
                RelationCandidate(obj=r_lo, relevance=0.1),
                RelationCandidate(obj=r_hi, relevance=0.9),
                RelationCandidate(obj=r_mid, relevance=0.5),
            ]
        }
    )
    # Budget = anchor(2) + hi(3) + mid(3) = 8. lo (next candidate) must drop.
    bundle = assemble_context_bundle(
        "@file:main.py",
        resolver,
        budget=8,
        relation_provider=relations,
    )

    # Anchor first, then related in DESCENDING relevance order.
    assert bundle.included_keys() == ["file:main.py", "file:hi.py", "file:mid.py"]

    # STOP at budget: total never exceeds the budget...
    assert bundle.total_tokens == 8
    assert bundle.total_tokens <= bundle.budget

    # ...and the next (lowest-relevance) candidate was dropped for budget.
    budget_drops = [d for d in bundle.dropped if d.reason == "budget"]
    assert [(d.kind, d.ref) for d in budget_drops] == [("file", "lo.py")]


def test_budget_stop_is_strict_never_exceeds_even_when_a_later_smaller_item_would_fit():
    anchor = ContextObject(kind="file", ref="a.py", content=_words(1))
    big = ContextObject(kind="file", ref="big.py", content=_words(5))
    small = ContextObject(kind="file", ref="small.py", content=_words(1))
    resolver = FakeResolver({"file:a.py": anchor})
    relations = FakeRelations(
        {
            "file:a.py": [
                RelationCandidate(obj=big, relevance=0.9),
                RelationCandidate(obj=small, relevance=0.5),
            ]
        }
    )
    # Budget 3: anchor(1) fits -> total 1. big(5) would exceed -> STOP.
    bundle = assemble_context_bundle("@file:a.py", resolver, budget=3, relation_provider=relations)
    assert bundle.included_keys() == ["file:a.py"]
    assert bundle.total_tokens == 1
    assert bundle.total_tokens <= bundle.budget
    # Both remaining candidates recorded as budget drops (strict stop).
    assert {(d.ref) for d in bundle.dropped if d.reason == "budget"} == {
        "big.py",
        "small.py",
    }


def test_bundle_records_both_included_and_dropped():
    anchor = ContextObject(kind="thread", ref="t1", content=_words(2))
    rel = ContextObject(kind="thread", ref="t1-reply", content=_words(2))
    resolver = FakeResolver({"thread:t1": anchor})
    relations = FakeRelations({"thread:t1": [RelationCandidate(obj=rel, relevance=0.8)]})
    bundle = assemble_context_bundle(
        "@thread:t1 @session:missing",
        resolver,
        budget=3,  # anchor(2) fits, reply(2) does not
        relation_provider=relations,
    )
    assert bundle.included_keys() == ["thread:t1"]
    reasons = {(d.ref, d.reason) for d in bundle.dropped}
    assert ("missing", "unresolvable") in reasons
    assert ("t1-reply", "budget") in reasons


def test_determinism_identical_inputs_identical_bundle():
    anchor = ContextObject(kind="file", ref="m.py", content=_words(2))
    resolver = FakeResolver({"file:m.py": anchor})
    # Two related items with EQUAL relevance -> tiebreak must be stable.
    a = ContextObject(kind="file", ref="a.py", content=_words(2))
    b = ContextObject(kind="file", ref="b.py", content=_words(2))
    relations = FakeRelations(
        {
            "file:m.py": [
                RelationCandidate(obj=b, relevance=0.5),
                RelationCandidate(obj=a, relevance=0.5),
            ]
        }
    )
    kwargs = dict(budget=6, relation_provider=relations)
    first = assemble_context_bundle("@file:m.py", resolver, **kwargs)
    second = assemble_context_bundle("@file:m.py", resolver, **kwargs)
    assert first == second
    # Equal-relevance tie broken by stable key: a.py before b.py.
    assert first.included_keys() == ["file:m.py", "file:a.py", "file:b.py"]


# --------------------------------------------------------------------------- #
# Real default resolver (files off disk; injected thread/session store)
# --------------------------------------------------------------------------- #


def test_default_resolver_reads_file_and_reports_missing(tmp_path):
    f = tmp_path / "hello.py"
    f.write_text("print('hi')\nmore\n", encoding="utf-8")
    resolver = DefaultMentionResolver(root=tmp_path, thread_lookup={"9": "parent"})

    ok = resolver.resolve(Mention(kind="file", ref="hello.py", raw="@file:hello.py"))
    assert ok.resolved
    assert ok.kind == "file"
    assert "print('hi')" in ok.content
    assert ok.summary == "print('hi')"

    missing = resolver.resolve(Mention(kind="file", ref="nope.py", raw="@file:nope.py"))
    assert not missing.resolved
    assert missing.error is not None

    thread = resolver.resolve(Mention(kind="thread", ref="9", raw="@thread:9"))
    assert thread.resolved
    assert thread.content == "parent"

    no_session = resolver.resolve(Mention(kind="session", ref="x", raw="@session:x"))
    assert not no_session.resolved
    assert "no session store" in no_session.error


def test_default_token_counter_counts_words():
    assert default_token_counter("one two three") == 3
    assert default_token_counter("") == 0
