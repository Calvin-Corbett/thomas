from __future__ import annotations

import ctypes
import os
import time
from collections.abc import Iterable
from ctypes import wintypes
from pathlib import Path
from typing import Any, Protocol

from .contracts import CaptureArtifact, Rect, WindowInfo, external_failure, not_found, unsupported

try:
    from PIL import Image, ImageGrab  # type: ignore
except Exception:  # noqa: BLE001
    Image = None  # type: ignore
    ImageGrab = None  # type: ignore


if hasattr(wintypes, "ULONG_PTR"):
    _ULONG_PTR = wintypes.ULONG_PTR
else:
    _ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


SRCCOPY = 0x00CC0020
PW_RENDERFULLCONTENT = 0x00000002
BI_RGB = 0
DIB_RGB_COLORS = 0


class DesktopAdapter(Protocol):
    def list_windows(self) -> list[WindowInfo]: ...
    def get_window(self, handle: int) -> WindowInfo | None: ...
    def capture_window(self, handle: int, output_path: Path) -> CaptureArtifact: ...
    def snapshot_accessibility(self, handle: int) -> dict[str, Any]: ...
    def get_foreground_window(self) -> int | None: ...
    def ensure_visible(self, handle: int, *, move_to_primary: bool = False) -> WindowInfo: ...
    def click(self, handle: int, x: int, y: int, *, button: str = "left", double: bool = False) -> None: ...
    def type_text(self, handle: int, text: str) -> None: ...
    def press_keys(self, handle: int, keys: Iterable[str]) -> None: ...
    def drag(self, handle: int, start_x: int, start_y: int, end_x: int, end_y: int) -> None: ...


