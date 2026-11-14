"""Build role choices follow real composer, tab, boot and queue ownership."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_saved_build_roles_reach_the_composer_and_stay_owned():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for the shipped Build role routing check")
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, str(repo / "tests/web_node/build_role_routing.mjs"), str(repo / "thomas/server/web")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["passed"] == 6
