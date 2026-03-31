/**
 * token_economy.js — Token Economy workspace panel v3
 *
 * Design: Bloomberg Terminal × spacecraft instruments.
 * No circular gauges, no uniform card grids, no AI slop.
 * Typography IS the design. Numbers dominate. Data is dense.
 *
 * Hooks into the module system via window.__tokenEconomy.
 * Consumes /api/spend/* endpoints + SSE for live updates.
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
        period: 7,
        economy: '',
        autonomy: 3,
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
                        if (typeof d.today_usd === 'number') _s.today.total_usd = d.today_usd;
                        if (d.today_tokens) _s.today.tokens = d.today_tokens;
                        if (typeof d.today_calls === 'number') _s.today.call_count = d.today_calls;
                        if (d.model && typeof d.usd_total === 'number') {
                            if (!_s.today.by_model_detail) _s.today.by_model_detail = {};
                            const x = _s.today.by_model_detail[d.model] || { usd: 0, calls: 0, tokens: { prompt: 0, completion: 0, total: 0 } };
                            x.usd = (x.usd || 0) + d.usd_total;
                            x.calls = (x.calls || 0) + 1;
                            x.tokens.prompt = (x.tokens?.prompt || 0) + (d.prompt_tokens || 0);
                            x.tokens.completion = (x.tokens?.completion || 0) + (d.completion_tokens || 0);
                            x.tokens.total = x.tokens.prompt + x.tokens.completion;
                            _s.today.by_model_detail[d.model] = x;
                        }
                    }
                    paintHero();
                    paintDataStrip();
                    paintModels();
                    pushFeed(d);
                } catch { /* ignore */ }
            });
            es.onerror = () => { es.close(); _s.sse = null; setTimeout(sseOn, 8000); };
        } catch { /* unsupported */ }
    }
    function sseOff() { if (_s.sse) { _s.sse.close(); _s.sse = null; } }

    // ── Animated starfield canvas ──────────────────────────────
    let _starfieldRAF = null;
    let _starfieldCanvas = null;
    let _stars = [];

    function initStarfield(canvas) {
        _starfieldCanvas = canvas;
        const w = canvas.width;
        const h = canvas.height;

        // 3 parallax layers spread evenly across the viewport
        // Far: 400 tiny stars, very dim, very slow drift
        // Mid: 150 medium stars, moderate, slow drift
        // Near: 50 bright stars, bright, slow drift
        const layerConfigs = [
            { count: 400, drift: 0.003, baseSize: 0.5, baseAlpha: 0.25, twinkleMin: 0.05, twinkleMax: 0.2 },
            { count: 150, drift: 0.008, baseSize: 1.0, baseAlpha: 0.45, twinkleMin: 0.08, twinkleMax: 0.25 },
            { count: 50,  drift: 0.015, baseSize: 2.0, baseAlpha: 0.7,  twinkleMin: 0.1,  twinkleMax: 0.3 },
        ];

        _stars = [];
        layerConfigs.forEach((cfg, layerIdx) => {
            for (let i = 0; i < cfg.count; i++) {
                // Spread stars evenly across entire viewport, not clustered at center
                const x = Math.random() * w;
                const y = Math.random() * h;
                _stars.push({
                    x,
                    y,
                    size: cfg.baseSize * (0.7 + Math.random() * 0.6),
                    baseAlpha: cfg.baseAlpha * (0.6 + Math.random() * 0.4),
                    twinkleSpeed: cfg.twinkleMin + Math.random() * (cfg.twinkleMax - cfg.twinkleMin),
                    twinklePhase: Math.random() * Math.PI * 2,
                    drift: cfg.drift,
                    layer: layerIdx,
                });
            }
        });

        animateStarfield();
    }

    function animateStarfield() {
        if (!_starfieldCanvas) return;
        const ctx = _starfieldCanvas.getContext('2d');
        const w = _starfieldCanvas.width;
        const h = _starfieldCanvas.height;
        let time = 0;

        function frame() {
            time += 0.016; // ~60fps
            ctx.fillStyle = 'rgba(0,0,0,0)';
            ctx.clearRect(0, 0, w, h);

            _stars.forEach((star) => {
                // Gentle lateral drift: all stars drift slowly left and slightly up (like moving forward + right)
                star.x -= star.drift;
                star.y -= star.drift * 0.4;

                // Recycle: when a star drifts off left edge, respawn on right edge at random Y
                if (star.x < -10) {
                    star.x = w + 10;
                    star.y = Math.random() * h;
                }
                // When drifts off top, respawn at bottom
                if (star.y < -10) {
                    star.y = h + 10;
                    star.x = Math.random() * w;
                }

                // Twinkle: MUCH slower and gentler. Only varies 30% in brightness
                const twinkle = 0.7 + 0.3 * Math.sin(time * star.twinkleSpeed + star.twinklePhase);
                const alpha = star.baseAlpha * twinkle;

                // Draw star
                ctx.globalAlpha = alpha;
                ctx.fillStyle = '#ffffff';
                ctx.beginPath();
                ctx.arc(star.x, star.y, star.size * 0.5, 0, Math.PI * 2);
                ctx.fill();

                // Glow for bigger stars
                if (star.size > 1.5) {
                    ctx.globalAlpha = alpha * 0.3;
                    ctx.beginPath();
                    ctx.arc(star.x, star.y, star.size * 1.2, 0, Math.PI * 2);
                    ctx.fill();
                }

                // 4-point diffraction spike for big stars
                if (star.size > 2) {
                    ctx.globalAlpha = alpha * 0.15;
                    ctx.strokeStyle = '#ffffff';
                    ctx.lineWidth = 0.5;
                    const spikeLong = star.size * 1.5;
                    const spikeShort = star.size * 0.5;
                    ctx.beginPath();
                    ctx.moveTo(star.x - spikeLong, star.y); ctx.lineTo(star.x + spikeLong, star.y);
                    ctx.moveTo(star.x, star.y - spikeShort); ctx.lineTo(star.x, star.y + spikeShort);
                    ctx.stroke();
                }
            });

            ctx.globalAlpha = 1;
            _starfieldRAF = requestAnimationFrame(frame);
        }

        frame();
    }

    // ── Galaxy renderer ────────────────────────────────────────
    let _galaxyRAF = null;
    let _galaxyCanvas = null;
    let _galaxies = [];

    function renderGalaxies(canvas) {
        _galaxyCanvas = canvas;
        const w = canvas.width;
        const h = canvas.height;

        _galaxies = [];
        const galaxyCount = 5 + Math.floor(Math.random() * 4);
        const galaxyTypes = ['spiral', 'elliptical', 'barred'];

        for (let i = 0; i < galaxyCount; i++) {
            const type = galaxyTypes[Math.floor(Math.random() * galaxyTypes.length)];
            const size = 40 + Math.random() * 50; // Bigger galaxies (40-90px)
            const x = Math.random() * w;
            const y = Math.random() * h;
            const rotation = Math.random() * Math.PI * 2;
            const armTightness = 0.5 + Math.random() * 1.5; // Vary spiral tightness

            _galaxies.push({
                type, size, x, y, rotation, armTightness,
                pulsePhase: Math.random() * Math.PI * 2,
                pulseSpeed: 0.1 + Math.random() * 0.3, // Much slower pulse
            });
        }

        animateGalaxies();
    }

    function animateGalaxies() {
        if (!_galaxyCanvas) return;
        const ctx = _galaxyCanvas.getContext('2d');
        const w = _galaxyCanvas.width;
        const h = _galaxyCanvas.height;
        let time = 0;

        function frame() {
            time += 0.016;
            ctx.fillStyle = 'rgba(0,0,0,0)';
            ctx.clearRect(0, 0, w, h);

            _galaxies.forEach(gal => {
                const pulseAlpha = 0.3 + 0.2 * Math.sin(time * gal.pulseSpeed + gal.pulsePhase);
                ctx.save();
                ctx.translate(gal.x, gal.y);
                ctx.rotate(gal.rotation);

                if (gal.type === 'spiral') {
                    drawSpiralGalaxy(ctx, gal.size, pulseAlpha, gal.armTightness);
                } else if (gal.type === 'elliptical') {
                    drawEllipticalGalaxy(ctx, gal.size, pulseAlpha);
                } else if (gal.type === 'barred') {
                    drawBarredSpiralGalaxy(ctx, gal.size, pulseAlpha, gal.armTightness);
                }

                ctx.restore();
            });

            _galaxyRAF = requestAnimationFrame(frame);
        }

        frame();
    }

    function drawSpiralGalaxy(ctx, size, alpha, armTightness) {
        // Background halo: very faint, large
        ctx.globalAlpha = alpha * 0.08;
        ctx.fillStyle = 'rgba(200, 180, 255, 1)';
        ctx.beginPath();
        ctx.arc(0, 0, size * 0.5, 0, Math.PI * 2);
        ctx.fill();

        // Core: warm yellowish-white with soft radial gradient
        const coreGradient = ctx.createRadialGradient(0, 0, 0, 0, 0, size * 0.15);
        coreGradient.addColorStop(0, 'rgba(255, 235, 180, ' + (alpha * 0.9) + ')');
        coreGradient.addColorStop(0.5, 'rgba(240, 210, 150, ' + (alpha * 0.5) + ')');
        coreGradient.addColorStop(1, 'rgba(200, 180, 255, ' + (alpha * 0.1) + ')');
        ctx.fillStyle = coreGradient;
        ctx.beginPath();
        ctx.arc(0, 0, size * 0.15, 0, Math.PI * 2);
        ctx.fill();

        // Spiral arms: 2 arms with 200+ points each, high scatter, small stars
        const armCount = 2;
        const pointsPerArm = 250;
        for (let arm = 0; arm < armCount; arm++) {
            for (let p = 0; p < pointsPerArm; p++) {
                const t = p / pointsPerArm; // 0 to 1 along the arm
                const baseAngle = (arm * Math.PI) + (t * Math.PI * 2.5 * armTightness); // Logarithmic spiral
                const baseR = t * size * 0.4;

                // Gaussian scatter perpendicular to arm
                const scatterStdDev = size * 0.04;
                const perpAngle = baseAngle + Math.PI / 2;
                const scatterDist = (Math.random() + Math.random() - 1) * scatterStdDev; // Box-Muller simplified
                const scatterX = Math.cos(perpAngle) * scatterDist;
                const scatterY = Math.sin(perpAngle) * scatterDist;

                const x = Math.cos(baseAngle) * baseR + scatterX;
                const y = Math.sin(baseAngle) * baseR + scatterY;

                // Color gradient: warm white near core, cool blue at edges
                const colorT = t;
                const r = 255 - (colorT * 50);
                const g = 235 - (colorT * 60);
                const b = 180 + (colorT * 40);

                // Alpha decreases with distance from core
                const pointAlpha = alpha * (1 - t * 0.7) * 0.6;
                ctx.globalAlpha = pointAlpha;
                ctx.fillStyle = 'rgba(' + Math.floor(r) + ',' + Math.floor(g) + ',' + Math.floor(b) + ', 1)';
                ctx.beginPath();
                ctx.arc(x, y, 0.3 + Math.random() * 0.4, 0, Math.PI * 2);
                ctx.fill();
            }
        }

        // HII regions: bright spots along arms
        for (let arm = 0; arm < armCount; arm++) {
            const hiiCount = 2 + Math.floor(Math.random() * 2);
            for (let i = 0; i < hiiCount; i++) {
                const t = 0.3 + Math.random() * 0.6;
                const baseAngle = (arm * Math.PI) + (t * Math.PI * 2.5 * armTightness);
                const baseR = t * size * 0.4;
                const x = Math.cos(baseAngle) * baseR;
                const y = Math.sin(baseAngle) * baseR;

                ctx.globalAlpha = alpha * (0.4 + Math.random() * 0.3);
                ctx.fillStyle = 'rgba(255, 150, 100, 1)';
                ctx.beginPath();
                ctx.arc(x, y, 1 + Math.random() * 1.5, 0, Math.PI * 2);
                ctx.fill();
            }
        }

        // Dust lanes: dark semi-transparent dots between arms
        const dustCount = 80;
        for (let i = 0; i < dustCount; i++) {
            const angle = Math.random() * Math.PI * 2;
            const r = Math.random() * size * 0.35;
            const x = Math.cos(angle) * r;
            const y = Math.sin(angle) * r;

            ctx.globalAlpha = alpha * 0.15;
            ctx.fillStyle = 'rgba(0, 0, 0, 1)';
            ctx.beginPath();
            ctx.arc(x, y, 0.5 + Math.random() * 1.5, 0, Math.PI * 2);
            ctx.fill();
        }
    }

    function drawEllipticalGalaxy(ctx, size, alpha) {
        // Dense gaussian blob of 200+ points
        // Color gradient: golden-yellow core to pale white edges
        const pointCount = 200;
        const aspectRatio = 0.6 + Math.random() * 0.3; // 0.6 to 0.9

        for (let i = 0; i < pointCount; i++) {
            const angle = Math.random() * Math.PI * 2;
            const r = Math.sqrt(Math.random()) * size * 0.3;
            const x = Math.cos(angle) * r;
            const y = Math.sin(angle) * r * aspectRatio;

            // Smooth radial falloff
            const dist = Math.sqrt(x * x + y * y) / (size * 0.3);
            const pointAlpha = alpha * Math.max(0, 1 - dist * dist);

            // Color: golden-yellow to pale white
            const colorT = dist;
            const r_val = 255 - (colorT * 30);
            const g_val = 220 - (colorT * 50);
            const b_val = 180 + (colorT * 20);

            ctx.globalAlpha = pointAlpha * 0.7;
            ctx.fillStyle = 'rgba(' + Math.floor(r_val) + ',' + Math.floor(g_val) + ',' + Math.floor(b_val) + ', 1)';
            ctx.beginPath();
            ctx.arc(x, y, 0.4 + Math.random() * 0.5, 0, Math.PI * 2);
            ctx.fill();
        }

        // Core: bright yellowish region
        const coreGradient = ctx.createRadialGradient(0, 0, 0, 0, 0, size * 0.12);
        coreGradient.addColorStop(0, 'rgba(255, 230, 150, ' + (alpha * 0.8) + ')');
        coreGradient.addColorStop(1, 'rgba(230, 190, 100, ' + (alpha * 0.2) + ')');
        ctx.fillStyle = coreGradient;
        ctx.beginPath();
        ctx.arc(0, 0, size * 0.12, 0, Math.PI * 2);
        ctx.fill();
    }

    function drawBarredSpiralGalaxy(ctx, size, alpha, armTightness) {
        // Background halo
        ctx.globalAlpha = alpha * 0.08;
        ctx.fillStyle = 'rgba(200, 180, 255, 1)';
        ctx.beginPath();
        ctx.arc(0, 0, size * 0.5, 0, Math.PI * 2);
        ctx.fill();

        // Central bright bar: elongated cluster of warm-white points
        const barLength = size * 0.35;
        const barWidth = size * 0.08;
        const barPointCount = 120;

        for (let i = 0; i < barPointCount; i++) {
            const t = (i / barPointCount) * 2 - 1; // -1 to 1
            const x = t * barLength * 0.5;
            const perturbY = (Math.random() - 0.5) * barWidth;
            const y = perturbY;

            const barAlpha = alpha * (0.7 - Math.abs(t) * 0.2) * 0.8;
            ctx.globalAlpha = barAlpha;
            ctx.fillStyle = 'rgba(255, 240, 180, 1)';
            ctx.beginPath();
            ctx.arc(x, y, 0.4 + Math.random() * 0.6, 0, Math.PI * 2);
            ctx.fill();
        }

        // Spiral arms from bar ends
        const armCount = 2;
        const pointsPerArm = 200;

        for (let arm = 0; arm < armCount; arm++) {
            const startAngle = (arm * Math.PI); // Arms start from bar ends
            for (let p = 0; p < pointsPerArm; p++) {
                const t = p / pointsPerArm;
                const baseAngle = startAngle + (t * Math.PI * 2 * armTightness);
                const baseR = (barLength * 0.5) + (t * size * 0.3);

                // Scatter perpendicular to arm
                const scatterStdDev = size * 0.04;
                const perpAngle = baseAngle + Math.PI / 2;
                const scatterDist = (Math.random() + Math.random() - 1) * scatterStdDev;
                const scatterX = Math.cos(perpAngle) * scatterDist;
                const scatterY = Math.sin(perpAngle) * scatterDist;

                const x = Math.cos(baseAngle) * baseR + scatterX;
                const y = Math.sin(baseAngle) * baseR + scatterY;

                // Color gradient
                const colorT = t;
                const r = 255 - (colorT * 40);
                const g = 240 - (colorT * 50);
                const b = 180 + (colorT * 30);

                const pointAlpha = alpha * (1 - t * 0.6) * 0.6;
                ctx.globalAlpha = pointAlpha;
                ctx.fillStyle = 'rgba(' + Math.floor(r) + ',' + Math.floor(g) + ',' + Math.floor(b) + ', 1)';
                ctx.beginPath();
                ctx.arc(x, y, 0.3 + Math.random() * 0.4, 0, Math.PI * 2);
                ctx.fill();
            }
        }
    }

    // ── Procedural nebula canvas — organic noise-based gas clouds ──
    function paintNebulaCanvas(canvas) {
        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const h = canvas.height;

        // Simple value noise for organic shapes
        function noise(x, y, seed) {
            const n = Math.sin(x * 12.9898 + y * 78.233 + seed) * 43758.5453;
            return n - Math.floor(n);
        }

        function smoothNoise(x, y, seed) {
            const ix = Math.floor(x), iy = Math.floor(y);
            const fx = x - ix, fy = y - iy;
            const sx = fx * fx * (3 - 2 * fx), sy = fy * fy * (3 - 2 * fy);
            const a = noise(ix, iy, seed), b = noise(ix + 1, iy, seed);
            const c = noise(ix, iy + 1, seed), d = noise(ix + 1, iy + 1, seed);
            return a + (b - a) * sx + (c - a) * sy + (a - b - c + d) * sx * sy;
        }

        function fbm(x, y, seed, octaves) {
            let v = 0, amp = 0.5, freq = 1;
            for (let i = 0; i < octaves; i++) {
                v += amp * smoothNoise(x * freq, y * freq, seed + i * 100);
                amp *= 0.5;
                freq *= 2.1;
            }
            return v;
        }

        // Nebula color palette — blues, purples, teals, pinks, golds, cyans
        const palette = [
            [20, 40, 120],   // deep blue
            [80, 25, 130],   // purple
            [15, 70, 100],   // teal
            [130, 40, 90],   // rose
            [40, 100, 160],  // bright blue
            [60, 20, 100],   // dark purple
            [180, 120, 40],  // amber/gold
            [40, 180, 200],  // cyan
        ];

        const imgData = ctx.createImageData(w, h);
        const d = imgData.data;
        const scaleX = 5 / w, scaleY = 5 / h;

        // Single pass: render with HIGHER octaves (6 instead of 5) for smoother noise
        for (let py = 0; py < h; py++) {
            for (let px = 0; px < w; px++) {
                const idx = (py * w + px) * 4;
                const nx = px * scaleX, ny = py * scaleY;

                // Multiple noise layers for different color channels (higher octaves = smoother)
                const n1 = fbm(nx, ny, 0, 6);
                const n2 = fbm(nx + 10, ny + 10, 50, 6);
                const n3 = fbm(nx + 20, ny - 5, 100, 5);

                // Pick colors based on noise values
                const ci1 = Math.floor(n1 * (palette.length - 1));
                const ci2 = Math.min(ci1 + 1, palette.length - 1);
                const t = (n1 * (palette.length - 1)) - ci1;
                const c1 = palette[ci1], c2 = palette[ci2];

                // Density — where the gas is thick vs thin
                // Softer falloff: use linear instead of quadratic to reduce hard transitions
                const density = Math.max(0, n2 * 1.2 - 0.2);
                const brightness = density * 0.6; // Cap max brightness lower for softer appearance

                const r = (c1[0] + (c2[0] - c1[0]) * t) * brightness;
                const g = (c1[1] + (c2[1] - c1[1]) * t) * brightness;
                const b = (c1[2] + (c2[2] - c1[2]) * t) * brightness;

                // Alpha based on combined noise — creates wispy edges
                const alpha = Math.min(255, brightness * n3 * 400);

                d[idx] = Math.min(255, r * 1.2);
                d[idx + 1] = Math.min(255, g * 1.1);
                d[idx + 2] = Math.min(255, b * 1.3);
                d[idx + 3] = alpha;
            }
        }
        ctx.putImageData(imgData, 0, 0);
    }

    // ── Planet renderer ────────────────────────────────────────
    let _planetCanvas = null;
    let _planets = [];

    function renderPlanets(canvas) {
        _planetCanvas = canvas;
        const w = canvas.width;
        const h = canvas.height;

        _planets = [];
        const planetCount = 2 + Math.floor(Math.random() * 3);
        const planetTypes = ['gasGiant', 'iceGiant', 'rocky'];

        for (let i = 0; i < planetCount; i++) {
            const type = planetTypes[Math.floor(Math.random() * planetTypes.length)];
            const radius = 8 + Math.random() * 22;
            let x, y;
            // Position planets away from each other
            let validPosition = false;
            while (!validPosition) {
                x = Math.random() * w;
                y = Math.random() * h;
                validPosition = true;
                // Check distance from other planets
                for (const p of _planets) {
                    const dist = Math.sqrt((p.x - x) ** 2 + (p.y - y) ** 2);
                    if (dist < (p.radius + radius) * 3) {
                        validPosition = false;
                        break;
                    }
                }
            }

            const hasRings = type === 'gasGiant' && Math.random() < 0.4;
            const rotation = Math.random() * Math.PI * 2;

            _planets.push({
                type, radius, x, y, hasRings, rotation,
                rotationSpeed: 0.001 + Math.random() * 0.003,
            });
        }

        drawPlanetsFrame(canvas.getContext('2d'));
    }

    function drawPlanetsFrame(ctx) {
        const canvas = ctx.canvas;
        const w = canvas.width;
        const h = canvas.height;

        ctx.fillStyle = 'rgba(0,0,0,0)';
        ctx.clearRect(0, 0, w, h);

        _planets.forEach(planet => {
            ctx.save();
            ctx.translate(planet.x, planet.y);
            ctx.rotate(planet.rotation);

            if (planet.type === 'gasGiant') {
                drawGasGiant(ctx, planet.radius);
            } else if (planet.type === 'iceGiant') {
                drawIceGiant(ctx, planet.radius);
            } else if (planet.type === 'rocky') {
                drawRockyPlanet(ctx, planet.radius);
            }

            if (planet.hasRings) {
                drawRings(ctx, planet.radius);
            }

            ctx.restore();

            // Update rotation
            planet.rotation += planet.rotationSpeed;
        });
    }

    function drawGasGiant(ctx, radius) {
        // Gradient from warm colors to darker tones
        const gradient = ctx.createRadialGradient(0, 0, 0, 0, 0, radius);
        gradient.addColorStop(0, 'rgba(220, 160, 80, 1)');
        gradient.addColorStop(0.4, 'rgba(200, 140, 60, 1)');
        gradient.addColorStop(0.7, 'rgba(100, 80, 40, 1)');
        gradient.addColorStop(1, 'rgba(40, 30, 20, 1)');

        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(0, 0, radius, 0, Math.PI * 2);
        ctx.fill();

        // Horizontal bands
        const bandCount = 4 + Math.floor(Math.random() * 3);
        for (let i = 0; i < bandCount; i++) {
            const y = (i / bandCount - 0.5) * radius * 1.8;
            const bandHeight = radius * 0.25;
            const bandIntensity = Math.random() * 0.3;

            ctx.globalAlpha = 0.4 * bandIntensity;
            ctx.fillStyle = i % 2 === 0 ? 'rgba(255, 200, 100, 1)' : 'rgba(150, 100, 50, 1)';
            ctx.fillRect(-radius, y - bandHeight, radius * 2, bandHeight * 2);
        }

        // Crescent shadow on one side
        ctx.globalAlpha = 0.3;
        const shadowGradient = ctx.createLinearGradient(-radius, 0, radius, 0);
        shadowGradient.addColorStop(0, 'rgba(0, 0, 0, 0.6)');
        shadowGradient.addColorStop(0.3, 'rgba(0, 0, 0, 0)');
        ctx.fillStyle = shadowGradient;
        ctx.beginPath();
        ctx.arc(0, 0, radius, 0, Math.PI * 2);
        ctx.fill();

        ctx.globalAlpha = 1;
    }

    function drawIceGiant(ctx, radius) {
        // Blue-green gradient
        const gradient = ctx.createRadialGradient(0, 0, 0, 0, 0, radius);
        gradient.addColorStop(0, 'rgba(150, 200, 220, 1)');
        gradient.addColorStop(0.5, 'rgba(80, 140, 180, 1)');
        gradient.addColorStop(1, 'rgba(30, 80, 120, 1)');

        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(0, 0, radius, 0, Math.PI * 2);
        ctx.fill();

        // Subtle banding
        for (let i = 0; i < 3; i++) {
            const y = (i / 3 - 0.5) * radius * 1.5;
            ctx.globalAlpha = 0.2;
            ctx.fillStyle = i % 2 === 0 ? 'rgba(200, 230, 255, 1)' : 'rgba(100, 150, 180, 1)';
            ctx.fillRect(-radius, y, radius * 2, radius * 0.3);
        }

        // Crescent shadow
        ctx.globalAlpha = 0.25;
        const shadowGradient = ctx.createLinearGradient(-radius, 0, radius, 0);
        shadowGradient.addColorStop(0, 'rgba(0, 30, 80, 0.5)');
        shadowGradient.addColorStop(0.3, 'rgba(0, 0, 0, 0)');
        ctx.fillStyle = shadowGradient;
        ctx.beginPath();
        ctx.arc(0, 0, radius, 0, Math.PI * 2);
        ctx.fill();

        ctx.globalAlpha = 1;
    }

    function drawRockyPlanet(ctx, radius) {
        // Gray-brown gradient
        const gradient = ctx.createRadialGradient(0, 0, 0, 0, 0, radius);
        gradient.addColorStop(0, 'rgba(180, 160, 140, 1)');
        gradient.addColorStop(0.5, 'rgba(120, 100, 80, 1)');
        gradient.addColorStop(1, 'rgba(60, 50, 40, 1)');

        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(0, 0, radius, 0, Math.PI * 2);
        ctx.fill();

        // Crater-like darker spots
        const craterCount = 3 + Math.floor(Math.random() * 4);
        for (let i = 0; i < craterCount; i++) {
            const angle = Math.random() * Math.PI * 2;
            const dist = Math.random() * radius * 0.7;
            const cx = Math.cos(angle) * dist;
            const cy = Math.sin(angle) * dist;
            const craterRadius = 1 + Math.random() * 3;

            ctx.globalAlpha = 0.4 + Math.random() * 0.3;
            ctx.fillStyle = 'rgba(30, 20, 10, 1)';
            ctx.beginPath();
            ctx.arc(cx, cy, craterRadius, 0, Math.PI * 2);
            ctx.fill();
        }

        // Crescent shadow
        ctx.globalAlpha = 0.3;
        const shadowGradient = ctx.createLinearGradient(-radius, 0, radius, 0);
        shadowGradient.addColorStop(0, 'rgba(0, 0, 0, 0.5)');
        shadowGradient.addColorStop(0.2, 'rgba(0, 0, 0, 0)');
        ctx.fillStyle = shadowGradient;
        ctx.beginPath();
        ctx.arc(0, 0, radius, 0, Math.PI * 2);
        ctx.fill();

        ctx.globalAlpha = 1;
    }

    function drawRings(ctx, planetRadius) {
        const ringOuterRadius = planetRadius * 1.8;
        const ringInnerRadius = planetRadius * 1.2;

        ctx.globalAlpha = 0.4;
        ctx.strokeStyle = 'rgba(180, 160, 140, 1)';
        ctx.lineWidth = planetRadius * 0.3;
        ctx.beginPath();
        ctx.ellipse(0, 0, ringOuterRadius, ringInnerRadius * 0.4, 0, 0, Math.PI * 2);
        ctx.stroke();

        // Ring shadow
        ctx.globalAlpha = 0.15;
        ctx.strokeStyle = 'rgba(0, 0, 0, 1)';
        ctx.lineWidth = planetRadius * 0.2;
        ctx.beginPath();
        ctx.ellipse(0, 0, ringOuterRadius * 0.95, ringInnerRadius * 0.35, 0, 0, Math.PI * 2);
        ctx.stroke();

        ctx.globalAlpha = 1;
    }

    function injectSpaceBg() {
        removeSpaceBg();

        const root = document.createElement('div');
        root.id = 'te-space-root';

        // Layer order: nebula gradient → nebula canvas → planet canvas → galaxies → starfield (on top) → CSS blobs
        // No scanlines

        // 1. CSS gradient nebula layer (animated background)
        const nebula = document.createElement('div');
        nebula.className = 'te-nebula-layer';
        root.appendChild(nebula);

        // 2. Procedural canvas nebula — render at very low res and blur heavily for soft edges
        const nebulaCanvas = document.createElement('canvas');
        nebulaCanvas.width = Math.floor(window.innerWidth * 0.15);
        nebulaCanvas.height = Math.floor(window.innerHeight * 0.15);
        nebulaCanvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;opacity:0.6;filter:blur(6px);pointer-events:none;';
        paintNebulaCanvas(nebulaCanvas);
        root.appendChild(nebulaCanvas);

        // 3. Canvas-based planet renderer (behind stars)
        const planetCanvas = document.createElement('canvas');
        planetCanvas.width = window.innerWidth;
        planetCanvas.height = window.innerHeight;
        planetCanvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;';
        renderPlanets(planetCanvas);
        root.appendChild(planetCanvas);

        // 4. Canvas-based galaxy renderer
        const galaxyCanvas = document.createElement('canvas');
        galaxyCanvas.width = window.innerWidth;
        galaxyCanvas.height = window.innerHeight;
        galaxyCanvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;';
        renderGalaxies(galaxyCanvas);
        root.appendChild(galaxyCanvas);

        // 5. Canvas-based animated starfield (on top, most visible)
        const starfieldCanvas = document.createElement('canvas');
        starfieldCanvas.width = window.innerWidth;
        starfieldCanvas.height = window.innerHeight;
        starfieldCanvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;';
        initStarfield(starfieldCanvas);
        root.appendChild(starfieldCanvas);

        // 6. 3 nebula gas clouds (CSS blurred blobs)
        for (let i = 0; i < 3; i++) {
            const blob = document.createElement('div');
            blob.className = 'te-nebula-blob';
            root.appendChild(blob);
        }

        document.body.appendChild(root);
        document.body.classList.add('te-space-active');
        floaterStart();
    }

    function removeSpaceBg() {
        floaterStop();
        if (_starfieldRAF) { cancelAnimationFrame(_starfieldRAF); _starfieldRAF = null; }
        if (_galaxyRAF) { cancelAnimationFrame(_galaxyRAF); _galaxyRAF = null; }
        _starfieldCanvas = null;
        _galaxyCanvas = null;
        _planetCanvas = null;
        const existing = document.getElementById('te-space-root');
        if (existing) existing.remove();
        document.body.classList.remove('te-space-active');
    }

    // ── Floating robots — random office bots drift across space ──
    let _floaterTimer = null;
    let _screensaverTimer = null;
    let _screensaverActive = false;
    const SCREENSAVER_IDLE_MS = 90000; // 90 seconds of inactivity

    // Robot roster — pulled from OFFICE_AGENT_SEEDS colors
    const FLOATER_BOTS = [
        { name: 'Thomas',  primary: '#9ad8ff', secondary: '#5aaeff', glow: 'rgba(154, 216, 255, 0.5)' },
        { name: 'Brandon', primary: '#9ad8ff', secondary: '#5aaeff', glow: 'rgba(154, 216, 255, 0.45)' },
        { name: 'Trey',    primary: '#9becc9', secondary: '#5ec9a0', glow: 'rgba(155, 236, 201, 0.45)' },
        { name: 'Zach',    primary: '#ffd49f', secondary: '#e0a050', glow: 'rgba(255, 212, 159, 0.4)' },
        { name: 'Matt',    primary: '#ffc7eb', secondary: '#e080c0', glow: 'rgba(255, 199, 235, 0.4)' },
        { name: 'Taylor',  primary: '#d7c8ff', secondary: '#a080e0', glow: 'rgba(215, 200, 255, 0.4)' },
        { name: 'Nova',    primary: '#9ad8ff', secondary: '#60b8f0', glow: 'rgba(154, 216, 255, 0.4)' },
        { name: 'Pixel',   primary: '#9becc9', secondary: '#50d0a0', glow: 'rgba(155, 236, 201, 0.4)' },
        { name: 'Byte',    primary: '#f4c4ff', secondary: '#c070e8', glow: 'rgba(244, 196, 255, 0.4)' },
        { name: 'Orbit',   primary: '#9fd9ff', secondary: '#60b0e0', glow: 'rgba(159, 217, 255, 0.4)' },
        { name: 'Echo',    primary: '#b2ffc8', secondary: '#60d090', glow: 'rgba(178, 255, 200, 0.4)' },
        { name: 'Glitch',  primary: '#ffd0a8', secondary: '#d09060', glow: 'rgba(255, 208, 168, 0.4)' },
        { name: 'Cipher',  primary: '#a7ffe3', secondary: '#50c8a0', glow: 'rgba(167, 255, 227, 0.4)' },
    ];

    function floaterStart() {
        // First flyby after 20-40 seconds, then every 55-120 seconds
        _floaterTimer = setTimeout(function loop() {
            launchFloater();
            _floaterTimer = setTimeout(loop, (55 + Math.random() * 65) * 1000);
        }, (20 + Math.random() * 20) * 1000);
        _startScreensaverWatch();
    }

    function floaterStop() {
        if (_floaterTimer) { clearTimeout(_floaterTimer); _floaterTimer = null; }
        _stopScreensaverWatch();
        const existing = document.querySelectorAll('.te-floater');
        existing.forEach(el => el.remove());
    }

    function launchFloater() {
        const root = document.getElementById('te-space-root');
        if (!root) return;

        const vw = window.innerWidth;
        const vh = window.innerHeight;

        // Pick a random robot from the roster
        const bot = FLOATER_BOTS[Math.floor(Math.random() * FLOATER_BOTS.length)];

        // Random edge to start from (0=left, 1=right, 2=top, 3=bottom)
        const edge = Math.floor(Math.random() * 4);
        // Wider scale range: tiny distant bots (0.35) to big close ones (1.5)
        const scale = 0.35 + Math.random() * 1.15;
        // Flight duration 14-24 seconds
        const duration = 14 + Math.random() * 10;

        let startX, startY, endX, endY;
        // Larger margin ensures bot is fully off-screen before appearing/fading
        const botSize = 58 * scale;
        const margin = botSize + 40;

        if (edge === 0) {
            startX = -margin; startY = vh * (0.1 + Math.random() * 0.8);
            endX = vw + margin; endY = vh * (0.1 + Math.random() * 0.8);
        } else if (edge === 1) {
            startX = vw + margin; startY = vh * (0.1 + Math.random() * 0.8);
            endX = -margin; endY = vh * (0.1 + Math.random() * 0.8);
        } else if (edge === 2) {
            startX = vw * (0.1 + Math.random() * 0.8); startY = -margin;
            endX = vw * (0.1 + Math.random() * 0.8); endY = vh + margin;
        } else {
            startX = vw * (0.1 + Math.random() * 0.8); startY = vh + margin;
            endX = vw * (0.1 + Math.random() * 0.8); endY = -margin;
        }

        const flipX = endX < startX ? 'scaleX(-1)' : '';

        const floater = document.createElement('div');
        floater.className = 'te-floater';
        // z-index 0 = behind content. Screensaver CSS overrides to 2.
        floater.style.cssText = `position:fixed;left:${startX}px;top:${startY}px;transform:scale(${scale}) ${flipX};z-index:0;`;
        floater.style.filter = `drop-shadow(0 0 18px ${bot.glow}) drop-shadow(0 0 6px ${bot.glow})`;

        floater.innerHTML =
            '<div class="te-floater-bot" style="animation:te-floater-bob 3s ease-in-out infinite;' +
            '--bot-primary:' + bot.primary + ';--bot-secondary:' + bot.secondary + '">' +
            '<div class="te-floater-head"><div class="te-floater-eye left"></div><div class="te-floater-eye right"></div></div>' +
            '<div class="te-floater-body"></div>' +
            '<div class="te-floater-leg left"></div><div class="te-floater-leg right"></div>' +
            '<span class="te-floater-name">' + bot.name + '</span>' +
            '</div>';

        document.body.appendChild(floater);

        // Keyframes: stay fully visible across the entire viewport,
        // only fade at the very edges (3% in, 97% out) so bot is off-screen when invisible
        const keyframes = [
            { left: startX + 'px', top: startY + 'px', opacity: 0 },
            { left: startX + (endX - startX) * 0.03 + 'px', top: startY + (endY - startY) * 0.03 + 'px', opacity: 0.85, offset: 0.03 },
            { left: startX + (endX - startX) * 0.97 + 'px', top: startY + (endY - startY) * 0.97 + 'px', opacity: 0.85, offset: 0.97 },
            { left: endX + 'px', top: endY + 'px', opacity: 0 },
        ];

        const anim = floater.animate(keyframes, {
            duration: duration * 1000,
            easing: 'linear',
            fill: 'forwards',
        });

        anim.onfinish = () => floater.remove();
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
                    <span><span class="te-dot"></span>TERMINAL</span>
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
                    <span class="te-panel-sub" data-te-mtitle>today</span>
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
        if (!tableEl) return;

        const detail = _s.today?.by_model_detail || {};
        const rows = Object.entries(detail)
            .map(([n, d]) => ({ n, usd: +d.usd || 0, calls: +d.calls || 0, total: +(d.tokens?.total) || 0 }))
            .sort((a, b) => b.usd - a.usd);

        if (!rows.length) {
            if (vizEl) vizEl.innerHTML = '<div class="te-idle-viz"><span class="te-idle-pulse"></span></div>';
            tableEl.innerHTML = '<div class="te-empty-state">no model usage today</div>';
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
            el.innerHTML = '<div class="te-empty-state">no spend history</div>';
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
    // This means moduleEnterMode('token_economy') will call injectSpaceBg()
    // and moduleLeaveMode() / switching away will call removeSpaceBg().
    // The space background covers the ENTIRE page, not just the widget.
    window.__moduleBackgrounds = window.__moduleBackgrounds || {};
    window.__moduleBackgrounds['token_economy'] = {
        mount: injectSpaceBg,
        unmount: removeSpaceBg,
    };

    window.__tokenEconomy = { mount, unmount, refresh, getState: () => ({ ..._s }) };
})();
