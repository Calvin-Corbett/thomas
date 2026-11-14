"""The no-follow file seam: read an agent-written file without following links, or say why it was refused.

``read_regular`` opens the file first (never following a reparse point) and judges what it opened through the
handle, so a swap between a check and the open cannot change the answer. ``hold_dir`` keeps a folder open with no
delete or rename sharing while its files are read, so the folder cannot be replaced by a junction in between.
``WindowsFs`` is the real implementation (ctypes); ``PortableFs`` is the fallback for other platforms and for
tests, using ``O_NOFOLLOW`` and an identity check. Both raise ``UnsafeEntry`` with a short code.
"""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

REPARSE, SPARSE, DIRECTORY = 0x400, 0x200, 0x10


class UnsafeEntry(Exception):
    """A file or folder was refused. ``code`` is short; ``detail`` is for the ledger only."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


def judge(attrs: int, links: int, size: int, streams: int, limit: int) -> None:
    """Raise ``UnsafeEntry`` unless these facts describe an ordinary, single-link, dense, small file."""
    if attrs & REPARSE:
        raise UnsafeEntry("reparse_point")
    if attrs & DIRECTORY:
        raise UnsafeEntry("not_a_file")
    if links > 1:
        raise UnsafeEntry("hard_linked", f"{links} links")
    if attrs & SPARSE:
        raise UnsafeEntry("sparse", f"{size} bytes claimed")
    if size > limit:
        raise UnsafeEntry("too_large", f"{size} bytes")
    if streams > 1:
        raise UnsafeEntry("alternate_stream", f"{streams} streams")


def _within(data: bytes | bytearray, limit: int) -> None:
    """A file that grew between the size check and the read is refused, not admitted one byte over the cap."""
    if len(data) > limit:
        raise UnsafeEntry("too_large", f"read {len(data)} bytes")


class PortableFs:
    @contextmanager
    def hold_dir(self, path: Path) -> Iterator[None]:
        info = os.lstat(path)
        if (
            stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & REPARSE
            or not stat.S_ISDIR(info.st_mode)
        ):
            raise UnsafeEntry("not_a_plain_folder")
        yield

    @contextmanager
    def hold_file(self, path: Path, required: bool = False) -> Iterator[bool]:
        """Keep ``path`` from being changed while held. Yields False when this platform cannot: callers must verify."""
        yield False

    def read_regular(self, path: Path, limit: int) -> bytes:
        try:
            before = os.lstat(path)
        except FileNotFoundError as exc:
            raise UnsafeEntry("missing") from exc
        attrs = getattr(before, "st_file_attributes", 0) | (REPARSE if stat.S_ISLNK(before.st_mode) else 0)
        if not stat.S_ISREG(before.st_mode):
            attrs |= DIRECTORY
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
        try:
            now = os.fstat(fd)
            if (now.st_ino, now.st_dev) != (before.st_ino, before.st_dev):
                raise UnsafeEntry("changed_while_opening")
            judge(attrs | getattr(now, "st_file_attributes", 0), now.st_nlink, now.st_size, 1, limit)
            data = os.read(fd, limit + 1)
            _within(data, limit)
            return data
        finally:
            os.close(fd)


class WindowsFs(PortableFs):
    """Handles opened with ``FILE_FLAG_OPEN_REPARSE_POINT`` and judged by ``GetFileInformationByHandle``."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        class Stream(ctypes.Structure):
            _fields_ = [("size", ctypes.c_longlong), ("name", ctypes.c_wchar * 296)]

        class Info(ctypes.Structure):
            _fields_ = [("attrs", wintypes.DWORD), ("times", wintypes.DWORD * 6), ("serial", wintypes.DWORD)] + [
                (n, wintypes.DWORD) for n in ("size_high", "size_low", "links", "index_high", "index_low")
            ]

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = k32.FindFirstStreamW.restype = ctypes.c_void_p
        k32.CreateFileW.argtypes = [ctypes.c_wchar_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p] + [
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        k32.GetFileInformationByHandle.argtypes = [ctypes.c_void_p, ctypes.POINTER(Info)]
        k32.ReadFile.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
            ctypes.c_void_p,
        ]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        k32.FindFirstStreamW.argtypes = [ctypes.c_wchar_p, ctypes.c_int, ctypes.POINTER(Stream), wintypes.DWORD]
        k32.FindNextStreamW.argtypes = [ctypes.c_void_p, ctypes.POINTER(Stream)]
        k32.FindClose.argtypes = [ctypes.c_void_p]
        self._c, self._w, self._k, self._Info, self._Stream = ctypes, wintypes, k32, Info, Stream

    def _open(self, path: Path, folder: bool, share: int = 0x3):
        flags = 0x00200000 | 0x02000000  # open the link itself, never its target; backup semantics let a folder open
        handle = self._k.CreateFileW(
            str(path), 0x80000000, share, None, 3, flags, None
        )  # read access; others share as asked
        if handle in (None, self._c.c_void_p(-1).value):
            code = self._c.get_last_error()
            raise UnsafeEntry("missing" if code in (2, 3) else "unreadable", f"Windows error {code}")
        info = self._Info()
        if not self._k.GetFileInformationByHandle(handle, self._c.byref(info)):
            self._k.CloseHandle(handle)
            raise UnsafeEntry("unreadable", "no file information")
        return handle, info

    def _streams(self, path: Path) -> int:
        data, count = self._Stream(), 0
        found = self._k.FindFirstStreamW(str(path), 0, self._c.byref(data), 0)
        if found in (None, self._c.c_void_p(-1).value):
            return 0
        try:
            count = 1
            while self._k.FindNextStreamW(found, self._c.byref(data)):
                count += 1
        finally:
            self._k.FindClose(found)
        return count

    @contextmanager
    def hold_file(self, path: Path, required: bool = False) -> Iterator[bool]:
        """Open ``path`` allowing others to read but not write, rename over or delete it. Yields True while held.

        A file that does not exist yields False only when it is not ``required``; a required file that is missing,
        locked by someone else or cannot be opened raises ``UnsafeEntry``. It never answers False for a failure.
        """
        try:
            handle, info = self._open(path, False, share=0x1)
        except UnsafeEntry as exc:
            if exc.code == "missing" and not required:
                yield False
                return
            raise
        try:
            if info.attrs & REPARSE:
                raise UnsafeEntry("reparse_point")
            yield True
        finally:
            self._k.CloseHandle(handle)

    @contextmanager
    def hold_dir(self, path: Path) -> Iterator[None]:
        handle, info = self._open(path, True)
        try:
            if info.attrs & REPARSE or not info.attrs & DIRECTORY:
                raise UnsafeEntry("not_a_plain_folder")
            yield
        finally:
            self._k.CloseHandle(handle)

    def read_regular(self, path: Path, limit: int) -> bytes:
        handle, info = self._open(path, False)
        try:
            size = (info.size_high << 32) | info.size_low
            judge(info.attrs, info.links, size, self._streams(path), limit)
            buffer, got, out = self._c.create_string_buffer(65536), self._w.DWORD(), bytearray()
            while len(out) <= limit and self._k.ReadFile(handle, buffer, 65536, self._c.byref(got), None) and got.value:
                out += buffer.raw[: got.value]
            _within(out, limit)
            return bytes(out)
        finally:
            self._k.CloseHandle(handle)


def default_fs() -> PortableFs:
    return WindowsFs() if sys.platform == "win32" else PortableFs()
