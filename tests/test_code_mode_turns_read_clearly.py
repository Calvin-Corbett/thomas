"""Saved Code turns distinguish your words from Autopilot's and lead with the reply."""

import json
import re
import subprocess
from html import unescape
from pathlib import Path

from thomas.server import thomas_project
from thomas.server.routes import autopilot_goal, autopilot_messages

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "thomas/server/web/css"
EVENTS = ROOT / "thomas/server/web/js/unified_code_events.js"
DRIVER = r"""
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
globalThis.window = {};
// The head, rows and cards a turn is drawn from load ahead of the event cluster.
const cards = path.join(path.dirname(process.argv[1]), 'unified_code_cards.js');
vm.runInThisContext(fs.readFileSync(cards, 'utf8'), { filename: cards });
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'), { filename: process.argv[1] });
const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const api = window.ThomasCodeEvents.create({
  MAX_VISIBLE_PROGRESS_EVENTS: 120, MAX_PROGRESS_EVENT_CHARS: 420,
  NARRATIVE_EVENT_KINDS: new Set(['planning','say','final','insight','steering']),
  state: { running: false, runStartedAt: 0 }, esc,
  codeResults: () => ({ runReportHtml: () => '<div class="run-report">REPORT</div>',
    artifactCardsHtml: () => '<div class="result-cards">CARDS</div>' }),
  surface: () => null, isInternalResultPath: () => false,
  safely: async fn => fn(), pushLiveEvent: () => {}, render: () => {}, send: () => {}
});
console.log(JSON.stringify(JSON.parse(process.argv[2]).map(turn => api.turnHtml(turn))));
"""


