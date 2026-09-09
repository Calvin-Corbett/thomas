"""Verification executes untrusted generated code, so it must run sealed off.

`smoke_html_artifacts` boots a real browser on whatever Thomas just wrote. That
code has not been reviewed by anyone — it is the thing being checked. The
browser is therefore launched with external name resolution mapped away, a
throwaway profile, and a proxy pointing at a local server that only serves the
allowlisted files.

None of that was asserted anywhere. Each flag is a single string in a long argv
list, easy to drop while tidying, and losing one would not fail a test or change
a result — it would just quietly let generated code reach the network during
the very step that exists to inspect it.
"""

from __future__ import annotations

import re
from pathlib import Path

SMOKE = Path(__file__).resolve().parents[1] / "thomas" / "forge" / "anvil" / "web_artifact_smoke.py"


def _command_block() -> str:
    text = SMOKE.read_text(encoding="utf-8")
    return text.split("command = [", 1)[1].split("]", 1)[0]


def test_external_name_resolution_is_mapped_away() -> None:
    """The one flag that stops generated code reaching the internet."""
    assert '"--host-resolver-rules=MAP * 0.0.0.0, EXCLUDE 127.0.0.1"' in _command_block()


def test_traffic_is_forced_through_the_local_allowlisted_server() -> None:
    block = _command_block()

    assert "--proxy-server=http://127.0.0.1:" in block
    assert "--proxy-bypass-list=<-loopback>" in block


def test_it_runs_headless_in_a_throwaway_profile() -> None:
    """A shared profile would carry the owner's real cookies and sessions into
    a page Thomas generated."""
    block = _command_block()

    assert '"--headless=new"' in block
    assert "--user-data-dir={profile}" in block


def test_the_profile_is_a_temporary_directory() -> None:
    text = SMOKE.read_text(encoding="utf-8")

    assert 'tempfile.TemporaryDirectory(prefix="thomas-web-smoke-")' in text


def test_the_run_is_bounded() -> None:
    """Generated code may loop forever; verification may not."""
    text = SMOKE.read_text(encoding="utf-8")

    assert "--virtual-time-budget=" in text
    assert re.search(r"timeout=max\(5,\s*int\(timeout\)\)", text), "the subprocess must have a wall-clock timeout"


def test_the_page_is_parsed_not_executed_in_thomas_own_process() -> None:
    """Everything above only matters because the code runs in a browser rather
    than in Thomas. Nothing here may eval or exec generated source."""
    text = SMOKE.read_text(encoding="utf-8")

    assert "eval(" not in text
    assert "exec(" not in text
