"""Remove link targets a browser cannot open, keeping the link's label.

A model sometimes links to a sandbox or local path (``sandbox:``, ``file:``,
``/mnt/``, a drive path). Your browser cannot follow those, so the reply keeps
the words and drops the dead target. It lives in ``core`` so both the agent
and the marketplace specialists can use it without importing each other.
"""

from __future__ import annotations

import re

_SANDBOX_LINK_RE = re.compile(r"\[([^\]]*)\]\(\s*(?:sandbox:|file:|/mnt/|[A-Za-z]:[\/])[^)]*\)")


def strip_sandbox_links(text: str) -> str:
    """Keep the label while removing a browser-inaccessible local link target."""
    src = str(text or "")
    if "](" not in src:
        return src
    return _SANDBOX_LINK_RE.sub(lambda match: (match.group(1) or "").strip(), src)
