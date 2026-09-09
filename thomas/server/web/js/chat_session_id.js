/* Which chat is open: the one thing the injected panels must agree on.
 *
 * Questions (ask_user) and checklists (todo.write) belong to the chat that
 * raised them; the panels ask the server for that chat's rows only. The
 * page keeps its session id in a closure, so this module learns it from
 * the outside: the body of each POST /api/v2/chat (chat.html sends
 * session_id there, null for a new chat), the stream's `done` event (which
 * names the session the server created), and, failing both, the sidebar
 * row marked aria-current. Loaded before the panels; pure core on
 * window.ThomasChatSession for the node harness (tests/web_node/chat_session_id.mjs).
 */
(function () {
  'use strict';

  var known = '';

  function fromBody(bodyText) {
    if (typeof bodyText !== 'string') return undefined;
    try {
      var body = JSON.parse(bodyText);
      if (!body || typeof body !== 'object' || Array.isArray(body)) return undefined;
      if (!('session_id' in body)) return undefined;
      return body.session_id ? String(body.session_id) : '';
    } catch (e) { return undefined; }
  }

  function pathOf(url) { return String(url || '').replace(/^https?:\/\/[^/]+/, '').split('?')[0]; }
  function isPost(init) { return String((init && init.method) || 'GET').toUpperCase() === 'POST'; }
  function isChatSend(url, init) { return isPost(init) && pathOf(url) === '/api/v2/chat'; }
  // The page's session provider creates the session before the first send
  // (chat_turn_flow.js: POST /api/session/new); its response names it.
  function isSessionCreate(url, init) { return isPost(init) && pathOf(url) === '/api/session/new'; }

  // Remember the session the page sends; a new chat sends null and clears it
  // until the session-create response or the stream's `done` names the one
  // the server created.
  function wrapFetch(inner) {
    return function (url, init) {
      if (isChatSend(url, init) && init) {
        var sid = fromBody(init.body);
        if (sid !== undefined) known = sid;
      }
      var result = inner.call(this, url, init);
      if (isSessionCreate(url, init) && result && typeof result.then === 'function') {
        result.then(function (res) {
          if (!res || !res.ok || typeof res.clone !== 'function') return;
          return res.clone().json().then(function (data) {
            var sid = data && (data.session_id || (data.data && data.data.session_id));
            if (sid) known = String(sid);
          });
        }).catch(function () { /* not ours to fail */ });
      }
      return result;
    };
  }

  // The person opened another chat (a sidebar row) or started a new one: the
  // remembered id must not outlive that, or the panels keep showing the old
  // chat's rows (codex, 2026-09-05).
  function chatChanged(sid) { known = sid ? String(sid) : ''; }

  function fold(evt) {
    if (evt && typeof evt === 'object' && evt.type === 'done' && evt.session_id) known = String(evt.session_id);
    return known;
  }

  function current(doc) {
    if (known) return known;
    var d = doc || (typeof document !== 'undefined' ? document : null);
    var row = d && d.querySelector ? d.querySelector('[data-history-id][aria-current]') : null;
    return row && row.dataset && row.dataset.historyId ? String(row.dataset.historyId) : '';
  }

  var core = { current: current, wrapFetch: wrapFetch, fold: fold, chatChanged: chatChanged, remember: chatChanged };
  if (typeof window !== 'undefined') window.ThomasChatSession = core;
  if (typeof document === 'undefined') return;

  function start() {
    document.addEventListener('click', function (event) {
      var target = event.target && event.target.closest ? event.target : null;
      if (!target) return;
      var row = target.closest('[data-history-id]');
      if (row) { chatChanged(row.dataset.historyId); return; }
      if (target.closest('#tc-newchat')) chatChanged('');
    }, true);
    if (typeof window.fetch === 'function' && !window.fetch.__thomasSession) {
      var wrapped = wrapFetch(window.fetch);
      wrapped.__thomasSession = true;
      window.fetch = wrapped;
    }
    var consumer = window.ThomasChatStreamConsumer;
    if (consumer && typeof consumer.consume === 'function' && !consumer.__thomasSession) {
      var inner = consumer.consume;
      consumer.consume = function (res, onEvent) {
        return inner.call(consumer, res, function (evt) { try { fold(evt); } catch (e) { /* the reply matters more */ } return onEvent(evt); });
      };
      consumer.__thomasSession = true;
    }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
