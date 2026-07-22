"""HTTP-surface tests for the at-mention context-object routes (CAP-148).

Drives the real aiohttp handlers through an in-process TestServer -- no network,
no full app boot. The file root is pointed at a temp dir and the thread/session
store is populated through the registration route, so every run is hermetic.

Proves the acceptance behaviours at the HTTP boundary:

* ``@file:`` / ``@thread:`` / ``@session:`` resolve to correctly-TYPED objects;
* an unresolvable mention is REPORTED (dropped + reason + error), never missing;
* ``total_tokens`` never exceeds the budget and the items that did not fit are
  listed as dropped-for-budget;
* bad input is a 4xx, never a 500.
"""

from __future__ import annotations

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from thomas.server.routes.mention_context_routes import (
    register_mention_context_routes,
    reset_mention_context_state,
)

RESOLVE_URL = "/api/mention-context/resolve"
OBJECTS_URL = "/api/mention-context/objects"


@pytest.fixture
def root(tmp_path, monkeypatch):
    """Contain @file reads to a temp dir and isolate the module singleton."""

    monkeypatch.setenv("THOMAS_MENTION_CONTEXT_ROOT", str(tmp_path))
    reset_mention_context_state()
    yield tmp_path
    reset_mention_context_state()


def _make_app() -> web.Application:
    app = web.Application()
    register_mention_context_routes(app, None)
    return app


def _drive(scenario):
    async def run():
        server = TestServer(_make_app())
        client = TestClient(server)
        await client.start_server()
        try:
            return await scenario(client)
        finally:
            await client.close()

    return asyncio.run(run())


def _words(n: int) -> str:
    """Text whose default token count is exactly ``n``."""

    return " ".join(["w"] * n)


async def _register(client, kind: str, ref: str, content: str, relations=None):
    payload = {"kind": kind, "ref": ref, "content": content}
    if relations is not None:
        payload["relations"] = relations
    resp = await client.post(OBJECTS_URL, json=payload)
    assert resp.status == 201, await resp.text()
    return await resp.json()


async def _resolve(client, utterance: str, budget: int, **extra):
    payload = {"utterance": utterance, "budget": budget}
    payload.update(extra)
    resp = await client.post(RESOLVE_URL, json=payload)
    return resp, await resp.json()


def _by_key(entries):
    return {entry["key"]: entry for entry in entries}


# --------------------------------------------------------------------------- #
# Typed resolution of all three mention kinds
# --------------------------------------------------------------------------- #


def test_three_mention_kinds_resolve_to_typed_objects(root):
    (root / "notes.md").write_text("file body here", encoding="utf-8")

    async def scenario(client):
        await _register(client, "thread", "t-1", "thread body")
        await _register(client, "session", "s-1", "session body")
        resp, body = await _resolve(
            client,
            "look at @file:notes.md and @thread:t-1 plus @session:s-1",
            budget=500,
            max_relations=0,
        )
        assert resp.status == 200
        assert [m["kind"] for m in body["mentions"]] == ["file", "thread", "session"]
        included = _by_key(body["included"])
        assert set(included) == {"file:notes.md", "thread:t-1", "session:s-1"}
        assert included["file:notes.md"]["preview"] == "file body here"
        assert included["thread:t-1"]["preview"] == "thread body"
        assert included["session:s-1"]["preview"] == "session body"
        assert all(entry["relation"] == "mention" for entry in included.values())
        assert body["dropped"] == []
        return body

    _drive(scenario)


def test_registry_is_shared_across_routes(root):
    async def scenario(client):
        await _register(client, "thread", "t-9", "shared thread")
        listed = await (await client.get(OBJECTS_URL)).json()
        assert listed["store"]["threads"] == ["t-9"]
        assert listed["store"]["root"] == str(root)
        # ... and the resolve route sees the same store.
        _resp, body = await _resolve(client, "@thread:t-9", budget=100, max_relations=0)
        assert _by_key(body["included"])["thread:t-9"]["preview"] == "shared thread"

    _drive(scenario)


# --------------------------------------------------------------------------- #
# Unresolvable mentions are reported, never silently missing
# --------------------------------------------------------------------------- #


