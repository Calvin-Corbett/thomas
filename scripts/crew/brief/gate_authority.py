"""Which local gates have the authority to refuse a commit.

Authority requires review. A gate whose script git does not track is one
nobody has committed, and on 2026-09-02 exactly such a gate - wired into an
uncommitted commit.py - refused every agent in this repo for twelve hours, its
own author included, with no trace but commits stopping.

So `reviewed_gates` drops gates whose script is untracked, and `skipped_note`
names them on the commit that skipped them. They are not hidden: the
`UNVERSIONED TOOLING` line of scripts/forge/fleet_stall.py prints the same set
on every session start. Commit the gate and it takes effect again immediately;
nothing about a tracked gate changes.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

GateCommand = tuple[str, Sequence[str]]


def gate_script(command: Sequence[str]) -> str:
    """The gate's own script path, if the command runs one."""
    for token in command:
        text = str(token)
        if text.endswith(".py") and text != str(sys.executable):
            return text.replace("\\", "/")
    return ""


def is_untracked(repo_root: Path, path: str) -> bool:
    """True when git tracks nothing at `path`.

    Encoding is explicit: capturing git output as platform text broke a gate on
    Windows over a single 0x9d byte, and the failure surfaced as a file
    appearing absent from the index.
    """
    if not path:
        return False
    proc = subprocess.run(
        ("git", "ls-files", "--", path),
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return proc.returncode == 0 and not proc.stdout.strip()


def reviewed_gates(
    repo_root: Path,
    commands: Sequence[GateCommand],
) -> tuple[list[GateCommand], list[str]]:
    """Split gates into those allowed to run and the names of those skipped."""
    kept: list[GateCommand] = []
    skipped: list[str] = []
    for gate_name, command in commands:
        script = gate_script(command)
        if is_untracked(repo_root, script):
            skipped.append(f"{gate_name} ({script})")
            continue
        kept.append((gate_name, command))
    return kept, skipped


def skipped_note(skipped: Sequence[str]) -> str:
    if not skipped:
        return ""
    return "skipped unreviewed gate(s), commit them to restore: " + ", ".join(skipped)
