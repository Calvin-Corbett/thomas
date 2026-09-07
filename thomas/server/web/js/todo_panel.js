/* The checklist Thomas keeps while it works (the todo.write tool).
 *
 * Frontier parity with Claude Code's TodoWrite: for multi-step work the
 * model writes its plan, marks one step in progress and ticks steps off,
 * and the person sees that instead of a spinner. Polls GET /api/chat/todos
 * while the page is visible and renders one card above the composer; the
 * card disappears when the list is cleared. Self-contained: nothing in
 * chat.html changes. The pure formatter is on window.ThomasTodoPanel for
 * the node harness (tests/web_node/todo_panel.mjs).
 */
(function () {
  'use strict';

  var GLYPH = { pending: '○', in_progress: '◐', done: '●' };

  // Progress line for a list record: "2 of 4 done · now: Compute turnaround".
  function summary(record) {
    var items = (record && Array.isArray(record.items)) ? record.items : [];
    if (!items.length) return '';
    var done = items.filter(function (i) { return i.status === 'done'; }).length;
    var now = items.filter(function (i) { return i.status === 'in_progress'; })[0];
    var line = done + ' of ' + items.length + ' done';
    if (now) line += ' · now: ' + now.text;
    return line;
  }

  // The card's lines, one per item, glyph first.
  function lines(record) {
    var items = (record && Array.isArray(record.items)) ? record.items : [];
    return items.map(function (i) { return (GLYPH[i.status] || GLYPH.pending) + ' ' + String(i.text || ''); });
  }

  var POLL_MS = 1500;
  var MAX_POLL_MS = 30000;

  // Next wait after a poll: the base on success, doubled to thirty seconds on failure.
  function nextDelay(current, ok) {
    if (ok) return POLL_MS;
    return Math.min(MAX_POLL_MS, Math.max(POLL_MS, Number(current) || 0) * 2);
  }

  var core = { summary: summary, lines: lines, GLYPH: GLYPH, nextDelay: nextDelay };
  if (typeof window !== 'undefined') window.ThomasTodoPanel = core;
  if (typeof document === 'undefined') return;
  if (window.__thomasTodoPanel) return;
  window.__thomasTodoPanel = true;

  var API = '/api/chat/todos';
  var delay = POLL_MS;
  var lastKey = '';

  function esc(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function anchor() {
    var box = document.querySelector('textarea[placeholder^="Message Thomas"], textarea[aria-label^="Message Thomas"]');
    if (!box) return null;
    return box.closest('form') || box.parentElement;
  }

  function host() {
    var el = document.getElementById('thomas-todo-host');
    if (el) return el;
    var at = anchor();
    if (!at || !at.parentElement) return null;
    el = document.createElement('div');
    el.id = 'thomas-todo-host';
    el.setAttribute('role', 'region');
    el.setAttribute('aria-label', "Thomas's checklist");
    el.hidden = true;
    at.parentElement.insertBefore(el, at);
    return el;
  }

  function styleOnce() {
    if (document.getElementById('thomas-todo-style')) return;
    var style = document.createElement('style');
    style.id = 'thomas-todo-style';
    style.textContent = [
      '#thomas-todo-host{margin:0 0 10px}',
      '.tc-todo{border:1px solid var(--border,rgba(127,127,127,.35));border-radius:12px;padding:10px 14px;',
      'background:var(--surface-2,rgba(127,127,127,.08));font:inherit;color:inherit}',
      '.tc-todo-head{display:flex;justify-content:space-between;gap:12px;font-weight:600;margin:0 0 6px}',
      '.tc-todo-head small{font-weight:400;opacity:.7}',
      '.tc-todo ol{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:3px}',
      '.tc-todo li{font-size:.95em}',
      '.tc-todo li[data-status="done"]{opacity:.55;text-decoration:line-through}',
      '.tc-todo li[data-status="in_progress"]{font-weight:600}',
    ].join('');
    document.head.appendChild(style);
  }

  function paint(record) {
    var el = host();
    if (!el) return;
    if (!record) { el.hidden = true; el.innerHTML = ''; lastKey = ''; return; }
    var key = JSON.stringify(record);
    if (key === lastKey) return;
    lastKey = key;
    styleOnce();
    var items = Array.isArray(record.items) ? record.items : [];
    el.innerHTML = '<div class="tc-todo"><div class="tc-todo-head"><span>' + esc(record.title || 'Plan') + '</span><small>' + esc(summary(record)) + '</small></div><ol>'
      + items.map(function (i) { return '<li data-status="' + esc(i.status) + '">' + esc(GLYPH[i.status] || GLYPH.pending) + ' ' + esc(i.text) + '</li>'; }).join('')
      + '</ol></div>';
    el.hidden = false;
  }

  function poll() {
    if (document.hidden) return Promise.resolve();
    // Only this chat's checklist; with no chat open there is nothing to show.
    var sid = window.ThomasChatSession ? window.ThomasChatSession.current() : '';
    if (!sid) { paint(null); return Promise.resolve(); }
    return fetch(API + '?session_id=' + encodeURIComponent(sid), { cache: 'no-store' })
      .then(function (res) { delay = nextDelay(delay, res.ok); return res.ok ? res.json() : null; })
      .then(function (data) {
        var todos = data && Array.isArray(data.todos) ? data.todos : [];
        paint(todos[0] || null);
      })
      .catch(function () { delay = nextDelay(delay, false); /* server away; wait longer */ });
  }

  function tick() { poll().finally(function () { setTimeout(tick, delay); }); }
  function start() { tick(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
