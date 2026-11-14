/* A resting model is announced with a countdown (frontier parity: Codex's
 * rate-limit banner).
 *
 * The LLM client parks a profile after a 429; the turn either fails with a
 * generic error or, with failover, answers from another model. The page saw
 * neither the park nor its end. This module folds three sources: the runtime
 * receipt (a skipped attempt with cooldown_remaining_s and the model that
 * answered instead), the error text ("Rate-limit cooldown active for profile
 * 'x' (45s remaining)"), and GET /api/chat/cooldowns on open and after any error. One
 * line under the composer counts down and clears itself. Pure core on
 * window.ThomasRateLimitBanner for the node harness
 * (tests/web_node/rate_limit_banner.mjs).
 *
 * A countdown is the truth only for a short burst. A park set by a spent
 * allowance is capped at ten minutes while the allowance itself can be out
 * until Saturday, so a ticking "back in 9:58" under the composer is the "wait
 * a moment" you were told in about. The cooldown route reads the refusal that
 * parked the profile (thomas/core/provider_cooldowns.py over
 * thomas/core/provider_limits.py) and sends the account and the reset already
 * worded; when a row carries those, this line names them instead of counting,
 * and lasts until the reset rather than until the park lifts. The route keeps
 * reporting such a row after its park has lifted, with remaining_s 0, and is
 * asked when the page opens, so a limit that started before this tab did is
 * still announced. The error text is not parsed for them here -- one reader
 * owns that, in Python -- so an error triggers the route fetch below too.
 *
 * A line that lasts until Saturday also has to end when the plan comes back
 * early, so a receipt that says a profile answered retires that profile's line
 * and re-asks the route.
 */
(function () {
  'use strict';

  var ERROR_RE = /Rate-limit cooldown active for profile '([^']+)' \((\d+)s remaining\)/;

  function seconds(v) { var n = Number(v); return isFinite(n) && n > 0 ? n : 0; }

  // The profile a runtime receipt says answered this turn, or ''. A spent-allowance
  // line now lasts until the reset the refusal named rather than until the park
  // lifts, and a provider can come back before then -- a reset read from the Claude
  // CLI's printed words is deliberately an hour late. The server stops claiming it
  // the moment the plan answers (llm_client clears the park on success); without
  // this the page would go on saying "has reached its usage limit" directly above
  // the reply that plan had just written.
  function answered(evt) {
    if (!evt || evt.type !== 'model_runtime') return '';
    var attempts = Array.isArray((evt.runtime || {}).attempts) ? evt.runtime.attempts : [];
    for (var i = 0; i < attempts.length; i++) {
      var a = attempts[i] || {};
      if (a.status === 'success') return String(a.profile || a.model || '');
    }
    return '';
  }

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
      if (!resting) {
        var back = answered(evt);
        return back && state && back === state.profile ? null : state;
      }
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

  // When the banner's line stops being true: the reset for a spent allowance,
  // otherwise the end of the park.
  function endsAt(row, now) {
    var at = Number(row && row.resets_at);
    if (isFinite(at) && at > 0) return at * 1000;
    return now + seconds(row && row.remaining_s) * 1000;
  }

  // Fold the cooldown route's rows: the one that lasts longest is the one that
  // matters; an empty list clears the banner.
  function applyCooldowns(state, rows, now) {
    var list = Array.isArray(rows) ? rows : [];
    if (!list.length) return null;
    var top = null;
    for (var i = 0; i < list.length; i++) {
      var r = list[i] || {};
      var until = endsAt(r, now);
      if (until > now && (!top || until > top.until)) {
        top = {
          profile: String(r.profile || ''),
          until: until,
          kind: String(r.failure_type || 'server'),
          account: String(r.account || ''),
          spent: !!r.spent,
          words: String(r.resets_words || ''),
          estimated: !!r.resets_estimated,
        };
      }
    }
    if (!top) return null;
    top.via = state && state.via ? state.via : '';
    return top;
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
    var tail = state.via ? 'replies come from ' + state.via + ' meanwhile' : '';
    if (state.spent) {
      var whose = (state.account ? state.account : state.profile) + ' has reached its usage limit';
      var when = state.words
        ? 'resets ' + state.words + (state.estimated ? ' (about)' : '')
        : 'the provider did not say when it resets';
      return whose + ' · ' + when + ' · ' + (tail || 'another model is needed until then');
    }
    var what = state.kind === 'rate_limit' ? 'is rate-limited' : 'is resting after errors';
    return state.profile + ' ' + what + ' · back in ' + clock(left) + ' · ' + (tail || 'Thomas will try again when it clears');
  }

  var core = { fold: fold, applyCooldowns: applyCooldowns, format: format, clock: clock, endsAt: endsAt, answered: answered };
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
          var before = state;
          var next = fold(before, evt, Date.now());
          if (next !== before) { state = next; paint(); }
          // The receipt and the error text can only say how long the park lasts.
          // Whenever either reports one, ask the route: it is the only place that
          // knows whether the allowance behind the park is out and until when --
          // including a turn a failover answered, where no error event arrives.
          var parked = next !== before && next && next.kind === 'rate_limit' && !next.spent;
          // A turn that answered is asked about too, while a line is up: the fold
          // above can only retire the line for the profile that answered, and the
          // route knows whether anything else is still out.
          if (evt && (evt.type === 'error' || parked || (before && answered(evt)))) askServer();
        } catch (e) { /* the reply matters more than the banner */ }
        return onEvent(evt);
      });
    };
    consumer.__rateLimitBanner = true;
  }

  // Asked once when the page opens, not only after a failed turn: a usage limit
  // outlives the ten-minute park that announced it, and outlives this page too.
  // Reopened during a limit that runs until Saturday, the composer said nothing
  // about it until you sent a message and were refused again.
  function start() {
    wrap();
    askServer();
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
