"""What a capture is told and what it may use: the defaults, the settings, the refusal and the size budget.

Part of the capture tool; ``capture.py`` is its command line (see its notes) and re-exports these names.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .places import FILE_LIMIT
from .private import existing

GB = 1024**3
DEFAULT_GIT = r"C:\Program Files\Git\cmd\git.exe"
DEFAULT_KEEP = r"C:\ProgramData\ThomasKeep"
DEFAULT_WORK = r"C:\r\keeper-work"
DEFAULT_SERVER = "http://127.0.0.1:8898"
CACHE_FOLDERS = ("__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", "node_modules", ".venv")
CID = re.compile(r"[A-Za-z0-9_.-]{1,128}")
SUBSTANTIAL = 64  # design 5.2: same bytes elsewhere on dev count only for real content


class CaptureRefused(Exception):
    """Nothing was written to the keep; the message says why."""


@dataclass
class Settings:
    keep: Path
    work: Path
    git_path: str
    label: str = ""
    provenance: str = ""
    cap_bytes: int = 5 * GB
    min_free_bytes: int = 15 * GB
    file_limit: int = FILE_LIMIT
    state_dir: Path | None = None
    fs: object = None
    now: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))


class Budget:
    """What a capture may put on disk while it is built: the cap, and the free-space floor of the work folder's drive.

    ``check`` runs before and after every entry the archive takes, and around the bundle, so a large or hostile
    place is refused as soon as it crosses the cap, not after all of it has been written to the work folder.
    """

    def __init__(self, settings: Settings) -> None:
        self.cap, self.floor, self.work = settings.cap_bytes, settings.min_free_bytes, Path(settings.work)

    def check(self, on_disk: int, incoming: int = 0, *, exact: bool = False) -> None:
        """Refuse when the capture is over the cap or ``incoming`` more bytes would take the work drive under the floor.

        ``on_disk`` is what the capture holds in the work folder now. With ``exact`` the incoming size is known (not
        a size before compression), so a write that would cross the cap is refused before it starts.
        """
        total = on_disk + (incoming if exact else 0)
        if total > self.cap:
            raise CaptureRefused(f"this capture is over the {self.cap}-byte cap ({total} bytes); nothing written")
        free = shutil.disk_usage(existing(self.work)).free
        if free - incoming < self.floor:
            raise CaptureRefused(
                f"the work folder's drive has {free} bytes free; {incoming} more would take it under the "
                f"{self.floor}-byte floor; nothing written"
            )
