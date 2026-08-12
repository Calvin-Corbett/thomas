from __future__ import annotations

import json
import subprocess
from pathlib import Path

import scripts.forge.publish.private_markers as private_markers
import scripts.forge.publish.snapshot as mod


def test_private_marker_line_forms_are_exact() -> None:
    assert mod.ACCEPTED_PRIVATE_MARKER_LINES == private_markers.ACCEPTED_PRIVATE_MARKER_LINES
    assert all(mod._line_has_private_marker(f"  {line}  ") for line in mod.ACCEPTED_PRIVATE_MARKER_LINES)
    assert not mod._line_has_private_marker("This public doc mentions THOMAS_PRIVATE in prose.")


def test_private_marker_scan_uses_shared_default_limit(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def fake_path_has_private_marker(repo_root: Path, rel_path: str) -> bool:
        calls.append((repo_root, rel_path))
        return True

    monkeypatch.setattr(mod, "path_has_private_marker", fake_path_has_private_marker)

    assert mod._has_private_marker(tmp_path, "plans/internal.md")
    assert calls == [(tmp_path, "plans/internal.md")]


def test_publishable_normalized_path_skips_private_markers(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "public.py").write_text("print('ok')\n", encoding="utf-8")
    (repo / "private.py").write_text(
        "THOMAS_PRIVATE\nreason: local-only fixture\nowner: codex-upgrade-worker\n",
        encoding="utf-8",
    )

    assert mod._publishable_normalized_path(repo, "public.py") == "public.py"
    assert mod._publishable_normalized_path(repo, "private.py") == ""
    assert mod._publishable_normalized_path(repo, "") == ""


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


def test_filter_publish_paths_excludes_private_marker_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "public.md").write_text("hello\n", encoding="utf-8")
    (repo / "private.md").write_text(
        "# THOMAS_PRIVATE\n# reason: local deployment details\n# owner: codex-upgrade-worker\n",
        encoding="utf-8",
    )
    (repo / "private_note.md").write_text(
        "THOMAS_PRIVATE\nreason: local deployment details\nowner: codex-upgrade-worker\n",
        encoding="utf-8",
    )
    (repo / "private_client.js").write_text(
        "// THOMAS_PRIVATE\n// reason: local deployment details\n// owner: codex-upgrade-worker\n",
        encoding="utf-8",
    )
    (repo / "private_style.css").write_text(
        "/* THOMAS_PRIVATE */\n/* reason: local deployment details */\n/* owner: codex-upgrade-worker */\n",
        encoding="utf-8",
    )
    (repo / "private_preview.html").write_text(
        "<!-- THOMAS_PRIVATE -->\n<!-- reason: local deployment details -->\n<!-- owner: codex-upgrade-worker -->\n",
        encoding="utf-8",
    )
    (repo / "public_marker_docs.md").write_text(
        "This public doc mentions THOMAS_PRIVATE in prose.\n",
        encoding="utf-8",
    )
    docs = repo / "docs"
    docs.mkdir()
    (docs / "trash_marker.md").write_text("THOMAS_PRIVATE\n", encoding="utf-8")

    filtered = mod._filter_publish_paths(
        repo,
        [
            "public.md",
            "private.md",
            "private_client.js",
            "private_note.md",
            "private_preview.html",
            "private_style.css",
            "public_marker_docs.md",
            "docs/trash_marker.md",
        ],
        respect_repo_hygiene=False,
    )

    assert filtered == ["docs/trash_marker.md", "public.md", "public_marker_docs.md"]


def test_remove_private_marker_files_after_directory_copy(tmp_path: Path) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "docs").mkdir()
    (snapshot / "docs" / "trash_marker.md").write_text("THOMAS_PRIVATE\n", encoding="utf-8")
    private_file = snapshot / "thomas" / "local_only.py"
    private_file.parent.mkdir()
    private_file.write_text(
        "# THOMAS_PRIVATE\n# reason: local-only fixture\n# owner: codex-upgrade-worker\n",
        encoding="utf-8",
    )

    removed = mod._remove_private_marker_files(snapshot)

    assert removed == ["thomas/local_only.py"]
    assert not private_file.exists()
    assert (snapshot / "docs" / "trash_marker.md").exists()


def test_run_creates_clean_snapshot_repo_and_passes_preflight(capsys, tmp_path: Path) -> None:
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
    publish_dir = repo / "scripts" / "forge" / "publish"
    publish_dir.mkdir(parents=True)
    (publish_dir / "preflight.py").write_text(
        "import json, sys\nprint(json.dumps({'ok': True, 'errors': [], 'warnings': [], 'argv': sys.argv[1:]}))\n",
        encoding="utf-8",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "init")
    (repo / "new_local.py").write_text("x=1\n", encoding="utf-8")
    private_file = repo / "thomas" / "local_only.py"
    private_file.parent.mkdir(parents=True, exist_ok=True)
    private_file.write_text(
        "THOMAS_PRIVATE\nreason: local-only fixture\nowner: codex-upgrade-worker\n",
        encoding="utf-8",
    )

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
    payload = json.loads(capsys.readouterr().out)

    status = _git(snapshot, "status", "--short")
    branches = set(line.strip() for line in _git(snapshot, "branch", "--format=%(refname:short)").splitlines())

    assert rc == 0
    assert status.strip() == ""
    assert {"dev", "prod"}.issubset(branches)
    assert (snapshot / "new_local.py").exists()
    assert not (snapshot / "thomas" / "local_only.py").exists()
    assert payload["removed_private_marker_file_count"] == 1
    assert payload["removed_private_marker_files"] == ["thomas/local_only.py"]


def test_run_console_reports_removed_private_marker_count(monkeypatch, capsys, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "public.py").write_text("print('ok')\n", encoding="utf-8")
    private_file = repo / "thomas" / "private.py"
    private_file.parent.mkdir()
    private_file.write_text(
        "THOMAS_PRIVATE\nreason: local-only fixture\nowner: codex-upgrade-worker\n",
        encoding="utf-8",
    )

    def _fake_copy_directory_if_present(repo_root: Path, snapshot_root: Path, rel_path: str) -> None:
        if rel_path == "thomas":
            mod.shutil.copytree(repo_root / rel_path, snapshot_root / rel_path, dirs_exist_ok=True)

    monkeypatch.setattr(mod, "_list_git_paths", lambda repo_root, *, include_untracked: ["public.py"])
    monkeypatch.setattr(mod, "_copy_directory_if_present", _fake_copy_directory_if_present)
    monkeypatch.setattr(mod, "_init_snapshot_repo", lambda snapshot_root, *, origin_url: None)
    monkeypatch.setattr(mod, "_current_origin", lambda repo_root: "")
    monkeypatch.setattr(mod, "_run_preflight", lambda snapshot_root, *, deep: {"ok": True})

    snapshot = tmp_path / "snapshot"
    rc = mod.run(["--repo-root", str(repo), "--output-root", str(snapshot)])
    output = capsys.readouterr().out

    assert rc == 0
    assert (snapshot / "public.py").exists()
    assert not (snapshot / "thomas" / "private.py").exists()
    assert "removed private marker files: 1" in output
