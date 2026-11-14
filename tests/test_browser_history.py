"""History opens and reuses its page."""

import pathlib
import shutil
import subprocess

import pytest


def test_history_opens_and_reuses_its_page() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for the tab interaction check")
    root = pathlib.Path(__file__).resolve().parents[1]
    subprocess.run(
        [
            node,
            str(root / "tests/web_node/browser_history.mjs"),
            str(root / "thomas/server/web/js/browser_shell_web.js"),
            str(root / "thomas/server/web/js/browser_shell.js"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
