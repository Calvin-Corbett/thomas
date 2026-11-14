"""Requested tab boots remain independent of slow model catalogs and other tabs."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_actual_chat_boot_with_delayed_models_and_user_interactions():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required to execute the shipped Chat boot module")
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            node,
            str(repo / "tests/web_node/chat_boot.mjs"),
            str(repo / "thomas/server/web/js/chat_boot.js"),
            str(repo / "thomas/server/web/chat.html"),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    proof = json.loads(result.stdout)
    assert proof["passed"] >= 24
