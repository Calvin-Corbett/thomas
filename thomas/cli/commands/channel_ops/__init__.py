"""Channel operations command package.

This package may be imported by the top-level `channels` CLI command group.

To maximize compatibility with different loaders, this package exposes:
- register(app): registers all discovered commands in this package
- register_command(app): alias
- add_commands(app): alias

Discovery is best-effort and deterministic. A broken module will raise an ImportError.
"""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType
from typing import Callable, Optional

import typer


def _find_register_fn(mod: ModuleType) -> Optional[Callable[[typer.Typer], None]]:
    for name in ("register", "register_command", "add_commands"):
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn
    return None


def _snapshot_typer_state(app: typer.Typer) -> tuple[list[object], list[object], object]:
    return (
        list(getattr(app, "registered_commands", [])),
        list(getattr(app, "registered_groups", [])),
        getattr(app, "registered_callback", None),
    )


def _restore_typer_state(app: typer.Typer, snap: tuple[list[object], list[object], object]) -> None:
    app.registered_commands = snap[0]  # type: ignore[assignment]
    app.registered_groups = snap[1]  # type: ignore[assignment]
    app.registered_callback = snap[2]  # type: ignore[assignment]


def register(app: typer.Typer) -> None:
    """Discover and register all channel ops modules in this package."""
    pkg_name = __name__
    pkg = importlib.import_module(pkg_name)

    for info in pkgutil.iter_modules(pkg.__path__, prefix=pkg_name + "."):
        mod = importlib.import_module(info.name)
        fn = _find_register_fn(mod)
        if fn is not None:
            snap = _snapshot_typer_state(app)
            try:
                fn(app)
                # Some commands are syntactically registerable but not buildable
                # as Typer commands due unresolved annotations. Drop those.
                typer.main.get_command(app)
            except TypeError as e:
                msg = str(e)
                if (
                    "Unsupported CLI" in msg
                    or "add_parser" in msg
                    or "argparse subparsers" in msg.lower()
                ):
                    _restore_typer_state(app, snap)
                    continue
                raise
            except AttributeError as e:
                # Some channel modules are argparse-only and expect `add_parser`.
                if "add_parser" in str(e):
                    _restore_typer_state(app, snap)
                    continue
                raise
            except Exception:
                _restore_typer_state(app, snap)
                continue


register_command = register
add_commands = register

__all__ = ["register", "register_command", "add_commands"]
