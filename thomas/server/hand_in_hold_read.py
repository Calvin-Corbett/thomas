"""Read a Build conversation for Autopilot's decisions and the hand-in without holding every run's transcript.

On 2026-11-04 a finished Thomas project's hand-in died with MemoryError: ``hand_in_hold.still_current`` loaded the
whole conversation, a 9 MB file of which 8.6 MB was the transcripts of 54 earlier runs, and nothing caught it. The
change it had made was stranded.

Every decision that reads a transcript reads only its tail (``autopilot_park._TAIL_CHARS``, the most any of them
reads), so each turn's transcript is cut to that tail while the file is parsed, one turn at a time: only one whole
transcript is held at once, and the last turn's is kept whole, so :func:`hand_in_hold.generation` (a hash of the last
turn) is the same as for the whole file. A file that exists but cannot be read, or is too large to read even so, is
not "gone": :func:`last_failure` says why, and ``hand_in_hold`` holds the change for its next try instead of dropping
it or crashing.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

from thomas.core import atomic_json

log = logging.getLogger(__name__)
TAIL_CHARS = 200_000  # autopilot_park._TAIL_CHARS: the most of one turn's transcript any decision reads
_failures: dict[str, str] = {}
_lock = threading.Lock()


def _parse(text: str) -> Any:
    whole: list[dict[str, Any]] = []  # the latest turn seen so far keeps its whole transcript

    def turn(obj: dict[str, Any]) -> dict[str, Any]:
        if "role" in obj and isinstance(obj.get("transcript"), str):
            if whole:
                earlier = whole.pop()
                earlier["transcript"] = earlier["transcript"][-TAIL_CHARS:]
            whole.append(obj)
        return obj

    return json.loads(text, object_hook=turn)


def read(path: Path) -> dict[str, Any] | None:
    """The conversation at ``path``, its earlier transcripts cut to their tails; None when missing or unreadable."""
    key = str(path)
    try:
        if not path.is_file():
            return None
        data = _parse(atomic_json.read_text_with_retry(path))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, MemoryError, RecursionError) as exc:  # ValueError: bad JSON or bad bytes
        why = (
            f"{type(exc).__name__}: {exc.strerror}" if isinstance(exc, OSError) and exc.strerror else type(exc).__name__
        )
        with _lock:
            _failures[key] = why
        log.warning("conversation %s could not be read (%s)", path.stem, why)
        return None
    with _lock:
        _failures.pop(key, None)
    return data if isinstance(data, dict) else None


def last_failure(path: Path) -> str:
    """Why the last :func:`read` of ``path`` failed, or "" when it did not."""
    with _lock:
        return _failures.get(str(path), "")
