"""The composer panels back off when the server is away (2026-09-05).

Two panels polled every 1.5 s regardless; a verify-server restart produced
3,179 refused-connection console errors. A failed poll now doubles the wait
up to thirty seconds and a good one resets it.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "thomas" / "server" / "web" / "js"
DRIVER = ROOT / "tests" / "web_node" / "panel_backoff.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_both_panels_double_the_wait_on_failure_and_reset_on_success() -> None:
    out = subprocess.run(
        ["node", str(DRIVER), str(JS / "ask_user_panel.js"), str(JS / "todo_panel.js")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    report = json.loads(out.stdout.strip().splitlines()[-1])
    expected = [1500, 3000, 6000, 12000, 24000, 30000, 30000, 1500]
    assert report["ask"] == expected
    assert report["todo"] == expected
