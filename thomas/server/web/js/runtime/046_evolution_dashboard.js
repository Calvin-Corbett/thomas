/**
 * Evolution dashboard -- the self-improvement panel, in plain English.
 *
 * Design intent (Calvin): a regular, non-technical person opens this and
 * instantly gets WHAT Thomas is doing and WHAT it needs from them -- no jargon,
 * no wall of knobs. One "Improve yourself" button; everything technical lives in
 * a collapsed Advanced drawer most people never open.
 *
 * The "evolve manager" is the grounded narrator below: it translates the REAL
 * loop state (counters, current task, history, pending approvals -- straight off
 * /api/evolve/loop/status) into plain sentences. It NEVER invents success: a run
 * is only ever called "shipped/done" when the loop's own `promoted === true`. It
 * shapes how things are shown; it never changes what happened.
 *
 * Self-contained: defines the global evolutionEnterMode/evolutionLeaveMode that
 * the sidebar dispatcher (039) calls, and talks to /api/evolve/loop/* via the
 * shared fetchJsonSafe helper. All rendering is defensive so a transient API
 * hiccup never white-screens the panel.
 */

var evolutionState = evolutionState || { built: false, pollTimer: 0, busy: false, previewLoaded: false };

const EVO_POLL_MS = 2500;

function evoEl(id) {
    return document.getElementById(id);
}

function evoEsc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch];
    });
}

// fetchJsonSafe returns an envelope { ok, status, data, text }; unwrap to the body.
function _evoUnwrap(result) {
    if (result && typeof result === 'object' && 'data' in result && 'status' in result) return result.data;
    return result;
}

async function evoGet(url) {
    try {
        return _evoUnwrap(await fetchJsonSafe(url));
    } catch (err) {
        console.warn('[Thomas] evolve GET failed', url, err);
        return null;
    }
}

async function evoPost(url, body) {
    try {
        return _evoUnwrap(
            await fetchJsonSafe(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body || {}),
            })
        );
    } catch (err) {
        console.warn('[Thomas] evolve POST failed', url, err);
        return null;
    }
}

// ---- the evolve-manager narrator: real fields -> plain English (never invents) ----

function evoPlainKind(category) {
    const m = {
        security: 'security', reliability: 'reliability', tests: 'safety tests',
        test: 'safety tests', refactor: 'tidy-up', cleanup: 'tidy-up',
        performance: 'speed', perf: 'speed', features: 'a new ability',
        feature: 'a new ability', docs: 'documentation', bug: 'a bug fix',
    };
    return m[String(category || '').toLowerCase()] || 'an improvement';
}

// Verb phrase for "Thomas wants to ___" / "Thomas is working on ___".
function evoPlainAim(category) {
    const m = {
        security: 'make things more secure', reliability: 'make things more reliable',
        tests: 'add safety tests', test: 'add safety tests', refactor: 'tidy up some code',
        cleanup: 'clean up some code', performance: 'make things faster', perf: 'make things faster',
        features: 'add a new ability', feature: 'add a new ability', docs: 'improve the docs',
        bug: 'fix a bug',
    };
    return m[String(category || '').toLowerCase()] || 'improve itself';
}

// "5m ago" / "2h ago" / "yesterday" from an ISO timestamp; "" if unparseable.
function evoAgo(iso) {
    if (!iso) return '';
    const t = Date.parse(iso);
    if (isNaN(t)) return '';
    const secs = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (secs < 60) return 'just now';
    if (secs < 3600) return Math.round(secs / 60) + 'm ago';
    if (secs < 86400) return Math.round(secs / 3600) + 'h ago';
    const days = Math.round(secs / 86400);
    return days === 1 ? 'yesterday' : days + 'd ago';
}

