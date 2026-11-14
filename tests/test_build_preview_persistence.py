"""Exercise the shipped Build renderer in an isolated, hidden Electron window."""

import json
import os
import subprocess
from pathlib import Path

import pytest


def test_build_preview_and_reader_state_survive_event_cap_redraws(tmp_path):
    repo = Path(__file__).resolve().parents[1]
    html = (repo / "thomas/server/web/chat.html").read_text(encoding="utf-8")
    assert html.index("/static/js/unified_code_view_state.js") < html.index("/static/js/unified_code_mode.js")
    electron = repo / "desktop/node_modules/electron/dist/electron.exe"
    if not electron.exists():
        pytest.skip("Install the desktop dependencies for the Electron renderer check")
    env = os.environ.copy()
    env.pop("ELECTRON_RUN_AS_NODE", None)
    result = subprocess.run(
        [str(electron), str(repo / "tests/web_node/build_preview_persistence.mjs"), str(repo), str(tmp_path)],
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
    assert all(proof.values()), proof
    (tmp_path / "proof.json").write_text(json.dumps(proof, indent=2), encoding="utf-8")
