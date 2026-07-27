function ensureTaskDefinitionUi() {
    if (!taskContinuityPanel) return null;
    let root = taskContinuityPanel.querySelector('.task-definition-panel');
    if (!(root instanceof HTMLElement)) {
        root = document.createElement('section');
        root.className = 'task-definition-panel hidden';
        root.innerHTML = `
            <div class="task-definition-head">
                <strong data-role="title">Task contract</strong>
                <span class="task-continuity-status" data-role="phase">idle</span>
            </div>
            <p class="task-definition-summary" data-role="summary"></p>
            <p class="task-definition-good hidden" data-role="good"></p>
            <div class="task-definition-meta hidden" data-role="type"></div>
            <div class="task-definition-section hidden" data-role="acceptance-wrap">
                <span class="task-definition-section-title">Acceptance</span>
                <ul data-role="acceptance"></ul>
            </div>
            <div class="task-definition-section hidden" data-role="visible-wrap">
                <span class="task-definition-section-title">Visible success</span>
                <ul data-role="visible"></ul>
            </div>
            <div class="task-definition-eval hidden" data-role="evaluation"></div>
        `;
        const anchor = taskContinuityBlockersWrap || taskContinuityEventsList || taskContinuityPanel.lastElementChild;
        if (anchor && anchor.parentNode === taskContinuityPanel) {
            taskContinuityPanel.insertBefore(root, anchor);
        } else {
            taskContinuityPanel.appendChild(root);
        }
    }
    return {
        root,
        phase: root.querySelector('[data-role="phase"]'),
        summary: root.querySelector('[data-role="summary"]'),
        good: root.querySelector('[data-role="good"]'),
        type: root.querySelector('[data-role="type"]'),
        acceptanceWrap: root.querySelector('[data-role="acceptance-wrap"]'),
        acceptance: root.querySelector('[data-role="acceptance"]'),
        visibleWrap: root.querySelector('[data-role="visible-wrap"]'),
        visible: root.querySelector('[data-role="visible"]'),
        evaluation: root.querySelector('[data-role="evaluation"]'),
    };
}

function taskDefinitionPhaseLabel(statusRaw) {
    const status = safeString(statusRaw).toLowerCase();
    if (status === 'defining') return 'Defining task';
    if (status === 'executing') return 'Executing';
    if (status === 'evaluating') return 'Evaluating result';
    if (status === 'complete') return 'Evaluated';
    return 'idle';
}

function renderTaskDefinitionUi(definition, evaluation, statusRaw) {
    const ui = ensureTaskDefinitionUi();
    if (!ui) return;
    const hasDefinition = Boolean(definition && typeof definition === 'object');
    const hasEvaluation = Boolean(evaluation && typeof evaluation === 'object');
    ui.root.classList.toggle('hidden', !hasDefinition && !hasEvaluation);
    if (!hasDefinition && !hasEvaluation) return;

    const phaseLabel = taskDefinitionPhaseLabel(statusRaw);
    if (ui.phase instanceof HTMLElement) {
        ui.phase.textContent = phaseLabel;
        ui.phase.classList.remove('is-complete', 'is-blocked');
        if (safeString(evaluation?.status) === 'passed') ui.phase.classList.add('is-complete');
        if (safeString(evaluation?.status) === 'failed') ui.phase.classList.add('is-blocked');
    }
    if (ui.summary instanceof HTMLElement) {
        ui.summary.textContent = safeString(definition?.task_summary || evaluation?.summary || 'Task contract pending.');
    }
    if (ui.good instanceof HTMLElement) {
        const good = safeString(definition?.good_result_definition);
        ui.good.classList.toggle('hidden', !good);
        ui.good.textContent = good ? `Good result: ${good}` : '';
    }
    if (ui.type instanceof HTMLElement) {
        const typeLabel = safeString(definition?.deliverable_type).replace(/_/g, ' ');
        ui.type.classList.toggle('hidden', !typeLabel);
        ui.type.textContent = typeLabel ? `Deliverable: ${typeLabel}` : '';
    }
    if (ui.acceptanceWrap instanceof HTMLElement && ui.acceptance instanceof HTMLElement) {
        const acceptance = Array.isArray(definition?.acceptance_checks) ? definition.acceptance_checks.slice(0, 4) : [];
        ui.acceptanceWrap.classList.toggle('hidden', acceptance.length === 0);
        ui.acceptance.innerHTML = acceptance.map((item) => `<li>${escapeHtml(safeString(item))}</li>`).join('');
    }
    if (ui.visibleWrap instanceof HTMLElement && ui.visible instanceof HTMLElement) {
        const visible = Array.isArray(definition?.visible_success_criteria)
            ? definition.visible_success_criteria.slice(0, 3)
            : [];
        ui.visibleWrap.classList.toggle('hidden', visible.length === 0);
        ui.visible.innerHTML = visible.map((item) => `<li>${escapeHtml(safeString(item))}</li>`).join('');
    }
    if (ui.evaluation instanceof HTMLElement) {
        const summary = safeString(evaluation?.summary);
        const failed = Array.isArray(evaluation?.failed_checks) ? evaluation.failed_checks.slice(0, 3) : [];
        const passed = Array.isArray(evaluation?.passed_checks) ? evaluation.passed_checks.slice(0, 2) : [];
        const parts = [];
        if (summary) parts.push(`<strong>${escapeHtml(summary)}</strong>`);
        if (failed.length > 0) {
            parts.push(`Failed: ${escapeHtml(failed.join(' | '))}`);
        } else if (passed.length > 0) {
            parts.push(`Passed: ${escapeHtml(passed.join(' | '))}`);
        }
        ui.evaluation.className = `task-definition-eval${safeString(evaluation?.status) === 'failed' ? ' is-failed' : (safeString(evaluation?.status) === 'passed' ? ' is-passed' : '')}`;
        ui.evaluation.classList.toggle('hidden', parts.length === 0);
        ui.evaluation.innerHTML = parts.join('<br>');
    }
}

function chatTaskStatusTone(statusRaw) {
    const status = safeString(statusRaw).toLowerCase();
    if (['completed', 'complete', 'passed', 'succeeded'].includes(status)) return 'completed';
    if (['failed', 'blocked', 'abandoned', 'cancelled', 'dead'].includes(status)) return 'failed';
    if (['defining', 'spawning', 'starting', 'pending', 'queued'].includes(status)) return 'starting';
    if (['quiet', 'waiting', 'paused', 'idle'].includes(status)) return 'quiet';
    return 'running';
}

function chatTaskStatusLabel(statusRaw) {
    const status = safeString(statusRaw).toLowerCase();
    if (status === 'defining') return 'Defining task';
    if (status === 'executing') return 'Executing';
    if (status === 'evaluating') return 'Evaluating result';
    if (status === 'spawning' || status === 'starting') return 'Spawning';
    if (status === 'quiet' || status === 'waiting') return 'Waiting';
    if (status === 'paused') return 'Paused';
    if (['completed', 'complete', 'passed', 'succeeded'].includes(status)) return 'Completed';
    if (['failed', 'blocked', 'abandoned', 'cancelled', 'dead'].includes(status)) return 'Failed';
    return 'Running';
}

function chatTaskIsTerminal(statusRaw) {
    return ['completed', 'complete', 'passed', 'succeeded', 'failed', 'blocked', 'abandoned', 'cancelled', 'dead']
        .includes(safeString(statusRaw).toLowerCase());
}

function chatTaskFormatElapsed(startedAtRaw, endedAtRaw = 0) {
    const startedAt = Number(startedAtRaw || 0);
    if (!Number.isFinite(startedAt) || startedAt <= 0) return '--';
    const endedAt = Number(endedAtRaw || 0);
    const now = endedAt > 0 ? endedAt : Date.now();
    return missionFormatDurationMs(Math.max(1000, now - startedAt));
}

function chatTaskStableHash(inputRaw) {
    const input = safeString(inputRaw) || 'task';
    let hash = 0;
    for (let i = 0; i < input.length; i += 1) {
        hash = ((hash * 31) + input.charCodeAt(i)) >>> 0;
    }
    return hash >>> 0;
}

