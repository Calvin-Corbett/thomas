/*
 * At-mention context objects — composer panel (CAP-148).
 *
 * A self-contained classic script (NOT an ES module): load it with a plain
 *   <script src="/static/js/mention_context_panel.js"></script>
 * then mount it into any element:
 *   window.mountMentionContextPanel(document.getElementById('host'));
 *
 * What it does: you type an utterance containing typed @-mentions —
 * @file:<path>, @thread:<id>, @session:<id> — set a TOKEN BUDGET, and the panel
 * calls POST /api/mention-context/resolve to get back the resolved CONTEXT
 * BUNDLE. It renders the typed objects that were INCLUDED (anchors and
 * budget-retrieved relations), the ones that were DROPPED with the reason
 * (unresolvable / budget / duplicate), and the running TOTAL TOKENS against the
 * budget. Threads and sessions have no ambient store at this tier, so the panel
 * can register them via POST /api/mention-context/objects.
 *
 * No libraries, no build step, no CDN: plain DOM + fetch, scoped styles.
 */
(function () {
  'use strict';

  var STYLE_ID = 'mctx-panel-styles';
  var MENTION_RE = /@(file|thread|session):(\S+)/gi;
  var TRAILING_PUNCT = /[.,;:!?)\]}"']+$/;

  var CSS = [
    '.mctx{--mctx-bg:#12141a;--mctx-fg:#e8e8ea;--mctx-muted:#9aa1ad;--mctx-line:#2a2f3a;',
    '--mctx-file:#3b82f6;--mctx-thread:#a855f7;--mctx-session:#14b8a6;--mctx-ok:#22c55e;--mctx-warn:#f59e0b;--mctx-bad:#ef4444;',
    'background:var(--mctx-bg);color:var(--mctx-fg);border:1px solid var(--mctx-line);border-radius:12px;',
    'padding:14px;font:13px/1.45 ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;box-sizing:border-box}',
    '.mctx *{box-sizing:border-box}',
    '.mctx h2{margin:0 0 2px;font-size:14px;font-weight:700;letter-spacing:.01em}',
    '.mctx .mctx-sub{margin:0 0 10px;color:var(--mctx-muted);font-size:11.5px}',
    '.mctx textarea{width:100%;min-height:76px;resize:vertical;background:#0d0f14;color:var(--mctx-fg);',
    'border:1px solid var(--mctx-line);border-radius:8px;padding:9px 10px;font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}',
    '.mctx .mctx-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:8px}',
    '.mctx label{color:var(--mctx-muted);font-size:11.5px;display:flex;gap:6px;align-items:center}',
    '.mctx input[type=number]{width:96px;background:#0d0f14;color:var(--mctx-fg);border:1px solid var(--mctx-line);',
    'border-radius:6px;padding:5px 7px;font:12.5px ui-monospace,Menlo,monospace}',
    '.mctx button{background:#1d4ed8;color:#fff;border:none;border-radius:7px;padding:7px 13px;cursor:pointer;',
    'font:600 12.5px ui-sans-serif,system-ui,sans-serif}',
    '.mctx button:hover{background:#2563eb}',
    '.mctx button.mctx-ghost{background:transparent;color:var(--mctx-muted);border:1px solid var(--mctx-line)}',
    '.mctx button.mctx-ghost:hover{color:var(--mctx-fg);border-color:#3a4150}',
    '.mctx button[disabled]{opacity:.55;cursor:default}',
    '.mctx .mctx-chips{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;min-height:20px}',
    '.mctx .mctx-chip{display:inline-flex;align-items:center;gap:5px;border-radius:999px;padding:2px 9px;',
    'font:600 11px ui-monospace,Menlo,monospace;border:1px solid transparent}',
    '.mctx .mctx-file{color:#bfdbfe;background:rgba(59,130,246,.16);border-color:rgba(59,130,246,.4)}',
    '.mctx .mctx-thread{color:#e9d5ff;background:rgba(168,85,247,.16);border-color:rgba(168,85,247,.4)}',
    '.mctx .mctx-session{color:#99f6e4;background:rgba(20,184,166,.16);border-color:rgba(20,184,166,.4)}',
    '.mctx .mctx-meter{margin-top:12px}',
    '.mctx .mctx-meter-top{display:flex;justify-content:space-between;font:600 11.5px ui-monospace,Menlo,monospace}',
    '.mctx .mctx-track{height:8px;border-radius:5px;background:#0d0f14;border:1px solid var(--mctx-line);overflow:hidden;margin-top:5px}',
    '.mctx .mctx-fill{height:100%;background:var(--mctx-ok);transition:width .18s ease}',
    '.mctx .mctx-fill.mctx-tight{background:var(--mctx-warn)}',
    '.mctx .mctx-fill.mctx-over{background:var(--mctx-bad)}',
    '.mctx .mctx-cols{display:flex;gap:12px;flex-wrap:wrap;margin-top:12px}',
    '.mctx .mctx-col{flex:1 1 240px;min-width:220px}',
    '.mctx .mctx-hd{font:700 10px ui-sans-serif,system-ui,sans-serif;letter-spacing:.14em;text-transform:uppercase;',
    'color:var(--mctx-muted);margin-bottom:6px}',
    '.mctx ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:6px}',
    '.mctx li{border:1px solid var(--mctx-line);border-radius:8px;padding:7px 9px;background:#0d0f14}',
    '.mctx .mctx-li-top{display:flex;gap:6px;align-items:center;flex-wrap:wrap}',
    '.mctx .mctx-ref{font:600 12px ui-monospace,Menlo,monospace;word-break:break-all}',
    '.mctx .mctx-meta{color:var(--mctx-muted);font:11px ui-monospace,Menlo,monospace;margin-top:3px}',
    '.mctx .mctx-preview{color:var(--mctx-muted);font-size:11.5px;margin-top:4px;white-space:pre-wrap;',
    'overflow:hidden;max-height:34px}',
    '.mctx .mctx-reason{border-radius:999px;padding:1px 7px;font:700 10px ui-sans-serif,system-ui,sans-serif;',
    'letter-spacing:.06em;text-transform:uppercase}',
    '.mctx .mctx-reason-budget{color:#fde68a;background:rgba(245,158,11,.16)}',
    '.mctx .mctx-reason-unresolvable{color:#fecaca;background:rgba(239,68,68,.16)}',
    '.mctx .mctx-reason-duplicate{color:#c7d2fe;background:rgba(99,102,241,.18)}',
    '.mctx .mctx-empty{color:var(--mctx-muted);font-size:11.5px;font-style:italic}',
    '.mctx .mctx-err{margin-top:10px;color:#fecaca;background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.4);',
    'border-radius:8px;padding:7px 9px;font-size:12px}',
    '.mctx .mctx-note{margin-top:8px;color:var(--mctx-muted);font-size:11px}'
  ].join('');

  function injectStyles(doc) {
    if (doc.getElementById(STYLE_ID)) return;
    var style = doc.createElement('style');
    style.id = STYLE_ID;
    style.textContent = CSS;
    (doc.head || doc.documentElement).appendChild(style);
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function kindClass(kind) {
    if (kind === 'file' || kind === 'thread' || kind === 'session') return 'mctx-' + kind;
    return 'mctx-file';
  }

  /* Client-side mirror of the server parser, used only for the live chip strip. */
  function detectMentions(text) {
    var out = [];
    var seen = {};
    var m;
    MENTION_RE.lastIndex = 0;
    while ((m = MENTION_RE.exec(text)) !== null) {
      var kind = m[1].toLowerCase();
      var ref = m[2].replace(TRAILING_PUNCT, '');
      if (!ref) continue;
      var key = kind + ':' + ref;
      if (seen[key]) continue;
      seen[key] = true;
      out.push({ kind: kind, ref: ref, key: key });
    }
    return out;
  }

  async function postJson(url, payload) {
    var resp = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    var text = await resp.text();
    var data = null;
    if (text) {
      try { data = JSON.parse(text); } catch (e) { data = null; }
    }
    if (!resp.ok) {
      var detail = (data && (data.error || data.message)) || text || ('HTTP ' + resp.status);
      throw new Error(resp.status + ': ' + String(detail).slice(0, 300));
    }
    return data;
  }

  function mount(containerEl) {
    if (!containerEl || !containerEl.appendChild) {
      throw new Error('mountMentionContextPanel: a container element is required');
    }
    if (containerEl.getAttribute('data-mctx-mounted') === '1') {
      return containerEl.__mctxApi || null;
    }
    containerEl.setAttribute('data-mctx-mounted', '1');
    injectStyles(containerEl.ownerDocument || document);

    var root = el('div', 'mctx');
    root.appendChild(el('h2', null, 'Context objects — @mentions'));
    root.appendChild(el(
      'p',
      'mctx-sub',
      'Type @file:<path>, @thread:<id> or @session:<id>. Relations are pulled in by relevance until the token budget is full.'
    ));

    var composer = el('textarea');
    composer.setAttribute('spellcheck', 'false');
    composer.placeholder = 'Summarise @file:README.md against @thread:demo-thread and @session:demo-session';
    composer.value = 'Summarise @file:README.md against @thread:demo-thread and @session:demo-session';
    root.appendChild(composer);

    var chips = el('div', 'mctx-chips');
    root.appendChild(chips);

    var controls = el('div', 'mctx-row');
    var budgetLabel = el('label', null, 'Budget (tokens)');
    var budgetInput = el('input');
    budgetInput.type = 'number';
    budgetInput.min = '0';
    budgetInput.step = '100';
    budgetInput.value = '2000';
    budgetLabel.appendChild(budgetInput);
    controls.appendChild(budgetLabel);

    var relLabel = el('label', null, 'Max relations');
    var relInput = el('input');
    relInput.type = 'number';
    relInput.min = '0';
    relInput.max = '32';
    relInput.step = '1';
    relInput.value = '6';
    relLabel.appendChild(relInput);
    controls.appendChild(relLabel);

    var resolveBtn = el('button', null, 'Resolve context');
    controls.appendChild(resolveBtn);
    var seedBtn = el('button', 'mctx-ghost', 'Register demo thread + session');
    controls.appendChild(seedBtn);
    root.appendChild(controls);

    var errBox = el('div', 'mctx-err');
    errBox.style.display = 'none';
    root.appendChild(errBox);

    var meter = el('div', 'mctx-meter');
    var meterTop = el('div', 'mctx-meter-top');
    var meterLeft = el('span', null, 'Total tokens 0 / 0');
    var meterRight = el('span', null, '');
    meterTop.appendChild(meterLeft);
    meterTop.appendChild(meterRight);
    meter.appendChild(meterTop);
    var track = el('div', 'mctx-track');
    var fill = el('div', 'mctx-fill');
    fill.style.width = '0%';
    track.appendChild(fill);
    meter.appendChild(track);
    root.appendChild(meter);

    var cols = el('div', 'mctx-cols');
    var includedCol = el('div', 'mctx-col');
    includedCol.appendChild(el('div', 'mctx-hd', 'Included'));
    var includedList = el('ul');
    includedCol.appendChild(includedList);
    var droppedCol = el('div', 'mctx-col');
    droppedCol.appendChild(el('div', 'mctx-hd', 'Dropped'));
    var droppedList = el('ul');
    droppedCol.appendChild(droppedList);
    cols.appendChild(includedCol);
    cols.appendChild(droppedCol);
    root.appendChild(cols);

    var note = el('div', 'mctx-note', '');
    root.appendChild(note);

    containerEl.appendChild(root);

    /* ── rendering ──────────────────────────────────────────────────────── */

    function showError(message) {
      if (!message) {
        errBox.style.display = 'none';
        errBox.textContent = '';
        return;
      }
      errBox.style.display = '';
      errBox.textContent = message;
    }

    function renderChips() {
      chips.textContent = '';
      var found = detectMentions(composer.value);
      if (!found.length) {
        chips.appendChild(el('span', 'mctx-empty', 'No @mentions typed yet.'));
        return;
      }
      found.forEach(function (m) {
        chips.appendChild(el('span', 'mctx-chip ' + kindClass(m.kind), m.kind + ':' + m.ref));
      });
    }

    function emptyItem(list, text) {
      var li = el('li');
      li.appendChild(el('span', 'mctx-empty', text));
      list.appendChild(li);
    }

    function renderIncluded(entries) {
      includedList.textContent = '';
      if (!entries.length) {
        emptyItem(includedList, 'Nothing included.');
        return;
      }
      entries.forEach(function (entry) {
        var li = el('li');
        var top = el('div', 'mctx-li-top');
        top.appendChild(el('span', 'mctx-chip ' + kindClass(entry.kind), entry.kind));
        top.appendChild(el('span', 'mctx-ref', entry.ref));
        li.appendChild(top);
        var meta = entry.relation === 'related'
          ? 'related · relevance ' + entry.relevance + ' · via ' + (entry.anchor || '?') + ' · ' + entry.tokens + ' tok'
          : 'mention · ' + entry.tokens + ' tok';
        li.appendChild(el('div', 'mctx-meta', meta));
        if (entry.preview) li.appendChild(el('div', 'mctx-preview', entry.preview));
        includedList.appendChild(li);
      });
    }

    function renderDropped(entries) {
      droppedList.textContent = '';
      if (!entries.length) {
        emptyItem(droppedList, 'Nothing dropped.');
        return;
      }
      entries.forEach(function (entry) {
        var li = el('li');
        var top = el('div', 'mctx-li-top');
        top.appendChild(el('span', 'mctx-chip ' + kindClass(entry.kind), entry.kind));
        top.appendChild(el('span', 'mctx-ref', entry.ref));
        top.appendChild(el('span', 'mctx-reason mctx-reason-' + entry.reason, entry.reason));
        li.appendChild(top);
        var bits = [];
        if (entry.reason === 'budget') bits.push('needed ' + entry.tokens + ' tok');
        if (entry.anchor) bits.push('via ' + entry.anchor);
        if (entry.error) bits.push(entry.error);
        if (bits.length) li.appendChild(el('div', 'mctx-meta', bits.join(' · ')));
        droppedList.appendChild(li);
      });
    }

    function renderMeter(bundle) {
      var total = Number(bundle.total_tokens) || 0;
      var budget = Number(bundle.budget) || 0;
      meterLeft.textContent = 'Total tokens ' + total + ' / ' + budget;
      meterRight.textContent = bundle.within_budget
        ? (bundle.remaining_tokens + ' left')
        : 'OVER BUDGET';
      var pct = budget > 0 ? Math.min(100, Math.round((total / budget) * 100)) : (total > 0 ? 100 : 0);
      fill.style.width = pct + '%';
      fill.className = 'mctx-fill' + (!bundle.within_budget ? ' mctx-over' : (pct >= 85 ? ' mctx-tight' : ''));
    }

    function renderBundle(bundle) {
      renderMeter(bundle);
      renderIncluded(bundle.included || []);
      renderDropped(bundle.dropped || []);
      var counts = bundle.counts || {};
      var reasons = counts.dropped_by_reason || {};
      note.textContent =
        (counts.mentions || 0) + ' mention(s) · ' +
        (counts.included || 0) + ' included · ' +
        (counts.dropped || 0) + ' dropped (' +
        (reasons.unresolvable || 0) + ' unresolvable, ' +
        (reasons.budget || 0) + ' budget, ' +
        (reasons.duplicate || 0) + ' duplicate)';
    }

    /* ── actions ────────────────────────────────────────────────────────── */

    var inFlight = 0;

    function busy(active) {
      resolveBtn.disabled = active;
      seedBtn.disabled = active;
      resolveBtn.textContent = active ? 'Resolving…' : 'Resolve context';
    }

    async function resolveNow() {
      var seq = ++inFlight;
      busy(true);
      showError('');
      try {
        var payload = {
          utterance: composer.value,
          budget: Math.max(0, parseInt(budgetInput.value, 10) || 0),
          max_relations: Math.max(0, parseInt(relInput.value, 10) || 0)
        };
        var bundle = await postJson('/api/mention-context/resolve', payload);
        if (seq !== inFlight) return null;
        renderBundle(bundle);
        return bundle;
      } catch (err) {
        if (seq === inFlight) showError('Resolve failed — ' + (err && err.message ? err.message : String(err)));
        return null;
      } finally {
        if (seq === inFlight) busy(false);
      }
    }

    async function seedDemoObjects() {
      busy(true);
      showError('');
      try {
        await postJson('/api/mention-context/objects', {
          kind: 'thread',
          ref: 'demo-thread',
          content: 'Thread demo-thread: the team agreed to ship the mention resolver behind the budget meter.',
          relations: [
            {
              kind: 'session',
              ref: 'demo-thread-reply',
              content: 'Reply in demo-thread: the budget must hold even when a big file is mentioned.',
              relevance: 0.8
            }
          ]
        });
        await postJson('/api/mention-context/objects', {
          kind: 'session',
          ref: 'demo-session',
          content: 'Session demo-session: working notes about at-mention context objects and token budgeting.'
        });
        note.textContent = 'Registered demo-thread and demo-session. Resolve to see them included.';
      } catch (err) {
        showError('Register failed — ' + (err && err.message ? err.message : String(err)));
      } finally {
        busy(false);
      }
      return resolveNow();
    }

    var debounceTimer = null;
    function scheduleResolve() {
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(function () {
        debounceTimer = null;
        resolveNow();
      }, 450);
    }

    composer.addEventListener('input', function () {
      renderChips();
      scheduleResolve();
    });
    budgetInput.addEventListener('change', resolveNow);
    relInput.addEventListener('change', resolveNow);
    resolveBtn.addEventListener('click', resolveNow);
    seedBtn.addEventListener('click', seedDemoObjects);
    composer.addEventListener('keydown', function (ev) {
      if ((ev.ctrlKey || ev.metaKey) && ev.key === 'Enter') {
        ev.preventDefault();
        resolveNow();
      }
    });

    renderChips();
    renderIncluded([]);
    renderDropped([]);
    resolveNow();

    var api = {
      element: root,
      resolve: resolveNow,
      registerDemoObjects: seedDemoObjects,
      setUtterance: function (text) { composer.value = String(text || ''); renderChips(); return resolveNow(); },
      setBudget: function (value) { budgetInput.value = String(value); return resolveNow(); }
    };
    containerEl.__mctxApi = api;
    return api;
  }

  window.mountMentionContextPanel = mount;
})();