function evolutionEnterMode() {
    if (typeof evolutionWorkspace === 'undefined' || !evolutionWorkspace) return;
    evolutionBuildShell();
    void evolutionRefresh();
    if (evolutionState.pollTimer) window.clearInterval(evolutionState.pollTimer);
    evolutionState.pollTimer = window.setInterval(function () {
        void evolutionRefresh();
    }, EVO_POLL_MS);
}

function evolutionLeaveMode() {
    if (evolutionState.pollTimer) {
        window.clearInterval(evolutionState.pollTimer);
        evolutionState.pollTimer = 0;
    }
    // Leaving Forge: stop claiming the composer so main chat behaves normally.
    window.forgeCodeActive = false;
}

function evolutionBuildShell() {
    if (evolutionState.built || typeof evolutionWorkspace === 'undefined' || !evolutionWorkspace) return;
    evolutionWorkspace.innerHTML = `
<div class="forge-shell">
  <div class="forge-topbar">
    <span class="forge-brand">Forge</span>
    <div class="forge-toggle" role="tablist" aria-label="Forge mode">
      <button class="forge-tab is-active" type="button" data-forge-side="evolve" role="tab" aria-selected="true">Evolve</button>
      <button class="forge-tab" type="button" data-forge-side="code" role="tab" aria-selected="false">Code</button>
    </div>
    <span class="forge-hint">Evolve = Thomas improves itself &middot; Code = build anything</span>
  </div>
  <div class="forge-view" id="forgeEvolve">
<div class="evolution-shell">
  <header class="evolution-header">
    <div>
      <h2>Self-improvement</h2>
      <p class="evo-sub">Thomas can look through its own code, find things to improve, and show you each change before anything sticks. You stay in control &mdash; nothing risky happens without your OK.</p>
      <div class="evo-byline"><span class="evo-byline-dot" id="evoByDot"></span> <span id="evoByline">managed by Thomas &mdash; keeps this view honest and up to date</span></div>
    </div>
    <div class="evolution-status-pill" id="evoStatusPill">ready</div>
  </header>

  <section class="evo-hero" id="evoHero"></section>

  <section class="evolution-counters" id="evoCounters"></section>
  <section class="evo-tile-detail is-hidden" id="evoTileDetail"></section>

  <section class="evo-needs-wrap" id="evoNeedsWrap" hidden>
    <h3 class="evo-section-title evo-section-warn">Needs your OK</h3>
    <div id="evoPending" class="evo-list"></div>
  </section>

  <div class="evolution-columns">
    <section class="evolution-col">
      <h3 class="evo-section-title" id="evoBacklogTitle">Ideas Thomas has</h3>
      <div id="evoBacklog" class="evo-list"></div>
    </section>
    <section class="evolution-col">
      <h3 class="evo-section-title">Recently done</h3>
      <div id="evoHistory" class="evo-list"></div>
    </section>
  </div>

  <details class="evo-advanced" id="evoAdvanced">
    <summary>Advanced settings &mdash; most people never need these</summary>
    <div class="evo-advanced-body">
      <label>How hard should Thomas think?
        <select id="evoDepth">
          <option value="classic" selected>Quick &mdash; good for clear fixes</option>
          <option value="funnel">Deep &mdash; several AIs compare approaches (slower, best for open-ended)</option>
        </select>
      </label>
      <label>How independent should it be?
        <select id="evoPosture">
          <option value="propose">Ask first &mdash; changes nothing until you say go</option>
          <option value="auto_safe" selected>Auto-safe &mdash; safe changes itself, asks before risky</option>
          <option value="autonomous">Full &mdash; keeps going until done or the limit</option>
        </select>
      </label>
      <label>Which AI runs this?
        <select id="evoModel">
          <option value="claude:sonnet" selected>Claude Sonnet &mdash; fast &amp; capable</option>
          <option value="claude:opus">Claude Opus &mdash; most capable</option>
          <option value="claude:fable">Claude Fable &mdash; fastest</option>
          <option value="codex:gpt">GPT (Codex) &mdash; OpenAI</option>
        </select>
      </label>
      <label>Effort
        <select id="evoEffort">
          <option value="medium" selected>Balanced</option>
          <option value="low">Low &mdash; quick &amp; cheap</option>
          <option value="high">High &mdash; more thorough</option>
          <option value="max">Max &mdash; slowest, deepest</option>
        </select>
      </label>
      <label>Anything specific to focus on? (optional)
        <input id="evoFocus" type="text" placeholder="e.g. speed, security, tests&hellip;" />
      </label>
      <label>Check with me after this many improvements
        <input id="evoMaxPromos" type="number" value="3" min="1" max="20" />
      </label>
    </div>
  </details>
</div>
  </div>
  <div class="forge-view is-hidden" id="forgeCode"></div>
</div>`;

    // Hero hosts the primary button; it is (re)wired on each hero render.
    const focusInput = evoEl('evoFocus');
    if (focusInput) {
        focusInput.addEventListener('change', function () {
            evolutionState.previewLoaded = false;
            const pill = evoEl('evoStatusPill');
            if (!pill || pill.getAttribute('data-running') !== '1') void evolutionLoadPreview();
        });
    }
    // Delegate approve/reject/expand clicks from the pending column.
    const pending = evoEl('evoPending');
    if (pending) {
        pending.addEventListener('click', function (evt) {
            const expander = evt.target.closest('[data-evo-expand]');
            if (expander) {
                const body = document.getElementById('evo-detail-' + expander.getAttribute('data-evo-expand'));
                if (body) body.hidden = !body.hidden;
                return;
            }
            const handoff = evt.target.closest('[data-evo-handoff]');
            if (handoff) { evoHandoffFromEl(handoff); return; }
            const btn = evt.target.closest('button[data-evo-action]');
            if (!btn) return;
            const id = btn.getAttribute('data-approval-id');
            if (btn.getAttribute('data-evo-action') === 'approve') void evolutionApprove(id);
            else void evolutionReject(id);
        });
    }
    // Backlog ideas delegate their "Open in Code" handoff here (host persists
    // across re-renders, so this single listener covers every rendered card).
    const backlog = evoEl('evoBacklog');
    if (backlog) {
        backlog.addEventListener('click', function (evt) {
            const handoff = evt.target.closest('[data-evo-handoff]');
            if (handoff) evoHandoffFromEl(handoff);
        });
    }
    // The tile-detail panel (expanded ideas/waiting lists) shares the same handoff.
    const tileDetail = evoEl('evoTileDetail');
    if (tileDetail) {
        tileDetail.addEventListener('click', function (evt) {
            const handoff = evt.target.closest('[data-evo-handoff]');
            if (handoff) evoHandoffFromEl(handoff);
        });
    }
    const counters = evoEl('evoCounters');
    if (counters) {
        counters.addEventListener('click', function (evt) {
            const btn = evt.target.closest('[data-evo-filter]');
            if (btn) evolutionShowTile(btn.getAttribute('data-evo-filter'));
        });
    }
    const tabs = evolutionWorkspace.querySelectorAll('.forge-tab');
    tabs.forEach(function (tab) {
        tab.addEventListener('click', function () { forgeShowSide(tab.getAttribute('data-forge-side')); });
    });
    evolutionState.built = true;
}

