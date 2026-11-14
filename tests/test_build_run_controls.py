"""Build's run controls (unified_code_controls.js), driven in Node against stubbed endpoints.

The 2026-10 redesign's composer button pauses and resumes a run, a queued message's Steer goes
into the lead's inbox, what you type while Thomas is asking is your answer, and the sidebar row
says how a task is going or how it ended. Each of those is one call this module makes or one
reading it gives; they are pinned here on the module itself, with no page and no server.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "js"
MODULES = (
    "unified_code_agents.js",
    "unified_code_roster.js",
    "unified_code_drawer.js",
    "unified_code_cards.js",
    "unified_code_composer.js",
    "unified_code_questions.js",
    "unified_code_controls.js",
)

DRIVER = r"""
const fs = require('node:fs');
const vm = require('node:vm');
globalThis.window = globalThis;
globalThis.document = { getElementById: () => null };
for (const path of process.argv.slice(1)) vm.runInThisContext(fs.readFileSync(path, 'utf8'), { filename: path });
const calls = [];
let reply = () => ({ ok: true });
globalThis.fetch = async (url, options) => {
  const body = options && options.body ? JSON.parse(options.body) : null;
  calls.push({ url, body });
  const data = reply(url, body);
  return { ok: data.ok !== false, status: data.ok === false ? 409 : 200, json: async () => data };
};
const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const state = { running: true, runId: 'r1', activeId: 'c1', conversations: [], liveEvents: [], changes: [], queuedSends: [] };
const pushed = [], steered = [], errors = [];
const controls = window.ThomasCodeControls.create({
  state, esc, host: () => ({}), render() {}, safely: fn => Promise.resolve().then(fn), send: async () => true,
  stopRun: async () => true, steer: async text => { steered.push(text); return true; },
  pushLiveEvent: event => pushed.push(event), recordError: (error, why) => errors.push(`${why}: ${error.message}`),
  changeAction: async () => true, surface: () => null, codeProjects: () => ({}), isInternalResultPath: () => false,
  transcriptText: turn => String(turn.transcript || ''), isActive: () => true,
});
const out = {};
(async () => {
  out.before = controls.runControls();
  controls.applyControls({ run_id: 'r1', controls: { pause: true, message: true, ask: true } });
  out.controlled = controls.runControls();

  controls.observe({ type: 'output', kind: 'plan', run_id: 'r1', event_seq: 1, items: [
    { id: '1', text: 'Map colours', status: 'completed' }, { id: '2', text: 'Wire the toggle', status: 'in_progress', owner: 'Wirer' }] });
  controls.observe({ type: 'output', kind: 'tool', run_id: 'r1', event_seq: 2, name: 'fs.read_file', text: 'path: a.js',
    agent_id: 'child_aaaaaaaaaaaa', agent_title: 'Wirer', agent_mode: 'builder' });
  controls.observe({ type: 'output', kind: 'tool', run_id: 'r1', event_seq: 2, name: 'fs.read_file', text: 'replayed' });
  out.row = controls.historyRow({ id: 'c1' }, true);
  out.agents = state.roster.agents().map(agent => agent.name);

  controls.observe({ type: 'output', kind: 'ask', run_id: 'r1', event_seq: 3, question_id: 'q1', text: 'Which icon?', allow_free_text: true });
  out.answered = await controls.answerTyped('Sun and moon');
  out.answerCall = calls.at(-1);
  out.answerEvent = pushed.at(-1);
  out.answeredAgain = await controls.answerTyped('more words');

  await controls.primaryAction();
  out.afterPause = { ...controls.runControls(), url: calls.at(-1).url };
  out.pausingWord = controls.activityButtonHtml('Working');
  controls.observe({ type: 'output', kind: 'paused', run_id: 'r1', event_seq: 4, text: 'Paused.' });
  out.pausedWord = controls.activityButtonHtml('Working');
  await controls.primaryAction();
  out.afterResume = { ...controls.runControls(), url: calls.at(-1).url };

  reply = url => (url.endsWith('/message') ? { ok: true, receipt: { id: 'm1', agent_id: 'lead', text: 'hi', state: 'queued' } } : { ok: true });
  state.queuedSends = [{ id: 'q-a', message: 'keep it top right', cid: 'c1' }, { id: 'q-b', message: 'other task', cid: 'c2' }];
  out.steeredInbox = await controls.steerQueued('q-a');
  out.steerCall = calls.at(-1);
  out.queueAfterSteer = state.queuedSends.filter(entry => !window.ThomasCodeControls.inInbox(state, entry)).map(entry => entry.id);
  out.heldAfterSteer = state.queuedSends.filter(entry => window.ThomasCodeControls.held(state, entry)).map(entry => entry.id);
  out.chips = state.steers.map(steer => [steer.receiptId, steer.state]);
  out.otherConversation = await controls.steerQueued('q-b');
  controls.observe({ type: 'output', kind: 'steering', run_id: 'r1', event_seq: 5, text: 'keep it top right', steer_id: 'm1' });
  out.chipsAfterRead = state.steers.length;
  out.queueAfterRead = state.queuedSends.map(entry => entry.id);

  controls.applyControls({ run_id: 'r1', controls: { pause: false, message: false, ask: false } });
  state.queuedSends = [{ id: 'q-c', message: 'use green', cid: 'c1' }];
  out.steeredRestart = await controls.steerQueued('q-c');
  out.restartSteer = steered;
  out.stopChoice = window.ThomasCodeComposer.primaryState({ ...controls.runControls(), hasText: false });

  state.finishing = Promise.resolve();
  out.finishing = controls.runControls();
  state.running = false; state.finishing = null;
  const stamp = new Date(Date.now() - 2 * 3600 * 1000).toISOString();
  out.rows = ['completed', 'conversation', 'noop', 'stopped', 'failed', null]
    .map(outcome => controls.historyRow({ id: 'x', last_outcome: outcome, updated_at: stamp }, false));
  out.errors = errors;
  console.log(JSON.stringify(out));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


@pytest.fixture(scope="module")
def seen() -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    result = subprocess.run(
        ["node", "-e", DRIVER, *(str(JS / name) for name in MODULES)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_the_run_says_what_its_lead_can_take(seen):
    assert seen["before"] == {"running": True, "paused": False, "canPause": False}
    assert seen["controlled"] == {"running": True, "paused": False, "canPause": True}
    # A run that is finishing is no longer one you can pause.
    assert seen["finishing"]["running"] is False


def test_frames_feed_the_roster_and_the_plan_once(seen):
    assert seen["agents"] == ["Thomas", "Wirer"]
    assert seen["row"] == {"className": "is-running", "preview": "Step 2 of 2 · 2 agents"}


def test_typing_while_thomas_asks_answers_him(seen):
    assert seen["answered"] is True
    assert seen["answerCall"] == {
        "url": "/api/evolve/agent/answer",
        "body": {"run_id": "r1", "question_id": "q1", "answer": "Sun and moon"},
    }
    # The card folds to "You chose: …" at once.
    assert seen["answerEvent"]["kind"] == "answered" and seen["answerEvent"]["question_id"] == "q1"
    # Once answered, typing is a message again.
    assert seen["answeredAgain"] is False


def test_the_primary_button_pauses_then_resumes(seen):
    assert seen["afterPause"] == {"running": True, "paused": True, "canPause": True, "url": "/api/evolve/agent/pause"}
    assert "Pausing…" in seen["pausingWord"]
    assert ">Paused<" in seen["pausedWord"] and 'data-tone="paused"' in seen["pausedWord"]
    assert seen["afterResume"] == {
        "running": True,
        "paused": False,
        "canPause": True,
        "url": "/api/evolve/agent/resume",
    }


def test_steer_goes_to_the_leads_inbox_and_leaves_the_queue(seen):
    assert seen["steeredInbox"] is True
    assert seen["steerCall"] == {
        "url": "/api/evolve/agent/message",
        "body": {"run_id": "r1", "agent_id": "lead", "text": "keep it top right"},
    }
    # It leaves the queue you see, but is held until the lead reads it.
    assert seen["queueAfterSteer"] == ["q-b"]
    assert seen["heldAfterSteer"] == ["q-a"]
    assert seen["chips"] == [["m1", "queued"]]
    # A message queued for another conversation is never steered into this run.
    assert seen["otherConversation"] is False
    # Once the lead reads it, its own `steering` frame shows it; the chip goes.
    assert seen["chipsAfterRead"] == 0
    assert seen["queueAfterRead"] == ["q-b"]


def test_a_lead_that_takes_no_messages_gets_the_stop_and_continue_steer(seen):
    assert seen["steeredRestart"] is True
    assert seen["restartSteer"] == ["use green"]
    assert seen["stopChoice"] == "stop"
    assert seen["errors"] == []


def test_a_finished_task_row_says_how_it_ended(seen):
    rows = seen["rows"]
    assert [row["className"] for row in rows] == ["is-done", "is-done", "", "", "is-failed", ""]
    assert [row["preview"].split(" · ")[0] for row in rows] == [
        "Verified",
        "Answered",
        "No changes",
        "Stopped",
        "Needs attention",
        "",
    ]


# ---------------------------------------------------------------------------
# What the first review of the redesign found, each pinned on the module: a
# run that can pause can still be stopped, a steer the lead never read goes
# back in the queue, a failed restart-steer keeps your message, the side chat
# belongs to one run in one task, a failed answer stays yours, a question has
# its own slot, the team's tally is one line, and "N agents" counts who is
# still at it.

FIXES_DRIVER = r"""
const fs = require('node:fs');
const vm = require('node:vm');
globalThis.window = globalThis;
const input = { value: '', dataset: {}, placeholder: 'Message Thomas…', events: [], dispatchEvent(event) { this.events.push(event.type); } };
globalThis.document = { getElementById: id => (id === 'tc-input' ? input : null) };
for (const path of process.argv.slice(1)) vm.runInThisContext(fs.readFileSync(path, 'utf8'), { filename: path });
// The side chat as the controls bind it: its handlers, and the thread it draws.
let chat = null;
window.ThomasCodeAgentChat = {
  bind: (_root, handlers) => { chat = handlers; },
  threadFor: (agent, receipts) => receipts.filter(receipt => receipt.agent_id === agent.id),
  html: ctx => JSON.stringify(ctx.thread.map(item => [item.text, item.state])),
};
const calls = [];
let reply = () => ({ ok: true });
globalThis.fetch = async (url, options) => {
  calls.push(url);
  const data = reply(url, options && options.body ? JSON.parse(options.body) : null);
  return { ok: data.ok !== false, status: data.ok === false ? 409 : 200, json: async () => data };
};
const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const flush = async () => { for (let i = 0; i < 5; i += 1) await new Promise(resolve => setTimeout(resolve, 0)); };
const Controls = window.ThomasCodeControls;
function make() {
  const state = { running: true, runId: 'r1', activeId: 'c1', conversations: [], liveEvents: [], changes: [], queuedSends: [] };
  const log = { stopped: 0, steered: [], started: 0, errors: [], steerResult: true, heldDuringSteer: null };
  const controls = Controls.create({
    state, esc, host: () => ({}), render() {},
    safely: async fn => { try { return await fn(); } catch (error) { log.errors.push(error.message); return null; } },
    send: async () => true, stopRun: async () => { log.stopped += 1; return true; },
    steer: async text => { log.steered.push(text); log.heldDuringSteer = Controls.held(state, state.queuedSends[0]); return log.steerResult; },
    startNextQueued: () => { log.started += 1; },
    pushLiveEvent() {}, recordError: (error, why) => log.errors.push(why),
    changeAction: async () => true, surface: () => null, codeProjects: () => ({}), isInternalResultPath: () => false,
    transcriptText: turn => String(turn.transcript || ''), isActive: () => true,
  });
  return { state, controls, log };
}
const inbox = { run_id: 'r1', controls: { pause: true, message: true, ask: true } };
const out = {};
(async () => {
  { // A paused run still stops: the status line's Stop and Escape both call stopLive.
    const { state, controls, log } = make();
    controls.applyControls(inbox);
    controls.observe({ kind: 'paused', run_id: 'r1', event_seq: 1 });
    out.pausedPrimary = window.ThomasCodeComposer.primaryState({ ...controls.runControls(), hasText: false });
    out.stopWhilePaused = controls.stopLive();
    await flush();
    out.stopCalls = log.stopped;
    state.running = false;
    out.stopWhenIdle = controls.stopLive();
  }
  { // A steer in the lead's inbox that the run ends without reading.
    const { state, controls } = make();
    controls.applyControls(inbox);
    reply = url => (url.endsWith('/message') ? { ok: true, receipt: { id: 'm1', agent_id: 'lead', state: 'queued' } } : { ok: true });
    state.queuedSends = [{ id: 'q1', message: 'also add dark mode', cid: 'c1' }];
    out.steered = await controls.steerQueued('q1');
    out.heldWhileLive = Controls.held(state, state.queuedSends[0]);
    controls.observe({ kind: 'done', run_id: 'r1', event_seq: 9, ok: true });
    out.afterDone = { queue: state.queuedSends.map(entry => entry.id), held: Controls.held(state, state.queuedSends[0]), chips: state.steers.length };
    state.running = false;
    out.startsAfterRun = !Controls.held(state, state.queuedSends[0]);
  }
  { // The poll says one steer was read and one never will be.
    const { state, controls } = make();
    controls.applyControls(inbox);
    reply = (url, body) => {
      if (url.endsWith('/message')) return { ok: true, receipt: { id: body.text === 'read me' ? 'ma' : 'mu', agent_id: 'lead', state: 'queued' } };
      if (url.includes('/messages?')) return { ok: true, messages: [{ id: 'ma', agent_id: 'lead', state: 'acked' }, { id: 'mu', agent_id: 'lead', state: 'undelivered' }], questions: [] };
      return { ok: true };
    };
    state.queuedSends = [{ id: 'qa', message: 'read me', cid: 'c1' }, { id: 'qu', message: 'never read', cid: 'c1' }];
    await controls.steerQueued('qa');
    await controls.steerQueued('qu');
    controls.tick();
    await flush();
    out.afterPoll = { queue: state.queuedSends.map(entry => [entry.id, Controls.held(state, entry)]), chips: state.steers.length };
  }
  { // The stop-and-continue steer keeps your message until the run has it.
    const { state, controls, log } = make();
    state.queuedSends = [{ id: 'q3', message: 'use green', cid: 'c1' }];
    log.steerResult = null;  // /steer answered 409: safely() hands back null
    out.restartFailed = await controls.steerQueued('q3');
    out.heldDuringRestart = log.heldDuringSteer;
    out.restartQueue = state.queuedSends.map(entry => entry.id);
    out.restartChips = state.steers.length;
    log.steerResult = true;
    out.restartOk = await controls.steerQueued('q3');
    out.restartQueueAfter = state.queuedSends.map(entry => entry.id);
  }
  { // The side chat: a failed message stops nothing polling, and another task starts clean.
    const { state, controls } = make();
    controls.observe({ kind: 'say', run_id: 'r1', event_seq: 1, text: 'hello' });
    controls.afterRender({ querySelectorAll: () => [], querySelector: () => null });
    state.agentChat = { agentId: 'lead' };
    reply = url => (url.endsWith('/message') ? { ok: false, error: 'agent_not_listening' } : { ok: true, messages: [], questions: [] });
    chat.onSend('first try');
    await flush();
    out.failedShown = controls.agentChatHtml();
    chat.onClose();
    calls.length = 0;
    controls.tick();
    await flush();
    out.pollsAfterFailure = calls.filter(url => url.includes('/messages?')).length;
    state.agentChat = { agentId: 'lead' };
    reply = url => (url.endsWith('/message') ? { ok: true, receipt: { id: 'm5', agent_id: 'lead', text: 'second', state: 'queued' } } : { ok: true, messages: [], questions: [] });
    chat.onSend('second');
    await flush();
    out.beforeSwitch = controls.agentChatHtml();
    Object.assign(state, { running: false, runId: '', activeId: 'c2', liveEvents: [],
      conversation: { turns: [{ role: 'agent', run_id: 'r0', ok: true, transcript: '{"fc":"say","text":"done before"}' }] } });
    controls.syncRoster();
    out.chatAfterSwitch = state.agentChat;
    state.agentChat = { agentId: 'lead' };
    out.reopenedInB = controls.agentChatHtml();
  }
  { // An answer that did not arrive goes back in the composer.
    const { controls } = make();
    controls.observe({ kind: 'ask', run_id: 'r1', event_seq: 1, question_id: 'qa', text: 'Which icon?', allow_free_text: true, options: [{ label: 'Sun' }] });
    reply = url => (url.endsWith('/answer') ? { ok: false, error: 'that question is no longer open' } : { ok: true });
    input.value = '';
    out.failedAnswer = await controls.answerTyped('Blue please');
    out.inputAfter = input.value;
    out.inputEvents = input.events.slice();
  }
  { // A question has its own slot; a re-entered run gets its state back from the replay.
    const { state, controls } = make();
    const frames = [
      { kind: 'paused', run_id: 'r1', event_seq: 1 },
      { kind: 'ask', run_id: 'r1', event_seq: 2, question_id: 'q9', text: 'Which colour?', allow_free_text: false, options: [{ label: 'Blue', recommended: true }] },
      { kind: 'plan', run_id: 'r1', event_seq: 3, items: [{ id: '1', text: 'Do it', status: 'in_progress' }] },
    ];
    frames.forEach(frame => controls.observe(frame));
    out.slotOpen = controls.liveAskHtml();
    for (let i = 0; i < 200; i += 1) {
      controls.observe({ kind: 'tool', run_id: 'r1', event_seq: 10 + i, name: 'fs.read_file', text: 'path: a.js',
        agent_id: 'child_aaaaaaaaaaaa', agent_title: 'Scout', agent_mode: 'read_only' });
    }
    out.slotAfterBusyFeed = (controls.liveAskHtml().match(/data-code-ask-option/g) || []).length;
    Object.assign(state, { running: false, runId: '', activeId: 'c2', liveEvents: [], conversation: null });
    controls.syncRoster();
    Object.assign(state, { running: true, runId: 'r1', activeId: 'c1' });
    controls.syncRoster();
    frames.forEach(frame => controls.observe(frame));
    out.afterReplay = { paused: state.paused, held: state.pauseHeld, plan: Boolean(state.plan), ask: controls.liveAskHtml().includes('Which colour?') };
    controls.observe({ kind: 'answered', run_id: 'r1', event_seq: 300, question_id: 'q9', answer: 'Blue', text: 'Blue' });
    out.slotAnswered = controls.liveAskHtml();
  }
  { // The team's tally: one quiet line, newest wins, gone once there is a plan.
    const { controls } = make();
    controls.observe({ kind: 'planning', name: 'team-progress', run_id: 'r1', event_seq: 1, team_id: 't1', text: 'Team: 0/3 files integrated · queued 3.' });
    controls.observe({ kind: 'planning', name: 'team-progress', run_id: 'r1', event_seq: 2, team_id: 't1', text: 'Team: 1/3 files integrated · queued 0.' });
    out.teamLine = controls.liveStepsHtml();
    controls.observe({ kind: 'plan', run_id: 'r1', event_seq: 3, items: [{ id: '1', text: 'Build pages', status: 'in_progress' }] });
    out.stepsWithPlan = controls.liveStepsHtml();
  }
  { // "N agents": who is still at it while live, everyone once it ended.
    const { state, controls } = make();
    const menu = { agent_id: 'child_aaaaaaaaaaaa', agent_title: 'Menu page helper', agent_mode: 'builder' };
    const home = { agent_id: 'child_bbbbbbbbbbbb', agent_title: 'Home page helper', agent_mode: 'builder' };
    controls.observe({ kind: 'say', run_id: 'r1', event_seq: 1, text: 'Splitting it.' });
    controls.observe({ kind: 'meta', run_id: 'r1', event_seq: 2, ...menu, text: '[Menu page helper] Spawned Menu page helper' });
    controls.observe({ kind: 'meta', run_id: 'r1', event_seq: 3, ...home, text: '[Home page helper] Spawned Home page helper' });
    controls.observe({ kind: 'meta', run_id: 'r1', event_seq: 4, ...menu, text: '[Menu page helper] Menu page helper finished' });
    out.pillLive = controls.activityButtonHtml('Working');
    out.rowLive = controls.historyRow({ id: 'c1' }, true).preview;
    controls.observe({ kind: 'done', run_id: 'r1', event_seq: 5, ok: true });
    state.running = false;
    out.pillDone = controls.activityButtonHtml('Completed');
  }
  console.log(JSON.stringify(out));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""

PROJECTS_DRIVER = r"""
const fs = require('node:fs');
const vm = require('node:vm');
globalThis.window = { localStorage: { getItem: () => null, setItem() {}, removeItem() {} }, addEventListener() {}, setInterval() {} };
globalThis.localStorage = window.localStorage;
globalThis.document = { readyState: 'loading', addEventListener() {}, getElementById: () => null };
globalThis.fetch = async () => ({ ok: true, json: async () => ({ ok: true, running: true, run_id: 'run-1', session: { started_at: 1 } }) });
for (const path of process.argv.slice(1)) vm.runInThisContext(fs.readFileSync(path, 'utf8'), { filename: path });
// Parked before this change: the entry still names where the park left off.
const state = { activeId: 'c1', contextEpoch: 1, running: false, finishing: false, liveEvents: [], runStatus: 'ready',
  runId: '', eventCursor: 0, parkedRuns: { c1: { runId: 'run-1', startedAt: 5, cursor: 41 } } };
window.ThomasCodeProjects.configure({ state });
let streamedFrom = null;
const lifecycle = {
  contextToken: () => 1, contextMatches: () => true, registerRunProof() {},
  adoptRunIdentity: (s, id) => { if (s.runId !== id) s.eventCursor = 0; s.runId = id; },
};
const session = window.ThomasCodeProjects.createTaskSession({
  closeSource() {}, esc: String, finishBusy() {}, host: () => ({ setBusy() {} }), lifecycle: () => lifecycle,
  loadConversation() {}, loadTree() {}, openStream() { streamedFrom = state.eventCursor; },
  pushLiveEvent(event) { state.liveEvents.push(event); }, recordError() {}, recordPreferenceWarning() {}, refresh() {},
  render() {}, safely() {},
});
(async () => {
  const ok = await session.reattachRunFor('c1');
  console.log(JSON.stringify({ ok, streamedFrom, running: state.running, parked: state.parkedRuns.c1 || null }));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""


def _node(driver: str, *modules: str) -> dict:
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    result = subprocess.run(
        ["node", "-e", driver, *(str(JS / name) for name in modules)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def fixed() -> dict:
    return _node(FIXES_DRIVER, *MODULES)


def test_a_run_that_can_pause_can_still_be_stopped(fixed):
    assert fixed["pausedPrimary"] == "resume"
    assert fixed["stopWhilePaused"] is True and fixed["stopCalls"] == 1
    assert fixed["stopWhenIdle"] is False


def test_a_steer_the_lead_never_read_goes_back_in_the_queue(fixed):
    assert fixed["steered"] is True and fixed["heldWhileLive"] is True
    # `done` came with no `steering` frame for it: the message is queued again.
    assert fixed["afterDone"] == {"queue": ["q1"], "held": False, "chips": 0}
    assert fixed["startsAfterRun"] is True
    # The poll's word for it: read -> gone; never read -> back, free to start.
    assert fixed["afterPoll"] == {"queue": [["qu", False]], "chips": 0}


def test_a_failed_stop_and_continue_steer_keeps_the_message(fixed):
    assert fixed["restartFailed"] is False
    assert fixed["heldDuringRestart"] is True, "a queued message being steered is never started as a task"
    assert fixed["restartQueue"] == ["q3"] and fixed["restartChips"] == 0
    assert fixed["restartOk"] is True and fixed["restartQueueAfter"] == []


def test_the_side_chat_belongs_to_one_run_in_one_task(fixed):
    assert json.loads(fixed["failedShown"]) == [["first try", "failed"]]
    assert fixed["pollsAfterFailure"] == 0, "a failed message is not waiting on anything"
    assert sorted(json.loads(fixed["beforeSwitch"])) == [["first try", "failed"], ["second", "queued"]]
    assert fixed["chatAfterSwitch"] is None
    assert json.loads(fixed["reopenedInB"]) == []


def test_an_answer_that_did_not_arrive_stays_in_the_composer(fixed):
    assert fixed["failedAnswer"] == "failed"
    assert fixed["inputAfter"] == "Blue please" and fixed["inputEvents"] == ["input"]


def test_a_question_keeps_its_own_slot_and_comes_back_after_a_park(fixed):
    assert "Which colour?" in fixed["slotOpen"] and "data-code-ask-option" in fixed["slotOpen"]
    assert fixed["slotAfterBusyFeed"] == 1, "200 helper frames later the one card is still there"
    assert fixed["afterReplay"] == {"paused": True, "held": True, "plan": True, "ask": True}
    assert "You chose: Blue" in fixed["slotAnswered"] and "data-code-ask-option" not in fixed["slotAnswered"]


def test_the_team_tally_is_one_line_until_there_is_a_plan(fixed):
    assert fixed["teamLine"].count("tc-code-quietline") == 1
    assert "Team: 1/3 files integrated" in fixed["teamLine"] and "0/3" not in fixed["teamLine"]
    assert fixed["stepsWithPlan"] == ""  # a plan is the pinned card, never an inline one


def test_n_agents_counts_who_is_still_working_then_everyone(fixed):
    assert ">2 agents<" in fixed["pillLive"], "the lead and the helper still building"
    assert fixed["rowLive"] == "Working · 2 agents"
    assert ">3 agents<" in fixed["pillDone"]


def test_coming_back_to_a_parked_run_replays_its_stream_from_the_start():
    seen = _node(PROJECTS_DRIVER, "unified_code_agents.js", "unified_code_projects.js")
    assert seen["ok"] is True and seen["running"] is True
    assert seen["streamedFrom"] == 0, "a cursor past the `paused` and `ask` frames loses them"
    assert seen["parked"] is None
