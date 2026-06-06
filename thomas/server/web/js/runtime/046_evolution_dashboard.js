/**
 * Evolution dashboard -- the cockpit for the self-recursive evolve loop.
 *
 * Thomas surveys itself, picks a ranked backlog of improvements across every
 * category (refactor / reliability / security / tests / features), runs them in
 * the safe green mirror, and -- per the autonomy posture -- promotes the safe
 * ones or holds risky ones for your approval. This panel lets you pick the
 * posture, set it loose, and watch it work.
 *
 * Self-contained: defines the global evolutionEnterMode/evolutionLeaveMode that
 * the sidebar dispatcher (039) calls, and talks to /api/evolve/loop/* via the
 * shared fetchJsonSafe helper. All rendering is defensive so a transient API
 * hiccup never white-screens the panel.
 */

var evolutionState = evolutionState || { built: false, pollTimer: 0, busy: false, lastFocus: '' };

const EVO_POLL_MS = 2500;

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

function evolutionEnterMode() {
    if (!evolutionWorkspace) return;
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
}

function evolutionBuildShell() {
    if (evolutionState.built || !evolutionWorkspace) return;
    evolutionWorkspace.innerHTML = `
<div class="evolution-shell">
  <header class="evolution-header">
    <div>
      <h2>Evolution</h2>
      <p>Thomas improving itself &mdash; refactors, hardening, reliability, tests, features. Pick how much rope it gets, then watch it work in a safe mirror before anything ships.</p>
      <p id="evoSignals" class="evo-card-why" style="margin-top:6px;"></p>
    </div>
    <div class="evolution-status-pill" id="evoStatusPill">idle</div>
  </header>

  <section class="evolution-chat">
    <div class="evo-chat-log" id="evoChatLog"></div>
    <form class="evo-chat-form" id="evoChatForm">
      <input id="evoChatInput" type="text" autocomplete="off" placeholder="Tell Thomas what to evolve &mdash; e.g. &quot;focus on hardening, but ask me first&quot;" />
      <button class="evo-btn evo-btn-primary" type="submit">Send</button>
    </form>
  </section>

  <section class="evolution-controls">
    <label>Posture
      <select id="evoPosture">
        <option value="propose">Propose &mdash; approve every change</option>
        <option value="auto_safe" selected>Auto-safe &mdash; promote safe, hold risky</option>
        <option value="autonomous">Autonomous &mdash; promote anything verified</option>
      </select>
    </label>
    <label>Focus
      <input id="evoFocus" type="text" placeholder="optional: hardening, perf, tests&hellip;" />
    </label>
    <label>Max changes
      <input id="evoMaxPromos" type="number" value="3" min="1" max="20" />
    </label>
    <label>Max steps
      <input id="evoMaxIters" type="number" value="6" min="1" max="40" />
    </label>
    <button id="evoStartBtn" class="evo-btn evo-btn-primary" type="button">Start evolving</button>
    <button id="evoPauseBtn" class="evo-btn" type="button">Pause</button>
    <button id="evoRefreshBtn" class="evo-btn" type="button">Refresh</button>
  </section>

  <section class="evolution-counters" id="evoCounters"></section>

  <div class="evolution-columns">
    <section class="evolution-col">
      <h3 id="evoBacklogTitle">Backlog &mdash; what Thomas wants to improve</h3>
      <div id="evoBacklog" class="evo-list"></div>
    </section>
    <section class="evolution-col">
      <h3>Awaiting your approval</h3>
      <div id="evoPending" class="evo-list"></div>
    </section>
  </div>

  <section class="evolution-history">
    <h3>Recent activity</h3>
    <div id="evoHistory" class="evo-list"></div>
  </section>
</div>`;

    const startBtn = document.getElementById('evoStartBtn');
    const pauseBtn = document.getElementById('evoPauseBtn');
    const refreshBtn = document.getElementById('evoRefreshBtn');
    const focusInput = document.getElementById('evoFocus');
    if (startBtn) startBtn.addEventListener('click', evolutionStart);
    if (pauseBtn) pauseBtn.addEventListener('click', evolutionPause);
    if (refreshBtn) refreshBtn.addEventListener('click', function () { void evolutionRefresh(); });
    if (focusInput) {
        focusInput.addEventListener('change', function () {
            if ((document.getElementById('evoStatusPill') || {}).textContent !== 'running') {
                void evolutionLoadPreview();
            }
        });
    }
    const chatForm = document.getElementById('evoChatForm');
    if (chatForm) {
        chatForm.addEventListener('submit', function (evt) {
            evt.preventDefault();
            void evolutionChatSend();
        });
    }
    // Delegate approve/reject clicks from the pending column.
    const pending = document.getElementById('evoPending');
    if (pending) {
        pending.addEventListener('click', function (evt) {
            const btn = evt.target.closest('button[data-evo-action]');
            if (!btn) return;
            const id = btn.getAttribute('data-approval-id');
            if (btn.getAttribute('data-evo-action') === 'approve') void evolutionApprove(id);
            else void evolutionReject(id);
        });
    }
    evolutionState.built = true;
}

