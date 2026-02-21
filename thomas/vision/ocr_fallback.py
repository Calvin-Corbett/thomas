from __future__ import annotations

import os
from pathlib import Path
from typing import List, Sequence

from PIL import Image, ImageEnhance, ImageOps


def _get_tesseract_cmd() -> str | None:
    return os.getenv("TESSERACT_CMD") or None


def _tesseract_available() -> bool:
    try:
        import pytesseract  # type: ignore
    except Exception:
        return False

    cmd = _get_tesseract_cmd()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd  # type: ignore[attr-defined]

    try:
        _ = pytesseract.get_tesseract_version()  # type: ignore[attr-defined]
        return True
    except Exception:
        return False


def _preprocess_for_ocr(img: Image.Image) -> Image.Image:
    """Screenshot-friendly preprocessing for OCR.

    We keep it light to avoid destroying UI glyph shapes:
    - EXIF transpose
    - grayscale + autocontrast
    - contrast bump
    - upscale small images
    """
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray)
    gray = ImageEnhance.Contrast(gray).enhance(1.6)

    w, h = gray.size
    if max(w, h) < 900:
        gray = gray.resize((w * 2, h * 2))
    return gray


def extract_text_from_images(image_paths: Sequence[Path]) -> List[str]:
    """Best-effort OCR. Returns one string per image.

    If pytesseract / the tesseract binary isn't available, returns a short inline hint.
    """
    if not image_paths:
        return []

    if not _tesseract_available():
        return [
            "(OCR unavailable: install pytesseract + tesseract, or set TESSERACT_CMD.)"
            for _ in image_paths
        ]

    import pytesseract  # type: ignore

    lang = os.getenv("TESSERACT_LANG", "eng")
    texts: List[str] = []

    for p in image_paths:
        try:
            with Image.open(p) as img:
                img2 = _preprocess_for_ocr(img)
                txt = pytesseract.image_to_string(img2, lang=lang)
                texts.append((txt or "").strip())
        except Exception as e:
            texts.append(f"(OCR failed for {p.name}: {e})")

    return texts