// Switch the Forge container between the Evolve dashboard and the Code surface.
// Code mounts itself (047) into #forgeCode; we just toggle visibility + tab state.
function forgeShowSide(side) {
    const isCode = side === 'code';
    const evolve = evoEl('forgeEvolve');
    const code = evoEl('forgeCode');
    if (evolve) evolve.classList.toggle('is-hidden', isCode);
    if (code) code.classList.toggle('is-hidden', !isCode);
    if (typeof evolutionWorkspace !== 'undefined' && evolutionWorkspace) {
        evolutionWorkspace.querySelectorAll('.forge-tab').forEach(function (t) {
            const active = t.getAttribute('data-forge-side') === side;
            t.classList.toggle('is-active', active);
            t.setAttribute('aria-selected', active ? 'true' : 'false');
        });
    }
    evolutionState.side = side;
    // Reuse Thomas's REAL composer for the Code side: un-hide it (it's the fixed
    // bottom chat bar) and flag Forge-Code active so its send routes to the build
    // (047's capture interceptor). On the Evolve side, hide it again.
    window.forgeCodeActive = isCode;
    var composer = document.querySelector('.composer-container');
    if (composer) composer.classList.toggle('hidden', !isCode);
    if (isCode && typeof forgeCodeMount === 'function') forgeCodeMount();
}

