from __future__ import annotations

import importlib
import json
import uuid
from pathlib import Path

import click
from click.testing import CliRunner

from thomas.cli.pack_bridge import invoke_pack_module, register_pack_proxy_commands


def _write_module(tmp_path: Path, source: str) -> str:
    name = f"pb_{uuid.uuid4().hex}"
    path = tmp_path / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    importlib.invalidate_caches()
    return name


def _write_pack_package(tmp_path: Path, package_name: str, modules: dict[str, str]) -> str:
    package_dir = tmp_path / package_name
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    for stem, source in modules.items():
        (package_dir / f"{stem}.py").write_text(source.strip() + "\n", encoding="utf-8")
    importlib.invalidate_caches()
    return package_name


def test_invoke_pack_module_passes_click_context_obj(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(tmp_path))
    module_name = _write_module(
        tmp_path,
        """
import click

@click.command(name="needs-ctx")
@click.pass_context
def cmd(ctx):
    payload = ctx.obj if isinstance(ctx.obj, dict) else {}
    if payload.get("token") != "ok":
        raise click.ClickException("missing context")
    return 0

COMMAND = cmd
""".strip()
        + "\n",
    )

    res = invoke_pack_module(module_name, [], prog_name="test", ctx_obj={"token": "ok"})
    assert res["ok"] is True
    assert res["mode"] == "click"


def test_invoke_pack_module_main_signature_handling(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(tmp_path))

    noarg_mod = _write_module(
        tmp_path,
        """
def main():
    return 0
""".strip()
        + "\n",
    )
    witharg_mod = _write_module(
        tmp_path,
        """
def main(argv):
    return 0 if isinstance(argv, list) else 1
""".strip()
        + "\n",
    )

    noarg_res = invoke_pack_module(noarg_mod, ["--x"], prog_name="test")
    witharg_res = invoke_pack_module(witharg_mod, ["--x"], prog_name="test")

    assert noarg_res["ok"] is True
    assert witharg_res["ok"] is True


def test_browser_proxy_run_noop_outputs_structured_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(tmp_path))
    package_name = _write_pack_package(
        tmp_path,
        f"pkg_{uuid.uuid4().hex}",
        {
            "p001_browser_missing_entrypoint": '"""Placeholder module with no entrypoint."""',
        },
    )
    group = click.Group("browser")
    added = register_pack_proxy_commands(
        group,
        package=package_name,
        family_hint="browser",
        strict_run_missing_entrypoint=True,
    )
    assert added == 1

    result = CliRunner().invoke(group, ["missing-entrypoint", "--run", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["mode"] == "noop"
    assert payload["error_code"] == "entrypoint_missing"
    assert payload["error_category"] == "not_implemented"
    assert "no callable main" in payload["message"]


def test_browser_proxy_describe_mode_is_informational_success(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(tmp_path))
    package_name = _write_pack_package(
        tmp_path,
        f"pkg_{uuid.uuid4().hex}",
        {
            "p001_browser_missing_entrypoint": '"""Placeholder module with no entrypoint."""',
        },
    )
    group = click.Group("browser")
    added = register_pack_proxy_commands(
        group,
        package=package_name,
        family_hint="browser",
        strict_run_missing_entrypoint=True,
    )
    assert added == 1

    result = CliRunner().invoke(group, ["missing-entrypoint"])
    assert result.exit_code == 0
    assert "wired to" in result.output
    assert "Pass args or --run to execute the module." in result.output


def test_browser_proxy_run_real_click_does_not_regress_to_noop(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.syspath_prepend(str(tmp_path))
    package_name = _write_pack_package(
        tmp_path,
        f"pkg_{uuid.uuid4().hex}",
        {
            "p001_browser_real_click": """
import click

@click.command(name="real-click")
@click.option("--target", required=True)
def cmd(target):
    return 0

COMMAND = cmd
""",
        },
    )
    group = click.Group("browser")
    added = register_pack_proxy_commands(
        group,
        package=package_name,
        family_hint="browser",
        strict_run_missing_entrypoint=True,
    )
    assert added == 1

    result = CliRunner().invoke(group, ["real-click", "--run"])
    assert result.exit_code != 0
    assert "failed via click" in result.output
    assert "noop" not in result.output


def test_non_browser_proxy_run_missing_main_keeps_legacy_noop_success(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.syspath_prepend(str(tmp_path))
    package_name = _write_pack_package(
        tmp_path,
        f"pkg_{uuid.uuid4().hex}",
        {
            "p001_missing_entrypoint": '"""Placeholder module with no entrypoint."""',
        },
    )
    group = click.Group("misc")
    added = register_pack_proxy_commands(group, package=package_name)
    assert added == 1

    result = CliRunner().invoke(group, ["missing-entrypoint", "--run"])
    assert result.exit_code == 0
    assert "executed via noop" in result.output
