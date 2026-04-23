"""Browser download tracking (Thomas-native).

This module provides a dependency-free way to detect the *next completed download*
in a download directory.

How it works
- Take an initial snapshot of the directory (files + size + mtime).
- Poll the directory until a file is either:
  - newly created, or
  - modified (size/mtime changed) since the snapshot.
- Once a candidate is found, wait until the file is "stable" for N consecutive
  polls (size and mtime unchanged). Then compute SHA-256.

Design goals
- Clear input/output contracts (dataclasses).
- Deterministic, machine-readable errors (stable error codes).
- Portable: no OS-specific filesystem watchers.

Limitations
This is a heuristic. For perfect fidelity you'd hook into browser download
events (e.g., Playwright download events).
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional


class DownloadTrackingError(RuntimeError):
    """Deterministic error raised by :func:`track_download`.

    Attributes:
        code: Stable machine-readable error code (e.g. ``BROWSER.DOWNLOAD_TIMEOUT``).
        message: Human-readable explanation.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class DownloadTrackingInput:
    """Input contract for download tracking.

    Attributes:
        download_dir:
            Directory where downloads are expected to appear. If ``None``, Thomas
            will try to read ``THOMAS_BROWSER_DOWNLOAD_DIR`` or ``THOMAS_DOWNLOAD_DIR``.
        timeout_s:
            Total time limit (seconds) including waiting for the download to
            complete (stabilize).
        poll_interval_s:
            Polling interval in seconds.
        stable_checks:
            Number of consecutive stable observations required to consider a file
            complete.
        ignore_suffixes:
            File suffixes ignored while watching (common partial-download extensions).
    """

    download_dir: Optional[Path]
    timeout_s: float = 30.0
    poll_interval_s: float = 0.1
    stable_checks: int = 2
    ignore_suffixes: tuple[str, ...] = (".crdownload", ".part", ".tmp", ".download")


@dataclass(frozen=True, slots=True)
class DownloadTrackingResult:
    """Output contract for download tracking."""

    file_path: Path
    bytes: int
    sha256: str
    detected_at: float  # epoch seconds
    duration_s: float

    @property
    def file_name(self) -> str:
        return self.file_path.name

    def to_dict(self) -> dict[str, object]:
        return {
            "file_path": str(self.file_path),
            "file_name": self.file_name,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "detected_at": self.detected_at,
            "duration_s": self.duration_s,
        }


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    path: Path
    size: int
    mtime_ns: int


def _resolve_download_dir(download_dir: Optional[Path]) -> Path:
    if download_dir is not None:
        return Path(download_dir)

    for key in ("THOMAS_BROWSER_DOWNLOAD_DIR", "THOMAS_DOWNLOAD_DIR"):
        value = os.environ.get(key)
        if value:
            return Path(value)

    raise DownloadTrackingError(
        "BROWSER.DOWNLOAD_DIR_NOT_CONFIGURED",
        "download_dir was not provided and no THOMAS_BROWSER_DOWNLOAD_DIR/THOMAS_DOWNLOAD_DIR is set",
    )


def _normalize_input(inp: DownloadTrackingInput) -> DownloadTrackingInput:
    if inp.timeout_s <= 0:
        raise DownloadTrackingError("BROWSER.INVALID_TIMEOUT", "timeout_s must be > 0")
    if inp.poll_interval_s <= 0:
        raise DownloadTrackingError("BROWSER.INVALID_POLL_INTERVAL", "poll_interval_s must be > 0")
    if inp.stable_checks <= 0:
        raise DownloadTrackingError("BROWSER.INVALID_STABLE_CHECKS", "stable_checks must be > 0")

    resolved_dir = _resolve_download_dir(inp.download_dir)

    return DownloadTrackingInput(
        download_dir=resolved_dir,
        timeout_s=float(inp.timeout_s),
        poll_interval_s=float(inp.poll_interval_s),
        stable_checks=int(inp.stable_checks),
        ignore_suffixes=tuple(inp.ignore_suffixes),
    )


def _snapshot_files(download_dir: Path, ignore_suffixes: tuple[str, ...]) -> dict[str, _FileSnapshot]:
    ignored = {s.lower() for s in ignore_suffixes}

    try:
        entries = list(download_dir.iterdir())
    except FileNotFoundError as exc:
        raise DownloadTrackingError("BROWSER.DOWNLOAD_DIR_NOT_FOUND", f"download_dir not found: {download_dir}") from exc
    except NotADirectoryError as exc:
        raise DownloadTrackingError(
            "BROWSER.DOWNLOAD_DIR_NOT_DIRECTORY", f"download_dir is not a directory: {download_dir}"
        ) from exc
    except PermissionError as exc:
        raise DownloadTrackingError(
            "BROWSER.DOWNLOAD_DIR_NOT_READABLE", f"download_dir not readable: {download_dir}"
        ) from exc
    except OSError as exc:
        raise DownloadTrackingError(
            "BROWSER.DOWNLOAD_DIR_LIST_FAILED", f"Unable to list download_dir: {download_dir}"
        ) from exc

    snap: dict[str, _FileSnapshot] = {}
    for p in entries:
        try:
            if not p.is_file():
                continue
            if p.suffix.lower() in ignored:
                continue
            st = p.stat()
            mtime_ns = getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000))
            snap[p.name] = _FileSnapshot(path=p, size=int(st.st_size), mtime_ns=int(mtime_ns))
        except (FileNotFoundError, PermissionError):
            # Transient or unreadable files are ignored until they become readable.
            continue
        except OSError:
            continue

    return snap