// ---- Evolve -> Code handoff -------------------------------------------------
// Each idea/pending card gets an "Open in Code" action. It hands the item's REAL
// context (title + rationale) to the Code side, which allocates a NEW Code
// conversation seeded with that context and persists it (source_evolve_item).
// The item data rides on data-* attributes so the handler is immune to the
// dashboard's 2.5s re-render churn (no stale closures).
function evoHandoffBtn(item) {
    item = item || {};
    return '<button class="evo-btn evo-handoff" type="button" data-evo-handoff="1"' +
        ' data-fc-id="' + evoEsc(item.id || '') + '"' +
        ' data-fc-title="' + evoEsc(item.title || '') + '"' +
        ' data-fc-rationale="' + evoEsc(item.rationale || item.reason || '') + '"' +
        ' data-fc-category="' + evoEsc(item.category || '') + '">Open in Code</button>';
}

function evoHandoffFromEl(btn) {
    if (!btn) return;
    evolutionOpenInCode({
        id: btn.getAttribute('data-fc-id') || '',
        title: btn.getAttribute('data-fc-title') || '',
        rationale: btn.getAttribute('data-fc-rationale') || '',
        category: btn.getAttribute('data-fc-category') || '',
    });
}

// Switch to the Code side, open a fresh Code conversation seeded with this
// Evolve item, and prefill the REAL composer with its context so the user sees
// exactly what is being handed off (and it becomes the first build message).
function evolutionOpenInCode(item) {
    item = item || {};
    forgeShowSide('code');
    const seed = {
        title: item.title || 'Code session',
        source_evolve_item: {
            id: item.id || '',
            title: item.title || '',
            rationale: item.rationale || '',
            category: item.category || '',
        },
    };
    if (typeof window.forgeCodeStartConversation === 'function') {
        void window.forgeCodeStartConversation(seed);
    }
    const ta = document.getElementById('composerTextarea');
    if (ta) {
        const lines = ['Work on this improvement: ' + (item.title || '')];
        if (item.rationale) { lines.push('', 'Why it matters: ' + item.rationale); }
        ta.value = lines.join('\n');
        ta.dispatchEvent(new Event('input'));
        try { ta.focus(); } catch (_e) { /* focus is best-effort */ }
    }
}

function evolutionStart() {
    const depth = (evoEl('evoDepth') || {}).value || 'classic';
    const posture = (evoEl('evoPosture') || {}).value || 'auto_safe';
    const focus = (evoEl('evoFocus') || {}).value || '';
    const maxPromotions = parseInt((evoEl('evoMaxPromos') || {}).value, 10) || 3;
    const maxIterations = parseInt((evoEl('evoMaxIters') || {}).value, 10) || 6;
    const startBtn = evoEl('evoPrimaryBtn');
    if (startBtn) startBtn.disabled = true;
    void evoPost('/api/evolve/loop/start', {
        posture: posture,
        focus: focus,
        mode: depth,
        max_promotions: maxPromotions,
        max_iterations: maxIterations,
    }).then(function (resp) {
        if (resp && resp.ok === false && resp.error) evolutionSetByline('Already running &mdash; watch the progress above.');
        void evolutionRefresh();
    });
}

function evolutionPause() {
    void evoPost('/api/evolve/loop/pause', {}).then(function () { void evolutionRefresh(); });
}

