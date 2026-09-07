/* Thumbs up or down on a reply (frontier parity: ChatGPT, Claude.ai).
 *
 * The chat page renders an action row under every message with a Copy button,
 * and an Edit button only under the person's own messages; a row with Copy and
 * no Edit is a reply from Thomas. This module watches the page, adds two
 * buttons beside Copy on each such row, and posts the verdict to
 * /api/chat/feedback with the open chat's id (the sidebar row marked
 * aria-current) and a stable message id (index plus a hash of the text).
 * Self-contained: no change to the page markup.
 */
(function () {
  'use strict';

  // "Branch from here" on a reply keeps every message up to and including that
  // reply: the reply's position among all message rows, in document order
  // (every message row carries one copy button). null when the row is unknown.
  function uptoFor(copies, copy) {
    const index = Array.prototype.indexOf.call(copies, copy);
    return index < 0 ? null : index + 1;
  }
  window.ThomasMessageFeedback = { uptoFor };
  if (typeof document === 'undefined' || !document.querySelectorAll) return;
  if (window.__thomasMessageFeedback) return;
  window.__thomasMessageFeedback = true;

  const API = '/api/chat/feedback';

  function hash(text) {
    let h = 5381;
    for (let i = 0; i < text.length; i += 1) h = ((h << 5) + h + text.charCodeAt(i)) | 0;
    return (h >>> 0).toString(16);
  }
  function chatId() {
    const row = document.querySelector('[data-history-id][aria-current]');
    return row ? String(row.dataset.historyId || '') : '';
  }
  function replyRows() {
    return Array.from(document.querySelectorAll('button[data-msg-copy]'))
      .map((copy) => copy.parentElement)
      .filter((row) => row && !row.querySelector('button[data-msg-edit]'));
  }
  function messageText(row) {
    let node = row.parentElement;
    for (let i = 0; i < 4 && node; i += 1) {
      const text = String(node.textContent || '').trim();
      if (text.length > 0 && node !== row) return text;
      node = node.parentElement;
    }
    return '';
  }
  function button(kind, label) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'hv-soft';
    btn.dataset.msgFeedback = kind;
    btn.title = label;
    btn.setAttribute('aria-label', label);
    btn.setAttribute('aria-pressed', 'false');
    btn.style.cssText = 'width:28px;height:28px;border-radius:8px;border:1px solid transparent;background:transparent;color:var(--c-muted);display:grid;place-items:center;cursor:pointer;transition:all .14s;';
    btn.innerHTML = `<i class="ph ${kind === 'up' ? 'ph-thumbs-up' : 'ph-thumbs-down'}" style="font-size:15px;" aria-hidden="true"></i>`;
    return btn;
  }
  async function send(row, kind, index) {
    const text = messageText(row);
    const messageId = `${index}-${hash(text.slice(0, 2000))}`;
    let note = '';
    if (kind === 'down') {
      const typed = window.prompt('What was wrong? (optional)', '');
      if (typed === null) return false;
      note = typed.trim();
    }
    const res = await fetch(API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: chatId(), message_id: messageId, rating: kind, note }),
    });
    return res.ok;
  }
  function decorate() {
    replyRows().forEach((row, index) => {
      if (row.querySelector('[data-msg-feedback]')) return;
      const up = button('up', 'Good reply');
      const down = button('down', 'Bad reply');
      [up, down].forEach((btn) => btn.addEventListener('click', async () => {
        const kind = btn.dataset.msgFeedback;
        btn.disabled = true;
        try {
          const ok = await send(row, kind, index);
          if (ok) {
            up.setAttribute('aria-pressed', String(kind === 'up'));
            down.setAttribute('aria-pressed', String(kind === 'down'));
            btn.style.color = 'var(--c-accent, #4f7cff)';
          }
        } catch (_err) { /* stays clickable */ } finally { btn.disabled = false; }
      }));
      const copy = row.querySelector('button[data-msg-copy]');
      // Branch from here (frontier parity: ChatGPT and Claude.ai): a copy of
      // this chat up to and including this reply, opened for a new direction.
      const branch = button('branch', 'Branch from here');
      branch.innerHTML = '<i class="ph ph-git-branch" style="font-size:15px;" aria-hidden="true"></i>';
      branch.addEventListener('click', async () => {
        const id = chatId();
        const history = window.ThomasSidebarHistory;
        if (!id || !history || typeof history.branchChat !== 'function') { window.alert('Open a saved chat first, then branch from a reply.'); return; }
        const upto = uptoFor(Array.from(document.querySelectorAll('button[data-msg-copy]')), copy);
        branch.disabled = true;
        try { await history.branchChat(id, history.displayTitle(id) || document.title || 'Chat', upto); }
        finally { branch.disabled = false; }
      });
      copy.insertAdjacentElement('afterend', branch);
      copy.insertAdjacentElement('afterend', down);
      copy.insertAdjacentElement('afterend', up);
    });
  }
  function start() {
    decorate();
    const observer = new MutationObserver(() => decorate());
    observer.observe(document.body, { childList: true, subtree: true });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  window.ThomasMessageFeedback = { decorate, replyRows, uptoFor };
})();