function chatAgentPresenceViewportBounds() {
    const sidebarRect = sidebar instanceof HTMLElement ? sidebar.getBoundingClientRect() : null;
    const composerRect = composerContainer instanceof HTMLElement ? composerContainer.getBoundingClientRect() : null;
    const left = Math.max(CHAT_AGENT_PRESENCE_FLOAT_PAD_X, Math.round((sidebarRect?.right || 0) + 10));
    const right = Math.max(left + 120, Math.round(window.innerWidth - CHAT_AGENT_PRESENCE_FLOAT_PAD_X - 84));
    const top = CHAT_AGENT_PRESENCE_FLOAT_PAD_TOP;
    const bottomLimit = composerRect ? composerRect.top - 78 : (window.innerHeight - CHAT_AGENT_PRESENCE_FLOAT_PAD_BOTTOM);
    const bottom = Math.max(top + 120, Math.round(bottomLimit));
    return {
        left,
        top,
        width: Math.max(120, right - left),
        height: Math.max(120, bottom - top),
    };
}

function chatAgentPresencePoint(activityId, indexHint = 0) {
    const bounds = chatAgentPresenceViewportBounds();
    const seed = chatTaskStableHash(`${activityId}|${indexHint}`);
    const xRatio = ((seed % 997) / 997);
    const yRatio = (((Math.floor(seed / 997) % 991)) / 991);
    return {
        x: Math.round(bounds.left + (Math.max(0, bounds.width - 88) * xRatio)),
        y: Math.round(bounds.top + (Math.max(0, bounds.height - 104) * yRatio)),
    };
}

function chatTaskCheckpointText(textRaw) {
    const clean = safeString(textRaw).replace(/\s+/g, ' ').trim();
    return clean.length > 180 ? `${clean.slice(0, 177)}...` : clean;
}

function _ensureArtifactStyles() {
    if (document.getElementById('thomasArtifactStyles')) return;
    const style = document.createElement('style');
    style.id = 'thomasArtifactStyles';
    style.textContent = `
    .message-task-artifact { margin-top: 8px; }
    .message-task-artifact-chip { display:inline-flex; align-items:center; gap:6px; padding:6px 12px;
        border-radius:8px; border:1px solid rgba(255,255,255,.18); background:rgba(255,255,255,.06);
        color:inherit; font-size:13px; cursor:pointer; text-decoration:none; }
    .message-task-artifact-chip:hover { background:rgba(255,255,255,.12); }
    .message-task-artifact-view { margin-top:8px; border-radius:8px; overflow:hidden; border:1px solid rgba(255,255,255,.12); }
    .message-task-artifact-view.hidden, .message-task-artifact.hidden { display:none; }
    .artifact-inline-frame { width:100%; height:460px; border:0; background:#fff; display:block; }
    .artifact-inline-img { max-width:100%; display:block; }
    .artifact-inline-text { margin:0; padding:12px; max-height:420px; overflow:auto; white-space:pre-wrap;
        font-family:var(--font-mono,monospace); font-size:12px; background:rgba(0,0,0,.25); }
    .thomas-preview-pane { position:fixed; top:0; right:0; width:42vw; min-width:360px; max-width:760px;
        height:100vh; background:#0d0f14; border-left:1px solid rgba(255,255,255,.14); z-index:9000;
        transform:translateX(100%); transition:transform .22s ease; display:flex; flex-direction:column;
        box-shadow:-12px 0 40px rgba(0,0,0,.45); }
    .thomas-preview-pane.open { transform:translateX(0); }
    .thomas-preview-head { display:flex; align-items:center; gap:10px; padding:10px 12px;
        border-bottom:1px solid rgba(255,255,255,.12); color:#e8e9ee; font-size:13px; }
    .thomas-preview-title { flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
    .thomas-preview-newtab, .thomas-preview-close { color:#cfd2da; text-decoration:none; cursor:pointer;
        background:none; border:0; font-size:15px; padding:2px 6px; border-radius:6px; }
    .thomas-preview-newtab:hover, .thomas-preview-close:hover { background:rgba(255,255,255,.12); }
    .thomas-preview-frame { flex:1; width:100%; border:0; background:#fff; }
    .session-deliverables { margin:14px 0 6px; padding:10px 12px; border-radius:10px;
        border:1px solid rgba(255,255,255,.12); background:rgba(255,255,255,.03); }
    .session-deliverables-head { font-size:11px; letter-spacing:.06em; text-transform:uppercase;
        opacity:.6; margin-bottom:8px; }
    .session-deliverable { margin:6px 0; }
    .session-deliverable-title { display:block; font-size:12px; opacity:.78; margin-bottom:4px; }
    `;
    document.head.appendChild(style);
}

// Right-side LIVE PREVIEW pane for web deliverables (apps/games): an iframe onto the
// loopback /deliverable URL so the user can actually watch the site/game the worker
// built — in-app, not a new tab. (Calvin: "a web browser thing that pops up on the
// right side so you can pull up the URL and show them their website/game.")
function openWebPreviewPane(url, title) {
    _ensureArtifactStyles();
    let pane = document.getElementById('thomasPreviewPane');
    if (!pane) {
        pane = document.createElement('div');
        pane.id = 'thomasPreviewPane';
        pane.className = 'thomas-preview-pane';
        pane.innerHTML =
            '<div class="thomas-preview-head">' +
            '<span class="thomas-preview-title" data-role="title"></span>' +
            '<a class="thomas-preview-newtab" data-role="newtab" target="_blank" rel="noopener" title="Open in new tab">↗</a>' +
            '<button type="button" class="thomas-preview-close" data-role="close" aria-label="Close preview">✕</button>' +
            '</div>' +
            // Worker-built deliverables are UNTRUSTED generated content served same-origin
            // (/deliverable/...). `allow-scripts` lets the game/app run; we deliberately do
            // NOT grant `allow-same-origin` — with it, the framed script would share Thomas's
            // origin and could read the parent app's cookies/localStorage and call its APIs as
            // the user. Without it the deliverable runs in an opaque origin: scripts execute,
            // but it is walled off from the host app. (Adversarial review 2026-06-17.)
            '<iframe class="thomas-preview-frame" data-role="frame" title="Live preview" ' +
            'sandbox="allow-scripts allow-forms"></iframe>';
        document.body.appendChild(pane);
        const closeBtn = pane.querySelector('[data-role="close"]');
        if (closeBtn) closeBtn.addEventListener('click', () => {
            pane.classList.remove('open');
            const f = pane.querySelector('[data-role="frame"]');
            if (f) f.setAttribute('src', 'about:blank');
        });
    }
    const frame = pane.querySelector('[data-role="frame"]');
    const titleEl = pane.querySelector('[data-role="title"]');
    const newtab = pane.querySelector('[data-role="newtab"]');
    if (titleEl) titleEl.textContent = title || 'Live preview';
    if (newtab) newtab.setAttribute('href', url);
    if (frame) frame.setAttribute('src', url);
    pane.classList.add('open');
}

// Toggle an INLINE viewer (pdf/image/text) inside a chat artifact card — opens IN chat,
// the way a frontier model presents a result. Clicking again collapses it.
function toggleInlineArtifact(view, url, kind, name) {
    if (!(view instanceof HTMLElement)) return;
    _ensureArtifactStyles();
    if (!view.classList.contains('hidden') && view.dataset.url === url) {
        view.classList.add('hidden');
        view.innerHTML = '';
        view.dataset.url = '';
        return;
    }
    view.dataset.url = url;
    if (kind === 'pdf') {
        // Same isolation invariant as the preview pane: worker output is untrusted and
        // served same-origin (/deliverable/...), so the inline viewer MUST be sandboxed
        // WITHOUT allow-same-origin or it could reach the host app's cookies/storage.
        // allow-scripts keeps the browser PDF viewer working. (Adversarial review 2026-06-17.)
        view.innerHTML = `<iframe class="artifact-inline-frame" src="${escapeHtml(url)}#toolbar=1" title="${escapeHtml(name)}" sandbox="allow-scripts allow-forms"></iframe>`;
    } else if (kind === 'image') {
        view.innerHTML = `<img class="artifact-inline-img" src="${escapeHtml(url)}" alt="${escapeHtml(name)}">`;
    } else {
        view.innerHTML = '<pre class="artifact-inline-text" data-role="text">Loading…</pre>';
        fetch(url)
            .then((r) => r.text())
            .then((t) => { const pre = view.querySelector('[data-role="text"]'); if (pre) pre.textContent = String(t).slice(0, 20000); })
            .catch(() => { const pre = view.querySelector('[data-role="text"]'); if (pre) pre.textContent = '(could not load this file)'; });
    }
    view.classList.remove('hidden');
}

