"""Exercise the live Build and Chat scripts against browser conditions.

Delayed and rejected responses for the preview and edit paths, and the frame
fan-out that both surfaces sit inside — each harness loads the shipped file and
runs it, so a fix that only edits a comment cannot pass.
"""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("harness", "source"),
    [
        ("build_preview_race.mjs", "thomas/server/web/js/unified_code_results.js"),
        ("chat_edit_resend_failure.mjs", "thomas/server/web/chat.html"),
        ("shell_frame_relay.mjs", "thomas/server/web/js/workspace_shell.js"),
    ],
)
def test_preview_and_edit_response_order(harness: str, source: str) -> None:
    result = subprocess.run(
        ["node", str(ROOT / "tests/web_node" / harness), str(ROOT / source)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "passed" in result.stdout or "preserve the transcript" in result.stdout
