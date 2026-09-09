"""Tests for named multi-root workspaces (CAP-016, Level 2).

Acceptance line: "Add named multi-root workspaces with cross-repo search, edit,
and coordinated PR proof."

All tests are hermetic: throwaway temp repo roots under ``tmp_path``, an
injected file writer to force write failures, and the inert dry-run gateway from
:mod:`thomas.tools.governed_git_pr` so nothing is ever pushed. No network, no
live model.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thomas.tools.governed_git_pr import GatewayResult, PrPayload, default_dry_run_gateway
from thomas.tools.multi_workspace import (
    CoordinatedChange,
    MultiRootWorkspace,
    RepoFileEdit,
    WorkspaceError,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_repo(base: Path, name: str, files: dict[str, str]) -> Path:
    root = base / name
    root.mkdir(parents=True, exist_ok=True)
    for relpath, content in files.items():
        target = root / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


@pytest.fixture
def workspace(tmp_path: Path) -> MultiRootWorkspace:
    """A named workspace grouping two temp repos, each with a shared symbol."""

    _make_repo(
        tmp_path,
        "service_api",
        {
            "app/handler.py": "import shared\n\ndef run():\n    return compute_total(1, 2)\n",
            "README.md": "# service_api\n",
        },
    )
    _make_repo(
        tmp_path,
        "service_worker",
        {
            "worker/job.py": "def process():\n    return compute_total(3, 4)\n",
            "notes/todo.txt": "call compute_total somewhere\n",
        },
    )
    return MultiRootWorkspace.from_pairs(
        "backend-stack",
        [
            ("service_api", tmp_path / "service_api"),
            ("service_worker", tmp_path / "service_worker"),
        ],
    )


# ---------------------------------------------------------------------------
# A named workspace groups 2+ repos
# ---------------------------------------------------------------------------


def test_named_workspace_groups_two_repos(workspace: MultiRootWorkspace) -> None:
    assert workspace.name == "backend-stack"
    assert workspace.repo_names == ("service_api", "service_worker")
    assert len(workspace.roots) == 2
    assert workspace.root_for("service_api").name == "service_api"


def test_workspace_rejects_duplicate_and_empty_repo_names(tmp_path: Path) -> None:
    with pytest.raises(WorkspaceError):
        MultiRootWorkspace(name="w", roots={"": tmp_path})
    ws = MultiRootWorkspace(name="w", roots={"a": tmp_path})
    with pytest.raises(WorkspaceError):
        ws.add_root("a", tmp_path)
    with pytest.raises(WorkspaceError):
        MultiRootWorkspace(name="", roots={})


# ---------------------------------------------------------------------------
# Cross-repo search finds a symbol in both repos
# ---------------------------------------------------------------------------


def test_cross_repo_search_finds_symbol_in_both_repos(workspace: MultiRootWorkspace) -> None:
    result = workspace.search("compute_total", symbol=True)

    by_repo = result.by_repo()
    assert set(by_repo) == {"service_api", "service_worker"}
    assert result.repos_with_hits == ("service_api", "service_worker")

    api_hits = result.hits_in("service_api")
    worker_hits = result.hits_in("service_worker")
    assert any(h.relpath == "app/handler.py" for h in api_hits)
    assert any(h.relpath == "worker/job.py" for h in worker_hits)
    # Every hit line actually contains the symbol.
    assert all("compute_total" in h.line for h in result.hits)


def test_search_is_deterministic_and_sorted(workspace: MultiRootWorkspace) -> None:
    first = workspace.search("compute_total", symbol=True)
    second = workspace.search("compute_total", symbol=True)
    assert first.hits == second.hits
    # Repos appear in sorted order.
    repos_in_order = [h.repo for h in first.hits]
    assert repos_in_order == sorted(repos_in_order)


def test_symbol_search_respects_word_boundaries(tmp_path: Path) -> None:
    _make_repo(tmp_path, "r1", {"a.py": "compute_total()\ncompute_total_v2()\n"})
    ws = MultiRootWorkspace(name="w", roots={"r1": tmp_path / "r1"})
    symbol_hits = ws.search("compute_total", symbol=True).hits
    # Only the bare symbol line matches, not compute_total_v2.
    assert len(symbol_hits) == 1
    assert symbol_hits[0].line_number == 1
    # Substring search matches both.
    assert ws.search("compute_total").total == 2


def test_search_can_filter_by_extension(workspace: MultiRootWorkspace) -> None:
    py_only = workspace.search("compute_total", include_ext=[".py"])
    assert all(h.relpath.endswith(".py") for h in py_only.hits)
    # The worker's todo.txt mention is excluded.
    assert not any(h.relpath.endswith(".txt") for h in py_only.hits)


# ---------------------------------------------------------------------------
# Coordinated cross-repo edit: applies to both, or rolls back both on failure
# ---------------------------------------------------------------------------


def test_coordinated_edit_applies_to_both_repos(workspace: MultiRootWorkspace) -> None:
    edits = [
        RepoFileEdit("service_api", "app/handler.py", "compute_total", "compute_sum"),
        RepoFileEdit("service_worker", "worker/job.py", "compute_total", "compute_sum"),
    ]
    result = workspace.apply_coordinated_edit(edits)

    assert result.applied is True
    assert result.rolled_back is False
    assert result.spanned_multiple_repos is True
    assert result.repos_changed == ("service_api", "service_worker")

    api_text = (workspace.root_for("service_api") / "app/handler.py").read_text(encoding="utf-8")
    worker_text = (workspace.root_for("service_worker") / "worker/job.py").read_text(encoding="utf-8")
    assert "compute_sum" in api_text and "compute_total" not in api_text
    assert "compute_sum" in worker_text and "compute_total" not in worker_text


def test_coordinated_edit_rolls_back_both_on_validation_failure(
    workspace: MultiRootWorkspace,
) -> None:
    api_path = workspace.root_for("service_api") / "app/handler.py"
    worker_path = workspace.root_for("service_worker") / "worker/job.py"
    api_before = api_path.read_text(encoding="utf-8")
    worker_before = worker_path.read_text(encoding="utf-8")

    edits = [
        RepoFileEdit("service_api", "app/handler.py", "compute_total", "compute_sum"),
        # This find string does not exist -> whole coordinated edit is rejected.
        RepoFileEdit("service_worker", "worker/job.py", "NOT_PRESENT_ANYWHERE", "x"),
    ]
    result = workspace.apply_coordinated_edit(edits)

    assert result.applied is False
    assert result.reason and "NOT_PRESENT" in result.reason or "find string" in result.reason
    # Neither file was touched (failure caught before any write).
    assert api_path.read_text(encoding="utf-8") == api_before
    assert worker_path.read_text(encoding="utf-8") == worker_before


def test_coordinated_edit_restores_written_files_on_write_failure(
    workspace: MultiRootWorkspace,
) -> None:
    api_path = workspace.root_for("service_api") / "app/handler.py"
    worker_path = workspace.root_for("service_worker") / "worker/job.py"
    api_before = api_path.read_text(encoding="utf-8")
    worker_before = worker_path.read_text(encoding="utf-8")

    # Injected writer: succeeds for the first (api) file, then fails on the
    # worker file -- proving the already-written api file is restored.
    def flaky_writer(path: Path, text: str) -> None:
        if path == worker_path and "compute_sum" in text:
            raise OSError("disk full (simulated)")
        path.write_text(text, encoding="utf-8")

    edits = [
        RepoFileEdit("service_api", "app/handler.py", "compute_total", "compute_sum"),
        RepoFileEdit("service_worker", "worker/job.py", "compute_total", "compute_sum"),
    ]
    result = workspace.apply_coordinated_edit(edits, writer=flaky_writer)

    assert result.applied is False
    assert result.rolled_back is True
    # Both repos are back to their original content -- no half-applied change.
    assert api_path.read_text(encoding="utf-8") == api_before
    assert worker_path.read_text(encoding="utf-8") == worker_before


def test_coordinated_edit_requires_multiple_repos(workspace: MultiRootWorkspace) -> None:
    single = [RepoFileEdit("service_api", "app/handler.py", "compute_total", "compute_sum")]
    result = workspace.apply_coordinated_edit(single)
    assert result.applied is False
    assert "more than one repo" in (result.reason or "")


def test_coordinated_edit_unknown_repo_aborts(workspace: MultiRootWorkspace) -> None:
    edits = [
        RepoFileEdit("service_api", "app/handler.py", "compute_total", "compute_sum"),
        RepoFileEdit("ghost_repo", "x.py", "a", "b"),
    ]
    api_path = workspace.root_for("service_api") / "app/handler.py"
    before = api_path.read_text(encoding="utf-8")
    result = workspace.apply_coordinated_edit(edits)
    assert result.applied is False
    assert api_path.read_text(encoding="utf-8") == before


# ---------------------------------------------------------------------------
# Coordinated PR plan: linked PR payloads per repo referencing the shared change
# ---------------------------------------------------------------------------


def test_coordinated_pr_plan_yields_linked_payloads_per_repo(
    workspace: MultiRootWorkspace,
) -> None:
    change = CoordinatedChange(
        change_id="CH-42",
        title="Rename compute_total to compute_sum",
        repo_summaries={
            "service_api": "update handler call site",
            "service_worker": "update job call site",
        },
    )

    plan = workspace.plan_coordinated_prs(change)

    # One payload per affected repo.
    assert plan.repos == ("service_api", "service_worker")
    assert len(plan.payloads) == 2

    api_payload = plan.payload_for("service_api")
    worker_payload = plan.payload_for("service_worker")
    assert isinstance(api_payload, PrPayload)

    # Each references the shared change id...
    assert "CH-42" in api_payload.body
    assert "CH-42" in worker_payload.body
    # ...and cross-references the companion repo (linked).
    assert "service_worker" in api_payload.body
    assert "service_api" in worker_payload.body
    # Shared branch across the linked PRs.
    assert api_payload.branch == worker_payload.branch == "coordinated/ch-42"
    assert plan.is_fully_linked() is True


def test_coordinated_pr_plan_uses_injected_dry_run_gateway(
    workspace: MultiRootWorkspace,
) -> None:
    calls: list[str] = []

    def recording_gateway(payload: PrPayload) -> GatewayResult:
        calls.append(payload.title)
        return default_dry_run_gateway(payload)

    change = CoordinatedChange(
        change_id="CH-7",
        title="Coordinated bump",
        repo_summaries={"service_api": "bump", "service_worker": "bump"},
    )
    plan = workspace.plan_coordinated_prs(change, gateway=recording_gateway)

    # Gateway was invoked exactly once per repo, and never pushed.
    assert len(calls) == 2
    assert all(res.pushed is False for res in plan.results.values())
    assert all("[DRY-RUN]" in res.pr_url_or_dryrun for res in plan.results.values())


def test_coordinated_pr_plan_rejects_single_repo_change(workspace: MultiRootWorkspace) -> None:
    change = CoordinatedChange(
        change_id="CH-1",
        title="only one repo",
        repo_summaries={"service_api": "solo"},
    )
    with pytest.raises(WorkspaceError):
        workspace.plan_coordinated_prs(change)


def test_coordinated_pr_plan_rejects_unknown_repo(workspace: MultiRootWorkspace) -> None:
    change = CoordinatedChange(
        change_id="CH-9",
        title="bad repo",
        repo_summaries={"service_api": "ok", "ghost": "nope"},
    )
    with pytest.raises(WorkspaceError):
        workspace.plan_coordinated_prs(change)


# ---------------------------------------------------------------------------
# Workspace round-trips
# ---------------------------------------------------------------------------


def test_workspace_round_trips(workspace: MultiRootWorkspace) -> None:
    data = workspace.to_dict()
    restored = MultiRootWorkspace.from_dict(data)

    assert restored.name == workspace.name
    assert restored.repo_names == workspace.repo_names
    assert restored.to_dict() == data
    # The restored workspace is functionally equivalent: search still works.
    assert restored.search("compute_total", symbol=True).repos_with_hits == (
        "service_api",
        "service_worker",
    )
