/*
 * Worktree / subagent progress panel (CAP-139).
 *
 * Self-contained classic script (loaded with a plain <script src> tag -- NOT an
 * ES module). Defines a single global:
 *
 *     window.mountWorktreeProgressPanel(containerEl)
 *
 * which renders three live sections against /api/worktree-progress/*:
 *   1. PER-WORKTREE STATUS cards  -- active / idle / done, current node, elapsed
 *      (a running node shows elapsed-so-far, ticking between polls).
 *   2. TASK-GRAPH TIMING          -- per-node durations with the CRITICAL PATH
 *      visually distinguished (amber rail, amber bar, "CRITICAL" chip).
 *   3. COST ROLLUP                -- per worktree plus the overall total.
 *
 * Polls the snapshot endpoint and updates rows in place (keyed by id) so the
 * view never flickers or loses scroll position. No libraries, no build step.
 */
(function () {
  'use strict';

  if (window.mountWorktreeProgressPanel) return;

  var API_SNAPSHOT = '/api/worktree-progress/snapshot';
  var API_EVENTS = '/api/worktree-progress/events';
  var API_RESET = '/api/worktree-progress/reset';
  var POLL_MS = 2000;
  var STYLE_ID = 'wtp-panel-styles';

  var CSS = [
    '.wtp{font:13px/1.45 ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;color:#e7e5e4;',
    'background:#101216;border:1px solid #262a33;border-radius:14px;padding:16px;box-sizing:border-box}',
    '.wtp *{box-sizing:border-box}',
    '.wtp-top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px}',
    '.wtp-title{font:700 14px/1.2 inherit;margin:0;letter-spacing:.01em}',
    '.wtp-sub{font-size:11px;color:#828a97;margin:2px 0 0}',
    '.wtp-spacer{flex:1 1 auto}',
    '.wtp-btn{border:1px solid #333945;background:#181c23;color:#cbd2dd;border-radius:8px;',
    'padding:6px 11px;font:600 11.5px/1 inherit;cursor:pointer}',
    '.wtp-btn:hover{background:#212733;color:#fff}',
    '.wtp-btn.on{background:#1d4ed8;border-color:#1d4ed8;color:#fff}',
    '.wtp-msg{font-size:11px;color:#828a97;min-height:14px;margin-bottom:10px}',
    '.wtp-msg.err{color:#f87171}',
    '.wtp-sec{margin-bottom:18px}',
    '.wtp-sec:last-child{margin-bottom:0}',
    '.wtp-h{font:700 10px/1 inherit;letter-spacing:.16em;text-transform:uppercase;color:#8b93a1;',
    'margin:0 0 9px;display:flex;align-items:baseline;gap:8px}',
    '.wtp-h em{font-style:normal;font-weight:600;letter-spacing:.02em;text-transform:none;color:#6d7481}',
    '.wtp-empty{font-size:12px;color:#6d7481;font-style:italic;padding:6px 0}',
    '.wtp-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:10px}',
    '.wtp-card{background:#15181e;border:1px solid #272c36;border-left:3px solid #4b5563;',
    'border-radius:10px;padding:10px 11px}',
    '.wtp-card.s-active{border-left-color:#22c55e}',
    '.wtp-card.s-idle{border-left-color:#64748b}',
    '.wtp-card.s-done{border-left-color:#3b82f6}',
    '.wtp-card-hd{display:flex;align-items:center;gap:6px;margin-bottom:7px}',
    '.wtp-wt{font:700 12.5px/1.2 inherit;color:#f4f4f5;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '.wtp-badge{margin-left:auto;font:700 9.5px/1 inherit;letter-spacing:.1em;text-transform:uppercase;',
    'border-radius:999px;padding:4px 7px;background:#2b313b;color:#aab2bf}',
    '.wtp-badge.s-active{background:#0f3d24;color:#4ade80}',
    '.wtp-badge.s-idle{background:#2b313b;color:#9aa3b1}',
    '.wtp-badge.s-done{background:#12294d;color:#7dabf8}',
    '.wtp-kv{display:flex;justify-content:space-between;gap:8px;font-size:11.5px;color:#98a0ad;padding:1.5px 0}',
    '.wtp-kv b{font-weight:600;color:#dfe3e9;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '.wtp-kv b.run{color:#4ade80}',
    '.wtp-rows{display:flex;flex-direction:column;gap:5px}',
    '.wtp-row{display:grid;grid-template-columns:minmax(96px,1.1fr) 74px minmax(70px,2fr) auto;',
    'align-items:center;gap:9px;background:#15181e;border:1px solid #272c36;border-left:3px solid #303845;',
    'border-radius:8px;padding:7px 10px}',
    // border-color first: the shorthand must not clobber the amber critical-path rail.
    '.wtp-row.crit{background:#1d1a12;border-color:#4a3c1c;border-left-color:#f59e0b}',
    '.wtp-node{font:600 12px/1.2 inherit;color:#e9eaee;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '.wtp-node small{display:block;font-weight:500;font-size:10px;color:#767e8b}',
    '.wtp-dur{font:600 12px/1 ui-monospace,SFMono-Regular,Menlo,monospace;color:#cbd2dd;text-align:right}',
    '.wtp-bar{height:7px;border-radius:4px;background:#22272f;overflow:hidden}',
    '.wtp-bar i{display:block;height:100%;background:#3b82f6;border-radius:4px;transition:width .25s ease}',
    '.wtp-row.crit .wtp-bar i{background:#f59e0b}',
    '.wtp-chips{display:flex;gap:5px;justify-content:flex-end}',
    '.wtp-chip{font:700 9px/1 inherit;letter-spacing:.09em;text-transform:uppercase;border-radius:999px;padding:4px 6px}',
    '.wtp-chip.run{background:#0f3d24;color:#4ade80}',
    '.wtp-chip.crit{background:#4a3410;color:#fbbf24}',
    '.wtp-cp{font-size:11.5px;color:#a1a8b4;background:#1d1a12;border:1px solid #4a3c1c;border-radius:8px;',
    'padding:7px 10px;margin-bottom:9px;word-break:break-word}',
    '.wtp-cp b{color:#fbbf24;font-weight:700}',
    '.wtp-cost{display:flex;flex-direction:column;gap:4px}',
    '.wtp-cost-row{display:grid;grid-template-columns:1fr auto auto;gap:12px;align-items:center;',
    'font-size:12px;color:#b3bac5;padding:6px 10px;background:#15181e;border:1px solid #272c36;border-radius:8px}',
    '.wtp-cost-row.total{background:#12203a;border-color:#1e3a63;color:#dbe6f7;font-weight:700}',
    '.wtp-money{font:600 12px/1 ui-monospace,SFMono-Regular,Menlo,monospace;color:#f4f4f5}',
    '.wtp-tok{font-size:11px;color:#7d8593;min-width:72px;text-align:right}'
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
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function fmtDur(seconds) {
    var s = Number(seconds);
    if (!isFinite(s) || s < 0) s = 0;
    if (s < 1) return (Math.round(s * 1000)) + 'ms';
    if (s < 60) return s.toFixed(1) + 's';
    var m = Math.floor(s / 60);
    var rest = s - m * 60;
    if (m < 60) return m + 'm ' + rest.toFixed(0) + 's';
    return Math.floor(m / 60) + 'h ' + (m % 60) + 'm';
  }

  function fmtMoney(value) {
    var v = Number(value);
    if (!isFinite(v)) v = 0;
    return '$' + v.toFixed(4);
  }

  function fmtTokens(value) {
    var v = Number(value);
    if (!isFinite(v)) v = 0;
    return v.toLocaleString() + ' tok';
  }

  function kv(parent, label) {
    var row = el('div', 'wtp-kv');
    row.appendChild(el('span', null, label));
    var val = el('b', null, '--');
    row.appendChild(val);
    parent.appendChild(row);
    return val;
  }

  /* ── section 1: per-worktree status cards ─────────────────────────────── */
  function WorktreeCards(host) {
    var cards = {};

    function card() {
      var root = el('div', 'wtp-card');
      var hd = el('div', 'wtp-card-hd');
      var name = el('span', 'wtp-wt');
      var badge = el('span', 'wtp-badge');
      hd.appendChild(name);
      hd.appendChild(badge);
      root.appendChild(hd);
      return {
        root: root,
        name: name,
        badge: badge,
        current: kv(root, 'current node'),
        elapsed: kv(root, 'elapsed'),
        nodes: kv(root, 'nodes'),
        cost: kv(root, 'cost')
      };
    }

    return function render(worktrees) {
      var seen = {};
      worktrees.forEach(function (w) {
        var id = String(w.worktree_id);
        seen[id] = true;
        var c = cards[id];
        if (!c) {
          c = cards[id] = card();
          c.root.setAttribute('data-worktree', id);
          host.appendChild(c.root);
        }
        var state = String(w.state || 'idle');
        c.root.className = 'wtp-card s-' + state;
        c.badge.className = 'wtp-badge s-' + state;
        c.name.textContent = id;
        c.name.title = id;
        c.badge.textContent = state;
        var running = (w.running_nodes || []).length > 0;
        c.current.textContent = w.current_node ? String(w.current_node) : '--';
        c.current.className = running ? 'run' : '';
        c.elapsed.textContent = fmtDur(w.elapsed_s) + (running ? ' (running)' : '');
        c.elapsed.className = running ? 'run' : '';
        c.nodes.textContent = String(w.node_count || 0);
        c.cost.textContent = fmtMoney(w.total_cost) + ' / ' + fmtTokens(w.total_tokens);
      });
      Object.keys(cards).forEach(function (id) {
        if (!seen[id]) {
          host.removeChild(cards[id].root);
          delete cards[id];
        }
      });
      return worktrees.length;
    };
  }

  /* ── section 2: task-graph timing with critical path ──────────────────── */
  function TimingRows(host) {
    var rows = {};

    function row() {
      var root = el('div', 'wtp-row');
      var node = el('div', 'wtp-node');
      var label = el('span');
      var wt = el('small');
      node.appendChild(label);
      node.appendChild(wt);
      var dur = el('div', 'wtp-dur');
      var bar = el('div', 'wtp-bar');
      var fill = el('i');
      bar.appendChild(fill);
      var chips = el('div', 'wtp-chips');
      root.appendChild(node);
      root.appendChild(dur);
      root.appendChild(bar);
      root.appendChild(chips);
      return { root: root, label: label, wt: wt, dur: dur, fill: fill, chips: chips };
    }

    return function render(timings, criticalIds) {
      var max = 0;
      timings.forEach(function (t) {
        var d = Number(t.duration_s) || 0;
        if (d > max) max = d;
      });
      var seen = {};
      timings.forEach(function (t) {
        var id = String(t.node_id);
        seen[id] = true;
        var r = rows[id];
        if (!r) {
          r = rows[id] = row();
          r.root.setAttribute('data-node', id);
          host.appendChild(r.root);
        }
        var isCrit = !!criticalIds[id];
        r.root.className = isCrit ? 'wtp-row crit' : 'wtp-row';
        r.label.textContent = id;
        r.wt.textContent = String(t.worktree_id || '');
        var d = Number(t.duration_s) || 0;
        r.dur.textContent = fmtDur(d);
        r.fill.style.width = (max > 0 ? Math.max(3, (d / max) * 100) : 3) + '%';
        while (r.chips.firstChild) r.chips.removeChild(r.chips.firstChild);
        if (t.running) r.chips.appendChild(el('span', 'wtp-chip run', 'running'));
        if (isCrit) r.chips.appendChild(el('span', 'wtp-chip crit', 'critical'));
      });
      Object.keys(rows).forEach(function (id) {
        if (!seen[id]) {
          host.removeChild(rows[id].root);
          delete rows[id];
        }
      });
      return timings.length;
    };
  }

  /* ── section 3: cost rollup ───────────────────────────────────────────── */
  function CostRows(host) {
    var rows = {};

    function row(cls) {
      var root = el('div', cls);
      var name = el('span');
      var money = el('span', 'wtp-money');
      var tok = el('span', 'wtp-tok');
      root.appendChild(name);
      root.appendChild(tok);
      root.appendChild(money);
      return { root: root, name: name, money: money, tok: tok };
    }

    var total = row('wtp-cost-row total');

    return function render(cost) {
      var perWt = cost.per_worktree || {};
      var perTok = cost.tokens_per_worktree || {};
      var ids = Object.keys(perWt).sort();
      var seen = {};
      ids.forEach(function (id) {
        seen[id] = true;
        var r = rows[id];
        if (!r) {
          r = rows[id] = row('wtp-cost-row');
          r.root.setAttribute('data-cost-worktree', id);
          host.appendChild(r.root);
        }
        r.name.textContent = id;
        r.money.textContent = fmtMoney(perWt[id]);
        r.tok.textContent = fmtTokens(perTok[id] || 0);
      });
      Object.keys(rows).forEach(function (id) {
        if (!seen[id]) {
          host.removeChild(rows[id].root);
          delete rows[id];
        }
      });
      total.name.textContent = 'TOTAL (' + ids.length + ' worktree' + (ids.length === 1 ? '' : 's') + ')';
      total.money.textContent = fmtMoney(cost.total);
      total.tok.textContent = fmtTokens(cost.tokens_total);
      host.appendChild(total.root); // keep the total pinned to the bottom
      return ids.length;
    };
  }

  /* ── demo seed: makes the panel usable with no live subagents ─────────── */
  function demoEvents() {
    var t0 = Math.floor(Date.now() / 1000) - 120;
    return [
      { event: 'node_started', worktree_id: 'wt-alpha', node_id: 'plan', at: t0 },
      { event: 'node_finished', node_id: 'plan', at: t0 + 12, tokens: 4200, cost: 0.084 },
      { event: 'node_started', worktree_id: 'wt-alpha', node_id: 'build', depends_on: ['plan'], at: t0 + 12 },
      { event: 'node_finished', node_id: 'build', at: t0 + 60, tokens: 18500, cost: 0.371 },
      { event: 'node_started', worktree_id: 'wt-beta', node_id: 'docs', depends_on: ['plan'], at: t0 + 12 },
      { event: 'node_finished', node_id: 'docs', at: t0 + 30, tokens: 6100, cost: 0.122 },
      { event: 'node_started', worktree_id: 'wt-alpha', node_id: 'verify', depends_on: ['build', 'docs'], at: t0 + 60 },
      { event: 'register_worktree', worktree_id: 'wt-gamma' }
    ];
  }

  /* ── mount ────────────────────────────────────────────────────────────── */
  window.mountWorktreeProgressPanel = function (containerEl) {
    if (!containerEl || !containerEl.appendChild) {
      throw new Error('mountWorktreeProgressPanel: a container element is required');
    }
    if (containerEl.__wtpPanel) return containerEl.__wtpPanel;

    injectStyles();

    var root = el('div', 'wtp');
    var top = el('div', 'wtp-top');
    var titleWrap = el('div');
    titleWrap.appendChild(el('h3', 'wtp-title', 'Worktree progress'));
    titleWrap.appendChild(el('p', 'wtp-sub', 'Per-worktree status plus task-graph timing and cost'));
    top.appendChild(titleWrap);
    top.appendChild(el('span', 'wtp-spacer'));

    var liveBtn = el('button', 'wtp-btn on', 'Live');
    var refreshBtn = el('button', 'wtp-btn', 'Refresh');
    var seedBtn = el('button', 'wtp-btn', 'Seed demo');
    var clearBtn = el('button', 'wtp-btn', 'Clear');
    [liveBtn, refreshBtn, seedBtn, clearBtn].forEach(function (b) {
      b.type = 'button';
      top.appendChild(b);
    });
    root.appendChild(top);

    var msg = el('div', 'wtp-msg', 'loading...');
    root.appendChild(msg);

    var secWt = el('section', 'wtp-sec');
    var wtHead = el('h4', 'wtp-h', 'Per-worktree status');
    var wtCount = el('em', null, '');
    wtHead.appendChild(wtCount);
    secWt.appendChild(wtHead);
    var wtEmpty = el('div', 'wtp-empty', 'No worktrees reporting yet.');
    var wtHost = el('div', 'wtp-cards');
    secWt.appendChild(wtEmpty);
    secWt.appendChild(wtHost);
    root.appendChild(secWt);

    var secTiming = el('section', 'wtp-sec');
    var tHead = el('h4', 'wtp-h', 'Task-graph timing');
    var tCount = el('em', null, '');
    tHead.appendChild(tCount);
    secTiming.appendChild(tHead);
    var cpLine = el('div', 'wtp-cp');
    var cpLabel = el('b', null, 'Critical path');
    var cpText = el('span', null, ' --');
    cpLine.appendChild(cpLabel);
    cpLine.appendChild(cpText);
    secTiming.appendChild(cpLine);
    var tEmpty = el('div', 'wtp-empty', 'No task-graph nodes yet.');
    var tHost = el('div', 'wtp-rows');
    secTiming.appendChild(tEmpty);
    secTiming.appendChild(tHost);
    root.appendChild(secTiming);

    var secCost = el('section', 'wtp-sec');
    secCost.appendChild(el('h4', 'wtp-h', 'Cost rollup'));
    var cHost = el('div', 'wtp-cost');
    secCost.appendChild(cHost);
    root.appendChild(secCost);

    containerEl.appendChild(root);

    var renderCards = WorktreeCards(wtHost);
    var renderTimings = TimingRows(tHost);
    var renderCost = CostRows(cHost);

    var timer = null;
    var destroyed = false;
    var inFlight = false;

    function setMsg(text, isError) {
      msg.textContent = text;
      msg.className = isError ? 'wtp-msg err' : 'wtp-msg';
    }

    function apply(payload) {
      var snap = (payload && payload.snapshot) || {};
      var worktrees = snap.worktrees || [];
      var timings = snap.node_timings || [];
      var cp = snap.critical_path || { nodes: [], duration_s: 0 };
      var cost = snap.cost || {};

      var critical = {};
      (cp.nodes || []).forEach(function (n) { critical[String(n)] = true; });

      renderCards(worktrees);
      wtEmpty.style.display = worktrees.length ? 'none' : '';
      wtCount.textContent = worktrees.length ? worktrees.length + ' tracked' : '';

      renderTimings(timings, critical);
      tEmpty.style.display = timings.length ? 'none' : '';
      tCount.textContent = timings.length ? timings.length + ' nodes' : '';
      cpText.textContent = (cp.nodes && cp.nodes.length)
        ? ': ' + cp.nodes.join(' → ') + '  ·  ' + fmtDur(cp.duration_s)
        : ': none yet';

      renderCost(cost);
      setMsg('updated ' + new Date().toLocaleTimeString(), false);
    }

    function refresh() {
      if (destroyed || inFlight) return Promise.resolve(null);
      inFlight = true;
      return fetch(API_SNAPSHOT, { headers: { Accept: 'application/json' } })
        .then(function (res) {
          if (!res.ok) throw new Error('snapshot HTTP ' + res.status);
          return res.json();
        })
        .then(function (payload) {
          if (!destroyed) apply(payload);
          return payload;
        })
        .catch(function (err) {
          if (!destroyed) setMsg('could not load progress: ' + (err && err.message ? err.message : err), true);
          return null;
        })
        .then(function (out) {
          inFlight = false;
          return out;
        });
    }

    function post(url, body) {
      return fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(body || {})
      }).then(function (res) {
        return res.json().then(function (payload) {
          if (!res.ok) throw new Error((payload && payload.error) || ('HTTP ' + res.status));
          return payload;
        });
      });
    }

    function seed() {
      seedBtn.disabled = true;
      setMsg('seeding demo task graph...', false);
      var chain = post(API_RESET, {});
      demoEvents().forEach(function (evt) {
        chain = chain.then(function () { return post(API_EVENTS, evt); });
      });
      return chain
        .then(function () { return refresh(); })
        .catch(function (err) { setMsg('seed failed: ' + (err && err.message ? err.message : err), true); })
        .then(function () { seedBtn.disabled = false; });
    }

    function startPolling() {
      if (timer || destroyed) return;
      timer = setInterval(function () {
        if (destroyed || !document.body.contains(root)) {
          api.stop();
          return;
        }
        refresh();
      }, POLL_MS);
    }

    function stopPolling() {
      if (timer) clearInterval(timer);
      timer = null;
    }

    liveBtn.addEventListener('click', function () {
      if (timer) {
        stopPolling();
        liveBtn.className = 'wtp-btn';
        setMsg('live updates paused', false);
      } else {
        liveBtn.className = 'wtp-btn on';
        startPolling();
        refresh();
      }
    });
    refreshBtn.addEventListener('click', function () { refresh(); });
    seedBtn.addEventListener('click', function () { seed(); });
    clearBtn.addEventListener('click', function () {
      post(API_RESET, {})
        .then(function (payload) { apply(payload); })
        .catch(function (err) { setMsg('clear failed: ' + (err && err.message ? err.message : err), true); });
    });

    var api = {
      root: root,
      refresh: refresh,
      seed: seed,
      apply: apply,
      stop: function () {
        destroyed = true;
        stopPolling();
      },
      destroy: function () {
        destroyed = true;
        stopPolling();
        if (root.parentNode) root.parentNode.removeChild(root);
        delete containerEl.__wtpPanel;
      }
    };

    containerEl.__wtpPanel = api;
    refresh();
    startPolling();
    return api;
  };
})();
