/**
 * token_economy.js — Token Economy workspace panel v3
 *
 * Design: Bloomberg Terminal × spacecraft instruments.
 * No circular gauges, no uniform card grids, no AI slop.
 * Typography IS the design. Numbers dominate. Data is dense.
 *
 * Hooks into the module system via window.__tokenEconomy.
 * Consumes /api/spend/* endpoints + SSE for live updates.
 *
 * Space rendering engine lives in token_economy_space.js (loaded on demand).
 */

// Space engine is now loaded globally via index.html <script> tag.
// This guard is kept only for edge cases (e.g. standalone preview pages).
if (!window.__teSpace) {
    const _teS = document.createElement('script');
    _teS.src = '/static/js/token_economy_space.js';
    _teS.async = false;
    document.head.appendChild(_teS);
}

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
        period: 7,
        economy: '',
        autonomy: 3,
        modelScope: 'session',
        sse: null,
        el: null,
        lastRefresh: 0,
        feedEvents: [],
        tickFrame: null,
        tickAngle: 0,
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

    function modelBreakdown(detail) {
        const source = detail && typeof detail === 'object' ? detail : {};
        return Object.entries(source)
            .map(([n, d]) => {
                const prompt = +(d?.prompt_tokens ?? d?.tokens?.prompt) || 0;
                const completion = +(d?.completion_tokens ?? d?.tokens?.completion) || 0;
                const total = +(d?.total_tokens ?? d?.tokens?.total) || (prompt + completion);
                return { n, usd: +d?.usd || 0, calls: +d?.calls || 0, prompt, completion, total };
            })
            .sort((a, b) => b.usd - a.usd);
    }

    function ensureSpendShape(target) {
        if (!target || typeof target !== 'object') return null;
        if (!target.tokens) target.tokens = { prompt: 0, completion: 0, total: 0 };
        if (!target.by_model_detail || typeof target.by_model_detail !== 'object') target.by_model_detail = {};
        return target;
    }

    function applySpendEvent(target, d, totals = null) {
        const bucket = ensureSpendShape(target);
        if (!bucket) return;

        if (totals?.tokens) {
            bucket.tokens = {
                prompt: +(totals.tokens.prompt) || 0,
                completion: +(totals.tokens.completion) || 0,
                total: +(totals.tokens.total) || 0,
            };
        } else {
            bucket.tokens.prompt = (+bucket.tokens.prompt || 0) + (+d.prompt_tokens || 0);
            bucket.tokens.completion = (+bucket.tokens.completion || 0) + (+d.completion_tokens || 0);
            bucket.tokens.total = (+bucket.tokens.prompt || 0) + (+bucket.tokens.completion || 0);
        }

        if (typeof totals?.total_usd === 'number') bucket.total_usd = totals.total_usd;
        else bucket.total_usd = (+bucket.total_usd || 0) + (+d.usd_total || 0);

        if (typeof totals?.call_count === 'number') bucket.call_count = totals.call_count;
        else bucket.call_count = (+bucket.call_count || 0) + 1;

        if (d.model) {
            const row = bucket.by_model_detail[d.model] || {
                usd: 0,
                calls: 0,
                prompt_tokens: 0,
                completion_tokens: 0,
                total_tokens: 0,
            };
            row.usd = (+row.usd || 0) + (+d.usd_total || 0);
            row.calls = (+row.calls || 0) + 1;
            row.prompt_tokens = (+row.prompt_tokens || 0) + (+d.prompt_tokens || 0);
            row.completion_tokens = (+row.completion_tokens || 0) + (+d.completion_tokens || 0);
            row.total_tokens = (+row.prompt_tokens || 0) + (+row.completion_tokens || 0);
            bucket.by_model_detail[d.model] = row;
        }
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
        if (!force && _s.lastRefresh && Date.now() - _s.lastRefresh < STALE) return;
        _s.loading = true;
        showLoading();

        const [t, s, h, p, prof] = await Promise.all([
            api('/api/spend/today'),
            api('/api/spend/session'),
            api('/api/spend/history?days=' + _s.period),
            _s.pricing ? { ok: true, data: _s.pricing } : api('/api/spend/pricing'),
            api('/api/runtime/profile'),
        ]);

        if (t.ok) _s.today = t.data;
        if (s.ok) _s.session = s.data;
        if (h.ok) _s.history = Array.isArray(h.data) ? h.data : [];
        if (p.ok && p.data) _s.pricing = p.data?.pricing || p.data;
        if (prof.ok && prof.data) {
            _s.profile = prof.data;
            _s.economy = prof.data.economy_level || 'optimal';
            _s.autonomy = prof.data.autonomy_level || 3;
        }

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
        if (_s.sse) return;
        try {
            const es = new EventSource('/api/spend/stream');
            _s.sse = es;
            es.addEventListener('spend', (e) => {
                try {
                    const d = JSON.parse(e.data);
                    if (_s.today) {
                        applySpendEvent(_s.today, d, {
                            total_usd: typeof d.today_usd === 'number' ? d.today_usd : undefined,
                            call_count: typeof d.today_calls === 'number' ? d.today_calls : undefined,
                            tokens: d.today_tokens || undefined,
                        });
                    }
                    if (_s.session) {
                        applySpendEvent(_s.session, d);
                    }
                    paintHero();
                    paintDataStrip();
                    paintBudget();
                    paintModels();
                    pushFeed(d);
                } catch { /* ignore */ }
            });
            es.onerror = () => { es.close(); _s.sse = null; setTimeout(sseOn, 8000); };
        } catch { /* unsupported */ }
    }
    function sseOff() { if (_s.sse) { _s.sse.close(); _s.sse = null; } }


    // ── Space rendering engine (extracted to token_economy_space.js) ──
    // Space is now globally injected at page load (index.html).
    // injectSpaceBg is kept for API compat but is effectively a no-op
    // since the global init already called inject(). removeSpaceBg is a
    // no-op so the module system doesn't tear down the global background.
    function injectSpaceBg() { if (window.__teSpace) window.__teSpace.inject(); }
    function removeSpaceBg() { /* no-op — space bg is global now */ }

    // ── Plugin iframe theme injection ──────────────────────────
    // Plugins run in iframes with their own stylesheets.
    // We inject a <style> override to make them transparent against space.
    const _IFRAME_SPACE_CSS = `
        html, body {
            background: transparent !important;
            color: #ececf1 !important;
        }
        .panel, .card, section, .app-shell > section {
            background: rgba(8, 12, 20, 0.55) !important;
            border-color: rgba(88, 166, 255, 0.14) !important;
            color: #ececf1 !important;
            backdrop-filter: blur(6px);
            -webkit-backdrop-filter: blur(6px);
        }
        .panel:hover, .card:hover {
            border-color: rgba(88, 166, 255, 0.30) !important;
        }
        .hero {
            background: linear-gradient(135deg, rgba(10, 16, 28, 0.90), rgba(8, 24, 52, 0.85)) !important;
        }
        input, select, textarea {
            background: rgba(255, 255, 255, 0.06) !important;
            border-color: rgba(88, 166, 255, 0.18) !important;
            color: #ececf1 !important;
        }
        input::placeholder { color: rgba(236, 236, 241, 0.35) !important; }
        h1, h2, h3, strong { color: #f0f4ff !important; }
        p, span, label, .panel-kicker, .eyebrow { color: rgba(236, 236, 241, 0.75) !important; }
        .panel-meta, .item-meta { color: rgba(236, 236, 241, 0.50) !important; }
        button[type="submit"], .btn-primary {
            background: rgba(88, 166, 255, 0.20) !important;
            border-color: rgba(88, 166, 255, 0.35) !important;
            color: #8cc8ff !important;
        }
        .hero-stat {
            background: rgba(255, 255, 255, 0.06) !important;
            border-color: rgba(255, 255, 255, 0.08) !important;
        }
        .item-row, .item-card { border-color: rgba(88, 166, 255, 0.10) !important; }
    `;

    function _injectIframeThemes() {
        const iframes = document.querySelectorAll('#moduleWorkspace iframe');
        iframes.forEach(iframe => {
            // Inject now if loaded
            _injectIntoIframe(iframe);
            // Also inject on load (iframe may still be loading)
            if (!iframe._teSpaceLoadHandler) {
                iframe._teSpaceLoadHandler = () => {
                    if (document.body.classList.contains('te-space-active')) {
                        _injectIntoIframe(iframe);
                    }
                };
                iframe.addEventListener('load', iframe._teSpaceLoadHandler);
            }
        });
    }
    function _injectIntoIframe(iframe) {
        try {
            const doc = iframe.contentDocument;
            if (!doc || !doc.head) return;
            if (doc.getElementById('te-space-iframe-theme')) return;
            const style = doc.createElement('style');
            style.id = 'te-space-iframe-theme';
            style.textContent = _IFRAME_SPACE_CSS;
            doc.head.appendChild(style);
        } catch (e) { /* cross-origin */ }
    }

    function _removeIframeThemes() {
        const iframes = document.querySelectorAll('#moduleWorkspace iframe');
        iframes.forEach(iframe => {
            try {
                const doc = iframe.contentDocument;
                if (!doc) return;
                const style = doc.getElementById('te-space-iframe-theme');
                if (style) style.remove();
            } catch (e) { /* cross-origin */ }
        });
    }

    // MutationObserver to catch iframes that load after the space bg is mounted
    let _iframeObserver = null;
    function _watchForIframes() {
        if (_iframeObserver) return;
        const ws = document.getElementById('moduleWorkspace');
        if (!ws) return;
        _iframeObserver = new MutationObserver(() => {
            if (document.body.classList.contains('te-space-active')) {
                _injectIframeThemes();
            }
        });
        _iframeObserver.observe(ws, { childList: true, subtree: true });
    }
    function _unwatchIframes() {
        if (_iframeObserver) { _iframeObserver.disconnect(); _iframeObserver = null; }
    }

    // ── Wire up space engine callbacks ─────────────────────────
    if (window.__teSpace) {
        window.__teSpace.init({
            onEnter: function() { _injectIframeThemes(); _watchForIframes(); floaterStart(); },
            onLeave: function() { floaterStop(); _removeIframeThemes(); _unwatchIframes(); },
        });
    }

    // ── Floating robots — random office bots drift across space ──
    let _floaterTimer = null;
    let _screensaverTimer = null;
    let _screensaverActive = false;
    const SCREENSAVER_IDLE_MS = 90000; // 90 seconds of inactivity

    // ── IDLE THOMAS — sits by the composer, breathes, blinks, talks randomly ──
    let _idleThomasEl = null;
    let _idleSpeechTimer = null;

    const THOMAS_IDLE_LINES = [
        'Systems nominal.',
        'Standing by...',
        'Ready for input.',
        'All quiet out here.',
        'Space is beautiful.',
        'Monitoring channels.',
        'Core temp stable.',
        'Signal strong.',
        'Orbit steady.',
        'Awaiting orders.',
        'Processing...',
        'Tokens flowing.',
        'Scanning horizon.',
        'Hull integrity 100%.',
        'Fuel cells charged.',
        'Navigation locked.',
        'Comms online.',
        'Enjoying the view.',
        'Nebula looks nice today.',
        'Sensors green.',
    ];

    function _positionIdleThomas() {
        if (!_idleThomasEl) return;
        /* Park Thomas just left of the composer textarea */
        var textarea = document.getElementById('composerTextarea');
        if (textarea) {
            var rect = textarea.getBoundingClientRect();
            _idleThomasEl.style.left = Math.max(8, Math.round(rect.left - 88)) + 'px';
        } else {
            var sidebar = document.querySelector('.sidebar');
            var leftOffset = 28;
            if (sidebar && !sidebar.classList.contains('collapsed')) {
                leftOffset = sidebar.offsetWidth + 28;
            }
            _idleThomasEl.style.left = leftOffset + 'px';
        }
    }

    let _sidebarObserver = null;

    function _createIdleThomas() {
        if (_idleThomasEl) return;
        const el = document.createElement('div');
        el.id = 'te-idle-thomas';
        el.innerHTML =
            '<div class="te-floater-bot" style="--bot-primary:#9ad8ff;--bot-secondary:#5aaeff">' +
                '<div class="te-floater-visual">' +
                    '<div class="te-floater-head"><div class="te-floater-eye left"></div><div class="te-floater-eye right"></div></div>' +
                    '<div class="te-floater-body"></div>' +
                    '<div class="te-floater-leg left"></div><div class="te-floater-leg right"></div>' +
                '</div>' +
                '<span class="te-floater-name">Thomas</span>' +
            '</div>' +
            '<div class="te-idle-speech"></div>';
        document.body.appendChild(el);
        _idleThomasEl = el;
        _positionIdleThomas();
        // Watch sidebar for collapse/expand to reposition
        var sidebar = document.querySelector('.sidebar');
        if (sidebar) {
            _sidebarObserver = new MutationObserver(_positionIdleThomas);
            _sidebarObserver.observe(sidebar, { attributes: true, attributeFilter: ['class'] });
        }
        _startIdleSpeech();
    }

    function _removeIdleThomas() {
        if (_idleSpeechTimer) { clearTimeout(_idleSpeechTimer); _idleSpeechTimer = null; }
        if (_sidebarObserver) { _sidebarObserver.disconnect(); _sidebarObserver = null; }
        if (_idleThomasEl) { _idleThomasEl.remove(); _idleThomasEl = null; }
    }

    function _startIdleSpeech() {
        // Say something random every 15-40 seconds
        function speak() {
            if (!_idleThomasEl) return;
            const bubble = _idleThomasEl.querySelector('.te-idle-speech');
            if (!bubble) return;
            const line = THOMAS_IDLE_LINES[Math.floor(Math.random() * THOMAS_IDLE_LINES.length)];
            bubble.textContent = line;
            bubble.classList.add('visible');
            // Hide after 4-6 seconds
            setTimeout(() => {
                if (bubble) bubble.classList.remove('visible');
            }, 4000 + Math.random() * 2000);
            _idleSpeechTimer = setTimeout(speak, (15 + Math.random() * 25) * 1000);
        }
        // First line after 5-10 seconds
        _idleSpeechTimer = setTimeout(speak, (5 + Math.random() * 5) * 1000);
    }

    // ── Ambient floating bots — small robots that drift across the space ──
    const AMBIENT_BOT_NAMES = [
        'Scout', 'Pixel', 'Drift', 'Echo', 'Spark', 'Nova', 'Byte', 'Glow',
        'Orbit', 'Pulse', 'Comet', 'Flick', 'Haze', 'Ripple', 'Blink',
    ];
    const AMBIENT_BOT_COLORS = [
        { primary: '#a0d4a0', secondary: '#6bae6b' },   // green
        { primary: '#e8b8e8', secondary: '#c080c0' },   // pink
        { primary: '#f0d080', secondary: '#d0a848' },   // gold
        { primary: '#b0c8e8', secondary: '#7898c0' },   // steel blue
        { primary: '#e0a890', secondary: '#c07860' },   // copper
        { primary: '#c8e0b8', secondary: '#90b870' },   // lime
        { primary: '#d0b8e8', secondary: '#a080c8' },   // lavender
    ];
    let _ambientBots = [];
    let _ambientSpawnTimer = null;
    const MAX_AMBIENT_BOTS = 3;

    function _spawnAmbientBot() {
        if (_ambientBots.length >= MAX_AMBIENT_BOTS) return;
        const palette = AMBIENT_BOT_COLORS[Math.floor(Math.random() * AMBIENT_BOT_COLORS.length)];
        const name = AMBIENT_BOT_NAMES[Math.floor(Math.random() * AMBIENT_BOT_NAMES.length)];

        const el = document.createElement('div');
        el.className = 'te-ambient-bot';
        el.innerHTML =
            '<div class="te-floater-bot" style="--bot-primary:' + palette.primary + ';--bot-secondary:' + palette.secondary + '">' +
                '<div class="te-floater-visual">' +
                    '<div class="te-floater-head"><div class="te-floater-eye left"></div><div class="te-floater-eye right"></div></div>' +
                    '<div class="te-floater-body"></div>' +
                    '<div class="te-floater-leg left"></div><div class="te-floater-leg right"></div>' +
                '</div>' +
                '<span class="te-floater-name">' + name + '</span>' +
            '</div>';

        // Random flight path: pick a start edge and end edge
        var vh = window.innerHeight;
        var vw = window.innerWidth;
        var goRight = Math.random() > 0.5;
        var startX = goRight ? -80 : vw + 80;
        var endX   = goRight ? vw + 80 : -80;
        var startY = 60 + Math.random() * (vh * 0.5);
        var endY   = 60 + Math.random() * (vh * 0.5);
        var duration = 25 + Math.random() * 35; // 25-60 seconds to cross

        el.style.left = startX + 'px';
        el.style.top = startY + 'px';
        el.style.transition = 'left ' + duration + 's linear, top ' + duration + 's ease-in-out, opacity 1s ease';

        // Flip direction if going left
        var visual = el.querySelector('.te-floater-visual');
        if (!goRight && visual) visual.style.transform = 'scaleX(-1)';

        document.body.appendChild(el);
        _ambientBots.push(el);

        // Force reflow so browser commits the start position before we animate
        void el.offsetWidth;
        el.classList.add('visible');
        // Use another reflow + rAF to ensure the transition starts from the committed position
        void el.offsetWidth;
        requestAnimationFrame(function() {
            el.style.left = endX + 'px';
            el.style.top = endY + 'px';
        });

        // Remove after flight completes
        setTimeout(function() {
            el.classList.remove('visible');
            setTimeout(function() {
                el.remove();
                var idx = _ambientBots.indexOf(el);
                if (idx !== -1) _ambientBots.splice(idx, 1);
            }, 1200);
        }, duration * 1000);
    }

    function _startAmbientBots() {
        // Spawn first after a delay, then periodically
        function scheduleNext() {
            _ambientSpawnTimer = setTimeout(function() {
                _spawnAmbientBot();
                scheduleNext();
            }, (12 + Math.random() * 25) * 1000); // every 12-37 seconds
        }
        // First bot after 8-15 seconds
        _ambientSpawnTimer = setTimeout(function() {
            _spawnAmbientBot();
            scheduleNext();
        }, (8 + Math.random() * 7) * 1000);
    }

    function _stopAmbientBots() {
        if (_ambientSpawnTimer) { clearTimeout(_ambientSpawnTimer); _ambientSpawnTimer = null; }
        _ambientBots.forEach(function(el) { el.remove(); });
        _ambientBots = [];
    }

    function floaterStart() {
        _createIdleThomas();
        _startScreensaverWatch();
        _startAmbientBots();
    }

    function floaterStop() {
        if (_floaterTimer) { clearTimeout(_floaterTimer); _floaterTimer = null; }
        _stopScreensaverWatch();
        _removeIdleThomas();
        _stopAmbientBots();
        const existing = document.querySelectorAll('.te-floater');
        existing.forEach(el => el.remove());
    }

    // ── Screensaver / idle mode ──────────────────────────────────
    let _idleTimeout = null;
    const _idleEvents = ['mousemove', 'mousedown', 'keydown', 'touchstart', 'scroll'];

    function _startScreensaverWatch() {
        _resetIdleTimer();
        _idleEvents.forEach(e => document.addEventListener(e, _onUserActivity, { passive: true }));
    }

    function _stopScreensaverWatch() {
        _idleEvents.forEach(e => document.removeEventListener(e, _onUserActivity));
        if (_idleTimeout) { clearTimeout(_idleTimeout); _idleTimeout = null; }
        _exitScreensaver();
    }

    function _onUserActivity() {
        if (_screensaverActive) _exitScreensaver();
        _resetIdleTimer();
    }

    function _resetIdleTimer() {
        if (_idleTimeout) clearTimeout(_idleTimeout);
        _idleTimeout = setTimeout(_enterScreensaver, SCREENSAVER_IDLE_MS);
    }

    function _enterScreensaver() {
        if (_screensaverActive) return;
        _screensaverActive = true;
        document.body.classList.remove('te-screensaver-exit');
        document.body.classList.add('te-screensaver-active');
    }

    function _exitScreensaver() {
        if (!_screensaverActive) return;
        _screensaverActive = false;
        document.body.classList.remove('te-screensaver-active');
        document.body.classList.add('te-screensaver-exit');
        setTimeout(() => document.body.classList.remove('te-screensaver-exit'), 1000);
    }

    // ── mount ────────────────────────────────────────────────────
    // Note: The space background is managed by the module background system
    // (window.__moduleBackgrounds['token_economy']) which calls injectSpaceBg/
    // removeSpaceBg on enter/leave. This keeps the bg lifecycle decoupled
    // from the widget mount/unmount.
    function mount(container) {
        _s.el = container;
        container.innerHTML = shell();
        bind();
        _s.mounted = true;
        refresh({ force: true });
        sseOn();
        tickStart();
    }
    function unmount() {
        sseOff();
        tickStop();
        _s.mounted = false;
        _s.el = null;
    }

    // ── tick (running clock + subtle animation) ──────────────────
    function tickStart() {
        function tick() {
            const clock = $('[data-te-clock]', _s.el);
            if (clock) clock.textContent = nowHHMMSS();
            _s.tickFrame = requestAnimationFrame(tick);
        }
        tick();
    }
    function tickStop() {
        if (_s.tickFrame) cancelAnimationFrame(_s.tickFrame);
        _s.tickFrame = null;
    }

    function shell() {
        return `
<div class="te-v3">
    <!-- Space bg is injected on document.body as #te-space-root -->

    <!-- ▸ TOP BAR: status line -->
    <div class="te-topbar">
        <span class="te-topbar-left">
            <span class="te-sigil"></span>
            <span class="te-topbar-title">TOKEN ECONOMY</span>
            <span class="te-topbar-dim" data-te-topmode></span>
        </span>
        <span class="te-topbar-right">
            <select class="te-range-sel" data-te-period aria-label="History window">
                <option value="7">7 DAY</option>
                <option value="14">14 DAY</option>
                <option value="30">30 DAY</option>
                <option value="90">90 DAY</option>
            </select>
            <button class="te-topbar-btn" data-te-refresh title="Refresh">↻</button>
            <button class="te-topbar-btn" data-te-export title="Export CSV">⤓</button>
            <span class="te-topbar-clock" data-te-clock>${nowHHMMSS()}</span>
            <span class="te-topbar-live"><span class="te-dot"></span>LIVE</span>
        </span>
    </div>

    <!-- ▸ HERO: the big number IS the design -->
    <div class="te-hero" data-te-hero>
        <div class="te-hero-cost">
            <span class="te-hero-dollar" data-te-hdollar>$</span><span class="te-hero-whole" data-te-hwhole>0</span><span class="te-hero-frac" data-te-hfrac>.00</span>
        </div>
        <div class="te-hero-sub">
            <span data-te-hcalls>0</span> calls
            <span class="te-hero-pipe">│</span>
            <span data-te-htokens>0</span> tokens
            <span class="te-hero-pipe">│</span>
            today
        </div>
        <div class="te-burnstrip" data-te-burnstrip>
            <div class="te-burnstrip-fill" data-te-burnfill></div>
            <div class="te-burnstrip-marker" data-te-burnmark></div>
        </div>
    </div>

    <!-- ▸ DATA STRIP: asymmetric stats -->
    <div class="te-datastrip" data-te-datastrip></div>

    <!-- ▸ MAIN AREA -->
    <div class="te-main">
        <!-- LEFT: History spectrum + Terminal feed -->
        <div class="te-col-left">
            <div class="te-panel te-panel-grow">
                <div class="te-panel-head">
                    <span>SPEND HISTORY</span>
                    <span class="te-panel-sub" data-te-htotal></span>
                </div>
                <div class="te-spectrum" data-te-spectrum></div>
            </div>
            <div class="te-panel">
                <div class="te-panel-head">
                    <span><span class="te-dot"></span> TERMINAL</span>
                    <span class="te-panel-sub" data-te-fcount>awaiting</span>
                </div>
                <div class="te-terminal" data-te-terminal>
                    <div class="te-term-line te-term-sys">system ready. streaming spend events...</div>
                </div>
            </div>
        </div>

        <!-- RIGHT: Mode switch + Models + Rates -->
        <div class="te-col-right">
            <div class="te-panel">
                <div class="te-panel-head">
                    <span>ECONOMY MODE</span>
                    <span class="te-panel-sub" data-te-modelabel></span>
                </div>
                <div class="te-switch-track" data-te-modes></div>
                <div class="te-mode-readout" data-te-modereadout></div>
                <div class="te-context-meter" data-te-ctxmeter>
                    <div class="te-ctx-label">
                        <span>CONTEXT BUDGET</span>
                        <span data-te-ctxval></span>
                    </div>
                    <div class="te-ctx-track"><div class="te-ctx-fill" data-te-ctxfill></div></div>
                </div>
            </div>
            <div class="te-panel">
                <div class="te-panel-head">
                    <span>MODEL MIX</span>
                    <span class="te-panel-sub te-modelscope" data-te-mtitle>
                        <button class="te-modelscope-btn active" data-te-modelscope="session" type="button">session</button>
                        <button class="te-modelscope-btn" data-te-modelscope="today" type="button">today</button>
                    </span>
                </div>
                <div data-te-modelviz></div>
                <div data-te-modeltable></div>
            </div>
            <div class="te-panel">
                <div class="te-panel-head"><span>RATE CARD</span></div>
                <div data-te-pricing></div>
            </div>
        </div>
    </div>
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
    }

    function paintTopMode() {
        const el = $('[data-te-topmode]', _s.el);
        if (!el) return;
        const active = MODE_SPECS[_s.economy] || MODE_SPECS.optimal;
        el.textContent = active.mul + ' ' + active.name.toUpperCase();
    }

    function paintHero() {
        const whole = $('[data-te-hwhole]', _s.el);
        const frac = $('[data-te-hfrac]', _s.el);
        const calls = $('[data-te-hcalls]', _s.el);
        const tokens = $('[data-te-htokens]', _s.el);
        const hero = $('[data-te-hero]', _s.el);
        const burnfill = $('[data-te-burnfill]', _s.el);
        const burnmark = $('[data-te-burnmark]', _s.el);
        if (!whole) return;

        const t = _s.today || {};
        const total = +t.total_usd || 0;
        const numCalls = +t.call_count || 0;
        const toks = t.tokens || {};
        const p = usdParts(total);

        whole.textContent = p.whole.replace('$', '');
        frac.textContent = p.frac;
        if (calls) calls.textContent = numCalls;
        if (tokens) tokens.textContent = tok(+toks.total || 0);

        // Tone class
        if (hero) {
            const tone = total > 20 ? 'te-tone-hot' : total > 5 ? 'te-tone-warm' : total > 0 ? 'te-tone-active' : 'te-tone-idle';
            hero.className = 'te-hero ' + tone;
        }

        // Burn strip: how far through a daily budget estimate
        if (burnfill) {
            const dailyEst = { cheap: 5, optimal: 20, max: 50 };
            const est = dailyEst[_s.economy] || 20;
            const w = Math.min(100, (total / est) * 100);
            burnfill.style.width = w + '%';
        }

        // Hour-of-day marker (how far through the day we are)
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
        const numCalls = +t.call_count || 0;
        const avgCost = numCalls > 0 ? (+t.total_usd || 0) / numCalls : 0;

        const hist = _s.history || [];
        const yesterday = hist.length >= 2 ? +hist[hist.length - 2]?.usd || 0 : 0;
        const todayUsd = +t.total_usd || 0;
        let deltaHtml = '';
        if (yesterday > 0 && todayUsd > 0) {
            const pctChange = ((todayUsd - yesterday) / yesterday) * 100;
            const cls = pctChange > 5 ? 'te-delta-up' : pctChange < -5 ? 'te-delta-down' : 'te-delta-flat';
            const sign = pctChange > 0 ? '+' : '';
            deltaHtml = `<span class="te-ds-delta ${cls}">${sign}${Math.round(pctChange)}%</span>`;
        }

        el.innerHTML = `
            <div class="te-ds-cell te-ds-wide">
                <span class="te-ds-num">${esc(usd(+s.total_usd || 0))}</span>
                <span class="te-ds-label">SESSION</span>
                <span class="te-ds-note">${+s.call_count || 0} calls</span>
            </div>
            <div class="te-ds-cell">
                <span class="te-ds-num">${esc(tok(+toks.prompt || 0))}</span>
                <span class="te-ds-label">TOKENS IN</span>
            </div>
            <div class="te-ds-cell">
                <span class="te-ds-num">${esc(tok(+toks.completion || 0))}</span>
                <span class="te-ds-label">TOKENS OUT</span>
            </div>
            <div class="te-ds-cell">
                <span class="te-ds-num">${esc(usd(avgCost))}</span>
                <span class="te-ds-label">AVG/CALL</span>
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
                return `<button class="te-switch-opt${active ? ' active' : ''}" data-mode="${id}">` +
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
        const titleEl = $('[data-te-mtitle]', _s.el);
        if (!tableEl) return;

        const scope = _s.modelScope === 'today' ? 'today' : 'session';
        const source = scope === 'today' ? _s.today : _s.session;
        const rows = modelBreakdown(source?.by_model_detail);

        if (titleEl) {
            titleEl.innerHTML =
                `<button class="te-modelscope-btn${scope === 'session' ? ' active' : ''}" data-te-modelscope="session" type="button">session</button>` +
                `<button class="te-modelscope-btn${scope === 'today' ? ' active' : ''}" data-te-modelscope="today" type="button">today</button>`;
        }

        if (!rows.length) {
            if (vizEl) vizEl.innerHTML = '<div class="te-idle-viz"><span class="te-idle-pulse"></span></div>';
            tableEl.innerHTML = `<div class="te-empty-state">no model usage ${esc(scope)}</div>`;
            return;
        }

        const sum = rows.reduce((a, r) => ({ usd: a.usd + r.usd, calls: a.calls + r.calls, total: a.total + r.total }), { usd: 0, calls: 0, total: 0 });

        // Proportion bars instead of treemap
        if (vizEl) {
            vizEl.innerHTML = rows.map((r, i) => {
                const w = sum.usd > 0 ? Math.max(4, (r.usd / sum.usd) * 100) : 100 / rows.length;
                const color = MODEL_COLORS[i % MODEL_COLORS.length];
                return `<div class="te-mprop"><div class="te-mprop-bar" style="width:${w}%;background:${color}"></div><span class="te-mprop-name">${esc(shortModel(r.n))}</span><span class="te-mprop-val">${esc(usd(r.usd))}</span></div>`;
            }).join('');
        }

        // Compact table
        tableEl.innerHTML = `<table class="te-mtbl"><tbody>` +
            rows.map((r, i) => {
                const color = MODEL_COLORS[i % MODEL_COLORS.length];
                return `<tr><td><span class="te-mdot" style="background:${color}"></span>${esc(shortModel(r.n))}</td><td>${esc(usd(r.usd))}</td><td>${r.calls}</td><td>${esc(tok(r.total))}</td></tr>`;
            }).join('') +
            `<tr class="te-mtbl-total"><td>TOTAL</td><td>${esc(usd(sum.usd))}</td><td>${sum.calls}</td><td>${esc(tok(sum.total))}</td></tr></tbody></table>`;
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

        const max = Math.max(...rows.map(r => +r.usd || 0), 0.01);
        const sum = rows.reduce((a, r) => a + (+r.usd || 0), 0);
        const todayDate = new Date().toISOString().split('T')[0];
        if (tot) tot.textContent = usd(sum) + ' / ' + rows.length + 'd';

        // Vertical spectrum bars (bottom-up like an equalizer)
        el.innerHTML = `<div class="te-spec-grid">${rows.map(r => {
            const v = +r.usd || 0;
            const h = Math.max(2, Math.round(pct(v, max)));
            const isToday = r.date === todayDate;
            const tone = v > 20 ? ' te-spec-hot' : v > 5 ? ' te-spec-warm' : '';
            return `<div class="te-spec-col${isToday ? ' te-spec-today' : ''}">` +
                `<div class="te-spec-bar${tone}" style="height:${h}%"></div>` +
                `<span class="te-spec-date">${shortDate(r.date).split('/')[1] || ''}</span>` +
                `<span class="te-spec-amt">${v >= 1 ? '$' + v.toFixed(0) : v > 0 ? usd(v) : ''}</span>` +
                `</div>`;
        }).join('')}</div>`;
    }

    function paintPricing() {
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

    function pushFeed(d) {
        const ev = {
            ts: d.ts || new Date().toISOString(),
            model: d.model || '?',
            tokens: (+d.prompt_tokens || 0) + (+d.completion_tokens || 0),
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
            const costClass = ev.usd > 0.10 ? ' te-term-red' : ev.usd > 0.02 ? ' te-term-amber' : '';
            return `<div class="te-term-line${i === 0 ? ' te-term-new' : ''}">` +
                `<span class="te-term-ts">${esc(t)}</span> ` +
                `<span class="te-term-model">${esc(shortModel(ev.model))}</span> ` +
                `<span class="te-term-tok">${esc(tok(ev.tokens))}tok</span> ` +
                `<span class="te-term-cost${costClass}">${esc(usd(ev.usd))}</span>` +
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

        root.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-te-modelscope]');
            if (!btn) return;
            const scope = btn.dataset.teModelscope;
            if (!scope || scope === _s.modelScope) return;
            _s.modelScope = scope;
            paintModels();
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

    // Register page background through the module background system.
    // Space bg is now global (injected at page load), so mount is kept
    // for compat but removeSpaceBg is a no-op to prevent teardown.
    window.__moduleBackgrounds = window.__moduleBackgrounds || {};
    window.__moduleBackgrounds['token_economy'] = {
        mount: injectSpaceBg,
        unmount: removeSpaceBg,
    };

    window.__tokenEconomy = { mount, unmount, refresh, getState: () => ({ ..._s }) };
})();
