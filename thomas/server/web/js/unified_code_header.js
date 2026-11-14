/* The row left of the Activity button in Build's top bar (window.ThomasCodeHeader).
 *
 * Three small things, each shown only when it has something to say:
 *   - the deck: a tile for everything this task made that can be looked at (a page or game, a picture, a PDF). They
 *     stack like cards, fan out when you hover, and a click opens the one you pick in the side viewer;
 *   - the changes: "+N -M" across the files this task changed, a running total you only read;
 *   - the context meter: how much of the model's context window is left, from the lead's own token count.
 *
 * It draws nothing of its own accord. The surface asks for rowHtml() when it renders, and paint() (called from the
 * messages poll and a timer) patches the row in place when what it shows changed, so a hover is never reset by a
 * repaint that changed nothing.
 */
(function () {
  'use strict';

  const SHOWN = 5;  // tiles in the fanned deck; the rest are one click away in the Activity drawer's Outputs
  const OPENABLE = /\.(x?html?|png|jpe?g|gif|webp|svg|pdf)$/i;
  const KIND_LABEL = { page: 'Web page', image: 'Image', pdf: 'PDF' };
  // The same sandbox the chat's own previews give a game (unified_code_artifacts.js livePreviewHtml).
  const FRAME_SANDBOX = 'allow-scripts allow-forms allow-modals allow-pointer-lock allow-downloads allow-same-origin';
  let ctx = null;  // what the surface last handed us: { state, esc, isInternal }

  function internal(file) {
    return /(^|\/)\.(git|thomas)(\/|$)/.test(String(file || '')) || Boolean(ctx && ctx.isInternal && ctx.isInternal(file));
  }

  function kindOf(file) {
    if (/\.pdf$/i.test(file)) return 'pdf';
    if (/\.(png|jpe?g|gif|webp|svg)$/i.test(file)) return 'image';
    return 'page';
  }

  // Everything openable the task made, oldest first, each file once (a later turn's version replaces the earlier).
  function artifactsOf(state) {
    const turns = state && state.conversation && Array.isArray(state.conversation.turns) ? state.conversation.turns : [];
    const seen = new Map();
    turns.forEach(turn => {
      if (!turn || turn.role !== 'agent') return;
      (turn.artifacts || []).forEach(item => {
        const file = item && item.file ? String(item.file) : '';
        if (!file || !OPENABLE.test(file) || internal(file)) return;
        seen.delete(file);
        seen.set(file, { file, kind: kindOf(file) });
      });
    });
    return [...seen.values()];
  }

  function totals(state) {
    let added = 0;
    let removed = 0;
    (Array.isArray(state && state.changes) ? state.changes : []).forEach(change => {
      if (!change || internal(change.file)) return;
      added += Number(change.added) > 0 ? Number(change.added) : 0;
      removed += Number(change.removed) > 0 ? Number(change.removed) : 0;
    });
    return { added, removed };
  }

  function fileCount(state) {
    return (Array.isArray(state && state.changes) ? state.changes : []).filter(change => change && !internal(change.file)).length;
  }

  function short(tokens) {
    return tokens >= 1000000 ? `${(tokens / 1000000).toFixed(1)}M` : tokens >= 1000 ? `${Math.round(tokens / 1000)}k` : String(tokens);
  }

  const ICONS = {
    page: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2.5"/><path d="M3 9h18M7 6.5h.01M10 6.5h.01"/></svg>',
    pdf: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M9.5 14h5M9.5 17h5"/></svg>',
    image: '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="9" cy="10" r="1.8"/><path d="m4 18 5-5 4 4 3-3 4 4"/></svg>',
  };

  function deckHtml(state, esc) {
    const all = artifactsOf(state);
    if (!all.length) return '';
    const newest = all.slice(-SHOWN).reverse();  // newest on top of the stack
    const more = all.length - newest.length;
    const cid = state.activeId ? encodeURIComponent(state.activeId) : '';
    const tiles = newest.map((item, index) => {
      const name = item.file.split('/').pop();
      const url = cid ? `/api/evolve/agent/artifact/${cid}/${item.file.split('/').map(encodeURIComponent).join('/')}` : '';
      // A page or game is a live miniature of itself (the same prepared document the chat's preview uses), a picture
      // is the picture, and a PDF is an icon. The miniature takes no clicks: the tile does.
      const doc = state.artifactDocs && state.artifactDocs[item.file];
      const source = doc || url;
      const face = item.kind === 'image' && url ? `<img src="${esc(url)}" alt="" loading="lazy">`
        : item.kind === 'page' && source ? `<iframe class="tc-dash-frame" src="${esc(source)}" sandbox="${FRAME_SANDBOX}" scrolling="no" tabindex="-1" loading="lazy" title="${esc(name)}"></iframe>`
          : ICONS[item.kind];
      return `<button type="button" class="tc-dash-tile is-${item.kind}" style="--i:${index}" data-dash-open="${esc(item.file)}" aria-label="Open ${esc(name)} (${KIND_LABEL[item.kind]})">${face}<span class="tc-dash-kind">${KIND_LABEL[item.kind]} · ${esc(name)}</span></button>`;
    }).join('');
    const rest = more > 0 ? `<button type="button" class="tc-dash-more" data-dash-more title="${more} more in the Activity drawer">+${more}</button>` : '';
    return `<div class="tc-dash-deck" style="--n:${newest.length}" role="group" aria-label="Everything made in this task">${tiles}${rest}</div>`;
  }

  function changesHtml(state) {
    const { added, removed } = totals(state);
    return `<div class="tc-dash-changes" title="Lines added and removed so far in this task"><span class="tc-dash-add">+${added}</span><span class="tc-dash-del">−${removed}</span></div>`;
  }

  function contextHtml(state) {
    const use = state && state.contextUse;
    // Always there once a task is open: with no reading it is an empty bar that says so, never nothing.
    if ((!use || !use.window) && state && state.activeId) {
      return '<button type="button" class="tc-dash-context is-empty" data-ctx-toggle aria-expanded="false" title="How much of the model\'s context window this task has used. It fills in after the first model call."><span class="tc-dash-bar"><i style="width:0%"></i></span><span class="tc-dash-pct">0%</span></button>';
    }
    if (!use || !use.window) return '';
    const used = Math.min(1, Math.max(0, use.tokens / use.window));
    const pct = Math.round(used * 100);
    const title = `${num(use.tokens)} of ${num(use.window)} tokens used. Click for where they went.`;
    return `<button type="button" class="tc-dash-context" data-ctx-toggle aria-expanded="${panelOpen}" style="--ctx:${fillColor(used)}" title="${title}"><span class="tc-dash-bar"><i style="width:${pct}%"></i></span><span class="tc-dash-pct">${pct}%</span></button>`;
  }

  // The bar turns from green through amber to red as the window fills.
  function fillColor(used) {
    return `hsl(${Math.round(140 - 140 * Math.min(1, Math.max(0, used)))} 72% 56%)`;
  }

  const num = value => Number(value || 0).toLocaleString('en-US');
  let panelOpen = false;
  let compact = { state: 'idle', message: '' };
  let windowOpen = false;  // the slider under the total is open
  let sliding = false;  // a drag is in progress: the panel is not redrawn under the thumb
  let windowNote = '';
  let appliedRun = '';  // the run the saved window was last sent to
  const WINDOW_KEY = 'thomas_context_window';
  const STEP = 25000;

  function savedWindow() {
    try { const value = Number(localStorage.getItem(WINDOW_KEY)); return Number.isFinite(value) && value >= STEP ? value : 0; } catch (error) { return 0; }
  }
  function saveWindow(value) {
    try { if (value > 0) localStorage.setItem(WINDOW_KEY, String(value)); else localStorage.removeItem(WINDOW_KEY); } catch (error) { /* just not remembered */ }
  }

  // The window you may choose: from one step up to a million or the model's own, whichever is more, 25,000 at a time.
  function sliderHtml(state, use, esc) {
    if (!windowOpen) return '';
    const own = use.model_window || use.window;
    const max = Math.ceil(Math.max(1000000, own, use.window) / STEP) * STEP;
    const live = Boolean(state && state.running && state.runId);
    const note = windowNote || (live
      ? 'Slide to set how much Thomas keeps in mind. Lower, and he compacts sooner. Higher, and he keeps more, up to what the model can take.'
      : 'Available while Thomas is working.');
    return `<div class="tc-ctx-slider"><input type="range" min="${STEP}" max="${max}" step="${STEP}" value="${use.window}" data-ctx-range aria-label="Context window in tokens"${live ? '' : ' disabled'}>
      <div class="tc-ctx-slider-line"><span><b data-ctx-draft>${num(use.window)}</b> tokens</span><span>the model's own: ${num(own)}</span>${use.window !== own ? '<button type="button" data-ctx-reset>Use the model\'s own</button>' : ''}</div>
      <small>${esc(note)}</small></div>`;
  }

  // Click the meter: a panel under the Steps card says what the window holds and offers to compact it.
  function panelHtml(state, esc) {
    const use = state && state.contextUse;
    const used = use && use.window ? Math.min(1, Math.max(0, use.tokens / use.window)) : 0;
    const rows = use && Array.isArray(use.breakdown) ? use.breakdown : [];
    const biggest = Math.max(1, ...rows.map(row => row.tokens));
    const body = use && use.window
      ? `<div class="tc-ctx-total"><b>${num(use.tokens)}</b><span>of <button type="button" class="tc-ctx-window" data-ctx-window aria-expanded="${windowOpen}" title="Change the window">${num(use.window)}</button> tokens used</span></div>${sliderHtml(state, use, esc)}
        <div class="tc-ctx-track" style="--ctx:${fillColor(used)}"><i style="width:${Math.round(used * 100)}%"></i><u title="Thomas compacts on his own from here"></u></div>
        ${rows.length ? `<div class="tc-ctx-rows">${rows.map((row, index) => `<div class="tc-ctx-row" style="--w:${Math.round((row.tokens / biggest) * 100)}%;--i:${index}"><span>${esc(row.label)}</span><b>${num(row.tokens)}</b><em>${Math.round((row.tokens / use.tokens) * 100)}%</em><i></i></div>`).join('')}</div>` : '<p class="tc-ctx-note">The breakdown arrives with Thomas\'s next step.</p>'}`
      : '<p class="tc-ctx-note">No reading yet. It arrives with Thomas\'s first model call in this task.</p>';
    const live = Boolean(state && state.running && state.runId);
    const label = compact.state === 'sending' ? 'Asking…' : compact.state === 'asked' ? 'Asked' : 'Compact now';
    return `<header><strong>Context window</strong><button type="button" data-ctx-close aria-label="Close">✕</button></header>${body}
      <footer><button type="button" class="tc-ctx-compact" data-ctx-compact${live && compact.state === 'idle' ? '' : ' disabled'}>${label}</button>
      <small>${esc(compact.message || (live ? 'Thomas compacts at his next step. He also does it on his own at 75%.' : 'Available while Thomas is working. He compacts on his own at 75%.'))}</small></footer>`;
  }

  function innerHtml(state, esc) {
    return deckHtml(state, esc) + changesHtml(state) + contextHtml(state);
  }

  function rowHtml(state, esc, isInternal) {
    ctx = { state, esc, isInternal };
    const panel = panelOpen ? `<section class="tc-ctx-panel" data-ctx-panel>${panelHtml(state, esc)}</section>` : '';
    return `<div class="tc-code-dash" data-code-dash>${innerHtml(state, esc)}</div>${panel}`;
  }

  // A task you open later has no live poll, so ask once for its last run's reading (the run's folder keeps it).
  const asked = new Set();
  function loadContext() {
    const state = ctx && ctx.state;
    if (!state || !state.activeId || state.contextUse || asked.has(state.activeId) || typeof fetch !== 'function') return;
    const turns = state.conversation && Array.isArray(state.conversation.turns) ? state.conversation.turns : [];
    const last = [...turns].reverse().find(turn => turn && turn.role === 'agent' && turn.run_id);
    if (!last) return;
    asked.add(state.activeId);
    const id = state.activeId;
    fetch(`/api/evolve/agent/messages?run_id=${encodeURIComponent(last.run_id)}`)
      .then(response => response.json())
      .then(data => {
        if (!data || data.ok !== true || !data.context || !(Number(data.context.window) > 0) || state.activeId !== id) return;
        state.contextUse = { tokens: Number(data.context.tokens) || 0, window: Number(data.context.window), breakdown: Array.isArray(data.context.breakdown) ? data.context.breakdown : [] };
        paint();
      })
      .catch(() => { /* the meter just says there is no reading */ });
  }

  // The Activity bubble opens under whatever the top bar holds (the buttons, the Steps card, the context panel), so
  // the bar's lower edge is kept in a variable the bubble's CSS reads. It follows the bar as panels open and close.
  let watched = null;
  function trackStack() {
    const bar = document.querySelector('.tc-code-context');
    const panel = document.querySelector('.tc-code-panel');
    if (!bar || !panel) return;
    const set = () => panel.style.setProperty('--tc-code-stack-bottom', `${Math.max(0, Math.round(bar.getBoundingClientRect().bottom - panel.getBoundingClientRect().top + 10))}px`);
    set();
    if (watched !== bar && typeof ResizeObserver === 'function') { watched = bar; new ResizeObserver(set).observe(bar); }
  }

  // Patch the row in place, only when its content changed.
  function paint() {
    if (!ctx || typeof document === 'undefined') return;
    loadContext();
    applySavedWindow();
    trackStack();
    const row = document.querySelector('[data-code-dash]');
    if (!row) return;
    const panel = document.querySelector('[data-ctx-panel]');
    if (panel && !sliding) {
      const panelNow = panelHtml(ctx.state, ctx.esc);
      if (panel.dataset.signature !== panelNow) { panel.dataset.signature = panelNow; panel.innerHTML = panelNow; }
    }
    const html = innerHtml(ctx.state, ctx.esc);
    if (row.dataset.signature === html) return;
    row.dataset.signature = html;
    row.innerHTML = html;
  }

  // Open or close the panel in place, without waiting for the surface to render again.
  function setPanel(open) {
    panelOpen = open;
    const header = document.querySelector('.tc-code-context');
    if (!header || !ctx) return;
    let panel = header.querySelector('[data-ctx-panel]');
    if (open && !panel) {
      panel = document.createElement('section');
      panel.className = 'tc-ctx-panel';
      panel.setAttribute('data-ctx-panel', '');
      panel.innerHTML = panelHtml(ctx.state, ctx.esc);
      header.appendChild(panel);
    } else if (!open && panel) {
      panel.remove();
    }
    document.querySelectorAll('[data-ctx-toggle]').forEach(node => node.setAttribute('aria-expanded', String(open)));
  }

  function repaintPanel() {
    const panel = document.querySelector('[data-ctx-panel]');
    if (!panel || !ctx) return;
    const html = panelHtml(ctx.state, ctx.esc);
    panel.dataset.signature = html;
    panel.innerHTML = html;
  }

  // Tell the live lead which window to work within (0 returns to the model's own), and remember it for next time.
  async function chooseWindow(value) {
    const state = ctx && ctx.state;
    if (!state || !state.runId) return;
    try {
      const response = await fetch('/api/evolve/agent/context-window', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ run_id: state.runId, window: value }) });
      const data = await response.json().catch(() => ({}));
      if (data && data.ok === true) {
        const own = state.contextUse && state.contextUse.model_window;
        if (state.contextUse) state.contextUse.window = data.window || own || state.contextUse.window;
        saveWindow(data.window || 0);
        windowNote = data.window ? `Set to ${num(data.window)}. Thomas uses it from his next step.` : 'Back to the model\'s own window.';
      } else {
        windowNote = (data && data.error) || 'Could not change it just now.';
      }
    } catch (error) {
      windowNote = 'Could not change it just now.';
    }
    repaintPanel();
    paint();
  }

  // A window you chose earlier is sent to each new run as it starts, so the choice sticks.
  function applySavedWindow() {
    const state = ctx && ctx.state;
    if (!state || !state.running || !state.runId || appliedRun === state.runId) return;
    appliedRun = state.runId;
    const saved = savedWindow();
    if (saved) void chooseWindow(saved);
  }

  // Ask the live lead to compact at its next step; the meter drops once it has.
  async function askCompaction() {
    const state = ctx && ctx.state;
    if (!state || !state.runId || compact.state !== 'idle') return;
    compact = { state: 'sending', message: '' };
    paint();
    try {
      const response = await fetch('/api/evolve/agent/compact', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ run_id: state.runId }) });
      const data = await response.json().catch(() => ({}));
      compact = data && data.ok === true
        ? { state: 'asked', message: 'Thomas will compact at his next step. Watch the bar drop.' }
        : { state: 'idle', message: (data && data.error) || 'Could not ask just now.' };
    } catch (error) {
      compact = { state: 'idle', message: 'Could not ask just now.' };
    }
    paint();
    setTimeout(() => { if (compact.state === 'asked') { compact = { state: 'idle', message: '' }; paint(); } }, 12000);
  }

  // Click a tile: that one output, large, in the middle of the chat. Not full screen and not the side panel.
  function closeFocus() {
    const layer = document.querySelector('.tc-dash-focus');
    if (layer) layer.remove();
  }

  function focus(file) {
    if (!ctx || typeof document === 'undefined') return;
    closeFocus();
    const { state, esc } = ctx;
    const kind = kindOf(file);
    const name = file.split('/').pop();
    const cid = state.activeId ? encodeURIComponent(state.activeId) : '';
    const url = cid ? `/api/evolve/agent/artifact/${cid}/${file.split('/').map(encodeURIComponent).join('/')}` : '';
    const doc = state.artifactDocs && state.artifactDocs[file];
    const stage = kind === 'image' ? `<img src="${esc(url)}" alt="${esc(name)}">`
      : kind === 'pdf' ? `<iframe src="${esc(url)}" title="${esc(name)}"></iframe>`
        : `<iframe src="${esc(doc || url)}" title="${esc(name)}" sandbox="${FRAME_SANDBOX}" allow="fullscreen; gamepad; autoplay; clipboard-write"></iframe>`;
    const layer = document.createElement('div');
    layer.className = 'tc-dash-focus';
    layer.setAttribute('role', 'dialog');
    layer.setAttribute('aria-modal', 'true');
    layer.setAttribute('aria-label', `${KIND_LABEL[kind]}: ${name}`);
    layer.innerHTML = `<div class="tc-dash-focus-card"><header><strong>${esc(name)}</strong><small>${KIND_LABEL[kind]}</small>
      <a href="${esc(url)}" target="_blank" rel="noopener noreferrer" aria-label="Open in a new tab" title="Open in a new tab"><svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 2.5h4.5V7M13.5 2.5L7.5 8.5M11.5 9.5v3a1 1 0 0 1-1 1h-7a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h3"/></svg></a>
      <button type="button" data-dash-close aria-label="Close" title="Close">✕</button></header><div class="tc-dash-focus-stage">${stage}</div></div>`;
    document.body.appendChild(layer);
    // Focus the card, not the game: a frame that has the keys swallows Escape. Click into the game to play it; the X
    // and a click outside the card close the view whatever has focus.
    const card = layer.querySelector('.tc-dash-focus-card');
    card.tabIndex = -1;
    card.focus({ preventScroll: true });
  }

  const api = { rowHtml, paint, open: null, focus, artifactsOf, totals, fileCount };
  window.ThomasCodeHeader = api;

  if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
    document.addEventListener('click', event => {
      const target = event.target && event.target.closest ? event.target : null;
      if (!target) return;
      const tile = target.closest('.tc-dash-tile');
      if (tile) { focus(tile.dataset.dashOpen); return; }
      const named = target.closest('[data-dash-open]');  // an output's name in the drawer opens in the side viewer
      if (named && typeof api.open === 'function') { api.open(named.dataset.dashOpen); return; }
      if (target.closest('[data-ctx-toggle]')) { setPanel(!panelOpen); return; }
      if (target.closest('[data-ctx-close]')) { setPanel(false); return; }
      if (target.closest('[data-ctx-compact]')) { void askCompaction(); return; }
      if (target.closest('[data-ctx-window]')) { windowOpen = !windowOpen; repaintPanel(); return; }
      if (target.closest('[data-ctx-reset]')) { void chooseWindow(0); return; }
      if (target.closest('[data-dash-more]')) { document.querySelector('.tc-code-context > button')?.click(); return; }
      if (target.closest('[data-dash-close]') || target.classList.contains('tc-dash-focus')) closeFocus();
    });
    document.addEventListener('keydown', event => { if (event.key === 'Escape') closeFocus(); });
    // The slider: the number follows the thumb as it moves, and the window is sent when it is let go.
    document.addEventListener('pointerdown', event => { if (event.target.closest && event.target.closest('[data-ctx-range]')) sliding = true; });
    document.addEventListener('pointerup', () => { setTimeout(() => { sliding = false; }, 400); });
    document.addEventListener('input', event => {
      if (!event.target.matches || !event.target.matches('[data-ctx-range]')) return;
      const draft = document.querySelector('[data-ctx-draft]');
      if (draft) draft.textContent = num(event.target.value);
    });
    document.addEventListener('change', event => {
      if (!event.target.matches || !event.target.matches('[data-ctx-range]')) return;
      sliding = false;
      void chooseWindow(Number(event.target.value));
    });
  }
  if (typeof window.setInterval === 'function') window.setInterval(paint, 2000);
})();
