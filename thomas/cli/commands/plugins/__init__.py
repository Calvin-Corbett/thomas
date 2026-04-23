from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType
from typing import Any, Callable

import typer


app = typer.Typer(add_completion=False, help="Plugin management commands.")


@app.callback(invoke_without_command=True)
def _plugins_root() -> None:
    return


def _find_register_fn(mod: ModuleType) -> Callable[[Any], None] | None:
    for name in ("register", "register_command", "add_commands"):
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn
    return None


def register(plugin_app: Any) -> None:
    """
    Discover and register plugin CLI command modules into ``plugin_app``.
    """
    pkg_name = __name__
    pkg = importlib.import_module(pkg_name)
    for info in pkgutil.iter_modules(pkg.__path__, prefix=pkg_name + "."):
        mod = importlib.import_module(info.name)
        fn = _find_register_fn(mod)
        if fn is not None:
            fn(plugin_app)


register_command = register
add_commands = register

