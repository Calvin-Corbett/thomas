(function () {
  'use strict';

  const MODES = {
    chat: { label: 'Chat', history: 'Recent chats', search: 'Search chats', create: 'New chat', prompt: 'Message Thomas…' },
    // Named "Build" to the user; the key stays `code` because it is the adapter
    // id, the surface-mode attribute and half the API's vocabulary.
    code: { label: 'Build', history: 'Recent tasks', search: 'Search tasks', create: 'New task', prompt: 'Message Thomas…' },
    work: { label: 'Work', history: 'Jobs', search: 'Search jobs', create: 'Create job', prompt: 'Describe the job or message this job…' },
  };
  const runtime = {
    mode: 'chat',
    adapterEntered: true,
    host: null,
    adapters: Object.create(null),
    switchGeneration: 0,
    transition: Promise.resolve(false),
  };

  function adapter(mode) { return runtime.adapters[mode] || null; }
  function byId(id) { return document.getElementById(id); }

  function refreshInBackground(mode, generation) {
    const current = adapter(mode);
    if (!current || !current.refresh) return;
    void Promise.resolve().then(() => current.refresh()).then(() => {
      if (generation === runtime.switchGeneration && mode === runtime.mode) {
        runtime.host && runtime.host.renderHistory && runtime.host.renderHistory();
      }
    }).catch(() => {
      if (generation === runtime.switchGeneration && mode === runtime.mode) {
        runtime.host && runtime.host.announce && runtime.host.announce(`Could not refresh ${MODES[mode].label}. Try again.`);
      }
    });
  }

  function updateChrome() {
    const cfg = MODES[runtime.mode];
    const shell = byId('tc-shell');
    if (shell) shell.dataset.surfaceMode = runtime.mode;
    document.querySelectorAll('[data-thomas-mode]').forEach(button => {
      const buttonMode = button.dataset.thomasMode;
      const active = button.dataset.thomasMode === runtime.mode;
      const running = isBusy(buttonMode);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
      button.setAttribute('tabindex', active ? '0' : '-1');
      button.classList.toggle('is-active', active);
      button.classList.toggle('is-running', running);
      if (running) button.setAttribute('data-running', 'true');
      else button.removeAttribute && button.removeAttribute('data-running');
    });
    const historyLabel = byId('tc-history-label');
    const search = byId('tc-search');
    const create = byId('tc-newchat');
    const input = byId('tc-input');
    if (historyLabel) historyLabel.textContent = cfg.history;
    if (search) search.placeholder = cfg.search;
    // One create control, above the search box. The pencil that used to sit in
    // the sidebar header did exactly the same thing.
    const plus = window.ThomasIcons ? window.ThomasIcons.glyph('plus', 14) : '';
    if (create) create.innerHTML = `<span aria-hidden="true" style="display:grid;place-items:center">${plus}</span> ${cfg.create}`;
    if (input) input.placeholder = cfg.prompt;
  }

  async function performModeSwitch(next, options, generation) {
    if (generation !== runtime.switchGeneration) return false;
    if (next === runtime.mode && runtime.adapterEntered && !(options && options.force)) return false;
    const previous = runtime.mode;
    const oldAdapter = adapter(previous);
    const nextAdapter = adapter(next);
    try {
      // A superseding request can arrive after leave disabled the surface.
      // Keep that fact separate from its mode label so returning re-enters it.
      const wasEntered = runtime.adapterEntered;
      runtime.adapterEntered = false;
      if (wasEntered && oldAdapter && oldAdapter.leave) await oldAdapter.leave();
      if (generation !== runtime.switchGeneration) return false;
      runtime.mode = next;
      updateChrome();
      runtime.host && runtime.host.modeChanged && runtime.host.modeChanged(next, previous);
      if (nextAdapter && nextAdapter.enter) await nextAdapter.enter(byId('tc-mode-surface'));
      runtime.adapterEntered = true;
      if (generation !== runtime.switchGeneration) return false;
      refreshInBackground(next, generation);
      runtime.host && runtime.host.renderHistory && runtime.host.renderHistory();
      if (options && options.focusTab) {
        const selected = document.querySelector(`[data-thomas-mode="${next}"]`);
        if (selected) selected.focus();
      } else {
        byId('tc-input') && byId('tc-input').focus();
      }
      return true;
    } catch (error) {
      runtime.adapterEntered = false;
      try {
        if (nextAdapter && nextAdapter.leave) await nextAdapter.leave();
      } catch (_) {
        // The rollback below is the authoritative recovery path.
      }
      runtime.mode = previous;
      updateChrome();
      try {
        runtime.host && runtime.host.modeChanged && runtime.host.modeChanged(previous, next);
        if (oldAdapter && oldAdapter.enter) await oldAdapter.enter(byId('tc-mode-surface'));
        runtime.adapterEntered = true;
        refreshInBackground(previous, generation);
        runtime.host && runtime.host.renderHistory && runtime.host.renderHistory();
      } catch (_) {
        // Keep the shell on the last known mode even when adapter recovery fails.
      }
      runtime.host && runtime.host.announce && runtime.host.announce(`Could not open ${MODES[next].label}. Try again.`);
      return false;
    }
  }

  function setMode(mode, options) {
    const next = String(mode || '').toLowerCase();
    if (!MODES[next]) return Promise.resolve(false);
    const generation = ++runtime.switchGeneration;
    runtime.transition = runtime.transition
      .catch(() => false)
      .then(() => performModeSwitch(next, options || {}, generation));
    return runtime.transition;
  }

  function registerAdapter(mode, value) {
    const key = String(mode || '').toLowerCase();
    if (!MODES[key] || key === 'chat') throw new Error('Only Code and Work adapters can be registered.');
    runtime.adapters[key] = value || {};
  }

  function renderHistory(wrap, query) {
    if (runtime.mode === 'chat') return false;
    const current = adapter(runtime.mode);
    if (!current || !current.renderHistory) {
      wrap.innerHTML = '<div class="tc-mode-empty">This mode is still loading.</div>';
      return true;
    }
    current.renderHistory(wrap, String(query || ''));
    return true;
  }

  function send(text, context) {
    if (runtime.mode === 'chat') return false;
    const current = adapter(runtime.mode);
    if (!current || !current.send) return false;
    // The composer clears only when the mode took the message. An adapter that
    // answers `false` has refused it and said why on its own surface, so the
    // words stay in the box; anything else (a promise included) is a yes.
    return current.send(String(text || ''), context || {}) === false ? 'refused' : true;
  }

  function isBusy(mode) {
    const key = String(mode || runtime.mode).toLowerCase();
    if (key === 'chat') return !!(runtime.host && runtime.host.isBusy && runtime.host.isBusy());
    const current = adapter(key);
    return !!(current && current.isBusy && current.isBusy());
  }

  function stop() {
    if (runtime.mode === 'chat') return false;
    const current = adapter(runtime.mode);
    if (!current || !current.stop || !isBusy()) return false;
    current.stop();
    return true;
  }

  function pickProject() {
    if (runtime.mode !== 'code') return false;
    const current = adapter('code');
    if (!current || !current.pickProject) return false;
    current.pickProject();
    return true;
  }

  function newConversation(projectRoot, projectLabel, options) {
    if (runtime.mode === 'chat') return false;
    const current = adapter(runtime.mode);
    // Forward the arguments: the library picker names the project it chose, and
    // dropping them here silently re-bound whatever was already selected.
    if (current && current.newConversation) return current.newConversation(projectRoot, projectLabel, options);
    return false;
  }

  function connect(host) {
    runtime.host = host || {};
    document.querySelectorAll('[data-thomas-mode]').forEach(button => {
      button.addEventListener('click', () => { void setMode(button.dataset.thomasMode); });
      button.addEventListener('keydown', event => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const keys = Object.keys(MODES);
        let index = keys.indexOf(runtime.mode);
        if (event.key === 'Home') index = 0;
        else if (event.key === 'End') index = keys.length - 1;
        else index = (index + (event.key === 'ArrowRight' ? 1 : -1) + keys.length) % keys.length;
        void setMode(keys[index], { focusTab: true });
      });
    });
    runtime.mode = 'chat';
    updateChrome();
    try {
      const initial = new URLSearchParams(location.search).get('tab_mode');
      if (initial && MODES[initial] && initial !== 'chat') void setMode(initial);
    } catch (_) { /* A standalone shell starts in Chat. */ }
  }

  window.ThomasUnifiedModes = {
    connect,
    isBusy,
    mode: () => runtime.mode,
    newConversation,
    pickProject,
    refreshChrome: updateChrome,
    registerAdapter,
    renderHistory,
    send,
    setMode,
    stop,
    host: () => runtime.host,
  };
})();
