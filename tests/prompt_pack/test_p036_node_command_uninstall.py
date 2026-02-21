from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import subprocess
import sys
from types import ModuleType
from typing import Any

import pytest


def _load_module(dotted: str, file_path: Path) -> ModuleType:
    """Import normally if possible, else load from path."""

    try:
        return importlib.import_module(dotted)
    except ModuleNotFoundError:
        spec = importlib.util.spec_from_file_location(dotted, file_path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        sys.modules[dotted] = mod
        spec.loader.exec_module(mod)  # type: ignore[arg-type]
        return mod


@pytest.fixture()
def core_mod() -> ModuleType:
    repo_root = Path(__file__).resolve().parents[2]
    return _load_module(
        "thomas.nodes.p036_node_command_uninstall",
        repo_root / "thomas" / "nodes" / "p036_node_command_uninstall.py",
    )


@pytest.fixture()
def cli_mod() -> ModuleType:
    repo_root = Path(__file__).resolve().parents[2]
    return _load_module(
        "thomas.cli.commands.nodes.p036_node_command_uninstall",
        repo_root / "thomas" / "cli" / "commands" / "nodes" / "p036_node_command_uninstall.py",
    )


def test_uninstall_success_local(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, core_mod: ModuleType) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "package.json").write_text('{"name":"proj"}', encoding="utf-8")

    calls: dict[str, Any] = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="removed", stderr="")

    monkeypatch.setattr(core_mod.subprocess, "run", fake_run)

    req = core_mod.NodeCommandUninstallRequest(package="lodash", project_dir=str(project_dir), npm_executable="npm")
    result = core_mod.uninstall_node_command(req)

    assert result.package == "lodash"
    assert result.return_code == 0
    assert calls["cmd"] == ["npm", "uninstall", "lodash"]
    assert calls["kwargs"]["cwd"] == str(project_dir.resolve())


def test_uninstall_success_global(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, core_mod: ModuleType) -> None:
    # global uninstall must not require package.json
    calls: dict[str, Any] = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="removed", stderr="")

    monkeypatch.setattr(core_mod.subprocess, "run", fake_run)

    req = core_mod.NodeCommandUninstallRequest(
        package="eslint",
        project_dir=str(tmp_path / "does_not_matter"),
        global_install=True,
        npm_executable="npm",
    )
    result = core_mod.uninstall_node_command(req)

    assert result.project_dir is None
    assert result.global_install is True
    assert calls["cmd"] == ["npm", "uninstall", "-g", "eslint"]
    assert calls["kwargs"].get("cwd") is None


def test_uninstall_missing_package_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, core_mod: ModuleType) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()

    # Ensure subprocess is never called.
    monkeypatch.setattr(core_mod.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not run")))

    req = core_mod.NodeCommandUninstallRequest(package="lodash", project_dir=str(project_dir), npm_executable="npm")
    with pytest.raises(core_mod.NodeCommandUninstallError) as ei:
        core_mod.uninstall_node_command(req)

    assert ei.value.code == "missing_config"


def test_uninstall_invalid_package(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, core_mod: ModuleType) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "package.json").write_text('{"name":"proj"}', encoding="utf-8")

    monkeypatch.setattr(core_mod.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not run")))

    req = core_mod.NodeCommandUninstallRequest(package="--force", project_dir=str(project_dir), npm_executable="npm")
    with pytest.raises(core_mod.NodeCommandUninstallError) as ei:
        core_mod.uninstall_node_command(req)

    assert ei.value.code == "invalid_input"


def test_uninstall_npm_not_found(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, core_mod: ModuleType) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "package.json").write_text('{"name":"proj"}', encoding="utf-8")

    def fake_run(*a, **k):
        raise FileNotFoundError("nope")

    monkeypatch.setattr(core_mod.subprocess, "run", fake_run)

    req = core_mod.NodeCommandUninstallRequest(package="lodash", project_dir=str(project_dir), npm_executable="npm")
    with pytest.raises(core_mod.NodeCommandUninstallError) as ei:
        core_mod.uninstall_node_command(req)

    assert ei.value.code == "npm_not_found"


def test_uninstall_external_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, core_mod: ModuleType) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    (project_dir / "package.json").write_text('{"name":"proj"}', encoding="utf-8")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="boom")

    monkeypatch.setattr(core_mod.subprocess, "run", fake_run)

    req = core_mod.NodeCommandUninstallRequest(package="lodash", project_dir=str(project_dir), npm_executable="npm")
    with pytest.raises(core_mod.NodeCommandUninstallError) as ei:
        core_mod.uninstall_node_command(req)

    assert ei.value.code == "uninstall_failed"
    assert ei.value.details["return_code"] == 2


def test_request_roundtrip(core_mod: ModuleType) -> None:
    payload = {
        "package": "lodash",
        "project_dir": ".",
        "global_install": True,
        "dry_run": True,
        "npm_executable": "npm",
        "timeout_s": 10,
    }
    req = core_mod.NodeCommandUninstallRequest.from_dict(payload)
    assert req.to_dict() == payload


def test_cli_json_success(monkeypatch: pytest.MonkeyPatch, cli_mod: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    # Patch _load_core so we don't depend on a full Thomas environment.
    class StubErr(Exception):
        def __init__(self, code: str, message: str):
            super().__init__(message)
            self.code = code
            self.message = message

        def to_dict(self):
            return {"code": self.code, "message": self.message, "details": {}}

    class StubReq:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class StubRes:
        def __init__(self):
            self.package = "lodash"
            self.global_install = False
            self.project_dir = "/tmp/proj"

        def to_dict(self):
            return {"package": self.package}

    def stub_uninstall(req):
        return StubRes()

    monkeypatch.setattr(
        cli_mod,
        "_load_core",
        lambda: (StubErr, StubReq, stub_uninstall, {"in": True}, {"out": True}),
    )

    args = cli_mod.NodeCommandUninstallCliArgs(
        package="lodash",
        project_dir=".",
        global_install=False,
        dry_run=False,
        npm_executable="npm",
        timeout_s=1,
        json_output=True,
    )
    rc = cli_mod.run(args)
    out = capsys.readouterr().out.strip()

    assert rc == 0
    assert out.startswith("{")
    assert '"ok": true' in out.lower()


def test_cli_json_failure(monkeypatch: pytest.MonkeyPatch, cli_mod: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    class StubErr(Exception):
        def __init__(self, code: str, message: str):
            super().__init__(message)
            self.code = code
            self.message = message

        def to_dict(self):
            return {"code": self.code, "message": self.message, "details": {"x": 1}}

    class StubReq:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    def stub_uninstall(req):
        raise StubErr("uninstall_failed", "boom")

    monkeypatch.setattr(
        cli_mod,
        "_load_core",
        lambda: (StubErr, StubReq, stub_uninstall, {"in": True}, {"out": True}),
    )

    args = cli_mod.NodeCommandUninstallCliArgs(
        package="lodash",
        project_dir=".",
        global_install=False,
        dry_run=False,
        npm_executable="npm",
        timeout_s=1,
        json_output=True,
    )
    rc = cli_mod.run(args)
    out = capsys.readouterr().out.strip()

    assert rc == 1
    assert '"ok": false' in out.lower()
    assert '"code": "uninstall_failed"' in out.lower()
