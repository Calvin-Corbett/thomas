from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    repo_root = Path(__file__).resolve().parents[1]
    return repo_root


def _load_module(module_name: str, relative_path: str):
    repo_root = _repo_root()
    mod_path = repo_root / relative_path
    spec = importlib.util.spec_from_file_location(module_name, mod_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_seed_batch_module():
    repo_root = _repo_root()
    mod_path = repo_root / "scripts" / "forge" / "intake" / "seed_batch.py"
    spec = importlib.util.spec_from_file_location("intake_seed_batch", mod_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_channels_domain_uses_channel_ops_path() -> None:
    mod = _load_seed_batch_module()
    allowed = mod._domain_allowed_paths("channels")
    assert "thomas/cli/commands/channel_ops" in allowed
    assert "thomas/cli/commands/channels.py" in allowed


def test_repo_root_helpers_resolve_project_root() -> None:
    seed_mod = _load_seed_batch_module()
    cli_mod = _load_module("intake_cli", "scripts/forge/intake/cli.py")

    assert seed_mod._repo_root() == _repo_root()
    assert cli_mod._repo_root() == _repo_root()
    assert seed_mod._intake_root(seed_mod._repo_root(), "") == _repo_root() / "code_intake"
    assert cli_mod._intake_root(cli_mod._repo_root(), "") == _repo_root() / "code_intake"


def test_load_rows_uses_non_competitor_fixture(tmp_path: Path) -> None:
    mod = _load_seed_batch_module()
    index = tmp_path / "batch_index.csv"
    index.write_text(
        "prompt_id,batch,lane,domain,title\n"
        "P002,B99,core,channels,Channel routing cleanup\n"
        "P001,B99,core,browser,Browser command cleanup\n"
        "P003,B98,core,plugins,Plugin cleanup\n",
        encoding="utf-8",
    )

    rows = mod._load_rows(index, "B99")

    assert [row["prompt_id"] for row in rows] == ["P001", "P002"]
    assert rows[0]["title"] == "Browser command cleanup"


def test_seed_batch_missing_index_does_not_create_intake_layout(tmp_path: Path) -> None:
    repo_root = _repo_root()
    root = tmp_path / "code_intake"
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/forge/intake/seed_batch.py",
            "--root",
            str(root),
            "--index",
            str(tmp_path / "missing.csv"),
            "--batch-id",
            "B99",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 2
    assert "error: index not found:" in proc.stdout
    assert not root.exists()


def test_seed_batch_direct_dry_run_uses_repo_root_intake(tmp_path: Path) -> None:
    repo_root = _repo_root()
    index = tmp_path / "batch_index.csv"
    index.write_text(
        "prompt_id,batch,lane,domain,title\nP001,B99,core,channels,Channel routing cleanup\n",
        encoding="utf-8",
    )

    proc = subprocess.run(
        [
            sys.executable,
            "scripts/forge/intake/seed_batch.py",
            "--index",
            str(index),
            "--batch-id",
            "B99",
            "--dry-run",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    assert f"incoming_dir: {repo_root / 'code_intake' / 'queue' / 'incoming'}" in proc.stdout
    assert not (repo_root / "scripts" / "forge" / "code_intake").exists()


def test_cli_direct_status_uses_repo_root_intake() -> None:
    repo_root = _repo_root()
    proc = subprocess.run(
        [sys.executable, "scripts/forge/intake/cli.py", "status"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    assert f"intake_root: {repo_root / 'code_intake'}" in proc.stdout
    assert not (repo_root / "scripts" / "forge" / "code_intake").exists()
