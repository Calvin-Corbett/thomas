import json
import subprocess
from pathlib import Path

from scripts.forge.gates.monolith_guard import run_guard


def _write_lines(path: Path, n: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(f"line_{i}\n" for i in range(n))
    path.write_text(text, encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_git_repo(repo: Path) -> None:
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")


def test_monolith_guard_fails_for_unbaselined_oversized_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_lines(repo / "thomas" / "feature" / "huge_module.py", 1210)
    baseline_path = repo / "docs" / "monolith_guard_baseline.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(
            {
                "version": 1,
                "scan_roots": ["thomas"],
                "hard_limits": {"py": 1200},
                "waiver_policy": {
                    "require_metadata": True,
                    "allow_legacy_reason": False,
                    "default_owner": "qa",
                    "default_expires_on": "2099-12-31",
                    "default_max_growth_lines": 0,
                },
                "allowed_large_files": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    report = run_guard(repo, baseline_path)
    assert report["ok"] is False
    assert len(report["violations"]) == 1
    assert report["violations"][0]["path"] == "thomas/feature/huge_module.py"


def test_monolith_guard_allows_baselined_legacy_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_lines(repo / "thomas" / "server" / "app.py", 1300)
    baseline_path = repo / "docs" / "monolith_guard_baseline.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(
            {
                "version": 1,
                "scan_roots": ["thomas"],
                "hard_limits": {"py": 1200},
                "waiver_policy": {
                    "require_metadata": True,
                    "allow_legacy_reason": False,
                    "default_owner": "qa",
                    "default_expires_on": "2099-12-31",
                    "default_max_growth_lines": 0,
                },
                "allowed_large_files": {
                    "thomas/server/app.py": {"max_lines": 1320, "reason": "monolith debt decomposition in progress"}
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    report = run_guard(repo, baseline_path)
    assert report["ok"] is True
    assert report["violations"] == []


def test_monolith_guard_growth_cap_passes_within_threshold(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _init_git_repo(repo)
    _write_lines(repo / "thomas" / "server" / "app.py", 130)
    baseline_path = repo / "docs" / "monolith_guard_baseline.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(
            {
                "version": 1,
                "scan_roots": ["thomas"],
                "hard_limits": {"py": 120},
                "waiver_policy": {
                    "require_metadata": True,
                    "allow_legacy_reason": False,
                    "default_owner": "qa",
                    "default_expires_on": "2099-12-31",
                    "default_max_growth_lines": 0,
                },
                "allowed_large_files": {
                    "thomas/server/app.py": {
                        "max_lines": 160,
                        "max_growth_lines": 5,
                        "reason": "monolith debt decomposition in progress",
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")

    _write_lines(repo / "thomas" / "server" / "app.py", 135)
    _git(repo, "add", "thomas/server/app.py")
    _git(repo, "commit", "-m", "small growth")

    report = run_guard(repo, baseline_path, base_ref="HEAD~1", head_ref="HEAD")
    assert report["ok"] is True
    assert report["violations"] == []


def test_monolith_guard_growth_cap_fails_when_exceeded(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _init_git_repo(repo)
    _write_lines(repo / "thomas" / "server" / "app.py", 130)
    baseline_path = repo / "docs" / "monolith_guard_baseline.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(
            {
                "version": 1,
                "scan_roots": ["thomas"],
                "hard_limits": {"py": 120},
                "waiver_policy": {
                    "require_metadata": True,
                    "allow_legacy_reason": False,
                    "default_owner": "qa",
                    "default_expires_on": "2099-12-31",
                    "default_max_growth_lines": 0,
                },
                "allowed_large_files": {
                    "thomas/server/app.py": {
                        "max_lines": 200,
                        "max_growth_lines": 5,
                        "reason": "monolith debt decomposition in progress",
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")

    _write_lines(repo / "thomas" / "server" / "app.py", 142)
    _git(repo, "add", "thomas/server/app.py")
    _git(repo, "commit", "-m", "large growth")

    report = run_guard(repo, baseline_path, base_ref="HEAD~1", head_ref="HEAD")
    assert report["ok"] is False
    reasons = {str(v.get("reason")) for v in report["violations"]}
    assert "baselined file exceeded max_growth_lines" in reasons


def test_monolith_guard_rejects_legacy_wording_in_waiver_reason(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _write_lines(repo / "thomas" / "server" / "app.py", 1300)
    baseline_path = repo / "docs" / "monolith_guard_baseline.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(
            {
                "version": 1,
                "scan_roots": ["thomas"],
                "hard_limits": {"py": 1200},
                "waiver_policy": {
                    "require_metadata": True,
                    "allow_legacy_reason": False,
                    "default_owner": "qa",
                    "default_expires_on": "2099-12-31",
                    "default_max_growth_lines": 0,
                },
                "allowed_large_files": {
                    "thomas/server/app.py": {"max_lines": 1320, "reason": "legacy hotspot, split later"}
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    report = run_guard(repo, baseline_path)
    assert report["ok"] is False
    reasons = {str(v.get("reason")) for v in report["violations"]}
    assert "baselined waiver reason uses forbidden 'legacy' wording" in reasons


def test_monolith_guard_growth_defaults_to_zero_when_missing(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _init_git_repo(repo)
    _write_lines(repo / "thomas" / "server" / "app.py", 130)
    baseline_path = repo / "docs" / "monolith_guard_baseline.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(
            {
                "version": 1,
                "scan_roots": ["thomas"],
                "hard_limits": {"py": 120},
                "waiver_policy": {
                    "require_metadata": True,
                    "allow_legacy_reason": False,
                    "default_owner": "qa",
                    "default_expires_on": "2099-12-31",
                    "default_max_growth_lines": 0,
                },
                "allowed_large_files": {
                    "thomas/server/app.py": {
                        "max_lines": 200,
                        "reason": "monolith debt decomposition in progress",
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")

    _write_lines(repo / "thomas" / "server" / "app.py", 131)
    _git(repo, "add", "thomas/server/app.py")
    _git(repo, "commit", "-m", "growth")

    report = run_guard(repo, baseline_path, base_ref="HEAD~1", head_ref="HEAD")
    assert report["ok"] is False
    reasons = {str(v.get("reason")) for v in report["violations"]}
    assert "baselined file exceeded max_growth_lines" in reasons


def test_monolith_guard_staged_only_ignores_unstaged_oversized_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _init_git_repo(repo)
    _write_lines(repo / "thomas" / "safe.py", 10)
    baseline_path = repo / "docs" / "monolith_guard_baseline.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(
            {
                "version": 1,
                "scan_roots": ["thomas"],
                "hard_limits": {"py": 1200},
                "waiver_policy": {
                    "require_metadata": True,
                    "allow_legacy_reason": False,
                    "default_owner": "qa",
                    "default_expires_on": "2099-12-31",
                    "default_max_growth_lines": 0,
                },
                "allowed_large_files": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")

    _write_lines(repo / "thomas" / "safe.py", 11)
    _write_lines(repo / "thomas" / "oversized.py", 1300)
    _git(repo, "add", "thomas/safe.py")

    report = run_guard(repo, baseline_path, staged_only=True)
    assert report["ok"] is True
    assert report["violations"] == []
    assert report["growth_context"].get("staged_only") is True
    assert int(report["measured_count"]) == 1


def test_monolith_guard_staged_only_fails_for_staged_oversized_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _init_git_repo(repo)
    _write_lines(repo / "thomas" / "safe.py", 10)
    baseline_path = repo / "docs" / "monolith_guard_baseline.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(
            {
                "version": 1,
                "scan_roots": ["thomas"],
                "hard_limits": {"py": 1200},
                "waiver_policy": {
                    "require_metadata": True,
                    "allow_legacy_reason": False,
                    "default_owner": "qa",
                    "default_expires_on": "2099-12-31",
                    "default_max_growth_lines": 0,
                },
                "allowed_large_files": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")

    _write_lines(repo / "thomas" / "oversized.py", 1300)
    _git(repo, "add", "thomas/oversized.py")

    report = run_guard(repo, baseline_path, staged_only=True)
    assert report["ok"] is False
    assert any(v.get("path") == "thomas/oversized.py" for v in report["violations"])


def test_monolith_guard_staged_only_enforces_growth_against_head_by_default(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _init_git_repo(repo)
    _write_lines(repo / "thomas" / "server" / "app.py", 130)

    baseline_path = repo / "docs" / "monolith_guard_baseline.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(
            {
                "version": 1,
                "scan_roots": ["thomas"],
                "hard_limits": {"py": 120},
                "waiver_policy": {
                    "require_metadata": True,
                    "allow_legacy_reason": False,
                    "default_owner": "qa",
                    "default_expires_on": "2099-12-31",
                    "default_max_growth_lines": 0,
                },
                "allowed_large_files": {
                    "thomas/server/app.py": {
                        "max_lines": 200,
                        "max_growth_lines": 5,
                        "reason": "monolith debt decomposition in progress",
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")

    _write_lines(repo / "thomas" / "server" / "app.py", 136)
    _git(repo, "add", "thomas/server/app.py")

    report = run_guard(repo, baseline_path, staged_only=True)
    assert report["ok"] is False
    assert any(str(v.get("reason")) == "baselined file exceeded max_growth_lines" for v in report["violations"])


def test_monolith_guard_soft_limit_fails_for_changed_unbaselined_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _init_git_repo(repo)
    _write_lines(repo / "thomas" / "medium.py", 805)
    baseline_path = repo / "docs" / "monolith_guard_baseline.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(
            {
                "version": 1,
                "scan_roots": ["thomas"],
                "hard_limits": {"py": 1200},
                "waiver_policy": {
                    "require_metadata": True,
                    "allow_legacy_reason": False,
                    "default_owner": "qa",
                    "default_expires_on": "2099-12-31",
                    "default_max_growth_lines": 0,
                    "unbaselined_soft_limit_lines": 800,
                    "enforce_soft_limit_changed_only": True,
                },
                "allowed_large_files": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")

    _write_lines(repo / "thomas" / "medium.py", 806)
    _git(repo, "add", "thomas/medium.py")
    _git(repo, "commit", "-m", "changed soft-limit file")

    report = run_guard(repo, baseline_path, base_ref="HEAD~1", head_ref="HEAD")
    assert report["ok"] is False
    reasons = {str(v.get("reason")) for v in report["violations"]}
    assert "changed file exceeds soft limit and is not baselined" in reasons


def test_monolith_guard_soft_limit_ignores_unchanged_unbaselined_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _init_git_repo(repo)
    _write_lines(repo / "thomas" / "medium.py", 805)
    _write_lines(repo / "thomas" / "small.py", 10)
    baseline_path = repo / "docs" / "monolith_guard_baseline.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(
            {
                "version": 1,
                "scan_roots": ["thomas"],
                "hard_limits": {"py": 1200},
                "waiver_policy": {
                    "require_metadata": True,
                    "allow_legacy_reason": False,
                    "default_owner": "qa",
                    "default_expires_on": "2099-12-31",
                    "default_max_growth_lines": 0,
                    "unbaselined_soft_limit_lines": 800,
                    "enforce_soft_limit_changed_only": True,
                },
                "allowed_large_files": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")

    _write_lines(repo / "thomas" / "small.py", 11)
    _git(repo, "add", "thomas/small.py")
    _git(repo, "commit", "-m", "unrelated change")

    report = run_guard(repo, baseline_path, base_ref="HEAD~1", head_ref="HEAD")
    assert report["ok"] is True
    assert report["violations"] == []


def test_monolith_guard_soft_limit_applies_in_staged_only_mode(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _init_git_repo(repo)
    _write_lines(repo / "thomas" / "small.py", 10)
    baseline_path = repo / "docs" / "monolith_guard_baseline.json"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        json.dumps(
            {
                "version": 1,
                "scan_roots": ["thomas"],
                "hard_limits": {"py": 1200},
                "waiver_policy": {
                    "require_metadata": True,
                    "allow_legacy_reason": False,
                    "default_owner": "qa",
                    "default_expires_on": "2099-12-31",
                    "default_max_growth_lines": 0,
                    "unbaselined_soft_limit_lines": 800,
                    "enforce_soft_limit_changed_only": True,
                },
                "allowed_large_files": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")

    _write_lines(repo / "thomas" / "soft_limit.py", 802)
    _git(repo, "add", "thomas/soft_limit.py")

    report = run_guard(repo, baseline_path, staged_only=True)
    assert report["ok"] is False
    reasons = {str(v.get("reason")) for v in report["violations"]}
    assert "changed file exceeds soft limit and is not baselined" in reasons
