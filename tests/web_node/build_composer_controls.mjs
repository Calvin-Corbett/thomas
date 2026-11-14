// Build's composer controls: the primary button and the queue stack.
//
// The redesign turns Build's round send button into Send / Pause / Resume /
// Stop, and stacks every message sent mid-run above the composer with its own
// Steer and ✕. This drives the shipped pieces together:
//
//   1. js/unified_code_composer.js -- primaryState's rule, applyPrimary's
//      icon / name / fill on the button, clearPrimary handing the button back
//      to Chat, extrasHtml's markup (escaped), formatElapsed, and bind()
//      reporting Steer and ✕ by id;
//   2. js/chat_message_view.js syncDynamic -- in Build it asks the composer,
//      reading ThomasCodeMode.runControls() when the run offers it and keeping
//      the old Stop when it does not; in Chat it clears the Build state;
//   3. js/chat_shell_bindings.js -- an empty-composer click in Build goes to
//      ThomasCodeMode.primaryAction() and nowhere else (never to Chat's stop),
//      falling back to the mode's stop() only when that accessor is absent.
//
// The real-DOM half (render() patching in place, focus, computed styles) is
// tests/test_build_composer_controls.py in Chromium.
import assert from 'node:assert/strict';
import { installFeature, installScript } from './chat_feature_fixture.mjs';

const htmlPath = process.argv[2];
if (!htmlPath) throw new Error('usage: node build_composer_controls.mjs <chat.html>');

const checks = {};
function check(name, run) { run(); checks[name] = true; }

function fakeButton(title = 'Send') {
  const attrs = new Map([['title', title]]);
  const props = new Map();
  return {
    dataset: {}, disabled: false, attrs, props,
    getAttribute: name => (attrs.has(name) ? attrs.get(name) : null),
    setAttribute: (name, value) => { attrs.set(name, String(value)); },
    removeAttribute: name => { attrs.delete(name); },
    hasAttribute: name => attrs.has(name),
    style: { setProperty: (key, value) => { props.set(key, value); }, removeProperty: key => { props.delete(key); } },
  };
}

const lib = { window: {} };
installScript(lib, htmlPath, 'unified_code_composer.js');
const composer = lib.window.ThomasCodeComposer;

// ---- 1. the module ----
check('primaryStateRule', () => {
  const state = (running, paused, hasText, canPause) => composer.primaryState({ running, paused, hasText, canPause });
  assert.equal(state(true, false, true, true), 'send', 'typed text sends even mid-run');
  assert.equal(state(true, true, true, true), 'send', 'typed text sends even while paused');
  assert.equal(state(true, true, false, true), 'resume');
  assert.equal(state(true, true, false, false), 'resume', 'a paused run resumes whatever canPause says');
  assert.equal(state(true, false, false, true), 'pause');
  assert.equal(state(true, false, false, false), 'stop', 'a run that cannot pause can only stop');
  assert.equal(state(false, false, false, true), 'send', 'idle and empty is the disabled-looking Send');
  assert.equal(state(false, true, false, true), 'send', 'a stale paused flag on an idle run is not Resume');
  assert.equal(composer.primaryState(), 'send');
});

check('applyPrimaryDrawsEachState', () => {
  const cases = [
    ['pause', { running: true, canPause: true }, 'ph ph-pause', 'Pause', 'var(--c-surface-2)'],
    ['resume', { running: true, paused: true }, 'ph ph-play', 'Resume', 'var(--c-surface-2)'],
    ['stop', { running: true }, 'ph ph-stop', 'Stop', 'var(--c-surface-2)'],
    ['send', { running: true, hasText: true }, 'ph ph-arrow-up', 'Send', 'var(--c-accent)'],
  ];
  for (const [state, ctx, icon, label, bg] of cases) {
    const button = fakeButton(), iconEl = { className: 'ph ph-arrow-up' };
    assert.equal(composer.applyPrimary(button, iconEl, state, ctx), state);
    assert.equal(iconEl.className, icon, state);
    assert.equal(button.dataset.primary, state);
    assert.equal(button.getAttribute('aria-label'), label);
    assert.equal(button.props.get('--send-bg'), bg, `${state} fill`);
    assert.equal(button.hasAttribute('aria-disabled'), false, `${state} is never disabled`);
  }
  // Pause, Resume and Stop are neutral controls with full-strength ink.
  const pause = fakeButton();
  composer.applyPrimary(pause, null, 'pause', { running: true, canPause: true });
  assert.equal(pause.props.get('--send-ink'), 'var(--c-text)');
  assert.match(pause.getAttribute('title'), /hold/i, 'the tooltip says what Pause does');
  // A mid-run Send says it queues.
  const queued = fakeButton();
  composer.applyPrimary(queued, null, 'send', { running: true, hasText: true });
  assert.match(queued.getAttribute('title'), /waits|queue/i);
});

