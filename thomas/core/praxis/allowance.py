"""Machine-sized Praxis admission without a limit on the size of a plan.

The allowance controls only how many light builders start together. Provider
request pacing is a separate per-credential concern. Every planned assignment
remains owned by the team and is admitted in a later wave.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _available_memory() -> int | None:
    try:
        import psutil
    except ImportError:
        return None
    try:
        return int(psutil.virtual_memory().available)
    except (AttributeError, OSError, ValueError):
        return None


@dataclass(frozen=True)
class BuildAllowance:
    assignments: int
    concurrent: int
    waves: int
    available_memory_bytes: int | None
    final_report_reserved: bool = True

    @classmethod
    def for_machine(
        cls,
        assignments: int,
        *,
        cpu_count: int | None = None,
        available_memory_bytes: int | None = None,
    ) -> BuildAllowance:
        """Size one wave from current resources; never refuse a larger plan."""
        if assignments < 1:
            raise ValueError("a Build team needs at least one assignment")
        cpus = max(1, int(cpu_count if cpu_count is not None else (os.cpu_count() or 1)))
        memory = available_memory_bytes if available_memory_bytes is not None else _available_memory()
        if memory is not None and memory < 0:
            raise ValueError("available memory cannot be negative")
        # Network-bound in-process builders are light; process-based builders
        # still need room. This is a wave size, never a limit on total agents.
        cpu_slots = cpus * 8
        memory_slots = max(1, memory // (64 * 1024 * 1024)) if memory is not None else cpu_slots
        concurrent = min(assignments, cpu_slots, memory_slots)
        return cls(assignments, concurrent, (assignments + concurrent - 1) // concurrent, memory)

    def snapshot(self) -> dict[str, int | bool | None]:
        return {
            "assignments": self.assignments,
            "concurrent": self.concurrent,
            "waves": self.waves,
            "available_memory_bytes": self.available_memory_bytes,
            "final_report_reserved": self.final_report_reserved,
        }


__all__ = ["BuildAllowance"]
