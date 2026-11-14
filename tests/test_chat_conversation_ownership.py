"""Run the actual chat shell functions against delayed network and DOM state."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_chat_turns_keep_conversation_and_attachment_ownership() -> None:
    result = subprocess.run(
        [
            "node",
            str(ROOT / "tests/web_node/chat_conversation_ownership.mjs"),
            str(ROOT / "thomas/server/web/chat.html"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    proof = json.loads(result.stdout)
    assert proof["passed"] >= 13