// Reconcile-on-load: a task strip's artifact chip lives only in in-memory state, so a
// reload or chat-switch wiped every chip ("the badges disappear, I don't see a PDF").
// The completed deliverables ARE durable in the task ledger, so on load we rebuild a
// "Results in this chat" block from /delegations — the chips survive reloads and the
// user can always find what was built. (Calvin's "My Stuff" direction.)
async function reconcileSessionDeliverables(sid) {
    const sessionId = safeString(sid);
    // Idempotent: drop any prior block so switching chats never stacks duplicates.
    const prior = document.getElementById('thomasSessionDeliverables');
    if (prior) prior.remove();
    if (!sessionId || typeof fetchJsonSafe !== 'function') return;
    let resp;
    try {
        resp = await fetchJsonSafe(`/api/v2/chat/session/${encodeURIComponent(sessionId)}/delegations`);
    } catch (error) {
        return;
    }
    if (!resp || !resp.ok || !resp.data || typeof resp.data !== 'object') return;
    const dels = Array.isArray(resp.data.delegations) ? resp.data.delegations : [];
    const seen = new Set();
    const items = [];
    for (const d of dels) {
        if (!d || typeof d !== 'object') continue;
        const url = safeString(d.artifact_url);
        if (!url || seen.has(url)) continue;
        const state = safeString(d.state).toLowerCase();
        if (state !== 'completed' && state !== 'verified' && state !== 'done') continue;
        seen.add(url);
        items.push({
            url,
            kind: safeString(d.artifact_kind) || 'file',
            name: safeString(d.artifact_name) || 'result',
            summary: safeString(d.summary) || safeString(d.last_progress) || '',
        });
    }
    if (items.length) renderSessionDeliverablesStrip(items);
}

function renderSessionDeliverablesStrip(items) {
    if (typeof chatMessagesInner === 'undefined' || !chatMessagesInner) return;
    _ensureArtifactStyles();
    const block = document.createElement('div');
    block.id = 'thomasSessionDeliverables';
    block.className = 'session-deliverables';
    const rows = items.map((it) => {
        const openable = it.url && it.kind && it.kind !== 'file';
        const label = it.kind === 'web'
            ? 'Open live preview'
            : (it.kind === 'image' ? `View ${it.name}` : `Open ${it.name}`);
        const action = openable
            ? `<button type="button" class="message-task-artifact-chip" data-art-url="${escapeHtml(it.url)}" `
                + `data-art-kind="${escapeHtml(it.kind)}" data-art-name="${escapeHtml(it.name)}">${escapeHtml(label)}</button>`
            : `<a class="message-task-artifact-chip" href="${escapeHtml(it.url)}" download>Download ${escapeHtml(it.name)}</a>`;
        const title = it.summary ? `<span class="session-deliverable-title">${escapeHtml(it.summary)}</span>` : '';
        return `<div class="session-deliverable" data-role="artifact">${title}${action}`
            + `<div class="message-task-artifact-view hidden" data-role="artifact-view"></div></div>`;
    }).join('');
    block.innerHTML = `<div class="session-deliverables-head">Results in this chat</div>${rows}`;
    chatMessagesInner.appendChild(block);
    // Same open behavior as the per-message strip chips (web -> right pane; else inline).
    block.querySelectorAll('[data-role="artifact"]').forEach((artifact) => {
        artifact.addEventListener('click', (ev) => {
            const chip = ev.target instanceof Element ? ev.target.closest('[data-art-url]') : null;
            if (!chip) return;
            const url = safeString(chip.getAttribute('data-art-url'));
            const kind = safeString(chip.getAttribute('data-art-kind'));
            const name = safeString(chip.getAttribute('data-art-name')) || 'result';
            if (!url) return;
            if (kind === 'web') {
                openWebPreviewPane(url, name);
            } else {
                const view = artifact.querySelector('[data-role="artifact-view"]');
                if (view instanceof HTMLElement) toggleInlineArtifact(view, url, kind, name);
            }
        });
    });
}

function appendDelegationResultMessage(evt, options = {}) {
    if (typeof renderMessage !== 'function' || typeof updateMessageTaskStrip !== 'function') return;
    const executionId = safeString(evt?.execution_id).replace(/[^A-Za-z0-9_-]/g, '');
    if (!executionId) return;
    const messageId = `task-result-${executionId}`;
    if (document.getElementById(messageId)) return;
    const status = safeString(options.status || evt?.state || evt?.type).toLowerCase();
    const failed = status.includes('failed') || safeString(evt?.type) === 'delegation_failed';
    const artifactUrl = safeString(evt?.artifact_url);
    const artifactName = safeString(evt?.artifact_name);
    const artifactKind = safeString(evt?.artifact_kind);
    let summary = safeString(options.summary || evt?.last_progress || evt?.summary || artifactName)
        .replace(/^\s*\[[^\]]+\]\s*/, '')
        .trim();
    summary = summary.replace(/no a first event/gi, 'no first event');
    const fallback = failed
        ? 'Thomas could not complete the background task.'
        : (artifactName ? `Result ready: ${artifactName}.` : 'Task finished.');
    renderMessage({
        role: 'assistant',
        content: failed ? `Task failed: ${summary || fallback}` : `Task finished: ${summary || fallback}`,
        id: messageId,
    });
    updateMessageTaskStrip(messageId, {
        sessionId: safeString(evt?.session_id),
        status: failed ? 'failed' : 'completed',
        summary: summary || artifactName || fallback,
        checkpoint: failed ? 'Needs review.' : 'Result ready.',
        artifactUrl,
        artifactName,
        artifactKind,
    });
    if (typeof syncActiveChatSidebarEntry === 'function') syncActiveChatSidebarEntry();
    if (typeof persistActiveChat === 'function') void persistActiveChat({ quiet: true });
}

function chatTaskStripState(messageId) {
    const normalizedId = safeString(messageId);
    if (!normalizedId) return null;
    if (!chatTaskStripStateByMessageId.has(normalizedId)) {
        chatTaskStripStateByMessageId.set(normalizedId, {
            messageId: normalizedId,
            sessionId: '',
            status: 'spawning',
            summary: '',
            latestCheckpoint: '',
            checkpoints: [],
            startedAt: 0,
            endedAt: 0,
            artifactUrl: '',
            artifactName: '',
            artifactKind: '',
        });
    }
    return chatTaskStripStateByMessageId.get(normalizedId) || null;
}

function ensureMessageTaskStrip(messageId) {
    _ensureArtifactStyles();
    const row = document.getElementById(safeString(messageId));
    if (!(row instanceof HTMLElement)) return null;
    const stack = row.querySelector('.message-stack');
    if (!(stack instanceof HTMLElement)) return null;

    let strip = stack.querySelector('.message-task-strip');
    if (!(strip instanceof HTMLElement)) {
        strip = document.createElement('section');
        strip.className = 'message-task-strip hidden';
        strip.innerHTML = `
            <div class="message-task-strip-head">
                <span class="message-task-strip-badge" data-role="badge">Running</span>
                <span class="message-task-strip-elapsed" data-role="elapsed">--</span>
                <button type="button" class="message-task-strip-open" data-role="open">Open Office</button>
            </div>
            <p class="message-task-strip-summary" data-role="summary"></p>
            <p class="message-task-strip-latest" data-role="latest"></p>
            <ul class="message-task-strip-checkpoints" data-role="checkpoints"></ul>
            <div class="message-task-artifact hidden" data-role="artifact"></div>
        `;
        const footer = stack.querySelector('.message-footer');
        if (footer instanceof HTMLElement) {
            stack.insertBefore(strip, footer);
        } else {
            stack.appendChild(strip);
        }
        const openBtn = strip.querySelector('[data-role="open"]');
        if (openBtn instanceof HTMLButtonElement) {
            openBtn.addEventListener('click', () => {
                const state = chatTaskStripState(messageId);
                if (!state) return;
                openOfficeForTaskContext({
                    sessionId: state.sessionId,
                    messageId,
                });
            });
        }
        // Artifact actions (delegated, so re-rendered chips stay wired). The deliverable
        // opens INLINE in chat (pdf/image/text) or, for a web app/game, in the right-side
        // live preview pane — never a new tab, never the old "▶ Play" button.
        const artifact = strip.querySelector('[data-role="artifact"]');
        if (artifact instanceof HTMLElement) {
            artifact.addEventListener('click', (ev) => {
                const chip = ev.target instanceof Element ? ev.target.closest('[data-art-url]') : null;
                if (!chip) return;
                const url = safeString(chip.getAttribute('data-art-url'));
                const kind = safeString(chip.getAttribute('data-art-kind'));
                const name = safeString(chip.getAttribute('data-art-name')) || 'result';
                if (!url) return;
                if (kind === 'web') {
                    openWebPreviewPane(url, name);
                } else {
                    const view = artifact.querySelector('[data-role="artifact-view"]');
                    if (view instanceof HTMLElement) toggleInlineArtifact(view, url, kind, name);
                }
            });
        }
    }

    return {
        root: strip,
        badge: strip.querySelector('[data-role="badge"]'),
        elapsed: strip.querySelector('[data-role="elapsed"]'),
        summary: strip.querySelector('[data-role="summary"]'),
        latest: strip.querySelector('[data-role="latest"]'),
        checkpoints: strip.querySelector('[data-role="checkpoints"]'),
        artifact: strip.querySelector('[data-role="artifact"]'),
    };
}

