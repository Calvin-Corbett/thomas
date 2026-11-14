"""A Build update folds a long block of code, and a reconnect is not titled as a failure (2026-11-09).

Found by watching the live app, not by reading it. An update that pasted a diff put a hundred lines of code in the
transcript and the sentences around it scrolled away; opening a task that had kept running in the background drew a
row titled ``disconnected`` over the words "Reattached"; and the words Thomas uses for his own parts ("Build lead",
"Praxis child") were printed to you after a restart. You asked for those to be fixed: "I like all those critiques.
Work on those first."

The page side is drawn through ``unified_code_events.js`` in node, the way ``test_every_step_shows_while_it_runs``
does it. The wording is read from the files that say it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
JS = REPO_ROOT / "thomas" / "server" / "web" / "js"


@pytest.fixture(scope="module")
def drawn() -> dict[str, str]:
    out = subprocess.run(
        ["node", str(REPO_ROOT / "tests" / "web_node" / "build_updates_fold_code_and_name_reconnects.mjs"),
         str(JS / "unified_code_events.js")],
        capture_output=True, check=False, text=True, encoding="utf-8", timeout=30,
    )  # fmt: skip
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_a_long_block_of_code_folds_behind_a_line_that_says_how_long_it_is(drawn: dict[str, str]) -> None:
    html = drawn["long"]
    assert "Show 30 lines of code</summary>" in html
    folded = html.split("Show 30 lines of code</summary>", 1)[1].split("</details>", 1)[0]
    assert "LONGLINE 0" in folded and "LONGLINE 29" in folded, "every line is still there behind the fold"
    before = html.split("<details", 1)[0]
    assert "BEFORE-MARKER" in before and "LONGLINE" not in before, "the sentence before it stays in the open"
    assert "AFTER-MARKER" in html.split("</details>", 1)[1], "and so does the sentence after it"


def test_a_short_block_and_an_unclosed_fence_are_left_as_they_were(drawn: dict[str, str]) -> None:
    assert "SHORTLINE 2" in drawn["short"] and "lines of code" not in drawn["short"]
    assert "UNCLOSED" in drawn["unclosed"] and "lines of code" not in drawn["unclosed"]


def test_coming_back_to_a_running_task_reads_reconnected(drawn: dict[str, str]) -> None:
    html = drawn["reconnected"]
    assert "<strong>Reconnected</strong>" in html
    assert "disconnected" not in html.lower()


def test_a_real_drop_reads_connection_lost(drawn: dict[str, str]) -> None:
    assert "<strong>Connection lost</strong>" in drawn["dropped"]
    assert "<strong>disconnected</strong>" not in drawn["dropped"]


def test_a_reconnect_is_sent_as_its_own_kind_and_the_page_treats_it_as_narrative() -> None:
    projects = (JS / "unified_code_projects.js").read_text("utf-8")
    assert projects.count("type: 'reconnected'") == 2, "both returns: a parked task, and a reload"
    assert "Reattached" not in projects
    mode = (JS / "unified_code_mode.js").read_text("utf-8")
    kinds = mode.split("const NARRATIVE_EVENT_KINDS = new Set(", 1)[1].split(");", 1)[0]
    assert "'reconnected'" in kinds, "a kind outside this set is drawn as a tool row, not a sentence"


@pytest.mark.parametrize("words", ["Build lead", "Praxis child", "Recovered child", "remains locked as running"])
def test_thomas_does_not_print_the_names_of_his_own_parts(words: str) -> None:
    for name in ("unified_code_projects.js", "unified_code_run_stream.js"):
        text = (JS / name).read_text("utf-8")
        # Only what reaches the screen is held to this: a string literal, not a comment that explains the code.
        shown = "\n".join(line for line in text.splitlines() if not line.strip().startswith(("//", "*", "/*")))
        assert words not in shown, f"{name} still says {words!r} to the person watching"
