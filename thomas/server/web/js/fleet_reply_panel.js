/*
 * Fleet inline reply panel (CAP-040) — "Add inline free-text reply/steer from
 * the fleet dashboard with delivery acknowledgement."
 *
 * Self-contained classic script (NOT an ES module — loaded via <script src>).
 * Defines exactly one global:
 *
 *     window.mountFleetReplyPanel(containerEl)
 *
 * Renders one row per live fleet session. Every row carries a FREE-TEXT reply
 * input + Send button; sending POSTs the steer to
 * /api/fleet/reply/sessions/{id}/reply and renders the returned DeliveryReceipt
 * inline on that row as a delivery acknowledgement badge (queued -> delivered ->
 * acked, or failed/undelivered). Replying to an unknown/ended session surfaces
 * the server's 4xx as a clear inline error instead of a crash.
 *
 * No libraries, no CDN, no build step: plain DOM APIs + fetch.
 */
(function () {
  'use strict';

  var API = '/api/fleet/reply';
  var STYLE_ID = 'fleet-reply-panel-styles';
  var MOUNT_FLAG = '__fleetReplyPanelMounted';
  var POLL_MS = 5000;

  var CSS = [
    '.frp-root{font:13px/1.45 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;color:#e7e5e4;',
    'background:#14161b;border:1px solid #2a2f38;border-radius:12px;padding:14px;box-sizing:border-box}',
    '.frp-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px}',
    '.frp-title{font-weight:700;font-size:13px;letter-spacing:.02em}',
    '.frp-sub{color:#98a2b3;font-size:11.5px;margin-top:2px}',
    '.frp-btn{cursor:pointer;border:1px solid #33507f;background:#1d4ed8;color:#fff;border-radius:8px;',
    'padding:7px 12px;font:600 12px/1 inherit}',
    '.frp-btn:hover{background:#2563eb}',
    '.frp-btn[disabled]{opacity:.5;cursor:default}',
    '.frp-btn-ghost{background:transparent;color:#c9d1d9;border-color:#39404d}',
    '.frp-btn-ghost:hover{background:#1e2229}',
    '.frp-list{display:flex;flex-direction:column;gap:8px}',
    '.frp-row{border:1px solid #2a2f38;border-radius:10px;padding:10px;background:#181b21}',
    '.frp-row-top{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px}',
    '.frp-sid{font-weight:600;font-size:12.5px;word-break:break-all}',
    '.frp-meta{color:#98a2b3;font-size:11px}',
    '.frp-form{display:flex;gap:8px;align-items:stretch}',
    '.frp-input{flex:1 1 auto;min-width:0;background:#0f1217;color:#e7e5e4;border:1px solid #39404d;',
    'border-radius:8px;padding:7px 10px;font:13px/1.4 inherit}',
    '.frp-input:focus{outline:none;border-color:#2563eb}',
    '.frp-ack{margin-top:8px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:11.5px}',
    '.frp-ack[hidden]{display:none}',
    '.frp-badge{display:inline-block;border-radius:999px;padding:3px 9px;font:700 10.5px/1.35 inherit;',
    'letter-spacing:.08em;text-transform:uppercase;border:1px solid transparent}',
    '.frp-badge.queued{background:#3a3411;color:#f6d365;border-color:#5c5220}',
    '.frp-badge.delivered{background:#0f3149;color:#7cc7f2;border-color:#1d5578}',
    '.frp-badge.acked{background:#123527;color:#5fd39b;border-color:#1e5f45}',
    '.frp-badge.failed{background:#3d1a1d;color:#f38b8b;border-color:#6d2a2f}',
    '.frp-badge.error{background:#3d1a1d;color:#f38b8b;border-color:#6d2a2f}',
    '.frp-badge.sending{background:#22262e;color:#b7bfcc;border-color:#39404d}',
    '.frp-ack-text{color:#b7bfcc;word-break:break-word}',
    '.frp-empty{color:#98a2b3;padding:14px;text-align:center;border:1px dashed #2f3540;border-radius:10px}',
    '.frp-error{color:#f38b8b;margin-bottom:8px;font-size:12px}',
    '.frp-error[hidden]{display:none}'
  ].join('');

  function injectStyles() {
    if (document.getElementById(STYLE_ID)) return;
    var style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = CSS;
    (document.head || document.documentElement).appendChild(style);
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = String(text);
    return node;
  }

  function jsonFetch(url, options) {
    var opts = options || {};
    opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
    opts.credentials = 'same-origin';
    return fetch(url, opts).then(function (resp) {
      return resp.text().then(function (raw) {
        var data = null;
        try { data = raw ? JSON.parse(raw) : null; } catch (e) { data = null; }
        return { status: resp.status, ok: resp.ok, data: data, raw: raw };
      });
    });
  }

  function errorMessage(result, fallback) {
    if (result && result.data && typeof result.data.error === 'string' && result.data.error) {
      return result.data.error;
    }
    if (result && typeof result.status === 'number' && result.status) {
      try { console.warn('fleet reply failed with HTTP', result.status); } catch (_e) {}
    }
    return fallback;
  }

  /* Human-readable delivery acknowledgement for one receipt. */
  function ackWording(receipt) {
    var state = (receipt && receipt.state) || 'unknown';
    if (state === 'acked') return 'Acknowledged by the session.';
    if (state === 'delivered') return 'Delivered to the session — awaiting acknowledgement.';
    if (state === 'queued') return 'Queued for delivery.';
    if (state === 'failed') {
      var why = receipt && receipt.reason ? ' (' + receipt.reason + ')' : '';
      return (receipt && receipt.undelivered ? 'Undelivered' : 'Delivery failed') + why + '.';
    }
    return 'Delivery state: ' + state + '.';
  }

  function badgeClass(state) {
    if (state === 'acked' || state === 'delivered' || state === 'queued' || state === 'failed') return state;
    return 'sending';
  }

  window.mountFleetReplyPanel = function mountFleetReplyPanel(containerEl) {
    var container = containerEl;
    if (typeof container === 'string') container = document.querySelector(container);
    if (!container || !container.appendChild) return null;
    if (container[MOUNT_FLAG]) return container[MOUNT_FLAG];

    injectStyles();
    container.textContent = '';

    var root = el('div', 'frp-root');
    var head = el('div', 'frp-head');
    var headLeft = el('div');
    headLeft.appendChild(el('div', 'frp-title', 'Fleet inline reply'));
    headLeft.appendChild(el('div', 'frp-sub', 'Type a steer for any live session — the delivery acknowledgement lands on its row.'));
    var refreshBtn = el('button', 'frp-btn frp-btn-ghost', 'Refresh');
    refreshBtn.type = 'button';
    head.appendChild(headLeft);
    head.appendChild(refreshBtn);

    var panelError = el('div', 'frp-error');
    panelError.hidden = true;

    var list = el('div', 'frp-list');

    root.appendChild(head);
    root.appendChild(panelError);
    root.appendChild(list);
    container.appendChild(root);

    var rows = Object.create(null);   // session_id -> row api
    var timer = null;
    var destroyed = false;

    function setPanelError(message) {
      if (message) {
        panelError.textContent = message;
        panelError.hidden = false;
      } else {
        panelError.textContent = '';
        panelError.hidden = true;
      }
    }

    function renderAck(row, kind, receipt, message) {
      row.ack.hidden = false;
      row.ack.textContent = '';
      var state = kind === 'receipt' ? ((receipt && receipt.state) || 'unknown') : kind;
      var badge = el('span', 'frp-badge ' + badgeClass(kind === 'receipt' ? state : kind), state);
      row.ack.appendChild(badge);
      var text = message != null ? message : ackWording(receipt);
      row.ack.appendChild(el('span', 'frp-ack-text', text));
      if (kind === 'receipt' && receipt && receipt.id) {
        row.ack.appendChild(el('span', 'frp-meta', receipt.id));
        if (receipt.state === 'delivered' || receipt.state === 'queued') {
          var ackBtn = el('button', 'frp-btn frp-btn-ghost', 'Mark acknowledged');
          ackBtn.type = 'button';
          ackBtn.addEventListener('click', function () {
            ackBtn.disabled = true;
            jsonFetch(API + '/receipts/' + encodeURIComponent(receipt.id) + '/ack', { method: 'POST' })
              .then(function (result) {
                if (result.ok && result.data && result.data.receipt) {
                  renderAck(row, 'receipt', result.data.receipt, null);
                } else {
                  ackBtn.disabled = false;
                  renderAck(row, 'error', null, errorMessage(result, 'Acknowledgement failed'));
                }
              })
              .catch(function (err) {
                ackBtn.disabled = false;
                renderAck(row, 'error', null, 'Acknowledgement request failed: ' + err);
              });
          });
          row.ack.appendChild(ackBtn);
        }
      }
    }

    function sendReply(row) {
      var text = row.input.value.trim();
      if (!text) {
        renderAck(row, 'error', null, 'Type a reply before sending.');
        row.input.focus();
        return;
      }
      row.sendBtn.disabled = true;
      row.input.disabled = true;
      renderAck(row, 'sending', null, 'Sending…');
      jsonFetch(API + '/sessions/' + encodeURIComponent(row.sessionId) + '/reply', {
        method: 'POST',
        body: JSON.stringify({ text: text })
      })
        .then(function (result) {
          row.sendBtn.disabled = false;
          row.input.disabled = false;
          var receipt = result.data && (result.data.receipt || result.data.acknowledgement);
          if (receipt) {
            // Delivered / acked / failed — the acknowledgement renders inline.
            renderAck(row, 'receipt', receipt, null);
            if (receipt.state === 'delivered' || receipt.state === 'acked') row.input.value = '';
            return;
          }
          renderAck(row, 'error', null, errorMessage(result, 'Reply was not delivered'));
        })
        .catch(function (err) {
          row.sendBtn.disabled = false;
          row.input.disabled = false;
          renderAck(row, 'error', null, 'Reply request failed: ' + err);
        });
    }

    function buildRow(sessionId) {
      var node = el('div', 'frp-row');
      node.setAttribute('data-session-id', sessionId);

      var top = el('div', 'frp-row-top');
      top.appendChild(el('span', 'frp-sid', sessionId));
      var meta = el('span', 'frp-meta', '');
      top.appendChild(meta);

      var form = el('form', 'frp-form');
      var input = el('input', 'frp-input');
      input.type = 'text';
      input.placeholder = 'Reply or steer this session…';
      input.setAttribute('aria-label', 'Reply to session ' + sessionId);
      var sendBtn = el('button', 'frp-btn', 'Send');
      sendBtn.type = 'submit';
      form.appendChild(input);
      form.appendChild(sendBtn);

      var ack = el('div', 'frp-ack');
      ack.hidden = true;

      node.appendChild(top);
      node.appendChild(form);
      node.appendChild(ack);

      var row = {
        sessionId: sessionId,
        node: node,
        meta: meta,
        input: input,
        sendBtn: sendBtn,
        ack: ack,
        touched: false
      };
      form.addEventListener('submit', function (event) {
        event.preventDefault();
        row.touched = true;
        sendReply(row);
      });
      return row;
    }

    function renderSessions(sessions) {
      var seen = Object.create(null);
      sessions.forEach(function (session) {
        var sid = String(session.id);
        seen[sid] = true;
        var row = rows[sid];
        if (!row) {
          row = buildRow(sid);
          rows[sid] = row;
          list.appendChild(row.node);
        }
        var pending = session.pending_count || 0;
        row.meta.textContent =
          (session.reply_count || 0) + ' replies · ' + (session.acked_count || 0) + ' acked' +
          (pending ? ' · ' + pending + ' pending' : '') +
          (session.failed_count ? ' · ' + session.failed_count + ' failed' : '');
        // Poll refresh must not clobber an acknowledgement the user just saw.
        if (!row.touched && session.last_receipt) renderAck(row, 'receipt', session.last_receipt, null);
      });
      Object.keys(rows).forEach(function (sid) {
        if (seen[sid]) return;
        if (rows[sid].node.parentNode) rows[sid].node.parentNode.removeChild(rows[sid].node);
        delete rows[sid];
      });
      var empty = list.querySelector('.frp-empty');
      if (!sessions.length) {
        if (!empty) list.appendChild(el('div', 'frp-empty', 'No live fleet sessions right now.'));
      } else if (empty && empty.parentNode) {
        empty.parentNode.removeChild(empty);
      }
    }

    function refresh() {
      return jsonFetch(API + '/sessions', { method: 'GET' })
        .then(function (result) {
          if (destroyed) return;
          if (!result.ok || !result.data || !Array.isArray(result.data.sessions)) {
            setPanelError(errorMessage(result, 'Could not load fleet sessions'));
            return;
          }
          setPanelError(null);
          renderSessions(result.data.sessions);
        })
        .catch(function (err) {
          if (!destroyed) setPanelError('Could not load fleet sessions: ' + err);
        });
    }

    refreshBtn.addEventListener('click', function () {
      refreshBtn.disabled = true;
      refresh().then(function () { refreshBtn.disabled = false; });
    });

    function startPolling() {
      if (timer) return;
      timer = setInterval(function () {
        if (document.hidden) return;
        refresh();
      }, POLL_MS);
    }

    var api = {
      refresh: refresh,
      element: root,
      destroy: function () {
        destroyed = true;
        if (timer) clearInterval(timer);
        timer = null;
        if (root.parentNode) root.parentNode.removeChild(root);
        try { delete container[MOUNT_FLAG]; } catch (e) { container[MOUNT_FLAG] = null; }
      }
    };
    container[MOUNT_FLAG] = api;

    refresh();
    startPolling();
    return api;
  };
})();