def test_unresolvable_mentions_are_reported_with_reason(root):
    (root / "real.txt").write_text("present", encoding="utf-8")

    async def scenario(client):
        _resp, body = await _resolve(
            client,
            "@file:real.txt @file:ghost.txt @thread:nope",
            budget=500,
            max_relations=0,
        )
        assert list(_by_key(body["included"])) == ["file:real.txt"]
        dropped = _by_key(body["dropped"])
        assert set(dropped) == {"file:ghost.txt", "thread:nope"}
        for entry in dropped.values():
            assert entry["reason"] == "unresolvable"
            assert entry["error"]
            # The server's absolute root is scrubbed out of reported errors,
            # in both the plain and the repr-escaped (Windows) spelling.
            assert str(root) not in entry["error"]
            assert str(root).replace("\\", "\\\\") not in entry["error"]
        assert body["counts"]["dropped_by_reason"]["unresolvable"] == 2

    _drive(scenario)


def test_file_mention_escaping_root_is_reported_not_read(root, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "secret.txt"
    outside.write_text("classified", encoding="utf-8")

    async def scenario(client):
        _resp, body = await _resolve(client, f"@file:{outside}", budget=500, max_relations=0)
        assert body["included"] == []
        dropped = body["dropped"][0]
        assert dropped["reason"] == "unresolvable"
        assert dropped["error"] == "outside project root"

    _drive(scenario)


# --------------------------------------------------------------------------- #
# Budgeted retrieval
# --------------------------------------------------------------------------- #


def test_total_never_exceeds_budget_and_budget_drops_are_listed(root):
    (root / "a.txt").write_text(_words(10), encoding="utf-8")
    (root / "b.txt").write_text(_words(10), encoding="utf-8")

    async def scenario(client):
        _resp, body = await _resolve(client, "@file:a.txt @file:b.txt", budget=15, max_relations=0)
        assert body["total_tokens"] == 10
        assert body["total_tokens"] <= body["budget"]
        assert body["within_budget"] is True
        assert body["remaining_tokens"] == 5
        assert list(_by_key(body["included"])) == ["file:a.txt"]
        dropped = _by_key(body["dropped"])
        assert dropped["file:b.txt"]["reason"] == "budget"
        assert dropped["file:b.txt"]["tokens"] == 10
        assert body["counts"]["dropped_by_reason"]["budget"] == 1

    _drive(scenario)


def test_zero_budget_drops_everything_for_budget(root):
    (root / "a.txt").write_text(_words(4), encoding="utf-8")

    async def scenario(client):
        _resp, body = await _resolve(client, "@file:a.txt", budget=0, max_relations=0)
        assert body["total_tokens"] == 0
        assert body["included"] == []
        assert body["dropped"][0]["reason"] == "budget"

    _drive(scenario)


def test_registered_relations_retrieved_in_relevance_order_within_budget(root):
    async def scenario(client):
        await _register(
            client,
            "thread",
            "t-2",
            _words(2),
            relations=[
                {"kind": "session", "ref": "weak", "content": _words(5), "relevance": 0.1},
                {"kind": "session", "ref": "strong", "content": _words(5), "relevance": 0.9},
            ],
        )
        # Budget fits the anchor (2) + exactly one 5-token relation.
        _resp, body = await _resolve(client, "@thread:t-2", budget=8, max_relations=4)
        included = _by_key(body["included"])
        assert included["thread:t-2"]["relation"] == "mention"
        assert included["session:strong"]["relation"] == "related"
        assert included["session:strong"]["anchor"] == "thread:t-2"
        assert "session:weak" not in included
        dropped = _by_key(body["dropped"])
        assert dropped["session:weak"]["reason"] == "budget"
        assert body["total_tokens"] == 7
        assert body["total_tokens"] <= body["budget"]

    _drive(scenario)


def test_related_object_duplicating_an_anchor_is_dropped_as_duplicate(root):
    (root / "a.txt").write_text(_words(3), encoding="utf-8")

    async def scenario(client):
        await _register(
            client,
            "thread",
            "t-3",
            _words(3),
            relations=[{"kind": "file", "ref": "a.txt", "content": _words(3), "relevance": 0.8}],
        )
        _resp, body = await _resolve(client, "@file:a.txt @thread:t-3", budget=500, max_relations=4)
        dropped = _by_key(body["dropped"])
        assert dropped["file:a.txt"]["reason"] == "duplicate"
        assert len(_by_key(body["included"])) == 2

    _drive(scenario)


def test_file_neighbours_are_offered_as_related_candidates(root):
    (root / "alpha.md").write_text(_words(3), encoding="utf-8")
    (root / "alphabet.md").write_text(_words(3), encoding="utf-8")

    async def scenario(client):
        _resp, body = await _resolve(client, "@file:alpha.md", budget=500, max_relations=4)
        included = _by_key(body["included"])
        assert included["file:alpha.md"]["relation"] == "mention"
        neighbour = included["file:alphabet.md"]
        assert neighbour["relation"] == "related"
        assert neighbour["anchor"] == "file:alpha.md"
        assert neighbour["relevance"] > 0
        assert body["total_tokens"] == 6

    _drive(scenario)


def test_max_relations_zero_disables_relation_retrieval(root):
    (root / "alpha.md").write_text(_words(3), encoding="utf-8")
    (root / "alphabet.md").write_text(_words(3), encoding="utf-8")

    async def scenario(client):
        _resp, body = await _resolve(client, "@file:alpha.md", budget=500, max_relations=0)
        assert list(_by_key(body["included"])) == ["file:alpha.md"]

    _drive(scenario)


def test_utterance_without_mentions_is_an_empty_bundle(root):
    async def scenario(client):
        resp, body = await _resolve(client, "no mentions here", budget=50)
        assert resp.status == 200
        assert body["included"] == []
        assert body["dropped"] == []
        assert body["total_tokens"] == 0

    _drive(scenario)


# --------------------------------------------------------------------------- #
# Input validation: user error is 4xx, never 500
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "payload",
    [
        {"utterance": "@thread:x"},
        {"utterance": "@thread:x", "budget": -1},
        {"utterance": "@thread:x", "budget": "lots"},
        {"utterance": "@thread:x", "budget": True},
        {"utterance": "@thread:x", "budget": 10**9},
        {"utterance": 42, "budget": 10},
        {"utterance": "@thread:x", "budget": 10, "max_relations": -2},
        {"utterance": "@thread:x", "budget": 10, "max_relations": 999},
    ],
)
def test_resolve_rejects_bad_input_with_400(root, payload):
    async def scenario(client):
        resp = await client.post(RESOLVE_URL, json=payload)
        assert resp.status == 400, await resp.text()

    _drive(scenario)


