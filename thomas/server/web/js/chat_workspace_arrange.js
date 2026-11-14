/* Arrange the Workspaces list: drag a row to reorder it, right-click to rename or
   remove it, and bring removed ones back from the "Hidden" row at the bottom.

   The list itself is built by chat_workspace_navigation.js; this file only decides
   what order it comes in, what each row is called, and which rows are hidden, and
   wires the gestures. Choices are saved in this browser (localStorage), the same
   trade sidebar_history.js makes for chat rows: they do not follow you to another
   machine, and the menu says so. Hiding a row deletes nothing. Uninstall, on a
   workspace that came from Marketplace, is asked for here and done by
   chat_workspace_navigation.js: this file never calls the server. */
(function () {
  'use strict';

  const KEY = 'thomas.workspaces.arrange.v1';

  function read() {
    const blank = { order: [], names: {}, hidden: [] };
    try {
      const raw = JSON.parse(localStorage.getItem(KEY) || 'null');
      if (!raw || typeof raw !== 'object') return blank;
      return {
        order: Array.isArray(raw.order) ? raw.order.map(String) : [],
        names: raw.names && typeof raw.names === 'object' && !Array.isArray(raw.names) ? raw.names : {},
        hidden: Array.isArray(raw.hidden) ? raw.hidden.map(String) : [],
      };
    } catch (_) { return blank; }
  }

  function write(state) {
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (_) { /* a list order is not worth failing over */ }
  }

  const esc = (text) => String(text).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // The rows to show, in the saved order. A workspace the saved order has never
  // seen (a newly installed plugin, such as Phone) goes after the ones you placed,
  // so it appears without you having to look for it.
  function arrange(list) {
    const state = read();
    const rank = new Map(state.order.map((mode, index) => [mode, index]));
    const placed = list.filter((w) => rank.has(w.mode)).sort((a, b) => rank.get(a.mode) - rank.get(b.mode));
    const fresh = list.filter((w) => !rank.has(w.mode));
    return placed.concat(fresh)
      .filter((w) => !state.hidden.includes(w.mode))
      .map((w) => Object.assign({}, w, { defaultLabel: w.label, label: String(state.names[w.mode] || w.label) }));
  }

  function hiddenOf(list) {
    const state = read();
    return list.filter((w) => state.hidden.includes(w.mode));
  }

  // Save the visible order as shown, with hidden rows kept after it.
  function saveOrder(visibleModes) {
    const state = read();
    state.order = visibleModes.concat(state.hidden.filter((m) => !visibleModes.includes(m)));
    write(state);
  }

  let menu = null;
  function closeMenu() {
    if (menu) { menu.remove(); menu = null; }
  }

  function placeMenu(x, y) {
    document.body.appendChild(menu);
    const box = menu.getBoundingClientRect();
    menu.style.left = `${Math.max(8, Math.min(window.innerWidth - box.width - 8, x))}px`;
    menu.style.top = `${Math.max(8, Math.min(window.innerHeight - box.height - 8, y))}px`;
    const first = menu.querySelector('button');
    if (first) first.focus();
  }

  function openMenu(x, y, title, items, onPick) {
    closeMenu();
    menu = document.createElement('div');
    menu.className = 'tc-history-menu tc-ws-menu';
    menu.setAttribute('role', 'menu');
    menu.innerHTML = `<div class="tc-history-menu-title">${esc(title)}</div>`
      + items.map((item) => (item.note
        ? `<div class="tc-history-menu-note">${esc(item.note)}</div>`
        : `<button type="button" role="menuitem" data-ws-action="${esc(item.action)}"${item.mode ? ` data-ws-mode="${esc(item.mode)}"` : ''} class="${item.danger ? 'is-danger' : ''}">${esc(item.label)}</button>`)).join('');
    menu.addEventListener('click', (event) => {
      const button = event.target.closest('[data-ws-action]');
      if (!button) return;
      event.preventDefault();
      const action = button.dataset.wsAction;
      const mode = button.dataset.wsMode || '';
      closeMenu();
      onPick(action, mode);
    });
    placeMenu(x, y);
  }

  function visibleModes(wrap) {
    return [...wrap.querySelectorAll('button[data-mode]')].map((b) => b.dataset.mode);
  }

  function move(wrap, mode, delta, rerender) {
    const modes = visibleModes(wrap);
    const from = modes.indexOf(mode);
    const to = from + delta;
    if (from < 0 || to < 0 || to >= modes.length) return;
    modes.splice(to, 0, modes.splice(from, 1)[0]);
    saveOrder(modes);
    rerender();
    const again = wrap.querySelector(`button[data-mode="${CSS.escape(mode)}"]`);
    if (again) again.focus();
  }

  function hide(mode, rerender) {
    const state = read();
    if (!state.hidden.includes(mode)) state.hidden.push(mode);
    write(state);
    rerender();
  }

  function show(mode, rerender) {
    const state = read();
    state.hidden = state.hidden.filter((m) => m !== mode);
    write(state);
    rerender();
  }

  function reset(rerender) {
    write({ order: [], names: {}, hidden: [] });
    rerender();
  }

  // Rename in place. Enter or leaving the box keeps the name, Escape drops it, and
  // an empty name (or the original) puts the original back.
  function rename(button, rerender) {
    const label = button.querySelector('span');
    if (!label || button.querySelector('input')) return;
    const mode = button.dataset.mode;
    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'tc-ws-rename';
    input.value = label.textContent;
    input.maxLength = 40;
    input.setAttribute('aria-label', 'Workspace name');
    button.draggable = false;
    label.replaceWith(input);
    input.focus();
    input.select();
    let done = false;
    const finish = (keep) => {
      if (done) return;
      done = true;
      if (keep) {
        const next = input.value.trim();
        const state = read();
        if (!next || next === button.dataset.defaultLabel) delete state.names[mode];
        else state.names[mode] = next;
        write(state);
      }
      rerender();
    };
    input.addEventListener('keydown', (event) => {
      event.stopPropagation();
      if (event.key === 'Enter') { event.preventDefault(); finish(true); }
      else if (event.key === 'Escape') { event.preventDefault(); finish(false); }
    });
    input.addEventListener('blur', () => finish(true));
    input.addEventListener('click', (event) => event.stopPropagation());
  }

  function rowMenu(wrap, button, x, y, rerender) {
    const mode = button.dataset.mode;
    const renamed = !!read().names[mode];
    const modes = visibleModes(wrap);
    const index = modes.indexOf(mode);
    const items = [{ action: 'rename', label: 'Rename' }];
    if (renamed) items.push({ action: 'unname', label: `Use the original name (${button.dataset.defaultLabel})` });
    if (index > 0) items.push({ action: 'up', label: 'Move up' });
    if (index < modes.length - 1) items.push({ action: 'down', label: 'Move down' });
    // Every workspace is a plugin and can be uninstalled from here. Marketplace is the one row without an id: it
    // is where the others are installed again, so it can only be hidden, and it says so.
    const pluginId = button.dataset.pluginId || '';
    if (pluginId) {
      items.push({ action: 'uninstall', label: 'Uninstall', danger: true });
      items.push({ note: 'Uninstalling removes it from Thomas. What you made with it is kept, and Marketplace has it to install again.' });
      items.push({ action: 'hide', label: 'Only hide it from this list' });
    } else {
      items.push({ action: 'hide', label: 'Hide from list', danger: true });
      items.push({ note: 'Marketplace is where the others are installed again, so it is not uninstalled; hiding it takes it off this list.' });
    }
    items.push({ note: 'Order, names and hidden rows are saved in this browser.' });
    openMenu(x, y, button.querySelector('span') ? button.querySelector('span').textContent : mode, items, (action) => {
      if (action === 'rename') rename(button, rerender);
      else if (action === 'unname') {
        const state = read();
        delete state.names[mode];
        write(state);
        rerender();
      } else if (action === 'up') move(wrap, mode, -1, rerender);
      else if (action === 'down') move(wrap, mode, 1, rerender);
      else if (action === 'hide') hide(mode, rerender);
      // Asked for, not done here: this file only arranges. chat_workspace_navigation.js talks to the server.
      else if (action === 'uninstall') {
        window.dispatchEvent(new CustomEvent('thomas:workspace:uninstall', {
          detail: { mode, pluginId, label: button.dataset.defaultLabel || mode },
        }));
      }
    });
  }

  // The bottom row: only present when something is hidden, and the way back.
  // Rename, move and remove were behind a right-click that nothing on screen mentioned, so removing a workspace
  // looked impossible. Each row carries a "⋯" that shows when you point at the row or reach it with the keyboard and
  // opens the same menu. It is a span, not a button, because the row itself is the button it sits in.
  function addMore(wrap, rerender) {
    if (!document.getElementById('tc-ws-more-style')) {
      const style = document.createElement('style');
      style.id = 'tc-ws-more-style';
      style.textContent = '.tc-ws-more{margin-left:auto;flex:none;padding:0 6px;border-radius:6px;line-height:18px;letter-spacing:1px;color:var(--c-muted,#8a8f98);opacity:0;cursor:pointer}'
        + 'button[data-mode]:hover .tc-ws-more,button[data-mode]:focus-visible .tc-ws-more,.tc-ws-more:focus-visible{opacity:1}'
        + '.tc-ws-more:hover,.tc-ws-more:focus-visible{background:var(--c-surface-2,rgba(127,127,127,.18));color:var(--c-text,inherit);outline:none}';
      document.head.appendChild(style);
    }
    wrap.querySelectorAll('button[data-mode]').forEach((button) => {
      if (button.querySelector('.tc-ws-more')) return;
      const name = button.querySelector('span') ? button.querySelector('span').textContent : button.dataset.mode;
      const more = document.createElement('span');
      more.className = 'tc-ws-more';
      more.setAttribute('role', 'button');
      more.setAttribute('tabindex', '0');
      more.setAttribute('aria-haspopup', 'menu');
      more.setAttribute('aria-label', `Rename, move or remove ${name}`);
      more.title = 'Rename, move or remove';
      more.textContent = '⋯';
      const open = (event) => {
        event.preventDefault();
        event.stopPropagation();
        const box = more.getBoundingClientRect();
        rowMenu(wrap, button, box.left, box.bottom + 4, rerender);
      };
      more.addEventListener('click', open);
      more.addEventListener('keydown', (event) => { if (event.key === 'Enter' || event.key === ' ') open(event); });
      button.appendChild(more);
    });
  }

  function footer(wrap, list, rerender) {
    addMore(wrap, rerender);
    const hidden = hiddenOf(list);
    if (!hidden.length) return;
    const row = document.createElement('button');
    row.type = 'button';
    row.className = 'tc-ws-restore hv-soft';
    // "1 hidden" read as a fault. It says what happened and what the row is for.
    row.textContent = `${hidden.length} removed · bring back`;
    row.title = 'Workspaces you removed from this list. Press to bring one back.';
    row.addEventListener('click', () => {
      const box = row.getBoundingClientRect();
      const items = hidden.map((w) => ({ action: 'show', mode: w.mode, label: `Show ${w.label}` }));
      items.push({ action: 'reset', label: 'Reset order, names and removals' });
      openMenu(box.left, box.top - 8 - 34 * (items.length + 1), 'Removed workspaces', items, (action, mode) => {
        if (action === 'show') show(mode, rerender);
        else if (action === 'reset') reset(rerender);
      });
    });
    wrap.appendChild(row);
  }

  // Wire the gestures once. Delegated on the list, so re-rendering rows never
  // loses them.
  function attach(wrap, rerender) {
    if (wrap.dataset.arrangeReady === '1') return;
    wrap.dataset.arrangeReady = '1';
    let dragging = '';

    const clearMarks = () => wrap.querySelectorAll('.is-drop-before, .is-drop-after, .is-dragging')
      .forEach((el) => el.classList.remove('is-drop-before', 'is-drop-after', 'is-dragging'));
    const rowOf = (event) => (event.target.closest ? event.target.closest('button[data-mode]') : null);

    wrap.addEventListener('contextmenu', (event) => {
      const button = rowOf(event);
      if (!button) return;
      event.preventDefault();
      rowMenu(wrap, button, event.clientX, event.clientY, rerender);
    });

    wrap.addEventListener('dragstart', (event) => {
      const button = rowOf(event);
      if (!button) return;
      closeMenu();
      dragging = button.dataset.mode;
      button.classList.add('is-dragging');
      event.dataTransfer.effectAllowed = 'move';
      try { event.dataTransfer.setData('text/plain', dragging); } catch (_) { /* some hosts refuse; the mode is held above */ }
    });

    wrap.addEventListener('dragover', (event) => {
      if (!dragging) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = 'move';
      // The list scrolls; dragging near its edge scrolls it, so a row can be
      // carried past what is on screen.
      const edge = wrap.getBoundingClientRect();
      if (event.clientY < edge.top + 24) wrap.scrollTop -= 14;
      else if (event.clientY > edge.bottom - 24) wrap.scrollTop += 14;
      wrap.querySelectorAll('.is-drop-before, .is-drop-after').forEach((el) => el.classList.remove('is-drop-before', 'is-drop-after'));
      const over = rowOf(event);
      if (!over || over.dataset.mode === dragging) return;
      const box = over.getBoundingClientRect();
      over.classList.add(event.clientY < box.top + box.height / 2 ? 'is-drop-before' : 'is-drop-after');
    });

    wrap.addEventListener('drop', (event) => {
      if (!dragging) return;
      event.preventDefault();
      const over = rowOf(event);
      const modes = visibleModes(wrap).filter((m) => m !== dragging);
      if (over && over.dataset.mode !== dragging) {
        const box = over.getBoundingClientRect();
        const at = modes.indexOf(over.dataset.mode) + (event.clientY < box.top + box.height / 2 ? 0 : 1);
        modes.splice(at, 0, dragging);
      } else {
        // Dropped on the empty space below the rows: to the end.
        modes.push(dragging);
      }
      dragging = '';
      clearMarks();
      saveOrder(modes);
      rerender();
    });

    wrap.addEventListener('dragend', () => { dragging = ''; clearMarks(); });

    // The keyboard path to the same things: Alt+Up/Down moves a row, F2 renames it.
    wrap.addEventListener('keydown', (event) => {
      const button = rowOf(event);
      if (!button || event.target.tagName === 'INPUT') return;
      if (event.altKey && (event.key === 'ArrowUp' || event.key === 'ArrowDown')) {
        event.preventDefault();
        move(wrap, button.dataset.mode, event.key === 'ArrowUp' ? -1 : 1, rerender);
      } else if (event.key === 'F2') {
        event.preventDefault();
        rename(button, rerender);
      }
    });

    document.addEventListener('pointerdown', (event) => {
      if (menu && !menu.contains(event.target)) closeMenu();
    }, true);
    document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeMenu(); });
    window.addEventListener('blur', closeMenu);
  }

  window.ThomasWorkspaceArrange = { arrange, attach, footer, hiddenOf };
})();
