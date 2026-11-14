"""Build selection and reconnect stay responsive and retain their owner."""

import json
import subprocess
from pathlib import Path


def test_build_selection_does_not_wait_for_files_or_adopt_stale_status():
    root = Path(__file__).resolve().parents[1]
    web = root / "thomas/server/web/js"
    result = subprocess.run(
        [
            "node",
            str(root / "tests/web_node/build_navigation_readiness.mjs"),
            str(web / "unified_code_projects.js"),
            str(web / "unified_code_lifecycle.js"),
            str(web / "unified_code_mode.js"),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert all(json.loads(result.stdout).values())
