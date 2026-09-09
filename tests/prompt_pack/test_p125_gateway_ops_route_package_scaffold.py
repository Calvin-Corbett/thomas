import json
from pathlib import Path

import pytest

from thomas.cli.commands.gateway.p125_gateway_ops_route_package_scaffold import main as cli_main
from thomas.server.routes.gateway.p125_gateway_ops_route_package_scaffold import (
    ERROR_EXTERNAL_FAILURE,
    ERROR_INVALID_INPUT,
    ERROR_MISSING_CONFIG,
    GatewayOpsRoutePackageScaffoldError,
    GatewayOpsRoutePackageScaffoldRequest,
    get_gateway_ops_route_package_scaffold_json_schema,
    scaffold_gateway_ops_route_package,
)


def _make_minimal_thomas_checkout(project_root: Path) -> None:
    (project_root / "thomas").mkdir(parents=True, exist_ok=True)


def test_scaffold_creates_leaf_package_and_is_idempotent(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    project_root.mkdir()
    _make_minimal_thomas_checkout(project_root)

    req = GatewayOpsRoutePackageScaffoldRequest(
        package_name="fleet_ops",
        project_root=str(project_root),
    )
    result = scaffold_gateway_ops_route_package(req)

    leaf = Path(result.package_dir)
    assert leaf.exists() and leaf.is_dir()
    assert (leaf / "__init__.py").is_file()
    assert (leaf / "routes.py").is_file()
    assert (project_root / "thomas" / "server" / "routes" / "gateway" / "ops").is_dir()

    result2 = scaffold_gateway_ops_route_package(req)
    assert result2.created_dirs == ()
    assert result2.created_files == ()


def test_invalid_package_name_returns_deterministic_error(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    project_root.mkdir()
    _make_minimal_thomas_checkout(project_root)

    req = GatewayOpsRoutePackageScaffoldRequest(
        package_name="not-a-valid-package-name",
        project_root=str(project_root),
    )
    with pytest.raises(GatewayOpsRoutePackageScaffoldError) as ei:
        scaffold_gateway_ops_route_package(req)

    err = ei.value
    assert err.code == ERROR_INVALID_INPUT
    assert "package_name" in err.message


def test_missing_config_root_without_thomas_dir(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    project_root.mkdir()

    req = GatewayOpsRoutePackageScaffoldRequest(
        package_name="fleet_ops",
        project_root=str(project_root),
    )
    with pytest.raises(GatewayOpsRoutePackageScaffoldError) as ei:
        scaffold_gateway_ops_route_package(req)

    assert ei.value.code == ERROR_MISSING_CONFIG


def test_external_failure_when_directory_conflicts_with_file(tmp_path: Path) -> None:
    project_root = tmp_path / "proj"
    project_root.mkdir()
    (project_root / "thomas").mkdir()

    server_path = project_root / "thomas" / "server"
    server_path.write_text("not a directory", encoding="utf-8")

    req = GatewayOpsRoutePackageScaffoldRequest(
        package_name="fleet_ops",
        project_root=str(project_root),
    )
    with pytest.raises(GatewayOpsRoutePackageScaffoldError) as ei:
        scaffold_gateway_ops_route_package(req)

    assert ei.value.code == ERROR_EXTERNAL_FAILURE
    assert ei.value.details.get("path") == str(server_path)


def test_cli_json_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project_root = tmp_path / "proj"
    project_root.mkdir()
    _make_minimal_thomas_checkout(project_root)

    rc = cli_main(["--project-root", str(project_root), "--json", "fleet_ops"])
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["result"]["package_name"] == "fleet_ops"
    assert Path(payload["result"]["package_dir"]).exists()


def test_cli_json_failure(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project_root = tmp_path / "proj"
    project_root.mkdir()
    _make_minimal_thomas_checkout(project_root)

    rc = cli_main(["--project-root", str(project_root), "--json", "bad-name"])
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)

    assert rc != 0
    assert payload["ok"] is False
    assert payload["error"]["code"] == ERROR_INVALID_INPUT


def test_json_schema_is_machine_readable() -> None:
    schema = get_gateway_ops_route_package_scaffold_json_schema()
    encoded = json.dumps(schema, sort_keys=True)
    assert "GatewayOpsRoutePackageScaffold" in encoded
    assert "request" in schema.get("properties", {})
