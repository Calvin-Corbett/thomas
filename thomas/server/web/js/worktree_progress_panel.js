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
    // Local --wtp-* tokens: theme tokens from tokens.css, with the panel's
    // original dark-theme literals as fallbacks for token-less pages.
    '.wtp{--wtp-bg:var(--c-menu-bg,#101216);--wtp-surface:var(--c-surface,#15181e);',
    '--wtp-surface-2:var(--c-surface-2,#2b313b);--wtp-hover:var(--c-hover,#212733);',
    '--wtp-border:var(--c-border,#272c36);--wtp-border-2:var(--c-border-2,#333945);',
    '--wtp-text:var(--c-text,#e7e5e4);--wtp-dim:var(--c-dim,#98a0ad);--wtp-muted:var(--c-muted,#6d7481);',
    '--wtp-accent:var(--c-accent,#3b82f6);--wtp-accent-ink:var(--c-accent-ink,#fff);',
    '--wtp-accent-soft:var(--c-accent-soft,#12294d);--wtp-accent-line:var(--c-accent-line,#1e3a63);',
    '--wtp-success:var(--c-success,#4ade80);--wtp-warn:var(--c-warn,#fbbf24);--wtp-danger:var(--c-danger,#f87171);',
    '--wtp-success-soft:color-mix(in srgb,var(--wtp-success) 14%,transparent);',
    '--wtp-warn-soft:color-mix(in srgb,var(--wtp-warn) 14%,transparent);',
    '--wtp-warn-line:color-mix(in srgb,var(--wtp-warn) 38%,transparent);',
    'font:13px/1.45 ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;color:var(--wtp-text);',
    'background:var(--wtp-bg);border:1px solid var(--wtp-border);border-radius:14px;padding:16px;box-sizing:border-box}',
    '.wtp *{box-sizing:border-box}',
    '.wtp-top{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:14px}',
    '.wtp-title{font:700 14px/1.2 inherit;margin:0;letter-spacing:.01em}',
    '.wtp-sub{font-size:11px;color:var(--wtp-dim);margin:2px 0 0}',
    '.wtp-spacer{flex:1 1 auto}',
    '.wtp-btn{border:1px solid var(--wtp-border-2);background:var(--wtp-surface);color:var(--wtp-dim);border-radius:8px;',
    'padding:6px 11px;font:600 11.5px/1 inherit;cursor:pointer}',
    '.wtp-btn:hover{background:var(--wtp-hover);color:var(--wtp-text)}',
    '.wtp-btn.on{background:var(--wtp-accent);border-color:var(--wtp-accent);color:var(--wtp-accent-ink)}',
    '.wtp-msg{font-size:11px;color:var(--wtp-dim);min-height:14px;margin-bottom:10px}',
    '.wtp-msg.err{color:var(--wtp-danger)}',
    '.wtp-sec{margin-bottom:18px}',
    '.wtp-sec:last-child{margin-bottom:0}',
    '.wtp-h{font:700 10px/1 inherit;letter-spacing:.16em;text-transform:uppercase;color:var(--wtp-dim);',
    'margin:0 0 9px;display:flex;align-items:baseline;gap:8px}',
    '.wtp-h em{font-style:normal;font-weight:600;letter-spacing:.02em;text-transform:none;color:var(--wtp-muted)}',
    '.wtp-empty{font-size:12px;color:var(--wtp-muted);font-style:italic;padding:6px 0}',
    '.wtp-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:10px}',
    '.wtp-card{background:var(--wtp-surface);border:1px solid var(--wtp-border);border-left:3px solid var(--wtp-border-2);',
    'border-radius:10px;padding:10px 11px}',
    '.wtp-card.s-active{border-left-color:var(--wtp-success)}',
    '.wtp-card.s-idle{border-left-color:var(--wtp-muted)}',
    '.wtp-card.s-done{border-left-color:var(--wtp-accent)}',
    '.wtp-card-hd{display:flex;align-items:center;gap:6px;margin-bottom:7px}',
    '.wtp-wt{font:700 12.5px/1.2 inherit;color:var(--wtp-text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '.wtp-badge{margin-left:auto;font:700 9.5px/1 inherit;letter-spacing:.1em;text-transform:uppercase;',
    'border-radius:999px;padding:4px 7px;background:var(--wtp-surface-2);color:var(--wtp-dim)}',
    '.wtp-badge.s-active{background:var(--wtp-success-soft);color:var(--wtp-success)}',
    '.wtp-badge.s-idle{background:var(--wtp-surface-2);color:var(--wtp-dim)}',
    '.wtp-badge.s-done{background:var(--wtp-accent-soft);color:var(--wtp-accent)}',
    '.wtp-kv{display:flex;justify-content:space-between;gap:8px;font-size:11.5px;color:var(--wtp-dim);padding:1.5px 0}',
    '.wtp-kv b{font-weight:600;color:var(--wtp-text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '.wtp-kv b.run{color:var(--wtp-success)}',
    '.wtp-rows{display:flex;flex-direction:column;gap:5px}',
    '.wtp-row{display:grid;grid-template-columns:minmax(96px,1.1fr) 74px minmax(70px,2fr) auto;',
    'align-items:center;gap:9px;background:var(--wtp-surface);border:1px solid var(--wtp-border);border-left:3px solid var(--wtp-border-2);',
    'border-radius:8px;padding:7px 10px}',
    // border-color first: the shorthand must not clobber the amber critical-path rail.
    '.wtp-row.crit{background:var(--wtp-warn-soft);border-color:var(--wtp-warn-line);border-left-color:var(--wtp-warn)}',
    '.wtp-node{font:600 12px/1.2 inherit;color:var(--wtp-text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
    '.wtp-node small{display:block;font-weight:500;font-size:10px;color:var(--wtp-muted)}',
    '.wtp-dur{font:600 12px/1 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--wtp-dim);text-align:right}',
    '.wtp-bar{height:7px;border-radius:4px;background:var(--wtp-surface-2);overflow:hidden}',
    '.wtp-bar i{display:block;height:100%;background:var(--wtp-accent);border-radius:4px;transition:width .25s ease}',
    '.wtp-row.crit .wtp-bar i{background:var(--wtp-warn)}',
    '.wtp-chips{display:flex;gap:5px;justify-content:flex-end}',
    '.wtp-chip{font:700 9px/1 inherit;letter-spacing:.09em;text-transform:uppercase;border-radius:999px;padding:4px 6px}',
    '.wtp-chip.run{background:var(--wtp-success-soft);color:var(--wtp-success)}',
    '.wtp-chip.crit{background:var(--wtp-warn-soft);color:var(--wtp-warn)}',
    '.wtp-cp{font-size:11.5px;color:var(--wtp-dim);background:var(--wtp-warn-soft);border:1px solid var(--wtp-warn-line);border-radius:8px;',
    'padding:7px 10px;margin-bottom:9px;word-break:break-word}',
    '.wtp-cp b{color:var(--wtp-warn);font-weight:700}',
    '.wtp-cost{display:flex;flex-direction:column;gap:4px}',
    '.wtp-cost-row{display:grid;grid-template-columns:1fr auto auto;gap:12px;align-items:center;',
    'font-size:12px;color:var(--wtp-dim);padding:6px 10px;background:var(--wtp-surface);border:1px solid var(--wtp-border);border-radius:8px}',
    '.wtp-cost-row.total{background:var(--wtp-accent-soft);border-color:var(--wtp-accent-line);color:var(--wtp-text);font-weight:700}',
    '.wtp-money{font:600 12px/1 ui-monospace,SFMono-Regular,Menlo,monospace;color:var(--wtp-text)}',
    '.wtp-tok{font-size:11px;color:var(--wtp-muted);min-width:72px;text-align:right}'
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

    var msg = el('div', 'wtp-msg', 'Checking branches…');
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