async function evolutionStart() {
    const posture = (document.getElementById('evoPosture') || {}).value || 'auto_safe';
    const focus = (document.getElementById('evoFocus') || {}).value || '';
    const maxPromotions = parseInt((document.getElementById('evoMaxPromos') || {}).value, 10) || 3;
    const maxIterations = parseInt((document.getElementById('evoMaxIters') || {}).value, 10) || 6;
    const startBtn = document.getElementById('evoStartBtn');
    if (startBtn) startBtn.disabled = true;
    const resp = await evoPost('/api/evolve/loop/start', {
        posture: posture,
        focus: focus,
        max_promotions: maxPromotions,
        max_iterations: maxIterations,
    });
    if (startBtn) startBtn.disabled = false;
    if (resp && resp.ok === false && resp.error) {
        evolutionSetSignals('Already running: ' + resp.error);
    }
    void evolutionRefresh();
}

async function evolutionPause() {
    await evoPost('/api/evolve/loop/pause', {});
    void evolutionRefresh();
}

async function evolutionApprove(id) {
    if (!id) return;
    await evoPost('/api/evolve/loop/approve/' + encodeURIComponent(id), {});
    evolutionSetSignals('Approving &mdash; re-deriving and promoting that change&hellip;');
    void evolutionRefresh();
}

async function evolutionReject(id) {
    if (!id) return;
    await evoPost('/api/evolve/loop/reject/' + encodeURIComponent(id), { reason: 'dismissed from dashboard' });
    void evolutionRefresh();
}

function evolutionChatAppend(who, text) {
    const log = document.getElementById('evoChatLog');
    if (!log) return;
    const row = document.createElement('div');
    row.className = 'evo-chat-msg evo-chat-' + who;
    row.textContent = text;
    log.appendChild(row);
    log.scrollTop = log.scrollHeight;
}

async function evolutionChatSend() {
    const input = document.getElementById('evoChatInput');
    if (!input) return;
    const message = (input.value || '').trim();
    if (!message) return;
    input.value = '';
    evolutionChatAppend('you', message);
    const resp = await evoPost('/api/evolve/loop/chat', { message: message });
    evolutionChatAppend('thomas', (resp && resp.reply) || 'Sorry, I could not parse that just now.');
    void evolutionRefresh();
}

async function evolutionRefresh() {
    if (!evolutionWorkspace || evolutionState.busy) return;
    evolutionState.busy = true;
    try {
        const data = await evoGet('/api/evolve/loop/status?events=30');
        if (!data || !data.state) return;
        const state = data.state;
        evolutionRenderStatus(state);
        evolutionRenderCounters(state);
        evolutionRenderPending(state);
        evolutionRenderHistory(state);
        evolutionRenderSignals(state);
        const running = state.status === 'running' || state.running_task;
        const backlogTitle = document.getElementById('evoBacklogTitle');
        if (running && Array.isArray(state.backlog) && state.backlog.length) {
            if (backlogTitle) backlogTitle.innerHTML = 'Backlog &mdash; queued this run';
            evolutionRenderBacklog(state.backlog);
        } else if (!running) {
            if (backlogTitle) backlogTitle.innerHTML = 'Backlog &mdash; what Thomas would improve';
            await evolutionLoadPreview();
        }
    } finally {
        evolutionState.busy = false;
    }
}

async function evolutionLoadPreview() {
    const focus = (document.getElementById('evoFocus') || {}).value || '';
    const data = await evoGet('/api/evolve/loop/plan?limit=10&focus=' + encodeURIComponent(focus));
    if (data && data.backlog) {
        evolutionRenderBacklog(data.backlog.goals || []);
        evolutionRenderSignalsFrom(data.backlog.signals || {});
    }
}

function evolutionSetSignals(html) {
    const el = document.getElementById('evoSignals');
    if (el) el.innerHTML = html;
}

function evolutionRenderStatus(state) {
    const pill = document.getElementById('evoStatusPill');
    if (!pill) return;
    const running = state.status === 'running' || state.running_task;
    pill.textContent = running ? 'running' : (state.status || 'idle');
    pill.classList.toggle('is-running', !!running);
    pill.classList.toggle('is-error', state.status === 'error');
    const startBtn = document.getElementById('evoStartBtn');
    if (startBtn) startBtn.disabled = !!running;
}

