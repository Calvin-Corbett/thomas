/* Inkwell core: namespace, API client with local-draft fallback, toasts. */
(function () {
  'use strict';

  const IW = {
    apiBase: '/api/plugins/inkwell',
    mode: 'select',          // select | text | draw | erase
    notes: [],
    reminders: [],
    insights: [],
    settings: { auto_smart: true, auto_create_reminders: true, mic_silence_s: 8 },
    activeNoteId: null,
    offline: false,          // true => persist to localStorage (draft mode)
    listeners: {},
  };
  window.IW = IW;

  IW.on = function (event, fn) {
    (IW.listeners[event] = IW.listeners[event] || []).push(fn);
  };
  IW.emit = function (event, payload) {
    (IW.listeners[event] || []).forEach((fn) => {
      try { fn(payload); } catch (err) { console.error('[inkwell]', event, err); }
    });
  };

  IW.uid = function () {
    return Math.random().toString(16).slice(2, 10) + Date.now().toString(16).slice(-4);
  };

  IW.debounce = function (fn, ms) {
    let timer = null;
    return function (...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), ms);
    };
  };

  IW.toast = function (message, kind) {
    const host = document.getElementById('toasts');
    if (!host) return;
    const el = document.createElement('div');
    el.className = 'iw-toast' + (kind ? ' iw-toast-' + kind : '');
    el.textContent = message;
    host.appendChild(el);
    setTimeout(() => el.classList.add('iw-toast-show'), 10);
    setTimeout(() => {
      el.classList.remove('iw-toast-show');
      setTimeout(() => el.remove(), 400);
    }, 4200);
  };

  // ---- API with local-draft fallback -------------------------------------

  const DRAFT_KEY = 'inkwell-local-draft';

  function readDraft() {
    try {
      const raw = localStorage.getItem(DRAFT_KEY);
      const data = raw ? JSON.parse(raw) : null;
      return data && typeof data === 'object'
        ? { notes: data.notes || [], reminders: data.reminders || [], insights: data.insights || [], settings: data.settings || null }
        : { notes: [], reminders: [], insights: [], settings: null };
    } catch (e) { return { notes: [], reminders: [], insights: [], settings: null }; }
  }

  function writeDraft() {
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify({ notes: IW.notes, reminders: IW.reminders, insights: IW.insights, settings: IW.settings }));
    } catch (e) { /* storage full/blocked: keep in memory */ }
  }
  IW.writeDraft = writeDraft;

  async function requestJson(url, options) {
    const response = await fetch(url, Object.assign({
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
    }, options));
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) {
      const detail = payload.error || response.statusText || ('HTTP ' + response.status);
      const err = new Error(detail);
      err.status = response.status;
      throw err;
    }
    return payload;
  }
  IW.requestJson = requestJson;

  IW.bootstrap = async function () {
    try {
      const payload = await requestJson(IW.apiBase + '/bootstrap');
      IW.notes = payload.state.notes || [];
      IW.reminders = payload.state.reminders || [];
      IW.insights = payload.state.insights || [];
      if (payload.state.settings) IW.settings = Object.assign(IW.settings, payload.state.settings);
      IW.offline = false;
    } catch (err) {
      const draft = readDraft();
      IW.notes = draft.notes;
      IW.reminders = draft.reminders;
      IW.insights = draft.insights || [];
      if (draft.settings) IW.settings = Object.assign(IW.settings, draft.settings);
      IW.offline = true;
      IW.toast('Thomas server not reachable — working in local draft mode.', 'warn');
    }
  };

  IW.createItem = async function (collection, body) {
    if (IW.offline) {
      const now = new Date().toISOString();
      const item = Object.assign({ id: IW.uid(), created_at: now, updated_at: now, fired_at: '' }, body);
      IW[collection].unshift(item);
      writeDraft();
      return item;
    }
    const payload = await requestJson(IW.apiBase + '/' + collection, {
      method: 'POST',
      body: JSON.stringify(body),
    });
    IW[collection].unshift(payload.item);
    return payload.item;
  };

  IW.patchItem = async function (collection, id, patch) {
    const items = IW[collection];
    const index = items.findIndex((row) => row.id === id);
    if (index >= 0) {
      items[index] = Object.assign({}, items[index], patch, { updated_at: new Date().toISOString() });
    }
    if (IW.offline) { writeDraft(); return items[index]; }
    const payload = await requestJson(IW.apiBase + '/' + collection + '/' + encodeURIComponent(id), {
      method: 'PATCH',
      body: JSON.stringify(patch),
    });
    if (index >= 0) items[index] = payload.item;
    return payload.item;
  };

  IW.deleteItem = async function (collection, id) {
    IW[collection] = IW[collection].filter((row) => row.id !== id);
    if (IW.offline) { writeDraft(); return; }
    await requestJson(IW.apiBase + '/' + collection + '/' + encodeURIComponent(id), { method: 'DELETE' });
  };

  IW.saveSettings = function (patch) {
    Object.assign(IW.settings, patch);
    if (IW.offline) { writeDraft(); return; }
    requestJson(IW.apiBase + '/settings', { method: 'PATCH', body: JSON.stringify(patch) })
      .catch((e) => IW.toast('Could not save settings: ' + e.message, 'warn'));
  };

  IW.activeNote = function () {
    return IW.notes.find((n) => n.id === IW.activeNoteId) || null;
  };

  // Local datetime string (YYYY-MM-DDTHH:MM) for the smart prompt + inputs.
  IW.localNow = function () {
    const d = new Date();
    const pad = (n) => String(n).padStart(2, '0');
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) +
      'T' + pad(d.getHours()) + ':' + pad(d.getMinutes());
  };
})();
