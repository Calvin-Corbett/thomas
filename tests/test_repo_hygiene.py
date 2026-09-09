from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.forge.gates.repo_hygiene import (
    evaluate_generated_artifacts,
    evaluate_hygiene,
    evaluate_worktree_change_budget,
    evaluate_worktree_clean,
)


def test_repo_hygiene_detects_unexpected_root_and_forbidden_prefix() -> None:
    baseline = {
        "max_tracked_root_files": 3,
        "allowed_tracked_root_files": [".gitignore", "README.md"],
        "forbidden_tracked_prefixes": ["runtime/", "tasks/"],
        "blocked_tracked_suffixes": [".log"],
    }
    tracked = [
        ".gitignore",
        "README.md",
        "surprise.txt",
        "runtime/cache.db",
        "thomas/server/app.py",
        "notes.log",
    ]

    result = evaluate_hygiene(tracked, baseline)
    assert result["ok"] is False
    assert "surprise.txt" in result["unexpected_root_files"]
    assert "runtime/cache.db" in result["forbidden_tracked_paths"]
    assert "notes.log" in result["blocked_suffix_paths"]


def test_repo_hygiene_passes_clean_layout() -> None:
    baseline = {
        "max_tracked_root_files": 5,
        "allowed_tracked_root_files": [".gitignore", "README.md", "pyproject.toml"],
        "forbidden_tracked_prefixes": ["runtime/"],
        "blocked_tracked_suffixes": [".tmp"],
    }
    tracked = [
        ".gitignore",
        "README.md",
        "pyproject.toml",
        "thomas/core/config.py",
        "tests/test_config.py",
    ]

    result = evaluate_hygiene(tracked, baseline)
    assert result["ok"] is True
    assert not result["violations"]


def test_repo_hygiene_worktree_clean_passes() -> None:
    result = evaluate_worktree_clean([])
    assert result["ok"] is True
    assert result["entry_count"] == 0
    assert result["summary"]["staged_count"] == 0
    assert result["summary"]["unstaged_count"] == 0
    assert result["summary"]["untracked_count"] == 0


def test_repo_hygiene_worktree_dirty_classifies_paths() -> None:
    status_lines = [
        "M  scripts/forge/gates/repo_hygiene.py",
        " M thomas/core/config.py",
        "MM thomas/cli/main.py",
        "?? scratch/local.txt",
    ]
    result = evaluate_worktree_clean(status_lines)
    assert result["ok"] is False
    assert result["summary"]["staged_count"] == 2
    assert result["summary"]["unstaged_count"] == 2
    assert result["summary"]["untracked_count"] == 1
    assert "scripts/forge/gates/repo_hygiene.py" in result["staged_paths"]
    assert "thomas/core/config.py" in result["unstaged_paths"]
    assert "thomas/cli/main.py" in result["staged_paths"]
    assert "thomas/cli/main.py" in result["unstaged_paths"]
    assert "scratch/local.txt" in result["untracked_paths"]


def test_repo_hygiene_generated_artifacts_detects_untracked_noise() -> None:
    baseline = {
        "forbidden_untracked_prefixes": ["output/", "tmp/", "artifacts/"],
        "blocked_untracked_suffixes": [".har", ".tar.gz"],
    }
    untracked_paths = [
        "docs/notes.md",
        "output/run-1/scorecard.json",
        "tmp/cache.db",
        "browser_capture.har",
        "artifacts/snapshots/report.txt",
    ]
    result = evaluate_generated_artifacts(untracked_paths, baseline)
    assert result["ok"] is False
    assert result["offenders"] == [
        "artifacts/snapshots/report.txt",
        "browser_capture.har",
        "output/run-1/scorecard.json",
        "tmp/cache.db",
    ]
    assert result["prefix_matches"] == [
        "artifacts/snapshots/report.txt",
        "output/run-1/scorecard.json",
        "tmp/cache.db",
    ]
    assert result["suffix_matches"] == ["browser_capture.har"]


def test_repo_hygiene_generated_artifacts_no_patterns_noop() -> None:
    result = evaluate_generated_artifacts(["docs/notes.md", "README.md"], {})
    assert result["ok"] is True
    assert result["offenders"] == []


def test_worktree_change_budget_flags_large_uncommitted_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "master"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)

    tracked_file = repo / "thomas" / "core" / "config.py"
    tracked_file.parent.mkdir(parents=True, exist_ok=True)
    tracked_file.write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

    tracked_file.write_text("".join(f"line_{idx} = {idx}\n" for idx in range(520)), encoding="utf-8")
    new_file = repo / "tests" / "test_generated.py"
    new_file.parent.mkdir(parents=True, exist_ok=True)
    new_file.write_text("".join(f"assert {idx} == {idx}\n" for idx in range(320)), encoding="utf-8")

    result = evaluate_worktree_change_budget(
        repo,
        [" M thomas/core/config.py", "?? tests/test_generated.py"],
        max_changed_lines=800,
        ignore_prefixes=["output/"],
    )

    assert result["ok"] is False
    assert result["total_changed_lines"] > 800
    assert result["tracked_total_changed_lines"] > 0
    assert result["untracked_total_changed_lines"] > 0
    assert "uncommitted change budget exceeded" in result["violations"][0]
