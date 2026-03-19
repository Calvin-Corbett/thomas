"""Runtime composition generated from source fragments."""

import sys
from pathlib import Path

_CURRENT_FILE = Path(__file__).resolve()
for _parent in (_CURRENT_FILE.parent, *_CURRENT_FILE.parents):
    _loader_marker = _parent / "scripts" / "monolith_source_loader.py"
    if _loader_marker.exists():
        if str(_parent) not in sys.path:
            sys.path.insert(0, str(_parent))
        break
else:
    raise RuntimeError("Unable to locate monolith_source_loader.py in repository root")

from scripts.monolith_source_loader import load_monolith_source

load_monolith_source(
    base_path=Path(__file__),
    part_files=(
        "dep_scanner_part01.py",
        "dep_scanner_part02.py",
    ),
    namespace=globals(),
)


del _CURRENT_FILE

del _loader_marker

del _parent

del load_monolith_source

del sys
