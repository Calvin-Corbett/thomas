/* Theme data for the Thomas Chat shell (THEMES vars payload + THEME_META
   extras). The vars payloads are DERIVED at load time from css/tokens.css
   (the single design-token source) via CSSOM, so editing tokens.css updates
   the chat shell automatically and drift is impossible. The baked values
   below are the offline fallback AND the key template; a mismatch between
   baked and derived logs one console.warn as a drift reminder. Loaded before
   chat.html's inline script, which consumes window.ThomasChatThemes. */
(function () {
  "use strict";
var THEMES = {
    nebula: { name: 'Nebula Core', tagline: 'Deep space — planets & flybys', sw: ['#0a0c18', '#1a1d33', '#8b8cff'],
      vars: { '--c-bg': '#070912', '--c-sidebar': 'rgba(11,14,26,0.72)', '--c-surface': 'rgba(255,255,255,0.04)', '--c-surface-2': 'rgba(255,255,255,0.08)', '--c-hover': 'rgba(255,255,255,0.06)', '--c-border': 'rgba(255,255,255,0.10)', '--c-border-2': 'rgba(255,255,255,0.17)', '--c-text': '#eef0fb', '--c-dim': 'rgba(238,240,251,0.66)', '--c-muted': 'rgba(238,240,251,0.42)', '--c-accent': '#8b8cff', '--c-accent-ink': '#0a0b16', '--c-accent-soft': 'rgba(139,140,255,0.16)', '--c-accent-line': 'rgba(139,140,255,0.45)', '--c-user-bg': 'rgba(124,118,235,0.20)', '--c-user-text': '#eef0fb', '--c-composer-bg': 'rgba(16,19,34,0.86)', '--c-shadow': '0 18px 50px rgba(2,4,12,0.55)', '--c-danger': '#ff9a9a', '--c-warn': '#e2b25f' } },
    dark: { name: 'Dark', tagline: 'Blueprint workshop, mono', sw: ['#16181c', '#23262c', '#6e9bff'],
      vars: { '--c-bg': '#16181c', '--c-sidebar': '#101216', '--c-surface': 'rgba(255,255,255,0.035)', '--c-surface-2': 'rgba(255,255,255,0.07)', '--c-hover': 'rgba(255,255,255,0.055)', '--c-border': 'rgba(255,255,255,0.09)', '--c-border-2': 'rgba(255,255,255,0.15)', '--c-text': '#e7e9ee', '--c-dim': 'rgba(231,233,238,0.64)', '--c-muted': 'rgba(231,233,238,0.40)', '--c-accent': '#6e9bff', '--c-accent-ink': '#0b1020', '--c-accent-soft': 'rgba(110,155,255,0.14)', '--c-accent-line': 'rgba(110,155,255,0.42)', '--c-user-bg': '#2a2e36', '--c-user-text': '#e7e9ee', '--c-composer-bg': '#1b1e23', '--c-shadow': '0 14px 40px rgba(0,0,0,0.45)', '--c-danger': '#ff9a9a', '--c-warn': '#e2b25f' } },
    light: { name: 'Light', tagline: 'Daylight studio, airy', sw: ['#ffffff', '#eef1f6', '#2b62f3'],
      vars: { '--c-bg': '#fafbfc', '--c-sidebar': '#f3f5f8', '--c-surface': '#fff', '--c-surface-2': '#f3f5f8', '--c-hover': 'rgba(20,30,60,0.05)', '--c-border': 'rgba(20,30,60,0.10)', '--c-border-2': 'rgba(20,30,60,0.16)', '--c-text': '#1c2330', '--c-dim': 'rgba(28,35,48,0.66)', '--c-muted': 'rgba(28,35,48,0.64)', '--c-accent': '#2b62f3', '--c-accent-ink': '#fff', '--c-accent-soft': 'rgba(43,98,243,0.10)', '--c-accent-line': 'rgba(43,98,243,0.42)', '--c-user-bg': '#eaeef6', '--c-user-text': '#1c2330', '--c-composer-bg': '#fff', '--c-shadow': '0 14px 40px rgba(20,30,60,0.12)', '--c-danger': '#b3261e', '--c-warn': '#a15c00' } },
    aurora: { name: 'Aurora', tagline: 'Tundra night, falling snow', sw: ['#08161a', '#0f2a2a', '#34e0b0'],
      vars: { '--c-bg': '#08151a', '--c-sidebar': 'rgba(9,22,26,0.78)', '--c-surface': 'rgba(120,255,220,0.04)', '--c-surface-2': 'rgba(120,255,220,0.08)', '--c-hover': 'rgba(120,255,220,0.06)', '--c-border': 'rgba(140,255,225,0.12)', '--c-border-2': 'rgba(140,255,225,0.20)', '--c-text': '#e7f3ef', '--c-dim': 'rgba(231,243,239,0.66)', '--c-muted': 'rgba(231,243,239,0.42)', '--c-accent': '#34e0b0', '--c-accent-ink': '#04211a', '--c-accent-soft': 'rgba(52,224,176,0.14)', '--c-accent-line': 'rgba(52,224,176,0.45)', '--c-user-bg': 'rgba(36,120,100,0.30)', '--c-user-text': '#e7f3ef', '--c-composer-bg': 'rgba(10,28,30,0.88)', '--c-shadow': '0 18px 50px rgba(0,12,10,0.55)', '--c-danger': '#ff9a9a', '--c-warn': '#e2b25f' } },
    sandstone: { name: 'Sandstone', tagline: 'Warm desert, editorial serif', sw: ['#f4ece0', '#e7d9c4', '#a84e30'],
      vars: { '--c-bg': '#f4ede1', '--c-sidebar': '#efe5d6', '--c-surface': '#fbf6ee', '--c-surface-2': '#f1e7d7', '--c-hover': 'rgba(80,52,28,0.06)', '--c-border': 'rgba(90,62,34,0.16)', '--c-border-2': 'rgba(90,62,34,0.26)', '--c-text': '#2f2a22', '--c-dim': 'rgba(47,42,34,0.70)', '--c-muted': 'rgba(47,42,34,0.68)', '--c-accent': '#a84e30', '--c-accent-ink': '#fdf6ee', '--c-accent-soft': 'rgba(168,78,48,0.12)', '--c-accent-line': 'rgba(168,78,48,0.45)', '--c-user-bg': '#ece0cd', '--c-user-text': '#2f2a22', '--c-composer-bg': '#fbf6ee', '--c-shadow': '0 14px 40px rgba(90,62,34,0.16)', '--c-danger': '#a33a28', '--c-warn': '#8a4b12' } },
  };
  
  var THEME_META = {
    nebula:    { bot: ['#9ad8ff', '#5aaeff', 'rgba(90,174,255,0.5)'],  trim: '#0d1117', fontHead: "'Manrope', system-ui, sans-serif", fontLabel: "'Manrope', system-ui, sans-serif", rCard: '14px', rComposer: '18px', menuBg: '#15142b', composerAccent: 'linear-gradient(90deg, transparent, rgba(139,140,255,0.7), transparent)', msgRule: '0', welcome: ['Where to, Captain?', 'Thomas understands the ask, acts within your boundaries, and shows you what changed.'] },
    dark:      { bot: ['#9ad8ff', '#5aaeff', 'rgba(90,174,255,0.30)'], trim: '#0d1117', fontHead: "'Manrope', system-ui, sans-serif", fontLabel: "'JetBrains Mono', ui-monospace, monospace", rCard: '8px', rComposer: '12px', menuBg: '#22252b', composerAccent: 'transparent', msgRule: '0', welcome: ['Ready when you are.', 'Describe the task. Thomas plans it, dispatches a worker, and reports back.'] },
    light:     { bot: ['#7db0ff', '#2f6bff', 'rgba(47,107,255,0.28)'], trim: '#16233a', fontHead: "'Manrope', system-ui, sans-serif", fontLabel: "'Manrope', system-ui, sans-serif", rCard: '16px', rComposer: '18px', menuBg: '#ffffff', composerAccent: 'transparent', msgRule: '0', welcome: ['How can I help?', 'Ask a question or describe something you want done — Thomas handles the rest.'] },
    aurora:    { bot: ['#a8f0da', '#34e0b0', 'rgba(52,224,176,0.45)'], trim: '#06302a', fontHead: "'Manrope', system-ui, sans-serif", fontLabel: "'Manrope', system-ui, sans-serif", rCard: '14px', rComposer: '18px', menuBg: '#0c2226', composerAccent: 'linear-gradient(90deg, transparent, rgba(52,224,176,0.7), rgba(70,160,255,0.5), transparent)', msgRule: '0', welcome: ['Good evening.', 'A calm place to think. Thomas takes the ask, hands it off, and reports back.'] },
    sandstone: { bot: ['#ffd6a7', '#ffad60', 'rgba(192,96,60,0.40)'],  trim: '#3a2a1a', fontHead: "'Newsreader', Georgia, serif", fontLabel: "'Newsreader', Georgia, serif", rCard: '12px', rComposer: '14px', menuBg: '#fbf6ee', composerAccent: 'transparent', msgRule: '2px solid var(--c-accent-line)', welcome: ['What shall we make?', 'An unhurried workspace. Thomas takes the ask, hands it off, and reports back.'] },
  };
  /* Derive the vars payloads from tokens.css so the stylesheet stays the
     single source of truth at runtime. Same-origin CSSOM read; any failure
     (missing sheet, changed shape) keeps the baked fallback. */
  function deriveThemeVarsFromTokens() {
    try {
      var keys = Object.keys(THEMES.nebula.vars);
      var sheet = null;
      for (var i = 0; i < document.styleSheets.length; i++) {
        var href = String(document.styleSheets[i].href || '');
        if (href.indexOf('/css/tokens.css') !== -1) { sheet = document.styleSheets[i]; break; }
      }
      if (!sheet) return null;
      var root = {};
      var overrides = { dark: {}, light: {}, aurora: {}, sandstone: {} };
      var rules = sheet.cssRules;
      for (var r = 0; r < rules.length; r++) {
        var rule = rules[r];
        if (!rule.selectorText || !rule.style) continue;
        var target = null;
        if (rule.selectorText.indexOf(':root') === 0) target = root;
        else {
          var m = rule.selectorText.match(/data-thomas-theme="(dark|light|aurora|sandstone)"/);
          if (m) target = overrides[m[1]];
        }
        if (!target) continue;
        for (var k = 0; k < keys.length; k++) {
          var v = rule.style.getPropertyValue(keys[k]);
          if (v) target[keys[k]] = v.trim();
        }
      }
      for (var k2 = 0; k2 < keys.length; k2++) {
        if (!root[keys[k2]]) return null;
      }
      var out = { nebula: root };
      ['dark', 'light', 'aurora', 'sandstone'].forEach(function (name) {
        var vars = {};
        keys.forEach(function (key) { vars[key] = overrides[name][key] || root[key]; });
        out[name] = vars;
      });
      return out;
    } catch (_e) { return null; }
  }

  var derived = deriveThemeVarsFromTokens();
  if (derived) {
    var norm = function (v) { return String(v).replace(/\s+/g, '').replace(/(^|[^0-9])0\./g, '$1.'); };
    var drift = [];
    Object.keys(THEMES).forEach(function (name) {
      Object.keys(THEMES[name].vars).forEach(function (key) {
        if (norm(THEMES[name].vars[key]) !== norm(derived[name][key])) drift.push(name + ' ' + key);
      });
      THEMES[name].vars = derived[name];
    });
    if (drift.length) {
      try { console.warn('chat_themes: baked fallback drifted from tokens.css (tokens.css wins):', drift.slice(0, 6).join(', ') + (drift.length > 6 ? ' +' + (drift.length - 6) + ' more' : '')); } catch (_e) {}
    }
  }

  /* The user overlay (thomas/server/overlay). Token records patch the stock
     payloads; overlay themes are appended in manifest order (the tab shell
     relays a theme choice by key index, so every document must build the
     same order) as full payloads derived from their stock parent; the five
     META fields that are real tokens follow their token records so
     chat.html's applyTheme (which re-applies META after vars) cannot clobber
     them. Runs once on the view the server put in the page, and again from
     overlay_runtime.js when a newer overlay is adopted. */
  var META_TOKENS = { '--font-head': 'fontHead', '--font-label': 'fontLabel', '--r-card': 'rCard', '--r-composer': 'rComposer', '--c-menu-bg': 'menuBg' };
  var STOCK_NAMES = ['nebula', 'dark', 'light', 'aurora', 'sandstone'];
  var THEME_NAME = /^[a-z][a-z0-9-]{1,31}$/;
  /* Theme strings end up inside chat.html's own theme menu and message markup
     (style attributes built as text), so a value is accepted only when it can
     neither escape a declaration nor open a tag - the server refuses the same
     shapes; this keeps a manifest written before that rule from rendering. */
  /* Two guards, by sink. A token or META value only ever reaches
     style.setProperty, where a double quote cannot escape anything, so it gets
     the same guard the server applies (font stacks carry double quotes). A
     string that chat.html builds INTO markup (swatches, msgRule, label,
     tagline) additionally refuses double quotes, backticks and backslashes. */
  var CSS_UNSAFE = /url\s*\(|expression\s*\(|@import|[;{}<>]/i;
  var ATTR_UNSAFE = /url\s*\(|expression\s*\(|@import|[;{}<>"`\\]/i;
  var ATTR_META = { msgRule: true, composerAccent: true };
  function safeValue(value, limit, pattern) {
    var text = String(value == null ? '' : value).trim();
    if (!text || text.length > (limit || 160)) return '';
    if ((pattern || ATTR_UNSAFE).test(text)) return '';
    return text;
  }
  function patchTokens(name, source) {
    Object.keys(source || {}).forEach(function (key) {
      var value = safeValue(source[key], 160, CSS_UNSAFE);
      if (!value) return;
      if (Object.prototype.hasOwnProperty.call(THEMES[name].vars, key)) THEMES[name].vars[key] = value;
      if (META_TOKENS[key] && THEME_META[name]) THEME_META[name][META_TOKENS[key]] = value;
    });
  }
  /* The stock payloads are snapshotted once and restored at the start of every
     merge, so a token or theme that was CLEARED since the last merge goes back
     to stock instead of lingering in the tables the shell repaints from. The
     objects keep their identity (keys replaced in place): chat.html and the
     workspace shell hold references to them. */
  var STOCK_SNAPSHOT = null;
  function pickStock(table) { var out = {}; STOCK_NAMES.forEach(function (n) { out[n] = table[n]; }); return out; }
  function replaceKeys(target, source) {
    Object.keys(target).forEach(function (k) { delete target[k]; });
    Object.keys(source).forEach(function (k) { target[k] = source[k]; });
  }
  function restoreStock() {
    if (!STOCK_SNAPSHOT) { STOCK_SNAPSHOT = JSON.parse(JSON.stringify({ themes: pickStock(THEMES), meta: pickStock(THEME_META) })); return; }
    STOCK_NAMES.forEach(function (name) {
      var t = STOCK_SNAPSHOT.themes[name];
      replaceKeys(THEMES[name].vars, t.vars);
      THEMES[name].name = t.name; THEMES[name].tagline = t.tagline; THEMES[name].sw = t.sw.slice();
      replaceKeys(THEME_META[name], JSON.parse(JSON.stringify(STOCK_SNAPSHOT.meta[name])));
    });
    Object.keys(THEMES).forEach(function (name) { if (THEMES[name] && THEMES[name].overlay) { delete THEMES[name]; delete THEME_META[name]; } });
  }
  function mergeOverlay(view) {
    restoreStock();
    if (!view || !view.present) return;
    var tokens = view.tokens || {};
    STOCK_NAMES.forEach(function (name) { patchTokens(name, tokens['*']); patchTokens(name, tokens[name]); });
    Object.keys(view.themes || {}).forEach(function (name) {
      var spec = view.themes[name] || {};
      if (STOCK_NAMES.indexOf(name) !== -1 || !THEME_NAME.test(name)) return;
      var parent = THEMES[spec.derives_from] && STOCK_NAMES.indexOf(spec.derives_from) !== -1 ? spec.derives_from : 'nebula';
      var vars = {};
      Object.keys(THEMES[parent].vars).forEach(function (key) { vars[key] = THEMES[parent].vars[key]; });
      var sw = Array.isArray(spec.swatches) && spec.swatches.length === 3 && spec.swatches.every(function (s) { return safeValue(s, 80); })
        ? spec.swatches.map(function (s) { return safeValue(s, 80); }) : THEMES[parent].sw.slice();
      var world = STOCK_NAMES.indexOf(spec.world) !== -1 ? spec.world : parent;
      THEMES[name] = { name: safeValue(spec.label, 80) || name, tagline: safeValue(spec.tagline, 80), sw: sw, vars: vars, overlay: true, world: world };
      var meta = {};
      Object.keys(THEME_META[parent] || {}).forEach(function (key) { meta[key] = THEME_META[parent][key]; });
      Object.keys(spec.meta || {}).forEach(function (key) {
        if (!Object.prototype.hasOwnProperty.call(meta, key)) return;
        var given = spec.meta[key];
        var guard = ATTR_META[key] ? ATTR_UNSAFE : CSS_UNSAFE;
        if (typeof meta[key] === 'string') { var text = safeValue(given, 160, guard); if (text) meta[key] = text; }
        else if (Array.isArray(meta[key]) && Array.isArray(given) && given.length === meta[key].length && given.every(function (v) { return safeValue(v); })) meta[key] = given.map(function (v) { return safeValue(v); });
      });
      THEME_META[name] = meta;
      patchTokens(name, tokens[name]);
    });
  }
  function readOverlayView() {
    if (window.ThomasOverlayView) return window.ThomasOverlayView;
    var el = document.getElementById('thomas-overlay-view');
    try { return el ? JSON.parse(el.textContent || '{}') : null; } catch (_e) { return null; }
  }
  mergeOverlay(readOverlayView());

  window.ThomasChatThemes = { THEMES: THEMES, THEME_META: THEME_META, mergeOverlay: mergeOverlay };
}());
