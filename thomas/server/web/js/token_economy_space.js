/**
 * token_economy_space.js — Space rendering engine v5
 *
 * Extracted from token_economy.js for monolith compliance.
 * Exposes window.__teSpace = { init, inject, remove }.
 * Must be loaded BEFORE token_economy.js.
 */
window.__teSpace = (function() {
    'use strict';

    // Callbacks set by the parent module via init()
    let _onEnter = null;   // called after space bg is injected
    let _onLeave = null;   // called before space bg is removed

    function init(callbacks) {
        if (callbacks.onEnter) _onEnter = callbacks.onEnter;
        if (callbacks.onLeave) _onLeave = callbacks.onLeave;
    }

    // ══════════════════════════════════════════════════════════════
    // SPACE RENDERING ENGINE v5 — Performance-first
    // Key optimizations over v4:
    //   1. Quality tiers (auto-detected from hardware)
    //   2. Static star layer pre-rendered once; only bright stars twinkle
    //   3. Single unified RAF loop at 30fps cap
    //   4. NO shadowBlur on stars (huge GPU savings) — bloom pre-baked
    //   5. Scene cached across tab switches (no re-render on mount)
    //   6. Galaxies fully static (cached offscreen, no breathing anim)
    // ══════════════════════════════════════════════════════════════

    // ── Quality tier auto-detection ─────────────────────────────
    const _detectQuality = () => {
        const hw = navigator.hardwareConcurrency || 2;
        const mem = navigator.deviceMemory || 4; // GB, Chrome-only
        const isMobile = /Mobi|Android|iPhone/i.test(navigator.userAgent);
        if (isMobile || hw <= 2 || mem <= 2) return 'low';
        if (hw >= 8 && mem >= 8) return 'high';
        return 'medium';
    };
    const QUALITY = _detectQuality();
    const Q = {
        low:    { dpr: 1,   stars: [400, 180, 50, 10],  nebulaScale: 0.15, fps: 20, twinkleCount: 30,  planets: 1, galaxyStars: 40 },
        medium: { dpr: Math.min(window.devicePixelRatio || 1, 1.5), stars: [800, 350, 100, 20], nebulaScale: 0.25, fps: 30, twinkleCount: 60,  planets: 1, galaxyStars: 70 },
        high:   { dpr: Math.min(window.devicePixelRatio || 1, 2),   stars: [1200, 500, 140, 30], nebulaScale: 0.3, fps: 30, twinkleCount: 100, planets: 2, galaxyStars: 100 },
    }[QUALITY];
    const DPR = Q.dpr;
    const FRAME_MS = 1000 / Q.fps; // throttle interval

    // ── Noise utilities (shared) ─────────────────────────────────
    function _hash(x, y, seed) {
        const n = Math.sin(x * 127.1 + y * 311.7 + seed * 43.27) * 43758.5453;
        return n - Math.floor(n);
    }
    function _smoothNoise(x, y, seed) {
        const ix = Math.floor(x), iy = Math.floor(y);
        const fx = x - ix, fy = y - iy;
        const sx = fx * fx * fx * (fx * (fx * 6 - 15) + 10);
        const sy = fy * fy * fy * (fy * (fy * 6 - 15) + 10);
        const a = _hash(ix, iy, seed), b = _hash(ix + 1, iy, seed);
        const c = _hash(ix, iy + 1, seed), d = _hash(ix + 1, iy + 1, seed);
        return a + (b - a) * sx + (c - a) * sy + (a - b - c + d) * sx * sy;
    }
    function _fbm(x, y, seed, oct) {
        let v = 0, a = 0.5, f = 1;
        for (let i = 0; i < oct; i++) { v += a * _smoothNoise(x * f, y * f, seed + i * 137); a *= 0.47; f *= 2.05; }
        return v;
    }

    // ── Optimized starfield — static base + animated twinkle overlay ──
    let _spaceRAF = null;       // single unified RAF for all animation
    let _starfieldCanvas = null;
    let _staticStarCanvas = null; // pre-rendered static star layer (no per-frame cost)
    let _twinklers = [];          // only the bright stars that animate
    let _shootingStars = [];

    const STAR_COLORS = [
        { r: 255, g: 204, b: 150, w: 0.05 },
        { r: 255, g: 220, b: 180, w: 0.12 },
        { r: 255, g: 240, b: 220, w: 0.20 },
        { r: 255, g: 250, b: 248, w: 0.28 },
        { r: 230, g: 238, b: 255, w: 0.20 },
        { r: 195, g: 210, b: 255, w: 0.10 },
        { r: 165, g: 185, b: 255, w: 0.05 },
    ];
    function _pickStarColor() {
        let roll = Math.random();
        for (const c of STAR_COLORS) { roll -= c.w; if (roll <= 0) return c; }
        return STAR_COLORS[3];
    }

    const SHOOTING_STAR_INTERVAL = [18000, 50000];

    function initStarfield(canvas) {
        _starfieldCanvas = canvas;
        const w = canvas.width, h = canvas.height;

        // Pre-render ALL stars to a static offscreen canvas (drawn once, never redrawn)
        const oc = document.createElement('canvas');
        oc.width = w; oc.height = h;
        const octx = oc.getContext('2d');
        _twinklers = [];

        const layers = [
            { count: Q.stars[0], maxSz: 0.6,  maxA: 0.25 },
            { count: Q.stars[1], maxSz: 1.1,  maxA: 0.50 },
            { count: Q.stars[2], maxSz: 1.8,  maxA: 0.75 },
            { count: Q.stars[3], maxSz: 3.2,  maxA: 1.00 },
        ];

        layers.forEach((cfg, li) => {
            for (let i = 0; i < cfg.count; i++) {
                const c = _pickStarColor();
                const sp = Math.pow(Math.random(), 2.0);
                const ap = Math.pow(Math.random(), 1.8);
                const sz = 0.3 + sp * cfg.maxSz;
                const ba = 0.04 + ap * cfg.maxA;
                const x = Math.random() * w;
                const y = Math.random() * h;

                // Draw star to static canvas — NO shadowBlur (huge perf save)
                if (sz > 1.0 && ba > 0.25) {
                    // Bright stars: draw a pre-baked glow (radial gradient, not shadowBlur)
                    const glowR = sz * 3;
                    const g = octx.createRadialGradient(x, y, 0, x, y, glowR);
                    g.addColorStop(0, 'rgba(' + c.r + ',' + c.g + ',' + c.b + ',' + (ba * 0.9) + ')');
                    g.addColorStop(0.3, 'rgba(' + c.r + ',' + c.g + ',' + c.b + ',' + (ba * 0.3) + ')');
                    g.addColorStop(1, 'rgba(' + c.r + ',' + c.g + ',' + c.b + ',0)');
                    octx.fillStyle = g;
                    octx.beginPath();
                    octx.arc(x, y, glowR, 0, Math.PI * 2);
                    octx.fill();

                    // Add to twinkle list (these animate at lower frequency)
                    if (_twinklers.length < Q.twinkleCount) {
                        _twinklers.push({
                            x, y, sz, ba, r: c.r, g: c.g, b: c.b,
                            ts: 0.4 + Math.random() * 1.2,
                            tp: Math.random() * Math.PI * 2,
                            td: 0.15 + Math.random() * 0.35,
                        });
                    }
                } else {
                    // Dim/small stars: single pixel dot
                    octx.globalAlpha = ba;
                    octx.fillStyle = 'rgb(' + c.r + ',' + c.g + ',' + c.b + ')';
                    octx.beginPath();
                    octx.arc(x, y, Math.max(sz * 0.4, 0.5), 0, Math.PI * 2);
                    octx.fill();
                }
            }
        });
        octx.globalAlpha = 1;
        _staticStarCanvas = oc;

        _scheduleShootingStar();
    }

    function _scheduleShootingStar() {
        const delay = SHOOTING_STAR_INTERVAL[0] + Math.random() * (SHOOTING_STAR_INTERVAL[1] - SHOOTING_STAR_INTERVAL[0]);
        setTimeout(() => {
            if (!_starfieldCanvas) return;
            const w = _starfieldCanvas.width, h = _starfieldCanvas.height;
            const sx = Math.random() * w * 0.8 + w * 0.1;
            const sy = Math.random() * h * 0.3;
            const angle = Math.PI * 0.2 + Math.random() * Math.PI * 0.15;
            const len = 80 + Math.random() * 160;
            _shootingStars.push({
                sx, sy,
                ex: sx + Math.cos(angle) * len,
                ey: sy + Math.sin(angle) * len,
                life: 0, maxLife: 0.4 + Math.random() * 0.3,
                width: 1 + Math.random() * 1.5,
            });
            _scheduleShootingStar();
        }, delay);
    }

    // ── Galaxy renderer ────────────────────────────────────────
    // Pre-rendered to offscreen canvas at high res, then composited.
    // Galaxies are rendered once and cached — no per-frame redraw.
    let _galaxyCanvas = null;
    let _galaxies = [];
    let _galaxyCache = []; // pre-rendered ImageData

    function _renderGalaxyToCache(gal) {
        // Render galaxy to an offscreen canvas at 2x its display size for quality
        const pad = 1.5; // extra space for outer glow
        const cSize = Math.ceil(gal.size * 2 * pad);
        const oc = document.createElement('canvas');
        oc.width = cSize; oc.height = cSize;
        const ctx = oc.getContext('2d');
        const cx = cSize / 2, cy = cSize / 2;
        const S = gal.size;

        if (gal.type === 'spiral' || gal.type === 'barred') {
            // ── Step 1: Broad diffuse disk (the "glow" that IS the galaxy) ──
            const diskGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, S * 0.7);
            diskGrad.addColorStop(0, 'rgba(255, 245, 220, 0.30)');
            diskGrad.addColorStop(0.15, 'rgba(250, 235, 200, 0.22)');
            diskGrad.addColorStop(0.4, 'rgba(220, 210, 200, 0.08)');
            diskGrad.addColorStop(0.7, 'rgba(200, 195, 210, 0.02)');
            diskGrad.addColorStop(1, 'rgba(180, 180, 200, 0)');
            ctx.fillStyle = diskGrad;
            ctx.beginPath();
            ctx.arc(cx, cy, S * 0.7, 0, Math.PI * 2);
            ctx.fill();

            // ── Step 2: Bright nucleus ──
            const coreGrad = ctx.createRadialGradient(cx, cy, 0, cx, cy, S * 0.1);
            coreGrad.addColorStop(0, 'rgba(255, 245, 215, 0.85)');
            coreGrad.addColorStop(0.3, 'rgba(255, 235, 195, 0.55)');
            coreGrad.addColorStop(0.7, 'rgba(240, 220, 180, 0.15)');
            coreGrad.addColorStop(1, 'rgba(220, 200, 170, 0)');
            ctx.fillStyle = coreGrad;
            ctx.beginPath();
            ctx.arc(cx, cy, S * 0.1, 0, Math.PI * 2);
            ctx.fill();

            // ── Step 3: Spiral arms — overlapping luminous blobs along log spirals ──
            const armCount = 2;
            const tight = gal.armTightness;
            for (let arm = 0; arm < armCount; arm++) {
                const off = arm * Math.PI;
                // Broad arm glow blobs
                for (let b = 0; b < 40; b++) {
                    const t = (b + 1) / 41;
                    const angle = off + t * Math.PI * 2.5 * tight;
                    const r = t * S * 0.55;
                    const x = cx + Math.cos(angle) * r;
                    const y = cy + Math.sin(angle) * r;
                    const bSz = S * (0.05 + t * 0.10) * (1 - t * 0.25);
                    const bA = (0.7 - t * 0.5) * 0.18;

                    const bg = ctx.createRadialGradient(x, y, 0, x, y, bSz);
                    bg.addColorStop(0, 'rgba(240, 232, 215, ' + bA + ')');
                    bg.addColorStop(0.5, 'rgba(215, 208, 220, ' + (bA * 0.3) + ')');
                    bg.addColorStop(1, 'rgba(195, 195, 215, 0)');
                    ctx.fillStyle = bg;
                    ctx.beginPath();
                    ctx.arc(x, y, bSz, 0, Math.PI * 2);
                    ctx.fill();
                }

                // Individual star points along arms
                for (let s = 0; s < Q.galaxyStars; s++) {
                    const t = Math.random();
                    const angle = off + t * Math.PI * 2.5 * tight;
                    const r = t * S * 0.55;
                    const scatter = S * 0.07 * (0.4 + t);
                    const sx = cx + Math.cos(angle) * r + (Math.random() - 0.5) * scatter;
                    const sy = cy + Math.sin(angle) * r + (Math.random() - 0.5) * scatter;
                    const sa = (0.55 - t * 0.35) * (0.2 + Math.random() * 0.6);
                    const w = 1 - t;

                    ctx.globalAlpha = sa;
                    ctx.fillStyle = 'rgb(' + (195 + Math.floor(w * 60)) + ',' + (190 + Math.floor(w * 45)) + ',' + (210 - Math.floor(w * 25)) + ')';
                    ctx.beginPath();
                    ctx.arc(sx, sy, 0.5 + Math.random() * 0.8, 0, Math.PI * 2);
                    ctx.fill();
                }
            }

            // ── Step 4: Dust lanes — dark ribbons on inner side of arms ──
            ctx.globalCompositeOperation = 'multiply';
            for (let arm = 0; arm < armCount; arm++) {
                const off = arm * Math.PI + 0.15; // slightly offset from bright arm
                for (let d = 0; d < 25; d++) {
                    const t = 0.1 + (d / 25) * 0.7;
                    const angle = off + t * Math.PI * 2.5 * tight;
                    const r = t * S * 0.5;
                    const x = cx + Math.cos(angle) * r;
                    const y = cy + Math.sin(angle) * r;
                    const dSz = S * 0.03 * (0.5 + t);
                    ctx.globalAlpha = 0.15 + Math.random() * 0.1;
                    ctx.fillStyle = 'rgb(20, 18, 15)';
                    ctx.beginPath();
                    ctx.arc(x, y, dSz, 0, Math.PI * 2);
                    ctx.fill();
                }
            }
            ctx.globalCompositeOperation = 'source-over';

            // ── Step 5: HII regions — pink star-forming knots ──
            for (let arm = 0; arm < armCount; arm++) {
                const hiiCount = 3 + Math.floor(Math.random() * 3);
                for (let i = 0; i < hiiCount; i++) {
                    const t = 0.2 + Math.random() * 0.6;
                    const angle = (arm * Math.PI) + t * Math.PI * 2.5 * tight;
                    const r = t * S * 0.55;
                    const x = cx + Math.cos(angle) * r;
                    const y = cy + Math.sin(angle) * r;
                    const hs = 1.5 + Math.random() * 3;
                    const hg = ctx.createRadialGradient(x, y, 0, x, y, hs);
                    hg.addColorStop(0, 'rgba(255, 160, 130, 0.35)');
                    hg.addColorStop(1, 'rgba(255, 110, 90, 0)');
                    ctx.globalAlpha = 1;
                    ctx.fillStyle = hg;
                    ctx.beginPath();
                    ctx.arc(x, y, hs, 0, Math.PI * 2);
                    ctx.fill();
                }
            }
        } else {
            // Elliptical / smudge — just a smooth golden glow
            const aspect = 0.55 + Math.random() * 0.35;
            ctx.save();
            ctx.translate(cx, cy);
            ctx.scale(1, aspect);
            const eg = ctx.createRadialGradient(0, 0, 0, 0, 0, S * 0.4);
            eg.addColorStop(0, 'rgba(255, 240, 200, 0.45)');
            eg.addColorStop(0.25, 'rgba(245, 225, 185, 0.25)');
            eg.addColorStop(0.6, 'rgba(215, 205, 195, 0.06)');
            eg.addColorStop(1, 'rgba(195, 195, 205, 0)');
            ctx.fillStyle = eg;
            ctx.beginPath();
            ctx.arc(0, 0, S * 0.4, 0, Math.PI * 2);
            ctx.fill();
            ctx.restore();
        }

        ctx.globalAlpha = 1;
        return oc;
    }

    function renderGalaxies(canvas) {
        _galaxyCanvas = canvas;
        const w = canvas.width, h = canvas.height;
        const ctx = canvas.getContext('2d');

        _galaxies = [];
        _galaxyCache = [];

        // 1 feature galaxy + 1-2 distant smudges
        const featureSize = 100 + Math.random() * 80;
        const fType = Math.random() < 0.65 ? 'spiral' : 'barred';
        const fx = w * (Math.random() < 0.5 ? 0.08 + Math.random() * 0.28 : 0.62 + Math.random() * 0.28);
        const fy = h * (Math.random() < 0.5 ? 0.55 + Math.random() * 0.35 : 0.08 + Math.random() * 0.32);
        _galaxies.push({
            type: fType, size: featureSize, x: fx, y: fy,
            rotation: Math.random() * Math.PI * 2,
            tilt: 0.25 + Math.random() * 0.55,
            armTightness: 0.7 + Math.random() * 1.0,
        });

        const distCount = 1 + Math.floor(Math.random() * 2);
        for (let i = 0; i < distCount; i++) {
            _galaxies.push({
                type: Math.random() < 0.5 ? 'elliptical' : 'smudge',
                size: 12 + Math.random() * 20,
                x: Math.random() * w, y: Math.random() * h,
                rotation: Math.random() * Math.PI * 2,
                tilt: 0.3 + Math.random() * 0.6,
                armTightness: 0.8 + Math.random() * 1.0,
            });
        }

        // Pre-render each galaxy then composite ONCE — no per-frame loop
        _galaxies.forEach(g => _galaxyCache.push(_renderGalaxyToCache(g)));

        _galaxies.forEach((gal, i) => {
            const cached = _galaxyCache[i];
            if (!cached) return;
            ctx.save();
            ctx.globalAlpha = 0.88;
            ctx.translate(gal.x, gal.y);
            ctx.rotate(gal.rotation);
            ctx.scale(1, gal.tilt);
            ctx.drawImage(cached, -cached.width / 2, -cached.height / 2);
            ctx.restore();
        });
        ctx.globalAlpha = 1;
        // Galaxies are now fully static — no RAF loop needed
    }

    // ── Procedural nebula canvas — organic noise-based gas clouds ──
    // Rendered at higher resolution, much darker/subtler than before
    function paintNebulaCanvas(canvas) {
        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const h = canvas.height;

        // Improved hash-based noise
        function noise(x, y, seed) {
            const n = Math.sin(x * 12.9898 + y * 78.233 + seed * 43.2187) * 43758.5453;
            return n - Math.floor(n);
        }

        function smoothNoise(x, y, seed) {
            const ix = Math.floor(x), iy = Math.floor(y);
            const fx = x - ix, fy = y - iy;
            // Quintic interpolation for smoother gradients (less blocky than cubic)
            const sx = fx * fx * fx * (fx * (fx * 6 - 15) + 10);
            const sy = fy * fy * fy * (fy * (fy * 6 - 15) + 10);
            const a = noise(ix, iy, seed), b = noise(ix + 1, iy, seed);
            const c = noise(ix, iy + 1, seed), d = noise(ix + 1, iy + 1, seed);
            return a + (b - a) * sx + (c - a) * sy + (a - b - c + d) * sx * sy;
        }

        function fbm(x, y, seed, octaves) {
            let v = 0, amp = 0.5, freq = 1;
            for (let i = 0; i < octaves; i++) {
                v += amp * smoothNoise(x * freq, y * freq, seed + i * 137.3);
                amp *= 0.48;
                freq *= 2.05;
            }
            return v;
        }

        // Much darker, more muted palette — realistic deep space nebula
        const palette = [
            [10, 20, 60],    // very deep blue
            [35, 12, 55],    // dark purple
            [8, 35, 50],     // dark teal
            [55, 18, 40],    // muted rose
            [20, 50, 80],    // medium blue
            [30, 10, 50],    // deep violet
            [60, 40, 15],    // muted amber
            [15, 60, 70],    // dark cyan
        ];

        const imgData = ctx.createImageData(w, h);
        const d = imgData.data;
        const scaleX = 4.5 / w, scaleY = 4.5 / h;

        for (let py = 0; py < h; py++) {
            for (let px = 0; px < w; px++) {
                const idx = (py * w + px) * 4;
                const nx = px * scaleX, ny = py * scaleY;

                // Domain-warped noise for more organic swirling shapes
                const warp = fbm(nx, ny, 200, 4) * 1.5;
                const n1 = fbm(nx + warp, ny + warp * 0.7, 0, 7);
                const n2 = fbm(nx + 10 + warp * 0.5, ny + 10, 50, 6);
                const n3 = fbm(nx + 20, ny - 5 + warp * 0.3, 100, 6);

                const ci1 = Math.floor(n1 * (palette.length - 1));
                const ci2 = Math.min(ci1 + 1, palette.length - 1);
                const t = (n1 * (palette.length - 1)) - ci1;
                const c1 = palette[ci1], c2 = palette[ci2];

                // Much lower density/brightness cap — space is mostly black
                const density = Math.max(0, n2 * 1.1 - 0.35);
                const brightness = density * 0.35; // very dim

                const r = (c1[0] + (c2[0] - c1[0]) * t) * brightness;
                const g = (c1[1] + (c2[1] - c1[1]) * t) * brightness;
                const b = (c1[2] + (c2[2] - c1[2]) * t) * brightness;

                // Alpha: softer, more wispy
                const alpha = Math.min(255, brightness * n3 * 280);

                d[idx] = Math.min(255, r);
                d[idx + 1] = Math.min(255, g);
                d[idx + 2] = Math.min(255, b * 1.15); // slight blue bias
                d[idx + 3] = alpha;
            }
        }
        ctx.putImageData(imgData, 0, 0);
    }

    // ── Planet renderer v4 — pixel-level sphere UV mapping ──────
    // Each visible pixel is reverse-projected onto the sphere surface,
    // then sampled from noise-based surface texture with proper Lambertian
    // lighting, atmospheric scattering, and specular highlights.
    // Planets are pre-rendered to offscreen canvases (like galaxies).
    let _planetCanvas = null;
    let _planets = [];
    let _planetCache = []; // offscreen canvas per planet

    // ── Planet type palettes ──
    // Each planet type defines multiple possible color schemes for variety
    const PLANET_PALETTES = {
        gasGiant: [
            // Jupiter-like: ochre/amber/brown bands
            { base: [180, 140, 80], band1: [210, 170, 100], band2: [130, 90, 50], band3: [220, 185, 120], storm: [200, 160, 90], atmos: [255, 210, 150] },
            // Saturn-like: pale gold/cream
            { base: [200, 185, 140], band1: [220, 200, 155], band2: [170, 150, 110], band3: [210, 195, 145], storm: [230, 210, 160], atmos: [255, 230, 180] },
            // Hot Jupiter: deep red/umber
            { base: [150, 70, 50], band1: [180, 90, 60], band2: [100, 50, 35], band3: [170, 80, 55], storm: [200, 100, 70], atmos: [255, 160, 120] },
        ],
        iceGiant: [
            // Uranus-like: pale cyan/teal
            { base: [100, 170, 190], band1: [120, 190, 210], band2: [70, 130, 160], highlight: [160, 210, 230], atmos: [150, 210, 240] },
            // Neptune-like: deep blue
            { base: [45, 80, 160], band1: [60, 100, 190], band2: [30, 55, 120], highlight: [90, 130, 210], atmos: [100, 160, 255] },
        ],
        rocky: [
            // Mars-like: rusty red/orange
            { base: [160, 100, 60], crater: [120, 70, 40], high: [190, 130, 85], atmos: [200, 150, 120] },
            // Moon-like: grey
            { base: [130, 125, 120], crater: [80, 75, 70], high: [160, 155, 150], atmos: [180, 175, 170] },
            // Mercury-like: dark grey/brown
            { base: [95, 85, 75], crater: [55, 50, 45], high: [125, 115, 105], atmos: [150, 140, 130] },
            // Volcanic: dark with orange cracks
            { base: [60, 50, 45], crater: [35, 28, 22], high: [80, 65, 55], atmos: [200, 120, 80] },
        ],
        earthLike: [
            // Temperate: blue ocean, green/brown land
            { ocean: [30, 60, 120], land: [70, 110, 55], desert: [160, 140, 95], ice: [210, 220, 230], cloud: [240, 240, 245], atmos: [130, 180, 255] },
            // Arid: mostly desert with small seas
            { ocean: [50, 80, 130], land: [150, 130, 80], desert: [180, 155, 100], ice: [200, 210, 220], cloud: [230, 225, 215], atmos: [180, 170, 140] },
        ],
    };

    function _renderPlanetToCache(planet) {
        const R = planet.radius;
        const pad = planet.hasRings ? 2.2 : 1.25; // extra room for rings + atmosphere
        const cSize = Math.ceil(R * 2 * pad);
        const oc = document.createElement('canvas');
        oc.width = cSize; oc.height = cSize;
        const ctx = oc.getContext('2d');
        const cx = cSize / 2, cy = cSize / 2;
        const seed = planet.seed;
        const pal = planet.palette;

        // Light direction (unit vector) — consistent upper-right
        const lx = Math.cos(planet.lightAngle);
        const ly = Math.sin(planet.lightAngle);
        const lz = 0.4; // slight z component (light slightly toward viewer)
        const lLen = Math.sqrt(lx * lx + ly * ly + lz * lz);
        const lnx = lx / lLen, lny = ly / lLen, lnz = lz / lLen;

        // ── Draw rings behind planet first ──
        if (planet.hasRings) _drawRingsV4(ctx, cx, cy, R, planet, false);

        // ── Pixel-level sphere rendering ──
        // Create ImageData for the planet sphere area
        const sphereR = Math.ceil(R);
        const diam = sphereR * 2 + 2;
        const ox = Math.floor(cx - sphereR - 1);
        const oy = Math.floor(cy - sphereR - 1);
        const imgData = ctx.createImageData(diam, diam);
        const d = imgData.data;

        for (let py = 0; py < diam; py++) {
            for (let px = 0; px < diam; px++) {
                const sx = px - diam / 2; // pixel relative to sphere center
                const sy = py - diam / 2;
                const dist2 = sx * sx + sy * sy;
                const r2 = sphereR * sphereR;

                if (dist2 > r2) continue; // outside sphere

                // ── Reverse project to sphere surface (x,y,z on unit sphere) ──
                const nz = Math.sqrt(1 - dist2 / r2);
                const nx = sx / sphereR;
                const ny = sy / sphereR;

                // ── Lambertian diffuse lighting ──
                const lambert = Math.max(0, nx * lnx + ny * lny + nz * lnz);
                // Smooth terminator with a little ambient
                const ambient = 0.04;
                const light = ambient + (1 - ambient) * Math.pow(lambert, 0.7);

                // ── Sphere UV coordinates ──
                // theta = atan2(ny, nx), phi = acos(nz)
                const u = 0.5 + Math.atan2(nx, nz) / (Math.PI * 2); // 0..1 longitude
                const v = 0.5 - Math.asin(ny) / Math.PI; // 0..1 latitude

                // ── Surface color from noise ──
                let cr, cg, cb;
                const noiseScale = 8;

                if (planet.type === 'gasGiant') {
                    // Banded gas giant with storms
                    const bandNoise = _fbm(u * noiseScale * 2, v * noiseScale * 0.3, seed, 5);
                    // Latitude-dependent bands
                    const latBand = Math.sin(v * Math.PI * (6 + Math.floor(seed % 4))) * 0.5 + 0.5;
                    // Domain-warped turbulence for swirls
                    const warp = _fbm(u * noiseScale, v * noiseScale, seed + 100, 4) * 0.3;
                    const turb = _fbm(u * noiseScale + warp, v * noiseScale * 0.5 + warp, seed + 200, 6);

                    // Blend between band colors based on latitude
                    const t1 = latBand * (0.5 + bandNoise * 0.5);
                    const t2 = turb;
                    cr = pal.base[0] + (pal.band1[0] - pal.base[0]) * t1 + (pal.band2[0] - pal.base[0]) * t2 * 0.3;
                    cg = pal.base[1] + (pal.band1[1] - pal.base[1]) * t1 + (pal.band2[1] - pal.base[1]) * t2 * 0.3;
                    cb = pal.base[2] + (pal.band1[2] - pal.base[2]) * t1 + (pal.band2[2] - pal.base[2]) * t2 * 0.3;

                    // Great spot / storm feature
                    if (planet.hasStorm) {
                        const sdx = u - planet.stormU;
                        const sdy = v - planet.stormV;
                        const sDist = Math.sqrt(sdx * sdx * 4 + sdy * sdy);
                        if (sDist < 0.08) {
                            const sf = 1 - sDist / 0.08;
                            const sw = sf * sf;
                            cr = cr * (1 - sw) + pal.storm[0] * sw;
                            cg = cg * (1 - sw) + pal.storm[1] * sw;
                            cb = cb * (1 - sw) + pal.storm[2] * sw;
                        }
                    }
                } else if (planet.type === 'iceGiant') {
                    // Subtle banding with smooth gradients
                    const latGrad = Math.sin(v * Math.PI * 3) * 0.5 + 0.5;
                    const noise1 = _fbm(u * noiseScale, v * noiseScale * 0.5, seed, 5);
                    const t = latGrad * 0.6 + noise1 * 0.4;
                    cr = pal.base[0] + (pal.band1[0] - pal.base[0]) * t;
                    cg = pal.base[1] + (pal.band1[1] - pal.base[1]) * t;
                    cb = pal.base[2] + (pal.band1[2] - pal.base[2]) * t;
                    // Bright highlight patches
                    const hn = _fbm(u * noiseScale * 1.5, v * noiseScale * 1.5, seed + 50, 4);
                    if (hn > 0.6) {
                        const hf = (hn - 0.6) * 2.5;
                        cr += (pal.highlight[0] - cr) * hf * 0.3;
                        cg += (pal.highlight[1] - cg) * hf * 0.3;
                        cb += (pal.highlight[2] - cb) * hf * 0.3;
                    }
                } else if (planet.type === 'earthLike') {
                    // Continents, oceans, polar ice
                    const continentNoise = _fbm(u * noiseScale * 0.8, v * noiseScale * 0.8, seed, 7);
                    const detailNoise = _fbm(u * noiseScale * 3, v * noiseScale * 3, seed + 300, 4);
                    const polarFactor = Math.abs(v - 0.5) * 2; // 0 at equator, 1 at poles

                    if (polarFactor > 0.82) {
                        // Ice caps
                        const iceMix = (polarFactor - 0.82) / 0.18;
                        cr = pal.ice[0]; cg = pal.ice[1]; cb = pal.ice[2];
                        cr += detailNoise * 15; cg += detailNoise * 15; cb += detailNoise * 15;
                    } else if (continentNoise > 0.48) {
                        // Land
                        const landT = (continentNoise - 0.48) * 3;
                        const dryT = Math.max(0, 1 - Math.abs(v - 0.5) * 4); // drier near equator
                        cr = pal.land[0] + (pal.desert[0] - pal.land[0]) * dryT * landT;
                        cg = pal.land[1] + (pal.desert[1] - pal.land[1]) * dryT * landT;
                        cb = pal.land[2] + (pal.desert[2] - pal.land[2]) * dryT * landT;
                        // Terrain detail
                        cr += detailNoise * 20 - 10;
                        cg += detailNoise * 20 - 10;
                        cb += detailNoise * 15 - 8;
                    } else {
                        // Ocean
                        const depthT = (0.48 - continentNoise) * 3;
                        cr = pal.ocean[0] - depthT * 10;
                        cg = pal.ocean[1] - depthT * 8;
                        cb = pal.ocean[2] + depthT * 15 + detailNoise * 10;
                        // Specular highlight on ocean (sun glint)
                        const spec = Math.pow(Math.max(0, nz * lnz + nx * lnx + ny * lny), 40);
                        cr += spec * 80; cg += spec * 80; cb += spec * 80;
                    }

                    // Cloud layer
                    const cloudNoise = _fbm(u * noiseScale * 1.2 + seed * 0.01, v * noiseScale * 0.8, seed + 500, 5);
                    if (cloudNoise > 0.45) {
                        const cloudT = Math.min(1, (cloudNoise - 0.45) * 3) * 0.6;
                        cr = cr * (1 - cloudT) + pal.cloud[0] * cloudT;
                        cg = cg * (1 - cloudT) + pal.cloud[1] * cloudT;
                        cb = cb * (1 - cloudT) + pal.cloud[2] * cloudT;
                    }
                } else {
                    // Rocky planet — craters, highlands, rougher terrain
                    const terrain = _fbm(u * noiseScale * 1.5, v * noiseScale * 1.5, seed, 7);
                    const rough = _fbm(u * noiseScale * 5, v * noiseScale * 5, seed + 77, 4);

                    // Mix between base, crater, and high ground colors
                    if (terrain < 0.35) {
                        // Crater / low ground
                        const t = terrain / 0.35;
                        cr = pal.crater[0] + (pal.base[0] - pal.crater[0]) * t;
                        cg = pal.crater[1] + (pal.base[1] - pal.crater[1]) * t;
                        cb = pal.crater[2] + (pal.base[2] - pal.crater[2]) * t;
                    } else if (terrain > 0.65) {
                        const t = (terrain - 0.65) / 0.35;
                        cr = pal.base[0] + (pal.high[0] - pal.base[0]) * t;
                        cg = pal.base[1] + (pal.high[1] - pal.base[1]) * t;
                        cb = pal.base[2] + (pal.high[2] - pal.base[2]) * t;
                    } else {
                        cr = pal.base[0]; cg = pal.base[1]; cb = pal.base[2];
                    }
                    // Micro-roughness detail
                    cr += (rough - 0.5) * 30;
                    cg += (rough - 0.5) * 28;
                    cb += (rough - 0.5) * 25;
                }

                // ── Apply lighting ──
                cr *= light; cg *= light; cb *= light;

                // ── Limb darkening (edges of sphere are dimmer) ──
                const limbDark = 0.7 + 0.3 * nz;
                cr *= limbDark; cg *= limbDark; cb *= limbDark;

                // ── Atmospheric scattering at the limb ──
                const limb = 1 - nz; // 0 at center, 1 at edge
                const scatterStrength = Math.pow(limb, 3) * 0.35;
                cr = cr * (1 - scatterStrength) + pal.atmos[0] * scatterStrength;
                cg = cg * (1 - scatterStrength) + pal.atmos[1] * scatterStrength;
                cb = cb * (1 - scatterStrength) + pal.atmos[2] * scatterStrength;

                // ── Anti-aliased edge ──
                const edgeDist = Math.sqrt(dist2) / sphereR;
                const edgeAlpha = edgeDist > 0.97 ? (1 - edgeDist) / 0.03 : 1;

                const idx = (py * diam + px) * 4;
                d[idx] = Math.max(0, Math.min(255, cr));
                d[idx + 1] = Math.max(0, Math.min(255, cg));
                d[idx + 2] = Math.max(0, Math.min(255, cb));
                d[idx + 3] = Math.max(0, Math.min(255, edgeAlpha * 255));
            }
        }
        ctx.putImageData(imgData, Math.max(0, ox), Math.max(0, oy));

        // ── Atmospheric glow (drawn on top of sphere with canvas API) ──
        const glowR = R * 1.12;
        const glowGrad = ctx.createRadialGradient(cx, cy, R * 0.92, cx, cy, glowR);
        glowGrad.addColorStop(0, 'rgba(' + pal.atmos[0] + ',' + pal.atmos[1] + ',' + pal.atmos[2] + ', 0)');
        glowGrad.addColorStop(0.4, 'rgba(' + pal.atmos[0] + ',' + pal.atmos[1] + ',' + pal.atmos[2] + ', 0.06)');
        glowGrad.addColorStop(0.7, 'rgba(' + pal.atmos[0] + ',' + pal.atmos[1] + ',' + pal.atmos[2] + ', 0.03)');
        glowGrad.addColorStop(1, 'rgba(' + pal.atmos[0] + ',' + pal.atmos[1] + ',' + pal.atmos[2] + ', 0)');
        ctx.fillStyle = glowGrad;
        ctx.beginPath();
        ctx.arc(cx, cy, glowR, 0, Math.PI * 2);
        ctx.fill();

        // ── Draw rings in front of planet ──
        if (planet.hasRings) _drawRingsV4(ctx, cx, cy, R, planet, true);

        return oc;
    }

    function _drawRingsV4(ctx, cx, cy, R, planet, frontHalf) {
        // Pixel-rendered ring bands with density variation and Cassini gap
        const rings = [
            { inner: 1.25, outer: 1.40, alpha: 0.22, color: [200, 185, 160] },
            { inner: 1.40, outer: 1.44, alpha: 0.03, color: [90, 80, 70] },  // Cassini gap
            { inner: 1.44, outer: 1.72, alpha: 0.18, color: [195, 180, 158] },
            { inner: 1.74, outer: 1.90, alpha: 0.08, color: [175, 165, 148] },
        ];
        const tilt = planet.ringTilt || 0.32;

        ctx.save();
        // Clip to front or back half
        if (frontHalf) {
            ctx.beginPath();
            ctx.rect(cx - R * 2.2, cy, R * 4.4, R * 2.2);
            ctx.clip();
        } else {
            ctx.beginPath();
            ctx.rect(cx - R * 2.2, cy - R * 2.2, R * 4.4, R * 2.2);
            ctx.clip();
        }

        rings.forEach(ring => {
            const bandSteps = 12;
            for (let b = 0; b < bandSteps; b++) {
                const t = b / bandSteps;
                const ringR = R * (ring.inner + t * (ring.outer - ring.inner));
                // Density varies — denser in middle of each band
                const densityT = Math.abs(t - 0.5) * 2;
                const opacity = ring.alpha * (1 - densityT * 0.4);
                // Add noise-based opacity variation for realism
                const noiseVar = 0.7 + _hash(b * 7, ring.inner * 100, planet.seed) * 0.6;

                ctx.globalAlpha = opacity * noiseVar;
                ctx.strokeStyle = 'rgba(' + ring.color[0] + ',' + ring.color[1] + ',' + ring.color[2] + ',1)';
                ctx.lineWidth = R * (ring.outer - ring.inner) / bandSteps * 0.85;
                ctx.beginPath();
                ctx.ellipse(cx, cy, ringR, ringR * tilt, 0, 0, Math.PI * 2);
                ctx.stroke();
            }
        });

        // Ring shadow on planet
        if (!frontHalf) {
            ctx.globalAlpha = 0.10;
            ctx.fillStyle = 'rgba(0,0,0,1)';
            ctx.beginPath();
            ctx.ellipse(cx, cy + R * 0.08, R * 1.55, R * tilt * 0.45, 0, 0, Math.PI);
            ctx.fill();
        }

        ctx.globalAlpha = 1;
        ctx.restore();
    }

    function renderPlanets(canvas) {
        _planetCanvas = canvas;
        const w = canvas.width, h = canvas.height;

        _planets = [];
        _planetCache = [];

        // Variety: not always the same types. Pool of 5 types, pick 1-2.
        const allTypes = ['gasGiant', 'gasGiant', 'iceGiant', 'rocky', 'rocky', 'earthLike'];
        const planetCount = Q.planets; // quality-dependent planet count

        for (let i = 0; i < planetCount; i++) {
            const type = allTypes[Math.floor(Math.random() * allTypes.length)];
            const palettes = PLANET_PALETTES[type];
            const palette = palettes[Math.floor(Math.random() * palettes.length)];
            // Feature planet is bigger (25-45px), secondary smaller (10-18px)
            const radius = i === 0 ? (25 + Math.random() * 20) : (10 + Math.random() * 8);

            // Position away from center (where UI content lives)
            let x, y, attempts = 0;
            do {
                x = w * (Math.random() < 0.5 ? 0.05 + Math.random() * 0.30 : 0.65 + Math.random() * 0.30);
                y = h * (0.1 + Math.random() * 0.8);
                attempts++;
            } while (attempts < 30 && _planets.some(p => Math.hypot(p.x - x, p.y - y) < (p.radius + radius) * 4));

            const hasRings = type === 'gasGiant' && Math.random() < 0.45;
            const hasStorm = type === 'gasGiant' && Math.random() < 0.5;

            _planets.push({
                type, radius, x, y, palette, hasRings,
                hasStorm,
                stormU: 0.3 + Math.random() * 0.4,
                stormV: 0.4 + Math.random() * 0.2,
                ringTilt: 0.25 + Math.random() * 0.2,
                lightAngle: -0.7,
                seed: Math.random() * 1000,
            });
        }

        // Pre-render each planet to offscreen canvas
        _planets.forEach(p => _planetCache.push(_renderPlanetToCache(p)));

        // Composite onto the main planet canvas
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, w, h);
        _planets.forEach((p, i) => {
            const cached = _planetCache[i];
            if (!cached) return;
            ctx.drawImage(cached, p.x - cached.width / 2, p.y - cached.height / 2);
        });
    }

    // ── Unified animation loop (single RAF, frame-throttled) ────
    function _startSpaceAnimation() {
        if (_spaceRAF) return; // already running
        let lastTime = 0;
        let time = 0;

        function frame(now) {
            _spaceRAF = requestAnimationFrame(frame);
            // Throttle to target FPS
            if (now - lastTime < FRAME_MS) return;
            lastTime = now;
            time += FRAME_MS / 1000;

            if (!_starfieldCanvas) return;
            const ctx = _starfieldCanvas.getContext('2d');
            const w = _starfieldCanvas.width, h = _starfieldCanvas.height;
            ctx.clearRect(0, 0, w, h);

            // 1. Blit the static star layer (one drawImage, very fast)
            if (_staticStarCanvas) {
                ctx.drawImage(_staticStarCanvas, 0, 0);
            }

            // 2. Overdraw the twinkler stars with animated brightness
            for (let i = 0; i < _twinklers.length; i++) {
                const s = _twinklers[i];
                const flicker = 0.5 + 0.5 * Math.sin(time * s.ts + s.tp);
                const alpha = s.ba * (1.0 - s.td + s.td * flicker);
                if (alpha < 0.1) continue;

                // Redraw this star brighter/dimmer via radial gradient (no shadowBlur)
                const glowR = s.sz * 3;
                const g = ctx.createRadialGradient(s.x, s.y, 0, s.x, s.y, glowR);
                g.addColorStop(0, 'rgba(' + s.r + ',' + s.g + ',' + s.b + ',' + (alpha * 0.9) + ')');
                g.addColorStop(0.3, 'rgba(' + s.r + ',' + s.g + ',' + s.b + ',' + (alpha * 0.3) + ')');
                g.addColorStop(1, 'rgba(' + s.r + ',' + s.g + ',' + s.b + ',0)');
                ctx.fillStyle = g;
                ctx.beginPath();
                ctx.arc(s.x, s.y, glowR, 0, Math.PI * 2);
                ctx.fill();
            }

            // 3. Shooting stars (rare, low cost)
            for (let i = _shootingStars.length - 1; i >= 0; i--) {
                const ss = _shootingStars[i];
                ss.life += FRAME_MS / 1000;
                const t = ss.life / ss.maxLife;
                if (t > 1) { _shootingStars.splice(i, 1); continue; }
                const headT = Math.min(1, t * 2);
                const hx = ss.sx + (ss.ex - ss.sx) * headT;
                const hy = ss.sy + (ss.ey - ss.sy) * headT;
                const tailT = Math.max(0, (t - 0.2) * 1.6);
                const tx = ss.sx + (ss.ex - ss.sx) * tailT;
                const ty = ss.sy + (ss.ey - ss.sy) * tailT;
                const fadeOut = t > 0.6 ? 1 - (t - 0.6) / 0.4 : 1;

                const grad = ctx.createLinearGradient(tx, ty, hx, hy);
                grad.addColorStop(0, 'rgba(255, 255, 255, 0)');
                grad.addColorStop(0.7, 'rgba(255, 250, 230, ' + (0.4 * fadeOut) + ')');
                grad.addColorStop(1, 'rgba(255, 255, 255, ' + (0.9 * fadeOut) + ')');
                ctx.strokeStyle = grad;
                ctx.lineWidth = ss.width;
                ctx.lineCap = 'round';
                ctx.beginPath();
                ctx.moveTo(tx, ty);
                ctx.lineTo(hx, hy);
                ctx.stroke();
            }
            ctx.globalAlpha = 1;
        }
        _spaceRAF = requestAnimationFrame(frame);
    }

    function _stopSpaceAnimation() {
        if (_spaceRAF) { cancelAnimationFrame(_spaceRAF); _spaceRAF = null; }
    }

    // ── Scene caching — avoid full re-render on tab switch ────
    // The DOM tree is cached and re-attached instead of rebuilt.
    let _cachedSpaceRoot = null;

    function injectSpaceBg() {
        // If we have a cached scene, just re-attach it
        if (_cachedSpaceRoot && _cachedSpaceRoot.parentNode !== document.body) {
            document.body.appendChild(_cachedSpaceRoot);
            document.body.classList.add('te-space-active');
            _startSpaceAnimation();
            if (_onEnter) _onEnter();
            return;
        }
        // If already attached, nothing to do
        if (_cachedSpaceRoot && _cachedSpaceRoot.parentNode === document.body) {
            document.body.classList.add('te-space-active');
            _startSpaceAnimation();
            if (_onEnter) _onEnter();
            return;
        }

        // First time: build the scene
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        const dpr = DPR;

        const root = document.createElement('div');
        root.id = 'te-space-root';

        const ORBIT_SCALE = 1.4;
        const orbit = document.createElement('div');
        orbit.className = 'te-space-orbit';
        orbit.style.cssText = 'position:absolute;pointer-events:none;' +
            'width:' + (ORBIT_SCALE * 100) + '%;height:' + (ORBIT_SCALE * 100) + '%;' +
            'left:' + (-(ORBIT_SCALE - 1) * 50) + '%;top:' + (-(ORBIT_SCALE - 1) * 50) + '%;';

        function makeCanvas(wMul, hMul) {
            const c = document.createElement('canvas');
            c.width = Math.floor(vw * ORBIT_SCALE * wMul * dpr);
            c.height = Math.floor(vh * ORBIT_SCALE * hMul * dpr);
            c.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;';
            return c;
        }

        // 1. CSS gradient nebula
        const nebula = document.createElement('div');
        nebula.className = 'te-nebula-layer';
        nebula.style.cssText += ';position:absolute;inset:0;width:100%;height:100%;';
        orbit.appendChild(nebula);

        // 2. Procedural canvas nebula — reduced resolution
        const nebulaCanvas = makeCanvas(Q.nebulaScale, Q.nebulaScale);
        nebulaCanvas.style.opacity = '0.5';
        nebulaCanvas.style.filter = 'blur(8px)';
        paintNebulaCanvas(nebulaCanvas);
        orbit.appendChild(nebulaCanvas);

        // 3. Planets (static, pre-rendered)
        const planetCanvas = makeCanvas(1, 1);
        renderPlanets(planetCanvas);
        orbit.appendChild(planetCanvas);

        // 4. Galaxies (static, pre-rendered — no animation loop)
        const galaxyCanvas = makeCanvas(1, 1);
        renderGalaxies(galaxyCanvas);
        orbit.appendChild(galaxyCanvas);

        // 5. Starfield (static base + animated twinkle overlay)
        const starfieldCanvas = makeCanvas(1, 1);
        initStarfield(starfieldCanvas);
        orbit.appendChild(starfieldCanvas);

        // 6. Nebula gas clouds
        for (let i = 0; i < 3; i++) {
            const blob = document.createElement('div');
            blob.className = 'te-nebula-blob';
            orbit.appendChild(blob);
        }

        root.appendChild(orbit);
        _cachedSpaceRoot = root;

        document.body.appendChild(root);
        document.body.classList.add('te-space-active');
        _startSpaceAnimation();
        if (_onEnter) _onEnter();
    }

    function removeSpaceBg() {
        if (_onLeave) _onLeave();
        _stopSpaceAnimation();
        // Don't destroy the DOM — just detach it for re-use
        if (_cachedSpaceRoot && _cachedSpaceRoot.parentNode) {
            _cachedSpaceRoot.remove();
        }
        document.body.classList.remove('te-space-active');
    }

    return { init: init, inject: injectSpaceBg, remove: removeSpaceBg };
})();