function renderMessageTaskStrip(messageId) {
    const state = chatTaskStripState(messageId);
    const ui = ensureMessageTaskStrip(messageId);
    if (!state || !ui) return;
    const tone = chatTaskStatusTone(state.status);
    const summaryText = chatTaskCheckpointText(state.summary) || 'Task accepted.';
    const latestText = chatTaskCheckpointText(state.latestCheckpoint)
        || (tone === 'completed'
            ? 'Task finished.'
            : tone === 'failed'
                ? 'Task hit a failure state.'
                : 'Waiting for the next checkpoint.');
    if (ui.root instanceof HTMLElement) {
        ui.root.classList.remove('hidden');
        ui.root.dataset.state = tone;
    }
    if (ui.badge instanceof HTMLElement) {
        ui.badge.className = `message-task-strip-badge tone-${tone}`;
        ui.badge.textContent = chatTaskStatusLabel(state.status);
    }
    if (ui.elapsed instanceof HTMLElement) {
        ui.elapsed.textContent = chatTaskFormatElapsed(state.startedAt, state.endedAt);
    }
    if (ui.summary instanceof HTMLElement) {
        ui.summary.textContent = summaryText;
    }
    if (ui.latest instanceof HTMLElement) {
        ui.latest.textContent = latestText;
    }
    if (ui.artifact instanceof HTMLElement) {
        // Surface the deliverable as a clickable chip: web apps/games open in the
        // right-side live preview; pdf/image/text open INLINE in chat; other files get a
        // download. Replaces the old new-tab "▶ Play" button.
        const url = safeString(state.artifactUrl);
        const kind = safeString(state.artifactKind);
        const name = safeString(state.artifactName) || 'result';
        if (url && kind && kind !== 'file') {
            const label = kind === 'web'
                ? 'Open live preview'
                : (kind === 'image' ? `View ${name}` : `Open ${name}`);
            const existing = ui.artifact.querySelector('[data-art-url]');
            // Rebuild the chip only when the artifact changed, so an opened inline view
            // is not clobbered on every status re-render.
            if (!existing || existing.getAttribute('data-art-url') !== url) {
                ui.artifact.innerHTML =
                    `<button type="button" class="message-task-artifact-chip" data-art-url="${escapeHtml(url)}" ` +
                    `data-art-kind="${escapeHtml(kind)}" data-art-name="${escapeHtml(name)}">${escapeHtml(label)}</button>` +
                    `<div class="message-task-artifact-view hidden" data-role="artifact-view"></div>`;
            }
            ui.artifact.classList.remove('hidden');
        } else if (url) {
            ui.artifact.innerHTML =
                `<a class="message-task-artifact-chip" href="${escapeHtml(url)}" download>Download ${escapeHtml(name)}</a>`;
            ui.artifact.classList.remove('hidden');
        } else {
            ui.artifact.classList.add('hidden');
            ui.artifact.innerHTML = '';
        }
    }
    if (ui.checkpoints instanceof HTMLElement) {
        const points = Array.isArray(state.checkpoints) ? state.checkpoints.slice(-3) : [];
        ui.checkpoints.classList.toggle('hidden', points.length === 0);
        ui.checkpoints.innerHTML = points.map((item) => {
            const label = chatTaskCheckpointText(item?.text);
            const when = Number(item?.at || 0) > 0 ? new Date(Number(item.at)).toLocaleTimeString() : '';
            return `<li><span>${escapeHtml(label)}</span>${when ? `<time>${escapeHtml(when)}</time>` : ''}</li>`;
        }).join('');
    }
}

function updateMessageTaskStrip(messageId, patch = {}) {
    const state = chatTaskStripState(messageId);
    if (!state) return null;
    const sessionId = safeString(patch.sessionId || state.sessionId);
    if (sessionId) {
        state.sessionId = sessionId;
        chatTaskMessageBySessionId.set(sessionId, state.messageId);
    }
    if (safeString(patch.artifactUrl)) {
        state.artifactUrl = safeString(patch.artifactUrl);
    }
    if (safeString(patch.artifactName)) {
        state.artifactName = safeString(patch.artifactName);
    }
    if (safeString(patch.artifactKind)) {
        state.artifactKind = safeString(patch.artifactKind);
    }
    const nextStatus = safeString(patch.status || state.status || 'running').toLowerCase() || 'running';
    state.status = nextStatus;
    if (!state.startedAt) {
        state.startedAt = Number(patch.startedAt || Date.now());
    } else if (Number(patch.startedAt) > 0) {
        state.startedAt = Number(patch.startedAt);
    }
    if (chatTaskIsTerminal(nextStatus)) {
        state.endedAt = Number(patch.endedAt || state.endedAt || Date.now());
    } else if (Number(patch.endedAt) > 0) {
        state.endedAt = Number(patch.endedAt);
    } else {
        state.endedAt = 0;
    }
    if (safeString(patch.summary)) {
        state.summary = safeString(patch.summary);
    }
    const checkpointText = chatTaskCheckpointText(patch.checkpoint);
    if (checkpointText) {
        state.latestCheckpoint = checkpointText;
        const last = state.checkpoints[state.checkpoints.length - 1];
        if (!last || safeString(last.text) !== checkpointText) {
            state.checkpoints.push({
                text: checkpointText,
                at: Number(patch.checkpointAt || Date.now()),
            });
            state.checkpoints = state.checkpoints.slice(-CHAT_TASK_STRIP_CHECKPOINT_LIMIT);
        }
    }
    renderMessageTaskStrip(messageId);
    chatTaskRuntimeEnsureTick();
    return state;
}

function officePixelAgentMarkup(extraClass = '', inlineStyle = '') {
    const classSuffix = safeString(extraClass).trim();
    const styleText = safeString(inlineStyle).trim();
    return `
        <span class="office-pixel-agent${classSuffix ? ` ${escapeHtml(classSuffix)}` : ''}"${styleText ? ` style="${escapeHtml(styleText)}"` : ''}>
            <span class="office-agent-head">
                <span class="office-agent-eye office-agent-eye-left"></span>
                <span class="office-agent-eye office-agent-eye-right"></span>
            </span>
            <span class="office-agent-body"></span>
            <span class="office-agent-leg office-agent-leg-left"></span>
            <span class="office-agent-leg office-agent-leg-right"></span>
        </span>
    `;
}

function chatTaskRobotAgentMarkup() {
    return '';
}

function chatAgentPresenceSyncRootVisibility() {
    removeChatAgentPresenceUi();
}

function chatAgentPresenceRemove(activityId, { immediate = false } = {}) {
    void immediate;
    chatAgentPresenceStateByActivityId.delete(safeString(activityId));
    removeChatAgentPresenceUi();
}

function removeChatAgentPresenceUi() {
    if (chatRobotWorldRaf) {
        window.cancelAnimationFrame(chatRobotWorldRaf);
        chatRobotWorldRaf = 0;
    }
    chatAgentPresenceStateByActivityId.clear();
    chatPrimaryPresenceState = null;
    try {
        chatPhysicsWorldDestroy();
    } catch (_) {}
    const root = document.getElementById('chatAgentPresence');
    if (root instanceof HTMLElement) root.remove();
    const legacyDock = document.getElementById(CHAT_ROBOT_DOCK_ID);
    if (legacyDock instanceof HTMLElement) legacyDock.remove();
}

function chatWorldEnsureUi() {
    removeChatAgentPresenceUi();
    return null;
}

function chatAgentPresenceShouldBeVisible() {
    return false;
}

function chatAgentPresenceSetOfficeContext(activityId, context = {}) {
    void activityId;
    void context;
}

function openOfficeForTaskContext(context = {}) {
    void context;
    setSidebarNavMode('office');
}

function chatAgentPresenceRender(state) {
    void state;
}

function chatAgentPresenceUpsert(activityId, patch = {}) {
    void activityId;
    void patch;
    return null;
}

function chatTaskRuntimeTick() {
    chatTaskStripStateByMessageId.forEach((state, messageId) => {
        if (!state) return;
        renderMessageTaskStrip(messageId);
    });
    chatTaskRuntimeStopIfIdle();
}