def test_resolve_rejects_non_object_and_invalid_json_bodies(root):
    async def scenario(client):
        listed = await client.post(RESOLVE_URL, json=["nope"])
        assert listed.status == 400
        broken = await client.post(
            RESOLVE_URL,
            data="{not json",
            headers={"Content-Type": "application/json"},
        )
        assert broken.status == 400

    _drive(scenario)


@pytest.mark.parametrize(
    "payload",
    [
        {"kind": "file", "ref": "a.txt", "content": "x"},
        {"kind": "thread", "ref": "  ", "content": "x"},
        {"kind": "thread", "ref": "t", "content": 5},
        {"kind": "thread", "ref": "t", "content": "x", "relations": "nope"},
        {"kind": "thread", "ref": "t", "content": "x", "relations": [{"kind": "bogus", "ref": "r"}]},
        {"kind": "thread", "ref": "t", "content": "x", "relations": [{"kind": "file", "ref": ""}]},
        {
            "kind": "thread",
            "ref": "t",
            "content": "x",
            "relations": [{"kind": "file", "ref": "r", "relevance": "high"}],
        },
    ],
)
def test_register_object_rejects_bad_input_with_400(root, payload):
    async def scenario(client):
        resp = await client.post(OBJECTS_URL, json=payload)
        assert resp.status == 400, await resp.text()

    _drive(scenario)


def test_long_utterance_rejected_with_400(root):
    async def scenario(client):
        resp = await client.post(RESOLVE_URL, json={"utterance": "x" * 20_001, "budget": 10})
        assert resp.status == 400

    _drive(scenario)
