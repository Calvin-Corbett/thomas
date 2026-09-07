/* A resting model is announced with a countdown (frontier parity: Codex's
 * rate-limit banner).
 *
 * The LLM client parks a profile after a 429; the turn either fails with a
 * generic error or, with failover, answers from another model. The page saw
 * neither the park nor its end. This module folds three sources: the runtime
 * receipt (a skipped attempt with cooldown_remaining_s and the model that
 * answered instead), the error text ("Rate-limit cooldown active for profile
 * 'x' (45s remaining)"), and GET /api/chat/cooldowns after any error. One
 * line under the composer counts down and clears itself. Pure core on
 * window.ThomasRateLimitBanner for the node harness
 * (tests/web_node/rate_limit_banner.mjs).
 */
(function () {
  'use strict';

  var ERROR_RE = /Rate-limit cooldown active for profile '([^']+)' \((\d+)s remaining\)/;

  function seconds(v) { var n = Number(v); return isFinite(n) && n > 0 ? n : 0; }

  // Fold one stream event into the banner state (null = nothing to show).
  function fold(state, evt, now) {
    if (!evt || typeof evt !== 'object') return state;
    if (evt.type === 'model_runtime') {
      var runtime = evt.runtime || {};
      var attempts = Array.isArray(runtime.attempts) ? runtime.attempts : [];
      var resting = null;
      for (var i = 0; i < attempts.length; i++) {
        var a = attempts[i] || {};
        var wait = seconds(a.cooldown_remaining_s);
        if ((a.status === 'skipped_rate_limited' || wait > 0) && (!resting || wait > resting.wait)) {
          resting = { profile: String(a.profile || a.model || ''), wait: wait };
        }
      }
      if (!resting) return state;
      var active = runtime.active || {};
      return { profile: resting.profile, until: now + resting.wait * 1000, via: String(active.model || active.profile || ''), kind: 'rate_limit' };
    }
    if (evt.type === 'error') {
      var m = ERROR_RE.exec(String(evt.error || evt.text || ''));
      if (!m) return state;
      return { profile: m[1], until: now + Number(m[2]) * 1000, via: '', kind: 'rate_limit' };
    }
    return state;
  }

  // Fold the cooldown route's rows: the longest wait is the one that matters;
  // an empty list clears the banner.
  function applyCooldowns(state, rows, now) {
    var list = Array.isArray(rows) ? rows : [];
    if (!list.length) return null;
    var top = null;
    for (var i = 0; i < list.length; i++) {
      var r = list[i] || {};
      var wait = seconds(r.remaining_s);
      if (wait > 0 && (!top || wait > top.wait)) top = { profile: String(r.profile || ''), wait: wait, kind: String(r.failure_type || 'server') };
    }
    if (!top) return null;
    return { profile: top.profile, until: now + top.wait * 1000, via: state && state.via ? state.via : '', kind: top.kind };
  }

  function clock(total) {
    var s = Math.max(0, Math.round(total));
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    var mm = h ? String(m).padStart(2, '0') : String(m);
    return (h ? h + ':' : '') + mm + ':' + String(r).padStart(2, '0');
  }

  function format(state, now) {
    if (!state || !state.profile) return '';
    var left = (state.until - now) / 1000;
    if (left <= 0) return '';
    var what = state.kind === 'rate_limit' ? 'is rate-limited' : 'is resting after errors';
    var tail = state.via ? 'replies come from ' + state.via + ' meanwhile' : 'Thomas will try again when it clears';
    return state.profile + ' ' + what + ' · back in ' + clock(left) + ' · ' + tail;
  }

  var core = { fold: fold, applyCooldowns: applyCooldowns, format: format, clock: clock };
  if (typeof window !== 'undefined') window.ThomasRateLimitBanner = core;
  if (typeof document === 'undefined') return;

  // ---- page wiring -------------------------------------------------------
  var state = null;
  var timer = null;

  function host() {
    var el = document.getElementById('thomas-rate-limit-banner');
    if (el) return el;
    var row = document.getElementById('thomas-composer-extras');
    if (!row) {
      var box = document.querySelector('textarea[placeholder^="Message Thomas"], textarea[aria-label^="Message Thomas"]');
      var at = box && (box.closest('form') || box.parentElement);
      if (!at || !at.parentElement) return null;
      row = document.createElement('div');
      row.id = 'thomas-composer-extras';
      row.style.cssText = 'display:flex;align-items:center;gap:10px;padding:2px 12px 0;font:11px/1.4 var(--font-mono, ui-monospace, monospace);color:var(--text-muted, #8a8f98);';
      at.parentElement.insertBefore(row, at.nextSibling);
    }
    el = document.createElement('div');
    el.id = 'thomas-rate-limit-banner';
    el.setAttribute('role', 'status');
    el.setAttribute('aria-live', 'polite');
    el.style.cssText = 'color:var(--warning, #d9a441);';
    el.hidden = true;
    row.appendChild(el);
    return el;
  }

  function paint() {
    var el = host();
    if (!el) return;
    var line = format(state, Date.now());
    el.textContent = line;
    el.hidden = !line;
    if (!line) { state = null; if (timer) { clearInterval(timer); timer = null; } }
    else if (!timer) timer = setInterval(paint, 1000);
  }

  function askServer() {
    if (typeof fetch !== 'function') return;
    fetch('/api/chat/cooldowns', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (body) { if (body) { state = applyCooldowns(state, body.cooldowns, Date.now()); paint(); } })
      .catch(function () { /* the banner is advisory */ });
  }

  function wrap() {
    var consumer = window.ThomasChatStreamConsumer;
    if (!consumer || typeof consumer.consume !== 'function' || consumer.__rateLimitBanner) return;
    var inner = consumer.consume;
    consumer.consume = function (res, onEvent) {
      return inner.call(consumer, res, function (evt) {
        try {
          var next = fold(state, evt, Date.now());
          if (next !== state) { state = next; paint(); }
          if (evt && evt.type === 'error') askServer();
        } catch (e) { /* the reply matters more than the banner */ }
        return onEvent(evt);
      });
    };
    consumer.__rateLimitBanner = true;
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wrap);
  else wrap();
})();
