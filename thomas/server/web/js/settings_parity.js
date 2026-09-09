/* Settings cards added on 2026-09-05 (frontier parity), rendered at run time.
 *
 * settings.html sits over the size guard's hard limit, so these cards are not
 * in the markup: this script inserts them into the existing groups and wires
 * them. Two cards:
 *   - Tools > Sensitive sites: mode (pause | allow) + the person's own hosts,
 *     saved straight to advanced.tools on change.
 *   - Autonomy > Scheduled tasks: list / add / pause / resume / run / remove
 *     through /api/schedules, the same scheduler `thomas cron` drives.
 * Injected by the settings page handler; needs nothing from settings.html.
 */
(function () {
  'use strict';

  // How a scheduled task's last run went, from the run history the schedules
  // route has always returned. Until 2026-09-05 the card showed cron, status
  // and next time only, so a task that failed every night looked like one
  // that worked.
  function lastRunLine(task) {
    const runs = Array.isArray(task && task.run_history) ? task.run_history : [];
    const last = runs.length ? runs[runs.length - 1] : null;
    const stamp = (iso) => {
      const d = new Date(String(iso || ''));
      if (Number.isNaN(d.getTime())) return String(iso || '');
      const p = (n) => String(n).padStart(2, '0');
      return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())} UTC`;
    };
    if (!last) {
      const err = task && task.last_error ? ` · ${task.last_error}` : '';
      return `Never run yet${err}`;
    }
    const seconds = Math.round(Number(last.duration_ms || 0) / 1000);
    const head = `Last run: ${last.ok ? 'ok' : 'failed'} in ${seconds} s at ${stamp(last.finished_at)}`;
    return last.ok || !last.error ? head : `${head}: ${last.error}`;
  }
  if (typeof window !== 'undefined') window.ThomasSettingsParity = { lastRunLine };
  if (typeof document === 'undefined') return;
  if (window.__thomasSettingsParity) return;
  window.__thomasSettingsParity = true;

  const PREFERENCES_API = '/api/preferences';
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function wireSectionSaveButtons() {
    document.querySelectorAll('[data-save-section]').forEach((button) => {
      button.addEventListener('click', () => { void window.saveSection(button.dataset.saveSection); });
    });
  }

  async function syncSavedTheme() {
    let exactTheme = document.documentElement.dataset.thomasTheme || document.documentElement.dataset.theme || 'nebula';
    try { exactTheme = localStorage.getItem('thomas_chat_theme') || exactTheme; } catch (error) { /* localStorage is optional */ }
    exactTheme = String(exactTheme).trim().toLowerCase() || 'nebula';
    const apiTheme = ['light', 'sandstone'].includes(exactTheme) ? 'light' : 'dark';
    try {
      const response = await fetch(PREFERENCES_API);
      if (!response.ok) return;
      const preferences = await response.json();
      const legacy = (preferences.thomads && preferences.thomads.legacy_settings) || {};
      if ((preferences.appearance && preferences.appearance.theme) === apiTheme && legacy.theme === exactTheme) return;
      await fetch(PREFERENCES_API, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ appearance: { theme: apiTheme }, thomads: { legacy_settings: { ...legacy, theme: exactTheme } } }),
      });
    } catch (error) { console.error('Error synchronizing the saved theme:', error); }
  }

  function toast(message, type) {
    if (typeof window.showToast === 'function') { window.showToast(message, type); return; }
    let host = document.getElementById('thomas-parity-toast');
    if (!host) {
      host = document.createElement('div');
      host.id = 'thomas-parity-toast';
      host.setAttribute('role', 'status');
      host.style.cssText = 'position:fixed;right:16px;bottom:16px;z-index:9999;padding:10px 14px;border-radius:10px;background:#1b1d24;color:#fff;font:14px system-ui;box-shadow:0 8px 24px rgba(0,0,0,.25)';
      document.body.appendChild(host);
    }
    host.textContent = message;
    host.style.background = type === 'error' ? '#8b1e1e' : '#1b1d24';
    host.hidden = false;
    clearTimeout(host._t);
    host._t = setTimeout(() => { host.hidden = true; }, 3500);
  }

  wireSectionSaveButtons();
  void syncSavedTheme();

  function insertSensitiveSites() {
    const toggle = document.getElementById('allowBrowser');
    const row = toggle && toggle.closest('.setting-item');
    if (!row || document.getElementById('sensitiveSiteMode')) return;
    row.insertAdjacentHTML('afterend',
      '<div class="setting-item" id="sensitiveSitesItem"><div class="setting-label"><div class="setting-name">Sensitive sites</div>'
      + '<div class="setting-description">Banks, payment, government and health sites are built in. Thomas can look at them, but by default it pauses instead of clicking or typing there on its own. Add your own hosts below, one per line or comma-separated.</div></div>'
      + '<div class="setting-control"><select id="sensitiveSiteMode" class="dropdown-select" aria-label="What Thomas does on sensitive sites"><option value="pause">Pause and ask me</option><option value="allow">Act like any other site</option></select></div></div>'
      + '<div class="setting-item"><div class="setting-label"><div class="setting-name">My sensitive hosts</div>'
      + '<div class="setting-description">Extra hosts to treat as sensitive, e.g. payroll.mycompany.com. Subdomains match.</div></div>'
      + '<div class="setting-control"><input type="text" id="sensitiveSiteHosts" class="text-input" placeholder="payroll.mycompany.com, hr.example.org" aria-label="Extra sensitive hosts" /></div></div>');
  }

  async function wireSensitiveSites() {
    const modeEl = document.getElementById('sensitiveSiteMode');
    const hostsEl = document.getElementById('sensitiveSiteHosts');
    if (!modeEl || !hostsEl) return;
    try {
      const response = await fetch(PREFERENCES_API);
      if (response.ok) {
        const data = await response.json();
        const tools = (data && data.advanced && data.advanced.tools) || {};
        modeEl.value = tools.browser_sensitive_mode === 'allow' ? 'allow' : 'pause';
        hostsEl.value = tools.browser_sensitive_hosts || '';
      }
    } catch (error) { console.error('Error loading sensitive-site settings:', error); }
    async function save() {
      try {
        const response = await fetch(PREFERENCES_API, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ advanced: { tools: { browser_sensitive_mode: modeEl.value === 'allow' ? 'allow' : 'pause', browser_sensitive_hosts: hostsEl.value.trim() } } }),
        });
        if (!response.ok) throw new Error('Failed to save sensitive-site settings');
        toast(modeEl.value === 'allow' ? 'Thomas may now act on sensitive sites' : 'Thomas will pause on sensitive sites', 'success');
      } catch (error) {
        console.error('Error saving sensitive-site settings:', error);
        toast('Sensitive-site settings were not saved', 'error');
      }
    }
    modeEl.addEventListener('change', save);
    hostsEl.addEventListener('change', save);
  }

  // Reply speed: advanced.runtime.default_mode has always steered the V2 chat
  // route (half the context budget, fewer tools, lighter memory lookup on
  // "fast"); until 2026-09-05 no control anywhere could set it.
  function insertReplySpeed() {
    const level = document.getElementById('autonomyLevel');
    const row = level && level.closest('.setting-item');
    if (!row || document.getElementById('replySpeed')) return;
    row.insertAdjacentHTML('afterend',
      '<div class="setting-item" id="replySpeedItem"><div class="setting-label"><div class="setting-name">Reply speed</div>'
      + '<div class="setting-description">Fast gives quicker, lighter replies: half the context budget, fewer tools offered, a lighter memory lookup. Thinking is the opposite. Auto lets Thomas decide from your effort setting. The Fast pill under the chat composer overrides this for one browser.</div></div>'
      + '<div class="setting-control"><select id="replySpeed" class="dropdown-select" aria-label="Default reply speed">'
      + '<option value="auto">Auto</option><option value="fast">Fast</option><option value="thinking">Thinking</option></select></div></div>');
  }

  async function wireReplySpeed() {
    const el = document.getElementById('replySpeed');
    if (!el) return;
    try {
      const response = await fetch(PREFERENCES_API);
      if (response.ok) {
        const data = await response.json();
        const runtime = (data && data.advanced && data.advanced.runtime) || {};
        const mode = String(runtime.default_mode || 'auto');
        el.value = ['auto', 'fast', 'thinking'].includes(mode) ? mode : 'auto';
      }
    } catch (error) { console.error('Error loading reply speed:', error); }
    el.addEventListener('change', async () => {
      try {
        const response = await fetch(PREFERENCES_API, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ advanced: { runtime: { default_mode: el.value } } }),
        });
        if (!response.ok) throw new Error('Failed to save reply speed');
        toast('Reply speed: ' + el.options[el.selectedIndex].text, 'success');
      } catch (error) {
        console.error('Error saving reply speed:', error);
        toast('Reply speed was not saved', 'error');
      }
    });
  }

  function insertSchedules() {
    const panel = document.getElementById('autonomy');
    const buttons = panel && panel.querySelector('.button-group');
    if (!buttons || document.getElementById('schedulesGroup')) return;
    buttons.insertAdjacentHTML('beforebegin',
      '<div class="settings-group" id="schedulesGroup"><div class="group-title">Scheduled tasks</div>'
      + '<div class="setting-item"><div class="setting-label"><div class="setting-name">Run something on a schedule</div>'
      + '<div class="setting-description">Cron syntax, local time: <code>0 9 * * 1-5</code> is weekdays at 9:00. The same list the <code>thomas cron</code> command shows.</div></div></div>'
      + '<div class="setting-item" id="scheduleAddRow"><div class="setting-label" style="flex:1">'
      + '<input type="text" id="scheduleCron" class="text-input" placeholder="0 9 * * 1-5" aria-label="Cron expression" style="max-width:180px;margin-right:8px" />'
      + '<input type="text" id="scheduleTask" class="text-input" placeholder="What Thomas should do, e.g. Summarise my inbox" aria-label="Task text" style="min-width:280px" /></div>'
      + '<div class="setting-control"><button type="button" class="btn btn-primary" id="scheduleAdd">Add</button></div></div>'
      + '<div id="schedulesList" role="list" aria-label="Scheduled tasks"></div><div class="setting-description" id="schedulesNote"></div></div>');
  }

  async function wireSchedules() {
    const list = document.getElementById('schedulesList');
    const note = document.getElementById('schedulesNote');
    const addBtn = document.getElementById('scheduleAdd');
    const cronEl = document.getElementById('scheduleCron');
    const taskEl = document.getElementById('scheduleTask');
    if (!list || !addBtn || !cronEl || !taskEl) return;
    async function call(method, path, body) {
      const res = await fetch(path, { method, headers: body ? { 'Content-Type': 'application/json' } : {}, body: body ? JSON.stringify(body) : undefined });
      let data = {};
      try { data = await res.json(); } catch (_e) { /* no body */ }
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      return data;
    }
    async function refresh() {
      try {
        const data = await call('GET', '/api/schedules');
        const tasks = Array.isArray(data.tasks) ? data.tasks : [];
        if (!tasks.length) { list.innerHTML = '<div class="setting-description">Nothing scheduled yet.</div>'; }
        else {
          list.innerHTML = tasks.map((t) => `<div class="setting-item" role="listitem" data-schedule-id="${esc(t.id)}">`
            + `<div class="setting-label"><div class="setting-name">${esc(t.task || t.id)}</div>`
            + `<div class="setting-description"><code>${esc(t.cron)}</code> · ${esc(t.status || '')}${t.next_run ? ' · next ' + esc(t.next_run) : ''}</div>`
            + `<div class="setting-description" data-schedule-last-run>${esc(lastRunLine(t))}</div></div>`
            + '<div class="setting-control">'
            + `<button type="button" class="btn btn-secondary" data-schedule-action="${t.status === 'paused' ? 'resume' : 'pause'}">${t.status === 'paused' ? 'Resume' : 'Pause'}</button> `
            + '<button type="button" class="btn btn-secondary" data-schedule-action="run">Run now</button> '
            + `<button type="button" class="btn btn-secondary" data-schedule-action="remove" aria-label="Remove ${esc(t.id)}">Remove</button>`
            + '</div></div>').join('');
        }
        const h = data.health || {};
        note.textContent = h.running === false ? 'The scheduler is not running in this server; tasks are saved and will run when it is.' : '';
      } catch (error) {
        list.innerHTML = `<div class="setting-description">Could not load schedules: ${esc(error.message)}</div>`;
      }
    }
    addBtn.addEventListener('click', async () => {
      const cron = cronEl.value.trim(); const task = taskEl.value.trim();
      if (!cron || !task) { toast('Give both a cron expression and a task', 'error'); return; }
      try { await call('POST', '/api/schedules', { cron, task }); cronEl.value = ''; taskEl.value = ''; toast('Scheduled', 'success'); await refresh(); }
      catch (error) { toast(`Not scheduled: ${error.message}`, 'error'); }
    });
    list.addEventListener('click', async (event) => {
      const btn = event.target.closest('[data-schedule-action]');
      if (!btn) return;
      const row = btn.closest('[data-schedule-id]');
      const id = row && row.dataset.scheduleId;
      const action = btn.dataset.scheduleAction;
      if (!id) return;
      if (action === 'remove' && !window.confirm('Remove this schedule?')) return;
      try {
        if (action === 'remove') await call('DELETE', `/api/schedules/${encodeURIComponent(id)}`);
        else await call('POST', `/api/schedules/${encodeURIComponent(id)}/${action}`);
        await refresh();
      } catch (error) { toast(`That did not work: ${error.message}`, 'error'); }
    });
    await refresh();
  }

  function start() {
    insertSensitiveSites();
    insertReplySpeed();
    insertSchedules();
    wireSensitiveSites();
    wireReplySpeed();
    wireSchedules();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  window.ThomasSettingsParity = { insertSensitiveSites, insertReplySpeed, insertSchedules, lastRunLine };
})();
