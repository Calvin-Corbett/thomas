"""Tool-call arguments as the text a stream carries them in.

A provider sends tool arguments as a JSON string, as an already-decoded object, or not at all. The OpenAI-family
streamer wants text every time, so this turns each shape into one.
"""

from __future__ import annotations

import json
from typing import Any


def coerce_args_fragment(raw: Any) -> str:
    """Return ``raw`` as text: ``""`` for nothing, a string as it is, anything else as JSON (or ``str`` if it will not encode)."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    try:
        return json.dumps(raw, ensure_ascii=False)
    except Exception:
        return str(raw)
