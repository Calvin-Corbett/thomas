"""Close a planner-selected pytest repair when its named test passes without a fix."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from thomas.server import green_checkout, self_project_queue
from thomas.server.proof import environment

_TEST_REQUEST = re.compile(
    r"^Fix failing test (tests/[\w./-]+\.py::test[\w-]+)"
    r"(?:\. Reproduce the failure and keep the regression test passing|; rerun it to verify the fix)\.$"
)


def passing_test(catalog: Path, cid: str, execution_id: str) -> str:
    """Return the exact selected node only when its current green run passes."""
    row = next(
        (
            row
            for row in self_project_queue.read(catalog)["started"]
            if row.get("conversation_id") == cid
            and row.get("execution_id") == execution_id
            and row.get("origin") == "pytest"
        ),
        None,
    )
    if row is None:
        return ""
    match = _TEST_REQUEST.fullmatch(str(row.get("request") or ""))
    if match is None:
        return ""
    node = match.group(1)
    green = green_checkout.find_green(execution_id)
    if green is None:
        return ""
    # A note is not a fix; any source or test change must take the normal check-and-card path.
    try:
        paths = green_checkout.changed_paths(green)
    except (OSError, RuntimeError):
        return ""
    if not paths or any(not (path.startswith("changelog.d/") and path.endswith(".md")) for path in paths):
        return ""
    python = environment.interpreter(green.blue)
    if not python:
        return ""
    try:
        with tempfile.TemporaryDirectory(prefix="thomas-passing-test-") as scratch:
            result = subprocess.run(
                [python, "-m", "pytest", "-q", "-p", "no:cacheprovider", node],
                cwd=green.work,
                env=environment.sandbox_env(green.work, Path(scratch)),
                capture_output=True,
                timeout=120,
                check=False,
            )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return node if result.returncode == 0 else ""


def remember(catalog: Path, cid: str, node: str) -> None:
    """Keep this exact passing node out of future planner scans, even after queue history rolls over."""

    def update(data: dict[str, Any]) -> None:
        if not any(row.get("conversation_id") == cid and row.get("origin") == "pytest" for row in data["started"]):
            return
        ignored = data["planner"].setdefault("already_passing_tests", [])
        if node not in ignored:
            ignored.append(node)

    self_project_queue.change(catalog, update)
