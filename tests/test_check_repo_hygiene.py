from __future__ import annotations

import json
from pathlib import Path

import scripts.check_repo_hygiene as mod


def test_evaluate_worktree_clean_partitions_status_lines() -> None:
    payload = mod.evaluate_worktree_clean(
        [
            "M  staged.py",
            " M unstaged.py",
            "MM both.py",
            "?? untracked.txt",
            "!! ignored.tmp",
        ]
    )

    assert payload["ok"] is False
    assert payload["summary"]["staged_count"] == 2
    assert payload["summary"]["unstaged_count"] == 2
    assert payload["summary"]["untracked_count"] == 1
    assert sorted(payload["staged_paths"]) == ["both.py", "staged.py"]
    assert sorted(payload["unstaged_paths"]) == ["both.py", "unstaged.py"]
    assert payload["untracked_paths"] == ["untracked.txt"]


def test_evaluate_generated_artifacts_flags_prefix_and_suffix_matches() -> None:
    baseline = {
        "forbidden_untracked_prefixes": ["output/", "tmp/"],
        "blocked_untracked_suffixes": [".zip", ".har"],
    }
    payload = mod.evaluate_generated_artifacts(
        ["output/run/data.json", "notes.txt", "capture.har", "tmp/scratch.md"],
        baseline,
    )

    assert payload["ok"] is False
    assert "output/run/data.json" in payload["prefix_matches"]
    assert "tmp/scratch.md" in payload["prefix_matches"]
    assert "capture.har" in payload["suffix_matches"]
    assert "notes.txt" not in payload["offenders"]


def test_evaluate_hygiene_flags_root_count_unexpected_and_blocked() -> None:
    baseline = {
        "max_tracked_root_files": 1,
        "allowed_tracked_root_files": ["README.md"],
        "forbidden_tracked_prefixes": ["runtime/"],
        "blocked_tracked_suffixes": [".log"],
    }
    tracked = ["README.md", "EXTRA.md", "runtime/state.json", "logs/build.log"]

    payload = mod.evaluate_hygiene(tracked, baseline)

    assert payload["ok"] is False
    assert any("tracked root file count" in msg for msg in payload["violations"])
    assert "EXTRA.md" in payload["unexpected_root_files"]
    assert "runtime/state.json" in payload["forbidden_tracked_paths"]
    assert "logs/build.log" in payload["blocked_suffix_paths"]


def test_build_synced_baseline_replaces_root_allowlist_and_max() -> None:
    baseline = {
        "version": 2,
        "max_tracked_root_files": 1,
        "allowed_tracked_root_files": ["README.md"],
        "forbidden_tracked_prefixes": ["runtime/"],
    }

    payload = mod.build_synced_baseline(
        baseline,
        ["README.md", "AGENTS.md", "thomas/server/app.py", "README.md"],
    )

    assert payload["max_tracked_root_files"] == 2
    assert payload["allowed_tracked_root_files"] == ["AGENTS.md", "README.md"]
    assert payload["forbidden_tracked_prefixes"] == ["runtime/"]


