"""Build's transcript, redesigned: work rows, STEPS, the proof card, ask, steer, live diff.

The Build redesign (designs 3a and 4a-4c) makes a Build conversation read like
one: what you and Thomas say is bright prose, and the work underneath is one dim
mono row per step. Those pieces are drawn by ``unified_code_cards.js`` and fed by
``unified_code_events.js``; ``unified_code_live_diff.js`` reads what an agent is
writing right now from the project.

Two halves, because neither covers the other:

* ``tests/web_node/build_transcript_cards.mjs`` runs the shipped modules under
  Node: each piece's markup and escaping, the verb a step gets, a call folded
  into its result, the proof card's honesty rules, the order a saved turn reads
  in, a question folding its answer, and the live-diff poller's baseline rule.
* ``test_the_transcript_wears_the_design_in_a_real_page`` loads the modules and
  their stylesheets into Chromium and reads computed styles: the colours, type
  and indents the design fixes, where your bubble and Thomas's words sit, that
  no bot or fold is drawn in the transcript, and that every row shows. It
  skips where Chromium cannot launch.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "thomas" / "server" / "web"
HARNESS = ROOT / "tests" / "web_node" / "build_transcript_cards.mjs"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from web_fixtures.thomas_chat_fixture import browser_ok  # noqa: E402


def test_the_transcript_pieces_hold_under_node() -> None:
    result = subprocess.run(
        ["node", str(HARNESS), str(WEB / "js")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    checks = json.loads(result.stdout)
    failed = [name for name, ok in checks.items() if not ok]
    assert not failed, f"transcript checks failed: {failed}"
    assert len(checks) >= 20


PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<link rel="stylesheet" href="/static/css/tokens.css">
<link rel="stylesheet" href="/static/css/unified_code_mode.css">
<link rel="stylesheet" href="/static/css/unified_code_activity.css">
<link rel="stylesheet" href="/static/css/unified_code_results.css">
<link rel="stylesheet" href="/static/css/thomas_bot.css">
<link rel="stylesheet" href="/static/css/unified_code_cards.css">
<script src="/static/js/thomas_bot.js"></script>
<script src="/static/js/unified_code_view_state.js"></script>
<script src="/static/js/unified_code_artifacts.js"></script>
<script src="/static/js/unified_code_results.js"></script>
<script src="/static/js/unified_code_agents.js"></script>
<script src="/static/js/unified_code_cards.js"></script>
<script src="/static/js/unified_code_events.js"></script>
</head>
<body style="margin:0">
<div id="tc-shell" data-surface-mode="code" style="width:900px;height:900px;background:var(--c-bg);font-family:var(--font-sans);">
  <section class="tc-code-transcript" style="height:900px"><div id="tc-code-turns"></div></section>
</div>
</body></html>"""

