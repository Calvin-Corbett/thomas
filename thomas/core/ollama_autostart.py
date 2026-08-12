"""Best-effort auto-start for a local Ollama backend.

When the user's selected model profile points at a local Ollama server that
is installed but not running, every chat dies with a connection error and a
"Try: ollama serve" hint. For an AI-first product the right behavior is to
make the user's stated choice true: start the local backend ourselves, once,
and let the caller's normal connection retries succeed.

Strictly bounded:
- only for loopback URLs on the default Ollama port (11434),
- only when an ollama binary can be found,
- at most one spawn attempt per process per cooldown window,
- opt-out via THOMAS_OLLAMA_AUTOSTART=0.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from urllib.parse import urlparse

log = logging.getLogger(__name__)

_LOCK = threading.Lock()
_LAST_ATTEMPT_TS: float = 0.0
_COOLDOWN_S = 120.0

_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "[::1]", "::1"}
_OLLAMA_PORT = 11434


def _env_enabled() -> bool:
    raw = str(os.environ.get("THOMAS_OLLAMA_AUTOSTART", "1")).strip().lower()
    return raw not in {"0", "false", "no", "off"}


def is_local_ollama_url(base_url: str | None) -> bool:
    """True when ``base_url`` points at a loopback Ollama default endpoint."""
    try:
        parsed = urlparse(str(base_url or ""))
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    port = parsed.port if parsed.port is not None else (443 if parsed.scheme == "https" else 80)
    return host in _LOOPBACK_HOSTS and port == _OLLAMA_PORT


def _find_ollama_binary() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    if os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA", "")
        candidate = os.path.join(local_app, "Programs", "Ollama", "ollama.exe")
        if local_app and os.path.isfile(candidate):
            return candidate
    return None


def maybe_autostart_ollama(base_url: str | None) -> bool:
    """Spawn ``ollama serve`` detached if ``base_url`` is a local Ollama.

    Returns True when a spawn was attempted (caller may want to extend its
    retry delay to give the server a moment to bind). Never raises.
    """
    global _LAST_ATTEMPT_TS
    if not _env_enabled() or not is_local_ollama_url(base_url):
        return False
    with _LOCK:
        now = time.monotonic()
        if _LAST_ATTEMPT_TS and now - _LAST_ATTEMPT_TS < _COOLDOWN_S:
            return False
        binary = _find_ollama_binary()
        if not binary:
            return False
        _LAST_ATTEMPT_TS = now
        try:
            kwargs: dict = {
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if os.name == "nt":
                # Detach fully so the backend outlives this process and opens no console.
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(
                    subprocess, "DETACHED_PROCESS", 0x00000008
                )
            else:
                kwargs["start_new_session"] = True
            subprocess.Popen([binary, "serve"], **kwargs)
            log.info("Local Ollama was not running; started it automatically (%s serve)", binary)
            return True
        except OSError as exc:
            log.warning("Could not auto-start local Ollama: %s", exc)
            return False
