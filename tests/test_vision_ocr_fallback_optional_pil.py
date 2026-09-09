from __future__ import annotations

import importlib
import sys
from pathlib import Path


def test_ocr_fallback_imports_and_degrades_without_pillow(monkeypatch) -> None:
    """Pillow is a `test` extra. Importing the module must not require it, and the
    desktop-operator CLI that imports this module must still register without it."""
    import thomas.marketplace.vision.ocr_fallback as ocr

    monkeypatch.setitem(sys.modules, "PIL", None)  # `import PIL` now raises ImportError
    try:
        mod = importlib.reload(ocr)
        assert mod.Image is None
        out = mod.extract_text_from_images([Path("a.png"), Path("b.png")])
        assert len(out) == 2
        assert all("Pillow" in line for line in out), out
    finally:
        monkeypatch.undo()
        importlib.reload(ocr)
