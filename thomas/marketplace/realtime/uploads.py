from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class UploadInfo:
    handle: str
    path: Path
    name: str
    mime: str
    size: int


def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


def new_handle() -> str:
    return f"up_{uuid.uuid4().hex[:12]}"


def safe_filename(name: str) -> str:
    # Avoid path tricks; keep it readable
    name = os.path.basename(name).strip().replace("\\", "_").replace("/", "_")
    if not name:
        name = "upload.bin"
    return name[:140]


def store_upload(uploads_dir: Path, *, filename: str, mime: str, data: bytes) -> UploadInfo:
    ensure_dir(uploads_dir)
    handle = new_handle()
    ts = int(time.time())
    safe = safe_filename(filename)
    out = uploads_dir / f"{ts}_{handle}_{safe}"
    out.write_bytes(data)
    return UploadInfo(handle=handle, path=out, name=safe, mime=mime, size=len(data))
