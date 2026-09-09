"""A scheduled task's card says how its last run went (2026-09-05).

The scheduler has kept a bounded run history per task all along and the
route returned it; the Settings card showed the cron, the status and the next
time only, so a task that failed every night looked exactly like one that
worked.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JS = ROOT / "thomas" / "server" / "web" / "js"
DRIVER = ROOT / "tests" / "web_node" / "schedule_last_run.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_last_run_line_reports_ok_failed_or_never() -> None:
    out = subprocess.run(
        ["node", str(DRIVER), str(JS / "settings_parity.js")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert out.returncode == 0, out.stderr
    report = json.loads(out.stdout.strip().splitlines()[-1])
    assert report["never"] == "Never run yet"
    assert report["ok"] == "Last run: ok in 26 s at 2026-09-05 05:34 UTC"
    assert report["failed"] == "Last run: failed in 3 s at 2026-09-05 05:34 UTC: scheduled task timed out after 900s: see run.log"
    assert report["paused_with_error"] == "Never run yet · Invalid cron (paused): bad field"


def test_the_card_row_shows_the_line() -> None:
    source = (JS / "settings_parity.js").read_text(encoding="utf-8")
    assert "lastRunLine(t)" in source
