from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_workboard_claim_list_smoke() -> None:
    proc = subprocess.run(
        [sys.executable, "scripts/crew/workboard/claim.py", "--list"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    assert "Workboard claim tool: PASS" in (proc.stdout or "")
