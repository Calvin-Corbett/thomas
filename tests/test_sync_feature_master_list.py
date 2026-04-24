from __future__ import annotations

import json
from pathlib import Path

import scripts.sync_feature_master_list as mod


def _write_manifest(repo_root: Path) -> Path:
    manifest = {
        "foundation": [
            {
                "name": "Core Ready",
                "location": "thomas/core/module.py",
                "code_paths": ["thomas/core/module.py"],
            },
            {
                "name": "Core Pack",
                "location": "thomas/core/inbox_module.py",
                "source_pack_globs": ["source_packs/core-pack-*.zip"],
            },
            {
                "name": "Core Missing",
                "location": "thomas/core/missing_module.py",
            },
        ],
        "features": [
            {
                "id": 1,
                "name": "Feature Ready",
                "location": "thomas/features/ready.py",
                "code_paths": ["thomas/features/ready.py"],
            },
            {
                "id": 2,
                "name": "Feature Missing",
                "location": "thomas/features/missing.py",
            },
        ],
        "source_packs": [
            {
                "name": "Candidate Pack",
                "source_zip": "source_packs/pack.zip",
                "source_pack_globs": ["source_packs/pack.zip"],
            }
        ],
    }
    manifest_path = repo_root / "docs" / "feature_master_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _seed_repo_files(repo_root: Path) -> None:
    (repo_root / "thomas" / "core").mkdir(parents=True, exist_ok=True)
    (repo_root / "thomas" / "features").mkdir(parents=True, exist_ok=True)
    (repo_root / "source_packs").mkdir(parents=True, exist_ok=True)
    (repo_root / "thomas" / "core" / "module.py").write_text("x = 1\n", encoding="utf-8")
    (repo_root / "thomas" / "features" / "ready.py").write_text("y = 1\n", encoding="utf-8")
    (repo_root / "source_packs" / "core-pack-01.zip").write_text("zip", encoding="utf-8")
    (repo_root / "source_packs" / "pack.zip").write_text("zip", encoding="utf-8")


def test_build_document_computes_expected_status_counts(tmp_path: Path) -> None:
    _seed_repo_files(tmp_path)
    manifest_path = _write_manifest(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    doc, totals = mod.build_document(tmp_path, manifest, date_stamp="2026-02-25")

    assert totals[mod.STATUS_DONE] == 2
    assert totals[mod.STATUS_PACK_FOUND] == 2
    assert totals[mod.STATUS_MISSING] == 2
    assert "**Last Updated:** 2026-02-25" in doc


def test_run_check_fails_when_master_is_stale(tmp_path: Path, capsys) -> None:
    _seed_repo_files(tmp_path)
    _write_manifest(tmp_path)
    master_path = tmp_path / "docs" / "FEATURE_MASTER_LIST.md"
    master_path.parent.mkdir(parents=True, exist_ok=True)
    master_path.write_text("stale", encoding="utf-8")

    rc = mod.run(["--repo-root", str(tmp_path), "--check"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "Feature master sync gate FAILED" in out


def test_run_updates_master_and_then_check_passes(tmp_path: Path, capsys) -> None:
    _seed_repo_files(tmp_path)
    _write_manifest(tmp_path)
    master_path = tmp_path / "docs" / "FEATURE_MASTER_LIST.md"
    master_path.parent.mkdir(parents=True, exist_ok=True)
    master_path.write_text("stale", encoding="utf-8")

    rc_update = mod.run(["--repo-root", str(tmp_path)])
    out_update = capsys.readouterr().out
    assert rc_update == 0
    assert "Feature master list updated:" in out_update
    assert "stale" not in master_path.read_text(encoding="utf-8")

    rc_check = mod.run(["--repo-root", str(tmp_path), "--check"])
    out_check = capsys.readouterr().out
    assert rc_check == 0
    assert "Feature master sync gate: OK" in out_check


def test_run_json_output_reports_action_and_totals(tmp_path: Path, capsys) -> None:
    _seed_repo_files(tmp_path)
    _write_manifest(tmp_path)
    master_path = tmp_path / "docs" / "FEATURE_MASTER_LIST.md"
    master_path.parent.mkdir(parents=True, exist_ok=True)
    master_path.write_text("", encoding="utf-8")

    rc = mod.run(["--repo-root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["ok"] is True
    assert payload["gate"] == "feature_master_sync"
    assert payload["action"] in {"updated", "already up to date"}
    assert payload["totals"][mod.STATUS_DONE] == 2
    assert payload["totals"][mod.STATUS_PACK_FOUND] == 2
    assert payload["totals"][mod.STATUS_MISSING] == 2


def test_run_check_json_reports_stale_payload(tmp_path: Path, capsys) -> None:
    _seed_repo_files(tmp_path)
    _write_manifest(tmp_path)
    master_path = tmp_path / "docs" / "FEATURE_MASTER_LIST.md"
    master_path.parent.mkdir(parents=True, exist_ok=True)
    master_path.write_text("stale", encoding="utf-8")

    rc = mod.run(["--repo-root", str(tmp_path), "--check", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False
    assert payload["gate"] == "feature_master_sync"
    assert payload["stale"] is True
    assert "stale" in payload["error"]


def test_run_check_json_reports_ok_payload(tmp_path: Path, capsys) -> None:
    _seed_repo_files(tmp_path)
    _write_manifest(tmp_path)
    _ = mod.run(["--repo-root", str(tmp_path)])
    _ = capsys.readouterr().out

    rc = mod.run(["--repo-root", str(tmp_path), "--check", "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["ok"] is True
    assert payload["gate"] == "feature_master_sync"
    assert payload["stale"] is False
    assert payload["totals"][mod.STATUS_DONE] == 2


def test_run_json_missing_manifest_reports_error(tmp_path: Path, capsys) -> None:
    rc = mod.run(["--repo-root", str(tmp_path), "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert payload["ok"] is False
    assert payload["gate"] == "feature_master_sync"
    assert "missing manifest" in payload["error"]
