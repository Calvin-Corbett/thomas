from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import threading
from typing import Callable, Optional

WM_CLIPBOARDUPDATE = 0x031D
WM_DESTROY = 0x0002

user32 = ctypes.windll.user32  # type: ignore[attr-defined]
kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]


class ClipboardListener:
    """Windows clipboard event listener (AddClipboardFormatListener) without pywin32."""

    def __init__(self, on_update: Callable[[], None]):
        self.on_update = on_update
        self._thread: Optional[threading.Thread] = None
        self._hwnd: Optional[int] = None
        self._stop = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_DESTROY, 0, 0)

    def _run(self) -> None:
        WNDPROCTYPE = ctypes.WINFUNCTYPE(ctypes.c_long, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

        def _wnd_proc(hwnd, msg, wparam, lparam):  # type: ignore[no-untyped-def]
            if msg == WM_CLIPBOARDUPDATE:
                try:
                    self.on_update()
                except Exception:
                    pass
                return 0
            if msg == WM_DESTROY:
                user32.RemoveClipboardFormatListener(hwnd)
                user32.DestroyWindow(hwnd)
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        wnd_proc = WNDPROCTYPE(_wnd_proc)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [
                ("style", wt.UINT),
                ("lpfnWndProc", WNDPROCTYPE),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wt.HINSTANCE),
                ("hIcon", wt.HICON),
                ("hCursor", wt.HCURSOR),
                ("hbrBackground", wt.HBRUSH),
                ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR),
            ]

        hinst = kernel32.GetModuleHandleW(None)
        cls_name = "ThomasClipboardListenerWindow"

        wc = WNDCLASS()
        wc.lpfnWndProc = wnd_proc
        wc.lpszClassName = cls_name
        wc.hInstance = hinst

        user32.RegisterClassW(ctypes.byref(wc))

        hwnd = user32.CreateWindowExW(0, cls_name, cls_name, 0, 0, 0, 0, 0, 0, 0, hinst, None)
        if not hwnd:
            return

        self._hwnd = hwnd
        if not user32.AddClipboardFormatListener(hwnd):
            return

        msg = wt.MSG()
        while not self._stop.is_set():
            bret = user32.GetMessageW(ctypes.byref(msg), 0, 0, 0)
            if bret == 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
