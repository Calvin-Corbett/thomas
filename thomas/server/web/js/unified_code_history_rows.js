/* unified_code_history_rows.js -- the Build task list in the sidebar, kept up to date without being rebuilt.

   Opening a task used to throw the whole list away and build it again (850 rows, about 4,000 nodes, several times per
   click), which is why the left side flickered as if the page had reloaded. A row now keeps its element while what it
   shows is unchanged: only the rows whose title, time, activity or highlight changed are built again. Sorting, headings
   and the hover and menu behaviour still come from ThomasSidebarHistory.decorate, as before. */
(function () {
  'use strict';

  function build(row, look, active, running, ctx) {
    const { history, esc } = ctx;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'tc-mode-history-row';
    const title = row.title || 'Untitled task';
    // Last TOUCHED, not last opened: these arrive as ISO strings, so Number() would yield NaN.
    const stamp = Date.parse(row.updated_at || row.updatedAt || '') || 0;
    const created = Date.parse(row.created_at || '') || stamp;
    button.dataset.historyId = String(row.id || '');
    button.dataset.historyTitle = title;
    button.dataset.historyTime = String(stamp);
    button.dataset.historyCreated = String(created);
    button.dataset.historyMode = 'code';
    button.innerHTML = history
      ? history.rowHtml({ title, time: stamp, running, preview: look.preview })
      : `<span>${esc(title)}</span>`;
    if (active) button.classList.add('is-active');
    if (look.className) button.classList.add(look.className);
    // Rows stay clickable while a run is live: switching parks the run.
    button.addEventListener('click', () => ctx.open(row.id));
    return button;
  }

  function render(root, rows, ctx) {
    const { state, controls } = ctx;
    // Where the existing rows cannot be looked at (a stand-in page in a test), every row is simply built fresh.
    const canReuse = typeof root.querySelectorAll === 'function';
    const kept = new Map();
    if (canReuse) {
      root.querySelectorAll(':scope > [data-history-id]').forEach(node => kept.set(node.dataset.historyId, node));
      root.querySelectorAll(':scope > .tc-mode-empty').forEach(node => node.remove());
    } else {
      root.innerHTML = '';
    }
    if (!rows.length) {
      root.innerHTML = `<div class="tc-mode-empty">${ctx.esc(ctx.emptyMessage)}</div>`;
    } else {
      const live = new Set();
      const signatures = [];
      rows.forEach(row => {
        const id = String(row.id || '');
        const active = row.id === state.activeId;
        const running = active && state.running;
        const look = controls.historyRow(row, active);
        const signature = [row.title, row.updated_at || row.updatedAt, row.created_at, active ? 1 : 0, running ? 1 : 0, look.preview, look.className].join('␟');
        signatures.push(signature);
        let node = kept.get(id);
        if (!node || node.dataset.sig !== signature) {
          const fresh = build(row, look, active, running, ctx);
          fresh.dataset.sig = signature;
          if (node) node.replaceWith(fresh);
          node = fresh;
        }
        live.add(node);
        if (node.parentNode !== root) root.appendChild(node);
      });
      if (canReuse) kept.forEach(node => { if (!live.has(node) && node.parentNode === root) node.remove(); });
      // The same list as the last draw (the search word, every row's content and the highlighted one): nothing to sort
      // or relabel, so the 650 rows are left exactly where they are. Renaming, pinning and sorting go through their
      // own refresh, not through here.
      const listSignature = ctx.term + '␞' + signatures.join('␞');
      if (canReuse && root.dataset.listSig === listSignature && kept.size === rows.length) return;
      if (root.dataset) root.dataset.listSig = listSignature;
    }
    if (ctx.history) ctx.history.decorate(root);
  }

  window.ThomasCodeHistoryRows = { render };
}());