async function evolutionApprove(id) {
    if (!id) return;
    await evoPost('/api/evolve/loop/approve/' + encodeURIComponent(id), {});
    evolutionSetByline('On it &mdash; making that change real and re-checking it&hellip;');
    void evolutionRefresh();
}

async function evolutionReject(id) {
    if (!id) return;
    await evoPost('/api/evolve/loop/reject/' + encodeURIComponent(id), { reason: 'not now, from dashboard' });
    void evolutionRefresh();
}

async function evolutionRefresh() {
    if (typeof evolutionWorkspace === 'undefined' || !evolutionWorkspace || evolutionState.busy) return;
    evolutionState.busy = true;
    try {
        const data = await evoGet('/api/evolve/loop/status?events=30');
        if (!data || !data.state) return;
        const state = data.state;
        evolutionState.lastState = state;
        const running = state.status === 'running' || state.running_task;
        evolutionRenderStatus(state, running);
        evolutionRenderHero(state, running);
        evolutionRenderCounters(state);
        evolutionRenderPending(state);
        evolutionRenderHistory(state);
        evolutionRenderByline(state, running);
        if (evolutionState.tileFilter) evolutionRenderTileDetail();
        const backlogTitle = evoEl('evoBacklogTitle');
        if (running && Array.isArray(state.backlog) && state.backlog.length) {
            if (backlogTitle) backlogTitle.textContent = 'Working through these';
            evolutionRenderBacklog(state.backlog);
        } else if (!running) {
            if (backlogTitle) backlogTitle.textContent = 'Ideas Thomas has';
            if (!evolutionState.previewLoaded) await evolutionLoadPreview();
        }
    } finally {
        evolutionState.busy = false;
    }
}

async function evolutionLoadPreview() {
    const focus = (evoEl('evoFocus') || {}).value || '';
    const data = await evoGet('/api/evolve/loop/plan?limit=8&focus=' + encodeURIComponent(focus));
    if (data && data.backlog) {
        evolutionState.previewLoaded = true;
        evolutionRenderBacklog(data.backlog.goals || []);
    }
}

function evolutionSetByline(html) {
    const el = evoEl('evoByline');
    if (el) el.innerHTML = html;
}

function evolutionRenderByline(state, running) {
    // Grounded one-liner: what the manager is reporting right now.
    if (running) {
        evolutionSetByline('managed by Thomas &mdash; live, updating as it works');
    } else if ((state.pending_count || 0) > 0) {
        evolutionSetByline('managed by Thomas &mdash; ' + state.pending_count + ' change' + (state.pending_count === 1 ? '' : 's') + ' waiting on you below');
    } else if (state.last_error) {
        evolutionSetByline('managed by Thomas &mdash; the last run hit a snag, details below');
    } else {
        evolutionSetByline('managed by Thomas &mdash; keeps this view honest and up to date');
    }
    const dot = evoEl('evoByDot');
    if (dot) dot.classList.toggle('is-live', !!running);
}

function evolutionRenderStatus(state, running) {
    const pill = evoEl('evoStatusPill');
    if (!pill) return;
    let label = 'ready';
    if (running) label = 'working';
    else if (state.status === 'error' || state.last_error) label = 'needs a look';
    else if ((state.pending_count || 0) > 0) label = 'needs your OK';
    else if ((state.counters || {}).promoted) label = 'finished';
    pill.textContent = label;
    pill.setAttribute('data-running', running ? '1' : '0');
    pill.classList.toggle('is-running', !!running);
    pill.classList.toggle('is-error', state.status === 'error' || !!state.last_error);
    pill.classList.toggle('is-attention', !running && (state.pending_count || 0) > 0);
}

