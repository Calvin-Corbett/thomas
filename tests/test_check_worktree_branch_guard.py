from __future__ import annotations

from pathlib import Path

import scripts.forge.gates.worktree_branch_guard as mod


def test_topic_branch_passes_without_unmerged_topic_ancestor(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "_topology_violations", lambda _branch: [])
    # Freshness is checked separately (and added later than these tests) — these cover
    # topic-branch stacking, not freshness, so neutralize it to avoid a stale base mock.
    monkeypatch.setattr(mod, "_branch_freshness_failure", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_branch_name", lambda: "codex/feature")
    monkeypatch.setattr(
        mod,
        "_local_branch_names",
        lambda: ["codex/feature", "master", "release/oss-launch", "publish-clean"],
    )
    monkeypatch.setattr(
        mod,
        "_branch_tip",
        lambda name: {
            "codex/feature": "feature-tip",
            "master": "master-tip",
            "release/oss-launch": "release-tip",
            "publish-clean": "publish-tip",
        }.get(name, f"{name}-tip"),
    )
    monkeypatch.setattr(mod, "_is_ancestor", lambda commit, ref: False)

    rc = mod.run([])
    out = capsys.readouterr().out

    assert rc == 0
    assert "no unmerged topic-branch ancestors" in out


def test_topic_branch_fails_when_it_is_stacked_on_unmerged_topic_branch(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "_topology_violations", lambda _branch: [])
    # Freshness is checked separately (and added later than these tests) — these cover
    # topic-branch stacking, not freshness, so neutralize it to avoid a stale base mock.
    monkeypatch.setattr(mod, "_branch_freshness_failure", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_branch_name", lambda: "codex/child")
    monkeypatch.setattr(
        mod,
        "_local_branch_names",
        lambda: ["codex/child", "codex/parent", "master", "release/oss-launch", "publish-clean"],
    )
    monkeypatch.setattr(
        mod,
        "_branch_tip",
        lambda name: {
            "codex/child": "child-tip",
            "codex/parent": "parent-tip",
            "master": "master-tip",
            "release/oss-launch": "release-tip",
            "publish-clean": "publish-tip",
        }.get(name, f"{name}-tip"),
    )

    def fake_is_ancestor(commit: str, ref: str) -> bool:
        return (commit, ref) == ("parent-tip", "child-tip")

    monkeypatch.setattr(mod, "_is_ancestor", fake_is_ancestor)

    rc = mod.run([])
    out = capsys.readouterr().out

    assert rc == 1
    assert "must start directly from canonical base branches" in out
    assert "codex/parent" in out


def test_topic_branch_passes_when_other_topic_branch_is_already_merged_to_master(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "_topology_violations", lambda _branch: [])
    # Freshness is checked separately (and added later than these tests) — these cover
    # topic-branch stacking, not freshness, so neutralize it to avoid a stale base mock.
    monkeypatch.setattr(mod, "_branch_freshness_failure", lambda *a, **k: None)
    monkeypatch.setattr(mod, "_branch_name", lambda: "codex/child")
    monkeypatch.setattr(
        mod,
        "_local_branch_names",
        lambda: ["codex/child", "codex/parent", "master", "release/oss-launch", "publish-clean"],
    )
    monkeypatch.setattr(
        mod,
        "_branch_tip",
        lambda name: {
            "codex/child": "child-tip",
            "codex/parent": "parent-tip",
            "master": "master-tip",
            "release/oss-launch": "release-tip",
            "publish-clean": "publish-tip",
        }.get(name, f"{name}-tip"),
    )

    def fake_is_ancestor(commit: str, ref: str) -> bool:
        return (commit, ref) in {
            ("parent-tip", "child-tip"),
            ("parent-tip", "master-tip"),
        }

    monkeypatch.setattr(mod, "_is_ancestor", fake_is_ancestor)

    rc = mod.run([])
    out = capsys.readouterr().out

    assert rc == 0
    assert "no unmerged topic-branch ancestors" in out


def test_side_clone_root_fails_topology_guard(monkeypatch, capsys, tmp_path: Path) -> None:
    clone_root = tmp_path / "thomas_side_clone"
    clone_root.mkdir()
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv(mod.DISABLE_ENV, raising=False)
    monkeypatch.setattr(mod, "ROOT", clone_root)
    monkeypatch.setattr(mod, "_runtime_protection_disabled", lambda: False)
    monkeypatch.setattr(mod, "_branch_name", lambda: "codex/side-proof")
    monkeypatch.setattr(mod, "_git_common_dir", lambda: str(clone_root / ".git"))
    monkeypatch.setattr(mod, "_overlay", lambda: {"primary_root": r"C:\Users\corbe\Thomas"})

    rc = mod.run([])
    out = capsys.readouterr().out

    assert rc == 1
    assert "side clone detected" in out
    assert "canonical Thomas git database" in out


def test_unapproved_linked_worktree_root_fails_topology_guard(monkeypatch, capsys, tmp_path: Path) -> None:
    linked_root = tmp_path / "unapproved_worktree"
    linked_root.mkdir()
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv(mod.DISABLE_ENV, raising=False)
    monkeypatch.setattr(mod, "ROOT", linked_root)
    monkeypatch.setattr(mod, "_runtime_protection_disabled", lambda: False)
    monkeypatch.setattr(mod, "_branch_name", lambda: "codex/unapproved")
    monkeypatch.setattr(mod, "_git_common_dir", lambda: r"C:\Users\corbe\Thomas\.git")
    monkeypatch.setattr(mod, "_overlay", lambda: {"primary_root": r"C:\Users\corbe\Thomas"})

    rc = mod.run([])
    out = capsys.readouterr().out

    assert rc == 1
    assert "unapproved linked worktree detected" in out


def test_approved_root_with_canonical_git_database_passes_topology_guard(monkeypatch, capsys) -> None:
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv(mod.DISABLE_ENV, raising=False)
    monkeypatch.setattr(mod, "ROOT", Path(r"C:\Users\corbe\Thomas"))
    monkeypatch.setattr(mod, "_runtime_protection_disabled", lambda: False)
    monkeypatch.setattr(mod, "_branch_name", lambda: "master")
    monkeypatch.setattr(mod, "_git_common_dir", lambda: r"C:\Users\corbe\Thomas\.git")
    monkeypatch.setattr(
        mod,
        "_overlay",
        lambda: {"primary_root": r"C:\Users\corbe\Thomas", "expected_by_branch": {"master": r"C:\Users\corbe\Thomas"}},
    )
    monkeypatch.setattr(mod, "_branch_freshness_failure", lambda *a, **k: None)
    # This test uses the real repo root where QuickBuilder may be ON (which would SKIP the
    # gate); neutralize it so the test deterministically exercises the topology/PASS path.
    import scripts.forge.gates._quickbuilder_guard as _qb

    monkeypatch.setattr(_qb, "announce_suppressed", lambda *a, **k: False)

    rc = mod.run([])
    out = capsys.readouterr().out

    assert rc == 0
    assert "expected worktree path" in out
