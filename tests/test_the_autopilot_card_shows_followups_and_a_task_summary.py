"""The autopilot card: what it is doing now, how each follow-up ended, and a summary once nothing is running."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web"

SCRIPT = """
const fs = require('fs');
globalThis.window = globalThis;
eval(fs.readFileSync(process.argv[1], 'utf8'));
const esc = t => String(t).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
const history = { count: 2, runs: [
  { run: 1, ts: '2026-11-06T18:04:00', outcome: 'completed', reason: 'done check found two failing tests' },
  { run: 2, ts: '2026-11-06T18:21:00', outcome: 'usage_limit_reached', reason: 'waiting <b>for</b> reset' }] };
const totals = { added: 412, removed: 97, files: 9 };
const html = window.ThomasCodeContinuation.html;
console.log(JSON.stringify({
  running: html({ history, running: true, live: true, totals }, esc),
  done: html({ history, running: false, live: false, totals }, esc),
  first: html({ history: { count: 0, runs: [] }, running: true, live: true, totals: null }, esc),
  none: html({ history: { count: 0, runs: [] }, running: false, live: false, totals }, esc),
  manual: html({ history, running: true, live: false, totals }, esc),
}));
"""


def rendered() -> dict[str, str]:
    done = subprocess.run(
        ["node", "-e", SCRIPT, str(WEB / "js" / "unified_code_continuation.js")],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(done.stdout)


def test_while_autopilot_works_the_card_says_what_it_is_doing():
    out = rendered()["running"]
    assert "Autopilot is working on follow-up 3" in out and "tc-cont-shimmer" in out and "is-live" in out
    assert "After: waiting &lt;b&gt;for&lt;/b&gt; reset" in out  # the reason shown is escaped, never markup
    assert "tc-cont-sum" not in out  # the summary waits for the end


def test_the_first_autopilot_run_says_it_is_initializing():
    assert "Initializing autopilot fix" in rendered()["first"]


def test_when_nothing_runs_the_card_summarizes_the_whole_task():
    out = rendered()["done"]
    assert "Kept going on its own, 2 times" in out
    assert "<b>2</b> follow-ups" in out and "<b>9</b> files changed" in out and "+412" in out and "−97" in out
    assert "Usage limit reached" in out and "is-bad" in out and "is-ok" in out  # each run says how it ended


def test_no_follow_ups_and_no_live_autopilot_means_no_card():
    out = rendered()
    assert out["none"] == ""
    assert (
        out["manual"].count("Initializing") == 0 and "is-live" not in out["manual"]
    )  # a run you started is not autopilot's


def test_the_surface_uses_the_card_and_the_total_is_always_in_the_bar():
    surface = (WEB / "js" / "unified_code_surface.js").read_text(encoding="utf-8")
    header = (WEB / "js" / "unified_code_header.js").read_text(encoding="utf-8")
    html = (WEB / "chat.html").read_text(encoding="utf-8")
    assert "ThomasCodeContinuation.html" in surface and "Self-continuations that ran" not in surface
    assert "if (!added && !removed) return ''" not in header and "fileCount" in header
    assert html.index("unified_code_continuation.js") < html.index("unified_code_home.js")
    assert "unified_code_continuation.css" in html
