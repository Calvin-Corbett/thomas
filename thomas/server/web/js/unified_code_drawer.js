/* The Activity drawer's contents in Build: every agent on the run (the lead,
   its helpers, and the Verifier when one is checking), the files they hold,
   and the changed files with Keep / Revert. The drawer itself -- the 360px
   slide-over `aside.tc-code-actions` -- belongs to the surface; this writes
   what goes inside it from data handed in, and nothing here fetches. */
(function () {
  'use strict';

  const FEED_SHOWN = 6;
  const BOT_STATE = { working: 'working', done: 'done', waiting: 'waiting', failed: 'failed', stopped: 'idle' };
  const ENDED = new Set(['done', 'failed', 'stopped']);
  // More finished helpers than this fold under one "N earlier helpers" toggle.
  const FOLD_AFTER = 3;

  function elapsedLabel(ms) {
    const seconds = Math.max(0, Math.floor(Number(ms || 0) / 1000));
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
    return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  }

  // A Verifier still waiting for work to check has not started, and an agent
  // under a second with nothing running has no honest time yet (a saved turn
  // written before events carried times), so both read "—" rather than a
  // number.
  function timeLabel(agent) {
    if (agent.id === 'verifier' && agent.state === 'waiting') return '—';
    if (agent.state !== 'working' && !(agent.elapsedMs >= 1000)) return '—';
    return elapsedLabel(agent.elapsedMs);
  }

  function plural(number, word) {
    return `${number} ${word}${number === 1 ? '' : 's'}`;
  }

  function botFor(agent, size) {
    if (!window.ThomasBot) return '';
    const seed = agent.id === 'lead' ? 'thomas' : agent.id === 'verifier' ? 'verifier' : agent.name;
    return window.ThomasBot.html({ state: BOT_STATE[agent.state] || 'idle', seed, size });
  }

  function feedLineHtml(esc, entry, working) {
    const first = String(entry.text || '').split('\n').find(line => line.trim()) || '';
    const classes = ['tc-agent-line'];
    if (entry.kind === 'reply') classes.push('is-reply');
    if (entry.ok === false) classes.push('is-failed');
    if (entry.kind === 'steer') classes.push('is-steer');
    const running = entry.ok === null && working;
    if (running) classes.push('is-running');
    return `<div class="${classes.join(' ')}">${esc(first.trim())}${running ? ' …' : ''}</div>`;
  }

  function agentHtml(esc, agent, expanded) {
    const id = String(agent.id);
    const working = agent.state === 'working';
    // Ids from the agent, not its position: the surface hands focus back by id
    // after every repaint, so a toggled card keeps the keyboard where it was.
    const key = id.replace(/[^\w-]/g, '_');
    const detailId = `tc-agent-detail-${key}`;
    const owned = (agent.files || []).filter(file => file.op === 'edit');
    const lines = (agent.feed || []).slice(-FEED_SHOWN);
    const chips = owned.length
      ? `<div class="tc-agent-chips">${owned.map(file => `<span class="tc-agent-chip" title="${esc(file.path)}">${esc(file.path)}</span>`).join('')}</div>` : '';
    const feedHtml = lines.length
      ? `<div class="tc-agent-feed">${lines.map(entry => feedLineHtml(esc, entry, working)).join('')}</div>`
      : `<div class="tc-agent-feed is-empty"><div class="tc-agent-line">Nothing to show yet.</div></div>`;
    // The Verifier is a report, not a conversation: there is nobody to open.
    const open = id === 'verifier' ? ''
      : `<button type="button" id="tc-agent-open-${key}" class="tc-agent-open" data-code-agent-chat="${esc(id)}">Open chat with ${esc(agent.name)}</button>`;
    const since = working && Number.isFinite(agent.startedAt) ? ` data-agent-since="${esc(String(agent.startedAt))}"` : '';
    return `<article class="tc-agent-card is-${esc(agent.state)}${expanded ? ' is-expanded' : ''}" data-agent-card="${esc(id)}">
      <button type="button" id="tc-agent-row-${key}" class="tc-agent-row" data-code-agent="${esc(id)}" aria-expanded="${expanded ? 'true' : 'false'}"${expanded ? ` aria-controls="${detailId}"` : ''}>
        ${botFor(agent, 'md')}
        <span class="tc-agent-main">
          <span class="tc-agent-title"><span class="tc-agent-name">${esc(agent.name)}</span><span class="tc-agent-role">${esc(agent.role || '')}</span></span>
          <span class="tc-agent-action">${esc(agent.action || '')}</span>
        </span>
        <span class="tc-agent-meta">
          <span class="tc-agent-dot" data-state="${esc(agent.state)}" role="img" aria-label="${esc(agent.state)}"></span>
          <span class="tc-agent-time"${since}>${esc(timeLabel(agent))}</span>
        </span>
      </button>
      ${expanded ? `<div class="tc-agent-detail" id="${detailId}">${chips}${feedHtml}${open}</div>` : ''}
    </article>`;
  }

  function claimHtml(esc, claim) {
    const held = claim.state !== 'released';
    return `<div class="tc-agents-claim${held ? '' : ' is-released'}"><span class="tc-agents-path" title="${esc(claim.path)}">${esc(claim.path)}</span><span>${esc(held ? claim.agentName : 'released')}</span></div>`;
  }

  function changeHtml(esc, change) {
    const file = String(change.file || '');
    const added = change.added > 0 ? `<span class="tc-agents-add">+${esc(String(change.added))}</span>` : '';
    const removed = change.removed > 0 ? `<span class="tc-agents-del">−${esc(String(change.removed))}</span>` : '';
    const fresh = !added && !removed && change.untracked ? '<span class="tc-agents-new">new</span>' : '';
    return `<div class="tc-agents-output"><span class="tc-agents-path" data-dash-open="${esc(file)}" title="Open ${esc(file)}">${esc(file)}</span>${added}${removed}${fresh}<button type="button" class="tc-agents-keep" data-code-keep="${esc(file)}">Keep</button><button type="button" class="tc-agents-revert" data-code-revert="${esc(file)}">Revert</button></div>`;
  }

  // The lead, then the helpers still at it, then the ones that finished (an
  // earlier pass's, or this one's done early), then the Verifier. A run with
  // 25 helpers stays readable: past FOLD_AFTER, the finished ones fold under
  // one toggle (`data-code-agents-earlier`), opened by `earlierOpen` or by
  // expanding one of them.
  function cardsHtml(esc, agents, ctx) {
    const expanded = agent => ctx.expandedAgent != null && String(ctx.expandedAgent) === String(agent.id);
    const card = agent => agentHtml(esc, agent, expanded(agent));
    const helper = agent => agent.id !== 'lead' && agent.id !== 'verifier';
    const live = agents.filter(agent => helper(agent) && !ENDED.has(agent.state));
    const earlier = agents.filter(agent => helper(agent) && ENDED.has(agent.state));
    const fold = earlier.length > FOLD_AFTER;
    const open = !fold || Boolean(ctx.earlierOpen) || earlier.some(expanded);
    const toggle = fold
      ? `<button type="button" class="tc-agents-earlier" data-code-agents-earlier aria-expanded="${open ? 'true' : 'false'}">${esc(plural(earlier.length, 'earlier helper'))}</button>` : '';
    return agents.filter(agent => agent.id === 'lead').concat(live).map(card).join('')
      + toggle + (open ? earlier.map(card).join('') : '')
      + agents.filter(agent => agent.id === 'verifier').map(card).join('');
  }

  function html(ctx) {
    const { esc } = ctx;
    const agents = Array.isArray(ctx.agents) ? ctx.agents : [];
    const claims = Array.isArray(ctx.claims) ? ctx.claims : [];
    const changes = Array.isArray(ctx.changes) ? ctx.changes : [];
    const crew = agents.filter(agent => agent.id !== 'verifier').length;
    const sub = crew ? plural(crew, 'agent') : '';
    const cards = agents.length
      ? cardsHtml(esc, agents, ctx)
      : `<p class="tc-agents-empty">${ctx.running ? 'Agents show up here as soon as Thomas starts working.' : 'No agents have worked on this task yet.'}</p>`;
    // One wrapper whether or not anything is claimed, so a live repaint can
    // swap this block on its own (unified_code_controls.js patchDrawer).
    const claimed = `<div class="tc-agents-claimed" data-agents-claimed>${claims.length
      ? `<div class="tc-agents-label">Claimed files</div><div class="tc-agents-claims">${claims.map(claim => claimHtml(esc, claim)).join('')}</div>` : ''}</div>`;
    const outputs = changes.length
      ? changes.map(change => changeHtml(esc, change)).join('')
      : '<p class="tc-agents-empty">Changed files show up here with Keep and Revert.</p>';
    return `<div class="tc-agents-drawer">
      <header class="tc-agents-head">
        <div class="tc-agents-head-text"><strong>Activity</strong>${sub ? `<small>${esc(sub)}</small>` : ''}</div>
        <button type="button" class="tc-agents-close" data-code-drawer-close aria-label="Close activity">✕</button>
      </header>
      <div class="tc-agents-body">
        <div class="tc-agents-label">Agents</div>
        <div class="tc-agents-list">${cards}</div>
        ${claimed}
        <div class="tc-agents-label">Outputs</div>
        <p class="tc-agents-explain">Files this task changed. Click a name to look at it. <b>Keep</b> accepts the change; <b>Revert</b> undoes it and puts the file back as it was before this task.</p>
        <div class="tc-agents-outputs">${outputs}</div>
        ${ctx.extraHtml || ''}
      </div>
    </div>`;
  }

  function bindOnce(element, type, listener) {
    const key = `agentsBound${type}`;
    if (element.dataset[key]) return;
    element.dataset[key] = '1';
    element.addEventListener(type, listener);
  }

  function bind(root, handlers) {
    if (!root || !root.querySelectorAll) return;
    const on = handlers || {};
    root.querySelectorAll('[data-code-agent]').forEach(button => bindOnce(button, 'click', () => {
      if (on.onToggleAgent) on.onToggleAgent(button.dataset.codeAgent);
    }));
    root.querySelectorAll('[data-code-agent-chat]').forEach(button => bindOnce(button, 'click', () => {
      if (on.onOpenChat) on.onOpenChat(button.dataset.codeAgentChat);
    }));
    root.querySelectorAll('[data-code-agents-earlier]').forEach(button => bindOnce(button, 'click', () => {
      if (on.onToggleEarlier) on.onToggleEarlier();
    }));
    if (on.onClose) {
      root.querySelectorAll('.tc-agents-drawer [data-code-drawer-close]').forEach(button => bindOnce(button, 'click', () => on.onClose()));
    }
  }

  // Working agents' clocks, between repaints: call once a second.
  function tick(root) {
    if (!root || !root.querySelectorAll) return;
    const now = Date.now();
    root.querySelectorAll('.tc-agent-time[data-agent-since]').forEach(node => {
      const since = Number(node.dataset.agentSince);
      if (Number.isFinite(since)) node.textContent = elapsedLabel(now - since);
    });
  }

  window.ThomasCodeDrawer = { html, bind, tick, elapsedLabel };
})();
