/**
 * Token Economy workspace.
 *
 * Thomas Chat is the immutable visual master. This module consumes the same
 * five-theme tokens, density, controls, eyes mark, and UI Edit Mode contract.
 *
 * Hooks into the module system via window.__tokenEconomy.
 * Consumes /api/spend/* endpoints + SSE for live updates.
 *
 * token_economy_space.js is now a static, active-only compatibility adapter.
 */

(function tokenEconomyModule() {
    'use strict';

    const _s = {
        mounted: false,
        loading: false,
        today: null,
        session: null,
        history: null,
        pricing: null,
        profile: null,
        matrix: null,
        period: 7,
        economy: '',
        autonomy: 3,
        sse: null,
        el: null,
        lastRefresh: 0,
        feedEvents: [],
        clockTimer: null,
        sseRetry: null,
        feedSequence: 0,
    };

    const STALE = 15_000;

    const MODE_SPECS = {
        cheap: {
            mul: '0.3×', name: 'Cheap', tag: 'ECON',
            passes: '1–3', budget: '250K', retries: '0',
            overhead: 'Minimal', skills: 'Off',
            desc: 'Single-shot. No retries, no overhead.',
        },
        optimal: {
            mul: '1.0×', name: 'Optimal', tag: 'STD',
            passes: '3–15', budget: '650K', retries: '1',
            overhead: 'Balanced', skills: 'Explicit',
            desc: 'Default runtime. Balanced effort.',
        },
        max: {
            mul: '2.5×', name: 'Max', tag: 'MAX',
            passes: '8–32', budget: '∞', retries: '2–3',
            overhead: 'Full', skills: 'Auto',
            desc: 'Full suite. Maximum capability.',
        },
    };

    const MODEL_COLORS = [
        '#58a6ff', '#47d7ac', '#ffbf47', '#ff6b6b', '#c084fc',
        '#f472b6', '#38bdf8', '#a3e635', '#fb923c', '#94a3b8',
    ];

    // ── util ─────────────────────────────────────────────────────
    function $(sel, r) { return (r || document).querySelector(sel); }
    function $$(sel, r) { return [...(r || document).querySelectorAll(sel)]; }
    function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
    function usd(n) {
        const v = +n || 0;
        if (v >= 1) return '$' + v.toFixed(2);
        if (v >= 0.01) return '$' + v.toFixed(3);
        if (v >= 0.001) return '$' + v.toFixed(4);
        if (v === 0) return '$0.00';
        return '$' + v.toFixed(6);
    }
    function usdParts(n) {
        const s = usd(n);
        const dot = s.indexOf('.');
        if (dot < 0) return { whole: s, frac: '' };
        return { whole: s.slice(0, dot), frac: s.slice(dot) };
    }
    function tok(n) {
        const v = +n || 0;
        if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
        if (v >= 1e3) return (v / 1e3).toFixed(1) + 'K';
        return String(v);
    }
    function modelTokens(detail) {
        const d = detail || {};
        const nested = d.tokens || {};
        return {
            prompt: +(nested.prompt ?? d.prompt_tokens) || 0,
            completion: +(nested.completion ?? d.completion_tokens) || 0,
            total: +(nested.total ?? d.total_tokens) || 0,
        };
    }
    function pct(n, d) { return d ? Math.min(100, Math.max(0, (n / d) * 100)) : 0; }
    function shortDate(iso) {
        if (!iso) return '--';
        const p = iso.split('-');
        return p.length >= 3 ? p[1] + '/' + p[2] : iso;
    }
    function dayName(iso) {
        if (!iso) return '';
        try { return new Date(iso + 'T12:00:00').toLocaleDateString('en', { weekday: 'short' }).toUpperCase(); }
        catch { return ''; }
    }
    function shortModel(m) {
        return String(m || '').replace(/^(gpt-|claude-|gemini-)/, '').split('/').pop() || m;
    }
    function nowHHMMSS() {
        const d = new Date();
        return [d.getHours(), d.getMinutes(), d.getSeconds()].map(v => String(v).padStart(2, '0')).join(':');
    }
    function uiKey(value) {
        return String(value || 'unknown').trim().toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') || 'unknown';
    }
    function workspaceActive() {
        if (!_s.mounted || !_s.el || !_s.el.isConnected || document.hidden) return false;
        return !_s.el.closest('.hidden, [hidden], [aria-hidden="true"]');
    }
    function ensureComponentStyles() {
        if (document.querySelector('link[href*="token_economy_components.css"]')) return;
        const source = document.querySelector('link[href*="token_economy_widget.css"]');
        let version = '';
        try { version = source ? new URL(source.href, window.location.href).search : ''; }
        catch { version = ''; }
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = '/static/css/token_economy_components.css' + version;
        link.dataset.tokenEconomyComponents = 'true';
        document.head.appendChild(link);
    }

    async function api(url) {
        try {
            if (typeof fetchJsonSafe === 'function') return await fetchJsonSafe(url);
            const r = await fetch(url);
            return r.ok ? { ok: true, data: await r.json() } : { ok: false, data: null };
        } catch { return { ok: false, data: null }; }
    }

    // ── data ─────────────────────────────────────────────────────
    async function refresh({ force = false } = {}) {
        if (!workspaceActive()) return;
        if (!force && _s.lastRefresh && Date.now() - _s.lastRefresh < STALE) return;
        _s.loading = true;
        showLoading();

        const [t, s, h, p, prof, matrix] = await Promise.all([
            api('/api/spend/today'),
            api('/api/spend/session'),
            api('/api/spend/history?days=' + _s.period),
            _s.pricing ? { ok: true, data: _s.pricing } : api('/api/spend/pricing'),
            api('/api/runtime/profile'),
            api('/api/runtime/matrix'),
        ]);

        if (t.ok) _s.today = t.data;
        if (s.ok) _s.session = s.data;
        if (h.ok) _s.history = Array.isArray(h.data) ? h.data : [];
        if (p.ok && p.data) {
            _s.pricing = p.data?.pricing || p.data;
            if (Array.isArray(p.data?.runtime_matrix)) _s.matrix = { profiles: p.data.runtime_matrix };
        }
        if (prof.ok && prof.data) {
            _s.profile = prof.data;
            _s.economy = prof.data.economy_level || 'optimal';
            _s.autonomy = prof.data.autonomy_level || 3;
        }
        if (matrix.ok && matrix.data) _s.matrix = matrix.data;

        if (!_s.economy) {
            try {
                const prefs = await api('/api/preferences');
                if (prefs.ok && prefs.data) {
                    const raw = prefs.data?.advanced?.runtime?.default_token_economy;
                    _s.economy = (typeof safeString === 'function' ? safeString(raw) : String(raw || '')).toLowerCase() || 'optimal';
                }
            } catch { /* noop */ }
        }
        if (!_s.economy) _s.economy = 'optimal';

        _s.loading = false;
        _s.lastRefresh = Date.now();
        paint();
    }

    // ── SSE ──────────────────────────────────────────────────────
    function sseOn() {
        if (_s.sse || !workspaceActive()) return;
        if (_s.sseRetry) { clearTimeout(_s.sseRetry); _s.sseRetry = null; }
        try {
            const es = new EventSource('/api/spend/stream');
            _s.sse = es;
            es.addEventListener('spend', (e) => {
                try {
                    const d = JSON.parse(e.data);
                    if (_s.today) {
                        if (typeof d.today_usd === 'number') _s.today.total_usd = d.today_usd;
                        if (d.today_tokens) _s.today.tokens = d.today_tokens;
                        if (typeof d.today_calls === 'number') _s.today.call_count = d.today_calls;
                        if (d.model) {
                            if (!_s.today.by_model_detail) _s.today.by_model_detail = {};
                            const x = _s.today.by_model_detail[d.model] || { usd: 0, calls: 0, tokens: { prompt: 0, completion: 0, total: 0 } };
                            x.usd = (x.usd || 0) + (+d.usd_total || 0);
                            x.calls = (x.calls || 0) + 1;
                            x.tokens.prompt = (x.tokens?.prompt || 0) + (d.prompt_tokens || 0);
                            x.tokens.completion = (x.tokens?.completion || 0) + (d.completion_tokens || 0);
                            x.tokens.total = x.tokens.prompt + x.tokens.completion;
                            x.prompt_tokens = x.tokens.prompt;
                            x.completion_tokens = x.tokens.completion;
                            x.total_tokens = x.tokens.total;
                            _s.today.by_model_detail[d.model] = x;
                        }
                    }
                    paintHero();
                    paintDataStrip();
                    paintModels();
                    pushFeed(d);
                } catch { /* ignore */ }
            });
            es.onerror = () => {
                es.close();
                _s.sse = null;
                if (workspaceActive()) _s.sseRetry = setTimeout(sseOn, 8000);
            };
        } catch { /* unsupported */ }
    }
    function sseOff() {
        if (_s.sse) { _s.sse.close(); _s.sse = null; }
        if (_s.sseRetry) { clearTimeout(_s.sseRetry); _s.sseRetry = null; }
    }


    // Workspace background compatibility. The adapter is static and active-only.
    function injectSpaceBg() {
        if (window.__teSpace && workspaceActive()) window.__teSpace.inject();
    }
    function removeSpaceBg() {
        if (window.__teSpace) window.__teSpace.remove();
    }

    // Live work exists only while Token Economy is the visible workspace.
    function syncClock() {
        const clock = $('[data-te-clock]', _s.el);
        if (clock) clock.textContent = nowHHMMSS();
    }
    function clockStart() {
        clockStop();
        if (!workspaceActive()) return;
        syncClock();
        _s.clockTimer = setInterval(syncClock, 1000);
    }
    function clockStop() {
        if (_s.clockTimer) clearInterval(_s.clockTimer);
        _s.clockTimer = null;
    }
    function onVisibilityChange() {
        if (!_s.mounted) return;
        if (document.hidden) {
            sseOff();
            clockStop();
            removeSpaceBg();
            return;
        }
        injectSpaceBg();
        clockStart();
        sseOn();
        refresh();
    }
    function mount(container) {
        if (!container) return;
        if (_s.mounted) unmount();
        ensureComponentStyles();
        _s.el = container;
        container.innerHTML = shell();
        _s.mounted = true;
        bind();
        injectSpaceBg();
        clockStart();
        document.addEventListener('visibilitychange', onVisibilityChange);
        refresh({ force: true });
        sseOn();
        if (window.ThomasUiLayout) window.ThomasUiLayout.applyAll(container);
    }
    function unmount() {
        document.removeEventListener('visibilitychange', onVisibilityChange);
        sseOff();
        clockStop();
        removeSpaceBg();
        _s.mounted = false;
        _s.el = null;
    }

    function shell() {
        return `
<div class="te-v3" data-ui-id="token-economy.workspace" data-ui-label="Token Economy workspace" data-ui-policy="protected">
    <header class="te-topbar" data-ui-id="token-economy.header" data-ui-label="Token Economy header" data-ui-policy="layout resize contain-parent collision-avoid" data-ui-constraints="minWidth=320 minHeight=44 maxHeight=112">
        <div class="te-topbar-left">
            <span class="thomas-eyes-mark" aria-hidden="true"><i></i><i></i></span>
            <span class="te-heading">
                <strong class="te-topbar-title">Token Economy</strong>
            </span>
            <span class="te-mode-pill" data-te-topmode></span>
        </div>
        <div class="te-topbar-right" aria-label="Token Economy tools">
            <label class="te-range-control" data-ui-id="token-economy.history-window" data-ui-label="History window" data-ui-policy="control no-resize contain-parent">
                <span>Window</span>
                <select class="te-range-sel" data-te-period aria-label="History window">
                    <option value="7">7 days</option>
                    <option value="14">14 days</option>
                    <option value="30">30 days</option>
                    <option value="90">90 days</option>
                </select>
            </label>
            <button class="te-topbar-btn" type="button" data-te-refresh data-ui-id="token-economy.refresh" data-ui-label="Refresh Token Economy" data-ui-policy="control no-resize contain-parent" title="Refresh"><i class="ph ph-arrow-clockwise" aria-hidden="true"></i><span>Refresh</span></button>
            <button class="te-topbar-btn" type="button" data-te-export data-ui-id="token-economy.export" data-ui-label="Export token ledger" data-ui-policy="control no-resize contain-parent" title="Export CSV"><i class="ph ph-download-simple" aria-hidden="true"></i><span>Export</span></button>
            <span class="te-topbar-clock" data-te-clock>${nowHHMMSS()}</span>
            <span class="te-topbar-live"><span class="te-dot"></span>Live</span>
        </div>
    </header>

    <div class="te-overview-rail">
        <section class="te-hero" data-te-hero data-ui-id="token-economy.overview" data-ui-label="Today's token overview" data-ui-policy="layout resize contain-parent collision-avoid" data-ui-constraints="minWidth=220 minHeight=76 maxHeight=180">
            <span class="te-eyebrow">Today</span>
            <div class="te-hero-cost">
                <span class="te-hero-dollar" data-te-hdollar>TOK</span><span class="te-hero-whole" data-te-hwhole>0</span><span class="te-hero-frac" data-te-hfrac> used</span>
            </div>
            <div class="te-hero-sub"><span data-te-hcalls>0</span> calls <span class="te-hero-pipe">/</span> <span data-te-htokens>0</span> tokens</div>
            <div class="te-burnstrip" data-te-burnstrip aria-label="Daily token budget progress">
                <div class="te-burnstrip-fill" data-te-burnfill></div>
                <div class="te-burnstrip-marker" data-te-burnmark></div>
            </div>
        </section>
        <section class="te-datastrip" data-te-datastrip data-ui-id="token-economy.summary" data-ui-label="Token summary metrics" data-ui-policy="layout resize contain-parent collision-avoid" data-ui-constraints="minWidth=280 minHeight=76 maxHeight=180" aria-live="polite"></section>
    </div>

    <main class="te-main">
        <div class="te-col-left">
            <section class="te-panel te-panel-grow" data-ui-id="token-economy.history" data-ui-label="Token history" data-ui-policy="layout resize contain-parent collision-avoid" data-ui-constraints="minWidth=280 minHeight=190">
                <div class="te-panel-head">
                    <span>Token history</span>
                    <span class="te-panel-sub" data-te-htotal></span>
                </div>
                <div class="te-spectrum" data-te-spectrum></div>
            </section>
            <section class="te-panel" data-ui-id="token-economy.ledger" data-ui-label="Live token ledger" data-ui-policy="layout resize contain-parent collision-avoid" data-ui-constraints="minWidth=280 minHeight=130">
                <div class="te-panel-head">
                    <span><span class="te-dot"></span> Live ledger</span>
                    <span class="te-panel-sub" data-te-fcount>Awaiting events</span>
                </div>
                <div class="te-terminal" data-te-terminal aria-live="polite">
                    <div class="te-term-line te-term-sys">Ready. New token events will appear here.</div>
                </div>
            </section>
        </div>

        <div class="te-col-right">
            <section class="te-panel te-policy-panel" data-ui-id="token-economy.policy" data-ui-label="Economy policy controls" data-ui-policy="protected" data-ui-constraints="minWidth=280 minHeight=220">
                <div class="te-panel-head">
                    <span>Economy policy</span>
                    <span class="te-panel-sub" data-te-modelabel></span>
                </div>
                <div class="te-switch-track" data-te-modes></div>
                <div class="te-mode-readout" data-te-modereadout></div>
                <div class="te-context-meter" data-te-ctxmeter>
                    <div class="te-ctx-label">
                        <span>Context budget</span>
                        <span data-te-ctxval></span>
                    </div>
                    <div class="te-ctx-track"><div class="te-ctx-fill" data-te-ctxfill></div></div>
                </div>
            </section>
            <section class="te-panel" data-ui-id="token-economy.models" data-ui-label="Model token mix" data-ui-policy="layout resize contain-parent collision-avoid" data-ui-constraints="minWidth=280 minHeight=160">
                <div class="te-panel-head">
                    <span>Model mix</span>
                    <span class="te-panel-sub" data-te-mtitle>Today</span>
                </div>
                <div data-te-modelviz data-ui-group-policy="managed-collection"></div>
                <div data-te-modeltable data-ui-group-policy="managed-collection"></div>
            </section>
            <section class="te-panel" data-ui-id="token-economy.profile-matrix" data-ui-label="Runtime profile matrix" data-ui-policy="layout resize contain-parent collision-avoid" data-ui-constraints="minWidth=280 minHeight=140">
                <div class="te-panel-head"><span>Runtime profiles</span></div>
                <div data-te-pricing></div>
            </section>
        </div>
    </main>
</div>`;
    }

    // ── paint ────────────────────────────────────────────────────
    function showLoading() {
        const ds = $('[data-te-datastrip]', _s.el);
        if (ds && !_s.today) ds.innerHTML = '<div class="te-loading">loading…</div>';
    }

    function paint() {
        if (!_s.el || !_s.mounted) return;
        paintHero();
        paintDataStrip();
        paintModes();
        paintBudget();
        paintModels();
        paintSpectrum();
        paintPricing();
        paintTopMode();
        if (window.ThomasUiLayout) window.ThomasUiLayout.applyAll(_s.el);
    }

    function paintTopMode() {
        const el = $('[data-te-topmode]', _s.el);
        if (!el) return;
        const active = MODE_SPECS[_s.economy] || MODE_SPECS.optimal;
        el.textContent = active.mul + ' ' + active.name.toUpperCase();
    }

    function paintHero() {
        const label = $('[data-te-hdollar]', _s.el);
        const whole = $('[data-te-hwhole]', _s.el);
        const frac = $('[data-te-hfrac]', _s.el);
        const calls = $('[data-te-hcalls]', _s.el);
        const tokens = $('[data-te-htokens]', _s.el);
        const hero = $('[data-te-hero]', _s.el);
        const burnfill = $('[data-te-burnfill]', _s.el);
        const burnmark = $('[data-te-burnmark]', _s.el);
        if (!whole) return;

        const t = _s.today || {};
        const numCalls = +t.call_count || 0;
        const toks = t.tokens || {};
        const totalTokens = +toks.total || 0;

        if (label) label.textContent = 'TOK';
        whole.textContent = tok(totalTokens);
        frac.textContent = ' used';
        if (calls) calls.textContent = numCalls;
        if (tokens) tokens.textContent = tok(totalTokens);

        if (hero) {
            const tone = totalTokens > 250000 ? 'te-tone-hot' : totalTokens > 75000 ? 'te-tone-warm' : totalTokens > 0 ? 'te-tone-active' : 'te-tone-idle';
            hero.className = 'te-hero ' + tone;
        }

        if (burnfill) {
            const defaultBudget = { cheap: 250000, optimal: 650000, max: 2000000 };
            const budget = +(_s.profile?.hard_budget || defaultBudget[_s.economy] || defaultBudget.optimal);
            burnfill.style.width = pct(totalTokens, budget) + '%';
        }

        if (burnmark) {
            const hour = new Date().getHours();
            burnmark.style.left = ((hour / 24) * 100) + '%';
        }
    }

    function paintDataStrip() {
        const el = $('[data-te-datastrip]', _s.el);
        if (!el) return;
        const t = _s.today || {};
        const s = _s.session || {};
        const toks = t.tokens || {};
        const sessionToks = s.tokens || {};
        const numCalls = +t.call_count || 0;
        const totalTokens = +toks.total || 0;
        const avgTokens = numCalls > 0 ? Math.round(totalTokens / numCalls) : 0;

        const hist = _s.history || [];
        const histTokenTotal = (row) => +((row?.tokens || {}).total ?? row?.total_tokens) || 0;
        const yesterday = hist.length >= 2 ? histTokenTotal(hist[hist.length - 2]) : 0;
        let deltaHtml = '';
        if (yesterday > 0 && totalTokens > 0) {
            const pctChange = ((totalTokens - yesterday) / yesterday) * 100;
            const cls = pctChange > 5 ? 'te-delta-up' : pctChange < -5 ? 'te-delta-down' : 'te-delta-flat';
            const sign = pctChange > 0 ? '+' : '';
            deltaHtml = `<span class="te-ds-delta ${cls}">${sign}${Math.round(pctChange)}%</span>`;
        }

        el.innerHTML = `
            <div class="te-ds-cell te-ds-wide" data-ui-id="token-economy.metric" data-ui-instance-key="session" data-ui-group="token-economy.summary" data-ui-group-policy="managed-collection" data-ui-label="Session tokens" data-ui-policy="protected">
                <span class="te-ds-num">${esc(tok(+sessionToks.total || 0))}</span>
                <span class="te-ds-label">SESSION TOKENS</span>
                <span class="te-ds-note">${+s.call_count || 0} calls</span>
            </div>
            <div class="te-ds-cell" data-ui-id="token-economy.metric" data-ui-instance-key="prompt" data-ui-group="token-economy.summary" data-ui-group-policy="managed-collection" data-ui-label="Prompt tokens" data-ui-policy="protected">
                <span class="te-ds-num">${esc(tok(+toks.prompt || 0))}</span>
                <span class="te-ds-label">TOKENS IN</span>
            </div>
            <div class="te-ds-cell" data-ui-id="token-economy.metric" data-ui-instance-key="completion" data-ui-group="token-economy.summary" data-ui-group-policy="managed-collection" data-ui-label="Completion tokens" data-ui-policy="protected">
                <span class="te-ds-num">${esc(tok(+toks.completion || 0))}</span>
                <span class="te-ds-label">TOKENS OUT</span>
            </div>
            <div class="te-ds-cell" data-ui-id="token-economy.metric" data-ui-instance-key="average" data-ui-group="token-economy.summary" data-ui-group-policy="managed-collection" data-ui-label="Average tokens per call" data-ui-policy="protected">
                <span class="te-ds-num">${esc(tok(avgTokens))}</span>
                <span class="te-ds-label">AVG TOK/CALL</span>
                ${deltaHtml}
            </div>`;
    }

    function paintModes() {
        const el = $('[data-te-modes]', _s.el);
        const readout = $('[data-te-modereadout]', _s.el);
        const mLabel = $('[data-te-modelabel]', _s.el);
        if (!el) return;

        const modes = ['cheap', 'optimal', 'max'];
        const activeIdx = modes.indexOf(_s.economy);

        // 3-position switch
        el.innerHTML = `<div class="te-switch-bg">` +
            `<div class="te-switch-thumb" style="left:${activeIdx >= 0 ? (activeIdx * 33.333) : 33.333}%"></div>` +
            modes.map((id, i) => {
                const m = MODE_SPECS[id];
                const active = _s.economy === id;
                return `<button class="te-switch-opt${active ? ' active' : ''}" data-mode="${id}" data-ui-id="token-economy.economy-mode" data-ui-instance-key="${id}" data-ui-group="token-economy.policy" data-ui-group-policy="protected-controls" data-ui-label="${m.name} economy policy" data-ui-policy="protected">` +
                    `<span class="te-sw-mul">${m.mul}</span>` +
                    `<span class="te-sw-name">${m.tag}</span></button>`;
            }).join('') +
            `</div>`;

        const active = MODE_SPECS[_s.economy] || MODE_SPECS.optimal;
        if (mLabel) mLabel.textContent = active.name.toLowerCase();

        if (readout) {
            const p = _s.profile;
            const passes = p?.pass_range ? p.pass_range[0] + '–' + p.pass_range[1] : active.passes;
            const budget = p ? (p.hard_budget ? tok(p.hard_budget) : '∞') : active.budget;
            const skills = p?.skills_mode || active.skills;

            readout.innerHTML =
                `<span class="te-ro-desc">${esc(active.desc)}</span>` +
                `<div class="te-ro-grid">` +
                `<span>passes</span><span>${esc(passes)}</span>` +
                `<span>budget</span><span>${esc(budget)}</span>` +
                `<span>retries</span><span>${esc(active.retries)}</span>` +
                `<span>overhead</span><span>${esc(active.overhead)}</span>` +
                `<span>skills</span><span>${esc(skills)}</span>` +
                `</div>`;
        }
    }

    function paintBudget() {
        const fill = $('[data-te-ctxfill]', _s.el);
        const val = $('[data-te-ctxval]', _s.el);
        if (!fill) return;
        const s = _s.session || {};
        const used = +(s.tokens?.total) || 0;
        const budgets = { cheap: 250000, optimal: 650000, max: 2000000 };
        const budget = _s.economy === 'max' ? 2000000 : (budgets[_s.economy] || 650000);
        const p = pct(used, budget);
        fill.style.width = p + '%';
        fill.className = 'te-ctx-fill' + (p > 85 ? ' te-ctx-danger' : p > 60 ? ' te-ctx-warn' : '');
        if (val) val.textContent = tok(used) + ' / ' + (_s.economy === 'max' ? '∞' : tok(budget));
    }

    function paintModels() {
        const vizEl = $('[data-te-modelviz]', _s.el);
        const tableEl = $('[data-te-modeltable]', _s.el);
        if (!tableEl) return;

        const detail = _s.today?.by_model_detail || {};
        const rows = Object.entries(detail)
            .map(([n, d]) => {
                const mt = modelTokens(d);
                return { n, usd: +d.usd || 0, calls: +d.calls || 0, prompt: mt.prompt, completion: mt.completion, total: mt.total };
            })
            .sort((a, b) => (b.total - a.total) || (b.usd - a.usd));

        if (!rows.length) {
            if (vizEl) vizEl.innerHTML = '<div class="te-idle-viz"><span class="te-idle-pulse"></span></div>';
            tableEl.innerHTML = '<div class="te-empty-state">no model usage today</div>';
            return;
        }

        const sum = rows.reduce((a, r) => ({
            usd: a.usd + r.usd,
            calls: a.calls + r.calls,
            prompt: a.prompt + r.prompt,
            completion: a.completion + r.completion,
            total: a.total + r.total,
        }), { usd: 0, calls: 0, prompt: 0, completion: 0, total: 0 });

        if (vizEl) {
            vizEl.innerHTML = rows.map((r, i) => {
                const w = sum.total > 0 ? Math.max(4, (r.total / sum.total) * 100) : 100 / rows.length;
                const color = MODEL_COLORS[i % MODEL_COLORS.length];
                return `<div class="te-mprop" data-ui-id="token-economy.model-share" data-ui-instance-key="${esc(uiKey(r.n))}" data-ui-group="token-economy.models" data-ui-group-policy="managed-collection" data-ui-label="${esc(shortModel(r.n))} token share" data-ui-policy="protected"><div class="te-mprop-bar" style="width:${w}%;background:${color}"></div><span class="te-mprop-name">${esc(shortModel(r.n))}</span><span class="te-mprop-val">${esc(tok(r.total))}</span></div>`;
            }).join('');
        }

        tableEl.innerHTML = `<table class="te-mtbl"><tbody>` +
            rows.map((r, i) => {
                const color = MODEL_COLORS[i % MODEL_COLORS.length];
                return `<tr data-ui-id="token-economy.model-ledger-row" data-ui-instance-key="${esc(uiKey(r.n))}" data-ui-group="token-economy.models" data-ui-group-policy="managed-collection" data-ui-label="${esc(shortModel(r.n))} model ledger row" data-ui-policy="protected"><td><span class="te-mdot" style="background:${color}"></span>${esc(shortModel(r.n))}</td><td>${esc(tok(r.total))}</td><td>${r.calls}</td><td>${esc(tok(r.prompt))}/${esc(tok(r.completion))}</td></tr>`;
            }).join('') +
            `<tr class="te-mtbl-total"><td>TOTAL</td><td>${esc(tok(sum.total))}</td><td>${sum.calls}</td><td>${esc(tok(sum.prompt))}/${esc(tok(sum.completion))}</td></tr></tbody></table>`;
    }

    function paintSpectrum() {
        const el = $('[data-te-spectrum]', _s.el);
        const tot = $('[data-te-htotal]', _s.el);
        if (!el) return;
        const rows = _s.history || [];

        if (!rows.length) {
            el.innerHTML = '<div class="te-empty-state">' +
                '<div class="te-empty-chart">' +
                '<svg viewBox="0 0 300 100" preserveAspectRatio="none" class="te-empty-svg">' +
                '<polyline points="0,90 30,82 60,75 90,68 120,72 150,55 180,58 210,42 240,35 270,28 300,18" fill="none" stroke="rgba(88,166,255,0.15)" stroke-width="1.5"/>' +
                '<polyline points="0,90 30,82 60,75 90,68 120,72 150,55 180,58 210,42 240,35 270,28 300,18 300,100 0,100" fill="url(#te-ghost-fill)" stroke="none"/>' +
                '<defs><linearGradient id="te-ghost-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="rgba(88,166,255,0.08)"/><stop offset="100%" stop-color="rgba(88,166,255,0)"/></linearGradient></defs>' +
                '</svg>' +
                '</div>' +
                '<span class="te-empty-label">awaiting first API call</span>' +
                '</div>';
            return;
        }

        const rowTokenTotal = (row) => +((row?.tokens || {}).total ?? row?.total_tokens) || 0;
        const max = Math.max(...rows.map(rowTokenTotal), 1);
        const sum = rows.reduce((a, r) => a + rowTokenTotal(r), 0);
        const todayDate = new Date().toISOString().split('T')[0];
        if (tot) tot.textContent = tok(sum) + ' tokens / ' + rows.length + 'd';

        // Vertical spectrum bars (bottom-up like an equalizer)
        el.innerHTML = `<div class="te-spec-grid">${rows.map(r => {
            const v = rowTokenTotal(r);
            const h = Math.max(2, Math.round(pct(v, max)));
            const isToday = r.date === todayDate;
            const tone = v > 250000 ? ' te-spec-hot' : v > 75000 ? ' te-spec-warm' : '';
            return `<div class="te-spec-col${isToday ? ' te-spec-today' : ''}" data-ui-id="token-economy.history-day" data-ui-instance-key="${esc(uiKey(r.date))}" data-ui-group="token-economy.history" data-ui-group-policy="managed-collection" data-ui-label="Token use ${esc(r.date || 'unknown date')}" data-ui-policy="protected">` +
                `<div class="te-spec-bar${tone}" style="height:${h}%"></div>` +
                `<span class="te-spec-date">${shortDate(r.date).split('/')[1] || ''}</span>` +
                `<span class="te-spec-amt">${v > 0 ? esc(tok(v)) : ''}</span>` +
                `</div>`;
        }).join('')}</div>`;
    }

    function paintPricingLegacy() {
        const el = $('[data-te-pricing]', _s.el);
        if (!el || !_s.pricing) { if (el) el.innerHTML = ''; return; }
        const entries = Object.entries(_s.pricing);
        if (!entries.length) { el.innerHTML = ''; return; }
        el.innerHTML = `<div class="te-rate-grid">` +
            `<span class="te-rh">model</span><span class="te-rh">in $/1M</span><span class="te-rh">out $/1M</span>` +
            entries.slice(0, 10).map(([name, p]) => {
                const inP = +(p?.prompt_per_1m || p?.input_per_1m || 0);
                const outP = +(p?.completion_per_1m || p?.output_per_1m || 0);
                return `<span class="te-rn">${esc(shortModel(name))}</span><span class="te-rv">${inP ? '$' + inP.toFixed(2) : '—'}</span><span class="te-rv">${outP ? '$' + outP.toFixed(2) : '—'}</span>`;
            }).join('') +
            '</div>';
    }

    function paintPricing() {
        const el = $('[data-te-pricing]', _s.el);
        if (!el) return;

        const profile = _s.profile || {};
        const profiles = Array.isArray(_s.matrix?.profiles) ? _s.matrix.profiles : [];
        const activeAutonomy = +(_s.autonomy || profile.autonomy_level || 3);
        const activeEconomy = profile.economy_level || _s.economy || 'optimal';
        const order = { cheap: 0, optimal: 1, max: 2 };
        const rows = profiles
            .filter((r) => !activeAutonomy || +r.autonomy_level === activeAutonomy)
            .sort((a, b) => (order[a.economy_level] ?? 9) - (order[b.economy_level] ?? 9));
        const visibleRows = rows.length ? rows : profiles.slice(0, 3);

        if (!visibleRows.length && !profile.summary) {
            el.innerHTML = '<div class="te-empty-state">runtime profile unavailable</div>';
            return;
        }

        const summary = profile.summary || `${profile.autonomy_name || 'runtime'} / ${activeEconomy}`;
        const budget = profile.hard_budget ? tok(profile.hard_budget) : (profile.context_budget ? tok(profile.context_budget) : 'open');
        const activeLine =
            `<div class="te-mode-readout">` +
            `<span class="te-ro-desc">${esc(summary)}</span>` +
            `<div class="te-ro-grid">` +
            `<span>autonomy</span><span>${esc(String(profile.autonomy_name || activeAutonomy))}</span>` +
            `<span>economy</span><span>${esc(activeEconomy)}</span>` +
            `<span>token budget</span><span>${esc(budget)}</span>` +
            `</div></div>`;

        const grid = visibleRows.length ? `<div class="te-rate-grid te-profile-grid">` +
            `<span class="te-rh">profile</span><span class="te-rh">budget</span><span class="te-rh">passes</span>` +
            visibleRows.slice(0, 6).map((r) => {
                const econ = r.economy_level || 'optimal';
                const active = econ === activeEconomy && +r.autonomy_level === activeAutonomy;
                const b = r.hard_budget ? tok(r.hard_budget) : (r.context_budget ? tok(r.context_budget) : 'open');
                const passes = Array.isArray(r.pass_range) ? r.pass_range.join('-') : (r.pass_range || '?');
                return `<span class="te-rn${active ? ' active' : ''}" data-ui-id="token-economy.profile" data-ui-instance-key="${esc(uiKey(String(r.autonomy_level) + '-' + econ))}" data-ui-group="token-economy.profile-matrix" data-ui-group-policy="managed-collection" data-ui-label="${esc(econ)} runtime profile" data-ui-policy="protected">${esc(econ.toUpperCase())}</span><span class="te-rv">${esc(b)}</span><span class="te-rv">${esc(String(passes))}</span>`;
            }).join('') +
            '</div>' : '';

        el.innerHTML = activeLine + grid;
    }

    function pushFeed(d) {
        const prompt = +d.prompt_tokens || 0;
        const completion = +d.completion_tokens || 0;
        const ev = {
            id: `${Date.now()}-${_s.feedSequence++}`,
            ts: d.ts || new Date().toISOString(),
            model: d.model || '?',
            prompt,
            completion,
            tokens: prompt + completion,
            usd: +d.usd_total || 0,
        };
        _s.feedEvents.unshift(ev);
        if (_s.feedEvents.length > 50) _s.feedEvents.length = 50;

        const el = $('[data-te-terminal]', _s.el);
        const cnt = $('[data-te-fcount]', _s.el);
        if (cnt) cnt.textContent = _s.feedEvents.length + ' events';
        if (!el) return;

        el.innerHTML = _s.feedEvents.slice(0, 40).map((ev, i) => {
            const t = ev.ts ? ev.ts.split('T')[1]?.substring(0, 8) || '' : '';
            return `<div class="te-term-line${i === 0 ? ' te-term-new' : ''}" data-ui-id="token-economy.ledger-event" data-ui-instance-key="${esc(ev.id)}" data-ui-group="token-economy.ledger" data-ui-group-policy="managed-collection" data-ui-label="${esc(shortModel(ev.model))} token event" data-ui-policy="protected">` +
                `<span class="te-term-ts">${esc(t)}</span> ` +
                `<span class="te-term-model">${esc(shortModel(ev.model))}</span> ` +
                `<span class="te-term-tok">${esc(tok(ev.tokens))}tok</span> ` +
                `<span class="te-term-cost">in ${esc(tok(ev.prompt))} / out ${esc(tok(ev.completion))}</span>` +
                `</div>`;
        }).join('');
    }

    // ── events ───────────────────────────────────────────────────
    function bind() {
        const root = _s.el;
        if (!root) return;

        const sel = $('[data-te-period]', root);
        if (sel) {
            sel.value = String(_s.period);
            sel.addEventListener('change', () => {
                _s.period = parseInt(sel.value, 10) || 7;
                _s.history = null;
                refresh({ force: true });
            });
        }
        const rb = $('[data-te-refresh]', root);
        if (rb) rb.addEventListener('click', () => refresh({ force: true }));

        const eb = $('[data-te-export]', root);
        if (eb) eb.addEventListener('click', () => window.open('/api/spend/export.csv?days=' + _s.period, '_blank'));

        root.addEventListener('click', (e) => {
            const btn = e.target.closest('.te-switch-opt');
            if (!btn) return;
            const mode = btn.dataset.mode;
            if (!mode || mode === _s.economy) return;
            _s.economy = mode;
            paintModes();
            paintBudget();
            paintHero();
            paintTopMode();
            setEconomy(mode);
        });
    }

    async function setEconomy(mode) {
        try {
            await fetch('/api/preferences', {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ advanced: { runtime: { default_token_economy: mode } } }),
            });
        } catch { /* best effort */ }
    }

    // The compatibility treatment mounts with the visible workspace and tears
    // down on hide or unmount without installing a global background.
    window.__moduleBackgrounds = window.__moduleBackgrounds || {};
    window.__moduleBackgrounds['token_economy'] = {
        mount: injectSpaceBg,
        unmount: removeSpaceBg,
    };

    window.__tokenEconomy = { mount, unmount, refresh, getState: () => ({ ..._s }) };
})();
