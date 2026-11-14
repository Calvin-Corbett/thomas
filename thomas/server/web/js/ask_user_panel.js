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
  const IDLE_MS = 15000;  // how rarely a hidden tab re-checks whether it is back

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
    const box = document.querySelector('#tc-agent-chat-input, #tc-input, textarea[placeholder^="Message Thomas"], textarea[aria-label^="Message Thomas"]');
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
      // The setting card wears Thomas's accent so an ask to raise a limit is
      // never mistaken for an ordinary question.
      '.tc-setting{border-color:var(--c-accent,var(--accent,#7c5cff));border-left-width:4px;',
      'background:linear-gradient(180deg,color-mix(in srgb,var(--c-accent,var(--accent,#7c5cff)) 10%,transparent),transparent)}',
      '.tc-setting-kicker{margin:0 0 4px;font-size:10.5px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;',
      'color:var(--c-accent,var(--accent,#7c5cff))}',
      '.tc-setting-what{margin:0 0 6px;opacity:.8;font-size:.9em}',
      '.tc-setting-why{margin:0 0 8px;font-size:.92em}',
      '.tc-setting-why span{font-weight:600;margin-right:6px}',
      '.tc-setting-lock{margin:0 0 8px;font-size:.88em;font-weight:600}',
      '.tc-setting-yes{background:var(--c-accent,var(--accent,#7c5cff));color:#fff;border-color:transparent}',
      '.tc-card-fields{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;margin:0 0 8px;font-size:.92em}',
      '.tc-card-fields dt{font-weight:600;opacity:.8}',
      '.tc-card-fields dd{margin:0;overflow-wrap:anywhere}',
      '.tc-card .tc-ask-opt{text-align:left}',
      '.tc-card-pair{margin:0 0 8px;font-size:.92em}',
      '.tc-card-pair strong{font-family:ui-monospace,Consolas,monospace;font-size:1.25em;letter-spacing:.12em;',
      'padding:2px 8px;border-radius:6px;border:1px solid var(--c-accent,var(--accent,#7c5cff))}',
      '.tc-card-diff{margin:0 0 8px;max-height:16em;overflow:auto;padding:8px 10px;border-radius:8px;',
      'font-family:ui-monospace,Consolas,monospace;font-size:.82em;line-height:1.4;white-space:pre;',
      'background:var(--surface-3,rgba(127,127,127,.12));border:1px solid var(--border,rgba(127,127,127,.3))}',
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

  // --- Thomas asking to change one of his own settings --------------------
  // Owner direction 2026-09-22: announce it on a card -- what, why, "it will
  // require a password" -- and let the person decide. Yes on a raised limit
  // goes to the server, which shows the one Thomas password prompt and
  // enforces the answer (thomas/server/dial_elevation.py). This card cannot
  // change anything the server would not honour; it is the announcement, the
  // server is the wall. The answer labels match thomas/tools/setting_request.py.
  const SETTING_YES = 'Yes';
  const SETTING_NO = 'No';
  const SETTING_PASSWORD_REFUSED = 'Password not approved';

  function dialField(key) {
    const prefs = window.ThomasChatPreferences;
    const fields = prefs && Array.isArray(prefs.DIAL_FIELDS) ? prefs.DIAL_FIELDS : [];
    return fields.filter((f) => f.key === key)[0] || null;
  }

  function storedDials() {
    try { return JSON.parse(localStorage.getItem('thomas_dials') || '{}') || {}; } catch (_) { return {}; }
  }

  function applyDial(key, value) {
    const dials = storedDials();
    dials[key] = key === 'autonomy' ? parseInt(value, 10) : value;
    try { localStorage.setItem('thomas_dials', JSON.stringify(dials)); } catch (_) { /* storage off */ }
    // The composer (chat_composer_panels.js) owns the live dials; tell it.
    window.dispatchEvent(new CustomEvent('thomas:dial-set', { detail: { key: key, value: dials[key] } }));
  }

  function renderSetting(question, where) {
    const d = question.details || {};
    const field = dialField(d.client_key);
    const opt = field ? field.opts.filter((o) => String(o[0]) === String(d.value))[0] : null;
    const elevates = !!(opt && opt[3] && opt[3].elevates);
    const now = field ? field.opts.filter((o) => String(o[0]) === String(storedDials()[d.client_key]))[0] : null;
    const card = document.createElement('div');
    card.className = 'tc-ask tc-setting';
    card.dataset.questionId = question.id;
    card.innerHTML = '<p class="tc-setting-kicker">Thomas wants to change a setting</p>'
      + `<p class="tc-ask-q">${esc(d.label)}: ${now ? `${esc(now[1])} &rarr; ` : ''}<strong>${esc(d.value_label)}</strong></p>`
      + (opt && opt[2] ? `<p class="tc-setting-what">${esc(opt[2])}</p>` : '')
      + `<p class="tc-setting-why"><span>Why</span>${esc(d.reason)}</p>`
      + (elevates ? '<p class="tc-setting-lock">Raising this asks for your Windows PIN or password next.</p>' : '')
      + '<div class="tc-ask-opts"><button type="button" class="tc-ask-opt tc-setting-yes">Yes, change it</button>'
      + '<button type="button" class="tc-ask-opt tc-setting-no">No</button></div>'
      + '<p class="tc-ask-note">Thomas is waiting for this before it continues.</p>';
    const note = card.querySelector('.tc-ask-note');
    card.querySelector('.tc-setting-yes').addEventListener('click', async () => {
      card.querySelectorAll('button').forEach((el) => { el.disabled = true; });
      if (elevates) {
        note.textContent = 'Waiting for your PIN or password…';
        let approved = false;
        try {
          const res = await fetch('/api/security/elevate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ dial: d.dial, value: d.value }),
          });
          const data = await res.json();
          approved = !!(data && data.approved);
        } catch (_) { approved = false; }
        if (!approved) { answer(question, [SETTING_PASSWORD_REFUSED], '', card); return; }
      }
      applyDial(d.client_key, d.value);
      answer(question, [SETTING_YES], '', card);
    });
    card.querySelector('.tc-setting-no').addEventListener('click', () => answer(question, [SETTING_NO], '', card));
    where.appendChild(card);
    rendered.set(question.id, card);
  }

  // --- A general card ---------------------------------------------------
  // Owner direction 2026-09-22: "Everything can become a card ... it can be
  // dynamic, it can be anything you want it to be." A card is a spec: a
  // kicker, a question, labelled fields, a note, and options. An option marked
  // requires_password is a wall, not a button: the server runs the one Thomas
  // password prompt when it is picked, and only records the answer if Windows
  // accepts the PIN or password (thomas/core/user_questions.py refuses it
  // otherwise). The first card built on this is the protected-file approval.
  async function answerCard(question, label, card) {
    const note = card.querySelector('.tc-ask-note');
    const buttons = card.querySelectorAll('button');
    buttons.forEach((el) => { el.disabled = true; });
    const opt = (question.options || []).filter((o) => o.label === label)[0] || {};
    if (opt.requires_password) note.textContent = 'Waiting for your PIN or password…';
    try {
      const sid = window.ThomasChatSession ? window.ThomasChatSession.current() : '';
      const res = await fetch(`${API}/${encodeURIComponent(question.id)}/answer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ selected: [label], other: '', session_id: question.kind === 'settings-control' ? question.session_id : sid }),
      });
      if (res.ok) {
        const result = await res.json();
        const instruction = result.instruction;
        if (instruction && instruction.type === 'browser_setting') {
          applyDial(instruction.id, instruction.value);
        }
        if (instruction && instruction.type === 'navigate') {
          note.textContent = 'Find it in ' + instruction.location;
          buttons.forEach((el) => { el.disabled = true; });
          return;
        }
        card.remove(); rendered.delete(question.id); return;
      }
      let data = {};
      try { data = await res.json(); } catch (_) { data = {}; }
      note.textContent = (data && data.error) || 'That did not reach Thomas. Try again.';
    } catch (_err) {
      note.textContent = 'That did not reach Thomas. Try again.';
    }
    buttons.forEach((el) => { el.disabled = false; });
  }

  function renderCard(question, where) {
    const d = question.details || {};
    const fields = Array.isArray(d.fields) ? d.fields : [];
    const opts = Array.isArray(question.options) ? question.options : [];
    const card = document.createElement('div');
    card.className = 'tc-ask tc-setting tc-card';
    card.dataset.questionId = question.id;
    // A trusted card (thomas/tools/trusted_card.py) carries the pairing code your
    // Windows prompt will show, and the real diff. Both are data and escaped like
    // everything else here; the code is set apart so it is easy to compare.
    card.innerHTML = (d.kicker ? `<p class="tc-setting-kicker">${esc(d.kicker)}</p>` : '')
      + `<p class="tc-ask-q">${esc(question.question)}</p>`
      + (d.pairing_code
        ? `<p class="tc-card-pair">Pairing code <strong>${esc(d.pairing_code)}</strong></p>`
        : '')
      + (fields.length
        ? '<dl class="tc-card-fields">' + fields.map((f) => `<dt>${esc(f.label)}</dt><dd>${esc(f.value)}</dd>`).join('') + '</dl>'
        : '')
      + (d.excerpt ? `<pre class="tc-card-diff">${esc(d.excerpt)}</pre>` : '')
      + (d.note ? `<p class="tc-setting-lock">${esc(d.note)}</p>` : '')
      + '<div class="tc-ask-opts" role="group" aria-label="Options">'
      + opts.map((o, i) => `<button type="button" class="tc-ask-opt${o.requires_password && i === 0 ? ' tc-setting-yes' : ''}" data-label="${esc(o.label)}">`
        + `${o.requires_password ? '🔒 ' : ''}${esc(o.label)}`
        + `${o.description ? `<small>${esc(o.description)}${o.requires_password ? ' Asks for your PIN.' : ''}</small>` : ''}</button>`).join('')
      + '</div>'
      // A mirror of something decided elsewhere (the Windows sign-in) holds nothing up.
      + (d.waits === false ? '' : '<p class="tc-ask-note">Thomas is waiting for this before it continues.</p>');
    card.querySelectorAll('.tc-ask-opt[data-label]').forEach((btn) => {
      btn.addEventListener('click', () => answerCard(question, btn.dataset.label, card));
    });
    where.appendChild(card);
    rendered.set(question.id, card);
  }

  function render(question) {
    const where = host();
    if (!where || rendered.has(question.id)) return;
    styleOnce();
    if (question.kind === 'setting_change') { renderSetting(question, where); return; }
    if (question.kind === 'card' || question.kind === 'settings-control') { renderCard(question, where); return; }
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

  const paused = () => !!(window.ThomasDocActivity && window.ThomasDocActivity.isPaused());

  async function poll() {
    // A hidden tab is still a live document; asking on its behalf is work
    // nobody can see. It refreshes the moment the tab is shown again.
    if (paused()) return;
    try {
      // Only this chat's questions; with no chat open there is nothing to ask for.
      const sid = window.ThomasChatSession ? window.ThomasChatSession.current() : '';
      const settingsRes = await fetch('/api/settings/index/cards?session_id=' + encodeURIComponent(sid), { cache: 'no-store' });
      const settingsData = settingsRes.ok ? await settingsRes.json() : { questions: [] };
      if (!sid) { (settingsData.questions || []).forEach(render); delay = nextDelay(delay, true); return; }
      const res = await fetch(`${API}?session_id=${encodeURIComponent(sid)}`, { cache: 'no-store' });
      delay = nextDelay(delay, res.ok);
      if (!res.ok) return;
      const data = await res.json();
      const open = (Array.isArray(data.questions) ? data.questions : []).concat(settingsData.questions || []);
      const openIds = new Set(open.map((q) => q.id));
      for (const [id, card] of rendered) {
        if (!openIds.has(id)) { card.remove(); rendered.delete(id); }
      }
      open.forEach(render);
    } catch (_err) {
      delay = nextDelay(delay, false); // server away; wait longer before asking again
    }
  }

  let timer = null;
  function schedule(ms) { clearTimeout(timer); timer = setTimeout(tick, ms); }
  function tick() {
    poll().finally(() => schedule(paused() ? IDLE_MS : delay));
  }

  function start() {
    tick();
    // Shown again: refresh at once rather than waiting out the idle gap.
    if (window.ThomasDocActivity) {
      window.ThomasDocActivity.onChange((isPaused) => { if (!isPaused) schedule(0); });
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();

  window.ThomasAskUserPanel = { poll, render };
})();
