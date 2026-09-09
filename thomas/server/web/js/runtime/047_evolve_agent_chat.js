(function () {
    'use strict';
    if (window.__forgeCodeLoaded) return;
    window.__forgeCodeLoaded = true;
    function el(id) { return document.getElementById(id); }
    function stripAnsi(s) { return String(s).replace(/\x1b\[[0-9;]*m/g, ''); }
    function escapeHtml(s) { return String(s).replace(/[&<>]/g, function (c) { return c === '&' ? '&amp;' : c === '<' ? '&lt;' : '&gt;'; }); }
    function tx() { return el('forgeCodeTranscript'); }
    function showStop(on) { var b = el('forgeCodeStop'); if (!b) return; if (on) b.removeAttribute('hidden'); else b.setAttribute('hidden', ''); }
    function setStatus(txt, working) { var s = el('forgeCodeStatus'); if (s) { s.textContent = txt; s.classList.toggle('working', !!working); } }
    (function mirrorForgeActive() {
        var active = !!window.forgeCodeActive;
        function reflect(v) {
            try { if (document.body) document.body.classList.toggle('forge-code-on', !!v); }
            catch (_e) { /* pre-body; reflected again on DOMContentLoaded */ }
        }
        try {
            Object.defineProperty(window, 'forgeCodeActive', {
                configurable: true, enumerable: true,
                get: function () { return active; },
                set: function (v) { active = !!v; reflect(active); }
            });
        } catch (_e) { window.forgeCodeActive = active; }
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', function () { reflect(active); });
        } else { reflect(active); }
    })();
    var ICONS = {
        read: '<path d="M4 4h10l6 6v10a0 0 0 0 1 0 0H4z"/><path d="M14 4v6h6"/><path d="M8 14h7M8 17h7"/>',
        edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M14 6l4 4"/>',
        write: '<path d="M4 4h9l5 5v11H4z"/><path d="M13 4v5h5"/><path d="M11 12v6M8 15h6"/>',
        find: '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
        search: '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.3-4.3"/>',
        run: '<path d="M5 4l14 8-14 8z"/>',
        tool: '<path d="M14 6a4 4 0 0 1-5 5L5 15v4h4l4-4a4 4 0 0 1 5-5l-4 4"/>',
        spinner: '<path d="M12 3a9 9 0 1 0 9 9" />',
        check: '<path d="M4 12l5 5L20 6"/>',
        alert: '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17v.5"/>',
        dash: '<path d="M5 12h14"/>',
        'arrow-down': '<path d="M12 5v14"/><path d="M6 13l6 6 6-6"/>',
        stop: '<rect x="6" y="6" width="12" height="12" rx="1"/>',
        think: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 1 4 10.5c-.6.6-1 1.2-1 2.5H9c0-1.3-.4-1.9-1-2.5A6 6 0 0 1 12 3z"/>',
        bulb: '<path d="M9.5 18h5M10.5 21h3"/><path d="M12 2a7 7 0 0 0-4 12.7V18h8v-3.3A7 7 0 0 0 12 2z"/><path d="M9.7 9.6l2.3 2.3 2.3-2.3"/>',
        spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/>',
        file: '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>',
        copy: '<rect x="9" y="9" width="11" height="11" rx="1.5"/><path d="M5 15V5a1.5 1.5 0 0 1 1.5-1.5H15"/>',
        plus: '<path d="M12 5v14M5 12h14"/>',
        trash: '<path d="M4 7h16"/><path d="M9 7V5h6v2"/><path d="M6 7l1 13h10l1-13"/><path d="M10 11v6M14 11v6"/>',
        pencil: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M14 6l4 4"/>',
        clock: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
        railLeft: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/><path d="M15 10l-2 2 2 2"/>',
        railRight: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/><path d="M13 10l2 2-2 2"/>',
        image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5L5 21"/>',
        window: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/><path d="M6.5 6.5h.01M9 6.5h.01"/>',
        table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M9 4v16"/>',
        external: '<path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5"/>'
    };
    function svg(name, cls) {
        var p = ICONS[name] || ICONS.tool;
        return '<svg class="' + (cls || '') + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            + 'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + p + '</svg>';
    }
    function mdHtml(text) {
        try { if (typeof formatMarkdown === 'function') return formatMarkdown(String(text || '')); }
        catch (_e) { /* fall through */ }
        return '<p>' + escapeHtml(String(text || '')) + '</p>';
    }
    function highlightIn(node) {
        try {
            if (typeof hljs === 'undefined' || !node) return;
            node.querySelectorAll('pre code:not(.fc-hl-done)').forEach(function (e) {
                try { hljs.highlightElement(e); } catch (_e) { /* unknown lang */ }
                e.classList.add('fc-hl-done');
            });
        } catch (_e) { /* ignore */ }
    }
    function agentName() {
        try {
            if (typeof resolveAgentName === 'function' && typeof currentPreferences !== 'undefined') {
                return resolveAgentName(currentPreferences) || 'Thomas';
            }
        } catch (_e) { /* ignore */ }
        return 'Thomas';
    }
    var stick = true;
    var newCount = 0; // unread units that arrived while the user was scrolled up
    function nearBottom(t) { return (t.scrollHeight - t.scrollTop - t.clientHeight) < 90; }
    function follow() { var t = tx(); if (t && stick) t.scrollTop = t.scrollHeight; }
    function jumpBottom() { var t = tx(); if (t) { stick = true; t.scrollTop = t.scrollHeight; } newCount = 0; updateJump(); }
    function noteNewContent() { if (!stick) { newCount++; updateJump(); } }
    function updateJump() {
        var b = el('forgeCodeJump'); if (!b) return;
        if (stick) { b.hidden = true; newCount = 0; return; }
        var lbl = b.querySelector('.fc-jump-label');
        if (lbl) lbl.textContent = newCount > 0 ? ('Jump to latest · ' + newCount + ' new') : 'Jump to latest';
        b.hidden = false;
    }
    var es = null;
    var currentConvoId = null, pendingSourceItem = null;
    var agentStack = null, currentSayEl = null, sawAction = false, sawSay = false, lastToolCard = null;
    var pendingFollowup = null;
    var lastSentMessage = null;
    function clearEmpty() { var t = tx(); if (!t) return; var e = t.querySelector('.fc-empty'); if (e) e.remove(); }
    function appendUserRow(msg) {
        var t = tx(); if (!t) return;
        clearEmpty();
        var row = document.createElement('div'); row.className = 'message-row is-user';
        var stack = document.createElement('div'); stack.className = 'message-stack';
        var content = document.createElement('div'); content.className = 'message-content user-bubble';
        content.innerHTML = mdHtml(msg);
        highlightIn(content);
        stack.appendChild(content); row.appendChild(stack); t.appendChild(row);
    }
    function startAgentTurn() { agentStack = null; currentSayEl = null; sawAction = false; sawSay = false; lastToolCard = null; resetDispatchFilter(); }
    var inChangedFilesBlock = false;
    function resetDispatchFilter() { inChangedFilesBlock = false; }
    function isDispatchNoiseLine(rawLine) {
        var t = stripAnsi(String(rawLine)).trim();
        if (!t) return false; // keep blank lines -- harmless prose spacing
        if (/^DISPATCHED via\b/i.test(t)) { inChangedFilesBlock = false; return true; }
        if (/dispatched via (?:claude|codex) cli/i.test(t)) { inChangedFilesBlock = false; return true; }
        if (/^NO-OP\b/i.test(t)) { inChangedFilesBlock = false; return true; }
        if (/^Review the diff\b/i.test(t)) { inChangedFilesBlock = false; return true; }
        if (/^changed files:/i.test(t)) { inChangedFilesBlock = true; return true; }
        if (inChangedFilesBlock) {
            if (/^\S+$/.test(t) && /[\/\\.]/.test(t)) return true;
            inChangedFilesBlock = false; // block ended -> keep this line
        }
        return false;
    }
    function stripDispatchNoise(text) {
        var lines = String(text == null ? '' : text).split('\n');
        var kept = [];
        for (var i = 0; i < lines.length; i++) {
            if (isDispatchNoiseLine(lines[i])) continue;
            kept.push(lines[i]);
        }
        return kept.join('\n');
    }
    var HARNESS_NOISE = [
        'file state is current in your context',
        'no need to read it back',
        'no need to re-read',
        "you don't need to read",
        'this file has not been modified since you last read it'
    ];
    function stripHarnessNoise(text) {
        var lines = String(text == null ? '' : text).split('\n');
        var kept = [];
        for (var i = 0; i < lines.length; i++) {
            var lower = lines[i].toLowerCase();
            var noisy = false;
            for (var n = 0; n < HARNESS_NOISE.length; n++) {
                if (lower.indexOf(HARNESS_NOISE[n]) !== -1) { noisy = true; break; }
            }
            if (!noisy) kept.push(lines[i]);
        }
        return kept.join('\n');
    }
    var SCRATCH_ID = /\bSC-[A-Z0-9]{1,8}-\d+\b/;
    function stripScratchIds(text) {
        var s = String(text == null ? '' : text);
        if (!SCRATCH_ID.test(s)) return s; // nothing to strip -> leave prose (and any code indentation) untouched
        s = s.replace(/[([{]\s*SC-[A-Z0-9]{1,8}-\d+\s*[)\]}]/g, '');
        s = s.replace(/\bSC-[A-Z0-9]{1,8}-\d+\b/g, '');
        s = s.replace(/(\S)[ \t]{2,}/g, '$1 ').replace(/[ \t]+([,.;:])/g, '$1');
        return s;
    }
    function cleanProse(text) {
        return stripScratchIds(stripHarnessNoise(stripDispatchNoise(text)));
    }
    function ensureAgentStack() {
        if (agentStack) return agentStack;
        var t = tx(); if (!t) return null;
        clearEmpty();
        var row = document.createElement('div'); row.className = 'message-row is-assistant';
        var stack = document.createElement('div'); stack.className = 'message-stack';
        var meta = document.createElement('div'); meta.className = 'message-meta';
        var author = document.createElement('span'); author.className = 'message-author'; author.textContent = agentName();
        meta.appendChild(author); stack.appendChild(meta); row.appendChild(stack); t.appendChild(row);
        agentStack = stack; return stack;
    }
    function verbFor(name) {
        switch (String(name || '').toLowerCase()) {
            case 'read': return 'Read';
            case 'edit': case 'multiedit': case 'notebookedit': return 'Edit';
            case 'write': return 'Write';
            case 'glob': return 'Find';
            case 'grep': return 'Search';
            case 'run': return 'Verify';
            default: return name || 'Tool';
        }
    }
    function iconFor(name) {
        switch (String(name || '').toLowerCase()) {
            case 'read': return 'read';
            case 'edit': case 'multiedit': case 'notebookedit': return 'edit';
            case 'write': return 'write';
            case 'glob': return 'find';
            case 'grep': return 'search';
            case 'run': return 'run';
            default: return 'tool';
        }
    }
    function actionTarget(raw) {
        var s = String(raw || '').trim();
        var m = s.match(/^[a-z_]+:\s*([\s\S]+)$/i);
        return (m ? m[1] : s).trim();
    }
    function renderSayMarkdown(elx) {
        if (!elx) return;
        if (elx.__mdTimer) { clearTimeout(elx.__mdTimer); elx.__mdTimer = null; }
        elx.innerHTML = mdHtml(elx.__buf || '');
        elx.__tail = null; // the plain-text tail is now baked into the rendered HTML
    }
    function scheduleSayMarkdown(elx) {
        if (!elx || elx.__mdTimer) return;
        elx.__mdTimer = setTimeout(function () {
            elx.__mdTimer = null;
            renderSayMarkdown(elx);
            follow();
        }, 120);
    }
    function appendSay(text, isDelta) {
        var stack = ensureAgentStack(); if (!stack) return;
        if (isDelta) {
            var raw = cleanProse(String(text == null ? '' : text));
            if (!raw) return;
            sawSay = true; // the agent produced a prose reply -> an ANSWER, not a build
            if (!currentSayEl) {
                currentSayEl = document.createElement('div');
                currentSayEl.className = 'message-content assistant-bubble is-streaming';
                currentSayEl.__buf = ''; currentSayEl.__last = ''; currentSayEl.__streamed = true;
                stack.appendChild(currentSayEl);
            }
            currentSayEl.__streamed = true;
            currentSayEl.__buf += raw;
            if (!currentSayEl.__tail) {
                currentSayEl.__tail = document.createTextNode('');
                currentSayEl.appendChild(currentSayEl.__tail);
            }
            currentSayEl.__tail.appendData(raw);
            scheduleSayMarkdown(currentSayEl);
            follow();
            return;
        }
        text = cleanProse(text); if (!text.trim()) return;
        sawSay = true;
        if (!currentSayEl) {
            currentSayEl = document.createElement('div');
            currentSayEl.className = 'message-content assistant-bubble is-streaming';
            currentSayEl.__buf = '';
            currentSayEl.__last = '';
            stack.appendChild(currentSayEl);
        }
        if (currentSayEl.__streamed) { renderSayMarkdown(currentSayEl); follow(); return; }
        var norm = text.trim();
        if (norm && (currentSayEl.__last === norm || currentSayEl.__buf.trim() === norm)) {
            renderSayMarkdown(currentSayEl); return;
        }
        currentSayEl.__last = norm;
        currentSayEl.__buf += (currentSayEl.__buf ? '\n\n' : '') + text;
        renderSayMarkdown(currentSayEl);
        follow();
    }
    function appendInsight(text) {
        text = cleanProse(text); if (!text.trim()) return;
        currentSayEl = null;
        var stack = ensureAgentStack(); if (!stack) return;
        if (stack.__lastInsight === text) return; // don't repeat the same observation
        stack.__lastInsight = text;
        var node = document.createElement('div'); node.className = 'fc-insight';
        node.innerHTML = '<span class="fc-insight-ic">' + svg('bulb') + '</span>'
            + '<span class="fc-insight-text"></span>';
        node.querySelector('.fc-insight-text').textContent = text;
        stack.appendChild(node); follow();
    }
    function appendReason(text) {
        text = String(text || ''); if (!text.trim()) return;
        currentSayEl = null;
        var stack = ensureAgentStack(); if (!stack) return;
        var det = document.createElement('details'); det.className = 'fc-reason';
        var sum = document.createElement('summary');
        sum.innerHTML = svg('think') + '<span>Thought for a moment</span>';
        var body = document.createElement('div'); body.className = 'fc-reason-body'; body.innerHTML = mdHtml(text);
        det.appendChild(sum); det.appendChild(body); stack.appendChild(det); follow();
    }
    function appendAction(d) {
        currentSayEl = null;
        var stack = ensureAgentStack(); if (!stack) return;
        var name = String(d.name || 'tool');
        var isRun = name === 'run'; // the engine's REAL verify/run step
        if (!isRun) sawAction = true; // a genuine agent build action
        var target = actionTarget(d.text) || (isRun ? 'changed files' : '');
        var card = document.createElement('div'); card.className = 'fc-tool' + (isRun ? ' is-run' : '');
        var head = document.createElement('div'); head.className = 'fc-tool-head';
        head.innerHTML =
            '<span class="fc-tool-ic">' + svg(iconFor(name)) + '</span>'
            + '<span class="fc-tool-verb">' + escapeHtml(verbFor(name)) + '</span>'
            + (target ? '<span class="fc-tool-target" title="' + escapeHtml(target) + '">' + escapeHtml(target) + '</span>' : '<span class="fc-tool-target"></span>')
            + '<span class="fc-tool-status" data-state="running">' + svg('spinner') + '</span>';
        card.appendChild(head);
        stack.appendChild(card);
        lastToolCard = card;
        follow();
    }
    function setToolState(card, state) {
        if (!card) return;
        var st = card.querySelector('.fc-tool-status'); if (!st) return;
        st.setAttribute('data-state', state);
        st.innerHTML = svg(state === 'error' ? 'alert' : state === 'success' ? 'check' : 'spinner');
        if (state === 'error') card.classList.add('is-error');
    }
    function looksLikeDiff(s) {
        return /^@@ /m.test(s) || /^(\+\+\+ |--- )/m.test(s);
    }
    function appendResult(d) {
        currentSayEl = null;
        var text = stripHarnessNoise(String(d.text || ''));
        var isErr = !!d.is_error;
        if (lastToolCard) {
            setToolState(lastToolCard, isErr ? 'error' : 'success');
            if (text.trim()) attachToolBody(lastToolCard, text, isErr);
            lastToolCard = null;
            follow();
            return;
        }
        var stack = ensureAgentStack(); if (!stack) return;
        if (!text.trim() && !isErr) return;
        if (text.length > 200 || text.indexOf('\n') !== -1) {
            var det = document.createElement('details'); det.className = 'fc-result' + (isErr ? ' is-error' : '');
            var sum = document.createElement('summary'); sum.textContent = isErr ? 'Result — error' : 'Result';
            var pre = document.createElement('pre'); pre.className = 'fc-result-pre'; pre.textContent = text;
            det.appendChild(sum); det.appendChild(pre); if (isErr) det.open = true;
            stack.appendChild(det);
        } else {
            var line = document.createElement('div'); line.className = 'fc-result-line' + (isErr ? ' is-error' : '');
            line.textContent = text;
            stack.appendChild(line);
        }
        follow();
    }
    function attachToolBody(card, text, isErr) {
        if (!isErr && looksLikeDiff(text)) {
            var dc = buildDiffCard(diffPathFromText(text) || (card.querySelector('.fc-tool-target') || {}).textContent || 'diff', text, {});
            dc.style.borderRadius = '0';
            dc.style.border = '0';
            dc.style.borderTop = '1px solid var(--fc-border)';
            card.appendChild(dc);
            return;
        }
        if (text.length > 160 || text.indexOf('\n') !== -1) {
            var det = document.createElement('details'); det.className = 'fc-tool-body' + (isErr ? ' is-error' : '');
            var sum = document.createElement('summary');
            var lines = text.split('\n').length;
            sum.textContent = isErr ? 'Error output' : ('Output · ' + lines + ' line' + (lines === 1 ? '' : 's'));
            var pre = document.createElement('pre'); pre.className = 'fc-tool-pre'; pre.textContent = text;
            det.appendChild(sum); det.appendChild(pre); if (isErr) det.open = true;
            card.appendChild(det);
        } else {
            var div = document.createElement('div'); div.className = 'fc-tool-inline' + (isErr ? ' is-error' : '');
            div.textContent = text;
            card.appendChild(div);
        }
    }
    function plainCause(detail, rc) {
        var s = String(detail == null ? '' : detail).toLowerCase();
        if (/rate.?limit|\b429\b|too many requests|quota|overloaded|capacity|try again later/.test(s))
            return 'The model provider is rate-limiting or at capacity right now.';
        if (/timed? ?out|timeout|deadline exceeded/.test(s))
            return 'The build timed out before it could finish.';
        if (/permission|denied|eacces|not permitted|forbidden|unauthor/.test(s))
            return 'A permission was denied — the build could not access something it needed.';
        if (/auth|login|credential|api key|\btoken\b|subscription|not logged in|sign in/.test(s))
            return 'The CLI is not authenticated — check your subscription login.';
        if (/network|connection|econn|socket|dns|fetch failed|unreachable|reset by peer/.test(s))
            return 'A network problem interrupted the build.';
        if (/git|merge|conflict|index\.lock|working tree|nothing to commit|detached head/.test(s))
            return 'Git could not complete the change in the repo.';
        if (/no such file|enoent|cannot find|not found/.test(s))
            return 'Something the build expected was missing.';
        if (rc != null && rc !== 0)
            return 'The build exited with an error (code ' + rc + ').';
        return 'The build hit an error before it could finish.';
    }
    function buildErrorDescriptor(detail, rc) {
        return {
            cause: plainCause(detail, rc),
            detail: String(detail == null ? '' : detail),
            retryable: !!lastSentMessage
        };
    }
    function retryLastTurn() {
        if (es) return;
        var msg = lastSentMessage;
        if (!msg) return;
        void sendToBuild(msg);
    }
    function appendBuildError(detail, rc) {
        currentSayEl = null;
        var stack = ensureAgentStack(); if (!stack) return null;
        var desc = buildErrorDescriptor(detail, rc);
        var node = document.createElement('div'); node.className = 'fc-error is-build';
        var head = document.createElement('div'); head.className = 'fc-error-head';
        head.innerHTML = svg('alert') + '<span class="fc-error-cause"></span>';
        head.querySelector('.fc-error-cause').textContent = desc.cause;
        node.appendChild(head);
        if (desc.detail.trim() && desc.detail.trim().toLowerCase() !== desc.cause.toLowerCase()) {
            var det = document.createElement('details'); det.className = 'fc-error-detail';
            var sum = document.createElement('summary'); sum.textContent = 'Details';
            var pre = document.createElement('pre'); pre.className = 'fc-error-pre'; pre.textContent = desc.detail;
            det.appendChild(sum); det.appendChild(pre);
            node.appendChild(det);
        }
        if (desc.retryable) {
            var actions = document.createElement('div'); actions.className = 'fc-error-actions';
            var retry = document.createElement('button'); retry.type = 'button'; retry.className = 'fc-error-retry';
            retry.innerHTML = svg('run') + '<span>Retry</span>';
            retry.addEventListener('click', function () {
                if (es) return; // a build is already live -> nothing to retry against
                retry.disabled = true;
                retryLastTurn();
            });
            actions.appendChild(retry);
            node.appendChild(actions);
        }
        stack.appendChild(node); follow();
        return desc;
    }
    function appendError(text) { return appendBuildError(text, null); }
    function appendStatus(text) {
        text = cleanProse(text); if (!text.trim()) return;
        currentSayEl = null;
        var stack = ensureAgentStack(); if (!stack) return;
        var node = document.createElement('div'); node.className = 'fc-status'; node.textContent = text;
        stack.appendChild(node); follow();
    }
    function appendNote(variant, iconName, text) {
        var t = tx(); if (!t) return;
        clearEmpty();
        var d = document.createElement('div'); d.className = 'fc-note ' + variant;
        d.innerHTML = svg(iconName) + '<span></span>';
        d.querySelector('span').textContent = text;
        t.appendChild(d); follow();
    }
    function forgeToast(msg, tone) {
        try {
            if (typeof window.notifyUser === 'function') {
                window.notifyUser(String(msg), { tone: tone || 'info', durationMs: 2600 });
            }
        } catch (_e) { /* toast is best-effort; the card state still tells the truth */ }
    }
    function finalizeTurn() {
        var t = tx(); if (!t) return;
        t.querySelectorAll('.assistant-bubble.is-streaming').forEach(function (b) {
            if (b.__buf != null) renderSayMarkdown(b);
            b.classList.remove('is-streaming');
        });
        t.querySelectorAll('.message-content').forEach(function (c) { highlightIn(c); });
    }
    function renderEvent(d) {
        var kind = d.kind || d.fc;
        var text = (d.text != null) ? d.text : '';
        var isNewUnit = (kind !== 'say') || !currentSayEl;
        if (kind === 'tool') { appendAction(d); }
        else if (kind === 'tool_result') { appendResult(d); }
        else if (kind === 'insight') { appendInsight(text); }
        else if (kind === 'reason') { appendReason(text); }
        else if (kind === 'error') { appendError(text); }
        else if (kind === 'meta') { appendStatus(text); }
        else { appendSay(text, !!d.delta); } // 'say'/unknown -> chat message (delta-aware)
        if (isNewUnit) noteNewContent();
    }
    var REPLAY_NOISE = ['claude session', 'hook_started', 'hook_response', 'thinking_tokens', 'post_turn_summary', 'notification', 'init ('];
    function replayTranscript(raw) {
        // A turn persisted before the store normalized transcript shapes can
        // carry its transcript as an array -- of single characters (measured:
        // one-char entries, w2-code-explain sweep) or of lines. String() on an
        // array comma-joins it, so no line parses as a forge event. Join
        // characters back into the string they were; join lines with the
        // newline this replay splits on.
        if (Array.isArray(raw)) {
            var parts = raw.map(function (part) { return part == null ? '' : String(part); });
            var allChars = parts.every(function (part) { return part.length <= 1; });
            raw = allChars ? parts.join('') : parts.join('\n');
        }
        var lines = String(raw || '').split('\n');
        for (var i = 0; i < lines.length; i++) {
            var t = stripAnsi(lines[i]).trim(); if (!t) continue;
            var lower = t.toLowerCase();
            var noisy = false;
            for (var n = 0; n < REPLAY_NOISE.length; n++) { if (lower.indexOf(REPLAY_NOISE[n]) !== -1) { noisy = true; break; } }
            if (noisy) continue;
            if (t.charAt(0) === '{') {
                var obj = null;
                try { obj = JSON.parse(t); } catch (_e) { obj = null; }
                if (obj && obj.fc) { renderEvent(obj); continue; }
            }
            appendSay(t);
        }
    }
    function clearTranscript() {
        var t = tx(); if (t) t.innerHTML = '';
        startAgentTurn();
        var ch = el('forgeCodeChanges'); if (ch) ch.innerHTML = '';
        stick = true; newCount = 0; updateJump(); // re-attach to the live edge
    }
    function langForFile(file) {
        var f = String(file || '').toLowerCase();
        var m = f.match(/\.([a-z0-9]+)$/);
        var ext = m ? m[1] : '';
        var map = {
            py: 'python', js: 'javascript', mjs: 'javascript', cjs: 'javascript', jsx: 'javascript',
            ts: 'typescript', tsx: 'typescript', json: 'json', css: 'css', scss: 'scss',
            html: 'xml', htm: 'xml', xml: 'xml', vue: 'xml', svg: 'xml',
            sh: 'bash', bash: 'bash', zsh: 'bash', go: 'go', rs: 'rust',
            yml: 'yaml', yaml: 'yaml', toml: 'ini', ini: 'ini', cfg: 'ini',
            md: 'markdown', sql: 'sql', java: 'java', c: 'c', h: 'c',
            cpp: 'cpp', cc: 'cpp', hpp: 'cpp', rb: 'ruby', php: 'php', kt: 'kotlin', swift: 'swift'
        };
        return map[ext] || '';
    }
    function langBadge(lang, file) {
        if (lang) {
            if (lang === 'javascript') return 'JS';
            if (lang === 'typescript') return 'TS';
            if (lang === 'python') return 'PY';
            if (lang === 'markdown') return 'MD';
            return lang.toUpperCase();
        }
        var m = String(file || '').toLowerCase().match(/\.([a-z0-9]+)$/);
        return m ? m[1].toUpperCase() : 'TXT';
    }
    function diffPathFromText(s) {
        var m = String(s).match(/^\+\+\+ b\/(.+)$/m) || String(s).match(/^\+\+\+ (.+)$/m);
        return m ? m[1].trim() : '';
    }
    function hlFrag(s, lang) {
        if (!s) return '';
        try {
            if (typeof hljs !== 'undefined' && lang && hljs.getLanguage && hljs.getLanguage(lang)) {
                return hljs.highlight(s, { language: lang }).value;
            }
        } catch (_e) { /* fall through */ }
        return escapeHtml(s);
    }
    function splitWords(s) { return String(s).match(/(\s+|[A-Za-z0-9_$]+|[^\sA-Za-z0-9_$])/g) || []; }
    function wordDiff(aStr, bStr) {
        var a = splitWords(aStr), b = splitWords(bStr);
        var n = a.length, m = b.length;
        if (n * m > 40000) return null;
        var dp = []; for (var i = 0; i <= n; i++) { dp.push(new Array(m + 1).fill(0)); }
        for (i = n - 1; i >= 0; i--) {
            for (var j = m - 1; j >= 0; j--) {
                dp[i][j] = (a[i] === b[j]) ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
            }
        }
        var aSeg = [], bSeg = []; i = 0; j = 0;
        while (i < n && j < m) {
            if (a[i] === b[j]) { aSeg.push({ t: a[i], c: false }); bSeg.push({ t: b[j], c: false }); i++; j++; }
            else if (dp[i + 1][j] >= dp[i][j + 1]) { aSeg.push({ t: a[i], c: true }); i++; }
            else { bSeg.push({ t: b[j], c: true }); j++; }
        }
        while (i < n) { aSeg.push({ t: a[i], c: true }); i++; }
        while (j < m) { bSeg.push({ t: b[j], c: true }); j++; }
        return { a: mergeSegs(aSeg), b: mergeSegs(bSeg) };
    }
    function mergeSegs(segs) {
        var out = [];
        for (var i = 0; i < segs.length; i++) {
            var s = segs[i];
            if (out.length && out[out.length - 1].c === s.c) out[out.length - 1].t += s.t;
            else out.push({ t: s.t, c: s.c });
        }
        return out;
    }
    function codeHtml(text, lang, segs) {
        if (text === '') return '';
        if (!segs) return hlFrag(text, lang);
        var out = '';
        for (var i = 0; i < segs.length; i++) {
            var frag = hlFrag(segs[i].t, lang);
            out += segs[i].c ? '<span class="fc-dw">' + frag + '</span>' : frag;
        }
        return out;
    }
    function parseDiff(diff) {
        var lines = String(diff || '').split('\n');
        var rows = [];
        var oldNo = 0, newNo = 0, maxNo = 0, adds = 0, dels = 0;
        for (var i = 0; i < lines.length; i++) {
            var line = lines[i];
            if (/^@@/.test(line)) {
                var hm = line.match(/@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
                if (hm) { oldNo = parseInt(hm[1], 10); newNo = parseInt(hm[2], 10); }
                rows.push({ type: 'hunk', text: line });
                continue;
            }
            if (/^(diff --git|index |--- |\+\+\+ |new file|deleted file|similarity|rename |Binary )/.test(line)) continue;
            var c = line.charAt(0);
            if (c === '+') { rows.push({ type: 'add', oldNo: 0, newNo: newNo, text: line.slice(1) }); maxNo = Math.max(maxNo, newNo); newNo++; adds++; }
            else if (c === '-') { rows.push({ type: 'del', oldNo: oldNo, newNo: 0, text: line.slice(1) }); maxNo = Math.max(maxNo, oldNo); oldNo++; dels++; }
            else { var txt = (c === ' ') ? line.slice(1) : line; rows.push({ type: 'ctx', oldNo: oldNo, newNo: newNo, text: txt }); maxNo = Math.max(maxNo, oldNo, newNo); oldNo++; newNo++; }
        }
        for (i = 0; i < rows.length; i++) {
            if (rows[i].type !== 'del') continue;
            var d0 = i; while (i < rows.length && rows[i].type === 'del') i++;
            var a0 = i; while (i < rows.length && rows[i].type === 'add') i++;
            var dN = a0 - d0, aN = i - a0, pairs = Math.min(dN, aN);
            for (var k = 0; k < pairs; k++) {
                var wd = wordDiff(rows[d0 + k].text, rows[a0 + k].text);
                if (wd) { rows[d0 + k].segs = wd.a; rows[a0 + k].segs = wd.b; }
            }
            i--; // outer loop re-increments
        }
        return { rows: rows, maxNo: maxNo, adds: adds, dels: dels };
    }
    function rowHtml(r, lang) {
        if (r.type === 'hunk') {
            return '<div class="fc-diff-row fc-hunk"><span class="fc-code">' + escapeHtml(r.text) + '</span></div>';
        }
        var cls = r.type === 'add' ? ' is-add' : r.type === 'del' ? ' is-del' : '';
        var sign = r.type === 'add' ? '+' : r.type === 'del' ? '-' : '';
        var oldN = r.oldNo ? String(r.oldNo) : '';
        var newN = r.newNo ? String(r.newNo) : '';
        return '<div class="fc-diff-row' + cls + '">'
            + '<span class="fc-ln fc-ln-old">' + oldN + '</span>'
            + '<span class="fc-ln fc-ln-new">' + newN + '</span>'
            + '<span class="fc-sign">' + sign + '</span>'
            + '<span class="fc-code">' + (codeHtml(r.text, lang, r.segs) || '&nbsp;') + '</span>'
            + '</div>';
    }
    var DIFF_VIRTUALIZE_THRESHOLD = 400; // rows; below this -> render everything
    var DIFF_WINDOW_BUFFER = 24;          // extra rows above & below the viewport
    var DIFF_ROW_FALLBACK_H = 21;         // px; sane row height until measured live
    function renderDiffRows(body, rows, lang) {
        if (rows.length <= DIFF_VIRTUALIZE_THRESHOLD) {
            var html = '';
            for (var i = 0; i < rows.length; i++) html += rowHtml(rows[i], lang);
            body.innerHTML = html;
            return;
        }
        virtualizeDiffBody(body, rows, lang);
    }
    function virtualizeDiffBody(body, rows, lang) {
        body.classList.add('fc-diff-virt');
        var sizer = document.createElement('div'); sizer.className = 'fc-diff-sizer';
        var win = document.createElement('div'); win.className = 'fc-diff-window';
        sizer.appendChild(win); body.appendChild(sizer);
        var rowH = DIFF_ROW_FALLBACK_H, measured = false, lastStart = -1, lastEnd = -1;
        var raf = window.requestAnimationFrame ? window.requestAnimationFrame.bind(window)
            : function (f) { return setTimeout(f, 16); };
        function applyHeight() { sizer.style.height = (rows.length * rowH) + 'px'; }
        function renderWindow() {
            var top = body.scrollTop;
            var viewH = body.clientHeight || 360;
            var start = Math.max(0, Math.floor(top / rowH) - DIFF_WINDOW_BUFFER);
            var end = Math.min(rows.length, Math.ceil((top + viewH) / rowH) + DIFF_WINDOW_BUFFER);
            if (start === lastStart && end === lastEnd) return;
            lastStart = start; lastEnd = end;
            var html = '';
            for (var i = start; i < end; i++) html += rowHtml(rows[i], lang);
            win.style.transform = 'translateY(' + (start * rowH) + 'px)';
            win.innerHTML = html;
        }
        function measure() {
            if (measured) return;
            var probe = win.firstChild;
            var h = (probe && probe.getBoundingClientRect) ? probe.getBoundingClientRect().height : 0;
            if (h && h > 4) { rowH = h; measured = true; applyHeight(); lastStart = lastEnd = -1; renderWindow(); }
        }
        applyHeight();
        renderWindow();
        raf(function () { measure(); if (!measured) raf(measure); });
        body.addEventListener('scroll', function () {
            if (body.__virtPending) return;
            body.__virtPending = true;
            raf(function () { body.__virtPending = false; if (!measured) measure(); renderWindow(); });
        });
    }
    function buildDiffCard(file, diff, opts) {
        opts = opts || {};
        var lang = langForFile(file);
        var parsed = parseDiff(diff);
        var digits = String(Math.max(parsed.maxNo, 1)).length;
        var card = document.createElement('div'); card.className = 'fc-diff-card';
        card.style.setProperty('--fc-gut', (digits + 1) + 'ch');
        var bar = document.createElement('div'); bar.className = 'fc-diff-bar';
        bar.innerHTML =
            '<span class="fc-diff-fic">' + svg('file') + '</span>'
            + '<span class="fc-diff-path" title="' + escapeHtml(file) + '"><bdi>' + escapeHtml(file) + '</bdi></span>'
            + '<span class="fc-diff-lang">' + escapeHtml(langBadge(lang, file)) + '</span>'
            + '<span class="fc-diff-stat"><span class="add">+' + parsed.adds + '</span><span class="del">−' + parsed.dels + '</span></span>';
        var actions = document.createElement('div'); actions.className = 'fc-diff-actions';
        var copyBtn = document.createElement('button'); copyBtn.type = 'button'; copyBtn.className = 'fc-diff-btn'; copyBtn.setAttribute('aria-label', 'Copy diff');
        copyBtn.innerHTML = svg('copy') + '<span>Copy</span>';
        copyBtn.addEventListener('click', function () {
            try {
                navigator.clipboard.writeText(String(diff || '')).then(function () {
                    copyBtn.classList.add('is-copied');
                    var s = copyBtn.querySelector('span'); var old = s ? s.textContent : '';
                    if (s) s.textContent = 'Copied';
                    setTimeout(function () { copyBtn.classList.remove('is-copied'); if (s) s.textContent = old; }, 1400);
                });
            } catch (_e) { /* clipboard unavailable */ }
        });
        actions.appendChild(copyBtn);
        if (opts.keepRevert) {
            var keepBtn = document.createElement('button'); keepBtn.type = 'button'; keepBtn.className = 'fc-diff-btn'; keepBtn.textContent = 'Keep';
            var revBtn = document.createElement('button'); revBtn.type = 'button'; revBtn.className = 'fc-diff-btn'; revBtn.textContent = 'Revert';
            function settleCard(state, label) {
                card.classList.add(state);
                keepBtn.disabled = true; revBtn.disabled = true;
                var badge = bar.querySelector('.fc-diff-state');
                if (!badge) { badge = document.createElement('span'); badge.className = 'fc-diff-state'; bar.insertBefore(badge, actions); }
                badge.classList.add('is-' + state);
                badge.textContent = label;
            }
            function failNote(verb, res) {
                keepBtn.disabled = false; revBtn.disabled = false;
                var why = (res && res.reason) ? res.reason : (res && res.error) ? res.error : 'please try again';
                forgeToast('Could not ' + verb + ' ' + file + ' — ' + why, 'error');
                appendNote('is-warn', 'alert', 'Could not ' + verb + ' ' + file + ' — ' + why);
            }
            keepBtn.addEventListener('click', async function () {
                keepBtn.disabled = true; revBtn.disabled = true;
                var res;
                try { res = await fetch('/api/evolve/agent/keep', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ file: file }) }).then(function (r) { return r.json(); }); }
                catch (_e) { res = null; }
                if (res && res.ok) { settleCard('kept', 'Kept'); forgeToast('Kept ' + file, 'success'); }
                else { failNote('keep', res); }
            });
            revBtn.addEventListener('click', async function () {
                keepBtn.disabled = true; revBtn.disabled = true;
                var res;
                try { res = await fetch('/api/evolve/agent/revert', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ file: file }) }).then(function (r) { return r.json(); }); }
                catch (_e) { res = null; }
                if (res && res.clean) { settleCard('reverted', 'Reverted'); forgeToast('Reverted ' + file, 'success'); }
                else { failNote('revert', res); }
            });
            actions.appendChild(keepBtn); actions.appendChild(revBtn);
        }
        bar.appendChild(actions);
        var body = document.createElement('div'); body.className = 'fc-diff-body';
        renderDiffRows(body, parsed.rows, lang);
        card.appendChild(bar); card.appendChild(body);
        return card;
    }
    function baseName(path) {
        var s = String(path || '');
        var i = Math.max(s.lastIndexOf('/'), s.lastIndexOf('\\'));
        return i >= 0 ? s.slice(i + 1) : s;
    }
    function artifactUrl(cid, file) {
        var segs = String(file || '').split('/').map(function (s) { return encodeURIComponent(s); });
        return '/api/evolve/agent/artifact/' + encodeURIComponent(String(cid || '')) + '/' + segs.join('/');
    }
    function iconForArtifact(kind) {
        switch (kind) {
            case 'html': return 'window';
            case 'image': return 'image';
            case 'markdown': return 'file';
            case 'data': return 'table';
            default: return 'file';
        }
    }
    function kindLabel(art) {
        if (art.kind === 'html') return 'PAGE';
        if (art.kind === 'image') return 'IMAGE';
        if (art.kind === 'markdown') return 'MD';
        if (art.kind === 'data') return String(art.ext || 'data').toUpperCase();
        return 'FILE';
    }
    function parseCsv(text) {
        var rows = [], row = [], field = '', i = 0, inQ = false;
        var s = String(text || '');
        while (i < s.length) {
            var c = s[i];
            if (inQ) {
                if (c === '"') { if (s[i + 1] === '"') { field += '"'; i += 2; continue; } inQ = false; i++; continue; }
                field += c; i++; continue;
            }
            if (c === '"') { inQ = true; i++; continue; }
            if (c === ',') { row.push(field); field = ''; i++; continue; }
            if (c === '\r') { i++; continue; }
            if (c === '\n') { row.push(field); rows.push(row); row = []; field = ''; i++; continue; }
            field += c; i++;
        }
        if (field !== '' || row.length) { row.push(field); rows.push(row); }
        return rows;
    }
    function tableFromRows(rows) {
        var MAX_ROWS = 50, MAX_COLS = 24;
        var table = document.createElement('table'); table.className = 'fc-art-table';
        var limited = rows.slice(0, MAX_ROWS + 1); // +1 for a header row
        for (var r = 0; r < limited.length; r++) {
            var tr = document.createElement('tr');
            var cells = limited[r].slice(0, MAX_COLS);
            for (var c = 0; c < cells.length; c++) {
                var cell = document.createElement(r === 0 ? 'th' : 'td');
                cell.textContent = String(cells[c]);
                tr.appendChild(cell);
            }
            table.appendChild(tr);
        }
        return table;
    }
    function renderDataPreview(body, art, text) {
        if (art.ext === 'csv') {
            var rows = parseCsv(text);
            if (rows.length) { body.appendChild(tableFromRows(rows)); return; }
        }
        if (art.ext === 'json') {
            var data = null;
            try { data = JSON.parse(text); } catch (_e) { data = undefined; }
            if (Array.isArray(data) && data.length && typeof data[0] === 'object' && data[0] !== null && !Array.isArray(data[0])) {
                var cols = [];
                for (var k in data[0]) { if (Object.prototype.hasOwnProperty.call(data[0], k)) cols.push(k); }
                var rws = [cols.slice()];
                for (var i = 0; i < data.length && i < 50; i++) {
                    var rec = data[i] || {};
                    rws.push(cols.map(function (col) {
                        var v = rec[col];
                        return (v === null || typeof v === 'undefined') ? '' : (typeof v === 'object' ? JSON.stringify(v) : String(v));
                    }));
                }
                body.appendChild(tableFromRows(rws));
                return;
            }
            if (typeof data !== 'undefined') {
                var pre = document.createElement('pre'); pre.className = 'fc-art-json';
                pre.textContent = JSON.stringify(data, null, 2);
                body.appendChild(pre);
                return;
            }
        }
        var raw = document.createElement('pre'); raw.className = 'fc-art-json';
        raw.textContent = String(text || '');
        body.appendChild(raw);
    }
    function buildArtifactCard(art, cid) {
        if (!art || !art.file || !art.kind) return null;
        var url = artifactUrl(cid, art.file);
        var title = baseName(art.file);
        var card = document.createElement('div'); card.className = 'fc-art-card';
        var bar = document.createElement('div'); bar.className = 'fc-art-bar';
        bar.innerHTML =
            '<span class="fc-art-ic">' + svg(iconForArtifact(art.kind)) + '</span>'
            + '<span class="fc-art-title" title="' + escapeHtml(art.file) + '"><bdi>' + escapeHtml(title) + '</bdi></span>'
            + '<span class="fc-art-kind">' + escapeHtml(kindLabel(art)) + '</span>';
        var open = document.createElement('a'); open.className = 'fc-art-open';
        open.href = url; open.target = '_blank'; open.rel = 'noopener noreferrer';
        open.innerHTML = svg('external') + '<span>Open</span>';
        bar.appendChild(open);
        card.appendChild(bar);
        var body = document.createElement('div'); body.className = 'fc-art-body fc-art-' + art.kind;
        if (art.kind === 'html') {
            var frame = document.createElement('iframe'); frame.className = 'fc-art-frame';
            frame.setAttribute('sandbox', 'allow-scripts allow-forms allow-popups');
            frame.setAttribute('loading', 'lazy');
            frame.setAttribute('title', title);
            frame.src = url;
            body.appendChild(frame);
        } else if (art.kind === 'image') {
            var img = document.createElement('img'); img.className = 'fc-art-img';
            img.alt = title; img.loading = 'lazy'; img.src = url;
            body.appendChild(img);
        } else if (art.kind === 'markdown') {
            var mdBox = document.createElement('div'); mdBox.className = 'fc-art-md markdown-body';
            mdBox.textContent = 'Loading…';
            body.appendChild(mdBox);
            fetch(url).then(function (r) { return r.text(); }).then(function (txt) {
                mdBox.innerHTML = mdHtml(txt); highlightIn(mdBox);
            }).catch(function () { mdBox.textContent = 'Could not load preview.'; });
        } else if (art.kind === 'data') {
            var dataBox = document.createElement('div'); dataBox.className = 'fc-art-data';
            dataBox.textContent = 'Loading…';
            body.appendChild(dataBox);
            fetch(url).then(function (r) { return r.text(); }).then(function (txt) {
                dataBox.innerHTML = '';
                renderDataPreview(dataBox, art, txt);
            }).catch(function () { dataBox.textContent = 'Could not load preview.'; });
        }
        card.appendChild(body);
        return card;
    }
    function renderArtifacts(list, cid) {
        if (!list || !list.length) return;
        cid = cid || currentConvoId;
        if (!cid) return;
        var stack = ensureAgentStack(); if (!stack) return;
        for (var i = 0; i < list.length; i++) {
            var card = buildArtifactCard(list[i], cid);
            if (card) stack.appendChild(card);
        }
        follow();
    }
    var convoSummaries = [];   // cached summaries from /conversations (newest first)
    var railQuery = '';        // current client-side search filter (lowercased)
    var railUserPref = null;   // null = auto (by viewport), true/false = user choice
    function startOfLocalDay(ms) { var d = new Date(ms); return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime(); }
    function bucketFor(iso) {
        var t = Date.parse(String(iso || ''));
        if (isNaN(t)) return 3;
        var diffDays = Math.round((startOfLocalDay(Date.now()) - startOfLocalDay(t)) / 86400000);
        if (diffDays <= 0) return 0;
        if (diffDays === 1) return 1;
        if (diffDays <= 7) return 2;
        return 3;
    }
    var BUCKET_LABELS = ['Today', 'Yesterday', 'Last 7 days', 'Older'];
    function relTime(iso) {
        var t = Date.parse(String(iso || ''));
        if (isNaN(t)) return '';
        var secs = Math.max(0, Math.round((Date.now() - t) / 1000));
        if (secs < 45) return 'just now';
        var mins = Math.round(secs / 60);
        if (mins < 60) return mins + 'm ago';
        var hrs = Math.round(mins / 60);
        if (hrs < 24) return hrs + 'h ago';
        var days = Math.round(hrs / 24);
        if (days < 7) return days + 'd ago';
        try { return new Date(t).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }); }
        catch (_e) { return ''; }
    }
    function modelLabel(m) {
        var s = String(m || '').trim(); if (!s) return '';
        var tier = s.indexOf(':') !== -1 ? s.split(':').pop() : s;
        var map = { sonnet: 'Sonnet', opus: 'Opus', fable: 'Fable', gpt: 'GPT-5.5', haiku: 'Haiku' };
        return map[tier.toLowerCase()] || (tier.charAt(0).toUpperCase() + tier.slice(1));
    }
    function setActiveConvo(id) {
        var list = el('forgeCodeRailList'); if (!list) return;
        list.querySelectorAll('.fc-convo').forEach(function (row) {
            row.classList.toggle('is-active', row.getAttribute('data-id') === String(id || ''));
        });
    }
    function railRowHtml(c) {
        var title = (c.title && String(c.title).trim()) || 'Untitled build';
        var meta = relTime(c.updated_at);
        var model = modelLabel(c.last_model);
        if (model) meta += (meta ? ' · ' : '') + model;
        var active = String(c.id) === String(currentConvoId || '');
        return '<div class="fc-convo' + (active ? ' is-active' : '') + '" data-id="' + escapeHtml(String(c.id)) + '">'
            + '<button type="button" class="fc-convo-open" data-act="open" title="' + escapeHtml(title) + '">'
            + '<span class="fc-convo-title">' + escapeHtml(title) + '</span>'
            + '<span class="fc-convo-meta">' + escapeHtml(meta) + '</span>'
            + '</button>'
            + '<div class="fc-convo-actions">'
            + '<button type="button" class="fc-convo-act" data-act="rename" aria-label="Rename conversation" title="Rename">' + svg('pencil') + '</button>'
            + '<button type="button" class="fc-convo-act fc-convo-del" data-act="delete" aria-label="Delete conversation" title="Delete">' + svg('trash') + '</button>'
            + '</div></div>';
    }
    function renderRail() {
        var list = el('forgeCodeRailList'); if (!list) return;
        var q = railQuery;
        var items = convoSummaries.filter(function (c) {
            if (!c || !c.id) return false;
            if (!q) return true;
            return String(c.title || '').toLowerCase().indexOf(q) !== -1;
        });
        if (!items.length) {
            list.innerHTML = '<div class="fc-rail-empty">' + (q ? 'No conversations match.' : 'No conversations yet.') + '</div>';
            return;
        }
        var buckets = [[], [], [], []];
        for (var i = 0; i < items.length; i++) buckets[bucketFor(items[i].updated_at)].push(items[i]);
        var html = '';
        for (var b = 0; b < buckets.length; b++) {
            if (!buckets[b].length) continue;
            html += '<div class="fc-rail-group"><div class="fc-rail-group-label">' + escapeHtml(BUCKET_LABELS[b]) + '</div>';
            for (var j = 0; j < buckets[b].length; j++) html += railRowHtml(buckets[b][j]);
            html += '</div>';
        }
        list.innerHTML = html;
    }
    async function refreshConvos() {
        var data;
        try { data = await fetch('/api/evolve/agent/conversations').then(function (r) { return r.json(); }); }
        catch (_e) { return; }
        if (!data || !data.ok) return;
        convoSummaries = data.conversations || [];
        renderRail();
    }
    function applyRailState() {
        var wrap = document.querySelector('.forge-code-wrap'); if (!wrap) return;
        var collapsed = (railUserPref === null) ? (window.innerWidth < 700) : railUserPref;
        wrap.classList.toggle('is-rail-collapsed', collapsed);
    }
    function toggleRail() {
        var wrap = document.querySelector('.forge-code-wrap');
        var collapsed = !!(wrap && wrap.classList.contains('is-rail-collapsed'));
        railUserPref = !collapsed; // collapse when shown, expand when hidden
        applyRailState();
    }
    async function renameConvo(id, row) {
        if (!row) return;
        var titleEl = row.querySelector('.fc-convo-title'); if (!titleEl) return;
        if (row.querySelector('.fc-convo-rename')) return; // already editing
        var current = titleEl.textContent || '';
        var input = document.createElement('input');
        input.type = 'text'; input.className = 'fc-convo-rename'; input.value = current;
        input.setAttribute('aria-label', 'New conversation title');
        titleEl.replaceWith(input);
        input.focus(); input.select();
        var done = false; // guards both restore (DOM swap) and commit (one POST)
        function restore(text) {
            if (done) return; done = true;
            var span = document.createElement('span'); span.className = 'fc-convo-title';
            span.textContent = text; input.replaceWith(span);
        }
        async function commit() {
            if (done) return;
            var next = input.value.trim();
            if (!next || next === current) { restore(current); return; }
            restore(next); // optimistic; refresh below reconciles with the server
            var res;
            try {
                res = await fetch('/api/evolve/agent/conversations/' + encodeURIComponent(id) + '/rename', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title: next })
                }).then(function (r) { return r.json(); });
            } catch (_e) { res = null; }
            if (!res || !res.ok) { appendNote('is-warn', 'alert', 'Could not rename that conversation'); }
            refreshConvos();
        }
        input.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { e.preventDefault(); commit(); }
            else if (e.key === 'Escape') { e.preventDefault(); restore(current); }
        });
        input.addEventListener('blur', function () { commit(); });
    }
    async function deleteConvo(id, row) {
        if (!id) return;
        var title = row ? (row.querySelector('.fc-convo-title') || {}).textContent : '';
        if (typeof window.confirm === 'function' && !window.confirm('Delete "' + (title || 'this conversation') + '"? This cannot be undone.')) return;
        var res;
        try {
            res = await fetch('/api/evolve/agent/conversations/' + encodeURIComponent(id), { method: 'DELETE' })
                .then(function (r) { return r.json(); });
        } catch (_e) { res = null; }
        if (!res || !res.ok) { appendNote('is-warn', 'alert', 'Could not delete that conversation'); return; }
        if (String(id) === String(currentConvoId || '')) window.forgeCodeNewConversation();
        refreshConvos();
    }
    async function resumeConversation(id) {
        var data;
        try { data = await fetch('/api/evolve/agent/conversations/' + encodeURIComponent(id)).then(function (r) { return r.json(); }); }
        catch (_e) { appendNote('is-warn', 'alert', 'Could not load that conversation'); return; }
        if (!data || !data.ok || !data.conversation) { appendNote('is-warn', 'alert', 'Could not load that conversation'); return; }
        currentConvoId = String(id);
        pendingSourceItem = null;
        clearTranscript();
        var turns = data.conversation.turns || [];
        var lastModel = null;
        for (var i = 0; i < turns.length; i++) {
            var turn = turns[i]; if (!turn) continue;
            if (turn.role === 'user') {
                appendUserRow(turn.text || '');
            } else {
                startAgentTurn();
                if (turn.transcript) replayTranscript(turn.transcript);
                else appendSay(turn.text || '');
                if (turn.artifacts && turn.artifacts.length) renderArtifacts(turn.artifacts, currentConvoId);
                if (turn.model) lastModel = turn.model;
            }
        }
        finalizeTurn();
        if (lastModel) { var m = el('forgeCodeModel'); if (m) m.value = lastModel; }
        setActiveConvo(currentConvoId);
        renderChanges();
        jumpBottom();
    }
    function emptyHintHtml() {
        return '<div class="fc-empty">'
            + '<div class="fc-empty-glyph">' + svg('spark') + '</div>'
            + '<div class="fc-empty-title">Build with Thomas Code</div>'
            + '<div>Describe what you want to build or change in the composer below, then send. '
            + 'Thomas works in the live repo on your subscription and shows its edits here — like talking to Claude Code. Git is your undo.</div>'
            + '</div>';
    }
    window.forgeCodeNewConversation = function () {
        currentConvoId = null;
        pendingSourceItem = null;
        clearTranscript();
        var t = tx(); if (t) t.innerHTML = emptyHintHtml();
        setActiveConvo(null);
    };
    function seedContext(src) {
        var t = tx(); if (!t) return;
        if (src && (src.title || src.rationale)) {
            startAgentTurn();
            var stack = ensureAgentStack();
            if (stack) {
                var note = document.createElement('div'); note.className = 'fc-status'; note.textContent = 'Handed off from an Evolve idea';
                stack.appendChild(note);
                var bubble = document.createElement('div'); bubble.className = 'message-content assistant-bubble';
                var md = (src.title ? ('**' + src.title + '**\n\n') : '') + (src.rationale || '');
                bubble.innerHTML = mdHtml(md);
                highlightIn(bubble);
                stack.appendChild(bubble);
            }
            var hint = document.createElement('div'); hint.className = 'fc-empty';
            hint.textContent = 'Review the prefilled message in the composer below, then send to build it.';
            t.appendChild(hint);
            startAgentTurn(); // the user's send begins a fresh assistant turn
        } else {
            t.innerHTML = emptyHintHtml();
        }
    }
    window.forgeCodeStartConversation = async function (seed) {
        seed = seed || {};
        var src = (seed.source_evolve_item && typeof seed.source_evolve_item === 'object') ? seed.source_evolve_item : null;
        var body = { title: seed.title || 'Code session', source_evolve_item: src };
        var resp;
        try {
            resp = await fetch('/api/evolve/agent/conversations/new', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            }).then(function (r) { return r.json(); });
        } catch (_e) { resp = null; }
        clearTranscript();
        seedContext(src);
        pendingSourceItem = src;
        currentConvoId = (resp && resp.ok && resp.conversation && resp.conversation.id) ? String(resp.conversation.id) : null;
        refreshConvos();
    };
    var MAX_RECONNECT = 3;
    var reconnectAttempts = 0;
    var reconnectTimer = null;
    function ensureReconnectBar() {
        var bar = el('forgeCodeReconnect'); if (bar) return bar;
        var main = document.querySelector('.forge-code-main'); if (!main) return null;
        bar = document.createElement('div');
        bar.id = 'forgeCodeReconnect';
        bar.className = 'fc-reconnect';
        bar.hidden = true;
        bar.innerHTML = svg('spinner', 'fc-reconnect-ic') + '<span class="fc-reconnect-text"></span>';
        var changes = el('forgeCodeChanges');
        if (changes && changes.parentNode === main) main.insertBefore(bar, changes);
        else main.appendChild(bar);
        return bar;
    }
    function showReconnecting(attempt, max) {
        var bar = ensureReconnectBar(); if (!bar) return;
        var t = bar.querySelector('.fc-reconnect-text');
        if (t) t.textContent = 'Reconnecting… (attempt ' + attempt + ' of ' + max + ')';
        bar.hidden = false;
    }
    function hideReconnecting() { var bar = el('forgeCodeReconnect'); if (bar) bar.hidden = true; }
    function clearReconnect() {
        if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
        reconnectAttempts = 0;
        hideReconnecting();
    }
    function resetCurrentAgentTurn() {
        try {
            if (agentStack) {
                var row = (agentStack.closest && agentStack.closest('.message-row')) || agentStack.parentNode;
                if (row && row.parentNode) row.parentNode.removeChild(row);
            }
        } catch (_e) { /* ignore */ }
        startAgentTurn();
    }
    function openStream() {
        clearReconnect();
        stick = true; newCount = 0; updateJump(); // follow the new run from the first token
        connectStream();
    }
    function connectStream() {
        if (es) { try { es.close(); } catch (_e) { /* ignore */ } }
        es = new EventSource('/api/evolve/agent/stream');
        showStop(true);
        es.onmessage = function (ev) {
            if (reconnectAttempts) { clearReconnect(); setStatus('working', true); }
            try {
                var d = JSON.parse(ev.data);
                if (d.type === 'output') { renderEvent(d); return; }
                if (d.type !== 'done') return;
                var rc = d.returncode;
                var changed = d.changed_files || [];
                finalizeTurn();
                clearReconnect(); // a clean terminal frame -> no reconnect owed
                if (rc !== 0) {
                    appendBuildError(plainCause(safeString(d && (d.error || d.detail || d.message)), rc), rc);
                } else if (changed.length > 0) {
                    renderArtifacts(d.artifacts, d.conversation_id || currentConvoId);
                    appendNote('is-done', 'check', 'Done — ' + changed.length + ' file' + (changed.length === 1 ? '' : 's') + ' changed');
                    renderChanges();
                } else if (sawSay) {
                    appendNote('is-done', 'check', 'Answered');
                } else if (sawAction) {
                    appendNote('is-warn', 'dash', 'No changes were needed.');
                } else if (!agentStack) {
                    appendNote('is-warn', 'alert', 'No response — try again.');
                }
                setStatus('idle', false);
                showStop(false);
                try { es.close(); } catch (_e) { /* ignore */ } es = null;
                refreshConvos();
                flushFollowup(); // the build finalized -> auto-send any queued follow-up
            } catch (_e) { /* ignore malformed frame */ }
        };
        es.onerror = function () {
            if (!es) return;
            try { es.close(); } catch (_e) { /* ignore */ }
            es = null;
            if (reconnectAttempts < MAX_RECONNECT) {
                reconnectAttempts++;
                setStatus('reconnecting', true);
                showReconnecting(reconnectAttempts, MAX_RECONNECT);
                var backoff = 350 * reconnectAttempts; // 350 / 700 / 1050 ms
                if (reconnectTimer) clearTimeout(reconnectTimer);
                reconnectTimer = setTimeout(function () {
                    reconnectTimer = null;
                    resetCurrentAgentTurn(); // replay re-renders this turn exactly once
                    connectStream();
                }, backoff);
                return;
            }
            clearReconnect();
            setStatus('idle', false); showStop(false); finalizeTurn();
            appendBuildError('The live connection to the build dropped and could not be restored after ' + MAX_RECONNECT + ' attempts.', null);
            flushFollowup();
        };
    }
    function stopBuild() {
        setStatus('idle', false);
        showStop(false);
        if (es) { try { es.close(); } catch (_e) { /* ignore */ } es = null; }
        clearReconnect(); // a manual Stop cancels any pending reconnect attempt
        finalizeTurn();
        cancelFollowup();
        appendNote('is-warn', 'stop', 'Stopped');
        try {
            var p = fetch('/api/evolve/agent/stop', { method: 'POST' });
            if (p && typeof p.catch === 'function') p.catch(function () { /* best effort */ });
        } catch (_e) { /* best effort */ }
    }
    function restoreComposer(msg) {
        var ta = el('composerTextarea');
        if (ta && !((ta.value || '').trim())) { ta.value = msg; ta.dispatchEvent(new Event('input')); }
    }
    function ensureQueuedBar() {
        var bar = el('forgeCodeQueued'); if (bar) return bar;
        var main = document.querySelector('.forge-code-main'); if (!main) return null;
        bar = document.createElement('div');
        bar.id = 'forgeCodeQueued';
        bar.className = 'fc-queued';
        bar.hidden = true;
        bar.innerHTML = svg('clock', 'fc-queued-ic')
            + '<span class="fc-queued-text">Queued — will send when this build finishes</span>'
            + '<button type="button" class="fc-queued-cancel">Cancel</button>';
        var changes = el('forgeCodeChanges');
        if (changes && changes.parentNode === main) main.insertBefore(bar, changes);
        else main.appendChild(bar);
        bar.querySelector('.fc-queued-cancel').addEventListener('click', cancelFollowup);
        return bar;
    }
    function showQueuedIndicator() { var bar = ensureQueuedBar(); if (bar) bar.hidden = false; }
    function hideQueuedIndicator() { var bar = el('forgeCodeQueued'); if (bar) bar.hidden = true; }
    function queueFollowup(msg) {
        pendingFollowup = msg;
        restoreComposer(msg);
        showQueuedIndicator();
    }
    function cancelFollowup() { pendingFollowup = null; hideQueuedIndicator(); }
    function flushFollowup() {
        if (!pendingFollowup || es) return;
        pendingFollowup = null;
        hideQueuedIndicator();
        var ta = el('composerTextarea');
        var msg = ((ta && ta.value) || '').trim();
        if (!msg) return;
        if (ta) { ta.value = ''; ta.dispatchEvent(new Event('input')); }
        void sendToBuild(msg);
    }
    async function sendToBuild(msg) {
        if (es) { queueFollowup(msg); return; }
        lastSentMessage = msg; // remember the turn so a build error can offer Retry
        var engine = (el('forgeCodeEngine') || {}).value || 'agent';
        var model = (el('forgeCodeModel') || {}).value || 'claude:sonnet';
        setStatus('working', true);
        showStop(true);
        appendUserRow(msg);
        startAgentTurn();
        jumpBottom();
        var body = { message: msg, engine: engine, model: model, effort: 'medium', conversation_id: currentConvoId };
        if (pendingSourceItem) body.source_evolve_item = pendingSourceItem;
        var resp, status = 0;
        try {
            var r = await fetch('/api/evolve/agent/send', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            status = r.status;
            resp = await r.json();
        } catch (_e) { resp = { ok: false, error: 'network error' }; }
        if (resp && resp.ok) {
            if (resp.conversation_id) currentConvoId = String(resp.conversation_id);
            pendingSourceItem = null;
            refreshConvos();
            openStream();
        } else if (status === 409 || (resp && resp.error === 'agent is already working')) {
            setStatus('idle', false);
            showStop(false);
            restoreComposer(msg);
            appendNote('is-warn', 'alert', 'Already working — wait or press Stop');
        } else {
            setStatus('idle', false);
            showStop(false);
            appendError((resp && resp.error) || 'could not start the build');
        }
    }
    async function renderChanges() {
        var panel = el('forgeCodeChanges'); if (!panel) return;
        var url = '/api/evolve/agent/changes';
        if (currentConvoId) url += '?cid=' + encodeURIComponent(currentConvoId);
        var data;
        try { data = await fetch(url).then(function (r) { return r.json(); }); }
        catch (_e) { return; }
        if (!data || !data.ok) return;
        var changed = data.changed || [];
        panel.innerHTML = '';
        if (!changed.length) return;
        for (var i = 0; i < changed.length; i++) {
            var item = changed[i]; if (!item) continue;
            var card = buildDiffCard((item.untracked ? '＋ ' : '') + item.file, item.diff || '', { keepRevert: true, untracked: !!item.untracked });
            panel.appendChild(card);
        }
    }
    function injectStyle() { /* all Forge Code styling lives in evolution.css (token-driven) */ }
    function mount() {
        var code = el('forgeCode'); if (!code) return false;
        if (code.querySelector('.forge-code-wrap')) return true;
        code.innerHTML = '<div class="forge-code-wrap">'
            + '<div class="forge-code-shell">'
            + '<button type="button" id="forgeCodeRailHandle" class="fc-rail-handle" aria-label="Show conversation history" title="Show history">' + svg('railRight') + '</button>'
            + '<aside class="forge-code-rail" id="forgeCodeRail" aria-label="Conversation history">'
            + '<div class="fc-rail-top">'
            + '<button type="button" id="forgeCodeRailNew" class="fc-rail-new">' + svg('plus') + '<span>New conversation</span></button>'
            + '<button type="button" id="forgeCodeRailCollapse" class="fc-rail-collapse" aria-label="Collapse history" title="Collapse history">' + svg('railLeft') + '</button>'
            + '</div>'
            + '<div class="fc-rail-search-wrap">' + svg('search', 'fc-rail-search-ic')
            + '<input type="search" id="forgeCodeRailSearch" class="fc-rail-search" placeholder="Search conversations" aria-label="Search conversations" autocomplete="off" />'
            + '</div>'
            + '<div class="fc-rail-list" id="forgeCodeRailList"></div>'
            + '</aside>'
            + '<div class="forge-code-main">'
            + '<div class="forge-code-head">'
            + '<div class="fc-sub">Tell Thomas what to build or change &mdash; type in the composer below (your normal chat bar). It builds in the live repo on your subscription and shows its work here. Git is your undo.</div>'
            + '<div class="forge-code-run">'
            + '<select id="forgeCodeEngine" aria-label="Build engine" title="Agent = build directly. Funnel = converge a plan across isolated agents first, then build."><option value="agent" selected>Agent</option><option value="funnel">Funnel</option></select>'
            + '<select id="forgeCodeModel" aria-label="Model" title="Which brain runs this build"><option value="claude:sonnet" selected>Claude Sonnet</option><option value="claude:opus">Claude Opus</option><option value="claude:fable">Claude Fable</option><option value="codex:gpt">GPT-5.5</option></select>'
            + '<span class="forge-code-status" id="forgeCodeStatus">idle</span>'
            + '<button id="forgeCodeStop" class="forge-code-stop" type="button" hidden>Stop</button>'
            + '</div></div>'
            + '<div class="forge-code-transcript" id="forgeCodeTranscript">' + emptyHintHtml() + '</div>'
            + '<div id="forgeCodeChanges" class="forge-code-changes"></div>'
            + '</div></div></div>';
        injectStyle();
        var trans = el('forgeCodeTranscript');
        if (trans && !trans.__forgeScroll) {
            trans.__forgeScroll = true;
            trans.addEventListener('scroll', function () { stick = nearBottom(trans); updateJump(); });
        }
        var jmain = document.querySelector('.forge-code-main');
        if (jmain && !el('forgeCodeJump')) {
            var jb = document.createElement('button');
            jb.id = 'forgeCodeJump';
            jb.type = 'button';
            jb.className = 'forge-code-jump';
            jb.hidden = true;
            jb.innerHTML = svg('arrow-down') + '<span class="fc-jump-label">Jump to latest</span>';
            jb.addEventListener('click', function () { jumpBottom(); });
            jmain.appendChild(jb);
        }
        var newBtn = el('forgeCodeRailNew');
        if (newBtn && !newBtn.__forgeWired) { newBtn.__forgeWired = true; newBtn.addEventListener('click', function () { window.forgeCodeNewConversation(); }); }
        var collapseBtn = el('forgeCodeRailCollapse');
        if (collapseBtn && !collapseBtn.__forgeWired) { collapseBtn.__forgeWired = true; collapseBtn.addEventListener('click', toggleRail); }
        var handleBtn = el('forgeCodeRailHandle');
        if (handleBtn && !handleBtn.__forgeWired) { handleBtn.__forgeWired = true; handleBtn.addEventListener('click', toggleRail); }
        var searchInput = el('forgeCodeRailSearch');
        if (searchInput && !searchInput.__forgeWired) {
            searchInput.__forgeWired = true;
            searchInput.addEventListener('input', function () { railQuery = (searchInput.value || '').trim().toLowerCase(); renderRail(); });
        }
        var list = el('forgeCodeRailList');
        if (list && !list.__forgeWired) {
            list.__forgeWired = true;
            list.addEventListener('click', function (e) {
                var btn = e.target.closest ? e.target.closest('[data-act]') : null;
                if (!btn) return;
                var row = btn.closest('.fc-convo'); if (!row) return;
                var id = row.getAttribute('data-id'); if (!id) return;
                var act = btn.getAttribute('data-act');
                if (act === 'open') { if (id !== String(currentConvoId || '')) resumeConversation(id); }
                else if (act === 'rename') { renameConvo(id, row); }
                else if (act === 'delete') { deleteConvo(id, row); }
            });
        }
        var stopBtn = el('forgeCodeStop');
        if (stopBtn && !stopBtn.__forgeWired) { stopBtn.__forgeWired = true; stopBtn.addEventListener('click', function () { void stopBuild(); }); }
        if (!window.__forgeRailResize) {
            window.__forgeRailResize = true;
            window.addEventListener('resize', applyRailState);
        }
        applyRailState();
        refreshConvos();
        return true;
    }
    window.forgeCodeMount = mount;
    window.forgeCodeOpenConversation = function (id) {
        if (!id) return;
        try { mount(); } catch (_e) { /* surface may already be mounted */ }
        return resumeConversation(String(id));
    };
    function interceptor(e) {
        if (!window.forgeCodeActive) return;
        var ta = el('composerTextarea'); var msg = ((ta && ta.value) || '').trim();
        if (!msg) return;
        e.stopImmediatePropagation();
        if (e.preventDefault) e.preventDefault();
        if (es) { queueFollowup(msg); return; }
        if (ta) { ta.value = ''; ta.dispatchEvent(new Event('input')); }
        void sendToBuild(msg);
    }
    function wireInterceptor() {
        var sb = el('sendBtn');
        if (sb && !sb.__forgeWired) { sb.__forgeWired = true; sb.addEventListener('click', interceptor, true); }
    }
    var tries = 0;
    var iv = setInterval(function () { tries++; wireInterceptor(); if ((el('sendBtn') && el('sendBtn').__forgeWired) || tries > 1500) clearInterval(iv); }, 500);
    wireInterceptor();
})();
