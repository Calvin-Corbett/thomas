/*
 * Live run telemetry panel (CAP-137).
 *
 * An always-visible compact readout of the live run: TURNS, TOKENS, RATE
 * (tokens/min + turns/min) and COMPLETION PROJECTION (remaining + ETA). It
 * polls GET /api/run-telemetry/snapshot on an interval and updates the four
 * values in place -- no re-render, no flicker.
 *
 * Loaded as a plain classic script:
 *     <script src="/static/js/run_telemetry_panel.js"></script>
 *     <script>window.mountRunTelemetryPanel(document.getElementById('rt'));</script>
 *
 * Unknown is a first-class state. When the backend cannot measure a rate or
 * cannot project completion (no data yet, zero rate, no target) the snapshot
 * carries null -- and this panel prints the literal word "unknown". It never
 * prints NaN, Infinity, or a fabricated ETA: every numeric formatter runs the
 * value through Number.isFinite() first and falls back to "unknown".
 *
 * Self-contained: no libraries, no build step, plain DOM + fetch, own styles.
 */
(function () {
  'use strict';

  if (typeof window.mountRunTelemetryPanel === 'function') return;

  var UNKNOWN = 'unknown';
  var STYLE_ID = 'run-telemetry-panel-styles';
  var DEFAULT_BASE = '/api/run-telemetry';
  var DEFAULT_POLL_MS = 2000;
  var MIN_POLL_MS = 250;

  /* ── styles (injected once, all classes scoped with the rtp- prefix) ──── */

  /*
   * Theme-agnostic on purpose: the panel inherits the host's text color and
   * paints its surfaces with neutral translucency, so it reads correctly on a
   * dark workspace shell and on a light one without guessing at either.
   */
  var CSS = [
    '.rtp-root{--rtp-accent:#14b8a6;--rtp-line:rgba(128,128,128,.30);--rtp-fill:rgba(128,128,128,.10);',
    'font:13px/1.35 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;color:inherit;',
    'background:var(--rtp-fill);border:1px solid var(--rtp-line);',
    'border-radius:10px;padding:10px 12px;box-sizing:border-box;display:block}',
    '.rtp-root *{box-sizing:border-box}',
    '.rtp-head{display:flex;align-items:center;gap:8px;margin-bottom:8px}',
    '.rtp-title{font-size:11px;letter-spacing:.10em;text-transform:uppercase;opacity:.62;font-weight:600}',
    '.rtp-dot{width:7px;height:7px;border-radius:50%;background:var(--rtp-accent);flex:0 0 auto}',
    '.rtp-dot[data-state="stale"]{background:#f59e0b}',
    '.rtp-dot[data-state="error"]{background:#ef4444}',
    '.rtp-status{margin-left:auto;font-size:11px;opacity:.62}',
    '.rtp-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(118px,1fr));gap:8px}',
    '.rtp-cell{background:var(--rtp-fill);border:1px solid var(--rtp-line);',
    'border-radius:8px;padding:7px 9px;min-width:0}',
    '.rtp-label{font-size:10px;letter-spacing:.09em;text-transform:uppercase;opacity:.62;font-weight:600}',
    '.rtp-value{font-size:19px;font-weight:650;margin-top:2px;font-variant-numeric:tabular-nums;',
    'white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    '.rtp-value--sm{font-size:15px}',
    '.rtp-value[data-unknown="1"]{font-size:14px;font-weight:500;font-style:italic;opacity:.55}',
    '.rtp-sub{font-size:11px;opacity:.62;margin-top:1px;font-variant-numeric:tabular-nums;',
    'white-space:nowrap;overflow:hidden;text-overflow:ellipsis}',
    '.rtp-foot{display:flex;align-items:center;gap:6px;margin-top:8px;flex-wrap:wrap}',
    '.rtp-foot label{font-size:10px;letter-spacing:.08em;text-transform:uppercase;opacity:.62}',
    '.rtp-foot input{width:74px;background:transparent;border:1px solid var(--rtp-line);',
    'border-radius:6px;color:inherit;padding:3px 6px;font:inherit;font-size:12px}',
    '.rtp-foot button{background:rgba(20,184,166,.14);border:1px solid rgba(20,184,166,.45);color:var(--rtp-accent);',
    'border-radius:6px;padding:3px 10px;font:inherit;font-size:12px;cursor:pointer}',
    '.rtp-foot button:hover{background:rgba(20,184,166,.26)}'
  ].join('');

  function injectStyles(doc) {
    if (doc.getElementById(STYLE_ID)) return;
    var style = doc.createElement('style');
    style.id = STYLE_ID;
    style.textContent = CSS;
    (doc.head || doc.documentElement).appendChild(style);
  }

  /* ── formatting: every path is finite-checked, unknown otherwise ──────── */

  function isNum(v) {
    return typeof v === 'number' && isFinite(v);
  }

  function formatCount(v) {
    if (!isNum(v)) return UNKNOWN;
    var n = Math.round(v);
    if (Math.abs(n) < 1000) return String(n);
    if (Math.abs(n) < 1000000) return (n / 1000).toFixed(n % 1000 === 0 ? 0 : 1) + 'k';
    return (n / 1000000).toFixed(1) + 'M';
  }

  function formatRate(v) {
    if (!isNum(v)) return UNKNOWN;
    if (v >= 100) return String(Math.round(v));
    if (v >= 10) return v.toFixed(1);
    return v.toFixed(2);
  }

  function formatDuration(seconds) {
    if (!isNum(seconds) || seconds < 0) return UNKNOWN;
    var total = Math.round(seconds);
    if (total < 60) return total + 's';
    var mins = Math.floor(total / 60);
    var secs = total % 60;
    if (mins < 60) return mins + 'm ' + secs + 's';
    var hours = Math.floor(mins / 60);
    var remMins = mins % 60;
    if (hours < 24) return hours + 'h ' + remMins + 'm';
    return Math.floor(hours / 24) + 'd ' + (hours % 24) + 'h';
  }

  /* ── DOM helpers ──────────────────────────────────────────────────────── */

  function el(doc, tag, cls, text) {
    var node = doc.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function cell(doc, label, small) {
    var root = el(doc, 'div', 'rtp-cell');
    root.appendChild(el(doc, 'div', 'rtp-label', label));
    var value = el(doc, 'div', small ? 'rtp-value rtp-value--sm' : 'rtp-value', UNKNOWN);
    value.setAttribute('data-unknown', '1');
    var sub = el(doc, 'div', 'rtp-sub', '—');
    root.appendChild(value);
    root.appendChild(sub);
    return { root: root, value: value, sub: sub };
  }

  function setValue(node, text, unknown) {
    var next = unknown ? UNKNOWN : text;
    if (node.textContent !== next) node.textContent = next;
    var flag = unknown ? '1' : '0';
    if (node.getAttribute('data-unknown') !== flag) node.setAttribute('data-unknown', flag);
  }

  function setText(node, text) {
    if (node.textContent !== text) node.textContent = text;
  }

  /* ── mount ────────────────────────────────────────────────────────────── */

  window.mountRunTelemetryPanel = function (containerEl, options) {
    if (!containerEl || !containerEl.ownerDocument) return null;
    if (containerEl.__runTelemetryPanel) return containerEl.__runTelemetryPanel;

    var opts = options || {};
    var doc = containerEl.ownerDocument;
    var base = String(opts.baseUrl || containerEl.getAttribute('data-endpoint') || DEFAULT_BASE).replace(/\/+$/, '');
    var pollMs = Math.max(MIN_POLL_MS, Number(opts.pollMs) || DEFAULT_POLL_MS);

    injectStyles(doc);

    var root = el(doc, 'div', 'rtp-root');
    root.setAttribute('role', 'status');
    root.setAttribute('aria-live', 'polite');
    root.setAttribute('aria-label', 'Live run telemetry');

    var head = el(doc, 'div', 'rtp-head');
    var dot = el(doc, 'span', 'rtp-dot');
    dot.setAttribute('data-state', 'live');
    var status = el(doc, 'span', 'rtp-status', 'connecting…');
    head.appendChild(dot);
    head.appendChild(el(doc, 'span', 'rtp-title', 'Live run'));
    head.appendChild(status);

    var grid = el(doc, 'div', 'rtp-grid');
    var turns = cell(doc, 'Turns');
    var tokens = cell(doc, 'Tokens');
    // Rate and Projection carry units/prefixes, so they render one step smaller
    // to keep long readings ("ETA 12h 30m") from being clipped.
    var rate = cell(doc, 'Rate', true);
    var projection = cell(doc, 'Projection', true);
    grid.appendChild(turns.root);
    grid.appendChild(tokens.root);
    grid.appendChild(rate.root);
    grid.appendChild(projection.root);

    var foot = el(doc, 'div', 'rtp-foot');
    var turnsInput = el(doc, 'input');
    turnsInput.type = 'number';
    turnsInput.min = '0';
    turnsInput.placeholder = 'turns';
    turnsInput.setAttribute('aria-label', 'Target turns');
    var tokensInput = el(doc, 'input');
    tokensInput.type = 'number';
    tokensInput.min = '0';
    tokensInput.placeholder = 'tokens';
    tokensInput.setAttribute('aria-label', 'Target tokens');
    var apply = el(doc, 'button', null, 'Set target');
    apply.type = 'button';
    foot.appendChild(el(doc, 'label', null, 'Target'));
    foot.appendChild(turnsInput);
    foot.appendChild(tokensInput);
    foot.appendChild(apply);

    root.appendChild(head);
    root.appendChild(grid);
    root.appendChild(foot);
    containerEl.appendChild(root);

    var timer = null;
    var destroyed = false;
    var inFlight = false;

    function markStatus(state, text) {
      if (dot.getAttribute('data-state') !== state) dot.setAttribute('data-state', state);
      setText(status, text);
    }

    function renderSnapshot(snap) {
      if (!snap || typeof snap !== 'object') {
        markStatus('idle', 'Nothing recorded yet.');
        return;
      }

      // TURNS
      var doneTurns = isNum(snap.cumulative_turns) ? snap.cumulative_turns : null;
      setValue(turns.value, formatCount(doneTurns), doneTurns === null);
      var turnBits = [];
      if (isNum(snap.turns_in_progress) && snap.turns_in_progress > 0) {
        turnBits.push(snap.turns_in_progress + ' in progress');
      }
      if (isNum(snap.target_turns)) turnBits.push('of ' + formatCount(snap.target_turns));
      setText(turns.sub, turnBits.length ? turnBits.join(' · ') : 'no target');

      // TOKENS
      var doneTokens = isNum(snap.cumulative_tokens) ? snap.cumulative_tokens : null;
      setValue(tokens.value, formatCount(doneTokens), doneTokens === null);
      setText(tokens.sub, isNum(snap.target_tokens) ? 'of ' + formatCount(snap.target_tokens) : 'no target');

      // RATE (tokens/min primary, turns/min secondary)
      var tokensPerMin = isNum(snap.tokens_per_min) ? snap.tokens_per_min : null;
      setValue(rate.value, tokensPerMin === null ? UNKNOWN : formatRate(tokensPerMin) + ' tok/min', tokensPerMin === null);
      var turnsPerMin = isNum(snap.turns_per_min) ? snap.turns_per_min : null;
      setText(rate.sub, turnsPerMin === null ? UNKNOWN + ' turns/min' : formatRate(turnsPerMin) + ' turns/min');

      // COMPLETION PROJECTION (remaining + ETA)
      var etaKnown = snap.projection_known === true && isNum(snap.eta_seconds);
      setValue(projection.value, etaKnown ? 'ETA ' + formatDuration(snap.eta_seconds) : UNKNOWN, !etaKnown);
      var remBits = [];
      if (isNum(snap.remaining_turns)) remBits.push(formatCount(snap.remaining_turns) + ' turns');
      if (isNum(snap.remaining_tokens)) remBits.push(formatCount(snap.remaining_tokens) + ' tok');
      setText(
        projection.sub,
        remBits.length
          ? remBits.join(' · ') + ' left'
          : snap.projection_known === true
            ? 'no target'
            : 'remaining ' + UNKNOWN
      );

      if (isNum(snap.target_turns) && turnsInput.value === '') turnsInput.value = String(snap.target_turns);
      if (isNum(snap.target_tokens) && tokensInput.value === '') tokensInput.value = String(snap.target_tokens);

      markStatus('live', 'live');
    }

    function refresh() {
      if (destroyed || inFlight) return Promise.resolve(null);
      inFlight = true;
      return fetch(base + '/snapshot', {
        method: 'GET',
        headers: { Accept: 'application/json' },
        credentials: 'same-origin'
      })
        .then(function (res) {
          if (!res.ok) throw new Error('HTTP ' + res.status);
          return res.json();
        })
        .then(function (body) {
          if (destroyed) return null;
          renderSnapshot(body && body.snapshot);
          return body;
        })
        .catch(function (err) {
          if (!destroyed) markStatus('error', 'offline');
          return { error: String((err && err.message) || err) };
        })
        .then(function (out) {
          inFlight = false;
          return out;
        });
    }

    function readTargetField(input) {
      var raw = String(input.value || '').trim();
      if (raw === '') return null;
      var n = Number(raw);
      if (!isFinite(n) || n < 0) return null;
      return Math.round(n);
    }

    function applyTarget() {
      var payload = { turns: readTargetField(turnsInput), tokens: readTargetField(tokensInput) };
      if (payload.turns === null && payload.tokens === null) {
        markStatus('stale', 'target needs a number');
        return Promise.resolve(null);
      }
      return fetch(base + '/target', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(payload)
      })
        .then(function (res) {
          if (!res.ok) throw new Error('HTTP ' + res.status);
          return res.json();
        })
        .then(function (body) {
          if (!destroyed) renderSnapshot(body && body.snapshot);
          return body;
        })
        .catch(function () {
          if (!destroyed) markStatus('error', 'target rejected');
          return null;
        });
    }

    apply.addEventListener('click', applyTarget);

    function start() {
      if (destroyed || timer !== null) return;
      timer = setInterval(refresh, pollMs);
    }

    function stop() {
      if (timer !== null) {
        clearInterval(timer);
        timer = null;
      }
    }

    function destroy() {
      destroyed = true;
      stop();
      apply.removeEventListener('click', applyTarget);
      if (root.parentNode === containerEl) containerEl.removeChild(root);
      delete containerEl.__runTelemetryPanel;
    }

    var controller = {
      root: root,
      refresh: refresh,
      applyTarget: applyTarget,
      render: renderSnapshot,
      start: start,
      stop: stop,
      destroy: destroy
    };

    containerEl.__runTelemetryPanel = controller;
    refresh();
    start();
    return controller;
  };
})();