function evolutionRenderCounters(state) {
    const host = document.getElementById('evoCounters');
    if (!host) return;
    const c = state.counters || {};
    const cells = [
        ['Promoted', c.promoted || 0],
        ['Awaiting you', state.pending_count || 0],
        ['Rejected', c.rejected || 0],
        ['Failed', c.failed || 0],
        ['Steps', state.iteration || 0],
    ];
    host.innerHTML = cells.map(function (pair) {
        return '<div class="evo-counter"><div class="evo-counter-value">' + pair[1] +
            '</div><div class="evo-counter-label">' + pair[0] + '</div></div>';
    }).join('');
}

function evolutionRenderBacklog(goals) {
    const host = document.getElementById('evoBacklog');
    if (!host) return;
    if (!goals || !goals.length) {
        host.innerHTML = '<div class="evo-empty">Nothing queued &mdash; Thomas looks healthy here.</div>';
        return;
    }
    host.innerHTML = goals.map(function (g) {
        const risk = evoEsc(g.risk_tier || 'medium');
        return '<div class="evo-card"><div class="evo-card-head">' +
            '<span class="evo-card-title">' + evoEsc(g.title) + '</span>' +
            '<span class="evo-chip risk-' + risk + '">' + evoEsc(g.category) + ' &middot; ' + risk + '</span>' +
            '</div><div class="evo-card-why">' + evoEsc(g.rationale) + '</div></div>';
    }).join('');
}

function evolutionRenderPending(state) {
    const host = document.getElementById('evoPending');
    if (!host) return;
    const pending = (state.pending_approvals || []).filter(function (p) { return p.status === 'pending'; });
    if (!pending.length) {
        host.innerHTML = '<div class="evo-empty">No changes waiting. Risky changes will queue here for your approval.</div>';
        return;
    }
    host.innerHTML = pending.map(function (p) {
        const risk = evoEsc(p.risk_tier || 'medium');
        return '<div class="evo-card"><div class="evo-card-head">' +
            '<span class="evo-card-title">' + evoEsc(p.title) + '</span>' +
            '<span class="evo-chip risk-' + risk + '">' + evoEsc(p.category) + ' &middot; ' + risk + '</span>' +
            '</div><div class="evo-card-why">' + evoEsc(p.rationale || p.reason || '') + '</div>' +
            '<div class="evo-card-actions">' +
            '<button class="evo-btn evo-btn-primary" type="button" data-evo-action="approve" data-approval-id="' + evoEsc(p.id) + '">Approve &amp; promote</button>' +
            '<button class="evo-btn" type="button" data-evo-action="reject" data-approval-id="' + evoEsc(p.id) + '">Dismiss</button>' +
            '</div></div>';
    }).join('');
}

function evolutionRenderHistory(state) {
    const host = document.getElementById('evoHistory');
    if (!host) return;
    const history = (state.history || []).slice(-10).reverse();
    if (!history.length) {
        host.innerHTML = '<div class="evo-empty">No activity yet. Press &ldquo;Start evolving&rdquo; to begin.</div>';
        return;
    }
    host.innerHTML = history.map(function (h) {
        const action = (h.decision && h.decision.action) || 'reject';
        const dotClass = action === 'promote' ? 'is-promote' : (action === 'approve' ? 'is-approve' : 'is-reject');
        const tag = h.promoted ? 'promoted' : (action === 'approve' ? 'held for you' : 'skipped');
        return '<div class="evo-hist-row"><span class="evo-hist-dot ' + dotClass + '"></span>' +
            '<span style="flex:1;">' + evoEsc(h.title) + '</span>' +
            '<span class="evo-card-why">' + evoEsc(h.category) + ' &middot; ' + tag + '</span></div>';
    }).join('');
}

function evolutionRenderSignals(state) {
    if (state && state.signals && Object.keys(state.signals).length) {
        evolutionRenderSignalsFrom(state.signals);
    }
}

function evolutionRenderSignalsFrom(signals) {
    if (!signals) return;
    const bits = [];
    if (signals.scanned_py_files) bits.push(signals.scanned_py_files + ' files surveyed');
    if (signals.bare_except_handlers) bits.push(signals.bare_except_handlers + ' silent catches');
    if (signals.xfail_markers) bits.push(signals.xfail_markers + ' xfail tests');
    if (signals.security_markers) bits.push(signals.security_markers + ' risk markers');
    if (signals.oversized_files) bits.push(signals.oversized_files + ' oversized files');
    if (bits.length) evolutionSetSignals(evoEsc(bits.join(' &middot; ')).replace(/&amp;middot;/g, '&middot;'));
}
