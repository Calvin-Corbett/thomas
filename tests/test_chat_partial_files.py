"""Exercise the shipped Chat factories with failed and cancelled output."""

import subprocess
from pathlib import Path


def test_partial_files_stay_unverified_through_stream_poll_and_restore():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            "node",
            str(root / "tests/web_node/chat_partial_artifacts.mjs"),
            str(root / "thomas/server/web/chat.html"),
            str(root / "thomas/server/web/js/chat_turn_flow.js"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
