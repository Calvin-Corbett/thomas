"""The mic button used to swallow every speech error and sit on "Listening" forever.

A blocked microphone (`not-allowed`), an unreachable speech service (`network`) and a missing device
(`audio-capture`) all ended with recognition restarting in a loop and no message. The fake recognition in
``tests/web_node/chat_mic_errors.mjs`` fires each of them and checks the words shown, that listening stops for good,
that the 5 second silence stop is kept, and that the silence clock starts when the microphone opens.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB = REPO_ROOT / "thomas" / "server" / "web"
PANELS_JS = WEB / "js" / "chat_composer_panels.js"
HARNESS = REPO_ROOT / "tests" / "web_node" / "chat_mic_errors.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_every_speech_error_is_said_in_plain_words_and_never_loops() -> None:
    result = subprocess.run(
        ["node", str(HARNESS), str(PANELS_JS)], capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stderr or result.stdout
    checks = json.loads(result.stdout.strip().splitlines()[-1])
    assert all(checks.values())
    assert "not-allowed says why" in checks and "no-speech is quiet" in checks


def test_the_embedded_tabs_need_no_microphone_allowance() -> None:
    """Build, Chat and Work tabs are same-origin frames: Chrome's default microphone allowlist is `self`, which a
    same-origin frame inherits, so no `allow="microphone"` is needed -- as long as nothing narrows it. A
    Permissions-Policy header or a sandboxed frame would, so neither may appear."""
    docs = (WEB / "js" / "browser_shell_docs.js").read_text(encoding="utf-8")
    policy = (WEB / "js" / "browser_shell_docs_policy.js").read_text(encoding="utf-8")
    assert "sandbox" not in re.sub(r"//[^\n]*|/\*.*?\*/", "", docs, flags=re.S)
    assert 'DOC_URL = "/?embed=1&browser=0"' in policy  # same origin, not an absolute URL
    for path in (REPO_ROOT / "thomas" / "server").rglob("*.py"):
        assert "Permissions-Policy" not in path.read_text(encoding="utf-8", errors="replace"), path


def test_chat_html_binds_the_mic_on_its_final_markup() -> None:
    page = (WEB / "chat.html").read_text(encoding="utf-8", errors="replace")
    assert page.count('id="tc-mic-btn"') == 1
    assert re.search(r"^\s*setupMic\(\);", page, flags=re.M)
