from __future__ import annotations

import importlib
import uuid
from pathlib import Path

from thomas.cli.pack_bridge import invoke_pack_module


def _write_module(tmp_path: Path, source: str) -> str:
    name = f"pb_{uuid.uuid4().hex}"
    path = tmp_path / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    importlib.invalidate_caches()
    return name


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
