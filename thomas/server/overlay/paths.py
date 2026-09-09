"""Where a user's overlay lives. This module never creates anything.

THOMAS_OVERLAY_DIR wins; otherwise <THOMAS_HOME>/overlay, where THOMAS_HOME is
the profile-suffixed data dir the config layer exports at boot
(thomas/core/config.py, apply_runtime_data_env_defaults). Outside a running
server (the CLI, a test) the config resolver is asked directly.

The base reads this directory at request time and writes it only through
thomas.server.overlay.manifest on an explicit user action. Nothing at startup, page
serving, fingerprinting, plugin install, janitors or updates may create,
modify or delete anything under it. docs/OVERLAY.md is the contract and
tests/test_overlay_injection_contract.py is the proof that serving every page
leaves an absent overlay absent.
"""

from __future__ import annotations

import os
from pathlib import Path


def overlay_dir() -> Path:
    """The overlay directory for this Thomas, whether or not it exists."""
    raw = str(os.environ.get("THOMAS_OVERLAY_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser()
    home = str(os.environ.get("THOMAS_HOME") or "").strip()
    if home:
        return Path(home).expanduser() / "overlay"
    from thomas.core.config import resolve_thomas_data_dir  # heavy; only when the env is not set

    return Path(resolve_thomas_data_dir()) / "overlay"


def manifest_path() -> Path:
    return overlay_dir() / "manifest.json"
