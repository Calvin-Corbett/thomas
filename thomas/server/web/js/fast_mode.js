/* Fast replies toggle (frontier parity: Claude Code /fast).
 *
 * The V2 chat route has always honoured `mode: "fast"` in the request body:
 * half the context budget, fewer tools offered, a lighter memory lookup
 * (thomas/core/token_economy.py, thomas/agent/loop_execution.py). The
 * composer never sent the key and nothing on the page could. The Tools menu
 * owns the visible switch; this module exposes its state and, while it is on,
 * marks each POST /api/v2/chat body with `mode: "fast"` on its way out.
 * A body that already names a mode is left alone: that is the page's
 * decision, not the toggle's. The choice persists per browser.
 *
 * Pure core on window.ThomasFastMode for the node harness
 * (tests/web_node/fast_mode.mjs): applyFast(bodyText, on), wrapFetch(inner, isOn).
 */
(function () {
  'use strict';

  var STORAGE_KEY = 'thomas.fastMode';

  function applyFast(bodyText, on) {
    if (!on || typeof bodyText !== 'string') return bodyText;
    var body;
    try { body = JSON.parse(bodyText); } catch (e) { return bodyText; }
    if (!body || typeof body !== 'object' || Array.isArray(body)) return bodyText;
    if (body.mode) return bodyText;
    body.mode = 'fast';
    return JSON.stringify(body);
  }

  function isChatSend(url, init) {
    var target = String(url || '');
    var method = String((init && init.method) || 'GET').toUpperCase();
    var path = target.replace(/^https?:\/\/[^/]+/, '').split('?')[0];
    return method === 'POST' && path === '/api/v2/chat';
  }

  function wrapFetch(inner, isOn) {
    return function (url, init) {
      if (isOn() && isChatSend(url, init) && init && typeof init.body === 'string') {
        var next = {};
        for (var k in init) if (Object.prototype.hasOwnProperty.call(init, k)) next[k] = init[k];
        next.body = applyFast(init.body, true);
        return inner.call(this, url, next);
      }
      return inner.call(this, url, init);
    };
  }

  var on = false;
  function remember() { try { localStorage.setItem(STORAGE_KEY, on ? '1' : '0'); } catch (e) { /* private window */ } }
  function isOn() { return on; }
  function setMode(value) {
    on = !!value;
    remember();
    if (typeof window !== 'undefined' && typeof window.CustomEvent === 'function') {
      window.dispatchEvent(new CustomEvent('thomas:fast-mode', { detail: { on: on } }));
    }
    return on;
  }

  var core = { applyFast: applyFast, wrapFetch: wrapFetch, isOn: isOn, setOn: setMode };
  if (typeof window !== 'undefined') window.ThomasFastMode = core;
  if (typeof document === 'undefined') return;

  // ---- page wiring -------------------------------------------------------
  try { on = localStorage.getItem(STORAGE_KEY) === '1'; } catch (e) { on = false; }
  core.isOn = function () { return on; };
  core.setOn = setMode;
  core.toggle = function () { return setMode(!on); };

  function start() {
    if (typeof window.fetch === 'function' && !window.fetch.__thomasFast) {
      var wrapped = wrapFetch(window.fetch, function () { return on; });
      wrapped.__thomasFast = true;
      window.fetch = wrapped;
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
