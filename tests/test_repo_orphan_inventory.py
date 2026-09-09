from __future__ import annotations

import json
from pathlib import Path

import scripts.repo_orphan_inventory as mod


def test_classify_untracked_generated_artifact_prefix() -> None:
    classified = mod._classify_untracked("output/run-1/result.json", allowed_root=set())
    assert classified["category"] == "generated_artifact"
    assert classified["recommendation"] == "remove"


def test_classify_untracked_root_doc_sprawl() -> None:
    classified = mod._classify_untracked("BUILD_REPORT.md", allowed_root={".gitignore", "README.md"})
    assert classified["category"] == "root_doc_sprawl"
    assert classified["recommendation"] == "archive_or_consolidate"


def test_build_inventory_collects_untracked_and_tracked_debt(tmp_path: Path, monkeypatch) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    baseline = {
        "allowed_tracked_root_files": [".gitignore", "README.md"],
        "forbidden_tracked_prefixes": ["runtime/"],
        "blocked_tracked_suffixes": [".log"],
    }
    baseline_path = repo_root / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")

    monkeypatch.setattr(
        mod,
        "_git_status_porcelain",
        lambda _root: ["?? output/run-1/result.json", "?? BUILD_REPORT.md"],
    )
    monkeypatch.setattr(
        mod,
        "_git_ls_files",
        lambda _root: [".gitignore", "README.md", "runtime/cache.db", "notes.log"],
    )

    payload = mod.build_inventory(repo_root=repo_root, baseline_path=baseline_path)
    assert int(payload["inventory_count"]) == 5
    assert payload["category_counts"]["generated_artifact"] == 1
    assert payload["category_counts"]["root_doc_sprawl"] == 1
    assert payload["category_counts"]["tracked_blocked_suffix"] == 1
    assert payload["category_counts"]["tracked_forbidden_prefix"] == 1
    assert payload["category_counts"]["tracked_root_sprawl"] == 1


def test_run_write_emits_json_and_markdown(tmp_path: Path, monkeypatch, capsys) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir(parents=True, exist_ok=True)
    baseline_path = repo_root / "baseline.json"
    baseline_path.write_text("{}", encoding="utf-8")
    json_output = repo_root / "out" / "inventory.json"
    md_output = repo_root / "out" / "inventory.md"

    monkeypatch.setattr(
        mod,
        "build_inventory",
        lambda **_kwargs: {
            "generated_at_utc": "2026-02-25T00:00:00+00:00",
            "repo_root": str(repo_root),
            "baseline_path": str(baseline_path),
            "worktree_summary": {"staged_count": 0, "unstaged_count": 1, "untracked_count": 1},
            "tracked_total": 5,
            "inventory_count": 1,
            "category_counts": {"untracked_review": 1},
            "recommendation_counts": {"review": 1},
            "sample_paths": ["scratch/note.txt"],
            "entries": [
                {
                    "path": "scratch/note.txt",
                    "source": "untracked",
                    "category": "untracked_review",
                    "recommendation": "review",
                    "reason": "needs decision",
                }
            ],
        },
    )

    rc = mod.run(
        [
            "--repo-root",
            str(repo_root),
            "--baseline",
            str(baseline_path),
            "--json-output",
            str(json_output),
            "--md-output",
            str(md_output),
            "--write",
            "--json",
        ]
    )
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["ok"] is True
    assert json_output.exists()
    assert md_output.exists()
    assert "Repo Orphan Inventory" in md_output.read_text(encoding="utf-8")
