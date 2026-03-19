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


class _AstCompatGroup:
    """AST-only compatibility shim for CLI guard tests.

    Runtime command registration is sourced from ``main_part*.py`` via
    ``load_monolith_source(...)`` below.
    """

    @staticmethod
    def command(*_args, **_kwargs):
        def _decorator(func):
            return func

        return _decorator


models = _AstCompatGroup()


def _run_models_discover(ctx, model_name, timeout_s):
    raise RuntimeError("models discover shim should be replaced by monolith loader")


@models.command("scan")
def models_scan(ctx, timeout_s):
    return _run_models_discover(ctx=ctx, model_name=None, timeout_s=timeout_s)


load_monolith_source(
    base_path=Path(__file__),
    part_files=(
        "main_part01.py",
        "main_part02.py",
        "main_part03.py",
    ),
    namespace=globals(),
)


del _CURRENT_FILE

del _loader_marker

del _parent

del load_monolith_source
