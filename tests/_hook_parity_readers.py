"""Readers shared by the hook-parity tests.

Two test files check that every commit-stage hook in .pre-commit-config.yaml is
accounted for on the scoped commit path, and both must judge the same parse, so the
readers live here once. The leading underscore keeps pytest from collecting it.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".pre-commit-config.yaml"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.crew.brief import commit as commit_tool  # noqa: E402

# python scripts/_gate_python.py <real gate> ... -- the first .py in an entry is the
# launcher, never the gate.
LAUNCHERS = {"scripts/_gate_python.py"}


def _hook_blocks() -> dict[str, dict[str, str]]:
    """hook id -> {stages, entry}, parsed a block at a time.

    Block-based on purpose: ``stages:`` may appear either side of ``entry:``, and
    a reader that only accepts it beforehand silently files the four pre-push
    hooks as commit-stage. That mistake makes this test report four false
    divergences, and a guard that cries wolf gets deleted.
    """
    blocks: dict[str, dict[str, str]] = {}
    current = ""
    for line in CONFIG.read_text(encoding="utf-8").splitlines():
        started = re.match(r"\s*-\s*id:\s*(\S+)", line)
        if started:
            current = started.group(1)
            blocks[current] = {"stages": "", "entry": ""}
            continue
        if not current:
            continue
        stages = re.search(r"stages:\s*\[([^\]]*)\]", line)
        if stages:
            blocks[current]["stages"] = stages.group(1)
        entry = re.match(r"\s*entry:\s*(.+)$", line)
        if entry:
            blocks[current]["entry"] = entry.group(1).strip()
    return blocks


def _gate_script(entry: str) -> str:
    """The repo script an entry runs, skipping the launcher. Empty if external."""
    candidates = [
        token.strip("\"'").replace("\\", "/")
        for token in entry.split()
        if token.strip("\"'").replace("\\", "/").endswith(".py")
    ]
    for candidate in candidates:
        if candidate not in LAUNCHERS:
            return candidate
    return ""


def _commit_stage_hooks() -> dict[str, dict[str, str]]:
    return {hook_id: block for hook_id, block in _hook_blocks().items() if "push" not in block["stages"]}


def _scoped_path_coverage() -> tuple[set[str], set[str]]:
    """(gate scripts, gate names) the scoped commit path actually runs."""
    scripts: set[str] = set()
    names: set[str] = set()
    for gate_name, command in commit_tool.LOCAL_GATE_COMMANDS:
        names.add(gate_name)
        for token in command:
            normalized = str(token).replace("\\", "/")
            if normalized.endswith(".py"):
                scripts.add(normalized)
    return scripts, names


def _merge_readiness_scripts() -> set[str]:
    """Scripts the merge-readiness check actually runs.

    Loaded under a private module name on purpose. Two test files in this suite
    both register commit.py as sys.modules["agent_commit"] and swap each other's
    module out from under monkeypatch, so a test here must not share a name.
    """
    path = ROOT / "scripts" / "forge" / "gates" / "merge_readiness.py"
    spec = importlib.util.spec_from_file_location("_parity_test_merge_readiness", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    found: set[str] = set()
    for _name, command in module.MERGE_GATE_COMMANDS:
        for token in command:
            normalized = str(token).replace(chr(92), "/")
            if normalized.endswith(".py"):
                found.add(normalized)
    return found
