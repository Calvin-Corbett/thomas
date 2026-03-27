"""Preferences store compatibility layer."""

from __future__ import annotations

import sys
from pathlib import Path

_CURRENT_FILE = Path(__file__).resolve()
_LOADER_ROOT = None
for _parent in (_CURRENT_FILE.parent, *_CURRENT_FILE.parents):
    _loader_marker = _parent / "scripts" / "monolith_source_loader.py"
    if _loader_marker.exists():
        if str(_parent) not in sys.path:
            sys.path.insert(0, str(_parent))
        _LOADER_ROOT = _parent
        break

if _LOADER_ROOT is not None:
    from scripts.monolith_source_loader import load_monolith_source

    load_monolith_source(
        base_path=Path(__file__),
        part_files=(
            "store_part01.py",
            "store_part02.py",
        ),
        namespace=globals(),
    )

    del load_monolith_source
else:
    from ._db import *  # noqa: F401,F403
    from ._patches import *  # noqa: F401,F403
    from ._prefs import *  # noqa: F401,F403
    from ._utils import *  # noqa: F401,F403

    __all__ = sorted(name for name in globals() if not name.startswith("_"))

del _CURRENT_FILE
del _LOADER_ROOT
del _loader_marker
del _parent
del sys
