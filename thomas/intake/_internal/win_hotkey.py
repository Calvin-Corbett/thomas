from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import threading
from dataclasses import dataclass
from typing import Callable, Optional

# RegisterHotKey docs: https://learn.microsoft.com/windows/win32/api/winuser/nf-winuser-registerhotkey
WM_HOTKEY = 0x0312

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

user32 = ctypes.windll.user32  # type: ignore[attr-defined]


@dataclass(frozen=True)
class Hotkey:
    modifiers: int
    vk: int


def vk_from_char(ch: str) -> int:
    # Basic A-Z, 0-9
    if len(ch) != 1:
        raise ValueError("vk_from_char expects a single character")
    o = ord(ch.upper())
    return o


class HotkeyListener:
    """Native Windows hotkey listener (RegisterHotKey) without admin privileges."""

    def __init__(self, hotkey: Hotkey, on_fire: Callable[[], None]):
        self.hotkey = hotkey
        self.on_fire = on_fire
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._hk_id = 1

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        # Post a dummy message to break GetMessage loop
        try:
            user32.PostThreadMessageW(ctypes.windll.kernel32.GetCurrentThreadId(), 0x0012, 0, 0)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _run(self) -> None:
        # Register for this thread
        if not user32.RegisterHotKey(None, self._hk_id, self.hotkey.modifiers, self.hotkey.vk):
            return

        msg = wt.MSG()
        while not self._stop.is_set():
            bret = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
            if bret == 0:
                break
            if msg.message == WM_HOTKEY and msg.wParam == self._hk_id:
                try:
                    self.on_fire()
                except Exception:
                    pass
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        user32.UnregisterHotKey(None, self._hk_id)
