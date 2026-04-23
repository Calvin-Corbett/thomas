"""REPL-facing project instruction helpers.

Thin compatibility wrapper around the shared agent implementation.
"""

from __future__ import annotations

from thomas.agent.project_instructions import (
    discover_project_instructions,
    instruction_file_path,
)

__all__ = ["discover_project_instructions", "instruction_file_path"]