def _new_or_changed(current: Mapping[str, _FileSnapshot], baseline: Mapping[str, _FileSnapshot]) -> list[_FileSnapshot]:
    candidates: list[_FileSnapshot] = []
    for name, snap in current.items():
        base = baseline.get(name)
        if base is None or base.size != snap.size or base.mtime_ns != snap.mtime_ns:
            candidates.append(snap)
    return candidates


def _pick_candidate(candidates: list[_FileSnapshot]) -> _FileSnapshot:
    # Deterministic choice when multiple files appear/change:
    # newest mtime first, then name.
    return sorted(candidates, key=lambda s: (s.mtime_ns, s.path.name), reverse=True)[0]


def _wait_for_stable_file(
    path: Path,
    poll_interval_s: float,
    stable_checks: int,
    deadline_monotonic: float,
) -> tuple[int, int]:
    """Wait until a file stops changing (size+mtime).

    Raises:
        DownloadTrackingError: if the file never stabilizes before deadline.
    """

    stable_count = 0
    prev: Optional[tuple[int, int]] = None

    while stable_count < stable_checks:
        if time.monotonic() >= deadline_monotonic:
            raise DownloadTrackingError(
                "BROWSER.DOWNLOAD_STABILIZE_TIMEOUT",
                f"Download did not stabilize before timeout: {path}",
            )

        try:
            st = path.stat()
        except (FileNotFoundError, PermissionError):
            prev = None
            stable_count = 0
            time.sleep(poll_interval_s)
            continue
        except OSError as exc:
            raise DownloadTrackingError(
                "BROWSER.DOWNLOAD_FILE_STAT_FAILED", f"Unable to stat downloaded file: {path}"
            ) from exc

        size = int(st.st_size)
        mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000)))
        cur = (size, mtime_ns)

        if prev == cur:
            stable_count += 1
        else:
            stable_count = 0
            prev = cur

        time.sleep(poll_interval_s)

    assert prev is not None
    return prev[0], prev[1]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 128), b""):
                h.update(chunk)
    except FileNotFoundError as exc:
        raise DownloadTrackingError("BROWSER.DOWNLOAD_FILE_MISSING", f"downloaded file missing: {path}") from exc
    except PermissionError as exc:
        raise DownloadTrackingError(
            "BROWSER.DOWNLOAD_FILE_NOT_READABLE", f"downloaded file not readable: {path}"
        ) from exc
    except OSError as exc:
        raise DownloadTrackingError(
            "BROWSER.DOWNLOAD_FILE_READ_FAILED", f"unable to read downloaded file: {path}"
        ) from exc

    return h.hexdigest()


def track_download(inp: DownloadTrackingInput) -> DownloadTrackingResult:
    """Track the next completed download.

    A download is considered complete once a candidate file is stable for
    ``stable_checks`` polls.

    Raises:
        DownloadTrackingError: deterministic, machine-readable failures.
    """

    normalized = _normalize_input(inp)
    assert normalized.download_dir is not None  # for type-checkers

    download_dir = normalized.download_dir
    start = time.monotonic()
    deadline = start + normalized.timeout_s

    baseline = _snapshot_files(download_dir, normalized.ignore_suffixes)

    while time.monotonic() < deadline:
        current = _snapshot_files(download_dir, normalized.ignore_suffixes)
        candidates = _new_or_changed(current, baseline)

        if candidates:
            chosen = _pick_candidate(candidates).path
            size, _mtime_ns = _wait_for_stable_file(
                chosen,
                poll_interval_s=normalized.poll_interval_s,
                stable_checks=normalized.stable_checks,
                deadline_monotonic=deadline,
            )

            if time.monotonic() >= deadline:
                raise DownloadTrackingError(
                    "BROWSER.DOWNLOAD_TIMEOUT",
                    f"No completed download detected within {normalized.timeout_s} seconds",
                )

            digest = _sha256_file(chosen)
            end = time.monotonic()
            return DownloadTrackingResult(
                file_path=chosen,
                bytes=size,
                sha256=digest,
                detected_at=time.time(),
                duration_s=end - start,
            )

        time.sleep(normalized.poll_interval_s)

    raise DownloadTrackingError(
        "BROWSER.DOWNLOAD_TIMEOUT",
        f"No completed download detected within {normalized.timeout_s} seconds",
    )
