"""Build's home shows its tasks without waiting for the usage reading (2026-11-09).

You said of the Build home: "it takes a long time to load". The page asked for the task list and for a week of usage
together and drew nothing until both had answered, so the slower reading held back every slide. They are asked for
apart now: the task slides fill when the task list answers, and the usage slide says it is still reading until its own
answer arrives.

The page script is run here in node. The usage answer is held back until the test lets it go.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

HOME = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "js" / "unified_code_home.js"
SCRIPT = r"""
const fs = require('fs'), vm = require('vm');
let release; const held = new Promise(resolve => { release = resolve; });
const asked = [];
global.window = { setInterval: () => 0 };
global.fetch = async url => {
  asked.push(url);
  if (url.includes('performance')) { await held;
    return { ok: true, json: async () => ({ ok: true, runs: 2, tokens_per_second: 5,
      days: [{ date: '2026-11-09', total: 10, prompt: 6, completion: 4, runs: 2 }] }) }; }
  return { ok: true, json: async () => ({ projects: [{ title: 'A build', state: 'landed',
    updated_at: '2026-11-09T10:00:00', timings_seconds: { building: 60 } }] }) };
};
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
(async () => {
  const home = window.ThomasCodeHome;
  const first = await home.load();
  const out = { tasks_first: first.projects.length, usage_waiting: first.perfPending, usage_first: first.perf,
    waiting_words: home.slides.tokens(first).body };
  release(); await new Promise(resolve => setTimeout(resolve, 30));
  const later = await home.load();
  out.usage_later = later.perf && later.perf.runs; out.still_waiting = later.perfPending;
  out.asked = asked;
  console.log(JSON.stringify(out));
})();
"""


@pytest.fixture(scope="module")
def seen() -> dict:
    out = subprocess.run(
        ["node", "-e", SCRIPT, str(HOME)], capture_output=True, check=False, text=True, encoding="utf-8", timeout=60
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


def test_the_tasks_are_ready_while_usage_is_still_being_read(seen: dict) -> None:
    assert seen["tasks_first"] == 1 and seen["usage_waiting"] is True and seen["usage_first"] is None


def test_the_usage_slide_says_it_is_reading_and_not_that_it_failed(seen: dict) -> None:
    assert "Reading usage" in seen["waiting_words"] and "could not be read" not in seen["waiting_words"]


def test_usage_fills_in_when_its_answer_arrives_without_being_asked_twice(seen: dict) -> None:
    assert seen["usage_later"] == 2 and seen["still_waiting"] is False
    assert len([url for url in seen["asked"] if "performance" in url]) == 1, "one reading, not one per look"


def test_the_two_answers_are_not_waited_for_together() -> None:
    assert "Promise.all" not in HOME.read_text("utf-8")
