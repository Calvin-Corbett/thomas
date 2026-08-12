import importlib.util
import os
import sys
from pathlib import Path

import pytest

# Ensure repo root is importable when running pytest from arbitrary working dirs.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
# Tests legitimately point the server at local test HTTP servers (loopback), which
# the SSRF guard (thomas/server/net_safety.py) blocks by default. Opt out here so
# integration tests run; the guard's blocking behavior is covered by test_net_safety.py.
os.environ.setdefault("THOMAS_ALLOW_PRIVATE_OUTBOUND", "1")
# evolve's headless build fallback spawns a real `claude -p` subprocess when the
# in-process agent no-ops; that subprocess blocks forever under pytest and hangs the
# suite (e.g. test_cli_evolve_commands.py). Disable the live fallback for tests --
# genuine evolve runs leave it enabled. See _evolve_cli_fallback_enabled().
os.environ.setdefault("THOMAS_EVOLVE_DISABLE_CLI_FALLBACK", "1")
# evolve's doppelganger builds a fresh "green" venv and, when its dep probe
# (import aiohttp, click, httpx) fails in that empty venv, runs a real networked
# `pip install -e .[repl,server]` that blocks forever offline -- hanging
# test_cli_evolve_commands.py. Build the green venv with --system-site-packages
# under test so it inherits those deps from this interpreter; the probe passes
# and the networked install is skipped. See doppelganger.ensure_green_venv().
os.environ.setdefault("THOMAS_EVOLVE_HERMETIC_VENV", "1")

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


@pytest.fixture(autouse=True)
def _runtime_protection_defaults_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate gate tests from this checkout's signed owner preference."""

    from scripts.forge.gates import _runtime_guard

    monkeypatch.setattr(_runtime_guard, "runtime_protection_disabled", lambda _root: False)


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
