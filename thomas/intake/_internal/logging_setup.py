from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import default_state_dir


def setup_logging(name: str, level: str = "INFO") -> None:
    """Configure console + rotating file logs under ~/.thomas/."""
    lvl = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(lvl)

    # Prevent duplicate handlers if called twice.
    if any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        return

    state_dir = default_state_dir()
    log_dir = state_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{name}.log"

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    ch = logging.StreamHandler()
    ch.setLevel(lvl)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    fh = RotatingFileHandler(str(log_path), maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fh.setLevel(lvl)
    fh.setFormatter(fmt)
    root.addHandler(fh)
