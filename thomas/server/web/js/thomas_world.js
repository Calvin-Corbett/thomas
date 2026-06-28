/*
 * thomas_world.js — "living world" theme layer for the real Thomas frontend.
 *
 * Splices Calvin's "Thomas Chat" design into the live app WITHOUT touching the
 * runtime wiring: it only (a) injects animated background worlds behind #app,
 * (b) sets body.tcw-on + data-tcw-world so css/thomas_world.css can recolor the
 * existing surfaces via --c-* tokens, and (c) adds a world switcher to the top
 * bar. Five worlds: nebula (default) / dark / light / aurora / sandstone.
 * Persisted to localStorage('thomas_world'). Defensive: never throws into the
 * runtime; everything is wrapped and runs after DOMContentLoaded.
 */
(function () {
  "use strict";

  var WORLDS = ['nebula', 'dark', 'light', 'aurora', 'sandstone'];
  var META = {
    nebula:    { name: 'Nebula Core', tagline: 'Deep space — planets & flybys', sw: ['#0a0c18', '#1a1d33', '#8b8cff'] },
    dark:      { name: 'Dark',        tagline: 'Blueprint workshop, mono',       sw: ['#16181c', '#23262c', '#6e9bff'] },
    light:     { name: 'Light',       tagline: 'Daylight studio, airy',          sw: ['#ffffff', '#eef1f6', '#2f6bff'] },
    aurora:    { name: 'Aurora',      tagline: 'Tundra night, falling snow',     sw: ['#08161a', '#0f2a2a', '#34e0b0'] },
    sandstone: { name: 'Sandstone',   tagline: 'Warm desert, editorial serif',   sw: ['#f4ece0', '#e7d9c4', '#c0603c'] },
  };

  function loadWorld() {
    try { var w = localStorage.getItem('thomas_world'); if (w && META[w]) return w; } catch (e) {}
    return 'nebula';
  }
  function saveWorld(w) { try { localStorage.setItem('thomas_world', w); } catch (e) {} }

  // ---- bot mascot (from the design's Bot.dc.html), used in the worlds ----
  function botHTML(p) {
    var flame = (p.flame === true || p.flame === 'true');
    return '<div style="position:relative;width:58px;height:54px;image-rendering:pixelated;transform:scale(' + p.scale + ');transform-origin:center;filter:drop-shadow(0 8px 16px ' + p.glow + ');">' +
      (flame ? '<span style="position:absolute;top:22px;left:1px;width:8px;height:16px;background:linear-gradient(180deg,#5a6e8a,#3b4d66);border:1px solid ' + p.trim + ';border-radius:2px;"></span>' +
        '<span style="position:absolute;top:38px;left:-3px;width:16px;height:13px;background:radial-gradient(ellipse at 50% 0%,#ffd54f 0%,#ff9800 35%,#ff5722 65%,transparent 100%);border-radius:0 0 50% 50%;filter:blur(.6px);transform-origin:50% 0;animation:tcw-flame .22s linear infinite;"></span>' : '') +
      '<span style="position:absolute;top:2px;left:16px;width:24px;height:14px;border:2px solid ' + p.trim + ';background:' + p.primary + ';">' +
        '<span style="position:absolute;top:3px;left:4px;width:4px;height:4px;background:#0b1726;animation:tcw-eye 4.6s ease-in-out infinite;"></span>' +
        '<span style="position:absolute;top:3px;left:13px;width:4px;height:4px;background:#0b1726;animation:tcw-eye 4.6s ease-in-out infinite;"></span></span>' +
      '<span style="position:absolute;top:18px;left:13px;width:30px;height:18px;border:2px solid ' + p.trim + ';background:linear-gradient(to bottom,' + p.primary + ' 0,' + p.primary + ' 44%,' + p.secondary + ' 45%,' + p.secondary + ' 100%);">' +
        '<span style="position:absolute;top:5px;left:6px;width:18px;height:3px;background:rgba(11,23,38,.5);border-radius:2px;"></span></span>' +
      '<span style="position:absolute;top:36px;left:18px;width:8px;height:10px;border:2px solid ' + p.trim + ';background:' + p.secondary + ';"></span>' +
      '<span style="position:absolute;top:36px;left:32px;width:8px;height:10px;border:2px solid ' + p.trim + ';background:' + p.secondary + ';"></span></div>';
  }

  function worldsMarkup() {
    return '' +
      // NEBULA
      '<div class="tcw-world tcw-nebula">' +
        '<div style="position:absolute;inset:-12%;">' +
          '<div style="position:absolute;inset:0;background:radial-gradient(42% 46% at 24% 30%,rgba(124,108,255,.42),transparent 60%),radial-gradient(38% 42% at 80% 22%,rgba(64,196,224,.28),transparent 62%),radial-gradient(48% 50% at 64% 82%,rgba(196,86,196,.24),transparent 60%),radial-gradient(64% 64% at 50% 50%,rgba(38,28,86,.32),transparent 72%);animation:tcw-neb-drift 160s ease-in-out infinite alternate;"></div>' +
          '<div style="position:absolute;inset:0;background-image:radial-gradient(1.4px 1.4px at 12% 18%,rgba(255,255,255,.95),transparent),radial-gradient(1px 1px at 28% 64%,rgba(255,255,255,.7),transparent),radial-gradient(1.6px 1.6px at 47% 32%,rgba(214,224,255,.9),transparent),radial-gradient(1px 1px at 63% 72%,rgba(255,255,255,.65),transparent),radial-gradient(1.3px 1.3px at 78% 44%,rgba(255,255,255,.85),transparent),radial-gradient(1px 1px at 88% 78%,rgba(255,255,255,.6),transparent),radial-gradient(1px 1px at 38% 88%,rgba(255,255,255,.7),transparent),radial-gradient(1.2px 1.2px at 8% 52%,rgba(255,255,255,.8),transparent),radial-gradient(1px 1px at 55% 12%,rgba(255,255,255,.7),transparent),radial-gradient(1.5px 1.5px at 70% 58%,rgba(230,224,255,.9),transparent);background-size:360px 360px;animation:tcw-stars 150s linear infinite,tcw-twinkle 5s ease-in-out infinite;"></div>' +
        '</div>' +
        '<div style="position:absolute;right:6%;bottom:-90px;width:240px;height:240px;animation:tcw-planet 90s ease-in-out infinite;">' +
          '<div style="position:absolute;inset:0;border-radius:50%;background:radial-gradient(circle at 34% 28%,#8f8cff,#4b3fa6 58%,#221a52 100%);box-shadow:inset -26px -20px 50px rgba(0,0,0,.55),0 0 70px rgba(124,108,255,.22);"></div>' +
          '<div style="position:absolute;top:44%;left:-22%;width:144%;height:36px;border-radius:50%;border:3px solid rgba(173,160,255,.5);transform:rotate(-18deg) scaleY(.34);animation:tcw-spin 80s linear infinite;"></div>' +
        '</div>' +
        '<div style="position:absolute;left:9%;top:14%;width:86px;height:86px;border-radius:50%;background:radial-gradient(circle at 36% 30%,#7fe4cf,#2f8f93 60%,#16454f 100%);box-shadow:inset -10px -8px 22px rgba(0,0,0,.5),0 0 36px rgba(71,215,172,.25);animation:tcw-planet 70s ease-in-out infinite reverse;"></div>' +
          '<div style="position:absolute;top:17%;left:0;animation:tcw-fly-r 30s linear infinite;"><div style="animation:tcw-bob 4s ease-in-out infinite;">' + botHTML({ primary: '#bcd8ff', secondary: '#6f9bff', trim: '#0a0e1c', glow: 'rgba(120,150,255,.55)', scale: 0.62, flame: true }) + '</div></div>' +
          '<div style="position:absolute;top:64%;left:0;animation:tcw-fly-r 52s linear infinite;"><div style="animation:tcw-bob 6s ease-in-out infinite;">' + botHTML({ primary: '#a8e8ff', secondary: '#5ec4e6', trim: '#0a0e1c', glow: 'rgba(94,196,230,.45)', scale: 0.38, flame: true }) + '</div></div>' +
      '</div>' +
      // AURORA
      '<div class="tcw-world tcw-aurora">' +
        '<div style="position:absolute;top:-34%;left:-20%;width:140%;height:95%;background:linear-gradient(115deg,transparent 22%,rgba(52,224,176,.30) 42%,rgba(70,160,255,.22) 56%,transparent 76%);filter:blur(44px);animation:tcw-aurora 20s ease-in-out infinite;"></div>' +
        '<div style="position:absolute;top:-44%;left:-10%;width:130%;height:100%;background:linear-gradient(98deg,transparent 30%,rgba(120,255,214,.2) 50%,transparent 72%);filter:blur(54px);animation:tcw-aurora 30s ease-in-out infinite reverse;"></div>' +
        '<div style="position:absolute;bottom:0;left:0;right:0;height:200px;background:linear-gradient(180deg,transparent,rgba(6,30,30,.6));clip-path:polygon(0 100%,0 56%,12% 38%,24% 60%,38% 30%,52% 58%,66% 26%,80% 54%,92% 36%,100% 56%,100% 100%);"></div>' +
        '<div style="position:absolute;top:38%;left:0;animation:tcw-fly-r 46s linear infinite;"><div style="animation:tcw-bob 5.5s ease-in-out infinite;">' + botHTML({ primary: '#a8f0da', secondary: '#34e0b0', trim: '#06302a', glow: 'rgba(52,224,176,.5)', scale: 0.52, flame: true }) + '</div></div>' +
      '</div>' +
      // SANDSTONE
      '<div class="tcw-world tcw-sandstone">' +
        '<div style="position:absolute;top:12%;right:16%;width:130px;height:130px;border-radius:50%;background:radial-gradient(circle at 50% 50%,rgba(255,214,150,.95),rgba(240,170,90,.5) 60%,transparent 72%);animation:tcw-sun 14s ease-in-out infinite;"></div>' +
        '<div style="position:absolute;inset:0;background-image:radial-gradient(rgba(120,90,50,.05) 1px,transparent 1px);background-size:4px 4px;opacity:.7;"></div>' +
        '<div style="position:absolute;bottom:0;left:0;right:0;height:200px;background:linear-gradient(180deg,transparent,rgba(206,158,104,.28));clip-path:ellipse(75% 100% at 30% 130%);"></div>' +
        '<div style="position:absolute;bottom:0;left:0;right:0;height:150px;background:linear-gradient(180deg,transparent,rgba(176,120,68,.3));clip-path:ellipse(70% 100% at 80% 140%);"></div>' +
        '<div style="position:absolute;bottom:92px;left:0;animation:tcw-sled 56s linear infinite;"><div style="animation:tcw-bob 6s ease-in-out infinite;">' + botHTML({ primary: '#ffd6a7', secondary: '#ffad60', trim: '#3a2a1a', glow: 'rgba(192,96,60,.45)', scale: 0.5, flame: false }) + '</div></div>' +
      '</div>' +
      // DARK
      '<div class="tcw-world tcw-dark">' +
        '<div style="position:absolute;inset:0;background-image:linear-gradient(rgba(110,155,255,.06) 1px,transparent 1px),linear-gradient(90deg,rgba(110,155,255,.06) 1px,transparent 1px);background-size:44px 44px;"></div>' +
        '<div style="position:absolute;left:0;right:0;height:160px;background:linear-gradient(180deg,transparent,rgba(110,155,255,.06),transparent);animation:tcw-scan 11s linear infinite;"></div>' +
        '<div style="position:absolute;right:13%;top:26%;opacity:.85;animation:tcw-bob 6s ease-in-out infinite;">' + botHTML({ primary: '#9ad8ff', secondary: '#5aaeff', trim: '#0a0e16', glow: 'rgba(90,174,255,.3)', scale: 0.62, flame: false }) + '</div>' +
      '</div>' +
      // LIGHT
      '<div class="tcw-world tcw-light">' +
        '<div style="position:absolute;top:16%;left:0;width:200px;height:64px;border-radius:999px;background:radial-gradient(circle at 40% 50%,rgba(255,255,255,.95),rgba(225,233,245,.5) 70%,transparent);filter:blur(8px);animation:tcw-cloud 70s linear infinite;"></div>' +
        '<div style="position:absolute;top:40%;left:0;width:150px;height:52px;border-radius:999px;background:radial-gradient(circle at 40% 50%,rgba(255,255,255,.9),rgba(225,233,245,.4) 70%,transparent);filter:blur(8px);animation:tcw-cloud 96s linear infinite;animation-delay:-30s;"></div>' +
        '<div style="position:absolute;right:14%;top:24%;animation:tcw-hover 5s ease-in-out infinite;">' + botHTML({ primary: '#7db0ff', secondary: '#2f6bff', trim: '#16233a', glow: 'rgba(47,107,255,.28)', scale: 0.6, flame: false }) + '</div>' +
      '</div>';
  }

  function injectBackground() {
    if (document.getElementById('tcw-bg')) return;
    var bg = document.createElement('div');
    bg.id = 'tcw-bg';
    bg.setAttribute('aria-hidden', 'true');
    bg.innerHTML = worldsMarkup();
    document.body.insertBefore(bg, document.body.firstChild);
  }

  function applyWorld(world) {
    if (!META[world]) world = 'nebula';
    var b = document.body;
    b.classList.add('tcw-on');
    b.setAttribute('data-tcw-world', world);
    saveWorld(world);
    updateSwitcherLabel(world);
  }

  // ---- world switcher injected into the top bar (.nav-right) ----
  function updateSwitcherLabel(world) {
    var m = META[world]; if (!m) return;
    var name = document.getElementById('tcw-switch-name');
    if (name) name.textContent = m.name;
    var sw = [document.getElementById('tcw-sw1'), document.getElementById('tcw-sw2'), document.getElementById('tcw-sw3')];
    for (var i = 0; i < 3; i++) { if (sw[i]) sw[i].style.background = m.sw[i]; }
  }
  function buildSwitcher() {
    if (document.getElementById('tcw-switch')) return;
    var host = document.querySelector('.top-nav .nav-right') || document.querySelector('.top-nav');
    if (!host) return;
    var wrap = document.createElement('div');
    wrap.id = 'tcw-switch';
    wrap.setAttribute('data-tcw-switch', '1');
    wrap.style.cssText = 'position:relative;display:inline-flex;';
    wrap.innerHTML =
      '<button id="tcw-switch-btn" class="tcw-pill" title="Switch theme world" style="display:flex;align-items:center;gap:9px;padding:7px 11px 7px 9px;border-radius:10px;border:1px solid var(--c-border);background:var(--c-surface);color:var(--c-text);font-family:inherit;font-size:13px;font-weight:600;cursor:pointer;">' +
        '<span style="display:inline-flex;border-radius:6px;overflow:hidden;border:1px solid var(--c-border-2);">' +
          '<span id="tcw-sw1" style="width:11px;height:18px;"></span><span id="tcw-sw2" style="width:11px;height:18px;"></span><span id="tcw-sw3" style="width:11px;height:18px;"></span>' +
        '</span>' +
        '<span id="tcw-switch-name">Nebula Core</span>' +
        '<i class="ph ph-caret-down" style="font-size:12px;opacity:.6;"></i>' +
      '</button>' +
      '<div id="tcw-switch-menu" style="display:none;position:absolute;right:0;top:calc(100% + 8px);z-index:9999;width:268px;padding:8px;border-radius:14px;background:var(--c-menu-bg,var(--c-surface));border:1px solid var(--c-border-2);box-shadow:var(--c-shadow,0 18px 50px rgba(0,0,0,.5));">' +
        '<div style="font-size:10.5px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--c-muted);padding:6px 8px 8px;">Theme — each its own world</div>' +
        '<div id="tcw-switch-options"></div>' +
      '</div>';
    host.insertBefore(wrap, host.firstChild);
    document.getElementById('tcw-switch-btn').addEventListener('click', toggleMenu);
    renderMenu();
    document.addEventListener('mousedown', function (e) {
      var menu = document.getElementById('tcw-switch-menu');
      if (menu && menu.style.display === 'block' && !e.target.closest('[data-tcw-switch]')) menu.style.display = 'none';
    });
  }
  function toggleMenu() {
    var menu = document.getElementById('tcw-switch-menu');
    var open = menu.style.display === 'block';
    menu.style.display = open ? 'none' : 'block';
    if (!open) renderMenu();
  }
  function renderMenu() {
    var wrap = document.getElementById('tcw-switch-options'); if (!wrap) return;
    var cur = document.body.getAttribute('data-tcw-world') || 'nebula';
    wrap.innerHTML = '';
    WORLDS.forEach(function (key) {
      var m = META[key], sel = key === cur;
      var b = document.createElement('button');
      b.className = 'tcw-opt';
      b.style.cssText = 'width:100%;display:flex;align-items:center;gap:11px;padding:9px;border-radius:10px;border:1px solid ' + (sel ? 'var(--c-accent-line)' : 'transparent') + ';background:' + (sel ? 'var(--c-accent-soft)' : 'transparent') + ';color:var(--c-text);font-family:inherit;cursor:pointer;text-align:left;margin-bottom:2px;';
      b.innerHTML =
        '<span style="display:inline-flex;border-radius:7px;overflow:hidden;border:1px solid var(--c-border-2);flex:0 0 auto;box-shadow:0 2px 8px rgba(0,0,0,.25);">' +
          '<span style="width:14px;height:30px;background:' + m.sw[0] + ';"></span><span style="width:14px;height:30px;background:' + m.sw[1] + ';"></span><span style="width:14px;height:30px;background:' + m.sw[2] + ';"></span>' +
        '</span>' +
        '<span style="flex:1;min-width:0;"><span style="display:block;font-size:13.5px;font-weight:700;">' + m.name + '</span><span style="display:block;font-size:11.5px;color:var(--c-muted);">' + m.tagline + '</span></span>' +
        '<i class="ph ph-check" style="font-size:15px;color:var(--c-accent);opacity:' + (sel ? '1' : '0') + ';"></i>';
      b.addEventListener('click', function () {
        applyWorld(key);
        renderMenu();
        document.getElementById('tcw-switch-menu').style.display = 'none';
      });
      wrap.appendChild(b);
    });
  }

  function boot() {
    try {
      injectBackground();
      applyWorld(loadWorld());
      buildSwitcher();
      updateSwitcherLabel(document.body.getAttribute('data-tcw-world') || 'nebula');
    } catch (e) { if (window.console) console.warn('[thomas_world] init failed', e); }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
  // re-attach the switcher if the top bar gets re-rendered by the runtime
  try {
    var mo = new MutationObserver(function () { if (!document.getElementById('tcw-switch')) { try { buildSwitcher(); } catch (e) {} } });
    mo.observe(document.documentElement, { childList: true, subtree: true });
  } catch (e) {}
})();
