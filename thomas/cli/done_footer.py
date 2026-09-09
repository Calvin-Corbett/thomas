"""The footer ``thomas chat`` prints when a run ends.

Streamed tokens never include the verification trailer - the acceptance
contract appends it to the done event's text after the stream has ended - so
the footer prints it explicitly, or the reader never sees what failed and what
nobody checked. Kept out of ``_commands_base`` (size-waivered) on purpose.
"""

from __future__ import annotations

import sys
from typing import Any

TRAILER_MARKER = "\nVerification: "


def print_done_footer(data: dict[str, Any]) -> None:
    """Blank line, the verification trailer when present, then the iteration count."""

    sys.stdout.write("\n")
    done_text = str(data.get("text") or "")
    marker = done_text.rfind(TRAILER_MARKER)
    if marker >= 0:
        sys.stdout.write(done_text[marker + 1 :].rstrip() + "\n")
    iters = int(data.get("iterations") or 0)
    tool_calls = int(data.get("tool_calls") or 0)
    if tool_calls > 0:
        sys.stdout.write(
            f"\033[90m({iters} iteration{'s' if iters != 1 else ''}, "
            f"{tool_calls} tool call{'s' if tool_calls != 1 else ''})\033[0m\n"
        )


__all__ = ["TRAILER_MARKER", "print_done_footer"]