check('emptySendLooksDisabled', () => {
  const button = fakeButton(), iconEl = { className: '' };
  composer.applyPrimary(button, iconEl, 'send', { running: false, hasText: false });
  assert.equal(button.getAttribute('aria-disabled'), 'true');
  assert.equal(button.props.get('--send-bg'), 'var(--c-surface-2)');
  assert.equal(button.props.get('--send-ink'), 'var(--c-muted)');
  assert.equal(button.props.get('--send-cursor'), 'default');
  // Typing lifts it: same button, accent fill, no aria-disabled left behind.
  composer.applyPrimary(button, iconEl, 'send', { running: false, hasText: true });
  assert.equal(button.hasAttribute('aria-disabled'), false);
  assert.equal(button.props.get('--send-bg'), 'var(--c-accent)');
  // Without a context the caller vouches for the send.
  const bare = fakeButton();
  composer.applyPrimary(bare, null, 'send');
  assert.equal(bare.props.get('--send-bg'), 'var(--c-accent)');
  // An unknown state is drawn as Send, never as a blank button.
  assert.equal(composer.applyPrimary(fakeButton(), iconEl, 'explode', { hasText: true }), 'send');
  assert.equal(iconEl.className, 'ph ph-arrow-up');
});

check('clearPrimaryHandsTheButtonBack', () => {
  const button = fakeButton('Send');
  composer.applyPrimary(button, null, 'pause', { running: true, canPause: true });
  composer.applyPrimary(button, null, 'resume', { running: true, paused: true });
  composer.clearPrimary(button);
  assert.equal('primary' in button.dataset, false);
  assert.equal('chatTitle' in button.dataset, false);
  assert.equal(button.getAttribute('title'), 'Send', 'the page tooltip comes back, not the last Build one');
  assert.equal(button.hasAttribute('aria-label'), false);
  assert.equal(button.hasAttribute('aria-disabled'), false);
  assert.equal(button.props.size, 0, 'no --send-* left on the button to mask the shell');
  composer.clearPrimary(button); // idempotent
  composer.clearPrimary(null);
  assert.equal(button.getAttribute('title'), 'Send');
});

check('formatElapsed', () => {
  assert.equal(composer.formatElapsed(0), '0s');
  assert.equal(composer.formatElapsed(14999), '14s');
  assert.equal(composer.formatElapsed(72000), '1m 12s');
  assert.equal(composer.formatElapsed(3723000), '1h 02m');
  assert.equal(composer.formatElapsed(-5), '0s');
  assert.equal(composer.formatElapsed('soon'), '');
});

