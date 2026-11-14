/* Attention cards: what Thomas wants you to see now, in the empty space left of the conversation.
 *
 * The page that is on screen asks GET /api/attention/cards and draws the open ones (attention_card_view.js draws
 * each). They sit in the gutter between the sidebar and the conversation, so they cover nothing you are reading.
 * Where there is no gutter (a narrow window, Build's file viewer open, a full-width workspace) they fold into one
 * small counter you press to see them. Drag a card's top edge to move the stack; double-click it to put it back.
 *
 * Every Chat, Build and Work tab is its own document and loads this file. Only the one you are looking at asks or
 * draws (doc_activity.js), so a card turns up on whichever tab you are on, once. With the attention row off the
 * route answers 404 and this goes quiet, asking again once a minute in case it is turned back on.
 */
(function () {
  'use strict';
  if (window.ThomasAttention || typeof document === 'undefined') return;
  const view = window.ThomasAttentionView;
  if (!view) return;

  const ASK_MS = 3000, QUIET_MS = 60000, MIN_GUTTER = 248, MAX_WIDTH = 340, POSITION_KEY = 'thomas_attention_offset_v1';
  // Read now: `currentScript` is only set while this file is first running, and the stylesheet is added later.
  const STAMP = ((document.currentScript && document.currentScript.src.match(/\?v=[^&]+/)) || [''])[0];
  const drawn = new Map(); // card id -> { node, signature }
  let cards = [], host = null, expanded = false, timer = null, offset = readOffset();

  function readOffset() {
    try { const saved = JSON.parse(localStorage.getItem(POSITION_KEY) || '{}'); return { x: Number(saved.x) || 0, y: Number(saved.y) || 0 }; }
    catch (error) { return { x: 0, y: 0 }; }
  }
  function saveOffset() { try { localStorage.setItem(POSITION_KEY, JSON.stringify(offset)); } catch (error) { /* not remembered, still moved */ } }

  // Not this document's turn: a hidden tab, or the home document while a tab is drawn over it.
  function resting() {
    const activity = window.ThomasDocActivity;
    if (activity && activity.isPaused()) return true;
    return !!document.querySelector('iframe.bt-doc.is-active.is-ready');
  }

  function ensureHost() {
    if (host) return host;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/static/css/attention_cards.css' + STAMP;
    document.head.appendChild(link);
    host = document.createElement('section');
    host.id = 'tc-attention';
    host.setAttribute('aria-label', 'Cards from Thomas');
    host.hidden = true;
    document.body.appendChild(host);
    host.addEventListener('click', onClick);
    host.addEventListener('submit', onSubmit);
    host.addEventListener('pointerdown', startDrag);
    host.addEventListener('dblclick', event => { if (event.target.closest('[data-attn-grip]') && !event.target.closest('button')) { offset = { x: 0, y: 0 }; saveOffset(); place(); } });
    window.addEventListener('resize', place);
    return host;
  }

  // The gutter: from the sidebar's right edge to the left edge of whatever holds the conversation in this mode.
  function gutter() {
    const left = edge('aside.tc-sidebar', 'right', 0);
    // Build's transcript box spans the whole width; its conversation sits in the same column as the composer, so
    // the composer's edge is the one that counts there.
    const columns = ['#tc-composer-rail', '#tc-thread', '.tc-work-home', '.tc-work-panel']
      .map(selector => edge(selector, 'left', null)).filter(value => value != null);
    const covered = ['#tc-ws-frame', '#tc-direct-frame'].some(selector => { const frame = document.querySelector(selector); return frame && frame.offsetParent !== null; });
    const right = columns.length && !covered ? Math.min.apply(null, columns) : left;
    const header = document.querySelector('main > header, #tc-header');
    return { left: Math.max(0, left), width: right - Math.max(0, left), top: (header ? header.getBoundingClientRect().bottom : 56) + 16 };
  }
  function edge(selector, side, fallback) {
    const node = document.querySelector(selector);
    if (!node || node.offsetParent === null) return fallback;
    const box = node.getBoundingClientRect();
    return box.width ? box[side] : fallback;
  }

  function place() {
    if (!host || host.hidden) return;
    const room = gutter();
    const compact = room.width < MIN_GUTTER;
    host.classList.toggle('is-compact', compact);
    host.classList.toggle('is-expanded', compact && expanded);
    const width = compact ? Math.min(MAX_WIDTH, window.innerWidth - 24) : Math.min(MAX_WIDTH, room.width - 24);
    const x = Math.min(Math.max(8, room.left + 12 + offset.x), Math.max(8, window.innerWidth - width - 8));
    const y = Math.min(Math.max(8, room.top + offset.y), Math.max(8, window.innerHeight - 80));
    host.style.width = `${width}px`;
    host.style.left = `${x}px`;
    host.style.top = `${y}px`;
    host.style.maxHeight = `${Math.max(120, window.innerHeight - y - 16)}px`;
    // The counter stays while there is no gutter: pressing it shows the cards, pressing it again folds them away.
    const pill = host.querySelector('[data-attn-pill]');
    if (compact && !pill) host.insertAdjacentHTML('afterbegin', view.pillHtml(cards.length));
    else if (pill && !compact) pill.remove();
    else if (pill) { pill.textContent = String(cards.length); pill.setAttribute('aria-expanded', expanded ? 'true' : 'false'); }
  }

  function draw() {
    ensureHost();
    const wanted = new Set(cards.map(card => String(card.id)));
    drawn.forEach((entry, id) => { if (!wanted.has(id)) { entry.node.remove(); drawn.delete(id); } });
    let before = host.querySelector('[data-attn-card]');
    cards.forEach(card => {
      const id = String(card.id), signature = view.signature(card), blocks = view.blocksSignature(card), held = drawn.get(id);
      const busy = held && held.node.contains(document.activeElement);
      if (!held || (held.signature !== signature && !busy)) {
        const shell = document.createElement('div');
        shell.innerHTML = view.cardHtml(card);
        const node = shell.firstElementChild;
        if (held) held.node.replaceWith(node); else host.insertBefore(node, before);
        drawn.set(id, { node, signature, blocks });
      } else {
        // Same widget, new readings: only its blocks are swapped, so it does not blink or jump every few seconds.
        const body = held.blocks !== blocks && held.node.querySelector('[data-attn-blocks]');
        if (body && window.ThomasAttentionWidgetView) { body.innerHTML = window.ThomasAttentionWidgetView.blocksHtml(card.blocks); held.blocks = blocks; }
        if (held.node !== before) host.insertBefore(held.node, before);
      }
      before = drawn.get(id).node.nextElementSibling;
    });
    host.hidden = cards.length === 0;
    if (!cards.length) expanded = false;
    place();
  }

  async function ask() {
    clearTimeout(timer);
    let wait = ASK_MS;
    if (!resting()) {
      try {
        const response = await fetch('/api/attention/cards', { cache: 'no-store' });
        if (response.status === 404) { cards = []; wait = QUIET_MS; draw(); }
        else if (response.ok) { const data = await response.json(); cards = Array.isArray(data.cards) ? data.cards : []; draw(); }
      } catch (error) { /* the server is restarting or away: ask again on the next turn */ }
    } else if (host) host.hidden = true;
    timer = setTimeout(ask, wait);
  }

  async function act(id, action, value) {
    const entry = drawn.get(String(id));
    try {
      const response = await fetch(`/api/attention/cards/${encodeURIComponent(id)}/act`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, value }) });
      // 410: it was already closed, on another tab. Either way it is closed, so it leaves this one too.
      if (!response.ok && response.status !== 410) throw new Error(`Thomas did not take that (${response.status}). Try again.`);
      cards = cards.filter(card => String(card.id) !== String(id));
      draw();
    } catch (error) {
      const note = entry && entry.node.querySelector('[data-attn-error]');
      if (note) { note.textContent = error && error.message ? error.message : 'Thomas did not take that. Try again.'; note.hidden = false; }
    }
  }

  // A switch on a widget: the row is turned and the widget stays open, redrawn from what the server answers.
  async function toggle(id, button) {
    const entry = drawn.get(String(id)), note = entry && entry.node.querySelector('[data-attn-error]');
    button.disabled = true;
    try {
      const value = { setting: button.getAttribute('data-attn-toggle'), on: button.getAttribute('aria-checked') !== 'true' };
      const response = await fetch(`/api/attention/cards/${encodeURIComponent(id)}/act`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'toggle', value }) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `Thomas did not switch that (${response.status}).`);
      if (note) note.hidden = true;
      if (data.card) { cards = cards.map(card => (String(card.id) === String(id) ? data.card : card)); draw(); }
    } catch (error) {
      if (note) { note.textContent = error && error.message ? error.message : 'Thomas did not switch that.'; note.hidden = false; }
      button.disabled = false;
    }
  }

  function onClick(event) {
    if (event.target.closest('[data-attn-pill]')) { expanded = !expanded; place(); return; }
    const card = event.target.closest('[data-attn-card]');
    if (!card) return;
    const id = card.getAttribute('data-attn-card');
    if (event.target.closest('[data-attn-dismiss]')) { void act(id, 'dismiss'); return; }
    const flip = event.target.closest('[data-attn-toggle]');
    if (flip) { if (!flip.disabled) void toggle(id, flip); return; }
    const option = event.target.closest('[data-attn-option]');
    if (!option || option.type === 'submit') return;
    const task = option.getAttribute('data-attn-open-task');
    if (task && window.ThomasCodeMode && window.ThomasCodeMode.openConversation) void window.ThomasCodeMode.openConversation(task);
    void act(id, 'choose', option.getAttribute('data-attn-option'));
  }

  function onSubmit(event) {
    const form = event.target.closest('[data-attn-reply]');
    if (!form) return;
    event.preventDefault();
    const words = String(form.elements.reply.value || '').trim();
    if (words) void act(form.closest('[data-attn-card]').getAttribute('data-attn-card'), 'reply', words);
  }

  function startDrag(event) {
    if (!event.target.closest('[data-attn-grip]') || event.target.closest('button') || event.button !== 0) return;
    const start = { x: event.clientX - offset.x, y: event.clientY - offset.y };
    const move = moved => { offset = { x: moved.clientX - start.x, y: moved.clientY - start.y }; place(); };
    const stop = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', stop); host.classList.remove('is-dragging'); saveOffset(); };
    host.classList.add('is-dragging');
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', stop);
    event.preventDefault();
  }

  // For the page's own use: a tab that is not on screen tells you its task ended, on the tab that is.
  async function show(spec) {
    try { await fetch('/api/attention/cards', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(spec) }); }
    catch (error) { /* a card that could not be shown is not worth an error of its own */ }
  }
  function taskEnded(task) {
    const activity = window.ThomasDocActivity;
    if (!task || !task.id || !activity || !activity.isPaused()) return;
    const name = String(task.title || 'A Build task').slice(0, 80);
    const good = task.status === 'completed' || task.status === 'ready' || task.status === 'noop';
    void show({
      kind: 'question', tone: good ? 'done' : 'warn', key: `task-${task.id}`, ttl_seconds: 900,
      title: good ? `Finished: ${name}` : `Needs you: ${name}`,
      body: good ? 'This task ended while you were on another tab.' : 'This task stopped before it finished, on a tab you are not looking at.',
      options: [{ id: 'open', label: 'Open it', open_task: String(task.id) }],
    });
  }

  window.ThomasAttention = { show, taskEnded, refresh: ask };
  if (window.ThomasDocActivity && window.ThomasDocActivity.onChange) window.ThomasDocActivity.onChange(ask);
  ask();
})();
