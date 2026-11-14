/* The System page: what Thomas is doing and how he is, a page at a time.
 *
 * Seven pages, each one idea: Overview, Tasks, This PC, Plugins, Spend, Builds, About. Each asks only the routes it
 * needs, again every few seconds while it is the page on screen, and says so plainly when a route cannot be read
 * (its plugin may be off). Some things can be changed where you read them: a plugin's switch, a task's Stop, Retry
 * and Run now, and restarting Thomas. Every word that came from the server is escaped.
 */
(function () {
  'use strict';

  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const num = value => Number(value || 0).toLocaleString('en-US');
  const span = seconds => { const m = Math.floor(Math.max(0, Number(seconds) || 0) / 60); return m < 60 ? `${m} min` : m < 2880 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${Math.floor(m / 1440)} days`; };
  const SOURCES = { health: '/api/health', load: '/api/agents/vitals', room: '/api/machine/capacity', work: '/api/mission/control', plugins: '/api/plugins/thomas', spend: '/api/spend/today', builds: '/api/self/projects' };
  const data = {};
  let page = 'overview', filter = '', said = '', ready = false;

  async function read(key) {
    try { const answer = await fetch(SOURCES[key], { cache: 'no-store' }); data[key] = answer.ok ? await answer.json() : null; }
    catch (error) { data[key] = null; }
  }
  async function send(url) {
    const answer = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    const body = await answer.json().catch(() => ({}));
    if (!answer.ok || body.ok === false) throw new Error(body.error || `Thomas answered ${answer.status}.`);
    return body;
  }

  // ---- shapes -------------------------------------------------------------------------------------------------
  const figures = rows => `<div class="sy-figures">${rows.map(([value, label]) => `<div><b>${esc(value)}</b><span>${esc(label)}</span></div>`).join('')}</div>`;
  const missing = what => `<p class="sy-note">${esc(what)} could not be read just now. Its plugin may be turned off.</p>`;
  function ring(label, value, mark, hint) {
    const known = value != null && !Number.isNaN(Number(value));
    const part = known ? Math.min(100, Math.max(0, Number(value))) : 0, round = 2 * Math.PI * 64;
    const over = known && mark && part >= mark;
    return `<figure class="sy-ring"><svg viewBox="0 0 148 148" role="img" aria-label="${esc(label)} ${known ? Math.round(part) + ' percent' : 'not read yet'}"><circle class="is-track" cx="74" cy="74" r="64"/><circle class="is-value${over ? ' is-over' : ''}" cx="74" cy="74" r="64" stroke-dasharray="${round.toFixed(1)}" stroke-dashoffset="${(round * (1 - part / 100)).toFixed(1)}"/></svg><figcaption><b>${known ? Math.round(part) + '%' : '—'}</b><span>${esc(label)}</span></figcaption><p>${esc(hint || '')}</p></figure>`;
  }
  function spark(points, mark) {
    const list = (points || []).map(Number).filter(point => !Number.isNaN(point));
    if (list.length < 2) return '<p class="sy-note">Collecting readings…</p>';
    const path = list.map((point, index) => `${((index / (list.length - 1)) * 100).toFixed(1)},${(100 - Math.min(100, Math.max(0, point))).toFixed(1)}`).join(' ');
    return `<svg class="sy-spark" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">${mark ? `<line x1="0" x2="100" y1="${100 - mark}" y2="${100 - mark}" vector-effect="non-scaling-stroke"/>` : ''}<polyline points="${path}" vector-effect="non-scaling-stroke"/></svg>`;
  }
  function bars(rows) {
    const most = Math.max(1e-9, ...rows.map(row => row.value));
    return `<div class="sy-bars">${rows.map(row => `<div class="sy-bar"><span title="${esc(row.name)}">${esc(row.name)}</span><i><u style="width:${Math.round((row.value / most) * 100)}%"></u></i><b>${esc(row.text)}</b></div>`).join('')}</div>`;
  }
  const row = (title, text, small, actions) => `<div class="sy-row"><strong>${esc(title)}</strong>${actions ? `<div class="sy-do">${actions}</div>` : ''}<p>${esc(text || '')}${small ? ` <small>${esc(small)}</small>` : ''}</p></div>`;
  const head = (title, lede) => `<h2>${esc(title)}</h2><p class="sy-lede">${esc(lede)}</p>`;

  // ---- what the data says ---------------------------------------------------------------------------------------
  const tasks = () => ((data.work || {}).agents || []);
  const working = () => tasks().filter(task => /^(running|working|active|busy|in_progress)$/i.test(String(task.status || '')));
  const stalled = () => tasks().filter(task => task.stalled);
  const waiting = () => Number((((data.work || {}).approvals) || {}).pending_total || 0);
  const rows = () => ((data.plugins || {}).rows || []);
  const failed = () => rows().filter(plugin => plugin.state === 'failed');
  const limit = () => Number((((data.room || {}).load) || {}).limit_percent || 0);
  function needsYou() {
    const list = [];
    const restart = (data.health || {}).restart || {};
    if (restart.restarting) list.push(['Thomas is waiting to restart', `He restarts when the work that is running ends. Waiting ${span(restart.elapsed_s)}.`, 'about']);
    if (waiting()) list.push([`${waiting()} ${waiting() === 1 ? 'approval is' : 'approvals are'} waiting for you`, 'Thomas has stopped until you decide.', 'tasks']);
    stalled().forEach(task => list.push([`"${task.name || task.id}" has stalled`, `No sign of work for ${span(task.idle_s)}.`, 'tasks']));
    failed().forEach(plugin => list.push([`${plugin.title || plugin.id} failed to start`, plugin.error || '', 'plugins']));
    if ((data.health || {}).model_auth && data.health.model_auth.ok === false) list.push(['The model sign-in is not working', data.health.model_auth.remedy || data.health.model_auth.reason || '', 'about']);
    return list;
  }

  // ---- the pages ------------------------------------------------------------------------------------------------
  const PAGES = [
    { id: 'overview', name: 'Overview', needs: ['health', 'load', 'work', 'plugins'], badge: () => needsYou().length, draw() {
      const now = (data.load || {}).latest, need = needsYou(), on = rows().filter(plugin => plugin.state === 'active').length;
      const line = !ready ? 'Reading…' : !data.health ? 'Thomas is not answering right now.' : need.length ? `${need.length} ${need.length === 1 ? 'thing needs' : 'things need'} you.` : 'Everything is running. Nothing needs you.';
      return head('Overview', line)
        + figures([[working().length, 'tasks working'], [waiting(), 'waiting on you'], [now ? `${Math.round(now.cpu)}%` : '—', 'CPU in use'], [rows().length ? `${on} of ${rows().length}` : '—', 'plugins on']])
        + `<h3>Needs you</h3>${need.length ? `<div class="sy-list">${need.map(([title, text, to]) => row(title, text, '', `<button type="button" class="sy-btn" data-go="${to}">Look</button>`)).join('')}</div>` : '<p class="sy-note">Nothing right now.</p>'}`;
    } },
    { id: 'tasks', name: 'Tasks', needs: ['work'], badge: () => working().length, draw() {
      if (!data.work) return head('Tasks', 'What Thomas is working on.') + missing('The task list');
      const list = [...stalled(), ...tasks().filter(task => !task.stalled)].slice(0, 40);
      const act = task => (String(task.id).startsWith('job:') ? ['cancel:Stop', 'requeue:Retry', 'run_now:Run now'].map(pair => `<button type="button" class="sy-btn" data-job="${esc(task.id)}" data-verb="${pair.split(':')[0]}">${pair.split(':')[1]}</button>`).join('') : '');
      return head('Tasks', `${working().length} working, ${stalled().length} stalled, ${waiting()} waiting on you.`)
        + (list.length ? `<div class="sy-list">${list.map(task => row(task.name || task.id, task.summary || 'No description.', `${task.stalled ? 'stalled' : task.status || ''}${task.idle_s ? ` · quiet for ${span(task.idle_s)}` : ''}`, act(task))).join('')}</div>` : '<p class="sy-note">No tasks right now.</p>');
    } },
    { id: 'pc', name: 'This PC', needs: ['load', 'room'], draw() {
      if (!data.load) return head('This PC', 'How hard this computer is working.') + missing('The load');
      const now = data.load.latest || {}, cap = limit(), room = data.room || {};
      return head('This PC', cap ? `Thomas holds new work when CPU or memory reaches ${cap}%.` : 'How hard this computer is working.')
        + `<div class="sy-rings">${ring('CPU', now.cpu, cap, 'average of the last 20 seconds')}${ring('Memory', now.memory, cap, 'in use now')}</div>`
        + `<h3>CPU, last ten minutes</h3>${spark(data.load.cpu, cap)}<h3>Memory, last ten minutes</h3>${spark(data.load.memory, cap)}`
        + (room.cpus ? `<h3>The machine</h3>${figures([[room.cpus, 'processors'], [`${Math.round(Number(room.total_ram_bytes || 0) / 2 ** 30)} GB`, 'memory'], [room.max_concurrent_runs != null ? room.max_concurrent_runs : '—', 'tasks at once']])}` : '');
    } },
    { id: 'plugins', name: 'Plugins', needs: ['plugins'], badge: () => failed().length, draw() {
      if (!data.plugins) return head('Plugins', 'Each part of Thomas you can turn off.') + missing('The plugin list');
      const words = filter.trim().toLowerCase();
      const shown = rows().filter(plugin => !words || `${plugin.title} ${plugin.about} ${plugin.id}`.toLowerCase().includes(words));
      const on = rows().filter(plugin => plugin.state === 'active').length;
      return head('Plugins', `${on} on, ${rows().length - on} off. Turn one off and that part of Thomas stops; turn it on and it comes back.`)
        + `<input class="sy-search" type="search" data-filter value="${esc(filter)}" placeholder="Find a plugin" aria-label="Find a plugin">`
        + `<div class="sy-list">${shown.map(plugin => row(plugin.title || plugin.id, plugin.state === 'failed' ? `Failed to start: ${plugin.error || 'no reason given'}` : plugin.about || '', plugin.required ? 'always on' : plugin.state === 'loading' ? 'starting' : '',
          `<button type="button" class="sy-switch" role="switch" aria-checked="${plugin.state === 'active' || plugin.state === 'loading'}" aria-label="${esc(plugin.title || plugin.id)}" data-plugin="${esc(plugin.id)}"${plugin.required ? ' disabled' : ''}><i></i></button>`)).join('') || '<p class="sy-note">No plugin matches that.</p>'}</div>`;
    } },
    { id: 'spend', name: 'Spend', needs: ['spend'], draw() {
      const spend = data.spend;
      if (!spend) return head('Spend', 'What today has cost.') + missing('Spending');
      const tokens = spend.tokens && typeof spend.tokens === 'object' ? Number(spend.tokens.total || spend.tokens.total_tokens || 0) : Number(spend.tokens || 0);
      const models = Object.entries(spend.by_model || {}).map(([name, value]) => ({ name, value: Number(value && typeof value === 'object' ? value.usd || value.total_usd || 0 : value) || 0 })).sort((a, b) => b.value - a.value);
      return head('Spend', 'What today has cost, from each model\'s own receipts.')
        + figures([[`$${Number(spend.total_usd || 0).toFixed(2)}`, 'today'], [num(spend.call_count), 'model calls'], [tokens ? num(tokens) : '—', 'tokens']])
        + `<h3>By model</h3>${models.length ? bars(models.map(model => ({ name: model.name, value: model.value, text: `$${model.value.toFixed(2)}` }))) : '<p class="sy-note">Nothing spent yet today.</p>'}`;
    } },
    { id: 'builds', name: 'Builds', needs: ['builds'], draw() {
      const builds = data.builds;
      if (!builds || !Array.isArray(builds.projects)) return head('Builds', 'How Thomas\'s own builds are going.') + missing('The build list');
      if (builds.refreshing && !builds.projects.length) return head('Builds', 'How Thomas\'s own builds are going.') + '<p class="sy-note">Reading your tasks. This can take a minute after Thomas restarts.</p>';
      const list = builds.projects, by = test => list.filter(build => test.test(String(build.state || ''))).length;
      const times = list.map(build => Number((build.timings_seconds || {}).building) || 0).filter(Boolean);
      const average = times.length ? times.reduce((a, b) => a + b, 0) / times.length : 0;
      const recent = [...list].sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || ''))).slice(0, 8);
      return head('Builds', 'How Thomas\'s own builds are going.')
        + figures([[by(/^(running|repair round)/), 'working now'], [by(/^landed$/), 'landed'], [by(/^(stopped|refused)$/), 'stopped'], [average ? span(average) : '—', 'average build']])
        + `<h3>Most recent</h3><div class="sy-list">${recent.map(build => row(build.title || 'Untitled', build.detail || '', String(build.state || ''))).join('')}</div>`;
    } },
    { id: 'about', name: 'About', needs: ['health'], draw() {
      const health = data.health;
      if (!health) return head('About', 'Thomas is not answering right now.');
      const build = health.build || {}, restart = health.restart || {}, auth = health.model_auth || {};
      const fact = (name, value) => `<dt>${esc(name)}</dt><dd>${esc(value)}</dd>`;
      return head('About', 'What is running on this computer.')
        + `<dl class="sy-facts">${fact('Version', health.version || 'unknown')}${fact('Running', build.commit || 'unknown')}${fact('Newest on disk', build.stale ? `${build.latest_commit} (newer than what is running)` : 'the same')}${fact('Up for', span(health.uptime_s))}${fact('Model sign-in', auth.ok === false ? `Not working. ${auth.remedy || auth.reason || ''}` : 'Working')}${fact('Restart', restart.restarting ? `Waiting ${span(restart.elapsed_s)} for running work to end` : 'Not restarting')}</dl>`
        + `<h3>Restart</h3><p class="sy-note">Restarting loads the newest code. Work that is running is stopped and picked up again afterwards.</p><button type="button" class="sy-btn" data-restart${restart.restarting ? ' disabled' : ''}>Restart Thomas</button>`;
    } },
  ];

  // ---- drawing and doing ----------------------------------------------------------------------------------------
  const main = document.getElementById('sy-page'), tabs = document.getElementById('sy-pages'), updated = document.getElementById('sy-updated');
  const current = () => PAGES.find(entry => entry.id === page) || PAGES[0];
  function draw() {
    tabs.innerHTML = PAGES.map(entry => { const count = entry.badge ? entry.badge() : 0; return `<button type="button" class="sy-tab" role="tab" aria-selected="${entry.id === page}" data-go="${entry.id}">${esc(entry.name)}${count ? `<b>${count}</b>` : ''}</button>`; }).join('');
    // Typing in the search box is not interrupted by the next reading.
    if (main.contains(document.activeElement) && document.activeElement.matches('input') && main.dataset.page === page) return;
    main.dataset.page = page;
    main.innerHTML = `${current().draw()}<p class="sy-said" role="status">${esc(said)}</p>`;
  }
  async function refresh() {
    const wanted = new Set([...current().needs, 'health', 'work', 'plugins']);
    await Promise.all([...wanted].map(read));
    ready = true;
    updated.textContent = `Read ${new Date().toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' })}`;
    draw();
  }
  function go(next) { page = PAGES.some(entry => entry.id === next) ? next : 'overview'; said = ''; try { history.replaceState(null, '', `#${page}`); } catch (error) { /* a frame without history */ } draw(); void refresh(); }
  async function act(doing, done) {
    said = 'Working…'; draw();
    try { await doing(); said = done; } catch (error) { said = error && error.message ? error.message : 'Thomas did not take that.'; }
    await refresh();
  }

  document.addEventListener('click', event => {
    const target = event.target.closest('[data-go], [data-plugin], [data-job], [data-restart]');
    if (!target || target.disabled) return;
    if (target.dataset.go) go(target.dataset.go);
    else if (target.dataset.plugin) { const on = target.getAttribute('aria-checked') !== 'true'; void act(() => send(`/api/plugins/thomas/${encodeURIComponent(target.dataset.plugin)}/${on ? 'on' : 'off'}`), on ? 'Turned on.' : 'Turned off.'); }
    else if (target.dataset.job) void act(() => send(`/api/mission/jobs/${encodeURIComponent(target.dataset.job)}/${target.dataset.verb}`), 'Done.');
    else if (window.confirm('Restart Thomas now? Work that is running is stopped and picked up again afterwards.')) void act(() => send('/api/server/restart'), 'Restart asked for.');
  });
  document.addEventListener('input', event => { if (event.target.matches('[data-filter]')) { filter = event.target.value; const list = main.querySelector('.sy-list'); const made = document.createElement('div'); made.innerHTML = current().draw(); if (list && made.querySelector('.sy-list')) list.replaceWith(made.querySelector('.sy-list')); } });

  go((location.hash || '').slice(1) || 'overview');
  setInterval(() => { if (!document.hidden) void refresh(); }, 5000);
})();