def test_run_json_error_payload_when_backend_raises(monkeypatch, tmp_path: Path, capsys) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(mod, "_load_baseline", lambda _p: {})
    monkeypatch.setattr(mod, "_git_ls_files", lambda _root: (_ for _ in ()).throw(RuntimeError("boom")))

    rc = mod.run(["--repo-root", str(tmp_path), "--baseline", str(baseline), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["gate"] == "repo_hygiene"
    assert "boom" in payload["error"]


def test_run_json_success_payload_and_no_require_clean_worktree(monkeypatch, tmp_path: Path, capsys) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        mod,
        "_load_baseline",
        lambda _p: {
            "max_tracked_root_files": 100,
            "allowed_tracked_root_files": [],
            "forbidden_tracked_prefixes": [],
            "blocked_tracked_suffixes": [],
            "forbidden_untracked_prefixes": [],
            "blocked_untracked_suffixes": [],
        },
    )
    monkeypatch.setattr(mod, "_git_ls_files", lambda _root: ["thomas/pkg.py"])
    monkeypatch.setattr(mod, "_git_status_porcelain", lambda _root: [" M dirty.py"])
    monkeypatch.setattr(
        mod,
        "evaluate_worktree_change_budget",
        lambda *_args, **_kwargs: {
            "ok": True,
            "threshold": 800,
            "total_changed_lines": 42,
            "violations": [],
        },
    )

    rc = mod.run(
        [
            "--repo-root",
            str(tmp_path),
            "--baseline",
            str(baseline),
            "--no-require-clean-worktree",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["gate"] == "repo_hygiene"
    assert payload["require_clean_worktree"] is False
    assert payload["worktree"]["ok"] is False
    assert payload["status"] == "ok"


def test_run_json_dirty_worktree_is_warning_not_failure(monkeypatch, tmp_path: Path, capsys) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        mod,
        "_load_baseline",
        lambda _p: {
            "max_tracked_root_files": 100,
            "allowed_tracked_root_files": [],
            "forbidden_tracked_prefixes": [],
            "blocked_tracked_suffixes": [],
            "forbidden_untracked_prefixes": [],
            "blocked_untracked_suffixes": [],
        },
    )
    monkeypatch.setattr(mod, "_git_ls_files", lambda _root: ["thomas/pkg.py"])
    monkeypatch.setattr(mod, "_git_status_porcelain", lambda _root: [" M dirty.py"])
    monkeypatch.setattr(
        mod,
        "evaluate_worktree_change_budget",
        lambda *_args, **_kwargs: {
            "ok": True,
            "threshold": 800,
            "total_changed_lines": 42,
            "violations": [],
        },
    )

    rc = mod.run(
        [
            "--repo-root",
            str(tmp_path),
            "--baseline",
            str(baseline),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["status"] == "warning"
    assert payload["warning_count"] == 1
    assert payload["error_count"] == 0
    assert payload["blocking_warnings"] == []
    assert "dirty worktree:" in payload["warnings"][0]


def test_run_json_strict_escalates_warning_to_failure(monkeypatch, tmp_path: Path, capsys) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        mod,
        "_load_baseline",
        lambda _p: {
            "max_tracked_root_files": 100,
            "allowed_tracked_root_files": [],
            "forbidden_tracked_prefixes": [],
            "blocked_tracked_suffixes": [],
            "forbidden_untracked_prefixes": [],
            "blocked_untracked_suffixes": [],
        },
    )
    monkeypatch.setattr(mod, "_git_ls_files", lambda _root: ["thomas/pkg.py"])
    monkeypatch.setattr(mod, "_git_status_porcelain", lambda _root: [" M dirty.py"])
    monkeypatch.setattr(
        mod,
        "evaluate_worktree_change_budget",
        lambda *_args, **_kwargs: {
            "ok": True,
            "threshold": 800,
            "total_changed_lines": 42,
            "violations": [],
        },
    )

    rc = mod.run(
        [
            "--repo-root",
            str(tmp_path),
            "--baseline",
            str(baseline),
            "--json",
            "--strict",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["warning_count"] == 1
    assert payload["error_count"] == 0
    assert len(payload["blocking_warnings"]) == 1
    assert "dirty worktree:" in payload["blocking_warnings"][0]


def test_run_json_change_budget_is_error_even_without_strict(monkeypatch, tmp_path: Path, capsys) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        mod,
        "_load_baseline",
        lambda _p: {
            "max_tracked_root_files": 100,
            "allowed_tracked_root_files": [],
            "forbidden_tracked_prefixes": [],
            "blocked_tracked_suffixes": [],
            "forbidden_untracked_prefixes": [],
            "blocked_untracked_suffixes": [],
        },
    )
    monkeypatch.setattr(mod, "_git_ls_files", lambda _root: ["thomas/pkg.py"])
    monkeypatch.setattr(mod, "_git_status_porcelain", lambda _root: [" M dirty.py"])
    monkeypatch.setattr(
        mod,
        "evaluate_worktree_change_budget",
        lambda *_args, **_kwargs: {
            "ok": False,
            "threshold": 800,
            "total_changed_lines": 1201,
            "violations": [
                "uncommitted change budget exceeded: 1201 changed lines exceeds max_uncommitted_changed_lines=800"
            ],
        },
    )

    rc = mod.run(
        [
            "--repo-root",
            str(tmp_path),
            "--baseline",
            str(baseline),
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["status"] == "error"
    assert payload["warning_count"] == 1
    assert payload["error_count"] == 1
    assert "uncommitted change budget exceeded" in payload["errors"][0]


def test_run_sync_baseline_json_writes_updated_baseline(tmp_path: Path, monkeypatch, capsys) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "version": 2,
                "max_tracked_root_files": 1,
                "allowed_tracked_root_files": ["README.md"],
                "forbidden_tracked_prefixes": ["runtime/"],
                "blocked_tracked_suffixes": [".log"],
                "forbidden_untracked_prefixes": ["tmp/"],
                "blocked_untracked_suffixes": [".zip"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "_git_ls_files", lambda _root: ["README.md", "AGENTS.md", "thomas/pkg.py"])

    rc = mod.run(
        [
            "--repo-root",
            str(tmp_path),
            "--baseline",
            str(baseline),
            "--sync-baseline",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    updated = json.loads(baseline.read_text(encoding="utf-8"))

    assert rc == 0
    assert payload["ok"] is True
    assert payload["action"] == "sync_baseline"
    assert payload["tracked_root_file_count"] == 2
    assert updated["allowed_tracked_root_files"] == ["AGENTS.md", "README.md"]
    assert updated["max_tracked_root_files"] == 2
    assert updated["forbidden_tracked_prefixes"] == ["runtime/"]