function evolutionRenderHero(state, running) {
    const host = evoEl('evoHero');
    if (!host) return;
    if (running) {
        const cur = state.current || {};
        const step = state.iteration || 0;
        const max = (state.budget && state.budget.max_iterations) || 0;
        const aim = cur.category ? ('working on ' + evoPlainKind(cur.category)) : 'looking for the next improvement';
        const detail = cur.title ? evoEsc(cur.title) : 'surveying the code';
        const stepText = max ? ('step ' + step + ' of ' + max) : ('step ' + step);
        const pct = max ? Math.min(100, Math.max(6, Math.round((step / max) * 100))) : 30;
        host.innerHTML =
            '<div class="evo-hero-row">' +
            '<span class="evo-hero-spin" aria-hidden="true"></span>' +
            '<div class="evo-hero-main">' +
            '<div class="evo-hero-title">Thomas is ' + aim + '&hellip;</div>' +
            '<div class="evo-hero-detail">' + detail + ' &middot; ' + stepText + '</div>' +
            '<div class="evo-progress"><div class="evo-progress-fill" style="width:' + pct + '%"></div></div>' +
            '</div>' +
            '<button class="evo-btn" type="button" id="evoPrimaryBtn">Pause</button>' +
            '</div>';
        const btn = evoEl('evoPrimaryBtn');
        if (btn) btn.addEventListener('click', evolutionPause);
        return;
    }
    const c = state.counters || {};
    const shipped = c.promoted || 0;
    const pending = state.pending_count || 0;
    let icon, title, detail;
    if (state.last_error) {
        icon = 'warn';
        title = 'The last run hit a snag';
        detail = 'Nothing was changed unsafely. You can try again whenever you like.';
    } else if (shipped || pending) {
        icon = 'check';
        title = 'Thomas improved ' + shipped + ' thing' + (shipped === 1 ? '' : 's') + ' on its own';
        detail = pending ? (pending + ' bigger change' + (pending === 1 ? '' : 's') + ' need' + (pending === 1 ? 's' : '') + ' your OK &mdash; just below.') : 'All done for this run. Run it again any time.';
    } else {
        icon = 'wand';
        title = 'Thomas is ready to improve itself';
        detail = 'It&rsquo;ll look through its own code and suggest improvements. You approve each one before it&rsquo;s real.';
    }
    host.innerHTML =
        '<div class="evo-hero-row">' +
        '<span class="evo-hero-icon is-' + icon + '" aria-hidden="true"></span>' +
        '<div class="evo-hero-main">' +
        '<div class="evo-hero-title">' + title + '</div>' +
        '<div class="evo-hero-detail">' + detail + '</div>' +
        '</div>' +
        '<button class="evo-btn evo-btn-primary" type="button" id="evoPrimaryBtn">' +
        (shipped || pending ? 'Find more' : 'Improve yourself') + '</button>' +
        '</div>';
    const btn = evoEl('evoPrimaryBtn');
    if (btn) btn.addEventListener('click', evolutionStart);
}

function evolutionRenderCounters(state) {
    const host = evoEl('evoCounters');
    if (!host) return;
    const c = state.counters || {};
    const backlogLen = Array.isArray(state.backlog) ? state.backlog.length : 0;
    const cells = [
        ['Improvements shipped', c.promoted || 0, '', 'shipped'],
        ['Waiting for you', state.pending_count || 0, (state.pending_count ? 'is-warn' : ''), 'waiting'],
        ['Ideas queued', backlogLen, '', 'ideas'],
    ];
    const active = evolutionState.tileFilter || '';
    host.innerHTML = cells.map(function (cell) {
        return '<button type="button" class="evo-counter evo-counter-click' + (active === cell[3] ? ' is-active' : '') +
            '" data-evo-filter="' + cell[3] + '"><div class="evo-counter-value ' + cell[2] + '">' + cell[1] +
            '</div><div class="evo-counter-label">' + cell[0] + ' &#9662;</div></button>';
    }).join('');
}