SCENARIO = """() => {
  const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state = { running: false, runStartedAt: 0, projectRoot: '/p', activeId: 'c1', conversation: null, changes: [] };
  window.ThomasCodeResults.configure({ state, esc, isInternalResultPath: () => false, lifecycle: () => ({}),
    render() {}, pushLiveEvent() {}, safely() {}, recordPreferenceWarning() {} });
  const api = window.ThomasCodeEvents.create({
    MAX_PROGRESS_EVENT_CHARS: 420,
    NARRATIVE_EVENT_KINDS: new Set(['approval','disconnected','done','final','insight','planning','say','settings','steering','stopped','stopping']),
    state, esc, codeResults: () => window.ThomasCodeResults, surface: () => null, isInternalResultPath: () => false,
  });
  const L = rows => rows.map(r => JSON.stringify(r)).join('\\n');
  const rubric = (status) => ({ outcome: 'completed', validations: [{ passed: true, evidence: 'ok' }], open_risks: [],
    rubric_mapping: [{ criterion: 'the run finished without error', status: 'met' }, { criterion: 'a toggle', status, evidence: 'clicked' }] });
  const t0 = 1761750000000;
  const planned = { role: 'agent', ok: true, report: rubric('met'), changed_files: ['a.css'], transcript: L([
    { fc: 'plan', ts: t0, items: [{ id: '1', text: 'Map', status: 'completed', started_at: t0, done_at: t0 + 9000 }, { id: '2', text: 'Toggle', status: 'in_progress' }] },
    { fc: 'say', ts: t0 + 1, text: 'Working on it.' },
    { fc: 'tool_result', ts: t0 + 2, name: 'diff.create', path: 'a.css', added: 4, removed: 1, text: 'Replaced 1 line(s) with 4 line(s) in a.css' },
    { fc: 'final', ts: t0 + 9000, text: 'Done.' } ]) };
  const failing = { role: 'agent', ok: true, report: rubric('not_met'), transcript: L([
    { fc: 'tool_result', name: 'fs.read_file', path: 'b.js', text: 'x' }, { fc: 'final', text: 'Not yet.' } ]) };
  const ask = window.ThomasCodeCards.askHtml({ esc, question: { question_id: 'q', question: 'Keep?', options: [{ label: 'Keep', recommended: true }, { label: 'Lose' }] }, waitingOn: 'Wirer' });
  const diff = window.ThomasCodeCards.liveDiffHtml({ esc, diff: { file: 'i.html', added: 1, removed: 0, lines: [{ n: 1, sign: '+', text: '<b>' }] } });
  document.getElementById('tc-code-turns').innerHTML = api.turnHtml({ role: 'user', text: 'Make a dark mode.' })
    + api.turnHtml(planned) + api.turnHtml(failing)
    + `<article class="tc-code-turn is-agent"><div class="tc-code-turn-body">${ask}${diff}</div></article>`
    + window.ThomasCodeCards.stepsHtml({ esc, plan: { items: [{ id: '1', text: 'Map', status: 'completed', started_at: t0, done_at: t0 + 9000 }, { id: '2', text: 'Toggle', status: 'in_progress' }] } });
  const css = (sel, prop, pseudo) => getComputedStyle(document.querySelector(sel), pseudo || null)[prop];
  const out = {};
  const turns = document.getElementById('tc-code-turns').getBoundingClientRect();
  const bubble = document.querySelector('.tc-code-turn.is-user');
  out.bubbleRight = turns.right - bubble.getBoundingClientRect().right;
  out.thomasLeft = document.querySelector('.tc-code-reply-text').getBoundingClientRect().left - turns.left;
  out.botsInTranscript = document.querySelectorAll('.tc-code-turn .tc-code-work-bot, .tc-code-turn [class*="-bot"]').length;
  out.heads = document.querySelectorAll('.tc-code-turn-body > .tc-code-message-head').length;
  out.replyHeads = document.querySelectorAll('.tc-code-reply > .tc-code-message-head').length;
  out.foldRows = document.querySelectorAll('details.tc-code-steps, .tc-code-receipts-more').length;
  out.bubbleBg = css('.tc-code-turn.is-user', 'backgroundColor');
  out.bubbleInk = css('.tc-code-turn.is-user', 'color');
  out.bubbleRadius = css('.tc-code-turn.is-user', 'borderTopLeftRadius');
  out.youHeading = /\\bYou\\b/.test(bubble.textContent.replace('Make a dark mode.', ''));
  out.replyInk = css('.tc-code-reply', 'color');
  out.replySize = css('.tc-code-reply', 'fontSize');
  out.replyWeight = css('.tc-code-reply', 'fontWeight');
  out.bodyIndent = css('.tc-code-turn-body', 'paddingLeft');
  out.planDoneFill = css('.tc-code-plan-row.is-completed .tc-code-plan-mark', 'backgroundColor');
  out.verbWeight = css('.tc-code-work-verb', 'fontWeight');
  out.detailFont = css('.tc-code-work-detail', 'fontFamily');
  out.addInk = css('.tc-code-work-meta .tc-code-add', 'color');
  out.rowMarker = css('.tc-code-work > summary', 'display');
  const proofs = document.querySelectorAll('.tc-code-proof');
  out.proofs = proofs.length;
  out.goodRule = getComputedStyle(proofs[0]).borderLeftColor;
  out.badRule = getComputedStyle(proofs[1]).borderLeftColor;
  const reply = [...document.querySelectorAll('.tc-code-reply')].find(n => n.textContent.includes('Not yet.'));
  const fix = document.querySelector('[data-code-proof-fix]');
  out.fixAfterReply = Boolean(reply && fix && (reply.compareDocumentPosition(fix) & Node.DOCUMENT_POSITION_FOLLOWING));
  out.fixBg = getComputedStyle(fix).backgroundColor;
  out.askLabel = css('.tc-code-ask-label', 'color');
  out.askBg = css('.tc-code-ask', 'backgroundColor');
  out.addLineBg = css('.tc-code-livediff-line.is-add', 'backgroundColor');
  out.addLineInk = css('.tc-code-livediff-line.is-add', 'color');
  out.diffBg = css('.tc-code-livediff', 'backgroundColor');
  // A row you opened stays open when the live feed redraws around it: the
  // reader-state keeper keys rows on what they hold, and the work row keeps
  // what it keys on (tc-code-receipt, data-code-* and the <pre>).
  const live = document.createElement('div');
  live.id = 'tc-code-live-events';
  document.querySelector('.tc-code-transcript').appendChild(live);
  const step = n => ({ kind: 'tool_result', name: 'fs.read_file', path: `f${n}.js`, text: `body ${n}`, event_seq: n });
  const shell = document.getElementById('tc-shell');
  // The first draw records the run the rows belong to, as the surface's render does.
  window.ThomasCodeViewState.replaceActivity(shell, live, api.interleavedActivityHtml([1, 2, 3].map(step), false), 'scope', null);
  live.querySelectorAll('.tc-code-work')[1].open = true;
  window.ThomasCodeViewState.replaceActivity(shell, live, api.interleavedActivityHtml([1, 2, 3, 4].map(step), false), 'scope', null);
  out.reopened = [...live.querySelectorAll('.tc-code-work')].map(row => row.open);
  return out;
}"""


