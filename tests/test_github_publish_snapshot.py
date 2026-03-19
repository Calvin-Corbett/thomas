from __future__ import annotations

import json
import subprocess
from pathlib import Path

import scripts.github_publish_snapshot as mod


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return str(proc.stdout or "")


def test_copy_snapshot_paths_copies_existing_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    (repo / "sub" / "app.py").parent.mkdir(parents=True, exist_ok=True)
    (repo / "sub" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    out = tmp_path / "snapshot"
    out.mkdir()

    copied = mod._copy_snapshot_paths(repo, out, ["README.md", "sub/app.py", "missing.txt"])

    assert copied == ["README.md", "sub/app.py"]
    assert (out / "README.md").read_text(encoding="utf-8") == "hello\n"
    assert (out / "sub" / "app.py").exists()


def test_filter_publish_paths_respects_repo_hygiene_baseline(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    docs = repo / "docs"
    docs.mkdir()
    (docs / "repo_hygiene_baseline.json").write_text(
        json.dumps(
            {
                "allowed_tracked_root_files": ["README.md"],
                "forbidden_tracked_prefixes": ["runtime/"],
                "blocked_tracked_suffixes": [".log"],
            }
        ),
        encoding="utf-8",
    )

    filtered = mod._filter_publish_paths(
        repo,
        ["README.md", "ARCHITECTURE.md", "runtime/cache.json", "notes.log", "src/app.py"],
        respect_repo_hygiene=True,
    )

    assert filtered == ["README.md", "src/app.py"]


def test_run_creates_clean_snapshot_repo_and_passes_preflight(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / ".gitignore").write_text(
        ".env\n.thomas/\nruntime/\nthomas.db\nthomas.asset_studio.db\n.env.local\n", encoding="utf-8"
    )
    (repo / "README.md").write_text("hi\n", encoding="utf-8")
    (repo / "thomas.prod.toml").write_text(
        "[server]\naccess_mode='local'\nallow_unauthenticated_version=false\napi_token=''\n\n[tools]\nallow_shell=false\n",
        encoding="utf-8",
    )
    scripts_dir = repo / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "github_publish_preflight.py").write_text(
        "import json, sys\nprint(json.dumps({'ok': True, 'errors': [], 'warnings': [], 'argv': sys.argv[1:]}))\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    (repo / "new_local.py").write_text("x=1\n", encoding="utf-8")

    snapshot = tmp_path / "snapshot"
    rc = mod.run(
        [
            "--repo-root",
            str(repo),
            "--output-root",
            str(snapshot),
            "--json",
        ]
    )

    status = _git(snapshot, "status", "--short")
    branches = set(line.strip() for line in _git(snapshot, "branch", "--format=%(refname:short)").splitlines())

    assert rc == 0
    assert status.strip() == ""
    assert {"dev", "prod"}.issubset(branches)
    assert (snapshot / "new_local.py").exists()