// Clicking a stat tile expands its full list below (shipped / waiting / ideas),
// with show-more. Clicking the active tile again collapses it.
function evolutionShowTile(filter) {
    evolutionState.tileFilter = (evolutionState.tileFilter === filter) ? '' : filter;
    evolutionState.tileLimit = 6;
    if (evolutionState.lastState) evolutionRenderCounters(evolutionState.lastState);
    evolutionRenderTileDetail();
}

function evolutionRenderTileDetail() {
    const host = evoEl('evoTileDetail');
    if (!host) return;
    const filter = evolutionState.tileFilter || '';
    const state = evolutionState.lastState || {};
    if (!filter) { host.classList.add('is-hidden'); host.innerHTML = ''; return; }
    host.classList.remove('is-hidden');
    const limit = evolutionState.tileLimit || 6;
    let title = '';
    let items = [];
    let rows = [];
    if (filter === 'shipped') {
        title = 'Improvements shipped';
        items = (state.history || []).filter(function (h) { return h.promoted === true; }).slice().reverse();
        rows = items.slice(0, limit).map(function (h) {
            return '<div class="evo-hist-row"><span class="evo-hist-dot is-done"></span>' +
                '<span class="evo-hist-title">' + evoEsc(h.title) + '</span>' +
                '<span class="evo-hist-tag">' + evoEsc(evoPlainKind(h.category)) + (evoAgo(h.at) ? ' &middot; ' + evoAgo(h.at) : '') + '</span></div>';
        });
    } else if (filter === 'waiting') {
        title = 'Waiting for your OK';
        items = (state.pending_approvals || []).filter(function (p) { return p.status === 'pending'; });
        rows = items.slice(0, limit).map(function (p) {
            return '<div class="evo-card evo-card-warn"><div class="evo-card-title">Thomas wants to ' + evoEsc(evoPlainAim(p.category)) + '</div>' +
                '<div class="evo-card-why">' + evoEsc(p.rationale || p.reason || '') + '</div>' +
                '<div class="evo-card-actions">' + evoHandoffBtn({ id: p.id, title: evoPlainAim(p.category), rationale: p.rationale || p.reason || '', category: p.category }) + '</div></div>';
        });
    } else if (filter === 'ideas') {
        title = 'Ideas queued';
        items = state.backlog || [];
        rows = items.slice(0, limit).map(function (g) {
            return '<div class="evo-card"><div class="evo-card-head"><span class="evo-card-title">' + evoEsc(g.title) + '</span>' +
                '<span class="evo-kind">' + evoEsc(evoPlainKind(g.category)) + '</span></div>' +
                '<div class="evo-card-why">' + evoEsc(g.rationale || '') + '</div>' +
                '<div class="evo-card-actions">' + evoHandoffBtn(g) + '</div></div>';
        });
    }
    let html = '<h3 class="evo-section-title">' + evoEsc(title) + ' (' + items.length + ')</h3>';
    if (!items.length) {
        html += '<div class="evo-empty">Nothing here yet.</div>';
    } else {
        html += '<div class="evo-list">' + rows.join('') + '</div>';
        if (items.length > limit) {
            html += '<button type="button" class="evo-expand-link" id="evoTileMore">Show more (' + (items.length - limit) + ' more)</button>';
        }
    }
    host.innerHTML = html;
    const more = evoEl('evoTileMore');
    if (more) {
        more.addEventListener('click', function () {
            evolutionState.tileLimit = (evolutionState.tileLimit || 6) + 8;
            evolutionRenderTileDetail();
        });
    }
}

function evolutionRenderBacklog(goals) {
    const host = evoEl('evoBacklog');
    if (!host) return;
    if (!goals || !goals.length) {
        host.innerHTML = '<div class="evo-empty">Nothing queued &mdash; Thomas looks healthy here.</div>';
        return;
    }
    host.innerHTML = goals.slice(0, 8).map(function (g) {
        return '<div class="evo-card">' +
            '<div class="evo-card-head"><span class="evo-card-title">' + evoEsc(g.title) + '</span>' +
            '<span class="evo-kind">' + evoEsc(evoPlainKind(g.category)) + '</span></div>' +
            '<div class="evo-card-why">' + evoEsc(g.rationale || '') + '</div>' +
            '<div class="evo-card-actions">' + evoHandoffBtn(g) + '</div></div>';
    }).join('');
}