function chatTaskRuntimeEnsureTick() {
    if (chatTaskRuntimeTimer) return;
    chatTaskRuntimeTimer = window.setInterval(() => {
        chatTaskRuntimeTick();
    }, 1000);
}

function chatTaskRuntimeStopIfIdle() {
    const hasLiveStrip = [...chatTaskStripStateByMessageId.values()].some((state) => state && !chatTaskIsTerminal(state.status));
    if (hasLiveStrip) return;
    if (chatTaskRuntimeTimer) {
        window.clearInterval(chatTaskRuntimeTimer);
        chatTaskRuntimeTimer = 0;
    }
}

function setChatAgentPresence(activity) {
    void activity;
    removeChatAgentPresenceUi();
}

function chatRobotWorldShouldBeVisible() {
    return false;
}

function chatRobotWorldAmbientLine(state) {
    if (!state) return '';
    const mode = safeString(state.mode);
    if (safeString(state.kind) === 'primary' && chatRobotWorldTaskIsLive(state)) {
        return 'Coordinating the active run while helpers work.';
    }
    if (mode === 'sleep') return 'Idle until the next task starts.';
    if (mode === 'workout') return 'Ready for a larger task.';
    if (mode === 'inspect') return 'Checking the chat controls.';
    if (mode === 'perch') return 'Monitoring the active surface.';
    if (chatTaskIsTerminal(state.status)) {
        return safeString(state.status) === 'failed'
            ? 'This run failed; review is needed.'
            : 'Run complete.';
    }
    if (safeString(state.kind) === 'delegation') {
        return officePick([
            'Working the delegated task.',
            'Waiting for the next tool result.',
            'Tracking the next step.',
            'Checking task progress.',
        ]) || 'Tracking the next step.';
    }
    return officePick([
        'Ready for the next request.',
        'Monitoring the chat.',
        'Idle.',
        'Waiting for input.',
    ]) || 'Ready for the next request.';
}

function chatRobotWorldDetailLine(state) {
    if (!state) return '';
    if (chatTaskIsTerminal(state.status)) {
        return safeString(state.status) === 'failed'
            ? (safeString(state.summary || state.taskText) || 'This run failed before completion.')
            : (safeString(state.summary || state.taskText) || 'This run completed successfully.');
    }
    if (chatRobotWorldTaskIsLive(state)) {
        return safeString(state.summary || state.taskText) || 'Working the assigned task.';
    }
    return safeString(state.summary || state.taskText) || 'Standing by.';
}

function chatRobotWorldTaskIsLive(state) {
    return Boolean(state && !chatTaskIsTerminal(state.status) && safeString(state.status) !== 'idle');
}

function chatRobotWorldRectIsRenderable(rect) {
    return Boolean(
        rect
        && Number.isFinite(rect.top)
        && Number.isFinite(rect.bottom)
        && Number.isFinite(rect.left)
        && Number.isFinite(rect.right)
        && Number.isFinite(rect.width)
        && Number.isFinite(rect.height)
        && rect.width > 2
        && rect.height > 2
    );
}

function chatRobotWorldRectWithin(rect, containerRect, slack = 48) {
    if (!chatRobotWorldRectIsRenderable(rect)) return false;
    if (!chatRobotWorldRectIsRenderable(containerRect)) return true;
    return (
        rect.top >= (containerRect.top - slack)
        && rect.bottom <= (containerRect.bottom + slack)
        && rect.left >= (containerRect.left - slack)
        && rect.right <= (containerRect.right + slack)
    );
}

function chatRobotWorldClamp(n, min, max) {
    return Math.min(max, Math.max(min, n));
}

function chatRobotWorldBounds() {
    const mainRect = mainContent instanceof HTMLElement
        ? mainContent.getBoundingClientRect()
        : { left: 0, right: window.innerWidth, width: window.innerWidth, top: 0 };
    const rawComposerRect = composerContainer instanceof HTMLElement
        ? composerContainer.getBoundingClientRect()
        : null;
    const composerRect = chatRobotWorldRectIsRenderable(rawComposerRect) ? rawComposerRect : null;
    const rawInputRowRect = composerContainer instanceof HTMLElement
        ? composerContainer.querySelector('.composer-input-row')?.getBoundingClientRect?.()
        : null;
    const inputRowRect = chatRobotWorldRectWithin(rawInputRowRect, composerRect, 32) ? rawInputRowRect : null;
    const rawStatusBarRect = composerStatusBar instanceof HTMLElement
        ? composerStatusBar.getBoundingClientRect()
        : null;
    const statusBarRect = chatRobotWorldRectWithin(rawStatusBarRect, composerRect, 20) ? rawStatusBarRect : null;
    const rawSuggestionRect = (assistantSuggestionRail instanceof HTMLElement && !assistantSuggestionRail.classList.contains('hidden'))
        ? assistantSuggestionRail.getBoundingClientRect()
        : null;
    const suggestionRect = chatRobotWorldRectWithin(rawSuggestionRect, composerRect, 64) ? rawSuggestionRect : null;
    const width = Math.max(220, Math.round((mainRect.width || window.innerWidth) - (CHAT_PRIMARY_ROBOT_WORLD_PADDING_X * 2)));
    const left = Math.round((mainRect.left || 0) + CHAT_PRIMARY_ROBOT_WORLD_PADDING_X);
    const anchorTop = Math.min(
        suggestionRect ? suggestionRect.top : Number.POSITIVE_INFINITY,
        composerRect ? composerRect.top : Number.POSITIVE_INFINITY,
    );
    const top = Number.isFinite(anchorTop)
        ? Math.round(Math.max(72, anchorTop - 124))
        : Math.round(Math.max(72, window.innerHeight - CHAT_PRIMARY_ROBOT_WORLD_HEIGHT - 34));
    const bottom = composerRect
        ? Math.round(Math.min(window.innerHeight - 8, composerRect.bottom + 14))
        : Math.round(Math.min(window.innerHeight - 8, top + CHAT_PRIMARY_ROBOT_WORLD_HEIGHT));
    const height = Math.max(CHAT_PRIMARY_ROBOT_WORLD_HEIGHT, bottom - top);
    const composerTopLineY = composerRect
        ? Math.round(composerRect.top - top)
        : Number.NaN;
    const inputRowTopLineY = inputRowRect
        ? Math.round(inputRowRect.top - top)
        : Number.NaN;
    const statusBarTopLineY = statusBarRect
        ? Math.round(statusBarRect.top - top)
        : Number.NaN;
    const preferredFloorLineY = Number.isFinite(inputRowTopLineY)
        ? inputRowTopLineY
        : (Number.isFinite(statusBarTopLineY) ? statusBarTopLineY : composerTopLineY);
    const fallbackFloorLineY = Number.isFinite(preferredFloorLineY)
        ? preferredFloorLineY
        : (inputRowRect
            ? Math.round(inputRowRect.bottom - top)
            : Math.round(height - CHAT_PRIMARY_ROBOT_GROUND_OFFSET));
    const rawFloorLineY = Number.isFinite(preferredFloorLineY)
        ? preferredFloorLineY
        : (inputRowRect
            ? Math.round(inputRowRect.bottom - top)
            : Math.round(height - CHAT_PRIMARY_ROBOT_GROUND_OFFSET));
    const floorLineY = chatRobotWorldClamp(
        Number.isFinite(rawFloorLineY) ? rawFloorLineY : fallbackFloorLineY,
        24,
        Math.max(28, height - 6),
    );
    return {
        left,
        top,
        width,
        height,
        floorLineY,
        groundY: chatRobotWorldClamp(
            floorLineY - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
            0,
            Math.max(0, height - CHAT_PRIMARY_ROBOT_ACTOR_HEIGHT),
        ),
    };
}

