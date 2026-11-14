/* The pixel bot mascot: the welcome hero's bot, and one small animated bot per
   agent in Build. `markup` is the drawing itself (it lived in
   chat_theme_controls.js as `botHTML`, unchanged); `html` boxes a scaled copy
   for an agent and lets css/thomas_bot.css animate it by state. */
(function () {
  'use strict';

  // ---------- Bot mascot (mirrors Bot.dc.html) ----------
  // The leg spans carry `tb-leg` classes so an agent's box can walk them; they
  // carry no style of their own, so every existing caller draws the same bot.
  function markup(p) {
    const flame = (p.flame === true || p.flame === 'true');
    const trim = p.trim, primary = p.primary, secondary = p.secondary;
    return `<div style="position: relative; width: 58px; height: 54px; image-rendering: pixelated; transform: scale(${p.scale}); transform-origin: center; filter: drop-shadow(0 8px 16px ${p.glow});">
        ${flame ? `<span style="position: absolute; top: 22px; left: 1px; width: 8px; height: 16px; background: linear-gradient(180deg, #5a6e8a, #3b4d66); border: 1px solid ${trim}; border-radius: 2px;"></span>
        <span style="position: absolute; top: 38px; left: -3px; width: 16px; height: 13px; background: radial-gradient(ellipse at 50% 0%, #ffd54f 0%, #ff9800 35%, #ff5722 65%, transparent 100%); border-radius: 0 0 50% 50%; filter: blur(0.6px); transform-origin: 50% 0; animation: bot-flame 0.22s linear infinite;"></span>` : ''}
        <span style="position: absolute; top: 2px; left: 16px; width: 24px; height: 14px; border: 2px solid ${trim}; background: ${primary};">
          <span class="tb-eye" style="position: absolute; top: 3px; left: 4px; width: 4px; height: 4px; background: #0b1726; transform-origin: center; animation: bot-blink 4.6s ease-in-out infinite; transition: translate .14s ease-out;"></span>
          <span class="tb-eye" style="position: absolute; top: 3px; left: 13px; width: 4px; height: 4px; background: #0b1726; transform-origin: center; animation: bot-blink 4.6s ease-in-out infinite; transition: translate .14s ease-out;"></span>
        </span>
        <span style="position: absolute; top: 18px; left: 13px; width: 30px; height: 18px; border: 2px solid ${trim}; background: linear-gradient(to bottom, ${primary} 0, ${primary} 44%, ${secondary} 45%, ${secondary} 100%);">
          <span style="position: absolute; top: 5px; left: 6px; width: 18px; height: 3px; background: rgba(11,23,38,0.5); border-radius: 2px;"></span>
        </span>
        <span class="tb-leg tb-leg-l" style="position: absolute; top: 36px; left: 18px; width: 8px; height: 10px; border: 2px solid ${trim}; background: ${secondary};"></span>
        <span class="tb-leg tb-leg-r" style="position: absolute; top: 36px; left: 32px; width: 8px; height: 10px; border: 2px solid ${trim}; background: ${secondary};"></span>
      </div>`;
  }

  // Agent colours: the lead is always the blue bot and the Verifier the amber
  // one, so the two roles every run has are recognisable at a glance. Everyone
  // else gets a pair picked by name, so "Scout" is the same colour on every run.
  const TRIM = '#0b0d12';
  const FIXED = {
    thomas: ['#9ad8ff', '#5aaeff'],
    lead: ['#9ad8ff', '#5aaeff'],
    verifier: ['#ffd98a', '#e2b25f'],
  };
  const PALETTE = [
    ['#c9cfdb', '#8f98a8'],
    ['#f0b3ff', '#c456c4'],
    ['#8ff0d2', '#34e0b0'],
    ['#ffc59a', '#f08a4b'],
    ['#c7b8ff', '#8b74f0'],
    ['#ffb3b3', '#e46a6a'],
    ['#d6f59a', '#9ccc3c'],
  ];
  const SIZES = { md: 0.44, sm: 0.3 };
  const STATES = new Set(['working', 'done', 'waiting', 'failed', 'idle']);

  function colours(seed) {
    const key = String(seed || '').trim().toLowerCase();
    if (FIXED[key]) return FIXED[key];
    // FNV-1a: tiny, stable across sessions, and spreads short names well.
    let hash = 0x811c9dc5;
    for (let i = 0; i < key.length; i += 1) {
      hash ^= key.charCodeAt(i);
      hash = Math.imul(hash, 0x01000193) >>> 0;
    }
    return PALETTE[hash % PALETTE.length];
  }

  function html(options) {
    const opts = options || {};
    const size = SIZES[opts.size] ? opts.size : 'md';
    const state = STATES.has(opts.state) ? opts.state : 'idle';
    const [primary, secondary] = colours(opts.seed);
    const bot = markup({ primary, secondary, trim: TRIM, glow: 'transparent', scale: SIZES[size], flame: false });
    return `<span class="tb-box tb-${size} is-${state}" aria-hidden="true"><span class="tb-motion">${bot}</span></span>`;
  }

  // The eyes follow the pointer when it comes close, and look ahead again when it leaves. They move with `translate`,
  // which is a property of its own, so the blink (a `transform` animation) carries on underneath. One listener for
  // every bot on the page, and one frame of work however fast the pointer moves.
  const REACH = 320, SHIFT_X = 2, SHIFT_Y = 1.5;
  let pointer = null, frame = 0;
  function look() {
    frame = 0;
    document.querySelectorAll('.tb-eye').forEach(eye => {
      const head = eye.parentElement.getBoundingClientRect();
      if (!pointer || !head.width) { eye.style.translate = ''; return; }
      const dx = pointer.x - (head.left + head.width / 2), dy = pointer.y - (head.top + head.height / 2);
      const far = Math.hypot(dx, dy);
      eye.style.translate = far > REACH || far < 1 ? '' : `${((dx / far) * SHIFT_X).toFixed(2)}px ${((dy / far) * SHIFT_Y).toFixed(2)}px`;
    });
  }
  function watch(next) {
    pointer = next;
    if (!frame && typeof requestAnimationFrame === 'function') frame = requestAnimationFrame(look);
  }
  const still = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (typeof document !== 'undefined' && document.addEventListener && !still) {
    document.addEventListener('pointermove', event => watch({ x: event.clientX, y: event.clientY }), { passive: true });
    document.addEventListener('pointerleave', () => watch(null));
  }

  window.ThomasBot = { markup, html, colours };
})();
