"""Setting up Thomas's ears: everything a listening model needs, done for you after one click on Set up now.

Two steps, each skipped when it is already done. First the speech engine: when sherpa-onnx is missing from Thomas's own
Python (someone updated Thomas without running the installer again), it is installed there with pip, with no window.
Then the model: each of its files that is not already in place is downloaded from where its makers publish it
(voice_ears_models.py) into ``<name>.part``, checked against its size and SHA-256, and only then moved into place. A file
that does not match is thrown away and the set-up says so; a half-finished one is started again next time.

It runs in a thread of its own, so Thomas keeps answering while it works. How far it has got is kept here, one entry per
model, and read by ``GET /api/voice/setup``. Nothing here starts on its own: only ``POST /api/voice/setup`` starts it.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from thomas.server import voice_ears_models

CHUNK = 1 << 20
_NO_WINDOW = int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0
_FAILURES = (OSError, ValueError, urllib.error.URLError, subprocess.SubprocessError)

_progress: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()


def engine_ready() -> bool:
    return importlib.util.find_spec("sherpa_onnx") is not None


def progress(model_id: str) -> dict[str, Any]:
    """``{"state", "done", "total", "step", "error"}`` for one model. ``state`` is idle, working, ready or failed."""
    entry = voice_ears_models.get(model_id)
    with _lock:
        found = _progress.get(entry["id"])
        if found:
            return dict(found)
    return {"state": "idle", "done": 0, "total": voice_ears_models.size(entry), "step": "", "error": ""}


def _note(model_id: str, **changes: Any) -> None:
    with _lock:
        _progress.setdefault(model_id, {"state": "idle", "done": 0, "total": 0, "step": "", "error": ""}).update(
            changes
        )


def start(
    model_id: str,
    folder: Path,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
    install: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Start setting up ``model_id`` into ``folder`` unless it is already being set up; returns its progress."""
    entry = voice_ears_models.get(model_id)
    with _lock:
        if (_progress.get(entry["id"]) or {}).get("state") == "working":
            return dict(_progress[entry["id"]])
        _progress[entry["id"]] = {
            "state": "working",
            "done": 0,
            "total": voice_ears_models.size(entry),
            "step": "starting",
            "error": "",
        }
    worker = threading.Thread(
        target=_run,
        args=(entry, Path(folder), opener, install or install_engine),
        name="thomas-ears-setup",
        daemon=True,
    )
    worker.start()
    return progress(entry["id"])


def _run(entry: dict[str, Any], folder: Path, opener: Callable[..., Any], install: Callable[[], None]) -> None:
    model_id = entry["id"]
    try:
        if not engine_ready():
            _note(model_id, step="engine")
            install()
            importlib.invalidate_caches()
            if not engine_ready():
                raise OSError("the speech engine (sherpa-onnx) still is not there after installing it")
        _note(model_id, step="model")
        folder.mkdir(parents=True, exist_ok=True)
        done = 0
        for name, (size, digest) in entry["files"].items():
            target = folder / name
            if not (target.is_file() and target.stat().st_size == size):
                _download(
                    entry["source"] + name,
                    target,
                    size,
                    digest,
                    opener,
                    lambda got, base=done: _note(model_id, done=base + got),
                )
            done += size
            _note(model_id, done=done)
        _note(model_id, state="ready", step="ready")
    except _FAILURES as exc:
        _note(model_id, state="failed", error=str(exc) or exc.__class__.__name__)


def _download(
    url: str, target: Path, size: int, digest: str, opener: Callable[..., Any], told: Callable[[int], None]
) -> None:
    part = target.with_name(target.name + ".part")
    hasher, got = hashlib.sha256(), 0
    request = urllib.request.Request(url, headers={"User-Agent": "Thomas"})
    with opener(request, timeout=60) as reply, part.open("wb") as out:
        while chunk := reply.read(CHUNK):
            got += len(chunk)
            if got > size:
                break
            hasher.update(chunk)
            out.write(chunk)
            told(got)
    if got != size or hasher.hexdigest() != digest:
        part.unlink(missing_ok=True)
        raise ValueError(f"{target.name} did not download whole and unchanged; try setting up again")
    os.replace(part, target)


def install_engine() -> None:
    """Install the pinned speech engine into the Python Thomas runs in. The one program this voice code ever starts."""
    done = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", voice_ears_models.ENGINE],
        capture_output=True,
        text=True,
        timeout=900,
        creationflags=_NO_WINDOW,
        check=False,
    )
    if done.returncode != 0:
        tail = (done.stderr or done.stdout or "").strip().splitlines()[-1:] or ["pip failed"]
        raise OSError(f"Thomas could not install his speech engine: {tail[0][:200]}")


__all__ = ["engine_ready", "install_engine", "progress", "start"]
