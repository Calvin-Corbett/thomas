"""Whether this process runs as the cage account, read from Windows itself.

The caged Thomas runs as ``thomas-agent`` (scripts/cage). That account cannot write Thomas's code, and the firewall
rule "Thomas cage: no direct connections out" (scripts/cage/enable_network_fence.ps1) blocks everything it opens but
loopback, so its only way out is the proxy's pinned hosts. That is what makes a shell safe to hand a Build run there
(forge_code_settings.direct_shell_allowed). The name comes from the process's own token, not from USERNAME or any
other variable: a variable anyone can set must never hand your own account a shell.
"""

from __future__ import annotations

import sys

CAGE_ACCOUNT = "thomas-agent"


def process_account() -> str:
    """The Windows account this process runs as, from its token; "" where that cannot be read."""
    if sys.platform != "win32":
        return ""
    try:
        import ctypes

        size = ctypes.c_ulong(257)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not ctypes.windll.advapi32.GetUserNameW(buffer, ctypes.byref(size)):
            return ""
        return str(buffer.value or "")
    except (AttributeError, OSError, ValueError):
        return ""


def running_as_cage_account() -> bool:
    """True only when Windows says this process is the cage account."""
    return process_account().casefold() == CAGE_ACCOUNT


__all__ = ["CAGE_ACCOUNT", "process_account", "running_as_cage_account"]
