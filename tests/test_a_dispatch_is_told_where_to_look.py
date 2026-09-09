"""A dispatched agent is told where to look, instead of searching from scratch.

Every dispatch used to send the task sentence and nothing else. On 2026-09-03 a
benchmark task cost Thomas 500 seconds, most of it grepping 958 test files for
the one to edit; the index answers the same question in six milliseconds. The
gap was not intelligence, it was that each run started amnesiac.

The rules these tests hold down are the ones that make the hint safe: an
explicit definition always wins, retrieval failure is never dispatch failure,
and the block says out loud that it may be wrong - measured on this repo, two
of five sample queries missed entirely, so an agent must feel free to ignore it.
"""

from __future__ import annotations

from typing import Any

import pytest

from thomas.forge.anvil.task_context import (
    MAX_BLOCK_CHARS,
    render_context,
    repo_context_for,
)


class _Index:
    def __init__(self, hits: list[dict[str, Any]] | None = None, boom: bool = False) -> None:
        self._hits = hits or []
        self._boom = boom
        self.queries: list[str] = []

    def search(self, query: str, k: int = 5, **kwargs: Any) -> list[dict[str, Any]]:
        self.queries.append(query)
        if self._boom:
            raise RuntimeError("chromadb is required")
        return self._hits[:k]


def _hits(*paths: str) -> list[dict[str, Any]]:
    return [{"file": p} for p in paths]


def test_the_block_names_the_files_the_index_found() -> None:
    out = repo_context_for(
        "branch claim expires",
        searcher=_Index(_hits("scripts/forge/branch_claims.py#L343-L382")),
    )
    assert "scripts/forge/branch_claims.py#L343-L382" in out


def test_the_block_says_it_may_be_wrong() -> None:
    """Two of five sample queries missed. A confident wrong pointer is worse than none."""
    out = repo_context_for("anything", searcher=_Index(_hits("a.py")))
    assert "hints, not answers" in out
    assert "search normally" in out


def test_a_broken_index_yields_no_context_and_no_exception() -> None:
    assert repo_context_for("anything", searcher=_Index(boom=True)) == ""


def test_no_hits_yields_an_empty_string_not_an_empty_header() -> None:
    """A header with nothing under it spends context to say nothing."""
    assert repo_context_for("anything", searcher=_Index([])) == ""


def test_an_empty_goal_is_not_searched() -> None:
    index = _Index(_hits("a.py"))
    assert repo_context_for("   ", searcher=index) == ""
    assert index.queries == [], "an empty goal should not reach the index"


def test_the_block_is_capped_without_cutting_a_path_in_half() -> None:
    """Half a path points at a file that does not exist."""
    out = render_context(_hits(*[f"some/quite/long/path/number_{i:03d}.py#L1-L40" for i in range(200)]))
    assert len(out) <= MAX_BLOCK_CHARS
    for line in out.splitlines():
        if line.strip().startswith("- "):
            assert line.rstrip().endswith(".py#L1-L40"), f"truncated mid-path: {line!r}"


def test_the_dispatcher_fills_an_empty_definition_with_repo_context(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The prompt itself must carry the hint, or none of this saves a turn."""
    import subprocess

    from thomas.forge.anvil import dispatch_claude_cli as mod

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    monkeypatch.setattr(mod, "repo_context_for", lambda goal: "MARKER: look in branch_claims.py")
    res = mod.dispatch_via_claude_cli(
        "fix the branch claim test",
        cwd=str(tmp_path),
        dry_run=False,
        runner=lambda cmd, cwd, to: (0, ""),
        claude_bin="claude",
    )
    assert "MARKER: look in branch_claims.py" in res.prompt


def test_a_definition_the_caller_wrote_is_never_replaced(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Retrieval is a fallback for silence, not an override of an instruction."""
    import subprocess

    from thomas.forge.anvil import dispatch_claude_cli as mod

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    monkeypatch.setattr(mod, "repo_context_for", lambda goal: "GUESSED CONTEXT")
    res = mod.dispatch_via_claude_cli(
        "fix the branch claim test",
        cwd=str(tmp_path),
        definition="THE CALLER KNOWS BEST",
        dry_run=False,
        runner=lambda cmd, cwd, to: (0, ""),
        claude_bin="claude",
    )
    assert "THE CALLER KNOWS BEST" in res.prompt
    assert "GUESSED CONTEXT" not in res.prompt


def test_a_failing_index_still_lets_the_dispatch_run(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A retrieval failure must never become a task failure."""
    import subprocess

    from thomas.forge.anvil import dispatch_claude_cli as mod

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, capture_output=True)
    monkeypatch.setattr(mod, "repo_context_for", lambda goal: "")
    res = mod.dispatch_via_claude_cli(
        "do the thing",
        cwd=str(tmp_path),
        dry_run=False,
        runner=lambda cmd, cwd, to: (0, ""),
        claude_bin="claude",
    )
    assert res.prompt, "the dispatch still produced a prompt"


def test_an_unbuilt_index_yields_no_context_and_starts_no_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dispatch must not silently start a 250-second repo build.

    `get_rag_index()` builds the whole repository when the store is empty. If a
    dispatch reached for that, the first dispatch on a fresh checkout would
    become the slowest one - the exact problem this module exists to remove.
    """
    from thomas.forge.anvil import task_context as tc

    built: list[str] = []

    class _Empty:
        def status(self) -> dict[str, Any]:
            return {"manifest_files": 0}

        def build(self, *a: Any, **k: Any) -> None:
            built.append("build")

    monkeypatch.setattr(tc, "_INDEX", None)
    monkeypatch.setattr(tc, "_INDEX_TRIED", False)
    monkeypatch.setitem(__import__("sys").modules, "thomas.core.rag_index", type("M", (), {"RagIndex": _Empty}))
    assert tc._shared_index() is None
    assert built == [], "an empty index must not be built from a dispatch"


def test_action_words_are_dropped_from_the_query() -> None:
    """`fix the failing X test` searched verbatim matches nothing; `X` matches."""
    from thomas.forge.anvil.task_context import query_terms

    terms = query_terms("fix the failing branch claims expiry test")
    assert "branch" in terms and "claims" in terms and "expiry" in terms
    for noise in ("fix", "the", "failing"):
        assert noise not in terms


def test_a_single_word_goal_is_still_searched() -> None:
    """A one-word goal must not be silently skipped."""
    index = _Index(_hits("thomas/core/breakglass.py"))
    assert "breakglass.py" in repo_context_for("breakglass", searcher=index)
    assert index.queries, "the index was never asked"


def test_the_query_relaxes_until_something_matches() -> None:
    """Every term must match at once, so an over-long query finds nothing."""

    class _OnlyShort:
        def __init__(self) -> None:
            self.tried: list[str] = []

        def search(self, query: str, k: int = 5, **kw: Any) -> list[dict[str, Any]]:
            self.tried.append(query)
            return _hits("found.py") if len(query.split()) <= 2 else []

    index = _OnlyShort()
    out = repo_context_for("alpha bravo charlie delta", searcher=index)
    assert "found.py" in out
    assert len(index.tried) > 1, "it gave up without relaxing"
    assert len(index.tried[-1].split()) <= 2
