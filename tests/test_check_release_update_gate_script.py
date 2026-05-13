from __future__ import annotations

import scripts.forge.gates.release_update_gate as mod


def test_product_surface_excludes_architecture_manifest() -> None:
    assert mod._is_product_surface("thomas/_architecture.py") is False


def test_product_surface_excludes_module_audit_manifest() -> None:
    assert mod._is_product_surface("thomas/observability/module_audit.py") is False


def test_product_surface_includes_runtime_module_code() -> None:
    assert mod._is_product_surface("thomas/server/app.py") is True


def test_manual_changed_files_skip_git_diff_resolution(monkeypatch, capsys) -> None:
    def _boom(*_args, **_kwargs):
        raise AssertionError("_git_changed_files should not be called when --changed-file is provided")

    monkeypatch.setattr(mod, "_git_changed_files", _boom)

    rc = mod.run(
        [
            "--changed-file",
            "thomas/server/app.py",
            "--changed-file",
            "pyproject.toml",
            "--changed-file",
            "thomas/__init__.py",
            "--changed-file",
            "CHANGELOG.md",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "Release update gate: PASS" in out


def test_release_update_does_not_run_release_hygiene_by_default(monkeypatch, capsys) -> None:
    called = {"value": False}

    def _sentinel():
        called["value"] = True
        return True, "should not run"

    monkeypatch.setattr(mod, "_check_release_hygiene_script", _sentinel)

    rc = mod.run(
        [
            "--changed-file",
            "thomas/server/app.py",
            "--changed-file",
            "pyproject.toml",
            "--changed-file",
            "thomas/__init__.py",
            "--changed-file",
            "CHANGELOG.md",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "Release update gate: PASS" in out
    assert called["value"] is False


def test_release_update_can_explicitly_run_release_hygiene(monkeypatch, capsys) -> None:
    monkeypatch.setattr(mod, "_check_release_hygiene_script", lambda: (False, "release hygiene: FAIL"))

    rc = mod.run(
        [
            "--enforce-release-hygiene",
            "--changed-file",
            "thomas/server/app.py",
            "--changed-file",
            "pyproject.toml",
            "--changed-file",
            "thomas/__init__.py",
            "--changed-file",
            "CHANGELOG.md",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 1
    assert "check_release_hygiene.py failed" in out
    assert "release hygiene: FAIL" in out
