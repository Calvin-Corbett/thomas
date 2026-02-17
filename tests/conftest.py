import sys
from pathlib import Path
import asyncio
import inspect

# Ensure repo root is importable when running pytest from arbitrary working dirs.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_configure(config):
    # Keep async-marked tests warning-free even without pytest-asyncio.
    config.addinivalue_line("markers", "asyncio: run test coroutine with asyncio.run")


def pytest_pyfunc_call(pyfuncitem):
    """Allow async def tests to run without external asyncio plugins."""
    test_fn = pyfuncitem.obj
    if inspect.iscoroutinefunction(test_fn):
        kwargs = {name: pyfuncitem.funcargs[name] for name in pyfuncitem._fixtureinfo.argnames}
        asyncio.run(test_fn(**kwargs))
        return True
    return None