function chatRobotWorldGeometry(bounds = chatRobotWorldBounds()) {
    const rawComposerBoxRect = composerBox instanceof HTMLElement
        ? composerBox.getBoundingClientRect()
        : null;
    const composerBoxRect = chatRobotWorldRectIsRenderable(rawComposerBoxRect) ? rawComposerBoxRect : null;
    const rawComposerRect = composerContainer instanceof HTMLElement
        ? composerContainer.getBoundingClientRect()
        : null;
    const composerRect = chatRobotWorldRectIsRenderable(rawComposerRect) ? rawComposerRect : composerBoxRect;
    const rawInputRowRect = composerContainer instanceof HTMLElement
        ? composerContainer.querySelector('.composer-input-row')?.getBoundingClientRect?.()
        : null;
    const inputRowRect = chatRobotWorldRectWithin(rawInputRowRect, composerRect, 32) ? rawInputRowRect : null;
    const rawStatusBarRect = composerStatusBar instanceof HTMLElement
        ? composerStatusBar.getBoundingClientRect()
        : null;
    const statusBarRect = chatRobotWorldRectWithin(rawStatusBarRect, composerRect, 20) ? rawStatusBarRect : null;
    const rawSuggestionRect = (assistantSuggestionRail instanceof HTMLElement && !assistantSuggestionRail.classList.contains('hidden'))
        ? assistantSuggestionRail.getBoundingClientRect()
        : null;
    const suggestionRect = chatRobotWorldRectWithin(rawSuggestionRect, composerRect, 64) ? rawSuggestionRect : null;
    const clampWorldY = (value, fallback, min = 0, max = bounds.height) => chatRobotWorldClamp(
        Number.isFinite(value) ? Math.round(value) : Math.round(fallback),
        min,
        Math.max(min, max),
    );
    const composerBlock = composerBoxRect
        ? {
            id: 'composer-block',
            x1: Math.max(18, Math.round(composerBoxRect.left - bounds.left + 6)),
            x2: Math.min(bounds.width - 18, Math.round(composerBoxRect.right - bounds.left - 6)),
            topY: clampWorldY(composerBoxRect.top - bounds.top, bounds.floorLineY - 96, 18, Math.max(24, bounds.height - 44)),
            bottomY: clampWorldY(composerBoxRect.bottom - bounds.top, bounds.floorLineY - 12, 24, Math.max(28, bounds.height - 8)),
        }
        : null;
    const floorY = clampWorldY(bounds.floorLineY, bounds.floorLineY, 24, Math.max(28, bounds.height - 6));
    const roofY = composerBoxRect
        ? clampWorldY(composerBoxRect.top - bounds.top, floorY - 46, 18, Math.max(24, floorY - 8))
        : Math.max(18, floorY - 46);
    const suggestionTopY = suggestionRect
        ? clampWorldY(suggestionRect.top - bounds.top, roofY - 32, 18, Math.max(24, floorY - 12))
        : 0;
    const tunnelInset = 22;
    return {
        baseFloor: {
            id: 'base-floor',
            x1: 12,
            x2: bounds.width - 12,
            y: floorY,
        },
        floorY,
        roofY,
        composerBlock,
        wall: composerBlock,
        suggestionBox: suggestionRect
            ? {
                id: 'suggestion-box',
                x1: Math.max(12, Math.round(suggestionRect.left - bounds.left)),
                x2: Math.min(bounds.width - 12, Math.round(suggestionRect.right - bounds.left)),
                topY: suggestionTopY,
                bottomY: clampWorldY(suggestionRect.bottom - bounds.top, suggestionTopY + 42, suggestionTopY + 8, Math.max(suggestionTopY + 12, floorY - 4)),
            }
            : null,
        backgroundTunnel: composerBlock
            ? {
                id: 'background-tunnel',
                leftDoorX: Math.max(20, composerBlock.x1 - tunnelInset),
                rightDoorX: Math.min(bounds.width - 20, composerBlock.x2 + tunnelInset),
                y: chatRobotWorldClamp(
                    floorY - CHAT_PRIMARY_ROBOT_FOOT_OFFSET,
                    0,
                    Math.max(0, bounds.height - CHAT_PRIMARY_ROBOT_ACTOR_HEIGHT),
                ),
            }
            : null,
        tunnel: composerBlock
            ? {
                leftDoorX: Math.max(20, composerBlock.x1 - tunnelInset),
                rightDoorX: Math.min(bounds.width - 20, composerBlock.x2 + tunnelInset),
            }
            : null,
    };
}

function chatRobotWorldMotionProfile(fidelityRaw) {
    const fidelity = normalizeAnimationFidelity(fidelityRaw, animationFidelityFromInterfacePrefs(currentPreferences?.advanced?.interface || {}));
    if (fidelity === ANIMATION_FIDELITY_MINIMAL) {
        return { fidelity, walkSpeed: 0.06, actionMinMs: 7600, actionMaxMs: 12_400, helperSpeedScale: 0.84 };
    }
    if (fidelity === ANIMATION_FIDELITY_BALANCED) {
        return { fidelity, walkSpeed: 0.085, actionMinMs: 7200, actionMaxMs: 11_600, helperSpeedScale: 0.9 };
    }
    return { fidelity, walkSpeed: 0.11, actionMinMs: 6800, actionMaxMs: 10_800, helperSpeedScale: 0.94 };
}

function chatRobotWorldPrimaryUsesGroundedPhysics(state) {
    return chatWorldIsPhysicsMode()
        && !chatRobotWorldTaskIsLive(state)
        && safeString(state?.kind) === 'primary';
}

function chatRobotWorldHelperSlot(state, platformGraph, platforms) {
    const ordinal = Math.max(0, Number(state?.spawnOrdinal || 0));
    const patterns = [
        { floorId: 'floor-left', pct: 0.18 },
        { floorId: 'floor-right', pct: 0.2 },
        { floorId: 'floor-right', pct: 0.76 },
        { floorId: 'floor-left', pct: 0.74 },
    ];
    const pattern = patterns[ordinal % patterns.length];
    const platform = platformGraph.platformsById?.get(pattern.floorId)
        || platforms.find((candidate) => safeString(candidate.id) === pattern.floorId)
        || platforms.find((candidate) => safeString(candidate.kind) === 'floor')
        || null;
    if (!platform) return null;
    const minX = Number(platform.x1 || 0) + 6;
    const maxX = Number(platform.x2 || 0) - 6;
    return {
        platform,
        homeX: chatRobotWorldClamp(minX + ((maxX - minX) * Number(pattern.pct || 0.5)), minX, maxX),
    };
}

function chatRobotWorldAddPlatformEdge(edges, fromId, toId, meta = {}) {
    if (!fromId || !toId || fromId === toId) return;
    if (!edges.has(fromId)) edges.set(fromId, []);
    if (!edges.has(toId)) edges.set(toId, []);
    edges.get(fromId).push({ to: toId, ...meta });
    edges.get(toId).push({ to: fromId, ...meta });
}