def render(*turns):
    result = subprocess.run(
        ["node", "-e", DRIVER, str(EVENTS), json.dumps(turns)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def user(text):
    return {"role": "user", "text": text}


def assert_note(html, text, title):
    assert 'class="tc-code-turn is-user"' not in html
    assert 'class="tc-code-autopilot-note"' in html
    assert f"<summary>{title}</summary>" not in html  # title must remain visible while closed
    assert unescape(re.search(r'<aside class="tc-code-autopilot-note"><span>(.*?)</span>', html, re.S)[1]) == title
    assert re.search(r"<details(?![^>]*\bopen\b)[^>]*>.*<summary>.*</summary>", html, re.S)
    # The complete message is available inside, and nowhere before the disclosure.
    before, full = html.split("<details", 1)
    assert text in unescape(full.split("</summary>", 1)[1])
    assert text not in unescape(before)


def test_reply_drops_internal_labels_and_defers_check_count_to_report():
    reply = (
        "TITLE: Fix the build\nDONE: The page opens.\nNEXT: Try it.\n"
        "Verification: 2/2 checks passed\nUnchecked (no evidence either way): The preview."
    )
    html = render(
        {
            "role": "agent",
            "ok": True,
            "transcript": json.dumps({"fc": "final", "text": reply}),
            "report": {"validations": []},
        }
    )[0]
    for label in ("TITLE:", "DONE:", "NEXT:", "Verification:", "Unchecked (no evidence either way):"):
        assert label not in html
    assert "The page opens." in html
    assert "Try it." in html
    assert "The preview." not in html
    assert "2/2 checks passed" not in html


def test_missing_reply_leaves_check_status_to_the_report():
    html = render(
        {
            "role": "agent",
            "ok": True,
            "transcript": "",
            "report": {"validations": [{"ok": False, "name": "Browser check"}]},
        }
    )[0]
    assert "Finished the requested changes." in html
    assert "passed Thomas’s verification" not in html
    assert "REPORT" in html
    waiting = render({"role": "agent", "ok": True, "transcript": "", "report": {"validations": []}})[0]
    assert "passed Thomas’s verification" not in waiting


def test_reply_does_not_repeat_unchecked_items_when_report_has_their_result():
    html = render(
        {
            "role": "agent",
            "ok": True,
            "transcript": json.dumps(
                {
                    "fc": "final",
                    "text": "DONE: Built it.\nUnchecked (no evidence either way):\n"
                    "- First, open the build.\n- Second, check the card.\n",
                }
            ),
            "report": {"validations": [], "rubric_mapping": [{"status": "not_checked"}]},
        }
    )[0]
    assert "Built it." in html
    assert "Unchecked (no evidence either way):" not in html
    assert "First, open the build." not in html
    assert "Second, check the card." not in html


def test_report_card_is_only_source_of_failed_check_and_missing_evidence_status():
    reply = (
        "DONE: I checked the guard.\n\nTITLE: Build clarity\n\n"
        "Verification: 2/2 checks passed.\n"
        "Unchecked (no evidence either way):\n"
        "- First, opening a saved build.\n"
        "- Second, the check card.\n"
        "- Third, plain language.\n\n"
        "The change is ready."
    )
    html = render(
        {
            "role": "agent",
            "ok": True,
            "transcript": json.dumps({"fc": "final", "text": reply}),
            "report": {
                "validations": [
                    {"kind": "engine_check", "passed": True},
                    {"kind": "engine_check", "passed": False},
                ]
            },
        }
    )[0]
    answer = unescape(html.split('class="tc-code-reply-text"', 1)[1].split("</div>", 1)[0])
    assert "I checked the guard." in answer
    assert "The change is ready." in answer
    for phrase in ("TITLE:", "DONE:", "Verification:", "2/2", "Unchecked", "First,", "Second,", "Third,"):
        assert phrase not in answer
    assert '<div class="result-cards">CARDS</div>' in html


def test_reply_without_report_keeps_check_result_but_not_internal_label():
    html = render(
        {
            "role": "agent",
            "ok": True,
            "transcript": json.dumps({"fc": "final", "text": "Verification: 2/2 checks passed"}),
        }
    )[0]
    assert "2/2 checks passed" in html
    assert "Verification:" not in html


def test_thomas_is_named_and_your_bubble_keeps_its_class():
    # Build redesign (2026-10, design 3a/4a): your message is one bright bubble
    # with no "You" heading over it -- whose words they are is plain from the
    # bubble. Thomas's turn keeps his name beside the build face.
    mine, thomas = render(user("Please build it"), {"role": "agent", "ok": True, "text": "Done"})
    assert 'class="tc-code-turn is-user"' in mine
    assert "Please build it" in mine
    assert "<strong>You</strong>" not in mine
    assert "<strong>Thomas</strong>" in thomas


def test_last_user_margin_rule_in_loaded_stylesheets_aligns_right():
    # Your bubble sits at the RIGHT edge of the reading column, Thomas's words on
    # the left. The rule must not be !important: the copy shown while a message
    # sends is wrapped (.tc-code-pending-user) so the transcript's !important
    # column inset places the wrapper and this margin places the bubble.
    stylesheet = "\n".join(
        (CSS / name).read_text(encoding="utf-8")
        for name in ("unified_code_mode.css", "unified_code_activity.css", "unified_code_cards.css")
    )
    stylesheet = re.sub(r"/\*.*?\*/", "", stylesheet, flags=re.S)
    declarations = [
        value.strip()
        for selector, block in re.findall(r"([^{}]+)\{([^{}]*)\}", stylesheet)
        if re.search(r"\.tc-code-turn\.is-user\b", selector)
        for value in re.findall(r"margin-left\s*:\s*([^;]+)", block)
    ]
    assert declarations and declarations[-1] == "auto", declarations


def test_autopilot_rounds_are_notes_not_your_requests():
    goal = "Fix <the> & thing"
    turn = {"outcome": "failed", "reason": "try again", "transcript": "raw evidence"}
    messages = [
        (autopilot_messages.review_message(goal, turn, "medium"), "Autopilot: continuing: done check"),
        (
            autopilot_messages.repair_message(goal, {"round": 2, "detail": "details"}),
            "Autopilot: continuing: repair round 2",
        ),
        (autopilot_messages.continuation_message(goal, turn), "Autopilot: continuing"),
        (
            autopilot_messages.resume_message(goal, turn, "provider"),
            "Autopilot: continuing: resuming after the usage limit",
        ),
        (autopilot_messages.restart_message(goal, "stopped text"), "Autopilot: continuing: resuming after a restart"),
    ]
    for (message, title), html in zip(messages, render(*(user(message) for message, _ in messages))):
        assert_note(html, message, title)
        assert goal not in html.split("<details", 1)[0]


def test_server_prefix_and_steering_are_rendered_consistently():
    prefix = autopilot_goal.CONTINUATION_PREFIX
    text = prefix + " toward the goal: build it\n\nlong instructions"
    steered = thomas_project.steering_message(["Make the button blue"], text)
    plain, with_steer = render(user(text), user(steered))
    assert_note(plain, text, prefix)
    assert_note(with_steer, steered, prefix)
    assert autopilot_goal.STEER_LINE + "Make the button blue" in with_steer.split("<details", 1)[0]
    assert autopilot_goal.STEER_LINE + "Make the button blue" not in plain.split("<details", 1)[0]


def test_autopilot_word_alone_is_your_own_message():
    html = render(user("Autopilot is helpful"))[0]
    assert 'class="tc-code-turn is-user"' in html
    assert 'class="tc-code-autopilot-note"' not in html
    assert "Autopilot is helpful" in html


def test_saved_turn_reads_work_then_report_then_reply_then_cards():
    # The order a finished turn reads in (Build redesign, design 4a): the work
    # that earned the answer, dim; the report on it; the reply in Thomas's own
    # words; then what he made. A short run's steps read inline.
    events = [
        {"fc": "planning", "text": "PLAN-ONE"},
        {"fc": "model", "text": "MODEL-TWO"},
        {"fc": "say", "text": "PROGRESS-THREE"},
        {"fc": "tool", "name": "shell.run", "text": "STEP-FOUR"},
        {"fc": "final", "text": "REPLY-FIVE"},
    ]
    html = render(
        {
            "role": "agent",
            "ok": True,
            "model_used": "engine",
            "changed_files": ["built.txt"],
            "transcript": "\n".join(map(json.dumps, events)),
        }
    )[0]
    body = html.split('class="tc-code-turn-body">', 1)[1]
    for event in events[:-1]:
        assert event["text"] in body, event
    last_step = max(body.index(event["text"]) for event in events[:-1])
    assert (
        last_step
        < body.index("REPORT")
        < body.index('<div class="tc-code-reply-text">REPLY-FIVE</div>')
        < body.index("CARDS")
    )
    assert body.count("REPLY-FIVE") == 1
    assert 'class="tc-code-steps"' not in body, "two steps fold behind nothing"
    assert "Work completed" not in body
    assert body.endswith('<div class="result-cards">CARDS</div></div></article>')
    assert "data-code-copy-reply" in html


def test_a_long_run_shows_every_step_and_folds_nothing():
    events = [{"fc": "tool_result", "name": "fs.read_file", "text": f"READ-{n}"} for n in range(9)]
    events.append({"fc": "final", "text": "REPLY-DONE"})
    html = render(
        {
            "role": "agent",
            "ok": True,
            "changed_files": ["a.js"],
            "transcript": "\n".join(map(json.dumps, events)),
        }
    )[0]
    body = html.split('class="tc-code-turn-body">', 1)[1]
    assert "tc-code-steps" not in body and "show work" not in body and "more steps" not in body
    assert body.count('<details class="tc-code-work ') == 9
    assert all(f"READ-{n}" in body for n in range(9))
    assert body.index("READ-8") < body.index("REPLY-DONE")


def test_view_state_restores_an_open_steps_disclosure():
    script = r"""
const fs = require('fs'), vm = require('vm');
global.window = {};
vm.runInThisContext(fs.readFileSync(process.argv[1], 'utf8'));
const make = (open) => {
  const detail = { open, tagName: 'DETAILS', className: 'tc-code-steps', textContent: 'Steps (1)',
    dataset: {}, parentElement: null, matches: () => false, closest: (selector) => selector === '[data-code-turn-key]'
      ? { dataset: { codeTurnKey: 'turn-1' } } : null,
    querySelector: () => null, querySelectorAll: () => [] };
  const root = { ownerDocument: { activeElement: null }, contains: () => true,
    querySelector: () => null, querySelectorAll: () => [detail] };
  detail.parentElement = root;
  return { root, detail };
};
const before = make(true), after = make(false);
const saved = window.ThomasCodeViewState.capture(before.root, null);
window.ThomasCodeViewState.restore(after.root, saved, undefined, null);
if (!after.detail.open) throw new Error('Steps closed on redraw');
"""
    path = ROOT / "thomas/server/web/js/unified_code_view_state.js"
    result = subprocess.run(["node", "-e", script, str(path)], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_empty_feed_has_no_steps():
    html = render({"role": "agent", "ok": True, "text": "Done"})[0]
    assert 'class="tc-code-steps"' not in html


def test_note_styles_center_it():
    css = "\n".join(
        (CSS / name).read_text(encoding="utf-8") for name in ("unified_code_mode.css", "unified_code_activity.css")
    )
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rule = re.search(r"\.tc-code-autopilot-note\s*\{([^}]+)\}", css)
    assert rule and re.search(r"margin(?:-left)?\s*:\s*(?:[^;]*\s)?auto", rule.group(1))
