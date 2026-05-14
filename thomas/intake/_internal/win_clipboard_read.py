from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from typing import Optional

CF_UNICODETEXT = 13

user32 = ctypes.windll.user32  # type: ignore[attr-defined]
kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]


def read_clipboard_text() -> str | None:
    """Read Unicode text directly from Windows clipboard (no extra deps)."""
    if not user32.OpenClipboard(None):
        return None
    try:
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        ptr = kernel32.GlobalLock(handle)
        if not ptr:
            return None
        try:
            text = ctypes.wstring_at(ptr)
            if text and text.strip():
                return text
            return None
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()
