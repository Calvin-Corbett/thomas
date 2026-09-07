/* Live cost readout under the composer (frontier parity: Claude Code /cost,
 * Codex /status). Every V2 `done` event already carries run_usage and
 * session_usage (thomas/server/routes/chat_v2_usage.py); until 2026-09-05
 * nothing on the page read them. This module wraps the stream consumer the
 * page dereferences at send time, folds the receipts, prices them with the
 * same table and key order as CostTracker._get_price, and paints one line:
 *
 *   This reply 1.2k in · 340 out · ~$0.0111 · This chat 20.3k · ~$0.1245
 *
 * Dollars are an estimate from the server's declared pricing; without a
 * pricing table the line shows tokens only rather than an invented number.
 * The pure core is exposed as window.ThomasCostReadout for the node harness
 * (tests/web_node/cost_readout.mjs).
 */
(function () {
  'use strict';

  function nonneg(v) { var n = Number(v); return isFinite(n) && n > 0 ? Math.floor(n) : 0; }

  function usage(raw) {
    if (!raw || typeof raw !== 'object') return null;
    var p = nonneg(raw.prompt_tokens), c = nonneg(raw.completion_tokens), t = nonneg(raw.total_tokens);
    return { prompt_tokens: p, completion_tokens: c, total_tokens: Math.max(t, p + c), cached_prompt_tokens: Math.min(p, nonneg(raw.cached_prompt_tokens)) };
  }

  // Fold one stream event into the readout state. `model_runtime` names the
  // model that actually answered; `done` carries the per-turn and per-chat
  // token receipts. Everything else passes through untouched.
  function fold(state, evt) {
    var s = state || { model: '', provider: '', turn: null, session: null };
    if (!evt || typeof evt !== 'object') return s;
    if (evt.type === 'model_runtime') {
      var active = evt.runtime && evt.runtime.active;
      if (active && typeof active === 'object') {
        if (active.model) s.model = String(active.model);
        if (active.provider) s.provider = String(active.provider);
      }
    } else if (evt.type === 'done') {
      var turn = usage(evt.run_usage || evt.usage);
      var session = usage(evt.session_usage);
      if (turn) s.turn = turn;
      if (session) s.session = session;
      // The server says when no count reached it; a turn with no usage at
      // all is the same fact. Neither is a free reply.
      s.unreported = evt.usage_reported === false || (!!turn && turn.total_tokens === 0);
    }
    return s;
  }

  // Price a usage with the /api/spend/pricing table. Key order mirrors
  // CostTracker._get_price: provider:model, provider/model, both lowercased,
  // bare model, lowercased model, then the table's declared defaults.
  function priceRow(table, model, provider) {
    if (!table || typeof table !== 'object') return null;
    var m = String(model || '').trim(), p = String(provider || '').trim();
    var keys = [];
    if (p) keys.push(p + ':' + m, p + '/' + m, (p + ':' + m).toLowerCase(), (p + '/' + m).toLowerCase());
    keys.push(m, m.toLowerCase());
    for (var i = 0; i < keys.length; i++) {
      var row = table[keys[i]];
      if (row && typeof row === 'object' && isFinite(Number(row.input_per_1k))) return row;
    }
    var d = table.defaults;
    return d && typeof d === 'object' && isFinite(Number(d.input_per_1k)) ? d : null;
  }

  // Providers that run on this machine bill nothing. Pricing them at the
  // table's cloud defaults put a dollar figure on a free reply.
  var LOCAL_PROVIDERS = { ollama: true, lm_studio: true, vllm: true };
  function isLocal(provider) { return !!LOCAL_PROVIDERS[String(provider || '').trim().toLowerCase()]; }

  // The server flags a configured model served from this machine in its
  // pricing row; a provider name such as openai_compat cannot say so.
  function localRow(table, model, provider) {
    var row = priceRow(table, model, provider);
    return !!(row && row.local);
  }

  function price(u, table, model, provider) {
    if (isLocal(provider) || localRow(table, model, provider)) return null;
    var row = priceRow(table, model, provider);
    var use = usage(u);
    if (!row || !use) return null;
    return (use.prompt_tokens / 1000) * Number(row.input_per_1k || 0) + (use.completion_tokens / 1000) * Number(row.output_per_1k || 0);
  }

  function compact(n) {
    n = nonneg(n);
    if (n < 1000) return String(n);
    if (n < 1000000) return (Math.round(n / 100) / 10).toFixed(1).replace(/\.0$/, '') + 'k';
    return (Math.round(n / 10000) / 100).toFixed(2).replace(/\.?0+$/, '') + 'M';
  }

  function dollars(v, lowerBound) { return v == null ? '' : ' · ' + (lowerBound ? '≥$' : '~$') + v.toFixed(4); }

  // The chat receipt floors total_tokens to the persisted count while its
  // in/out split covers only the turns since the server started. Tokens the
  // split does not cover are priced at the input rate, and the figure is
  // shown as a lower bound rather than passed off as exact.
  function sessionPrice(s, table, model, provider) {
    var known = price(s, table, model, provider);
    if (known == null) return { usd: null, lowerBound: false };
    var covered = s.prompt_tokens + s.completion_tokens;
    var uncovered = Math.max(0, s.total_tokens - covered);
    if (!uncovered) return { usd: known, lowerBound: false };
    var row = priceRow(table, model, provider);
    return { usd: known + (uncovered / 1000) * Number(row.input_per_1k || 0), lowerBound: true };
  }

  function format(state, table) {
    if (!state || !state.turn) return '';
    if (state.unreported) return 'This reply · usage not reported by ' + (state.provider || 'the model server');
    var t = state.turn;
    var cached = t.cached_prompt_tokens ? ' (' + compact(t.cached_prompt_tokens) + ' cached)' : '';
    var local = isLocal(state.provider) || localRow(table, state.model, state.provider) ? ' · local, no charge' : '';
    var line = 'This reply ' + compact(t.prompt_tokens) + ' in' + cached + ' · ' + compact(t.completion_tokens) + ' out' + local + dollars(price(t, table, state.model, state.provider));
    if (state.session) {
      var sp = sessionPrice(state.session, table, state.model, state.provider);
      line += ' · This chat ' + compact(state.session.total_tokens) + dollars(sp.usd, sp.lowerBound);
    }
    return line;
  }

  var core = { fold: fold, price: price, format: format, compact: compact };
  if (typeof window !== 'undefined') window.ThomasCostReadout = core;
  if (typeof document === 'undefined') return;

  // ---- page wiring -------------------------------------------------------
  var state = null;
  var table = null;

  function anchor() {
    var box = document.querySelector('textarea[placeholder^="Message Thomas"], textarea[aria-label^="Message Thomas"]');
    if (!box) return null;
    return box.closest('form') || box.parentElement;
  }

  function host() {
    var el = document.getElementById('thomas-cost-readout');
    if (el) return el;
    var at = anchor();
    if (!at || !at.parentElement) return null;
    el = document.createElement('div');
    el.id = 'thomas-cost-readout';
    el.setAttribute('role', 'status');
    el.setAttribute('aria-live', 'polite');
    el.setAttribute('aria-label', 'Cost of this reply and this chat');
    el.title = 'Tokens from the model\'s own receipt; dollars estimated from Settings > Token Economy pricing. Click to open Token Economy.';
    el.style.cssText = 'font:11px/1.4 var(--font-mono, ui-monospace, monospace);color:var(--text-muted, #8a8f98);padding:2px 12px 0;cursor:pointer;user-select:none;';
    // The fast toggle (fast_mode.js) keeps a shared row under the composer;
    // join it when it exists so the two sit on one line, whichever loaded first.
    el.addEventListener('click', function () {
      var open = document.querySelector('[aria-label="Token Economy"], [data-space="token_economy"], a[href*="token_economy"]');
      if (open && typeof open.click === 'function') open.click();
    });
    var row = document.getElementById('thomas-composer-extras');
    if (row) { el.style.padding = '0'; row.appendChild(el); return el; }
    at.parentElement.insertBefore(el, at.nextSibling);
    return el;
  }

  function paint() {
    var el = host();
    if (!el) return;
    var line = format(state, table);
    el.textContent = line;
    el.hidden = !line;
  }

  function loadPricing() {
    if (typeof fetch !== 'function') return;
    fetch('/api/spend/pricing', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (body) { if (body && body.pricing) { table = body.pricing; paint(); } })
      .catch(function () { /* no pricing: tokens only */ });
  }

  // Wrap the consumer the page looks up per send. Same contract in, same
  // result out; this only observes the events on their way to the page.
  function wrap() {
    var consumer = window.ThomasChatStreamConsumer;
    if (!consumer || typeof consumer.consume !== 'function' || consumer.__costReadout) return;
    var inner = consumer.consume;
    consumer.consume = function (res, onEvent) {
      return inner.call(consumer, res, function (evt) {
        try { state = fold(state, evt); if (evt && evt.type === 'done') paint(); } catch (e) { /* the reply matters more than the readout */ }
        return onEvent(evt);
      });
    };
    consumer.__costReadout = true;
  }

  function start() { wrap(); loadPricing(); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
