"""Windows file-system primitives the Express threat-lab fixtures stand on.

Each function reports a fact about a path (reparse point, 8.3 alias, alternate streams) or builds one trick inside a
scratch folder (a junction, a hard link, a sparse file). Nothing here touches machine state outside the paths it is
given. The Windows calls go through one private ``WinDLL`` handle. ``EnvironmentUnavailable`` means this machine
cannot do it (not Windows, 8.3 names off, no symlink privilege, no sparse support): a test skips with the reason.
``FixtureBroken`` means the machine can and the fixture did not (a junction or hard link needs no privilege): a
test fails.
"""

from __future__ import annotations

import ctypes
import functools
import os
import shutil
import stat
import sys
from collections.abc import Callable
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
FILE_ATTRIBUTE_SPARSE_FILE = 0x200
FILE_ATTRIBUTE_REPARSE_POINT = 0x400
_FSCTL_SET_SPARSE = 0x900C4
_FILE_SUPPORTS_SPARSE_FILES = 0x40
_INVALID_HANDLE = ctypes.c_void_p(-1).value
_PROBE_BYTES = 16 * 1024 * 1024
_ERROR_HANDLE_EOF = 38


class EnvironmentUnavailable(Exception):
    """The trick cannot be built on this machine; the message is the reason a test skips with."""


class FixtureBroken(Exception):
    """The machine can build this trick and the fixture failed to: a test error, never a skip."""


def require_windows(what: str) -> None:
    if not IS_WINDOWS:
        raise EnvironmentUnavailable(f"{what} is a Windows file-system behaviour; this platform is {sys.platform}")


class _StreamData(ctypes.Structure):
    _fields_ = [("StreamSize", ctypes.c_longlong), ("cStreamName", ctypes.c_wchar * 296)]


@functools.cache
def _k32() -> ctypes.WinDLL:
    """A private kernel32 handle with every prototype this module needs set once."""
    require_windows("a kernel32 call")
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.FindFirstStreamW.restype = ctypes.c_void_p
    k32.FindFirstStreamW.argtypes = [ctypes.c_wchar_p, ctypes.c_int, ctypes.POINTER(_StreamData), ctypes.c_ulong]
    k32.FindNextStreamW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_StreamData)]
    k32.FindClose.argtypes = [ctypes.c_void_p]
    k32.DeviceIoControl.argtypes = [
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.c_void_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.c_void_p,
    ]
    k32.GetCompressedFileSizeW.restype = ctypes.c_ulong
    k32.GetCompressedFileSizeW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
    k32.GetVolumeInformationW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.c_ulong),
        ctypes.c_wchar_p,
        ctypes.c_ulong,
    ]
    return k32


def file_attributes(path: str | Path) -> int:
    """The Windows attribute bits of a path, read without following it. A path that cannot be read raises."""
    return int(getattr(os.lstat(path), "st_file_attributes", 0))


