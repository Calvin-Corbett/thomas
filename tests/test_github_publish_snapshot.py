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


def test_filter_publish_paths_excludes_internal_release_only_surfaces(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    filtered = mod._filter_publish_paths(
        repo,
        [
            "README.md",
            "agent_memory/app.py",
            "agent_vf/cli.py",
            "code_intake/README.md",
            "library/entries/architecture/note.md",
            "patches/0001-example.patch",
            "plans/README.md",
            ".github/pull_request_template.md",
            "definitions/model-vs-os.md",
            "docs/evals/2026-02-21_webui_natural_behavior_eval.md",
            "docs/feature_13_dep_scanner.md",
            "tests/test_agent_memory_cli_workflow.py",
            "tests/test_agent_memory_workflow_evals.py",
            "tests/test_code_intake_pipeline.py",
        ],
        respect_repo_hygiene=False,
    )

    assert filtered == ["README.md", "tests/test_code_intake_pipeline.py"]


def test_run_creates_clean_snapshot_repo_and_passes_preflight(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / ".gitignore").write_text(
        ".env\n.thomas/\nruntime/\nthomas.db\nthomas.asset_studio.db\n.env.local\nscripts/local-cache.txt\n",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("hi\n", encoding="utf-8")
    (repo / "thomas.prod.toml").write_text(
        "[server]\naccess_mode='local'\nallow_unauthenticated_version=false\napi_token=''\n\n[tools]\nallow_shell=false\n",
        encoding="utf-8",
    )
    docs_dir = repo / "docs"
    docs_dir.mkdir()
    (docs_dir / "repo_hygiene_baseline.json").write_text(
        json.dumps(
            {
                "allowed_tracked_root_files": ["README.md", ".gitignore", "thomas.prod.toml"],
                "forbidden_tracked_prefixes": ["plans/thomas/"],
                "blocked_tracked_suffixes": [],
            }
        ),
        encoding="utf-8",
    )
    (repo / "plans" / "thomas").mkdir(parents=True)
    (repo / "plans" / "thomas" / "PRIVATE.md").write_text("private task note\n", encoding="utf-8")
    scripts_dir = repo / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "github_publish_preflight.py").write_text(
        "import json, sys\nprint(json.dumps({'ok': True, 'errors': [], 'warnings': [], 'argv': sys.argv[1:]}))\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    (repo / "src").mkdir()
    (repo / "src" / "new_local.py").write_text("x=1\n", encoding="utf-8")
    (repo / "scripts" / "local-cache.txt").write_text("ignored cache\n", encoding="utf-8")

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
    assert (snapshot / "src" / "new_local.py").exists()
    assert not (snapshot / "scripts" / "local-cache.txt").exists()
    assert not (snapshot / "plans" / "thomas" / "PRIVATE.md").exists()