def _serve_static(route) -> None:
    """The page's /static tree, from the shipped files (tokens.css @imports a sibling)."""
    relative = route.request.url.split("/static/", 1)[1].split("?", 1)[0]
    path = (WEB / relative).resolve()
    if WEB.resolve() not in path.parents or not path.is_file():
        route.fulfill(status=404, body="")
        return
    kind = "text/css" if path.suffix == ".css" else "text/javascript"
    route.fulfill(status=200, content_type=kind, body=path.read_bytes())


def test_the_transcript_wears_the_design_in_a_real_page() -> None:
    if not browser_ok():
        pytest.skip("Chromium cannot launch here")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 900, "height": 900})
            errors: list[str] = []
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            page.route("http://thomas.test/static/**", _serve_static)
            page.route(
                "http://thomas.test/",
                lambda route: route.fulfill(status=200, content_type="text/html", body=PAGE),
            )
            page.goto("http://thomas.test/", wait_until="load")
            out = page.evaluate(SCENARIO)
        finally:
            browser.close()

    assert not errors, errors
    # Your words: a bright bubble at the column's right edge, no name over it.
    assert abs(out["bubbleRight"]) <= 1, out["bubbleRight"]
    # Thomas's words stay on the left, under his own small head; no bots, no fold.
    assert abs(out["thomasLeft"]) <= 1, out["thomasLeft"]
    assert out["botsInTranscript"] == 0
    assert out["heads"] == 0 and out["replyHeads"] >= 2
    assert out["foldRows"] == 0
    assert out["bubbleBg"] == "rgb(42, 46, 54)"
    assert out["bubbleInk"] == "rgb(247, 248, 250)"
    assert out["bubbleRadius"] == "10px"
    assert out["youHeading"] is False
    # Thomas's words: 15px, weight 500, the strong ink, under his head.
    assert out["replyInk"] == "rgb(247, 248, 250)"
    assert out["replySize"] == "15px" and out["replyWeight"] == "500"
    assert out["bodyIndent"] == "0px"
    # The work: every row, in order, no marker.
    assert out["planDoneFill"] == "rgb(110, 155, 255)"
    assert out["verbWeight"] == "650"
    assert "JetBrains Mono" not in out["detailFont"]
    assert out["addInk"] == "rgb(95, 211, 138)"
    assert out["rowMarker"] == "flex"
    # The Verifier: green when your asks pass, red when one fails, and the fix
    # offered under the reply that explains the failure.
    assert out["proofs"] == 2
    assert out["goodRule"] == "rgb(71, 215, 172)"
    assert out["badRule"] == "rgb(255, 154, 154)"
    assert out["fixAfterReply"] is True
    assert out["fixBg"] == "rgb(110, 155, 255)"
    # Asking and writing.
    assert out["askLabel"] == "rgb(226, 178, 95)"
    assert out["askBg"] == "rgb(27, 30, 35)"
    assert out["addLineBg"] == "rgba(63, 185, 80, 0.14)"
    assert out["addLineInk"] == "rgb(95, 211, 138)"
    assert out["diffBg"] == "rgb(17, 19, 22)"
    # The row you opened survives a live redraw; nothing else opens.
    assert out["reopened"] == [False, True, False, False], out["reopened"]
