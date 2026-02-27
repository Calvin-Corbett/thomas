import importlib.util
import sys
from pathlib import Path

# Ensure repo root is importable when running pytest from arbitrary working dirs.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest_plugins = []
try:
    plugin_spec = importlib.util.find_spec("aiohttp.pytest_plugin")
except Exception:
    pass
else:
    if plugin_spec is not None:
        pytest_plugins.append("aiohttp.pytest_plugin")
