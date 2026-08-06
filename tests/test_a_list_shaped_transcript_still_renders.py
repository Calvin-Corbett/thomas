"""A list-shaped transcript already on disk renders like the string it was.

Measured (w2-code-explain sweep, 2026-08-06): a persisted turn carried its
transcript as 2541 single-character array entries instead of one string. The
transcript renderer (``unified_code_events.js``) ran that array through
``String(...)``, which comma-joins it -- ``'{,",f,c,...'`` -- so nothing
parsed as a forge event and the agent's produced answer never reached the
screen. The store's writer now persists ONE string, but records written before
that fix exist, so the read path must keep rendering both shapes.

Driven through ``tests/web_node/code_list_shaped_transcript_renders.mjs``:
the SAME turn rendered with its transcript as the true string, as a
character array, and as a line array must produce identical HTML -- and that
HTML must carry the final answer.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EVENTS_JS = REPO_ROOT / "thomas" / "server" / "web" / "js" / "unified_code_events.js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "code_list_shaped_transcript_renders.mjs"


def _drive() -> dict[str, str]:
    result = subprocess.run(
        ["node", str(HARNESS), str(EVENTS_JS)],
        capture_output=True,
        check=False,
        text=True,
        # Node writes UTF-8; without this, Windows decodes the report as
        # cp1252 and any em dash in the wording arrives mangled.
        encoding="utf-8",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_a_character_array_transcript_renders_exactly_like_the_string() -> None:
    report = _drive()
    assert "THE-ANSWER: this project is empty." in report["asString"]
    assert report["asCharArray"] == report["asString"]


def test_a_line_array_transcript_renders_exactly_like_the_string() -> None:
    report = _drive()
    assert report["asLineArray"] == report["asString"]
