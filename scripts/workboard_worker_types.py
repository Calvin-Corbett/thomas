"""Shared datatypes for the persistent workboard worker."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AssignedTask:
    line_no: int
    task_id: str
    scope: str
    summary: str


@dataclass(frozen=True)
class CommandRun:
    command: str
    returncode: int
    elapsed_seconds: float
    timed_out: bool
    stdout: str
    stderr: str


class _SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:  # pragma: no cover - defensive
        return "{" + key + "}"
