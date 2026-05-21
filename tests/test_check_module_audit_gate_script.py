from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import scripts.forge.gates.module_audit_gate as mod


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_module_file(tmp_path: Path, rel_path: str, content: str) -> str:
    full = tmp_path / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return hashlib.sha256(full.read_bytes()).hexdigest()


def _set_repo_root(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "ROOT_DIRNAME", tmp_path.name)


def test_module_audit_gate_fails_when_changed_file_not_covered(tmp_path: Path, monkeypatch, capsys) -> None:
    _set_repo_root(monkeypatch, tmp_path)
    _write_module_file(tmp_path, "thomas/models/discovery.py", "print('ok')\n")

    registry = {
        "latest_by_module": {
            "models": {
                "auditor": "qa",
                "status": "pass",
                "audited_at": _now_iso(),
                "signature": "abc123",
                "files_touched": [],
                "file_hashes": {},
            }
        }
    }
    monkeypatch.setattr(mod, "load_registry", lambda _path: registry)

    rc = mod.run(
        [
            "--changed-file",
            "thomas/models/discovery.py",
            "--changed-file",
            "docs/ops/module_audit_log.json",
            "--changed-file",
            "CHANGELOG.md",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 1
    assert "does not cover changed file(s)" in out


def test_module_audit_gate_fails_on_hash_mismatch(tmp_path: Path, monkeypatch, capsys) -> None:
    _set_repo_root(monkeypatch, tmp_path)
    _write_module_file(tmp_path, "thomas/models/discovery.py", "print('new content')\n")

    registry = {
        "latest_by_module": {
            "models": {
                "auditor": "qa",
                "status": "pass",
                "audited_at": _now_iso(),
                "signature": "abc123",
                "files_touched": ["thomas/models/discovery.py"],
                "file_hashes": {"thomas/models/discovery.py": "0" * 64},
            }
        }
    }
    monkeypatch.setattr(mod, "load_registry", lambda _path: registry)

    rc = mod.run(
        [
            "--changed-file",
            "thomas/models/discovery.py",
            "--changed-file",
            "docs/ops/module_audit_log.json",
            "--changed-file",
            "CHANGELOG.md",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 1
    assert "stale hash" in out


def test_module_audit_gate_passes_with_covered_matching_hash(tmp_path: Path, monkeypatch, capsys) -> None:
    _set_repo_root(monkeypatch, tmp_path)
    digest = _write_module_file(tmp_path, "thomas/models/discovery.py", "print('ok')\n")

    registry = {
        "latest_by_module": {
            "models": {
                "auditor": "qa",
                "status": "pass",
                "audited_at": _now_iso(),
                "signature": "abc123",
                "files_touched": ["thomas/models/discovery.py"],
                "file_hashes": {"thomas/models/discovery.py": digest},
            }
        }
    }
    monkeypatch.setattr(mod, "load_registry", lambda _path: registry)

    rc = mod.run(
        [
            "--changed-file",
            "thomas/models/discovery.py",
            "--changed-file",
            "docs/ops/module_audit_log.json",
            "--changed-file",
            "CHANGELOG.md",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0, out
    assert "Module audit gate: OK" in out
