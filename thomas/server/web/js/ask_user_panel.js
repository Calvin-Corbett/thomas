/* Questions Thomas asks the person mid-run (the ask_user tool).
 *
 * Frontier parity with Claude Code's AskUserQuestion and ChatGPT's clarifying
 * prompts: the run pauses, the person taps an option (or types), the answer
 * goes back as the tool's result and the same run continues.
 *
 * Self-contained: polls GET /api/chat/questions while the page is visible and
 * renders a card above the composer; POST /api/chat/questions/{id}/answer on
 * a choice. Injected by the chat page handler; needs nothing from chat.html.
 */
(function () {
  'use strict';

  const POLL_MS = 1500;
  const MAX_POLL_MS = 30000;

  // Next wait after a poll: back to the base on success, doubled up to
  // thirty seconds on failure, so a server that is away is not asked every
  // 1.5 s (3,179 refused-connection console errors on 2026-09-05).
  function nextDelay(current, ok) {
    if (ok) return POLL_MS;
    return Math.min(MAX_POLL_MS, Math.max(POLL_MS, Number(current) || 0) * 2);
  }

  if (typeof window !== 'undefined') window.ThomasAskUserPanel = { nextDelay: nextDelay };
  if (typeof document === 'undefined') return;
  if (window.__thomasAskUserPanel) return;
  window.__thomasAskUserPanel = true;
  const API = '/api/chat/questions';
  const rendered = new Map(); // question id -> card element

  function esc(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function anchor() {
    const box = document.querySelector('textarea[placeholder^="Message Thomas"], textarea[aria-label^="Message Thomas"]');
    if (!box) return null;
    return box.closest('form') || box.parentElement;
  }

  function host() {
    let el = document.getElementById('thomas-ask-user-host');
    if (el) return el;
    const at = anchor();
    if (!at || !at.parentElement) return null;
    el = document.createElement('div');
    el.id = 'thomas-ask-user-host';
    el.setAttribute('role', 'region');
    el.setAttribute('aria-label', 'Thomas has a question');
    at.parentElement.insertBefore(el, at);
    return el;
  }

  function styleOnce() {
    if (document.getElementById('thomas-ask-user-style')) return;
    const style = document.createElement('style');
    style.id = 'thomas-ask-user-style';
    style.textContent = [
      '#thomas-ask-user-host{display:flex;flex-direction:column;gap:10px;margin:0 0 10px}',
      '.tc-ask{border:1px solid var(--border,rgba(127,127,127,.35));border-radius:12px;padding:12px 14px;',
      'background:var(--surface-2,rgba(127,127,127,.08));font:inherit;color:inherit}',
      '.tc-ask-q{font-weight:600;margin:0 0 8px}',
      '.tc-ask-opts{display:flex;flex-wrap:wrap;gap:8px}',
      '.tc-ask-opt{border:1px solid var(--border,rgba(127,127,127,.45));border-radius:999px;padding:6px 12px;',
      'background:transparent;color:inherit;cursor:pointer;font:inherit}',
      '.tc-ask-opt[aria-pressed="true"]{background:var(--accent,#4f7cff);color:#fff;border-color:transparent}',
      '.tc-ask-opt small{display:block;opacity:.7;font-size:.85em}',
      '.tc-ask-free{display:flex;gap:8px;margin-top:8px}',
      '.tc-ask-free input{flex:1;font:inherit;padding:6px 10px;border-radius:8px;border:1px solid var(--border,rgba(127,127,127,.45));background:transparent;color:inherit}',
      '.tc-ask-submit{margin-top:8px}',
      '.tc-ask-note{opacity:.7;font-size:.85em;margin-top:6px}',
    ].join('');
    document.head.appendChild(style);
  }

  async function answer(question, selected, other, card) {
    card.querySelectorAll('button,input').forEach((el) => { el.disabled = true; });
    try {
      // The answer names the chat it comes from; the server refuses another chat's.
      const sid = window.ThomasChatSession ? window.ThomasChatSession.current() : '';
      const res = await fetch(`${API}/${encodeURIComponent(question.id)}/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ selected, other: other || '', session_id: sid }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      card.remove();
      rendered.delete(question.id);
    } catch (err) {
      card.querySelectorAll('button,input').forEach((el) => { el.disabled = false; });
      const note = card.querySelector('.tc-ask-note');
      if (note) note.textContent = 'That did not reach Thomas. Try again.';
      console.error('ask_user answer failed', err);
    }
  }

  function render(question) {
    const where = host();
    if (!where || rendered.has(question.id)) return;
    styleOnce();
    const card = document.createElement('div');
    card.className = 'tc-ask';
    card.dataset.questionId = question.id;
    const opts = Array.isArray(question.options) ? question.options : [];
    card.innerHTML = `<p class="tc-ask-q">${esc(question.question)}</p>`
      + `<div class="tc-ask-opts" role="group" aria-label="Options">`
      + opts.map((o) => `<button type="button" class="tc-ask-opt" data-label="${esc(o.label)}" aria-pressed="false">${esc(o.label)}${o.description ? `<small>${esc(o.description)}</small>` : ''}</button>`).join('')
      + '</div>'
      + (question.allow_free_text ? '<div class="tc-ask-free"><input type="text" aria-label="Your answer" placeholder="Or type an answer…" /><button type="button" class="tc-ask-opt tc-ask-send">Send</button></div>' : '')
      + (question.multi_select ? '<button type="button" class="tc-ask-opt tc-ask-submit">Done choosing</button>' : '')
      + '<p class="tc-ask-note">Thomas is waiting for this before it continues.</p>';
    const chosen = new Set();
    card.querySelectorAll('.tc-ask-opt[data-label]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const label = btn.dataset.label;
        if (question.multi_select) {
          if (chosen.has(label)) { chosen.delete(label); btn.setAttribute('aria-pressed', 'false'); }
          else { chosen.add(label); btn.setAttribute('aria-pressed', 'true'); }
          return;
        }
        btn.setAttribute('aria-pressed', 'true');
        answer(question, [label], '', card);
      });
    });
    const submit = card.querySelector('.tc-ask-submit');
    if (submit) submit.addEventListener('click', () => { if (chosen.size) answer(question, Array.from(chosen), '', card); });
    const send = card.querySelector('.tc-ask-send');
    if (send) {
      const input = card.querySelector('.tc-ask-free input');
      const go = () => { const text = (input.value || '').trim(); if (text) answer(question, Array.from(chosen), text, card); };
      send.addEventListener('click', go);
      input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); go(); } });
    }
    where.appendChild(card);
    rendered.set(question.id, card);
  }

  let delay = POLL_MS;

  async function poll() {
    if (document.hidden) return;
    try {
      // Only this chat's questions; with no chat open there is nothing to ask for.
      const sid = window.ThomasChatSession ? window.ThomasChatSession.current() : '';
      if (!sid) { delay = nextDelay(delay, true); return; }
      const res = await fetch(`${API}?session_id=${encodeURIComponent(sid)}`, { cache: 'no-store' });
      delay = nextDelay(delay, res.ok);
      if (!res.ok) return;
      const data = await res.json();
      const open = Array.isArray(data.questions) ? data.questions : [];
      const openIds = new Set(open.map((q) => q.id));
      for (const [id, card] of rendered) {
        if (!openIds.has(id)) { card.remove(); rendered.delete(id); }
      }
      open.forEach(render);
    } catch (_err) {
      delay = nextDelay(delay, false); // server away; wait longer before asking again
    }
  }

  function tick() {
    poll().finally(() => setTimeout(tick, delay));
  }

  function start() { tick(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();

  window.ThomasAskUserPanel = { poll, render };
})();