function evolutionRenderPending(state) {
    const wrap = evoEl('evoNeedsWrap');
    const host = evoEl('evoPending');
    if (!host || !wrap) return;
    const pending = (state.pending_approvals || []).filter(function (p) { return p.status === 'pending'; });
    wrap.hidden = pending.length === 0;
    if (!pending.length) { host.innerHTML = ''; return; }
    host.innerHTML = pending.map(function (p) {
        const aim = evoPlainAim(p.category);
        const files = Array.isArray(p.changed_files) ? p.changed_files : [];
        const fileList = files.slice(0, 12).map(function (f) { return '<li>' + evoEsc(f) + '</li>'; }).join('');
        const moreFiles = files.length > 12 ? ('<li>&hellip; and ' + (files.length - 12) + ' more</li>') : '';
        const why = evoEsc(p.rationale || p.reason || '');
        return '<div class="evo-card evo-card-warn">' +
            '<div class="evo-card-head"><span class="evo-card-title">Thomas wants to ' + evoEsc(aim) + '</span></div>' +
            (why ? '<div class="evo-card-why">' + why + '</div>' : '') +
            '<div class="evo-card-why evo-safe-note">It built this in a private copy and it passed the safety checks &mdash; it just needs your OK to make it real.</div>' +
            (files.length ? '<button class="evo-expand-link" type="button" data-evo-expand="' + evoEsc(p.id) + '">What would change? (' + files.length + ' file' + (files.length === 1 ? '' : 's') + ')</button>' : '') +
            (files.length ? '<div class="evo-detail" id="evo-detail-' + evoEsc(p.id) + '" hidden><ul class="evo-files">' + fileList + moreFiles + '</ul></div>' : '') +
            '<div class="evo-card-actions">' +
            '<button class="evo-btn evo-btn-primary" type="button" data-evo-action="approve" data-approval-id="' + evoEsc(p.id) + '">Yes, do this</button>' +
            '<button class="evo-btn" type="button" data-evo-action="reject" data-approval-id="' + evoEsc(p.id) + '">Not now</button>' +
            evoHandoffBtn({ id: p.id, title: evoPlainAim(p.category), rationale: p.rationale || p.reason || '', category: p.category }) +
            '</div></div>';
    }).join('');
}

function evolutionRenderHistory(state) {
    const host = evoEl('evoHistory');
    if (!host) return;
    const history = (state.history || []).slice(-12).reverse();
    if (!history.length) {
        host.innerHTML = '<div class="evo-empty">No activity yet. Press &ldquo;Improve yourself&rdquo; to begin.</div>';
        return;
    }
    host.innerHTML = history.map(function (h) {
        // Grounded: only "Done" when the loop actually promoted it.
        const action = (h.decision && h.decision.action) || '';
        let cls, tag;
        if (h.promoted === true) { cls = 'is-done'; tag = 'done'; }
        else if (action === 'approve') { cls = 'is-wait'; tag = 'waiting for you'; }
        else if (action === 'reject') { cls = 'is-skip'; tag = 'skipped'; }
        else if ((h.session_status || '').indexOf('fail') >= 0) { cls = 'is-skip'; tag = 'didn’t work out'; }
        else { cls = 'is-skip'; tag = 'no change needed'; }
        const when = evoAgo(h.at);
        return '<div class="evo-hist-row"><span class="evo-hist-dot ' + cls + '"></span>' +
            '<span class="evo-hist-title">' + evoEsc(h.title) + '</span>' +
            '<span class="evo-hist-tag">' + tag + (when ? ' &middot; ' + when : '') + '</span></div>';
    }).join('');
}
