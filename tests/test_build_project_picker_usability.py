"""Exercise the project form through the shipped shell, Build adapter and request."""

import json
import os
import subprocess
from pathlib import Path

import pytest


def test_build_new_project_is_named_and_waits_for_creation(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    electron = repo / "desktop/node_modules/electron/dist/electron.exe"
    if not electron.exists():
        pytest.skip("Install desktop dependencies for the Electron renderer check")
    env = os.environ.copy()
    env.pop("ELECTRON_RUN_AS_NODE", None)
    result = subprocess.run(
        [str(electron), str(repo / "tests/web_node/build_project_picker_usability.mjs"), str(repo), str(tmp_path)],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=45,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    receipt = next(line for line in result.stdout.splitlines() if line.startswith("PROOF:"))
    proof = json.loads(receipt.removeprefix("PROOF:"))
    assert len(proof) >= 16 and all(proof.values()), proof
