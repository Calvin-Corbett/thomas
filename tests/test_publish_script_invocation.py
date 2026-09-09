"""Regression: publish scripts must run under their documented invocation.

The publish preflight gate (CI: .github/workflows/github-publish-safety.yml,
pre-push hook via scripts/_gate_python.py) invokes these files as plain
scripts — `python scripts/forge/publish/preflight.py` — from the repo root.
A repo-absolute import (`from scripts.forge.publish...`) without a sys.path
bootstrap crashed that invocation with ModuleNotFoundError from 2026-06-28
until 2026-07-15, failing the entire publish lane closed. These tests run the
scripts exactly as CI does so the crash class cannot return unnoticed.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

SCRIPTS = [
    "scripts/forge/publish/preflight.py",
    "scripts/forge/publish/snapshot.py",
]


@pytest.mark.parametrize("script", SCRIPTS)
def test_publish_script_direct_invocation_imports(script: str) -> None:
    """`python <script> --help` must exit 0 (imports resolve, argparse loads)."""
    proc = subprocess.run(
        [sys.executable, script, "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"{script} failed under its documented direct invocation.\n"
        f"stdout: {proc.stdout[-2000:]}\nstderr: {proc.stderr[-2000:]}"
    )


@pytest.mark.parametrize(
    "module",
    [
        "scripts.forge.publish.preflight",
        "scripts.forge.publish.snapshot",
    ],
)
def test_publish_script_module_invocation_imports(module: str) -> None:
    """`python -m <module> --help` must also exit 0."""
    proc = subprocess.run(
        [sys.executable, "-m", module, "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"{module} failed under -m invocation.\nstdout: {proc.stdout[-2000:]}\nstderr: {proc.stderr[-2000:]}"
    )