function chatRobotWorldBuildPlatformGraph(bounds = chatRobotWorldBounds(), fidelityRaw = animationFidelityFromInterfacePrefs(currentPreferences?.advanced?.interface || {})) {
    const fidelity = normalizeAnimationFidelity(fidelityRaw, ANIMATION_FIDELITY_HIGH);
    const geometry = chatRobotWorldGeometry(bounds);
    const platforms = [];
    const edges = new Map();
    const pushPlatform = (platform) => {
        if (!platform || !Number.isFinite(platform.x1) || !Number.isFinite(platform.x2) || platform.x2 - platform.x1 < 28) return;
        platforms.push(platform);
    };
    if (geometry.composerBlock) {
        pushPlatform({ id: 'floor-left', kind: 'floor', x1: geometry.baseFloor.x1, x2: geometry.composerBlock.x1 - 10, y: geometry.floorY });
        pushPlatform({ id: 'floor-right', kind: 'floor', x1: geometry.composerBlock.x2 + 10, x2: geometry.baseFloor.x2, y: geometry.floorY });
        pushPlatform({ id: 'composer-roof', kind: 'roof', x1: geometry.composerBlock.x1 + 12, x2: geometry.composerBlock.x2 - 12, y: geometry.roofY });
    } else {
        pushPlatform({ id: 'floor-main', kind: 'floor', x1: geometry.baseFloor.x1, x2: geometry.baseFloor.x2, y: geometry.floorY });
    }
    if (geometry.suggestionBox && fidelity !== ANIMATION_FIDELITY_MINIMAL) {
        pushPlatform({
            id: 'suggestion-top',
            kind: 'suggestion',
            x1: geometry.suggestionBox.x1 + 10,
            x2: geometry.suggestionBox.x2 - 10,
            y: geometry.suggestionBox.topY,
        });
    }
    if (composerContainer instanceof HTMLElement && fidelity === ANIMATION_FIDELITY_HIGH) {
        const platformEls = composerContainer.querySelectorAll('#attachBtn, #micBtn, #sendBtn, .composer-mode-chip, .assistant-suggestion-bubbles > *, .assistant-suggestion-head');
        platformEls.forEach((el, index) => {
            if (!(el instanceof HTMLElement) || !el.offsetParent) return;
            const rect = el.getBoundingClientRect();
            const x1 = Math.max(12, Math.round(rect.left - bounds.left));
            const x2 = Math.min(bounds.width - 12, Math.round(rect.right - bounds.left));
            const y = Math.round(rect.top - bounds.top);
            if (x2 - x1 < 28 || y < 12 || y > bounds.height - 10) return;
            pushPlatform({ id: `ui-${index}`, kind: 'ui', x1, x2, y });
        });
    }
    const dedupedPlatforms = platforms
        .filter((platform, index, list) => !list.some((other, otherIndex) => (
            otherIndex < index
            && Math.abs(other.y - platform.y) <= 2
            && Math.abs(other.x1 - platform.x1) <= 4
            && Math.abs(other.x2 - platform.x2) <= 4
        )))
        .sort((a, b) => a.y - b.y);
    const platformsById = new Map(dedupedPlatforms.map((platform) => [platform.id, platform]));
    const floorIds = dedupedPlatforms.filter((platform) => platform.kind === 'floor').map((platform) => platform.id);
    const roofIds = dedupedPlatforms.filter((platform) => platform.kind === 'roof').map((platform) => platform.id);
    const upperIds = dedupedPlatforms
        .filter((platform) => platform.kind === 'roof' || platform.kind === 'suggestion' || platform.kind === 'ui')
        .map((platform) => platform.id);

    if (floorIds.length === 2 && geometry.backgroundTunnel) {
        chatRobotWorldAddPlatformEdge(edges, floorIds[0], floorIds[1], { kind: 'tunnel', routeKind: 'door' });
    }
    if (floorIds.length >= 1 && roofIds.length >= 1) {
        floorIds.forEach((floorId) => {
            roofIds.forEach((roofId) => {
                chatRobotWorldAddPlatformEdge(edges, floorId, roofId, {
                    kind: 'climb',
                    routeKind: chatRobotWorldTransitionKindForFidelity(fidelity),
                });
            });
        });
    }
    if (upperIds.length >= 2) {
        for (let i = 0; i < upperIds.length; i += 1) {
            for (let j = i + 1; j < upperIds.length; j += 1) {
                const a = platformsById.get(upperIds[i]);
                const b = platformsById.get(upperIds[j]);
                if (!a || !b) continue;
                const overlapsX = !(a.x2 < b.x1 || b.x2 < a.x1);
                const nearY = Math.abs(a.y - b.y) <= 22;
                if (overlapsX || nearY) {
                    chatRobotWorldAddPlatformEdge(edges, a.id, b.id, {
                        kind: 'climb',
                        routeKind: chatRobotWorldTransitionKindForFidelity(fidelity),
                    });
                }
            }
        }
    }
    upperIds.forEach((upperId) => {
        floorIds.forEach((floorId) => {
            chatRobotWorldAddPlatformEdge(edges, floorId, upperId, {
                kind: 'climb',
                routeKind: chatRobotWorldTransitionKindForFidelity(fidelity),
            });
        });
    });
    return {
        fidelity,
        bounds,
        geometry,
        platforms: dedupedPlatforms,
        platformsById,
        edges,
    };
}

function chatRobotWorldPlatforms(bounds = chatRobotWorldBounds(), fidelityRaw = animationFidelityFromInterfacePrefs(currentPreferences?.advanced?.interface || {})) {
    return chatRobotWorldBuildPlatformGraph(bounds, fidelityRaw).platforms;
}

function chatWorldCurrentMode(interfacePrefs = currentPreferences?.advanced?.interface || {}) {
    return chatWorldModeFromInterfacePrefs(interfacePrefs);
}

function chatRobotWorldStage() {
    const root = chatWorldEnsureUi();
    if (!(root instanceof HTMLElement)) return null;
    return root.querySelector('[data-role="stage"]');
}

function chatRobotWorldPhysicsLayer() {
    const root = chatWorldEnsureUi();
    if (!(root instanceof HTMLElement)) return null;
    return root.querySelector('[data-role="physics"]');
}

function chatWorldIsPhysicsMode(interfacePrefs = currentPreferences?.advanced?.interface || {}) {
    return chatWorldCurrentMode(interfacePrefs) === CHAT_WORLD_MODE_PHYSICS;
}

function chatPhysicsWorldActorMetrics(state) {
    return safeString(state?.kind) === 'delegation'
        ? {
            width: 18,
            height: 28,
            centerOffsetX: 23,
            centerOffsetY: 28,
        }
        : {
            width: 20,
            height: 30,
            centerOffsetX: 23,
            centerOffsetY: 28,
        };
}

function chatPhysicsColorToInt(colorRaw, fallback = 0x9ad8ff) {
    const color = safeString(colorRaw).trim();
    if (!color) return fallback;
    const normalized = color.startsWith('#') ? color.slice(1) : color;
    if (!/^[0-9a-f]{6}$/i.test(normalized)) return fallback;
    return Number.parseInt(normalized, 16);
}

function chatPhysicsWorldStateSignature(bounds, graph) {
    return JSON.stringify({
        width: Math.round(Number(bounds?.width || 0)),
        height: Math.round(Number(bounds?.height || 0)),
        floorLineY: Math.round(Number(bounds?.floorLineY || 0)),
        groundY: Math.round(Number(bounds?.groundY || 0)),
        geometry: graph?.geometry || null,
        platforms: Array.isArray(graph?.platforms)
            ? graph.platforms.map((platform) => ({
                id: safeString(platform?.id),
                kind: safeString(platform?.kind),
                x1: Math.round(Number(platform?.x1 || 0)),
                x2: Math.round(Number(platform?.x2 || 0)),
                y: Math.round(Number(platform?.y || 0)),
            }))
            : [],
    });
}

function chatPhysicsWorldBodyCenterFromState(state) {
    const metrics = chatPhysicsWorldActorMetrics(state);
    return {
        x: Number(state?.x || 0) + metrics.centerOffsetX,
        y: Number(state?.y || 0) + metrics.centerOffsetY,
    };
}

function chatPhysicsWorldSyncStateFromBody(state, actorRecord, bounds = chatRobotWorldBounds()) {
    const body = actorRecord?.body;
    const node = actorRecord?.node;
    if (!state || !body || !node) return;
    const metrics = actorRecord.metrics || chatPhysicsWorldActorMetrics(state);
    const bodyCenterX = Number(node.x || 0);
    const bodyCenterY = Number(node.y || 0);
    state.x = chatRobotWorldClamp(
        bodyCenterX - metrics.centerOffsetX,
        0,
        Math.max(0, Number(bounds?.width || 0) - 18),
    );
    state.y = chatRobotWorldClamp(
        bodyCenterY - metrics.centerOffsetY,
        0,
        Math.max(0, Number(bounds?.height || 0) - CHAT_PRIMARY_ROBOT_ACTOR_HEIGHT),
    );
}

function chatPhysicsWorldSyncBodyFromState(state, actorRecord) {
    const body = actorRecord?.body;
    const node = actorRecord?.node;
    if (!state || !body || !node) return;
    const center = chatPhysicsWorldBodyCenterFromState(state);
    node.setPosition(center.x, center.y);
    body.reset(center.x, center.y);
    body.setVelocity(0, 0);
}

function chatPhysicsWorldSetActorGravity(actorRecord, enabled) {
    const body = actorRecord?.body;
    if (!body) return;
    body.setAllowGravity(Boolean(enabled));
    if (!enabled) body.setVelocityY(0);
}

function chatPhysicsWorldClearStaticBodies(worldState) {
    const bodies = Array.isArray(worldState?.staticBodies) ? worldState.staticBodies : [];
    bodies.forEach((entry) => {
        try {
            entry?.body?.destroy?.();
        } catch (_) {}
        try {
            entry?.node?.destroy?.();
        } catch (_) {}
    });
    if (worldState) worldState.staticBodies = [];
}

function chatPhysicsWorldEnsureVisualLayer(worldState) {
    const scene = worldState?.scene;
    if (!scene) return null;
    if (worldState.visualLayer?.graphics?.active) return worldState.visualLayer;
    const graphics = scene.add.graphics();
    graphics.setDepth(30);
    worldState.visualLayer = { graphics };
    return worldState.visualLayer;
}

function chatPhysicsWorldDrawTraversalProp(graphics, placement) {
    void graphics;
    void placement;
}

function chatPhysicsWorldRenderVisualLayer(worldState, bounds, graph, actors = []) {
    const visualLayer = chatPhysicsWorldEnsureVisualLayer(worldState);
    const graphics = visualLayer?.graphics;
    if (!graphics) return;
    graphics.clear();
    void bounds;
    void graph;
    void actors;
}

function chatPhysicsWorldAddStaticRect(worldState, id, left, top, width, height) {
    const scene = worldState?.scene;
    if (!scene || !scene.physics) return null;
    const safeWidth = Math.max(4, Math.round(width));
    const safeHeight = Math.max(4, Math.round(height));
    const node = scene.add.rectangle(
        Math.round(left + (safeWidth * 0.5)),
        Math.round(top + (safeHeight * 0.5)),
        safeWidth,
        safeHeight,
        0x9bd8ff,
        0.001,
    );
    node.setVisible(false);
    scene.physics.add.existing(node, true);
    const body = node.body;
    const entry = { id: safeString(id), node, body };
    worldState.staticBodies.push(entry);
    return entry;
}

