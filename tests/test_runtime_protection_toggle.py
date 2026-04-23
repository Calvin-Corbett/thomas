from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_module():
    path = ROOT / "scripts" / "runtime_protection_toggle.py"
    spec = importlib.util.spec_from_file_location("runtime_protection_toggle", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["runtime_protection_toggle_test"] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


def test_runtime_protection_requires_flag_and_receipt(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(mod, "_state_root", lambda: tmp_path / "state")
    monkeypatch.setattr(mod.time, "time", lambda: 1_000.0)

    flag = mod._flag_path(repo)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("disabled\n", encoding="utf-8")

    assert mod.runtime_protection_is_disabled(repo) is False

    receipt = mod._receipt_path()
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(
        json.dumps(
            {
                "actor": "WORKSTATION\\corbe",
                "method": "windows-credential-dialog",
                "disabled_at": "2026-04-10T20:00:00+0000",
                "expires_at": 1_300.0,
            }
        ),
        encoding="utf-8",
    )

    assert mod.runtime_protection_is_disabled(repo) is True


def test_runtime_protection_rejects_invalid_receipt(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(mod, "_state_root", lambda: tmp_path / "state")

    flag = mod._flag_path(repo)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("disabled\n", encoding="utf-8")

    receipt = mod._receipt_path()
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text('{"actor":"", "method":"windows-credential-dialog", "expires_at": 1300}', encoding="utf-8")

    assert mod.runtime_protection_is_disabled(repo) is False


def test_runtime_protection_rejects_expired_receipt(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(mod, "_state_root", lambda: tmp_path / "state")
    monkeypatch.setattr(mod.time, "time", lambda: 1_000.0)

    flag = mod._flag_path(repo)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("disabled\n", encoding="utf-8")

    receipt = mod._receipt_path()
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(
        json.dumps(
            {
                "actor": "WORKSTATION\\corbe",
                "method": "windows-credential-dialog",
                "disabled_at": "2026-04-10T20:00:00+0000",
                "expires_at": 999.0,
            }
        ),
        encoding="utf-8",
    )

    assert mod.runtime_protection_is_disabled(repo) is False


def test_cmd_off_writes_expiring_receipt(tmp_path: Path, monkeypatch, capsys) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(mod, "_state_root", lambda: tmp_path / "state")
    monkeypatch.setattr(mod, "_authenticate_windows", lambda: True)
    monkeypatch.setenv("USERNAME", "corbe")
    monkeypatch.setattr(mod.time, "time", lambda: 1_000.0)
    monkeypatch.setattr(mod.time, "strftime", lambda fmt, ts=None: "2026-04-13 12:00:00")
    monkeypatch.setattr(mod.time, "localtime", lambda value=None: value)

    rc = mod.cmd_off(repo, minutes=5)

    assert rc == 0
    receipt = json.loads(mod._receipt_path().read_text(encoding="utf-8"))
    assert receipt["duration_minutes"] == 5
    assert receipt["expires_at"] == 1_300.0
    assert mod.runtime_protection_is_disabled(repo) is True
    assert "DISABLED for 5 minute(s)." in capsys.readouterr().out
