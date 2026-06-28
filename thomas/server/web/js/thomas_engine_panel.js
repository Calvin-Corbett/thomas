/*
 * Thomas Engine panel — the Autonomy / Effort / Guardrails dials.
 *
 * Self-contained: renders a control panel and injects the selected Effort
 * (token_economy) into the chat request so picking "Exhaustive" actually fires
 * the full quality pipeline. Effort is the live, wired dial; Autonomy and
 * Guardrails are shown for the full control surface (Effort drives behavior today).
 */
(function () {
  'use strict';
  if (window.__thomasEnginePanelLoaded) return;
  window.__thomasEnginePanelLoaded = true;

  var LS_KEY = 'thomas_engine_v1';
  var DEFAULTS = { autonomy: 'auto', effort: 'diligent', guardrails: 'guarded' };

  function loadState() {
    try { return Object.assign({}, DEFAULTS, JSON.parse(localStorage.getItem(LS_KEY) || '{}')); }
    catch (e) { return Object.assign({}, DEFAULTS); }
  }
  var state = loadState();
  window.__thomasEngine = state;
  function save() {
    try { localStorage.setItem(LS_KEY, JSON.stringify(state)); } catch (e) {}
    window.__thomasEngine = state;
  }

  /* ── inject Effort into chat requests ─────────────────────────────────── */
  var _fetch = window.fetch;
  window.fetch = function (input, init) {
    try {
      var url = (typeof input === 'string') ? input : (input && input.url) || '';
      var isChat = /\/api\/(v2\/)?chat(\b|\?|$)/.test(url);
      var method = (init && init.method ? init.method : (input && input.method) || 'GET').toUpperCase();
      if (isChat && method === 'POST' && init && typeof init.body === 'string') {
        var body = JSON.parse(init.body);
        if (body && typeof body === 'object' && !Array.isArray(body)) {
          body.token_economy = state.effort;            // Brisk / Diligent / Exhaustive
          body.thomas_autonomy = state.autonomy;        // surfaced for the full control plane
          body.thomas_guardrails = state.guardrails;
          // Exhaustive implies real background work — ensure it dispatches.
          if (state.effort === 'exhaustive') body.mode = 'max';
          init = Object.assign({}, init, { body: JSON.stringify(body) });
        }
      }
    } catch (e) { /* never break a request */ }
    return _fetch.call(this, input, init);
  };

  /* ── styles ───────────────────────────────────────────────────────────── */
  var css = '' +
    '#tw-engine-btn{position:fixed;right:18px;bottom:18px;z-index:2147483000;cursor:pointer;' +
    'background:#1d4ed8;color:#fff;border:none;border-radius:22px;padding:10px 16px;font:600 12.5px/1 ui-sans-serif,system-ui,sans-serif;' +
    'box-shadow:0 4px 16px rgba(0,0,0,.35);letter-spacing:.02em}' +
    '#tw-engine-btn:hover{background:#2563eb}' +
    '#tw-engine-pop{position:fixed;right:18px;bottom:64px;z-index:2147483000;width:300px;display:none;' +
    'background:#15171c;color:#e7e5e4;border:1px solid #2b2f37;border-radius:14px;padding:14px 14px 12px;' +
    'box-shadow:0 12px 40px rgba(0,0,0,.5);font:13px/1.3 ui-sans-serif,system-ui,sans-serif}' +
    '#tw-engine-pop.open{display:block}' +
    '.tw-hd{font:700 10px/1 ui-sans-serif;letter-spacing:.16em;text-transform:uppercase;color:#9aa0aa;margin:2px 0 10px}' +
    '.tw-row{margin-bottom:12px}' +
    '.tw-lbl{font-size:11px;font-weight:600;color:#b8bcc4;margin-bottom:5px;display:flex;justify-content:space-between}' +
    '.tw-lbl small{font-weight:500;color:#7d828c}' +
    '.tw-seg{display:flex;border:1px solid #2b2f37;border-radius:9px;overflow:hidden}' +
    '.tw-seg button{flex:1;border:0;border-right:1px solid #2b2f37;background:transparent;color:#9aa0aa;' +
    'padding:7px 4px;font:600 11.5px/1 ui-sans-serif;cursor:pointer}' +
    '.tw-seg button:last-child{border-right:0}' +
    '.tw-seg button.on{background:#1d4ed8;color:#fff}' +
    '.tw-note{font-size:10.5px;color:#7d828c;border-top:1px solid #2b2f37;padding-top:9px;margin-top:4px}' +
    '.tw-note b{color:#cfd2d8}';
  var style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);

  /* ── build a segmented control ────────────────────────────────────────── */
  function seg(key, opts) {
    var wrap = document.createElement('div');
    wrap.className = 'tw-seg';
    opts.forEach(function (opt) {
      var b = document.createElement('button');
      b.textContent = opt.label;
      if (state[key] === opt.value) b.className = 'on';
      b.addEventListener('click', function () {
        state[key] = opt.value;
        save();
        Array.prototype.forEach.call(wrap.children, function (c) { c.className = ''; });
        b.className = 'on';
      });
      wrap.appendChild(b);
    });
    return wrap;
  }

  function row(label, hint, control) {
    var r = document.createElement('div');
    r.className = 'tw-row';
    var l = document.createElement('div');
    l.className = 'tw-lbl';
    l.innerHTML = '<span>' + label + '</span><small>' + hint + '</small>';
    r.appendChild(l);
    r.appendChild(control);
    return r;
  }

  function build() {
    var btn = document.createElement('button');
    btn.id = 'tw-engine-btn';
    btn.textContent = '◆ Thomas Engine';

    var pop = document.createElement('div');
    pop.id = 'tw-engine-pop';

    var hd = document.createElement('div');
    hd.className = 'tw-hd';
    hd.textContent = 'Thomas Engine · how it works';
    pop.appendChild(hd);

    pop.appendChild(row('Autonomy', 'acts alone', seg('autonomy', [
      { label: 'Chat', value: 'chat' }, { label: 'Assist', value: 'assist' },
      { label: 'Auto', value: 'auto' }, { label: 'Agent', value: 'agent' }
    ])));
    pop.appendChild(row('Effort', 'how good', seg('effort', [
      { label: 'Brisk', value: 'brisk' }, { label: 'Diligent', value: 'diligent' },
      { label: 'Exhaustive', value: 'exhaustive' }
    ])));
    pop.appendChild(row('Guardrails', 'which rules', seg('guardrails', [
      { label: 'Open', value: 'open' }, { label: 'Guarded', value: 'guarded' },
      { label: 'Fortress', value: 'fortress' }
    ])));

    var note = document.createElement('div');
    note.className = 'tw-note';
    note.innerHTML = '<b>Effort is live</b> — pick <b>Exhaustive</b> and send a build task to fire the full pipeline (staff crew → build → verify → review). Autonomy/Guardrails are shown for the full surface.';
    pop.appendChild(note);

    btn.addEventListener('click', function () { pop.classList.toggle('open'); });
    document.body.appendChild(btn);
    document.body.appendChild(pop);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', build);
  } else {
    build();
  }
})();
