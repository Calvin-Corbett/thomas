"""Build's home: what Thomas noticed reads in full, opens in place, repeats nothing and stays fresh (2026-11-09).

You said of that slide: "it has that yellow, orange, and red color, that basic AI square thing. I hate that ... you
can't read the full thing and click on it and see what he's really saying. And it's kind of almost the same thing. It
repeats ... I'd rather be able to click on it without having to actually open the task ... I don't feel like it updates
very well."

The slide is built in the page from the task list, so it is run here in node with a list made to trip each fault: a
long title, one task that is both in repair and the slowest, and a stopped one.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOME_JS = ROOT / "thomas" / "server" / "web" / "js" / "unified_code_home.js"
HOME_CSS = ROOT / "thomas" / "server" / "web" / "css" / "unified_code_home.css"
LONG = "Fix the really long named thing that used to be cut off at forty four characters"
SCRIPT = r"""
const fs = require('fs'), vm = require('vm');
global.window = { setInterval: null };
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
const now = Date.now() / 1000;
const task = (id, title, state, building) => ({ conversation_id: id, title, state, detail: 'detail of ' + id,
  last_verdict: 'verdict of ' + id, updated_at: now - 100, timings_seconds: { building, checks: 60 } });
const data = { perf: null, projects: [
  task('a', process.argv[2], 'repair round 3', 5000), task('b', 'Quick one', 'landed', 100),
  task('c', 'Another', 'landed', 120), task('d', 'Stopped task', 'stopped', 90), task('e', 'Slow build', 'landed', 4000)] };
const slides = window.ThomasCodeHome.slides;
const quiet = { perf: null, projects: [task('b', 'Quick one', 'landed', 100)] };
console.log(JSON.stringify({ noticed: slides.noticed(data).body, ideas: slides.ideas(data).body, quiet: slides.noticed(quiet).body }));
"""


@pytest.fixture(scope="module")
def drawn() -> dict[str, str]:
    out = subprocess.run(
        ["node", "-e", SCRIPT, str(HOME_JS), LONG],
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_a_heading_is_never_cut_short(drawn: dict[str, str]) -> None:
    assert f"<strong>&quot;{LONG}&quot; is in repair round 3</strong>" in drawn["noticed"]


def test_each_task_is_noticed_once(drawn: dict[str, str]) -> None:
    noticed = drawn["noticed"]
    assert noticed.count("<details") == 3
    assert noticed.count("<strong>&quot;Fix the really long") == 1, "in repair and the slowest, it is told once"
    assert "<strong>&quot;Slow build&quot; took" in noticed, "the slow item is the slowest of the others"
    assert "<strong>1 task stopped without finishing</strong>" in noticed


def test_an_item_opens_in_place_and_says_everything_without_opening_the_task(drawn: dict[str, str]) -> None:
    noticed = drawn["noticed"]
    assert '<details class="tc-home-card"><summary>' in noticed
    for said in (
        "<dt>Task</dt>",
        "<dt>Where it stands</dt><dd>repair round 3</dd>",
        "<dd>detail of a</dd>",
        "<dd>verdict of a</dd>",
    ):
        assert said in noticed, said
    assert noticed.count('data-home-open="') == 3 and 'data-home-open="a">Open the task</button>' in noticed
    assert noticed.count("data-home-fill=") == 3, "the request for the composer is still there, inside"


def test_where_to_go_next_does_not_offer_a_task_the_slide_before_told_you_about(drawn: dict[str, str]) -> None:
    assert "Pick up &quot;Fix the really" not in drawn["ideas"] and "Pick up &quot;Stopped task" not in drawn["ideas"]


def test_with_nothing_wrong_it_says_so_once(drawn: dict[str, str]) -> None:
    assert drawn["quiet"].count("<details") == 1 and "Nothing needs attention" in drawn["quiet"]


def test_no_colour_marks_the_kind_of_item() -> None:
    css = HOME_CSS.read_text("utf-8")
    for gone in ("--tone", ".is-warn", ".is-slow", ".is-stop", "#f5b84b", "#ff9a6b", "#ff7a7a", "border-left: 3px"):
        assert gone not in css, gone
    assert "card('warn'" not in HOME_JS.read_text("utf-8")


def test_the_numbers_are_read_again_and_an_open_item_is_left_alone() -> None:
    source = HOME_JS.read_text("utf-8")
    assert "document.querySelectorAll('[data-code-home][data-home-ready]').forEach(root => hydrate(root));" in source
    assert "}, FRESH_MS + 5000);" in source
    assert "window.ThomasDocActivity.isPaused()) return;" in source, "only the tab on screen asks"
    assert "slide.dataset.homeDrawn === markup || slide.querySelector('details[open]')" in source
    assert "!root.querySelector('details[open]')" in source, "the slides do not turn while you are reading one"