def is_reparse_point(path: str | Path) -> bool:
    """True for a junction or symlink, judged without following it.

    A path that does not exist is not a reparse point. Any other failure to look raises: a helper that answered
    "no" when it could not look would make every check built on it fail open.
    """
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    return bool(getattr(info, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT) or stat.S_ISLNK(info.st_mode)


def create_junction(link: Path, target: Path) -> None:
    require_windows("a directory junction")
    import _winapi  # Windows-only stdlib module

    try:
        _winapi.CreateJunction(str(target), str(link))
    except OSError as exc:  # a junction needs no privilege: failing here is a broken fixture, not a skip
        raise FixtureBroken(f"a junction could not be created: {exc}") from exc


def remove_junction(link: Path) -> None:
    """Remove the junction itself; ``rmdir`` never follows it, so the target folder is never touched."""
    if is_reparse_point(link):
        os.rmdir(link)


def remove_link(link: Path) -> None:
    """Remove a symlink itself (a directory symlink needs ``rmdir`` on Windows); never touches its target."""
    if not is_reparse_point(link):
        return
    if IS_WINDOWS and link.is_dir():
        os.rmdir(link)
    else:
        os.unlink(link)


def create_symlink(
    link: Path, target: Path, *, directory: bool = False, symlink: Callable[..., None] = os.symlink
) -> None:
    """Make a symlink with ``symlink`` (injectable, so a test can run this path without the privilege)."""
    try:
        symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:
        raise EnvironmentUnavailable(f"a symlink needs a privilege this account lacks here: {exc}") from exc


def create_hard_link(link: Path, existing: Path) -> None:
    try:
        os.link(existing, link)
    except (OSError, NotImplementedError) as exc:  # NTFS hard links need no privilege
        raise FixtureBroken(f"a hard link could not be created: {exc}") from exc


def link_count(path: str | Path) -> int:
    return int(os.lstat(path).st_nlink)


def short_path(path: Path) -> str | None:
    """The full 8.3 spelling of an existing path, or None."""
    buf = ctypes.create_unicode_buffer(1024)
    size = _k32().GetShortPathNameW(str(path), buf, 1024)
    return buf.value if 0 < size < 1024 else None


def alternate_streams(path: Path) -> list[str]:
    """Names of the alternate data streams on a file or folder, as ``:name:$DATA`` (the main stream is left out)."""
    k32 = _k32()
    data = _StreamData()
    handle = k32.FindFirstStreamW(str(path), 0, ctypes.byref(data), 0)
    if handle in (None, _INVALID_HANDLE):
        code = ctypes.get_last_error()
        if code == _ERROR_HANDLE_EOF:  # a folder with no streams at all: the only "no" that means "I looked"
            return []
        raise OSError(None, f"the streams of {path} could not be listed (Windows error {code})", str(path), code)
    names = []
    try:
        while True:
            if data.cStreamName != "::$DATA":
                names.append(data.cStreamName)
            if not k32.FindNextStreamW(handle, ctypes.byref(data)):
                return names
    finally:
        k32.FindClose(handle)


def _set_sparse(handle_fd: int) -> bool:
    import msvcrt

    returned = ctypes.c_ulong(0)
    handle = msvcrt.get_osfhandle(handle_fd)
    return bool(_k32().DeviceIoControl(handle, _FSCTL_SET_SPARSE, None, 0, None, 0, ctypes.byref(returned), None))


def allocated_size(path: Path) -> int:
    """Bytes the file really occupies on disk (a sparse file's holes are not counted)."""
    high = ctypes.c_ulong(0)
    low = _k32().GetCompressedFileSizeW(str(path), ctypes.byref(high))
    return (high.value << 32) | low


def volume_supports_sparse(folder: Path) -> bool:
    flags = ctypes.c_ulong(0)
    root = os.path.splitdrive(os.path.abspath(folder))[0] + "\\"
    ok = _k32().GetVolumeInformationW(root, None, 0, None, None, ctypes.byref(flags), None, 0)
    return bool(ok) and bool(flags.value & _FILE_SUPPORTS_SPARSE_FILES)


def _write_sparse(path: Path, logical_size: int) -> bool:
    """Mark ``path`` sparse before writing anything, then stretch it. False when the flag would not take."""
    with open(path, "wb") as handle:
        if not _set_sparse(handle.fileno()):
            return False
        handle.seek(logical_size - 1)
        handle.write(b"\0")
    return True


def _holds_holes(path: Path) -> bool:
    return bool(file_attributes(path) & FILE_ATTRIBUTE_SPARSE_FILE) and allocated_size(path) <= 1 << 20


def check_sparse_room(folder: Path, logical_size: int) -> None:
    """Raise ``EnvironmentUnavailable`` unless a sparse file of ``logical_size`` can safely be made in ``folder``.

    A dense file of this size would fill the drive, so nothing large is written until a 16 MiB probe has shown the
    volume really keeps holes: the volume must report sparse support, have more free space than the logical size,
    and the probe must occupy under 1 MiB. The probe is always removed.
    """
    require_windows("a sparse file")
    if not volume_supports_sparse(folder):
        raise EnvironmentUnavailable("this volume does not report sparse-file support")
    if shutil.disk_usage(folder).free <= logical_size:
        raise EnvironmentUnavailable("there is less free space than the file's logical size; not risking the drive")
    probe = folder / ".sparse-probe"
    try:
        if not _write_sparse(probe, _PROBE_BYTES) or not _holds_holes(probe):
            raise EnvironmentUnavailable("a 16 MiB probe took real disk space, so the volume is not keeping holes")
    finally:
        probe.unlink(missing_ok=True)


def create_sparse_giant(path: Path, logical_size: int) -> None:
    """A file whose size is ``logical_size`` but which occupies almost nothing on disk (see ``check_sparse_room``)."""
    check_sparse_room(path.parent, logical_size)
    if not _write_sparse(path, logical_size) or not _holds_holes(path):
        path.unlink(missing_ok=True)
        raise EnvironmentUnavailable("the sparse file took real disk space, so it was removed")
