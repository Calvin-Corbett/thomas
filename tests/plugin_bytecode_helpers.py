"""Setting up a stale ``__pycache__`` on purpose, for the reload tests.

Shared by ``test_plugin_source_reload.py`` (through the supervisor) and
``test_plugin_reload_over_http.py`` (through the route the running server
answers on). Not named ``test_*`` so pytest does not collect it.

The condition being reproduced: ``SourceFileLoader`` runs cached bytecode
whenever the source's mtime **in whole seconds** and its size both match the
``.pyc`` header. Waiting for an edit to land inside the same second would make
the tests timing-dependent, so the state is constructed instead — compile, then
rewrite with same-length text and put the mtime back.
"""

from __future__ import annotations

import importlib.util
import json
import os
import py_compile
from pathlib import Path

#: Two marks of the same length, so the rewrite leaves the file exactly as long
#: as it was. The pair the live app got wrong.
OLD_MARK = "loop36"
NEW_MARK = "loop49"

PLUGIN_SOURCE = """
class Plugin:
    name = "{name}"

    def before_tool(self, payload):
        data = dict(payload or {{}})
        data["marks"] = list(data.get("marks") or []) + ["{mark}"]
        return data


def get_plugin():
    return Plugin()
"""

#: A package whose behaviour lives one level down, where the package's own
#: ``from . import rule`` goes to the path finder rather than to the loader that
#: imported the package.
PACKAGE_INIT = """
from . import rule


class Plugin:
    name = "{name}"

    def before_tool(self, payload):
        data = dict(payload or {{}})
        data["marks"] = list(data.get("marks") or []) + [rule.MARK]
        return data


def get_plugin():
    return Plugin()
"""


def write_manifest(root: Path, *names: str) -> None:
    manifest = {"plugins": {name: {"installed_path": str(root / name)} for name in names}}
    (root / "installed_plugins.json").write_text(json.dumps(manifest), encoding="utf-8")


def write_plugin(root: Path, name: str, mark: str) -> Path:
    package = root / name
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text(PLUGIN_SOURCE.format(name=name, mark=mark), encoding="utf-8")
    return package


def set_stale_pyc_trap(file_path: Path, new_text: str) -> None:
    """Compile what is there, then swap in same-length text at the same mtime.

    Afterwards the ``.pyc`` beside ``file_path`` is what the stock loader
    considers current — same source mtime to the second, same size — and it holds
    the *previous* code.
    """
    py_compile.compile(str(file_path), doraise=True)
    before = file_path.stat()
    file_path.write_text(new_text, encoding="utf-8")
    assert file_path.stat().st_size == before.st_size, "this trap needs a same-length edit"
    os.utime(file_path, (before.st_atime, before.st_mtime))


def mark_the_stock_loader_produces(file_path: Path) -> str:
    """What an ordinary ``SourceFileLoader`` import of this file stamps.

    Used to check the trap itself: if this stops returning the old mark, the
    reload tests would pass without exercising anything.
    """
    name = f"_stale_pyc_probe_{abs(hash(str(file_path))) & 0xFFFFFF:x}"
    spec = importlib.util.spec_from_file_location(name, str(file_path))
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return str(module.get_plugin().before_tool({})["marks"][0])
