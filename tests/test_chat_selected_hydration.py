"""The selected Chat transcript keeps ownership while its saved copy is fetched."""

import json
import subprocess
from pathlib import Path


def test_selected_chat_hydration_preserves_newer_turns():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["node", str(root / "tests/web_node/chat_selected_hydration.mjs"), str(root / "thomas/server/web/chat.html")],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["passed"] == 7
