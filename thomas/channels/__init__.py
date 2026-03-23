"""Backward-compatible bridge for the moved channels package."""

from __future__ import annotations

from pathlib import Path
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)
_MARKETPLACE_DIR = Path(__file__).resolve().parents[1] / "marketplace" / "channels"
_MARKETPLACE_PATH = str(_MARKETPLACE_DIR)
if _MARKETPLACE_DIR.exists() and _MARKETPLACE_PATH not in __path__:
    __path__.append(_MARKETPLACE_PATH)

from thomas.marketplace.channels import *  # noqa: F401,F403

del Path
del extend_path
del _MARKETPLACE_DIR
del _MARKETPLACE_PATH
