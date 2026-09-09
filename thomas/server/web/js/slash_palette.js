/* A "/" command palette in the composer (frontier parity: Claude Code, Codex, ChatGPT).
 *
 * Type "/" at the start of the message box and a list opens; arrow keys or
 * more letters narrow it; Enter runs the highlighted command; Escape closes.
 * Every command drives a control that already exists on the page, found by
 * its accessible label at run time, so the list never promises something the
 * page cannot do: a command whose control is missing is not shown.
 *
 * Pure core on window.ThomasSlashPalette (commands, match, resolve) so a
 * node test can drive it with a stub document; DOM wiring only when a real
 * document is present.
 */
(function () {
  'use strict';
  const COMMANDS = [
    { name: 'new', label: 'New chat', hint: 'start a fresh conversation', find: (d) => byLabel(d, ['New chat']) },
    { name: 'ask', label: 'Quick question', hint: 'a side chat, no full tab', find: (d) => byLabel(d, ['Quick question']) },
    { name: 'model', label: 'Switch model', hint: 'pick the model for this chat', find: (d) => byLabel(d, ['Switch model']) },
    { name: 'tools', label: 'Tools and AI settings', hint: 'effort, autonomy, file access, guardrails', find: (d) => byLabel(d, ['Tools']) },
    { name: 'files', label: 'Add files', hint: 'attach files to the message', find: (d) => byLabel(d, ['Add files']) },
    { name: 'voice', label: 'Voice input', hint: 'dictate the message', find: (d) => byLabel(d, ['Voice input']) },
    { name: 'settings', label: 'Settings', hint: 'open settings', find: (d) => byLabel(d, ['Settings']) },
    { name: 'export', label: 'Export this chat', hint: 'download the open chat as Markdown', find: (d) => currentChatRow(d) },
    { name: 'retry', label: 'Regenerate the last reply', hint: 'resend your last message', find: (d) => lastEditButton(d) },
    { name: 'schedules', label: 'Scheduled tasks', hint: 'settings > autonomy', find: (d) => byLabel(d, ['Settings']) },
    { name: 'fast', label: 'Fast replies on or off', hint: 'quicker, lighter replies for this browser', find: (d) => byLabel(d, ['Fast replies']) },
    // Always offered: it needs no control on the page (frontier parity: Claude Code /help).
    { name: 'help', label: 'Every / command', hint: 'what each command does', find: () => ({ help: true }) },
  ];

  function byLabel(doc, labels) {
    const buttons = Array.from(doc.querySelectorAll('button, [role="button"], a[href]'));
    for (const label of labels) {
      const want = label.toLowerCase();
      const hit = buttons.find((b) => {
        const aria = String(b.getAttribute && b.getAttribute('aria-label') || '').toLowerCase();
        const text = String(b.textContent || '').trim().toLowerCase();
        const title = String(b.getAttribute && b.getAttribute('title') || '').toLowerCase();
        return aria.startsWith(want) || text === want || title.startsWith(want);
      });
      if (hit) return hit;
    }
    return null;
  }

  function currentChatRow(doc) {
    return doc.querySelector('[data-history-id][aria-current]') || null;
  }

  function lastEditButton(doc) {
    const edits = Array.from(doc.querySelectorAll('button[data-msg-edit]'));
    return edits.length ? edits[edits.length - 1] : null;
  }

  function match(query, doc) {
    const q = String(query || '').replace(/^\//, '').trim().toLowerCase();
    const hits = COMMANDS.filter((c) => (!q || c.name.startsWith(q) || c.label.toLowerCase().includes(q)) && !!c.find(doc));
    // A name prefix outranks a label substring, so Enter runs what was typed:
    // "/he" used to run "Regenerate the last reply" ahead of /help.
    if (!q) return hits;
    return hits.filter((c) => c.name.startsWith(q)).concat(hits.filter((c) => !c.name.startsWith(q)));
  }

  function resolve(name, doc) {
    const command = COMMANDS.find((c) => c.name === name);
    if (!command) return null;
    const target = command.find(doc);
    if (!target) return null;
    if (name === 'export') {
      const id = target.dataset ? target.dataset.historyId : target.getAttribute('data-history-id');
      const title = target.dataset ? (target.dataset.historyTitle || '') : '';
      return { kind: 'open', url: `/api/chats/${encodeURIComponent(id)}/export?format=md&title=${encodeURIComponent(title)}` };
    }
    if (name === 'schedules') return { kind: 'open', url: '/settings#autonomy' };
    if (name === 'retry') return { kind: 'retry', target };
    if (name === 'help') return { kind: 'help', commands: COMMANDS.map((c) => ({ name: c.name, label: c.label, hint: c.hint })) };
    return { kind: 'click', target };
  }

  const core = { commands: COMMANDS, match, resolve };
  if (typeof window !== 'undefined') window.ThomasSlashPalette = core;
  if (typeof document === 'undefined' || !document.querySelector) return;
  if (window.__thomasSlashPaletteWired) return;
  window.__thomasSlashPaletteWired = true;

  let box = null;
  let index = 0;
  let items = [];

  function composer() {
    return document.querySelector('textarea[placeholder^="Message Thomas"], textarea[aria-label^="Message Thomas"]');
  }
  function styleOnce() {
    if (document.getElementById('thomas-slash-style')) return;
    const style = document.createElement('style');
    style.id = 'thomas-slash-style';
    style.textContent = '.tc-slash{position:absolute;z-index:60;min-width:280px;max-width:420px;border:1px solid var(--border,rgba(127,127,127,.35));border-radius:12px;background:var(--surface,#1b1d24);color:inherit;box-shadow:0 8px 24px rgba(0,0,0,.25);padding:6px;font:inherit}'
      + '.tc-slash [role=option]{display:flex;justify-content:space-between;gap:12px;padding:8px 10px;border-radius:8px;cursor:pointer}'
      + '.tc-slash [role=option][aria-selected=true]{background:var(--accent,#4f7cff);color:#fff}'
      + '.tc-slash small{opacity:.75}';
    document.head.appendChild(style);
  }
  function close() { if (box) { box.remove(); box = null; } items = []; index = 0; }
  function render(input) {
    items = match(input.value, document);
    if (!items.length) { close(); return; }
    styleOnce();
    if (!box) {
      box = document.createElement('div');
      box.className = 'tc-slash';
      box.setAttribute('role', 'listbox');
      box.setAttribute('aria-label', 'Commands');
      document.body.appendChild(box);
    }
    index = Math.min(index, items.length - 1);
    box.innerHTML = items.map((c, i) => `<div role="option" aria-selected="${i === index}" data-name="${c.name}"><span>/${c.name} <small>${c.label}</small></span><small>${c.hint}</small></div>`).join('');
    const r = input.getBoundingClientRect();
    box.style.left = `${Math.max(8, r.left)}px`;
    box.style.top = `${Math.max(8, r.top - box.offsetHeight - 8)}px`;
    box.querySelectorAll('[role=option]').forEach((el, i) => el.addEventListener('mousedown', (e) => { e.preventDefault(); run(items[i], input); }));
  }
  // The /help card: every command and what it does, above the composer,
  // gone on Escape, a click, or the next keystroke in the composer.
  function showHelp(commands, input) {
    const old = document.getElementById('thomas-slash-help');
    if (old) old.remove();
    const anchor = input.closest('form') || input.parentElement;
    if (!anchor || !anchor.parentElement) return;
    const card = document.createElement('div');
    card.id = 'thomas-slash-help';
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-label', 'Slash commands');
    card.style.cssText = 'margin:0 0 10px;padding:10px 14px;border:1px solid var(--border,rgba(127,127,127,.35));border-radius:12px;background:var(--surface-2,rgba(127,127,127,.08));font:inherit;color:inherit;font-size:.92em';
    const rows = commands.map((c) => `<div style="display:flex;gap:12px;padding:2px 0"><code style="min-width:9ch">/${c.name}</code><span>${c.label}<span style="opacity:.65"> · ${c.hint}</span></span></div>`).join('');
    card.innerHTML = `<div style="font-weight:600;margin-bottom:6px">Type / in the composer, then a command name. Esc closes this.</div>${rows}`;
    anchor.parentElement.insertBefore(card, anchor);
    const dismiss = () => { card.remove(); document.removeEventListener('keydown', onKey, true); document.removeEventListener('mousedown', onClick, true); };
    const onKey = (e) => { if (e.key === 'Escape' || e.target === input) dismiss(); };
    const onClick = (e) => { if (!card.contains(e.target)) dismiss(); };
    setTimeout(() => { document.addEventListener('keydown', onKey, true); document.addEventListener('mousedown', onClick, true); }, 0);
  }
  function run(command, input) {
    const action = resolve(command.name, document);
    close();
    if (!action) return;
    input.value = '';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    if (action.kind === 'open') { window.open(action.url, '_blank', 'noopener'); return; }
    if (action.kind === 'help') { showHelp(action.commands, input); return; }
    if (action.kind === 'retry') {
      // Edit-and-resend forks the history at the last message and puts its
      // text back in the composer; sending it again is a regenerate.
      action.target.click();
      setTimeout(() => { const send = byLabel(document, ['Send']); if (send && composer() && composer().value.trim()) send.click(); }, 500);
      return;
    }
    action.target.click();
  }
  document.addEventListener('input', (e) => {
    const input = e.target;
    if (!input || input !== composer()) return;
    if (input.value.startsWith('/') && !input.value.includes('\n')) render(input); else close();
  }, true);
  document.addEventListener('keydown', (e) => {
    if (!box) return;
    const input = composer();
    if (!input || e.target !== input) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); e.stopPropagation(); index = (index + 1) % items.length; render(input); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); e.stopPropagation(); index = (index - 1 + items.length) % items.length; render(input); return; }
    if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); e.stopPropagation(); run(items[index], input); }
  }, true);
})();