class WindowsDesktopAdapter:
    """Windows desktop automation adapter with direct window capture support."""

    def __init__(self) -> None:
        self._is_windows = os.name == "nt"
        if not self._is_windows:
            return
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self.gdi32 = ctypes.windll.gdi32

    def _require_windows(self) -> None:
        if not self._is_windows:
            raise unsupported("Desktop operator is Windows-only in v2.")

    def list_windows(self) -> list[WindowInfo]:
        self._require_windows()
        rows: list[WindowInfo] = []
        enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        @enum_proc
        def _callback(hwnd: int, _lparam: int) -> bool:
            info = self._window_info(hwnd)
            if info is not None:
                rows.append(info)
            return True

        self.user32.EnumWindows(_callback, 0)
        rows.sort(key=lambda item: (not item.visible, item.title.lower(), int(item.handle)))
        return rows

    def get_window(self, handle: int) -> WindowInfo | None:
        self._require_windows()
        return self._window_info(int(handle))

    def capture_window(self, handle: int, output_path: Path) -> CaptureArtifact:
        self._require_windows()
        window = self._require_window(handle)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        direct = self._capture_window_direct(window, output_path)
        if direct is not None:
            return direct
        if ImageGrab is None:
            raise external_failure("Pillow ImageGrab is required for window capture.", reason="missing_dependency")
        bbox = (
            int(window.bounds.left),
            int(window.bounds.top),
            int(window.bounds.right),
            int(window.bounds.bottom),
        )
        try:
            image = ImageGrab.grab(bbox=bbox, all_screens=True)
        except Exception as exc:  # noqa: BLE001
            raise external_failure("Window capture failed.", handle=int(handle), reason=type(exc).__name__) from None
        image.save(output_path)
        return CaptureArtifact(
            path=str(output_path),
            source="screen",
            timestamp_epoch_s=time.time(),
            occlusion_safe=False,
        )

    def snapshot_accessibility(self, handle: int) -> dict[str, Any]:
        self._require_windows()
        window = self._require_window(handle)
        try:
            import uiautomation as automation  # type: ignore
        except Exception:  # noqa: BLE001
            return {
                "available": False,
                "source": "uia",
                "reason": "uiautomation_not_installed",
                "window": window.to_dict(),
                "nodes": [],
            }

        control = automation.ControlFromHandle(int(handle))
        nodes: list[dict[str, Any]] = []

        def _walk(node: Any, depth: int = 0) -> None:
            if node is None or depth > 5 or len(nodes) >= 240:
                return
            try:
                rect = node.BoundingRectangle
                bounds = {
                    "left": int(getattr(rect, "left", 0)),
                    "top": int(getattr(rect, "top", 0)),
                    "right": int(getattr(rect, "right", 0)),
                    "bottom": int(getattr(rect, "bottom", 0)),
                }
            except Exception:
                bounds = {"left": 0, "top": 0, "right": 0, "bottom": 0}
            nodes.append(
                {
                    "name": str(getattr(node, "Name", "") or ""),
                    "role": str(getattr(node, "ControlTypeName", "") or ""),
                    "automation_id": str(getattr(node, "AutomationId", "") or ""),
                    "bounds": bounds,
                    "depth": depth,
                }
            )
            try:
                children = list(node.GetChildren() or [])
            except Exception:
                children = []
            for child in children:
                _walk(child, depth + 1)

        _walk(control, 0)
        return {"available": True, "source": "uia", "window": window.to_dict(), "nodes": nodes}

    def get_foreground_window(self) -> int | None:
        self._require_windows()
        try:
            hwnd = int(self.user32.GetForegroundWindow())
            return hwnd or None
        except Exception:
            return None

    def ensure_visible(self, handle: int, *, move_to_primary: bool = False) -> WindowInfo:
        self._require_windows()
        hwnd = int(handle)
        if not self.user32.IsWindow(hwnd):
            raise not_found("Window no longer exists.", handle=hwnd)
        self.user32.ShowWindow(hwnd, 9)
        self.user32.SetForegroundWindow(hwnd)
        if move_to_primary:
            self._move_to_primary_monitor(hwnd)
        time.sleep(0.05)
        return self._require_window(hwnd)

    def click(self, handle: int, x: int, y: int, *, button: str = "left", double: bool = False) -> None:
        self._require_windows()
        self.ensure_visible(handle)
        abs_x, abs_y = self._client_to_screen(int(handle), int(x), int(y))
        self.user32.SetCursorPos(abs_x, abs_y)
        button_kind = str(button or "left").strip().lower()
        down, up = (0x0002, 0x0004) if button_kind != "right" else (0x0008, 0x0010)
        self.user32.mouse_event(down, 0, 0, 0, 0)
        self.user32.mouse_event(up, 0, 0, 0, 0)
        if double:
            time.sleep(0.05)
            self.user32.mouse_event(down, 0, 0, 0, 0)
            self.user32.mouse_event(up, 0, 0, 0, 0)

    def type_text(self, handle: int, text: str) -> None:
        self._require_windows()
        self.ensure_visible(handle)
        for char in str(text or ""):
            self._send_unicode_char(char)

    def press_keys(self, handle: int, keys: Iterable[str]) -> None:
        self._require_windows()
        self.ensure_visible(handle)
        for key in keys:
            vk = _VK_MAP.get(str(key or "").strip().lower())
            if vk is None:
                raise unsupported("Unsupported key for desktop operator.", key=str(key))
            self._send_virtual_key(vk)

    def drag(self, handle: int, start_x: int, start_y: int, end_x: int, end_y: int) -> None:
        self._require_windows()
        self.ensure_visible(handle)
        sx, sy = self._client_to_screen(int(handle), int(start_x), int(start_y))
        ex, ey = self._client_to_screen(int(handle), int(end_x), int(end_y))
        self.user32.SetCursorPos(sx, sy)
        self.user32.mouse_event(0x0002, 0, 0, 0, 0)
        steps = 12
        for idx in range(1, steps + 1):
            nx = int(round(sx + (ex - sx) * idx / steps))
            ny = int(round(sy + (ey - sy) * idx / steps))
            self.user32.SetCursorPos(nx, ny)
            time.sleep(0.01)
        self.user32.mouse_event(0x0004, 0, 0, 0, 0)

    def _window_info(self, hwnd: int) -> WindowInfo | None:
        if not hwnd or not self.user32.IsWindow(hwnd):
            return None
        title = self._window_text(hwnd)
        if not title.strip():
            return None
        visible = bool(self.user32.IsWindowVisible(hwnd))
        rect = wintypes.RECT()
        self.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return None
        client = self._client_rect(hwnd)
        monitor_id = self._monitor_id(hwnd)
        process_id = self._process_id(hwnd)
        process_path = self._process_path(hwnd)
        minimized = bool(self.user32.IsIconic(hwnd))
        class_name = self._class_name(hwnd)
        return WindowInfo(
            handle=int(hwnd),
            title=title,
            executable_path=process_path,
            process_id=process_id,
            visible=visible,
            minimized=minimized,
            monitor_id=monitor_id,
            bounds=Rect(rect.left, rect.top, rect.right, rect.bottom),
            client_bounds=client,
            class_name=class_name,
        )

    def _require_window(self, handle: int) -> WindowInfo:
        info = self._window_info(int(handle))
        if info is None:
            raise not_found("Window not found.", handle=int(handle))
        return info

    def _capture_window_direct(self, window: WindowInfo, output_path: Path) -> CaptureArtifact | None:
        if Image is None:
            return None
        width = int(window.bounds.width)
        height = int(window.bounds.height)
        if width <= 0 or height <= 0:
            return None
        hwnd = int(window.handle)
        hwnd_dc = self.user32.GetWindowDC(hwnd)
        if not hwnd_dc:
            return None
        mem_dc = self.gdi32.CreateCompatibleDC(hwnd_dc)
        bitmap = self.gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
        old_obj = self.gdi32.SelectObject(mem_dc, bitmap)
        try:
            result = int(self.user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT))
            if result == 0:
                result = int(self.user32.PrintWindow(hwnd, mem_dc, 0))
            if result == 0:
                copied = int(self.gdi32.BitBlt(mem_dc, 0, 0, width, height, hwnd_dc, 0, 0, SRCCOPY))
                if copied == 0:
                    return None
            info = BITMAPINFO()
            info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            info.bmiHeader.biWidth = width
            info.bmiHeader.biHeight = -height
            info.bmiHeader.biPlanes = 1
            info.bmiHeader.biBitCount = 32
            info.bmiHeader.biCompression = BI_RGB
            buffer_len = width * height * 4
            buffer = ctypes.create_string_buffer(buffer_len)
            scanlines = self.gdi32.GetDIBits(
                mem_dc,
                bitmap,
                0,
                height,
                buffer,
                ctypes.byref(info),
                DIB_RGB_COLORS,
            )
            if int(scanlines) == 0:
                return None
            image = Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1)
            image.save(output_path)
            return CaptureArtifact(
                path=str(output_path),
                source="printwindow",
                timestamp_epoch_s=time.time(),
                occlusion_safe=True,
            )
        except Exception:
            return None
        finally:
            self.gdi32.SelectObject(mem_dc, old_obj)
            self.gdi32.DeleteObject(bitmap)
            self.gdi32.DeleteDC(mem_dc)
            self.user32.ReleaseDC(hwnd, hwnd_dc)

    def _window_text(self, hwnd: int) -> str:
        length = int(self.user32.GetWindowTextLengthW(hwnd)) + 1
        buffer = ctypes.create_unicode_buffer(max(length, 2))
        self.user32.GetWindowTextW(hwnd, buffer, len(buffer))
        return str(buffer.value or "").strip()

    def _class_name(self, hwnd: int) -> str:
        buffer = ctypes.create_unicode_buffer(256)
        self.user32.GetClassNameW(hwnd, buffer, len(buffer))
        return str(buffer.value or "").strip()

    def _client_rect(self, hwnd: int) -> Rect:
        client_rect = wintypes.RECT()
        self.user32.GetClientRect(hwnd, ctypes.byref(client_rect))
        origin = wintypes.POINT(0, 0)
        self.user32.ClientToScreen(hwnd, ctypes.byref(origin))
        left = int(origin.x)
        top = int(origin.y)
        right = left + int(client_rect.right - client_rect.left)
        bottom = top + int(client_rect.bottom - client_rect.top)
        return Rect(left, top, right, bottom)

    def _client_to_screen(self, hwnd: int, x: int, y: int) -> tuple[int, int]:
        point = wintypes.POINT(int(x), int(y))
        self.user32.ClientToScreen(hwnd, ctypes.byref(point))
        return int(point.x), int(point.y)

    def _monitor_id(self, hwnd: int) -> str:
        monitor = self.user32.MonitorFromWindow(hwnd, 2)
        if not monitor:
            return "DISPLAY0"
        return f"DISPLAY{int(monitor)}"

    def _process_id(self, hwnd: int) -> int:
        pid = wintypes.DWORD(0)
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value or 0)

    def _process_path(self, hwnd: int) -> str:
        pid = self._process_id(hwnd)
        if pid <= 0:
            return ""
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        process = self.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not process:
            return ""
        try:
            buffer_len = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(buffer_len.value)
            QueryFullProcessImageNameW = self.kernel32.QueryFullProcessImageNameW
            QueryFullProcessImageNameW.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.LPWSTR,
                ctypes.POINTER(wintypes.DWORD),
            ]
            QueryFullProcessImageNameW.restype = wintypes.BOOL
            ok = QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(buffer_len))
            if not ok:
                return ""
            return str(buffer.value or "")
        except Exception:
            return ""
        finally:
            self.kernel32.CloseHandle(process)

    def _move_to_primary_monitor(self, hwnd: int) -> None:
        rect = wintypes.RECT()
        self.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = max(100, int(rect.right - rect.left))
        height = max(100, int(rect.bottom - rect.top))
        self.user32.SetWindowPos(hwnd, 0, 40, 40, width, height, 0x0040)

    def _send_virtual_key(self, vk_code: int) -> None:
        self.user32.keybd_event(vk_code, 0, 0, 0)
        self.user32.keybd_event(vk_code, 0, 2, 0)

    def _send_unicode_char(self, char: str) -> None:
        if not char:
            return
        code = ord(char[0])
        self.user32.keybd_event(0, code, 0x0004, 0)
        self.user32.keybd_event(0, code, 0x0004 | 0x0002, 0)


_VK_MAP = {
    "enter": 0x0D,
    "escape": 0x1B,
    "esc": 0x1B,
    "tab": 0x09,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
}
