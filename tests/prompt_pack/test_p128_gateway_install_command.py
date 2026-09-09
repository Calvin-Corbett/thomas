import json
import zipfile
from pathlib import Path

import pytest

from thomas.cli.commands.gateway.p128_gateway_install_command import render_cli_output, run_gateway_install
from thomas.server.routes.gateway.p128_gateway_install_command import (
    GatewayInstallCommandError,
    GatewayInstallCommandRequest,
    gateway_install_schema,
    install_gateway_artifact,
)


def test_install_success_directory(tmp_path: Path) -> None:
    source = tmp_path / "my_plugin"
    source.mkdir()
    (source / "hello.txt").write_text("hi", encoding="utf-8")

    install_dir = tmp_path / "gateway_install"
    req = GatewayInstallCommandRequest(source=str(source), install_dir=str(install_dir))
    result = install_gateway_artifact(req)

    dest = install_dir / result.name
    assert result.installed is True
    assert (dest / "hello.txt").read_text(encoding="utf-8") == "hi"


def test_install_success_zip(tmp_path: Path) -> None:
    zpath = tmp_path / "my_plugin.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("hello.txt", "ziphi")

    install_dir = tmp_path / "gateway_install"
    req = GatewayInstallCommandRequest(source=str(zpath), install_dir=str(install_dir))
    result = install_gateway_artifact(req)

    dest = install_dir / result.name
    assert (dest / "hello.txt").read_text(encoding="utf-8") == "ziphi"


def test_install_rejects_zip_slip(tmp_path: Path) -> None:
    zpath = tmp_path / "evil.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("../evil.txt", "nope")

    install_dir = tmp_path / "gateway_install"
    req = GatewayInstallCommandRequest(source=str(zpath), install_dir=str(install_dir))
    with pytest.raises(GatewayInstallCommandError) as excinfo:
        install_gateway_artifact(req)

    assert excinfo.value.code == "unsafe_archive"


def test_install_failure_missing_source(tmp_path: Path) -> None:
    install_dir = tmp_path / "gateway_install"
    req = GatewayInstallCommandRequest(source=str(tmp_path / "does_not_exist"), install_dir=str(install_dir))
    with pytest.raises(GatewayInstallCommandError) as excinfo:
        install_gateway_artifact(req)

    err = excinfo.value
    assert err.code == "invalid_source"
    assert err.http_status == 404


def test_install_failure_already_installed(tmp_path: Path) -> None:
    source = tmp_path / "my_plugin"
    source.mkdir()
    (source / "hello.txt").write_text("hi", encoding="utf-8")

    install_dir = tmp_path / "gateway_install"

    req1 = GatewayInstallCommandRequest(source=str(source), install_dir=str(install_dir))
    result1 = install_gateway_artifact(req1)

    req2 = GatewayInstallCommandRequest(
        source=str(source),
        install_dir=str(install_dir),
        name=result1.name,
        overwrite=False,
    )
    with pytest.raises(GatewayInstallCommandError) as excinfo:
        install_gateway_artifact(req2)

    err = excinfo.value
    assert err.code == "already_installed"
    assert err.http_status == 409


def test_cli_json_output_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "my_plugin"
    source.mkdir()
    (source / "hello.txt").write_text("hi", encoding="utf-8")

    install_dir = tmp_path / "gateway_install"
    monkeypatch.setenv("THOMAS_GATEWAY_INSTALL_DIR", str(install_dir))

    cli_result = run_gateway_install(source=str(source), dry_run=True)
    rendered = render_cli_output(cli_result, as_json=True)

    payload = json.loads(rendered)
    assert payload["ok"] is True
    assert payload["result"]["dry_run"] is True
    assert "installed_path" in payload["result"]


def test_schema_is_machine_readable() -> None:
    schema = gateway_install_schema()
    assert schema["name"] == "gateway_install"
    assert schema["request"]["type"] == "object"
    assert "source" in schema["request"]["required"]
