/* Directed Evolve agent -- the engineering chat surface.

   Talks straight to Thomas's own engineering agent via /api/evolve/agent/* --
   no dispatcher, no task manager. The agent edits the live repo and streams its
   work back (SSE); you direct and steer. This is the directed half of the Evolve
   module (the dashboard is the autonomous half). Self-mounts into the Evolve tab
   so it needs no edit to the dashboard file. */
(function () {
    'use strict';
    if (window.__evoAgentChatLoaded) return;
    window.__evoAgentChatLoaded = true;

    var STYLE = [
        '.evo-eng { margin: 0 0 16px; border: 1px solid rgba(91,140,255,0.25); border-radius: 12px; background: rgba(15,18,28,0.55); overflow: hidden; }',
        '.evo-eng-head { display:flex; align-items:flex-start; justify-content:space-between; gap:12px; padding: 10px 14px; border-bottom: 1px solid rgba(255,255,255,0.06); }',
        '.evo-eng-head h3 { margin:0; font-size: 14px; }',
        '.evo-eng-sub { font-size: 12px; color: var(--text-secondary, #94a3b8); margin: 3px 0 0; }',
        '.evo-eng-status { font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: var(--text-secondary,#94a3b8); white-space:nowrap; }',
        '.evo-eng-status.working { color: #5b8cff; }',
        '.evo-eng-transcript { max-height: 340px; overflow:auto; padding: 12px 14px; font: 12px/1.55 ui-monospace, Menlo, Consolas, monospace; white-space: pre-wrap; word-break: break-word; }',
        '.evo-eng-you { color: #e2e8f0; margin: 10px 0 2px; font-weight: 600; }',
        '.evo-eng-agent { color: #aebbcf; margin: 2px 0 6px; }',
        '.evo-eng-done { color: #47d7ac; margin: 0 0 8px; }',
        '.evo-eng-warn { color: #f0a868; margin: 0 0 8px; }',
        '.evo-eng-empty { color: var(--text-secondary,#94a3b8); }',
        '.evo-eng-composer { display:flex; gap: 8px; padding: 10px 14px; border-top: 1px solid rgba(255,255,255,0.06); align-items: flex-end; }',
        '.evo-eng-composer textarea { flex:1; resize: vertical; min-height: 44px; max-height: 180px; background: rgba(0,0,0,0.28); color: var(--text-primary,#e2e8f0); border: 1px solid rgba(255,255,255,0.1); border-radius: 8px; padding: 8px 10px; font: 13px/1.4 inherit; }',
        '.evo-eng-btn { padding: 8px 14px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.12); background: rgba(91,140,255,0.18); color: #dbe5ff; cursor: pointer; font-size: 13px; }',
        '.evo-eng-btn[disabled] { opacity: .45; cursor: default; }',
        '.evo-eng-banner { padding: 8px 14px; background: rgba(240,168,104,0.12); border-bottom: 1px solid rgba(240,168,104,0.28); color: #f0c088; font-size: 12px; }',
        '.evo-eng-banner code { background: rgba(0,0,0,0.3); padding: 1px 5px; border-radius: 4px; }',
        '.evo-eng-tool { color: #7fb0ff; margin: 3px 0; }',
        '.evo-eng-tres { color: #6b7a90; margin: 1px 0; font-size: 11px; }',
        '.evo-eng-meta { color: #5a6678; margin: 1px 0; font-size: 11px; }',
        '.evo-eng-err { color: #f0a868; margin: 2px 0; }',
        '.evo-eng-say { color: #c5d1e3; margin: 2px 0; }',
        '.evo-eng-quick { display:flex; flex-wrap:wrap; gap:6px; padding: 0 14px 8px; align-items:center; }',
        '.evo-eng-quick-label { width:100%; font-size:11px; color: var(--text-secondary,#94a3b8); margin: 2px 0; }',
        '.evo-eng-chip { font-size:11px; padding: 4px 9px; border-radius: 999px; border:1px solid rgba(91,140,255,0.3); background: rgba(91,140,255,0.1); color:#cdd9f2; cursor:pointer; }',
        '.evo-eng-chip:hover { background: rgba(91,140,255,0.22); }'
    ].join('\n');

    var PANEL = '' +
        '<section class="evo-eng" id="evoEng">' +
        '<div class="evo-eng-head">' +
        '<div><h3>&#128296; Direct engineering &mdash; the Evolve agent</h3>' +
        '<p class="evo-eng-sub">Talks straight to Thomas&#39;s own engineering agent (no dispatcher). It edits the live repo and shows its work &mdash; you direct, it builds. Git is your undo.</p></div>' +
        '<span class="evo-eng-status" id="evoEngStatus">idle</span>' +
        '</div>' +
        '<div class="evo-eng-banner" id="evoEngBanner" style="display:none">&#9888; The Evolve agent needs a running model. Start yours (e.g. <code>ollama serve</code>) or set one in Settings &rarr; Model &mdash; for real self-engineering, point it at a frontier model.</div>' +
        '<div class="evo-eng-transcript" id="evoEngTranscript"><div class="evo-eng-empty">Tell the agent what to build or change in Thomas, then watch it work.</div></div>' +
        '<div class="evo-eng-quick" id="evoEngQuick"></div>' +
        '<div class="evo-eng-composer">' +
        '<textarea id="evoEngInput" placeholder="e.g. Add a /health endpoint that returns version + uptime, with a test."></textarea>' +
        '<button class="evo-eng-btn" id="evoEngSend" type="button">Send</button>' +
        '<button class="evo-eng-btn" id="evoEngStop" type="button" disabled>Stop</button>' +
        '</div>' +
        '</section>';

    function stripAnsi(s) { return String(s).replace(/\x1b\[[0-9;]*m/g, ''); }
    function el(id) { return document.getElementById(id); }
    function scrollBottom() { var t = el('evoEngTranscript'); if (t) t.scrollTop = t.scrollHeight; }
    function setStatus(txt, working) { var s = el('evoEngStatus'); if (s) { s.textContent = txt; s.classList.toggle('working', !!working); } }
    function setBusy(busy) { var sb = el('evoEngSend'), st = el('evoEngStop'); if (sb) sb.disabled = busy; if (st) st.disabled = !busy; }

    var es = null, agentBlock = null, agentBuf = '';

    function escapeHtml(s) {
        return String(s).replace(/[&<>]/g, function (c) { return c === '&' ? '&amp;' : c === '<' ? '&lt;' : '&gt;'; });
    }
    // Render the agent's raw log into structured lines -- the "show its work"
    // view: tool calls, tool results, run meta, errors, and plain reasoning.
    function renderAgentHtml(text) {
        var lines = text.split('\n'); var out = [];
        for (var i = 0; i < lines.length; i++) {
            var t = lines[i].trim(); if (!t) continue;
            var esc = escapeHtml(lines[i]);
            if (/^\[calling\b/i.test(t)) out.push('<div class="evo-eng-tool">🔧 ' + escapeHtml(t.replace(/^\[calling\s*/i, '').replace(/\]$/, '')) + '</div>');
            else if (/^\[.*:\s*(ok|error|fail|failed)\b/i.test(t)) out.push('<div class="evo-eng-tres">' + esc + '</div>');
            else if (/^\[(route|runtime model|tools|autonomy)/i.test(t)) out.push('<div class="evo-eng-meta">' + esc + '</div>');
            else if (/\b(error:|warning:|cannot connect|traceback|connection error)\b/i.test(t)) out.push('<div class="evo-eng-err">' + esc + '</div>');
            else out.push('<div class="evo-eng-say">' + esc + '</div>');
        }
        return out.join('');
    }
    function maybeModelBanner(buf) {
        if (/cannot connect to llm|is ollama running|connection attempts failed/i.test(buf)) {
            var b = el('evoEngBanner'); if (b) b.style.display = 'block';
        }
    }
    function appendYou(msg) {
        var t = el('evoEngTranscript'); if (!t) return;
        var empty = t.querySelector('.evo-eng-empty'); if (empty) empty.remove();
        var you = document.createElement('div'); you.className = 'evo-eng-you'; you.textContent = '▸ You: ' + msg; t.appendChild(you);
        agentBlock = document.createElement('div'); agentBlock.className = 'evo-eng-agent'; agentBuf = ''; t.appendChild(agentBlock);
        scrollBottom();
    }
    function appendOutput(text) {
        if (!agentBlock) return;
        agentBuf += stripAnsi(text);
        agentBlock.innerHTML = renderAgentHtml(agentBuf);
        maybeModelBanner(agentBuf);
        scrollBottom();
    }
    function appendNote(cls, text) { var t = el('evoEngTranscript'); if (!t) return; var d = document.createElement('div'); d.className = cls; d.textContent = text; t.appendChild(d); scrollBottom(); }

    function openStream() {
        if (es) { try { es.close(); } catch (_e) { /* ignore */ } }
        es = new EventSource('/api/evolve/agent/stream');
        es.onmessage = function (ev) {
            try {
                var d = JSON.parse(ev.data);
                if (d.type === 'output') appendOutput(d.text);
                else if (d.type === 'done') {
                    appendNote('evo-eng-done', d.returncode === 0 ? '✓ done' : ('✗ finished (exit ' + d.returncode + ')'));
                    setStatus('idle', false); setBusy(false);
                    try { es.close(); } catch (_e) { /* ignore */ } es = null;
                }
            } catch (_e) { /* ignore */ }
        };
        es.onerror = function () { setStatus('idle', false); setBusy(false); try { es.close(); } catch (_e) { /* ignore */ } es = null; };
    }

    async function send() {
        var input = el('evoEngInput'); if (!input) return;
        var msg = (input.value || '').trim(); if (!msg) return;
        setBusy(true); setStatus('working', true);
        var resp;
        try {
            resp = await fetch('/api/evolve/agent/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: msg }) }).then(function (r) { return r.json(); });
        } catch (_e) { resp = { ok: false, error: 'network error' }; }
        if (resp && resp.ok) { appendYou(msg); input.value = ''; openStream(); }
        else { setBusy(false); setStatus('idle', false); appendNote('evo-eng-warn', '✗ ' + ((resp && resp.error) || 'could not start the agent')); }
    }

    async function stop() {
        setStatus('stopping…', true);
        try { await fetch('/api/evolve/agent/stop', { method: 'POST' }); } catch (_e) { /* ignore */ }
    }

    function wire() {
        var sb = el('evoEngSend'); if (sb && !sb.__wired) { sb.__wired = true; sb.addEventListener('click', function () { void send(); }); }
        var st = el('evoEngStop'); if (st && !st.__wired) { st.__wired = true; st.addEventListener('click', function () { void stop(); }); }
        var inp = el('evoEngInput'); if (inp && !inp.__wired) { inp.__wired = true; inp.addEventListener('keydown', function (e) { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); void send(); } }); }
    }

    function injectStyle() {
        if (document.getElementById('evoEngStyle')) return;
        var s = document.createElement('style'); s.id = 'evoEngStyle'; s.textContent = STYLE; document.head.appendChild(s);
    }

    function tryMount() {
        var ws = document.getElementById('evolutionWorkspace'); if (!ws) return false;
        var shell = ws.querySelector('.evolution-shell'); if (!shell) return false;  // workspace not built yet
        if (shell.querySelector('#evoEng')) { wire(); return true; }                 // already mounted
        var holder = document.createElement('div'); holder.innerHTML = PANEL;
        shell.insertBefore(holder.firstChild, shell.firstChild);                      // top of the evolve tab
        injectStyle(); wire(); populateQuickStart(); return true;
    }

    function populateQuickStart() {
        var host = el('evoEngQuick'); if (!host || host.__done) return; host.__done = true;
        var examples = [
            ['Add /health endpoint', 'Add a /health endpoint to the server that returns version + uptime as JSON, with a test.'],
            ['Harden exception handlers', 'Find a cluster of broad/silent exception handlers, narrow them to the specific expected exceptions, and add logging -- behavior-preserving, with tests.'],
            ['Faster green-mirror setup', 'Make the evolve green-mirror setup skip the redundant editable reinstall when nothing changed, so runs start faster.'],
            ['Add type hints', 'Add precise type hints to thomas/forge/anvil/evolve.py and fix any ruff issues you introduce.']
        ];
        var html = '<span class="evo-eng-quick-label">Try one &mdash; click to fill, then send:</span>';
        examples.forEach(function (ex, i) { html += '<button class="evo-eng-chip" type="button" data-i="' + i + '">' + escapeHtml(ex[0]) + '</button>'; });
        host.innerHTML = html;
        host.addEventListener('click', function (evt) {
            var chip = evt.target.closest('.evo-eng-chip'); if (!chip) return;
            var ex = examples[parseInt(chip.getAttribute('data-i'), 10)]; if (!ex) return;
            var input = el('evoEngInput'); if (input) { input.value = ex[1]; input.focus(); }
        });
    }

    // The evolve workspace is built lazily on first tab entry; poll until it
    // exists (then stop). Cheap querySelector, no edit to the dashboard file.
    var tries = 0;
    var iv = setInterval(function () { tries++; if (tryMount() || tries > 1500) clearInterval(iv); }, 500);
    tryMount();
})();