const esc = value => String(value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

check('extrasEmptyIsNothing', () => {
  assert.equal(composer.extrasHtml({ esc, queued: [], status: null }), '');
  assert.equal(composer.extrasHtml({ esc }), '');
  assert.equal(composer.extrasHtml({ esc, status: { words: '', stepText: '', elapsed: '' } }), '');
});

check('extrasQueueMarkup', () => {
  const html = composer.extrasHtml({ esc, queued: [
    { id: 'q1', message: 'make the toggle a sun and moon icon' },
    { id: 'q"2', message: 'also <b>keep</b>\nit in the top right' },
  ], status: null });
  const items = html.match(/class="tc-code-queue-item/g) || [];
  assert.equal(items.length, 2);
  assert.match(html, /role="list" aria-label="Queued messages"/);
  assert.match(html, />Queued</, 'the QUEUED label (uppercased by CSS)');
  assert.match(html, /data-code-queue-steer="q1"[^>]*>Steer</);
  assert.match(html, /data-code-queue-remove="q1"/);
  assert.match(html, /data-code-queue-steer="q&quot;2"/, 'ids are attribute-escaped');
  assert.ok(!html.includes('<b>keep</b>'), 'message text is escaped');
  assert.match(html, /also &lt;b&gt;keep&lt;\/b&gt; it in the top right</, 'newlines fold onto the one line');
  assert.match(html, /title="also &lt;b&gt;keep&lt;\/b&gt;\nit in the top right"/, 'the full text stays on hover');
  assert.match(html, /aria-label="Remove queued message: make the toggle a sun and moon icon"/);
  assert.match(html, /class="tc-code-status"[^>]*hidden/, 'no status, no status line');
  assert.ok(!/<button[^>]*disabled/.test(html), 'idle items are live');
});

check('extrasBusyAndInertItems', () => {
  const html = composer.extrasHtml({ esc, queued: [{ id: 'q1', message: 'one', busy: true }, { message: 'no id' }, { id: 'q3', message: 'three' }], steerDisabled: false });
  assert.match(html, /tc-code-queue-item is-busy/);
  assert.match(html, /data-code-queue-steer="q1"[^>]*disabled>Steering…</);
  assert.match(html, /data-code-queue-steer=""[^>]*disabled>Steer</, 'an item with no id still shows, inert');
  assert.match(html, /data-code-queue-steer="q3"[^>]*>Steer</);
  assert.ok(!/data-code-queue-steer="q3"[^>]*disabled/.test(html));
  const locked = composer.extrasHtml({ esc, queued: [{ id: 'q3', message: 'three' }], steerDisabled: true });
  assert.match(locked, /data-code-queue-steer="q3"[^>]*disabled/, 'steerDisabled holds every Steer');
  assert.ok(!/data-code-queue-remove="q3"[^>]*disabled/.test(locked), '✕ still works while a steer is in flight');
});

check('extrasStatusLine', () => {
  const html = composer.extrasHtml({ esc, queued: [], status: { words: 'Thomas is editing', tone: 'working', stepText: 'Step 4 of 5', elapsed: 72000 } });
  assert.match(html, /class="tc-code-queue"[^>]*hidden/);
  assert.match(html, /data-tone="working"/);
  assert.match(html, />Thomas is editing</);
  assert.match(html, />Step 4 of 5 · 1m 12s</);
  const paused = composer.extrasHtml({ esc, status: { words: 'Paused', tone: 'paused', elapsed: '2m 3s' } });
  assert.match(paused, /data-tone="paused"/);
  assert.match(paused, />2m 3s</, 'no step yet: just the clock');
  const odd = composer.extrasHtml({ esc, status: { words: '<i>x</i>', tone: 'confused' } });
  assert.match(odd, /data-tone="idle"/, 'an unknown tone is idle, never an attribute injection');
  assert.match(odd, /&lt;i&gt;x&lt;\/i&gt;/);
  assert.match(odd, /data-code-status-meta hidden/, 'no step and no clock: the right side is hidden');
  // One escaper on the page (unified_code_mode.js's), handed in: the module
  // keeps no copy of its own, so drawing without it is refused, not guessed.
  assert.throws(() => composer.extrasHtml({ queued: [{ id: 1, message: '<x>' }] }), /needs ctx\.esc/);
});

check('theStatusLineHasNoStopButton', () => {
  // The primary button is the control; the line carries words and the clock only.
  const live = composer.extrasHtml({ esc, status: { words: 'Paused', tone: 'paused', stoppable: true, stopping: true } });
  assert.ok(!/data-code-stop|status-stop|<button/.test(live), 'no button on the status line');
  assert.match(live, /data-code-status-words[^>]*>Paused</);
});

check('bindReportsClicksById', () => {
  let listeners = 0, listener = null;
  const root = { addEventListener(type, fn) { if (type === 'click') { listeners += 1; listener = fn; } }, contains: () => true };
  const target = (attrs, disabled = false) => ({
    disabled,
    hasAttribute: name => name in attrs,
    getAttribute: name => (name in attrs ? attrs[name] : null),
    closest() { return Object.keys(attrs).length ? this : null; },
  });
  const seen = [];
  composer.bind(root, { onSteer: id => seen.push(['steer', id]), onRemove: id => seen.push(['remove', id]) });
  listener({ target: target({ 'data-code-queue-steer': 'q1' }) });
  listener({ target: target({ 'data-code-queue-remove': 'q2' }) });
  listener({ target: target({ 'data-code-queue-steer': 'q3' }, true) });
  listener({ target: target({}) });
  listener({ target: { nodeType: 3 } });
  assert.deepEqual(seen, [['steer', 'q1'], ['remove', 'q2']]);
  // Re-binding swaps the handlers and never stacks a second listener.
  const later = [];
  composer.bind(root, { onSteer: id => later.push(id) });
  listener({ target: target({ 'data-code-queue-steer': 'q9' }) });
  listener({ target: target({ 'data-code-queue-remove': 'q9' }) });
  assert.equal(listeners, 1);
  assert.deepEqual(later, ['q9']);
  composer.bind(null, {});
});

// ---- 2. syncDynamic asks the composer in Build ----
function viewHarness() {
  const button = fakeButton('Send');
  const icon = { className: 'ph ph-arrow-up', closest: selector => (selector === '#tc-send' ? button : null) };
  const shellProps = new Map();
  let mode = 'code', busy = false, attachmentBusy = null;
  const ctx = {
    window: { ThomasChatMediaBridge: { syncContext() {} }, ThomasUnifiedModes: { mode: () => mode, isBusy: () => busy } },
    document: { getElementById: () => null },
    state: { input: '' },
    sendIconEl: icon,
    shell: { style: { setProperty: (key, value) => { shellProps.set(key, value); } } },
    syncAttachmentState(value) { attachmentBusy = value; },
    isChatBusy: () => false,
  };
  installScript(ctx, htmlPath, 'unified_code_composer.js');
  installFeature(ctx, htmlPath, 'message_view', ['syncDynamic']);
  return {
    ctx, button, icon, shellProps,
    set mode(value) { mode = value; }, set busy(value) { busy = value; },
    get attachmentBusy() { return attachmentBusy; },
  };
}

check('syncDynamicBuildReadsRunControls', () => {
  const h = viewHarness();
  h.busy = true;
  let controls = { running: true, paused: false, canPause: true };
  h.ctx.window.ThomasCodeMode = { runControls: () => controls };
  h.ctx.syncDynamic();
  assert.equal(h.icon.className, 'ph ph-pause');
  assert.equal(h.button.dataset.primary, 'pause');
  assert.equal(h.attachmentBusy, true, 'attachments still lock while the run is busy');
  controls = { running: true, paused: true, canPause: true };
  h.ctx.syncDynamic();
  assert.equal(h.icon.className, 'ph ph-play');
  h.ctx.state.input = 'make the toggle a sun and moon icon';
  h.ctx.syncDynamic();
  assert.equal(h.button.dataset.primary, 'send');
  assert.equal(h.button.props.get('--send-bg'), 'var(--c-accent)');
  h.ctx.state.input = '   ';
  controls = { running: true, paused: false, canPause: false };
  h.ctx.syncDynamic();
  assert.equal(h.button.dataset.primary, 'stop', 'the Claude Code lead cannot pause');
  controls = { running: false, paused: false, canPause: false };
  h.ctx.syncDynamic();
  assert.equal(h.button.dataset.primary, 'send');
  assert.equal(h.button.getAttribute('aria-disabled'), 'true');
  assert.equal(h.shellProps.size, 0, 'Build never writes the shell-wide Chat send look');
});

check('syncDynamicBuildWithoutRunControlsKeepsStop', () => {
  const h = viewHarness();
  h.busy = true;
  h.ctx.syncDynamic();
  assert.equal(h.button.dataset.primary, 'stop', 'before the integrator adds runControls, busy means Stop');
  assert.equal(h.icon.className, 'ph ph-stop');
  h.busy = false;
  h.ctx.syncDynamic();
  assert.equal(h.button.dataset.primary, 'send');
});

check('syncDynamicLeavingBuildRestoresChat', () => {
  const h = viewHarness();
  h.busy = true;
  h.ctx.window.ThomasCodeMode = { runControls: () => ({ running: true, paused: false, canPause: true }) };
  h.ctx.syncDynamic();
  assert.equal(h.button.dataset.primary, 'pause');
  h.mode = 'chat';
  h.ctx.syncDynamic();
  assert.equal('primary' in h.button.dataset, false);
  assert.equal(h.button.getAttribute('title'), 'Send');
  assert.equal(h.button.props.size, 0);
  assert.equal(h.icon.className, 'ph ph-stop', 'Chat keeps its own busy-and-empty Stop');
  assert.equal(h.shellProps.get('--send-bg'), 'var(--c-accent)');
  // Work is unchanged too.
  h.mode = 'work'; h.busy = false; h.ctx.state.input = '';
  h.ctx.syncDynamic();
  assert.equal(h.icon.className, 'ph ph-arrow-up');
  assert.equal('primary' in h.button.dataset, false);
});

check('syncDynamicWithoutTheModule', () => {
  const h = viewHarness();
  delete h.ctx.window.ThomasCodeComposer;
  h.busy = true;
  h.ctx.syncDynamic();
  assert.equal(h.icon.className, 'ph ph-stop', 'a page without the module keeps the old button');
  assert.equal(h.shellProps.get('--send-bg'), 'var(--c-accent)');
});

// ---- 3. the click goes to the run in Build ----
function clickHarness(mode) {
  let click = null, keydown = null;
  const log = [];
  const noop = () => {};
  const ctx = {
    window: { ThomasUnifiedModes: { mode: () => mode, stop: () => { log.push('modeStop'); return true; } } },
    state: { input: '' },
    isChatBusy: () => true,
    stopChat: () => { log.push('stopChat'); },
    send: () => { log.push('send'); },
    bindLibraryActions: noop,
    inputEl: { addEventListener: (type, handler) => { if (type === 'keydown') keydown = handler; } },
    document: { addEventListener: noop, querySelectorAll: () => [],
      getElementById: id => ({ addEventListener: (_event, handler) => { if (id === 'tc-send') click = handler; } }) },
  };
  installFeature(ctx, htmlPath, 'shell_bindings');
  const key = (name, extra = {}) => {
    const event = { key: name, shiftKey: false, isComposing: false, prevented: false, preventDefault() { this.prevented = true; }, ...extra };
    keydown(event);
    return event.prevented;
  };
  return { ctx, log, click: () => click(), key };
}

check('escapeInAnEmptyBuildComposerStopsTheLiveRun', () => {
  const h = clickHarness('code');
  let live = true;
  h.ctx.window.ThomasCodeMode = { stopRun: () => { h.log.push('stopRun'); return live; } };
  assert.equal(h.key('Escape'), true, 'a live run (working or paused) stops');
  assert.deepEqual(h.log, ['stopRun']);
  live = false;
  assert.equal(h.key('Escape'), false, 'nothing live: Escape is left alone');
  h.log.length = 0;
  h.ctx.state.input = 'half a thought';
  h.key('Escape');
  h.ctx.state.input = '';
  h.key('Escape', { isComposing: true });
  h.ctx.state.toolsMenuOpen = true;
  h.key('Escape');
  assert.deepEqual(h.log, [], 'typed text, an IME and an open menu keep their Escape');
  h.ctx.state.toolsMenuOpen = false;
  const chat = clickHarness('chat');
  chat.ctx.window.ThomasCodeMode = { stopRun: () => { chat.log.push('stopRun'); return true; } };
  chat.key('Escape');
  assert.deepEqual(chat.log, [], 'Chat never stops a Build run');
  assert.equal(h.key('Enter'), true);
  assert.deepEqual(h.log, ['send'], 'Enter still sends');
});

check('emptyBuildClickGoesToPrimaryAction', () => {
  const h = clickHarness('code');
  h.ctx.window.ThomasCodeMode = { primaryAction: () => { h.log.push('primary'); return Promise.resolve(false); } };
  h.click();
  assert.deepEqual(h.log, ['primary'], 'Pause/Resume/Stop never falls through to a stop');
  h.ctx.state.input = 'also keep it in the top right';
  h.click();
  assert.deepEqual(h.log, ['primary', 'send'], 'typed text always sends (and queues mid-run)');
});

check('emptyBuildClickFallsBackToModeStop', () => {
  const h = clickHarness('code');
  h.click();
  assert.deepEqual(h.log, ['modeStop'], 'without primaryAction the old stop path stands');
  const work = clickHarness('work');
  work.ctx.window.ThomasCodeMode = { primaryAction: () => { work.log.push('primary'); } };
  work.click();
  assert.deepEqual(work.log, ['modeStop'], 'Work keeps its own stop');
  const chat = clickHarness('chat');
  chat.ctx.window.ThomasCodeMode = { primaryAction: () => { chat.log.push('primary'); } };
  chat.click();
  assert.deepEqual(chat.log, ['stopChat'], 'Chat keeps its own stop');
});

process.stdout.write(`${JSON.stringify(checks)}\n`);
