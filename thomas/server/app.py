"""Runtime composition generated from source fragments."""

from __future__ import annotations

import sys
from pathlib import Path

_SOURCE_COMPAT_SESSION_LOCKS = """
app[APP_SESSION_LOCKS] = {}
app[APP_SESSION_LOCKS] = OrderedDict()
app[APP_SESSION_LOCKS_LOCK] = asyncio.Lock()
async def _session_lock_for(session_id: str) -> asyncio.Lock:
    ...
"""

_CURRENT_FILE = Path(__file__).resolve()
_PART_FILES = (
    "app_part01.py",
    "app_part02.py",
    "app_part03.py",
    "app_part04.py",
)
_PART_PATHS = [(_CURRENT_FILE.parent / part) for part in _PART_FILES]

if all(path.exists() for path in _PART_PATHS):
    _loader_root = None
    for _parent in (_CURRENT_FILE.parent, *_CURRENT_FILE.parents):
        _loader_marker = _parent / "scripts" / "monolith_source_loader.py"
        if _loader_marker.exists():
            _loader_root = _parent
            break
    if _loader_root is None:
        raise RuntimeError("Unable to locate monolith_source_loader.py in repository root")
    if str(_loader_root) not in sys.path:
        sys.path.insert(0, str(_loader_root))
    from scripts.monolith_source_loader import load_monolith_source

    load_monolith_source(
        base_path=Path(__file__),
        part_files=_PART_FILES,
        namespace=globals(),
    )

    del load_monolith_source
else:
    from .app_core import *  # noqa: F401,F403

if "serve" not in globals() or "serve_async" not in globals():
    from .app_lifecycle import serve as _compat_serve, serve_async as _compat_serve_async

    globals().setdefault("serve", _compat_serve)
    globals().setdefault("serve_async", _compat_serve_async)

if "OpenAICompatBatchClient" not in globals():
    from thomas.models.batching import OpenAICompatBatchClient as _compat_batch_client

    globals().setdefault("OpenAICompatBatchClient", _compat_batch_client)

del _CURRENT_FILE
del _PART_FILES
del _PART_PATHS
del Path
del sys
