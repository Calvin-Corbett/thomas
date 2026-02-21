import json
from pathlib import Path

from scripts.check_monolith_guard import run_guard


def _write_lines(path: Path, n: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(f"line_{i}\n" for i in range(n))
    path.write_text(text, encoding="utf-8")


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
                "allowed_large_files": {
                    "thomas/server/app.py": {"max_lines": 1320}
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    report = run_guard(repo, baseline_path)
    assert report["ok"] is True
    assert report["violations"] == []
