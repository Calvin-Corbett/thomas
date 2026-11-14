/* The Thomas <-> agent side chat in Build: one agent's brief, its replies and
   tool lines, and the messages you sent it with their delivery state, plus a
   composer for messaging that agent directly.

   `html(ctx)` returns the whole `aside.tc-code-agent-chat`, so the caller
   inserts it as-is inside `.tc-code-panel`. The panel slides in when it first
   appears and not on the repaints after, which is why this module remembers
   the panel it last bound. */
(function () {
  'use strict';

  let boundPanel = null;
  // How far from the bottom the reader had scrolled, per agent, so a repaint
  // while you are reading the brief does not throw you back to the end.
  const scrollFromBottom = new Map();
  // Where the caret was in each agent's message box.
  const carets = new Map();

  function sentenceName(agent) {
    return agent.id === 'lead' ? 'Thomas' : String(agent.name || 'this agent');
  }

  // Your messages for this agent are the receipts addressed to it. Thomas's
  // brief comes first, then everything in the order it happened.
  function threadFor(agent, receipts) {
    if (!agent) return [];
    const items = [];
    if (agent.brief) items.push({ who: 'thomas', kind: 'brief', text: String(agent.brief), ts: Number(agent.startedAt) || 0, rank: 0 });
    (agent.history || agent.feed || []).forEach(entry => {
      items.push({
        who: 'agent',
        kind: entry.kind === 'reply' ? 'reply' : 'tool',
        text: String(entry.text || ''),
        ts: Number(entry.ts) || 0,
        ok: entry.ok === undefined ? null : entry.ok,
        rank: 1,
      });
    });
    (Array.isArray(receipts) ? receipts : []).forEach(receipt => {
      if (!receipt || String(receipt.agent_id) !== String(agent.id)) return;
      items.push({
        who: 'you',
        kind: 'message',
        text: String(receipt.text || ''),
        ts: Number(receipt.queued_at) || 0,
        state: String(receipt.state || 'queued'),
        rank: 1,
      });
    });
    return items
      .map((item, index) => ({ item, index }))
      .sort((a, b) => (a.item.rank - b.item.rank) || (a.item.ts - b.item.ts) || (a.index - b.index))
      .map(({ item }) => {
        const out = { who: item.who, kind: item.kind, text: item.text, ts: item.ts };
        if (item.state !== undefined) out.state = item.state;
        if (item.who === 'agent') out.ok = item.ok;
        return out;
      });
  }

  // Briefs and replies are model prose: keep line breaks and `code` spans,
  // and nothing else that would need a full markdown renderer.
  function proseHtml(esc, text) {
    return esc(String(text || '').trim()).replace(/`([^`\n]{1,200})`/g, '<code>$1</code>');
  }

  function toolLineHtml(esc, item, working) {
    let mark = '<span class="tc-agent-chat-mark is-unknown" aria-hidden="true">·</span>';
    let tone = '';
    if (item.ok === true) mark = '<span class="tc-agent-chat-mark is-ok" aria-hidden="true">✓</span>';
    else if (item.ok === false) { mark = '<span class="tc-agent-chat-mark is-failed" aria-hidden="true">✕</span>'; tone = ' is-failed'; }
    else if (working) { mark = '<span class="tc-agent-chat-mark is-running" aria-hidden="true">◌</span>'; tone = ' is-running'; }
    const first = String(item.text || '').split('\n').find(line => line.trim()) || '';
    return `<div class="tc-agent-chat-tool${tone}">${mark} ${esc(first.trim())}</div>`;
  }

  // Consecutive items from one speaker share one label, and consecutive tool
  // lines share one ruled block, the way the design groups them.
  function threadHtml(esc, agent, thread) {
    const upper = sentenceName(agent).toUpperCase();
    const working = agent.state === 'working';
    const groups = [];
    thread.forEach(item => {
      const last = groups[groups.length - 1];
      if (last && last.who === item.who && item.who !== 'thomas') last.items.push(item);
      else groups.push({ who: item.who, items: [item] });
    });
    return groups.map(group => {
      if (group.who === 'thomas') {
        return group.items.map(item => `<section class="tc-agent-chat-group is-brief">
          <div class="tc-agent-chat-label is-accent">THOMAS → ${esc(upper)} · BRIEF</div>
          <div class="tc-agent-chat-brief">${proseHtml(esc, item.text)}</div>
        </section>`).join('');
      }
      if (group.who === 'you') {
        return `<section class="tc-agent-chat-group is-you">
          <div class="tc-agent-chat-label">YOU → ${esc(upper)}</div>
          ${group.items.map(item => `<div class="tc-agent-chat-mine">
            <div class="tc-agent-chat-bubble">${proseHtml(esc, item.text)}</div>
            <span class="tc-agent-chat-badge" data-state="${esc(item.state || 'queued')}">${esc(item.state || 'queued')}</span>
          </div>`).join('')}
        </section>`;
      }
      const parts = [];
      group.items.forEach(item => {
        const last = parts[parts.length - 1];
        if (item.kind === 'reply') parts.push({ reply: item });
        else if (last && last.tools) last.tools.push(item);
        else parts.push({ tools: [item] });
      });
      const partHtml = part => (part.reply
        ? `<div class="tc-agent-chat-reply">${proseHtml(esc, part.reply.text)}</div>`
        : `<div class="tc-agent-chat-tools">${part.tools.map(item => toolLineHtml(esc, item, working)).join('')}</div>`);
      return `<section class="tc-agent-chat-group is-agent">
        <div class="tc-agent-chat-label">${esc(upper)}</div>
        ${parts.map(partHtml).join('')}
      </section>`;
    }).join('');
  }

  // Why the composer is not there, in the words of what actually happened.
  function closedReason(agent) {
    const name = sentenceName(agent);
    const ended = agent.state === 'done' || agent.state === 'failed' || agent.state === 'stopped';
    if (agent.id === 'lead') {
      return ended
        ? 'This run has finished. Send your next message from the main composer.'
        : "Thomas can't take direct messages on this run. Steer it from the main composer.";
    }
    if (agent.state === 'done') return `${name} has finished, so it can't take messages any more.`;
    if (agent.state === 'failed') return `${name} stopped with an error, so it can't take messages.`;
    if (agent.state === 'stopped') return `${name} was stopped, so it can't take messages.`;
    if (String(agent.id).startsWith('agent_')) return `${name} runs inside Thomas's server and can't take direct messages.`;
    return `${name} isn't listening for messages right now.`;
  }

  function composerHtml(esc, agent, draft, sending) {
    const name = sentenceName(agent);
    const hasText = Boolean(String(draft || '').trim());
    return `<form class="tc-agent-chat-composer" data-agent-chat-form${sending ? ' data-sending="1"' : ''}>
      <textarea id="tc-agent-chat-input" data-agent-chat-input rows="1" placeholder="Message ${esc(name)}…" aria-label="Message ${esc(name)}">${esc(draft || '')}</textarea>
      <button type="submit" class="tc-agent-chat-send${hasText ? ' has-text' : ''}" data-agent-chat-send aria-label="Send to ${esc(name)}"${sending ? ' disabled aria-busy="true"' : ''}><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5M5 12l7-7 7 7"></path></svg></button>
    </form>`;
  }

  function html(ctx) {
    const { esc } = ctx;
    const agent = ctx.agent;
    if (!agent) return '';
    const id = String(agent.id);
    const thread = Array.isArray(ctx.thread) ? ctx.thread : threadFor(agent, []);
    const entering = !(boundPanel && boundPanel.isConnected && boundPanel.dataset.agentChatFor === id);
    const title = agent.id === 'lead' ? 'You ↔ Thomas' : `Thomas ↔ ${agent.name}`;
    const role = [agent.role, 'direct control'].filter(Boolean).join(' · ');
    const body = thread.length ? threadHtml(esc, agent, thread)
      : `<p class="tc-agent-chat-empty">Nothing from ${esc(sentenceName(agent))} yet.</p>`;
    const foot = agent.reachable
      ? composerHtml(esc, agent, ctx.draft, Boolean(ctx.sending))
      : `<p class="tc-agent-chat-closed">${esc(ctx.closedText || closedReason(agent))}</p>`;
    const error = ctx.error ? `<p class="tc-agent-chat-error" role="alert">${esc(ctx.error)}</p>` : '';
    return `<aside class="tc-code-agent-chat${entering ? ' is-entering' : ''}" data-agent-chat-for="${esc(id)}" aria-label="${esc(title)}">
      <header class="tc-agent-chat-head">
        <div class="tc-agent-chat-title"><strong>${esc(title)}</strong><small>${esc(role)}</small></div>
        <button type="button" id="tc-agent-chat-close" class="tc-agent-chat-close" data-agent-chat-close aria-label="Close chat with ${esc(sentenceName(agent))}">✕</button>
      </header>
      <div class="tc-agent-chat-thread" data-agent-chat-thread role="log" aria-live="polite">
        <div class="tc-agent-chat-stack">${body}</div>
      </div>
      <footer class="tc-agent-chat-foot">${foot}${error}</footer>
    </aside>`;
  }

  function fit(input) {
    input.style.height = 'auto';
    input.style.height = `${Math.min(input.scrollHeight, 132)}px`;
  }

  function bind(root, handlers) {
    if (!root || !root.querySelector) return;
    const on = handlers || {};
    const panel = root.matches && root.matches('.tc-code-agent-chat') ? root : root.querySelector('.tc-code-agent-chat');
    if (!panel || panel.dataset.agentChatBound) return;
    panel.dataset.agentChatBound = '1';
    const entering = panel.classList.contains('is-entering');
    const agentId = panel.dataset.agentChatFor || '';
    boundPanel = panel;

    const close = () => {
      boundPanel = null;
      scrollFromBottom.delete(agentId);
      carets.delete(agentId);
      if (on.onClose) on.onClose();
    };
    panel.querySelector('[data-agent-chat-close]')?.addEventListener('click', close);
    panel.addEventListener('keydown', event => {
      if (event.key === 'Escape' && !event.defaultPrevented) { event.preventDefault(); close(); }
    });

    const thread = panel.querySelector('[data-agent-chat-thread]');
    if (thread) {
      const away = scrollFromBottom.get(agentId) || 0;
      thread.scrollTop = Math.max(0, thread.scrollHeight - thread.clientHeight - away);
      thread.addEventListener('scroll', () => {
        scrollFromBottom.set(agentId, Math.max(0, thread.scrollHeight - thread.clientHeight - thread.scrollTop));
      });
    }

    const form = panel.querySelector('[data-agent-chat-form]');
    const input = panel.querySelector('[data-agent-chat-input]');
    const send = panel.querySelector('[data-agent-chat-send]');
    if (!form || !input) return;
    fit(input);
    const submit = () => {
      const text = input.value.trim();
      if (!text || form.dataset.sending === '1') return;
      if (on.onSend) on.onSend(text);
    };
    const remember = () => {
      if (typeof input.selectionStart === 'number') carets.set(agentId, [input.selectionStart, input.selectionEnd]);
    };
    form.addEventListener('submit', event => { event.preventDefault(); submit(); });
    input.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); submit(); }
    });
    input.addEventListener('input', () => {
      fit(input);
      remember();
      send?.classList.toggle('has-text', Boolean(input.value.trim()));
      if (on.onDraft) on.onDraft(input.value);
    });
    ['keyup', 'click', 'select'].forEach(type => input.addEventListener(type, remember));
    // A repaint while you type replaces this box. The surface gives focus back
    // by id; the caret is put back here, so the next key lands where it was.
    const end = input.value.length;
    const [start, stop] = entering ? [end, end] : carets.get(agentId) || [end, end];
    try { input.setSelectionRange(Math.min(start, end), Math.min(stop, end)); } catch (error) { /* not a text field */ }
    if (entering) input.focus({ preventScroll: true });
  }

  // Forget the open panel, so the next one slides in even for the same agent.
  function reset() {
    boundPanel = null;
  }

  window.ThomasCodeAgentChat = { threadFor, html, bind, reset };
})();
