import contextlib
import importlib.util
import os
import shutil
import sys
from pathlib import Path

# Ensure repo root is importable when running pytest from arbitrary working dirs.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")


def _clear_python_bytecode(root: Path) -> None:
    for pyc_file in root.rglob("*.pyc"):
        with contextlib.suppress(OSError):
            pyc_file.unlink()
    cache_dirs = sorted(
        (path for path in root.rglob("__pycache__") if path.is_dir()), key=lambda path: len(path.parts), reverse=True
    )
    for cache_dir in cache_dirs:
        shutil.rmtree(cache_dir, ignore_errors=True)


_clear_python_bytecode(ROOT / "thomas")

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

# Load aiohttp plugin if available
try:
    plugin_spec = importlib.util.find_spec("aiohttp.pytest_plugin")
except Exception:
    pass
else:
    if plugin_spec is not None:
        pytest_plugins.append("aiohttp.pytest_plugin")
