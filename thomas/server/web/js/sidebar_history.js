(function () {
  'use strict';

  // The sidebar list, for every mode.
  //
  // Chat, Code and Work each render their own rows, so this decorates whatever
  // they produced rather than owning the markup: sorting, pin/archive/rename,
  // the hover card, the full-title tooltip, per-row running dots, and the
  // collapse. A renderer opts in by tagging each row with data-history-id and
  // data-history-time; anything untagged is left exactly as it was.

  const OVERLAY_KEY = 'thomas_history_overlay_v1';
  const VIEW_KEY = 'thomas_history_view_v1';
  const HOVER_DELAY = 550;

  const SORTS = [
    { id: 'recent', short: 'Recent', label: 'Last message', hint: 'newest first', dated: true },
    { id: 'created', short: 'Created', label: 'Date created', hint: 'newest first', dated: true },
    { id: 'name', short: 'Name', label: 'Name', hint: 'A to Z', dated: false },
  ];
  const sortSpec = id => SORTS.find(row => row.id === id) || SORTS[0];

  let hoverTimer = 0;
  let tip = null;
  let menu = null;
  let menuOwner = '';
  let refreshHook = null;

  const esc = value => String(value == null ? '' : value)
    .replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));

  function readJson(key, fallback) {
    try { return JSON.parse(localStorage.getItem(key) || 'null') || fallback; }
    catch (_) { return fallback; }
  }
  function writeJson(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) { /* view state is not worth failing over */ }
  }

  // Per-row overrides live in the browser. Rename/pin/archive apply uniformly
  // across Chat, Code and Work rows this way, without a schema change in three
  // different stores — the trade is that they do not follow you to another
  // machine, which the menu says out loud.
  const overlay = () => readJson(OVERLAY_KEY, {});
  function patchOverlay(id, patch) {
    const all = overlay();
    all[id] = Object.assign({}, all[id] || {}, patch);
    if (!all[id].title && !all[id].pinned && !all[id].archived) delete all[id];
    writeJson(OVERLAY_KEY, all);
  }

  const view = () => Object.assign({ sort: 'recent', showArchived: false, collapsed: false }, readJson(VIEW_KEY, {}));
  function patchView(patch) { writeJson(VIEW_KEY, Object.assign(view(), patch)); }

  // "Last touched" is the last message SENT, not the last time it was opened —
  // opening a chat must never bubble it to the top of the list.
  function relativeTime(ms) {
    const value = Number(ms) || 0;
    if (!value) return '';
    const delta = Date.now() - value;
    if (delta < 0) return 'just now';
    const minute = 60000, hour = 3600000, day = 86400000;
    if (delta < minute) return 'just now';
    if (delta < hour) return `${Math.floor(delta / minute)}m ago`;
    if (delta < day) return `${Math.floor(delta / hour)}h ago`;
    if (delta < day * 2) return 'yesterday';
    if (delta < day * 7) return `${Math.floor(delta / day)}d ago`;
    try { return new Date(value).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }); }
    catch (_) { return ''; }
  }

  function rowsIn(wrap) {
    return Array.from(wrap.querySelectorAll('[data-history-id]'));
  }

  function titleOf(row) {
    const custom = (overlay()[row.dataset.historyId] || {}).title;
    return String(custom || row.dataset.historyTitle || '').trim();
  }

  function ensureTip() {
    if (tip) return tip;
    tip = document.createElement('div');
    tip.className = 'tc-history-tip';
    tip.setAttribute('role', 'tooltip');
    tip.hidden = true;
    document.body.appendChild(tip);
    return tip;
  }

  function hideTip() {
    clearTimeout(hoverTimer);
    if (tip) tip.hidden = true;
  }

  // Only pops when the name is ACTUALLY cut off. A tooltip that repeats a title
  // you can already read in full is noise on every single hover.
  function isTruncated(node) {
    return node ? node.scrollWidth > node.clientWidth + 1 : false;
  }

  function showTip(row) {
    const label = row.querySelector('[data-history-name]');
    if (!isTruncated(label)) return;
    const box = ensureTip();
    box.textContent = titleOf(row);
    box.hidden = false;
    const rect = row.getBoundingClientRect();
    const own = box.getBoundingClientRect();
    box.style.left = `${Math.max(8, Math.min(window.innerWidth - own.width - 8, rect.left))}px`;
    box.style.top = `${Math.max(8, rect.top - own.height - 8)}px`;
  }

  function closeMenu() {
    if (menu) { menu.remove(); menu = null; }
    menuOwner = '';
    const filter = document.getElementById('tc-history-filter');
    if (filter) filter.setAttribute('aria-expanded', 'false');
  }

  function menuItems(row) {
    const id = row.dataset.historyId;
    const current = overlay()[id] || {};
    return [
      { action: 'rename', icon: 'ph-pencil-simple', label: 'Rename' },
      { action: 'pin', icon: 'ph-push-pin', label: current.pinned ? 'Unpin' : 'Pin to top' },
      { action: 'archive', icon: 'ph-archive', label: current.archived ? 'Unarchive' : 'Archive' },
      { action: 'delete', icon: 'ph-trash', label: 'Delete', danger: true },
    ];
  }

  function openMenu(row, x, y) {
    closeMenu();
    menuOwner = 'row';
    menu = document.createElement('div');
    menu.className = 'tc-history-menu';
    menu.setAttribute('role', 'menu');
    menu.innerHTML = `<div class="tc-history-menu-title">${esc(titleOf(row))}</div>`
      + menuItems(row).map(item => `<button type="button" role="menuitem" data-history-action="${item.action}" class="${item.danger ? 'is-danger' : ''}"><i class="ph ${item.icon}" aria-hidden="true"></i>${esc(item.label)}</button>`).join('');
    document.body.appendChild(menu);
    const box = menu.getBoundingClientRect();
    menu.style.left = `${Math.max(8, Math.min(window.innerWidth - box.width - 8, x))}px`;
    menu.style.top = `${Math.max(8, Math.min(window.innerHeight - box.height - 8, y))}px`;
    menu.addEventListener('click', event => {
      const button = event.target.closest('[data-history-action]');
      if (button) { event.preventDefault(); void runAction(button.dataset.historyAction, row); }
    });
    const first = menu.querySelector('[data-history-action]');
    if (first) first.focus();
  }

  async function removeRow(row) {
    const id = row.dataset.historyId;
    const mode = String(row.dataset.historyMode || (window.ThomasUnifiedModes ? window.ThomasUnifiedModes.mode() : 'chat'));
    const url = mode === 'code'
      ? `/api/evolve/agent/conversations/${encodeURIComponent(id)}`
      : `/api/chats/${encodeURIComponent(id)}`;
    const response = await fetch(url, { method: 'DELETE' });
    // Reported from the response, not assumed: a row that vanishes from the
    // list while the server still has it is the worst of both.
    if (!response.ok) throw new Error(`Could not delete that (${response.status})`);
  }

  async function runAction(action, row) {
    const id = row.dataset.historyId;
    if (action === 'rename') {
      const next = window.prompt('Rename this to:', titleOf(row));
      closeMenu();
      if (next == null) return;
      patchOverlay(id, { title: String(next).trim().slice(0, 200) || undefined });
      refresh();
      return;
    }
    if (action === 'pin') {
      patchOverlay(id, { pinned: !(overlay()[id] || {}).pinned || undefined });
      closeMenu(); refresh(); return;
    }
    if (action === 'archive') {
      patchOverlay(id, { archived: !(overlay()[id] || {}).archived || undefined });
      closeMenu(); refresh(); return;
    }
    if (action === 'delete') {
      closeMenu();
      if (!window.confirm(`Delete "${titleOf(row)}"? This cannot be undone.`)) return;
      try { await removeRow(row); }
      catch (error) { window.alert(error && error.message ? error.message : 'Delete failed.'); return; }
      patchOverlay(id, { title: undefined, pinned: undefined, archived: undefined });
      refresh();
    }
  }

  function openFilterMenu(anchor) {
    // Pressing the button while its own menu is open closes it.
    if (menuOwner === 'filter') { closeMenu(); return; }
    closeMenu();
    menuOwner = 'filter';
    anchor.setAttribute('aria-expanded', 'true');
    const current = view();
    menu = document.createElement('div');
    menu.className = 'tc-history-menu';
    menu.setAttribute('role', 'menu');
    // Unselected rows get an empty slot, not a bare dot: a dot with no meaning
    // is exactly as unreadable in a menu as it was on the button.
    menu.innerHTML = '<div class="tc-history-menu-title">Sort by</div>'
      + SORTS.map(row => `<button type="button" role="menuitemradio" aria-checked="${current.sort === row.id}" data-history-sort="${row.id}" class="${current.sort === row.id ? 'is-on' : ''}">${current.sort === row.id ? '<i class="ph ph-check" aria-hidden="true"></i>' : '<span class="tc-history-menu-gap" aria-hidden="true"></span>'}${esc(row.label)}<small>${esc(row.hint)}</small></button>`).join('')
      + '<div class="tc-history-menu-sep"></div>'
      + `<button type="button" role="menuitemcheckbox" aria-checked="${current.showArchived}" data-history-archived="1" class="${current.showArchived ? 'is-on' : ''}">${current.showArchived ? '<i class="ph ph-check" aria-hidden="true"></i>' : '<span class="tc-history-menu-gap" aria-hidden="true"></span>'}Show archived</button>`
      + '<div class="tc-history-menu-note">Renames, pins and archiving are saved in this browser.</div>';
    document.body.appendChild(menu);
    const rect = anchor.getBoundingClientRect();
    const box = menu.getBoundingClientRect();
    menu.style.left = `${Math.max(8, Math.min(window.innerWidth - box.width - 8, rect.left - box.width + rect.width))}px`;
    menu.style.top = `${Math.min(window.innerHeight - box.height - 8, rect.bottom + 6)}px`;
    menu.addEventListener('click', event => {
      const sort = event.target.closest('[data-history-sort]');
      const archived = event.target.closest('[data-history-archived]');
      if (sort) { patchView({ sort: sort.dataset.historySort }); closeMenu(); refresh(); }
      else if (archived) { patchView({ showArchived: !view().showArchived }); closeMenu(); refresh(); }
    });
  }

  function refresh() {
    if (typeof refreshHook === 'function') { refreshHook(); return; }
    const wrap = document.getElementById('tc-chats');
    if (wrap) decorate(wrap);
  }

  function applyCollapse() {
    const wrap = document.getElementById('tc-chats');
    const button = document.getElementById('tc-history-collapse');
    if (!wrap || !button) return;
    const collapsed = view().collapsed;
    wrap.hidden = collapsed;
    wrap.style.flex = collapsed ? '0 0 auto' : '1 1 auto';
    wrap.style.minHeight = collapsed ? '0' : '60px';
    button.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    button.title = collapsed ? 'Expand the list' : 'Collapse the list';
    // Rotate the drawn chevron rather than swapping to another glyph.
    const caret = document.getElementById('tc-history-collapse-icon');
    if (caret) caret.style.transform = collapsed ? 'rotate(-90deg)' : 'none';
  }

  function decorateRow(row) {
    if (row.dataset.historyReady === '1') return;
    row.dataset.historyReady = '1';
    // Only the tooltip timer lives here now — swapping the preview for the
    // time is pure CSS, so nothing runs per row while the list is scrolling.
    row.addEventListener('pointerenter', () => {
      clearTimeout(hoverTimer);
      hoverTimer = setTimeout(() => showTip(row), HOVER_DELAY);
    });
    row.addEventListener('pointerleave', hideTip);
    row.addEventListener('contextmenu', event => {
      event.preventDefault();
      hideTip();
      openMenu(row, event.clientX, event.clientY);
    });
  }

  // Sorting reorders the nodes the renderer produced, so it works the same for
  // Chat, Code and Work without any of them knowing about it.
  function order(rows) {
    const sort = view().sort;
    const marks = overlay();
    const key = row => {
      const custom = marks[row.dataset.historyId] || {};
      const name = String(custom.title || row.dataset.historyTitle || '').toLowerCase();
      return {
        pinned: custom.pinned ? 0 : 1,
        touched: Number(row.dataset.historyTime || 0),
        created: Number(row.dataset.historyCreated || row.dataset.historyTime || 0),
        name,
      };
    };
    return rows.slice().sort((a, b) => {
      const left = key(a), right = key(b);
      if (left.pinned !== right.pinned) return left.pinned - right.pinned;
      if (sort === 'name') return left.name.localeCompare(right.name);
      if (sort === 'created') return right.created - left.created;
      return right.touched - left.touched;
    });
  }

  // "Today", "Yesterday", then "Aug 7" — the heading you'd write yourself.
  function dayLabel(ms) {
    const value = Number(ms) || 0;
    if (!value) return 'Undated';
    const then = new Date(value);
    const today = new Date();
    const midnight = d => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
    const days = Math.round((midnight(today) - midnight(then)) / 86400000);
    if (days <= 0) return 'Today';
    if (days === 1) return 'Yesterday';
    try {
      return then.toLocaleDateString(undefined, then.getFullYear() === today.getFullYear()
        ? { month: 'short', day: 'numeric' }
        : { year: 'numeric', month: 'short', day: 'numeric' });
    } catch (_) { return 'Earlier'; }
  }

  function dayHeading(text) {
    const node = document.createElement('div');
    node.className = 'tc-history-day';
    node.dataset.historyDay = '1';
    node.textContent = text;
    return node;
  }

  function clearHeadings(wrap) {
    Array.from(wrap.querySelectorAll('[data-history-day]')).forEach(node => node.remove());
  }

  function decorate(wrap) {
    if (!wrap) return;
    applyCollapse();
    clearHeadings(wrap);
    const rows = rowsIn(wrap);
    if (!rows.length) { syncSortLabel(); return; }
    const marks = overlay();
    const showArchived = view().showArchived;
    rows.forEach(row => {
      const custom = marks[row.dataset.historyId] || {};
      row.hidden = Boolean(custom.archived) && !showArchived;
      row.classList.toggle('is-pinned', Boolean(custom.pinned));
      row.classList.toggle('is-archived', Boolean(custom.archived));
      const label = row.querySelector('[data-history-name]');
      if (label && custom.title) label.textContent = custom.title;
      const meta = row.querySelector('[data-history-meta]');
      if (meta) meta.textContent = relativeTime(row.dataset.historyTime);
      decorateRow(row);
    });

    // Sorted by a date? Then the list reads as days: a small heading, then that
    // day's threads under it. Pinned rows float above the first date heading,
    // under their own, because they are deliberately out of chronological order.
    const spec = sortSpec(view().sort);
    const stampKey = spec.id === 'created' ? 'historyCreated' : 'historyTime';
    let lastHeading = '';
    order(rows).forEach(row => {
      if (spec.dated && !row.hidden) {
        const pinned = row.classList.contains('is-pinned');
        const heading = pinned ? 'Pinned' : dayLabel(row.dataset[stampKey] || row.dataset.historyTime);
        if (heading !== lastHeading) { wrap.appendChild(dayHeading(heading)); lastHeading = heading; }
      }
      wrap.appendChild(row);
    });
    syncSortLabel();
    // After the list is on screen, not before: naming is a nicety and must
    // never delay the rows appearing.
    setTimeout(() => { void titleRawRows(wrap); }, 400);
  }

  function syncSortLabel() {
    const label = document.getElementById('tc-history-sort-label');
    if (label) label.textContent = sortSpec(view().sort).short;
  }

  // A stored title is the first 60 characters of whatever was typed first, so
  // the list reads as a wall of raw prompts. Ask the model to name the ones
  // that clearly need it — batched into ONE request for a whole page of rows,
  // only for rows that look raw, only once each, and cached in the overlay so
  // it never costs anything again. A user rename always wins.
  // ONE batch per page load. Writing titles triggers a refresh, which
  // re-decorates, which used to start the next batch — with 476 rows that
  // marched through the whole history twelve at a time and made 88 model calls
  // in four minutes. `titledThisSession` stopped a row being named twice; it
  // did nothing to stop the list being walked end to end. A hard budget does.
  const RAW_MIN_LENGTH = 34;
  const BATCH_SIZE = 12;
  const SESSION_BUDGET = 12;
  const titledThisSession = new Set();
  let titleRunning = false;
  let titleBudget = SESSION_BUDGET;

  function looksRaw(text) {
    const value = String(text || '').trim();
    if (!value) return false;
    if (value.length >= RAW_MIN_LENGTH) return true;
    // Markdown headings, code fences and imperative openers are prompts, not names.
    return /^[#`>\-*\d]|^(please|can you|i want|i need|make|build|create|fix|write|add|help)\b/i.test(value);
  }

  // Rows the user can actually see. Naming what is scrolled far out of view is
  // spending real money on something nobody is looking at.
  function onScreen(row, wrap) {
    const box = wrap.getBoundingClientRect();
    const rect = row.getBoundingClientRect();
    return rect.bottom > box.top - 40 && rect.top < box.bottom + 40;
  }

  async function titleRawRows(wrap) {
    if (titleRunning || titleBudget <= 0) return;
    const marks = overlay();
    const pending = rowsIn(wrap)
      .filter(row => !row.hidden)
      .filter(row => !(marks[row.dataset.historyId] || {}).title)
      .filter(row => !titledThisSession.has(row.dataset.historyId))
      .filter(row => looksRaw(row.dataset.historyTitle))
      .filter(row => onScreen(row, wrap))
      .slice(0, Math.min(BATCH_SIZE, titleBudget));
    if (!pending.length) return;
    titleRunning = true;
    titleBudget -= pending.length;
    pending.forEach(row => titledThisSession.add(row.dataset.historyId));
    try {
      const response = await fetch('/api/chats/title', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          items: pending.map(row => ({ id: row.dataset.historyId, text: row.dataset.historyTitle })),
        }),
      });
      const data = await response.json();
      const titles = (data && data.titles) || {};
      let wrote = 0;
      Object.keys(titles).forEach(id => {
        // Never overwrite a name the user chose themselves.
        if ((overlay()[id] || {}).title) return;
        patchOverlay(id, { title: String(titles[id]).slice(0, 200) });
        wrote += 1;
      });
      if (wrote) refresh();
    } catch (_) {
      // The list is perfectly usable with the names it already had.
    } finally { titleRunning = false; }
  }

  // The row markup every renderer shares, so a chat, a code task and a job all
  // behave identically under the cursor.
  function rowHtml({ title, preview, time, running, pinned }) {
    return `<span class="tc-history-line">`
      + `<span class="tc-history-name" data-history-name>${esc(title)}</span>`
      + (running ? '<span class="tc-history-dot" title="Running now" aria-label="Running now"></span>' : '')
      + (pinned ? '<i class="ph ph-push-pin tc-history-pin" aria-hidden="true"></i>' : '')
      + '</span>'
      + '<span class="tc-history-sub">'
      + `<span class="tc-history-preview">${esc(preview || '')}</span>`
      + `<span class="tc-history-meta" data-history-meta>${esc(relativeTime(time))}</span>`
      + '</span>';
  }

  function bind() {
    const collapse = document.getElementById('tc-history-collapse');
    if (collapse) collapse.addEventListener('click', () => { patchView({ collapsed: !view().collapsed }); applyCollapse(); });
    const filter = document.getElementById('tc-history-filter');
    if (filter) filter.addEventListener('click', event => { event.stopPropagation(); openFilterMenu(filter); });
    document.addEventListener('click', event => { if (menu && !event.target.closest('.tc-history-menu')) closeMenu(); });
    document.addEventListener('keydown', event => { if (event.key === 'Escape') { closeMenu(); hideTip(); } });
    window.addEventListener('scroll', hideTip, true);
    applyCollapse();
  }

  window.ThomasSidebarHistory = {
    decorate,
    rowHtml,
    relativeTime,
    dayLabel,
    looksRaw,
    overlay,
    view,
    displayTitle: id => (overlay()[id] || {}).title || '',
    onRefresh: fn => { refreshHook = typeof fn === 'function' ? fn : null; },
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', bind, { once: true });
  else bind();
})();
