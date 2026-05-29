import importlib.util
import os
import sys
from pathlib import Path

# Ensure repo root is importable when running pytest from arbitrary working dirs.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

pytest_plugins = []
if (Path(__file__).with_name("conftest_factories.py")).exists():
    pytest_plugins.append("tests.conftest_factories")


# Optional pytest plugins. find_spec() can raise ImportError (a parent package
# is missing) or ValueError (the module has no __spec__), so guard narrowly
# rather than swallowing every exception.
def _has_module(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


# pytest-asyncio's entry point loads its .plugin submodule; appending the
# package itself adds its fixtures without colliding with that registration.
if _has_module("pytest_asyncio"):
    pytest_plugins.append("pytest_asyncio")

# NOTE: pytest-timeout is intentionally NOT appended here. It ships a setuptools
# entry point, so pytest auto-loads it (as the "timeout" plugin) whenever the
# package is installed. Appending it re-registers the *same* module under a
# second name and raises "Plugin already registered under a different name" --
# the failure that silently took down the merge-readiness architecture gate on
# any interpreter that had the package installed. When pytest-timeout is absent,
# pytest_addoption below registers the ini keys as a warning-free fallback so
# pyproject's `timeout = 300` never errors.

if _has_module("aiohttp.pytest_plugin"):
    pytest_plugins.append("aiohttp.pytest_plugin")


def _add_ini_if_missing(parser, name: str, help_text: str) -> None:
    registered = getattr(parser, "_inidict", {})
    if name in registered:
        return
    try:
        parser.addini(name, help_text)
    except ValueError as exc:
        if "already added" not in str(exc):
            raise


def pytest_addoption(parser) -> None:
    _add_ini_if_missing(parser, "timeout", "Fallback registration for pytest-timeout's timeout setting.")
    _add_ini_if_missing(
        parser,
        "timeout_method",
        "Fallback registration for pytest-timeout's timeout_method setting.",
    )
