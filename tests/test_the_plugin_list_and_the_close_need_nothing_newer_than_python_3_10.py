"""pyproject says Python 3.10 and lists ``tomli`` for it, so the plugin list and the close may lean on nothing newer.

The plugin floor had, twice over: ``asyncio.Runner`` in the close and a bare ``import tomllib`` in the two files that read
the row list and the manifests, both of which arrived in Python 3.11. A whole server start on 3.10 is not proven here.

Spec: docs/superpowers/specs/2026-10-31-cordis-foundation-design.md
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from thomas.server import app_lifecycle

ROOT = Path(__file__).resolve().parents[1]


def test_closing_needs_no_asyncio_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(asyncio, "Runner", raising=False)

    async def main() -> str:
        return "served"

    assert app_lifecycle._run_and_close(main()) == "served"


@pytest.mark.parametrize(
    "module",
    ["thomas.core.plugin_manifest", "thomas.server.runtime_plugins", "tests.test_the_plugins_page_speaks_plainly"],
)
def test_a_python_with_no_tomllib_takes_tomli_instead(module: str, tmp_path: Path) -> None:
    """One module is imported again with ``tomllib`` gone, with the parser it had standing in for ``tomli``.

    Only that one, because others choose by version number, and this Python is new enough to send them to ``tomllib``.
    """
    script = textwrap.dedent(
        f"""
        import importlib
        import sys

        parser = importlib.import_module("{module}").tomllib
        sys.modules["tomli"] = parser
        sys.modules["tomllib"] = None
        del sys.modules["{module}"]

        print(importlib.import_module("{module}").tomllib is parser)
        """
    )
    finished = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env={**os.environ, "THOMAS_DATA_DIR": str(tmp_path / "data"), "THOMAS_MEMORY_ROOT": str(tmp_path / "memory")},
        capture_output=True,
        text=True,
    )

    assert finished.stdout.split() == ["True"], finished.stderr
