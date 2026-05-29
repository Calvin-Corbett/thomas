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

# Load pytest-asyncio for async test support
try:
    plugin_spec = importlib.util.find_spec("pytest_asyncio")
except Exception:
    pass
else:
    if plugin_spec is not None:
        pytest_plugins.append("pytest_asyncio")

# Load pytest-timeout when the optional test dependency is installed.  Local
# lightweight environments may omit it, so pytest_addoption below registers the
# ini keys as a warning-free fallback.
try:
    plugin_spec = importlib.util.find_spec("pytest_timeout")
except Exception:
    pass
else:
    if plugin_spec is not None:
        pytest_plugins.append("pytest_timeout")

# Load aiohttp plugin if available
try:
    plugin_spec = importlib.util.find_spec("aiohttp.pytest_plugin")
except Exception:
    pass
else:
    if plugin_spec is not None:
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
