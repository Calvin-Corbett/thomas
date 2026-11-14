/* What an empty Build shows instead of a question (window.ThomasCodeHome): a slideshow that turns slowly by itself.
 *
 * Slides: how Thomas is doing, how fast he is going, work per day, tokens, what he has noticed (each with a button that
 * starts something), your recent tasks (click one to go to it), and ideas drawn from what you have been working on.
 * The numbers are your task list (with each task's own timings) and the usage each run records, read once a minute at
 * most. A slide with nothing real to say says so instead of showing a made-up number.
 *
 * Hover the show to stop it turning and to see the arrows; the arrows, the dots and the left and right keys move it.
 */
(function () {
  'use strict';

  const TURN_MS = 9000;
  const FRESH_MS = 60000;
  const ORDER = ['stats', 'perf', 'perday', 'tokens', 'noticed', 'recent', 'ideas'];
  const TITLES = { stats: 'How Thomas is doing', perf: 'How fast Thomas is going', perday: 'Tasks worked on, last 7 days', tokens: 'Tokens, last 7 days', noticed: 'What Thomas has noticed', recent: 'Your recent tasks', ideas: 'Where to go next' };
  let cache = { at: 0, projects: null, perf: null, loading: null };
  let fallbackIdeas = [];

  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
  const when = iso => { const t = Date.parse(iso || ''); return Number.isFinite(t) ? t : 0; };
  const ago = ms => {
    const s = Math.max(0, Math.floor((Date.now() - ms) / 1000));
    return s < 90 ? 'just now' : s < 5400 ? `${Math.round(s / 60)} min ago` : s < 129600 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} days ago`;
  };
  const num = value => Number(value || 0).toLocaleString('en-US');
  const day = ms => { const d = new Date(ms); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
  const span = sec => (sec < 90 ? `${Math.round(sec)}s` : sec < 5400 ? `${Math.round(sec / 60)}m` : `${Math.floor(sec / 3600)}h ${String(Math.round((sec % 3600) / 60)).padStart(2, '0')}m`);
  const lastDays = count => Array.from({ length: count }, (_, i) => day(Date.now() - (count - 1 - i) * 86400000));
  const clip = (text, n) => { const t = String(text || 'Untitled').replace(/\s+/g, ' ').trim(); return t.length > n ? `${t.slice(0, n - 1)}…` : t; };
  const mean = list => (list.length ? list.reduce((a, b) => a + b, 0) / list.length : 0);
  const built = p => (p && p.timings_seconds && Number(p.timings_seconds.building) > 0 ? Number(p.timings_seconds.building) : 0);

  const get = async url => { try { const r = await fetch(url); return r.ok ? await r.json() : null; } catch (error) { return null; } };
  const usage = { seen: null, at: 0, pending: false };
  function readUsage() {
    if (usage.pending || Date.now() - usage.at < FRESH_MS) return;
    usage.pending = true;
    get('/api/evolve/agent/performance?days=7').then(perf => {
      usage.seen = perf;
      usage.at = Date.now();
      usage.pending = false;
      if (cache.projects) { cache.perf = perf && perf.ok ? perf : null; cache.perfPending = false; }
      // Draw it into whichever slideshow is on screen, without waiting for the next minute's reading.
      if (typeof document !== 'undefined') document.querySelectorAll('[data-code-home][data-home-ready]').forEach(root => hydrate(root));
    });
  }

  async function load() {
    if (Date.now() - cache.at < FRESH_MS && cache.projects) return cache;
    if (cache.loading) return cache.loading;
    // The two answers are asked for apart. The slides used to wait for both, so the slower one (reading a week of
    // run files) held back the task slides that never needed it. Usage fills its own slide when it arrives.
    readUsage();
    cache.loading = get('/api/self/projects').then(projects => {
      const perf = usage.seen;
      const list = projects && Array.isArray(projects.projects) ? projects.projects : [];
      // The server is still reading the task list after a start: an empty answer then is "not yet", not "none".
      const pending = !projects || (projects.refreshing === true && !list.length);
      const made = { at: pending ? 0 : Date.now(), projects: list, perf: perf && perf.ok ? perf : null, perfPending: usage.pending, pending, failed: !projects, loading: null };
      cache = pending ? { at: 0, projects: null, perf: null, loading: null } : made;
      return made;
    });
    return cache.loading;
  }

  // A bar per day with its number above it, so a bar is never a guess.
  function bars(rows, label) {
    const max = Math.max(1, ...rows.map(row => row.value));
    const cells = rows.map(row => `<div class="tc-home-bar" title="${esc(`${row.day}: ${num(row.value)}`)}"><em>${row.value ? esc(row.text || num(row.value)) : ''}</em><i style="height:${Math.round((row.value / max) * 100)}%"></i><span>${esc(row.day.slice(5))}</span></div>`).join('');
    return `<div class="tc-home-chart" role="img" aria-label="${esc(label)}">${cells}</div>`;
  }
  const figure = (value, label) => `<div><b>${value}</b><span>${esc(label)}</span></div>`;
  const kilo = n => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n));
  // A thing Thomas noticed. Its heading is never cut short, and pressing it opens it in place: the task's whole
  // name, where it stands and what its last check said, with a button to open the task and one that puts a request
  // in the composer. No colour marks the kind; the words say it.
  const fact = (label, value) => (value ? `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>` : '');
  function about(p) {
    if (!p) return '';
    const times = p.timings_seconds || {};
    return `<dl class="tc-home-facts">${fact('Task', String(p.title || 'Untitled').replace(/\s+/g, ' ').trim())}${fact('Where it stands', String(p.state || ''))}${fact('What Thomas said', String(p.detail || '').trim())}${fact('Last check', String(p.last_verdict || '').trim())}${fact('Time building', built(p) ? span(built(p)) : '')}${fact('Time in checks', Number(times.checks) > 0 ? span(Number(times.checks)) : '')}${fact('Last activity', when(p.updated_at) ? ago(when(p.updated_at)) : '')}</dl>`;
  }
  const card = (title, text, action, tasks) => {
    const list = (tasks || []).filter(Boolean);
    const opens = list.filter(p => p.conversation_id).map(p => `<button type="button" data-home-open="${esc(p.conversation_id)}">${list.length > 1 ? `Open "${esc(clip(p.title, 40))}"` : 'Open the task'}</button>`).join('');
    return `<details class="tc-home-card"><summary><div><strong>${esc(title)}</strong><span>${esc(text)}</span></div><i aria-hidden="true">›</i></summary><div class="tc-home-more">${list.map(about).join('')}<div class="tc-home-actions">${opens}${action ? `<button type="button" data-home-fill="${esc(action.prompt)}">${esc(action.label)}</button>` : ''}</div></div></details>`;
  };
  // What is worth noticing, each task at most once: one in a repair round, then the slowest other build, then the
  // rest that stopped. The same list tells "Where to go next" which task it should not offer a second time.
  function noticedTasks(list) {
    const avg = mean(list.map(built).filter(Boolean));
    const repair = list.find(p => /^repair round/.test(String(p.state || ''))) || null;
    const slow = list.filter(p => p !== repair && avg && built(p) > Math.max(600, avg * 2)).sort((a, b) => built(b) - built(a))[0] || null;
    const stopped = list.filter(p => p !== repair && p !== slow && /^(stopped|refused)$/.test(String(p.state || '')));
    return { avg, repair, slow, stopped };
  }

  const slides = {
    stats(data) {
      const list = data.projects;
      const by = state => list.filter(p => state.test(String(p.state || ''))).length;
      const newest = Math.max(0, ...list.map(p => when(p.updated_at)));
      return { title: TITLES.stats, body: `<div class="tc-home-figures">${figure(by(/^landed$/), 'landed')}${figure(by(/^(running|repair round)/), 'working now')}${figure(by(/^(reported|stopped|refused)$/), 'finished or stopped')}${figure(list.length, 'tasks in all')}</div><p>${newest ? `Last activity ${esc(ago(newest))}.` : 'No tasks yet.'}</p>` };
    },
    perf(data) {
      const done = data.projects.filter(built).sort((a, b) => when(b.updated_at) - when(a.updated_at));
      const perf = data.perf || {};
      const checks = data.projects.map(p => Number(p.timings_seconds && p.timings_seconds.checks) || 0).filter(Boolean);
      const recent = done.slice(0, 5).map(built);
      const before = done.slice(5, 10).map(built);
      let trend = 'Not enough finished tasks yet to compare speed over time.';
      if (recent.length >= 3 && before.length >= 3) {
        const change = Math.round((1 - mean(recent) / mean(before)) * 100);
        trend = change >= 3 ? `Builds are <b>${change}% faster</b> than the five before them.` : change <= -3 ? `Builds are <b>${-change}% slower</b> than the five before them.` : 'Build time is about the same as the five tasks before.';
      }
      const dash = '<span class="is-none">not yet</span>';
      return { title: TITLES.perf, body: `<div class="tc-home-figures">${figure(done.length ? span(mean(done.map(built))) : dash, 'average build')}${figure(checks.length ? span(mean(checks)) : dash, 'average checks')}${figure(perf.first_output_median_s != null ? `${perf.first_output_median_s}s` : dash, 'to first reply')}${figure(perf.tokens_per_second != null ? num(Math.round(perf.tokens_per_second)) : dash, 'tokens a second')}</div><p>${trend}${perf.runs ? '' : ' First reply and tokens a second start recording with your next task.'}</p>` };
    },
    perday(data) {
      const counts = lastDays(7).map(d => ({ day: d, value: data.projects.filter(p => day(when(p.updated_at)) === d).length }));
      const total = counts.reduce((n, c) => n + c.value, 0);
      return { title: TITLES.perday, body: total ? `${bars(counts, 'Tasks worked on per day')}<p><b>${total}</b> ${total === 1 ? 'task' : 'tasks'} worked on this week, <b>${counts.slice(-3).reduce((n, c) => n + c.value, 0)}</b> in the last three days.</p>` : '<p>Nothing was worked on in the last 7 days.</p>' };
    },
    tokens(data) {
      const perf = data.perf;
      if (!perf) return { title: TITLES.tokens, body: `<p>${data.perfPending ? 'Reading usage…' : 'Usage could not be read just now.'}</p>` };
      if (!perf.runs) return { title: TITLES.tokens, body: '<p>No usage recorded yet. Each task from here on records the tokens it uses, and this fills in.</p>' };
      const byDay = new Map(perf.days.map(d => [d.date, d]));
      const rows = lastDays(7).map(d => ({ day: d, value: (byDay.get(d) || {}).total || 0, text: kilo((byDay.get(d) || {}).total || 0) }));
      const total = rows.reduce((n, r) => n + r.value, 0);
      const prompt = perf.days.reduce((n, d) => n + d.prompt, 0);
      return { title: TITLES.tokens, body: `${bars(rows, 'Tokens per day')}<p><b>${num(total)}</b> tokens in 7 days across <b>${perf.runs}</b> ${perf.runs === 1 ? 'task' : 'tasks'}, <b>${num(rows.slice(-3).reduce((n, r) => n + r.value, 0))}</b> in the last 3. Prompt ${num(prompt)}, reply ${num(total - prompt)}${perf.reply_tokens_per_second != null ? `, ${num(Math.round(perf.reply_tokens_per_second))} reply tokens a second` : ''}.</p>` };
    },
    noticed(data) {
      const { avg, repair, slow, stopped } = noticedTasks(data.projects);
      const name = p => String(p.title || 'Untitled').replace(/\s+/g, ' ').trim();
      const items = [];
      if (repair) {
        const n = (String(repair.state).match(/\d+/) || ['several'])[0];
        items.push(card(`"${name(repair)}" is in repair round ${n}`, 'Its checks keep sending it back.', { label: 'Find out why', prompt: `Look at "${clip(repair.title, 80)}": it has needed ${n} repair rounds. Find out why its checks keep sending it back and fix the cause.` }, [repair]));
      }
      if (slow) items.push(card(`"${name(slow)}" took ${span(built(slow))} to build`, `That is ${(built(slow) / avg).toFixed(1)}× your average of ${span(avg)}.`, { label: 'Find what slowed it', prompt: `"${clip(slow.title, 80)}" took ${span(built(slow))} to build, ${(built(slow) / avg).toFixed(1)} times the average. Find where the time went and what would make the next one faster.` }, [slow]));
      if (stopped.length) items.push(card(`${stopped.length} ${stopped.length === 1 ? 'task' : 'tasks'} stopped without finishing`, stopped.slice(0, 3).map(p => `"${name(p)}"`).join(', '), { label: 'Review them', prompt: `These tasks stopped without finishing: ${stopped.slice(0, 5).map(p => `"${clip(p.title, 60)}"`).join(', ')}. Tell me which are worth picking up again and why.` }, stopped.slice(0, 3)));
      if (!items.length) items.push(card('Nothing needs attention', 'Nothing is stuck, slow or stopped right now.', { label: 'Look for what to improve', prompt: 'Look at the last few tasks and tell me the one change that would make Thomas faster or more reliable.' }, []));
      return { title: TITLES.noticed, body: `<div class="tc-home-cards">${items.join('')}</div>` };
    },
    recent(data) {
      const rows = [...data.projects].filter(p => p.conversation_id).sort((a, b) => when(b.updated_at) - when(a.updated_at)).slice(0, 5);
      return { title: TITLES.recent, body: rows.length ? `<div class="tc-home-recent">${rows.map(p => `<button type="button" class="tc-home-row" data-home-open="${esc(p.conversation_id)}"><span>${esc(clip(p.title, 70))}</span><small>${esc(String(p.state || ''))} · ${esc(ago(when(p.updated_at)))}</small><i aria-hidden="true">›</i></button>`).join('')}</div>` : '<p>No tasks yet.</p>' };
    },
    ideas(data) {
      const list = [...data.projects].sort((a, b) => when(b.updated_at) - when(a.updated_at));
      // Not a task the slide before this one already told you about.
      const told = noticedTasks(data.projects);
      const seen = new Set([told.repair, told.slow, ...told.stopped.slice(0, 3)].filter(Boolean));
      const open = list.find(p => !seen.has(p) && /^(running|repair round|stopped)/.test(String(p.state || '')));
      const landed = list.find(p => p.state === 'landed');
      const ideas = [];
      if (open) ideas.push({ title: `Pick up "${clip(open.title, 42)}"`, line: 'Where it stands, and what is left to do.', prompt: `Pick up "${clip(open.title, 80)}": check where it stands and carry on from there.` });
      if (landed) ideas.push({ title: `Check "${clip(landed.title, 42)}" works`, line: 'Try what landed end to end and report what is left.', prompt: `Try "${clip(landed.title, 80)}" end to end as a user would and tell me what is missing or broken.` });
      ideas.push({ title: 'Speed up the slowest part', line: 'Use the timings of your last tasks to find it.', prompt: 'Look at where my last tasks spent their time and speed up the slowest step.' });
      ideas.push({ title: 'Review the last day of changes', line: 'Anything risky that landed.', prompt: 'Read what landed in the last 24 hours and list anything risky or half-finished.' });
      const chosen = list.length ? ideas.slice(0, 4) : fallbackIdeas.map(s => ({ title: s.title, line: clip(s.text, 70), prompt: s.text }));
      return { title: TITLES.ideas, body: `<div class="tc-home-ideas">${chosen.map(i => `<button type="button" class="tc-home-idea" data-home-fill="${esc(i.prompt)}"><b>${esc(i.title)}</b><span>${esc(i.line)}</span><i aria-hidden="true">›</i></button>`).join('')}</div>` };
    },
  };

  // The markup the surface renders: every slide starts as "Loading…" and fills in once the numbers arrive.
  function html(escape, starters) {
    fallbackIdeas = Array.isArray(starters) ? starters : [];
    const loading = ORDER.map(key => `<section class="tc-home-slide" data-home-slide="${key}"><h3>${esc(TITLES[key])}</h3><p>Loading…</p></section>`).join('');
    return `<div class="tc-code-empty tc-home" data-code-home tabindex="0" aria-roledescription="carousel" aria-label="Thomas at a glance">
      <div class="tc-home-stage">${loading}</div>
      <button type="button" class="tc-home-arrow is-prev" data-home-step="-1" aria-label="Previous">‹</button>
      <button type="button" class="tc-home-arrow is-next" data-home-step="1" aria-label="Next">›</button>
      <div class="tc-home-dots" role="tablist">${ORDER.map((_, i) => `<button type="button" data-home-go="${i}" aria-label="Slide ${i + 1}"></button>`).join('')}</div>
    </div>`;
  }

  function show(root, index) {
    const all = [...root.querySelectorAll('[data-home-slide]')];
    if (!all.length) return;
    const at = ((index % all.length) + all.length) % all.length;
    root.dataset.homeAt = String(at);
    all.forEach((slide, i) => slide.classList.toggle('is-active', i === at));
    root.querySelectorAll('[data-home-go]').forEach((dot, i) => dot.classList.toggle('is-active', i === at));
    countUp(all[at]);
  }

  // The big numbers climb to their value when their slide arrives, over about 0.8 s.
  function countUp(slide) {
    if (!slide || typeof requestAnimationFrame !== 'function') return;
    slide.querySelectorAll('.tc-home-figures b').forEach(node => {
      if (node.querySelector('span')) return;
      const target = Number(node.dataset.value || node.textContent.replace(/,/g, ''));
      if (!Number.isFinite(target)) return;
      node.dataset.value = String(target);
      const began = performance.now();
      const frame = now => {
        const t = Math.min(1, (now - began) / 800);
        node.textContent = num(Math.round(target * (1 - Math.pow(1 - t, 3))));
        if (t < 1) requestAnimationFrame(frame);
      };
      node.textContent = '0';
      requestAnimationFrame(frame);
    });
  }

  function hydrate(root) {
    root.dataset.homeReady = '1';
    show(root, 0);
    load().then(data => {
      ORDER.forEach(key => {
        const slide = root.querySelector(`[data-home-slide="${key}"]`);
        if (!slide) return;
        // Only the token slide has an answer before the task list is read; the others wait for it. A waiting slide
        // is marked, and the show passes over it by itself until it has something to say.
        // The usage slide waits for its own answer and nothing else's.
        if (key === 'tokens' && data.perfPending && !data.perf) slide.dataset.pending = '1';
        else if (key === 'tokens') delete slide.dataset.pending;
        if (data.pending && key !== 'tokens') {
          slide.dataset.pending = '1';
          slide.innerHTML = `<h3>${esc(TITLES[key])}</h3><p>${data.failed ? 'Your task list could not be read just now.' : 'Reading your tasks. This can take a minute after Thomas restarts.'}</p>`;
          return;
        }
        if (key !== 'tokens') delete slide.dataset.pending;
        const made = slides[key](data);
        const markup = `<h3>${esc(made.title)}</h3>${made.body}`;
        // Unchanged, or open and being read: left as it is, so a refresh never closes what you opened.
        if (slide.dataset.homeDrawn === markup || slide.querySelector('details[open]')) return;
        slide.dataset.homeDrawn = markup;
        slide.innerHTML = markup;
      });
      // Start on a slide that has something to show.
      const first = [...root.querySelectorAll('[data-home-slide]')].findIndex(slide => !slide.dataset.pending);
      if (!root.dataset.homeStarted) { root.dataset.homeStarted = '1'; show(root, Math.max(0, first)); } else show(root, Number(root.dataset.homeAt || 0));
      if (data.pending) setTimeout(() => { if (root.isConnected) hydrate(root); }, 6000);
    });
  }

  function tick() {
    if (typeof document === 'undefined') return;
    document.querySelectorAll('[data-code-home]').forEach(root => {
      if (!root.dataset.homeReady) hydrate(root);
      else if (!root.matches(':hover') && !root.matches(':focus-within') && !root.querySelector('details[open]')) {
        // The next slide that has something to show; one still waiting for its numbers is passed over.
        const all = [...root.querySelectorAll('[data-home-slide]')];
        const from = Number(root.dataset.homeAt || 0);
        for (let step = 1; step <= all.length; step += 1) {
          if (!all[(from + step) % all.length].dataset.pending) { show(root, from + step); break; }
        }
      }
    });
  }

  // A button puts its words in the composer for you to read and send; it never sends by itself.
  function fillComposer(text) {
    const input = document.getElementById('tc-input');
    if (!input) return;
    input.value = text;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    input.focus();
    try { input.setSelectionRange(input.value.length, input.value.length); } catch (error) { /* not a text input */ }
  }

  function openTask(id) {
    const row = [...document.querySelectorAll('[data-history-id]')].find(node => node.getAttribute('data-history-id') === id);
    if (row) row.click();
  }

  if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
    document.addEventListener('click', event => {
      const target = event.target && event.target.closest ? event.target : null;
      const root = target && target.closest('[data-code-home]');
      if (!root) return;
      const step = target.closest('[data-home-step]');
      const go = target.closest('[data-home-go]');
      const fill = target.closest('[data-home-fill]');
      const open = target.closest('[data-home-open]');
      if (step) show(root, Number(root.dataset.homeAt || 0) + Number(step.dataset.homeStep));
      else if (go) show(root, Number(go.dataset.homeGo));
      else if (fill) fillComposer(fill.dataset.homeFill || '');
      else if (open) openTask(open.dataset.homeOpen);
    });
    document.addEventListener('keydown', event => {
      const root = event.target && event.target.closest ? event.target.closest('[data-code-home]') : null;
      if (!root || !['ArrowLeft', 'ArrowRight'].includes(event.key) || event.target.matches('input, textarea')) return;
      show(root, Number(root.dataset.homeAt || 0) + (event.key === 'ArrowRight' ? 1 : -1));
    });
  }
  if (typeof window.setInterval === 'function') {
    window.setInterval(() => { for (const root of document.querySelectorAll('[data-code-home]:not([data-home-ready])')) hydrate(root); }, 400);
    window.setInterval(tick, TURN_MS);
    // It used to be filled once and never again, so it went stale while it sat on screen. The list is asked for
    // again once it is a minute old, only while this tab is the one on screen.
    window.setInterval(() => {
      if (window.ThomasDocActivity && window.ThomasDocActivity.isPaused()) return;
      document.querySelectorAll('[data-code-home][data-home-ready]').forEach(root => hydrate(root));
    }, FRESH_MS + 5000);
  }

  window.ThomasCodeHome = { html, show, slides, load };
})();
