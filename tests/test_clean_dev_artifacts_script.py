from __future__ import annotations

import json
from pathlib import Path

import scripts.clean_dev_artifacts as mod


def test_discover_dev_artifacts_finds_known_patterns(tmp_path: Path) -> None:
    (tmp_path / "%s").write_text("junk", encoding="utf-8")
    (tmp_path / "tmp_companion_phone.png").write_text("img", encoding="utf-8")
    (tmp_path / "thomas").mkdir(parents=True, exist_ok=True)
    (tmp_path / "thomas" / "tmp_script.py").write_text("print('x')", encoding="utf-8")

    found = mod.discover_dev_artifacts(tmp_path)
    assert "%s" in found
    assert "tmp_companion_phone.png" in found
    assert "thomas/tmp_script.py" in found


def test_evaluate_separates_tracked_and_untracked(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "%s").write_text("junk", encoding="utf-8")
    (tmp_path / "tmp_companion_phone.png").write_text("img", encoding="utf-8")
    monkeypatch.setattr(mod, "_git_tracked_paths", lambda _root: {"tmp_companion_phone.png"})

    payload = mod.evaluate(tmp_path, include_tracked=False)
    assert payload["tracked_matches"] == ["tmp_companion_phone.png"]
    assert payload["untracked_matches"] == ["%s"]
    assert payload["removable"] == ["%s"]


def test_run_apply_removes_only_untracked_by_default(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    (root / "%s").write_text("junk", encoding="utf-8")
    (root / "tmp_companion_phone.png").write_text("img", encoding="utf-8")

    monkeypatch.setattr(mod, "ROOT", root)
    monkeypatch.setattr(mod, "_git_tracked_paths", lambda _root: {"tmp_companion_phone.png"})
    monkeypatch.setattr(
        mod,
        "_run_verification_commands",
        lambda _commands, _root: [{"command": "ok", "exit_code": 0, "ok": True}],
    )

    rc = mod.run(["--apply", "--verify-command", "ok", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["removed"] == ["%s"]
    assert not (root / "%s").exists()
    assert (root / "tmp_companion_phone.png").exists()


def test_tracked_dev_artifacts_returns_tracked_matches(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "_git_tracked_paths", lambda _root: {"tmp_companion_phone.png", "README.md"})
    offenders = mod.tracked_dev_artifacts(tmp_path)
    assert offenders == ["tmp_companion_phone.png"]


def test_run_apply_requires_verification_command(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    (root / "%s").write_text("junk", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", root)
    monkeypatch.setattr(mod, "_git_tracked_paths", lambda _root: set())

    rc = mod.run(["--apply", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert "--apply requires at least one --verify-command" in payload["error"]
    assert (root / "%s").exists()


def test_run_apply_aborts_on_failed_verification(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "repo"
    root.mkdir(parents=True, exist_ok=True)
    (root / "%s").write_text("junk", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", root)
    monkeypatch.setattr(mod, "_git_tracked_paths", lambda _root: set())
    monkeypatch.setattr(
        mod,
        "_run_verification_commands",
        lambda _commands, _root: [{"command": "bad", "exit_code": 2, "ok": False}],
    )

    rc = mod.run(["--apply", "--verify-command", "bad", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert "verification failed:" in payload["error"]
    assert payload["removed_count"] == 0
    assert (root / "%s").exists()
