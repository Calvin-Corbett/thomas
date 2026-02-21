import sys
from pathlib import Path

# Ensure repo root is importable when running pytest from arbitrary working dirs.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

pytest_plugins = []
try:
    import aiohttp.pytest_plugin  # noqa: F401
except Exception:
    pass
else:
    pytest_plugins.append("aiohttp.pytest_plugin")
