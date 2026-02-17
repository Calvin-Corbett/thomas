"""Task journal — writes human-readable markdown task files.

Each non-trivial agent run creates a file in the journal directory (default: ./tasks/).
The file records the original request, routing plan, tool calls, and final result.
Any agent or human reading the file gets full context to continue the work.

Design:
- Append-only during the task (crash-safe: each write opens, appends, closes).
- Stdlib only — no SQLite, no threads, no external deps.
- Idempotent finalize — safe to call multiple times.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

# Routes that should NOT produce journal entries.
_SKIP_ROUTES = frozenset({"casual", "personal", "meta"})

# Minimum prompt length to create a journal.
_MIN_PROMPT_LEN = 10


def _slugify(text: str, max_len: int = 50) -> str:
    """Turn prompt text into a filesystem-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text).strip("-")
    return text[:max_len].rstrip("-") or "task"


class TaskJournal:
    """Writes a single markdown task file for one agent run."""

    def __init__(
        self,
        journal_dir: Path,
        run_id: str,
        prompt: str,
        route: Dict[str, Any],
        model_info: Dict[str, Any],
    ) -> None:
        self._finalized = False
        self._iteration_count = 0
        self._tool_count = 0

        date_str = datetime.now().strftime("%Y-%m-%d")
        time_str = datetime.now().strftime("%H:%M")
        short_id = run_id[:6]
        slug = _slugify(prompt)
        filename = f"{date_str}_{short_id}_{slug}.md"

        self.path = journal_dir / filename

        # Build the title from the first ~80 chars of the prompt.
        title = prompt.strip()
        if len(title) > 80:
            title = title[:77] + "..."

        route_path = route.get("path", "unknown")
        confidence = route.get("confidence", 0.0)
        mode = route.get("mode", "auto")
        tools_policy = route.get("tools_policy", "auto")
        model_name = model_info.get("model", "unknown")
        provider = model_info.get("provider", "unknown")

        header = (
            f"# {title}\n"
            f"\n"
            f"> **Created:** {date_str} {time_str} | **Status:** in_progress | **Run:** {run_id}\n"
            f"\n"
            f"## Original Request\n"
            f'"{prompt.strip()}"\n'
            f"\n"
            f"## Plan\n"
            f"- Route: {route_path} (confidence: {confidence:.2f})\n"
            f"- Mode: {mode} | Tools policy: {tools_policy}\n"
            f"- Model: {model_name} via {provider}\n"
            f"\n"
            f"## Log\n"
        )

        try:
            journal_dir.mkdir(parents=True, exist_ok=True)
            self.path.write_text(header, encoding="utf-8")
        except OSError as e:
            log.warning("Failed to create task journal %s: %s", self.path, e)

    def log_iteration(
        self, iteration: int, token_estimate: int = 0
    ) -> None:
        """Append a timestamped iteration start line."""
        self._iteration_count = iteration
        ts = datetime.now().strftime("%H:%M")
        line = f"- [{ts}] Iteration {iteration} (~{token_estimate:,} context tokens)\n"
        self._append(line)

    def log_tool_result(
        self, tool_name: str, ok: bool, duration_ms: float
    ) -> None:
        """Append a tool result line."""
        self._tool_count += 1
        status = "ok" if ok else "FAILED"
        ts = datetime.now().strftime("%H:%M")
        line = f"  - [{ts}] {tool_name} → {status} ({duration_ms:.0f}ms)\n"
        self._append(line)

    def finalize(
        self,
        ok: bool,
        iterations: int,
        tool_calls: int,
        total_tokens: int = 0,
        error: Optional[str] = None,
    ) -> None:
        """Write the result section and update the status in the header."""
        if self._finalized:
            return
        self._finalized = True

        status = "complete" if ok else "error"

        result_lines = [
            "\n## Result\n",
            f"{iterations} iteration(s), {tool_calls} tool call(s)",
        ]
        if total_tokens:
            result_lines[-1] += f", {total_tokens:,} tokens"
        result_lines[-1] += "\n"
        if error:
            result_lines.append(f"\n**Error:** {error}\n")

        self._append("".join(result_lines))

        # Rewrite the status in the header line.
        try:
            content = self.path.read_text(encoding="utf-8")
            content = content.replace(
                "**Status:** in_progress",
                f"**Status:** {status}",
                1,
            )
            self.path.write_text(content, encoding="utf-8")
        except OSError as e:
            log.warning("Failed to update journal status for %s: %s", self.path, e)

    def _append(self, text: str) -> None:
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            log.debug("Journal append failed: %s", e)


def should_create_journal(
    prompt: str,
    route: Dict[str, Any],
    enabled: bool = True,
) -> bool:
    """Decide whether a journal should be created for this request."""
    if not enabled:
        return False
    if len(prompt.strip()) < _MIN_PROMPT_LEN:
        return False
    route_path = route.get("path", "")
    if route_path in _SKIP_ROUTES:
        return False
    return True