function chatPhysicsWorldRefreshActorColliders(worldState, actorRecord) {
    if (!worldState?.scene || !actorRecord?.node) return;
    actorRecord.colliders = Array.isArray(actorRecord.colliders) ? actorRecord.colliders : [];
    actorRecord.colliders.forEach((collider) => {
        try { collider?.destroy?.(); } catch (_) {}
    });
    actorRecord.colliders = [];
    (worldState.staticBodies || []).forEach((entry) => {
        const collider = worldState.scene.physics.add.collider(actorRecord.node, entry.node);
        actorRecord.colliders.push(collider);
    });
}

function chatPhysicsWorldDestroyActorVisual(actorRecord) {
    const visual = actorRecord?.visual;
    if (!visual) return;
    try { visual.root?.destroy?.(); } catch (_) {}
    actorRecord.visual = null;
}

function chatPhysicsWorldEnsureActorVisual(worldState, state, actorRecord) {
    void worldState;
    void state;
    if (actorRecord?.visual) {
        chatPhysicsWorldDestroyActorVisual(actorRecord);
    }
    return null;
}

function chatPhysicsWorldRenderActorVisual(state, actorRecord) {
    void state;
    if (actorRecord?.visual) {
        chatPhysicsWorldDestroyActorVisual(actorRecord);
    }
}

function chatPhysicsWorldRebuildStatics(worldState, bounds, graph) {
    if (!worldState?.scene?.physics) return;
    const scene = worldState.scene;
    const geometry = graph?.geometry || chatRobotWorldGeometry(bounds);
    const platforms = Array.isArray(graph?.platforms) ? graph.platforms : [];
    scene.physics.world.setBounds(0, 0, Math.max(220, Number(bounds?.width || 0)), Math.max(140, Number(bounds?.height || 0)));
    chatPhysicsWorldClearStaticBodies(worldState);
    chatPhysicsWorldAddStaticRect(
        worldState,
        'floor',
        Number(geometry?.baseFloor?.x1 || 0),
        Number(geometry?.floorY || bounds?.floorLineY || 0),
        Math.max(24, Number(geometry?.baseFloor?.x2 || bounds?.width || 0) - Number(geometry?.baseFloor?.x1 || 0)),
        8,
    );
    if (geometry?.composerBlock) {
        chatPhysicsWorldAddStaticRect(
            worldState,
            'composer-block',
            Number(geometry.composerBlock.x1 || 0),
            Number(geometry.composerBlock.topY || 0),
            Math.max(24, Number(geometry.composerBlock.x2 || 0) - Number(geometry.composerBlock.x1 || 0)),
            Math.max(24, Number(geometry.composerBlock.bottomY || 0) - Number(geometry.composerBlock.topY || 0)),
        );
    }
    if (geometry?.suggestionBox) {
        const suggestionWidth = Math.max(24, Number(geometry.suggestionBox.x2 || 0) - Number(geometry.suggestionBox.x1 || 0));
        const suggestionHeight = Math.max(14, Number(geometry.suggestionBox.bottomY || 0) - Number(geometry.suggestionBox.topY || 0));
        const wallThickness = 8;
        chatPhysicsWorldAddStaticRect(
            worldState,
            'suggestion-ceiling',
            Number(geometry.suggestionBox.x1 || 0),
            Number(geometry.suggestionBox.topY || 0),
            suggestionWidth,
            wallThickness,
        );
        chatPhysicsWorldAddStaticRect(
            worldState,
            'suggestion-wall-left',
            Number(geometry.suggestionBox.x1 || 0),
            Number(geometry.suggestionBox.topY || 0),
            wallThickness,
            suggestionHeight,
        );
        chatPhysicsWorldAddStaticRect(
            worldState,
            'suggestion-wall-right',
            Number(geometry.suggestionBox.x2 || 0) - wallThickness,
            Number(geometry.suggestionBox.topY || 0),
            wallThickness,
            suggestionHeight,
        );
    }
    platforms
        .filter((platform) => new Set(['roof', 'ui', 'suggestion']).has(safeString(platform?.kind)))
        .forEach((platform) => {
            chatPhysicsWorldAddStaticRect(
                worldState,
                `platform-${safeString(platform.id)}`,
                Number(platform.x1 || 0),
                Number(platform.y || 0),
                Math.max(18, Number(platform.x2 || 0) - Number(platform.x1 || 0)),
                8,
            );
        });
    (worldState.actorBodies || new Map()).forEach((actorRecord) => {
        chatPhysicsWorldRefreshActorColliders(worldState, actorRecord);
    });
}

function chatPhysicsWorldRemoveActor(worldState, activityId) {
    const key = safeString(activityId);
    if (!worldState?.actorBodies?.has(key)) return;
    const record = worldState.actorBodies.get(key);
    chatPhysicsWorldDestroyActorVisual(record);
    (record?.colliders || []).forEach((collider) => {
        try { collider?.destroy?.(); } catch (_) {}
    });
    try { record?.body?.destroy?.(); } catch (_) {}
    try { record?.node?.destroy?.(); } catch (_) {}
    worldState.actorBodies.delete(key);
}

function chatPhysicsWorldEnsureActor(worldState, state) {
    if (!worldState?.scene?.physics || !state) return null;
    const key = safeString(state.activityId);
    if (!key) return null;
    let actorRecord = worldState.actorBodies.get(key);
    const center = chatPhysicsWorldBodyCenterFromState(state);
    if (!actorRecord) {
        const metrics = chatPhysicsWorldActorMetrics(state);
        const node = worldState.scene.add.rectangle(
            center.x,
            center.y,
            metrics.width,
            metrics.height,
            0xffffff,
            0.001,
        );
        node.setVisible(false);
        worldState.scene.physics.add.existing(node, false);
        const body = node.body;
        body.setCollideWorldBounds(true);
        body.setDragX(2600);
        body.setMaxVelocity(108, 860);
        actorRecord = {
            activityId: key,
            node,
            body,
            colliders: [],
            metrics,
        };
        worldState.actorBodies.set(key, actorRecord);
        chatPhysicsWorldRefreshActorColliders(worldState, actorRecord);
    } else {
        actorRecord.metrics = chatPhysicsWorldActorMetrics(state);
    }
    if (Math.abs(Number(actorRecord.node.x || 0) - center.x) > 48 || Math.abs(Number(actorRecord.node.y || 0) - center.y) > 56) {
        chatPhysicsWorldSyncBodyFromState(state, actorRecord);
    }
    actorRecord.node.body.setSize(actorRecord.metrics.width, actorRecord.metrics.height, true);
    chatPhysicsWorldEnsureActorVisual(worldState, state, actorRecord);
    return actorRecord;
}

function chatPhysicsWorldStablePlatformForState(state, graph = null) {
    const platformGraph = graph || chatPhysicsWorldState?.graph || null;
    const platformsById = platformGraph?.platformsById instanceof Map ? platformGraph.platformsById : new Map();
    const livePlatforms = Array.isArray(platformGraph?.platforms) ? platformGraph.platforms : [];
    const currentPlatformId = safeString(state?.currentPlatformId);
    const targetPlatformId = safeString(state?.targetPlatformId);
    const preferredX = Number.isFinite(Number(state?.targetX)) ? Number(state.targetX) : Number(state?.x || 0);
    const current = currentPlatformId ? platformsById.get(currentPlatformId) : null;
    if (current) return current;
    const target = targetPlatformId ? platformsById.get(targetPlatformId) : null;
    if (target) return target;
    const floorPlatforms = livePlatforms.filter((platform) => safeString(platform?.kind) === 'floor');
    const candidates = floorPlatforms.length ? floorPlatforms : livePlatforms;
    if (!candidates.length) return null;
    let best = candidates[0];
    let bestScore = Number.POSITIVE_INFINITY;
    candidates.forEach((platform) => {
        const x1 = Number(platform?.x1 || 0);
        const x2 = Number(platform?.x2 || x1);
        const centerX = (x1 + x2) * 0.5;
        const clampedX = chatRobotWorldClamp(preferredX, x1, x2);
        const score = Math.abs(clampedX - preferredX) + (Math.abs(centerX - preferredX) * 0.1);
        if (score < bestScore) {
            best = platform;
            bestScore = score;
        }
    });
    return best;
}

