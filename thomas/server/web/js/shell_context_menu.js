/* Refresh-button context menu: one action, Restart server, shown step by step while it happens.

   You said (2026-11-07): right-clicking the reload button should offer only the restart (a left click already
   reloads), the item should light up under the pointer, and pressing it must show what is going on, because
   "it just sits there, and all of a sudden, nothing happens". The strip below the toolbar now says what Thomas
   is waiting for (runs, checks, elapsed time), when he is stopping and starting again, and when he is back on
   which commit; nothing here gives up on a clock, since a restart waits for running checks as long as they take. */
(function () {
  'use strict';

  const POLL_MS = 1000;
  // The server kept answering with the same pid and said no restart was under way for this long: it did not begin.
  // That is a refusal being noticed, not a limit on how long a real restart may take.
  const NOT_STARTED_MS = 10000;
  let menu = null;
  let restartButton = null;
  let strip = null;
  let initialPid = null;
  let initialUptime = null;
  let initialGeneration = null;
  let busy = false;

  function icon(name) {
    const node = document.createElement('i');
    node.className = 'ph ph-' + name;
    node.setAttribute('aria-hidden', 'true');
    return node;
  }

  function button(label, iconName, source, uiId) {
    const node = document.createElement('button');
    node.type = 'button';
    node.className = 'tc-shell-menu-item';
    node.dataset.uiId = uiId;
    node.dataset.uiLabel = label;
    node.dataset.uiPolicy = 'protected source-edit';
    node.dataset.redesignSource = source;
    node.append(icon(iconName));
    const text = document.createElement('span');
    text.className = 'tc-shell-menu-item-label';
    text.textContent = label;
    node.append(text);
    return node;
  }

  async function health() {
    const response = await fetch('/api/health', { cache: 'no-store' });
    if (!response.ok) throw new Error('Health check answered ' + response.status + '.');
    return response.json();
  }

  async function refreshIdentity() {
    try {
      const data = await health();
      initialPid = data.pid;
      initialUptime = Number(data.uptime_s);
      initialGeneration = data.restart && data.restart.generation ? String(data.restart.generation) : null;
    } catch (_) { initialPid = null; initialUptime = null; initialGeneration = null; }
  }

  function close(force) {
    if ((!force && busy) || !menu) return;
    menu.hidden = true;
  }

  function show(x, y) {
    restartButton.dataset.state = '';
    restartButton.querySelector('.tc-shell-menu-item-label').textContent = 'Restart server';
    restartButton.title = '';
    restartButton.setAttribute('aria-label', 'Restart server');
    menu.hidden = false;
    menu.style.left = '0px';
    menu.style.top = '0px';
    const rect = menu.getBoundingClientRect();
    menu.style.left = Math.max(8, Math.min(x, innerWidth - rect.width - 8)) + 'px';
    menu.style.top = Math.max(8, Math.min(y, innerHeight - rect.height - 8)) + 'px';
    refreshIdentity();
    menu.querySelector('.tc-shell-menu-item').focus();
  }

  async function restart() {
    if (busy) return { ok: false, error: 'A server restart is already in progress.' };
    busy = true;
    if (!menu) mount();
    await refreshIdentity();
    restartButton.dataset.state = 'restarting';
    const label = restartButton.querySelector('.tc-shell-menu-item-label');
    label.textContent = 'Restarting...';
    restartButton.disabled = true;
    let accepted = false;
    const started = Date.now();
    try {
      if (!initialPid || !Number.isFinite(initialUptime)) {
        throw new Error('Could not identify the current server. Retry when it answers.');
      }
      const response = await fetch('/api/server/restart', { method: 'POST' });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.ok === false) throw new Error(data.error || data.message || 'Restart request was rejected.');
      accepted = true;
      close(true);
      progress('Restart asked for. Waiting for Thomas to answer', 'draining', started);
      let notRestartingSince = null;
      for (;;) {
        await new Promise(resolve => setTimeout(resolve, POLL_MS));
        let next;
        try {
          next = await health();
        } catch (_) {
          // The handover gap: the old server has closed its port and the new one is not up yet.
          progress('Thomas is stopping and starting again', 'down', started);
          continue;
        }
        const uptime = Number(next.uptime_s);
        const generation = next.restart && next.restart.generation ? String(next.restart.generation) : null;
        const replaced = next.pid && next.pid !== initialPid;
        const rebootedInPlace = Number.isFinite(uptime) && Number.isFinite(initialUptime) && uptime + 1 < initialUptime;
        const newGeneration = initialGeneration && generation && generation !== initialGeneration;
        if (replaced || rebootedInPlace || newGeneration) {
          const build = next.build && next.build.commit ? ' on ' + next.build.commit : '';
          progress('Thomas is back' + build + '. Reloading this tab', 'up', started);
          label.textContent = 'Server answered';
          window.dispatchEvent(new CustomEvent('thomas:reload-current-tab'));
          busy = false;
          restartButton.disabled = false;
          close(true);
          setTimeout(hideProgress, 4000);
          return { ok: true, pid: next.pid, uptime_s: uptime };
        }
        const state = next.restart || {};
        if (state.restarting) {
          notRestartingSince = null;
          const waiting = Array.isArray(state.waiting_for) ? state.waiting_for.filter(Boolean) : [];
          const checks = Number(state.checks_running);
          let text = waiting.length ? 'Restarting Thomas: waiting for ' + waiting.join(', ') : 'Restarting Thomas: draining';
          if (Number.isFinite(checks) && checks > 0) text += ' (' + checks + (checks === 1 ? ' check' : ' checks') + ' running)';
          if (state.words) text += '. ' + String(state.words);
          progress(text, 'draining', started);
          continue;
        }
        if (notRestartingSince === null) notRestartingSince = Date.now();
        if (Date.now() - notRestartingSince >= NOT_STARTED_MS) {
          throw new Error('The restart did not begin: Thomas answers as before and reports no restart under way.');
        }
        progress('Restart asked for. Waiting for Thomas to answer', 'draining', started);
      }
    } catch (error) {
      const reason = error && error.message ? error.message : String(error);
      restartButton.dataset.state = 'failed';
      label.textContent = accepted ? 'Restart failed' : reason;
      restartButton.title = reason;
      restartButton.setAttribute('aria-label', reason);
      progress('Restart failed: ' + reason, 'failed', started);
      busy = false;
      restartButton.disabled = false;
      return { ok: false, error: reason, accepted };
    }
  }

  function elapsed(since) {
    const seconds = Math.max(0, Math.floor((Date.now() - since) / 1000));
    return seconds >= 60 ? Math.floor(seconds / 60) + 'm ' + (seconds % 60) + 's' : seconds + 's';
  }

  // The strip under the toolbar. It is what you watch; the menu item only names the action.
  function progress(text, state, since) {
    if (typeof document === 'undefined') return;
    if (!strip) {
      strip = document.createElement('div');
      strip.id = 'tc-restart-strip';
      strip.setAttribute('role', 'status');
      strip.setAttribute('aria-live', 'polite');
      const message = document.createElement('span');
      message.className = 'tc-restart-strip-text';
      const meter = document.createElement('span');
      meter.className = 'tc-restart-strip-meter';
      meter.setAttribute('aria-hidden', 'true');
      strip.append(message, meter);
      document.body.append(strip);
    }
    strip.hidden = false;
    strip.dataset.state = state;
    strip.querySelector('.tc-restart-strip-text').textContent = text + ' · ' + elapsed(since);
  }

  function hideProgress() {
    if (strip) strip.hidden = true;
  }

  // Self-edit Apply uses the exact same restart state, health handover, and
  // in-place tab reload as the refresh menu instead of growing a second path.
  window.ThomasShellRestart = restart;

  function createRestartAction() {
    const source = 'thomas/server/web/js/shell_context_menu.js';
    restartButton = button('Restart server', 'power', source, 'browser.context.restart');
    restartButton.dataset.menuAction = 'restart-server';
    restartButton.setAttribute('role', 'menuitem');
    restartButton.addEventListener('click', restart);
    return restartButton;
  }

  function mount() {
    menu = document.createElement('div');
    menu.className = 'tc-shell-menu';
    menu.hidden = true;
    menu.dataset.uiId = 'browser.context.menu';
    menu.dataset.menuLayout = 'flat';
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', 'Restart');
    menu.setAttribute('aria-orientation', 'vertical');
    // A left click on the reload button already reloads the tab, so the menu offers only what a left click cannot.
    menu.replaceChildren(createRestartAction());
    document.body.append(menu);

    // Keep the browser's normal context menu everywhere except the protected
    // refresh control, whose source-backed menu has one direct action.
    document.addEventListener('contextmenu', event => {
      const refreshButton = event.target.closest && event.target.closest('#bt-reload');
      if (!refreshButton) return;
      event.preventDefault();
      show(event.clientX, event.clientY);
    });
    document.addEventListener('pointerdown', event => {
      if (!menu.hidden && !menu.contains(event.target)) close();
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') close();
    });
    refreshIdentity();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, { once: true });
  else mount();
})();
