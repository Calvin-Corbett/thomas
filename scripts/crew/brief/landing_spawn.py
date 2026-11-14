"""Start child processes without a console window. Stdlib only.

Agents run land.py from parents that have no console (a tool shell, a service). On Windows every child such a parent
starts, python, git or taskkill, then gets a visible console window of its own: a measurement that spawned dozens of
them put dozens of windows on the desktop. ``CREATE_NO_WINDOW`` on every spawn prevents it, so every spawn the
landing tools make goes through ``run`` or ``popen`` here.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any

NO_WINDOW = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW


def hidden(kw: dict[str, Any]) -> dict[str, Any]:
    """The keyword arguments with the no-window flag added to whatever creation flags the caller already set."""
    kw["creationflags"] = int(kw.get("creationflags") or 0) | NO_WINDOW
    return kw


def run(*args: Any, **kw: Any) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(*args, **hidden(kw))


def popen(*args: Any, **kw: Any) -> subprocess.Popen[Any]:
    return subprocess.Popen(*args, **hidden(kw))
