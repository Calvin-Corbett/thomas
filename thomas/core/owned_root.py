"""Where Thomas's own ``~/.thomas`` tree lives, decided in one place.

Legacy Work apps, global skills and the lane stores all sit under that tree. They
used to build the path from ``Path.home()`` directly, so a Thomas started with a
data directory of its own (a test server, a second profile, the caged account)
still read and wrote the machine user's real files. This follows the same rules
the rest of Thomas follows for its data:

1. ``THOMAS_OWNED_ROOT`` names the tree outright.
2. Otherwise a ``THOMAS_DATA_DIR`` (or ``THOMAS_PROFILE``) that is not the OS
   default puts the tree inside that data directory, at ``<data dir>/.thomas``.
3. Otherwise it is ``~/.thomas`` -- the same path a normal install has always used.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from thomas.core.config import resolve_thomas_data_dir


def thomas_owned_tree(*, env: Mapping[str, str] | None = None, home: str | Path | None = None) -> Path:
    """The ``.thomas`` folder this Thomas owns. ``env`` and ``home`` exist so callers can ask about another setup."""
    env_map = env if env is not None else os.environ
    explicit = str(env_map.get("THOMAS_OWNED_ROOT") or "").strip()
    if explicit:
        return Path(explicit).expanduser()
    moved = str(env_map.get("THOMAS_DATA_DIR") or "").strip() or str(env_map.get("THOMAS_PROFILE") or "").strip()
    if moved:
        active = resolve_thomas_data_dir(env=env_map)
        if active != resolve_thomas_data_dir(env={}):
            return active / ".thomas"
    return (Path(home).expanduser() if home else Path.home()) / ".thomas"


def freedom_transit_dir(*, env: Mapping[str, str] | None = None, home: str | Path | None = None) -> Path:
    """Legacy user Work files (apps, lane definitions, proposals, stats)."""
    return thomas_owned_tree(env=env, home=home) / "freedom_transit"


def global_skills_dir(*, env: Mapping[str, str] | None = None, home: str | Path | None = None) -> Path:
    return thomas_owned_tree(env=env, home=home) / "skills"
