"""An explicitly-requested table must come back as a table, not pipe soup.

Measured (2026-08-05, live): the user asked for a budget table, the model wrote
correct GFM table markdown, and chat.html's ``mdToHtml`` — which knows headings,
lists, fences and rules but not tables — fell through to the paragraph branch.
The DOM held 0 ``<table>`` elements; every row rendered as its own ``<p>`` of
literal ``| Category | Monthly |`` text. The model's work was right every time;
the renderer dropped it on the floor.

The contract, driven through the same VM-extraction harness the existing
markdown test uses (tests/web_node/chat_markdown_tables.mjs):

* header row + delimiter row + body rows -> one real ``<table>`` with ``<th>``
  and ``<td>`` cells carrying the right text,
* alignment colons in the delimiter row become ``text-align`` on the cells,
* ``\\|`` inside a cell stays a literal pipe,
* a pipe line with NO delimiter row underneath keeps today's raw-text fallback
  (paragraph per line) — a malformed table is shown, never half-parsed,
* ragged body rows normalize to the header's width, GFM-style.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CHAT_HTML = REPO_ROOT / "thomas" / "server" / "web" / "chat.html"
HARNESS = REPO_ROOT / "tests" / "web_node" / "chat_markdown_tables.mjs"


def test_a_gfm_table_renders_as_a_real_table() -> None:
    result = subprocess.run(
        ["node", str(HARNESS), str(CHAT_HTML)],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    checks = json.loads(result.stdout)
    assert checks and all(checks.values()), checks
